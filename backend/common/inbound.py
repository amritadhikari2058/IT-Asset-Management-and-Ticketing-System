"""Inbound email ingestion: parse raw MIME messages into tickets/notes.

Receives messages from the organizational support mailbox (polled over
IMAP by the Celery ``process_inbound_mailbox`` task, or supplied directly
for tests / manual retries) and turns eligible messages into tickets or
ticket replies while guarding against duplicates.

Privacy / security rules enforced here:
- Only messages from recognized senders (known employee email or an
  explicitly allowed sender domain) are eligible for ticket creation.
- Internal IT notes never leave through email; inbound staff replies are
  stored as internal notes.
- Attachments go through the same policy as API uploads (extension
  whitelist, size cap, executable blocking) before touching storage.
- Malformed / unsupported messages are recorded as failed for safe retry.
"""
import logging
import os
import re
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from accounts.models import User
from common.models import EmailProcessing
from tickets.models import Ticket, TicketCategory, TicketNote

logger = logging.getLogger(__name__)

#: Ticket reference accepted in subjects, e.g. "Printer broken #42".
TICKET_REF_RE = re.compile(r"#(\d+)")


def _allowed_extensions():
    raw = getattr(settings, "ATTACHMENT_ALLOWED_EXTENSIONS", None) or \
        "pdf,png,jpg,jpeg,txt,csv,log,docx,xlsx"
    return [e.strip().lower() for e in str(raw).split(",")
            if e.strip()]


def _max_attachment_bytes():
    try:
        return max(0, float(getattr(settings, "ATTACHMENT_MAX_SIZE_MB", 10))) \
            * 1024 * 1024
    except (ValueError, TypeError):
        return 10 * 1024 * 1024


def build_inbound_message(msg, mailbox="support"):
    """Build the internal processing dict from a parsed email.Message."""
    from email.utils import getaddresses
    sender = ""
    for _n, addr in getaddresses(msg.get_all("From", []) or []):
        sender = (addr or "").strip().lower()
        if sender:
            break
    recipient = ""
    for _n, addr in getaddresses(msg.get_all("To", []) or []):
        recipient = (addr or "").strip().lower()
        if recipient:
            break
    return {
        "message_id": msg.get("Message-ID") or "",
        "sender": sender,
        "recipient": recipient,
        "subject": msg.get("Subject") or "",
        "body": _body_from_message(msg),
        "in_reply_to": msg.get("In-Reply-To") or "",
        "attachments": _attachments_from_message(msg),
        "mailbox": mailbox or "support",
    }


def _sender_email(msg):
    """Return the bare email address of the first From address."""
    from email.utils import getaddresses
    for _name, addr in getaddresses(msg.get_all("From", []) or []):
        addr = (addr or "").strip().lower()
        if addr:
            return addr
    return ""


def _recipient_email(msg, fallback=""):
    from email.utils import getaddresses
    for _name, addr in getaddresses(msg.get_all("To", []) or []):
        addr = (addr or "").strip().lower()
        if addr:
            return addr
    return (fallback or "").strip().lower()


def _body_from_message(msg):
    """Best-effort text body extraction from a parsed MIME message."""
    text_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            if not ctype.startswith("text/"):
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                payload = (part.get_payload() or "").encode()
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if ctype == "text/plain" and text.strip():
                text_parts.append(text.strip())
                break
        if text_parts:
            return "\n\n".join(text_parts)
    payload = msg.get_payload(decode=True)
    if payload is None:
        payload = (msg.get_payload() or "").encode()
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _attachments_from_message(msg):
    """Return list of {'filename','content_type','data'} for real parts."""
    out = []
    if not msg.is_multipart():
        return out
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename() or part.get_param("filename") or ""
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            payload = b""
        out.append({
            "filename": filename,
            "content_type": part.get_content_type(),
            "data": payload,
        })
    return out


def validate_inbound_attachment(filename, content_type, data):
    """Apply the same policy as API ticket/asset uploads.

    Returns (ok, error_message).
    """
    name = (filename or "").strip()
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    allowed = _allowed_extensions()
    if ext and ext not in allowed:
        return False, (f"Extension '.{ext}' not allowed. Allowed: {allowed}")
    max_bytes = _max_attachment_bytes()
    if len(data or b"") > max_bytes:
        return False, (f"File too large ({len(data or b'')} bytes). "
                       f"Limit: {max_bytes:.0f} bytes.")
    ctype = (content_type or "").lower()
    if ctype.startswith(("application/x-ms", "application/x-sh",
                         "application/x-executable")) or \
            ext in ("exe", "bat", "cmd", "sh", "ps1", "msi"):
        return False, "Executable files are blocked."
    return True, None


def _find_user_by_email(email):
    if not email:
        return None
    return User.objects.filter(email__iexact=email).first()


def _allowed_sender_domain(sender_email):
    domains = [d.strip().lower() for d in
               (getattr(settings, "INBOUND_ALLOWED_SENDER_DOMAINS", None) or "")
               .split(",") if d.strip()]
    if not domains:
        return False
    domain = (sender_email or "").split("@")[-1]
    return domain in domains


def _wants_ticket_email(user):
    return bool(getattr(user, "receive_ticket_emails", True))


def _ensure_requester_account(sender_email):
    """Minimal employee record for a sender without a portal account."""
    from django.contrib.auth import get_user_model
    U = get_user_model()
    user, _created = U.objects.get_or_create(
        email=sender_email,
        defaults={
            "username": sender_email,
            "role": "employee",
            "employee_id": sender_email.split("@")[0].upper(),
            "can_create_tickets": True,
            "receive_ticket_emails": True,
        })
    return user


def _resolve_reply_ticket(in_reply_to, subject):
    """Find a ticket referenced by In-Reply-To / subject for a reply."""
    from tickets.models import Ticket
    ref = ""
    for candidate in (in_reply_to or "", subject or ""):
        m = TICKET_REF_RE.search(candidate)
        if m:
            ref = m.group(1)
            break
    if not ref:
        return None
    try:
        return Ticket.objects.select_related(
            "category", "requester", "assignee", "department"
        ).get(pk=int(ref))
    except (ValueError, Ticket.DoesNotExist, TypeError):
        return None


def _save_attachment(ticket, att):
    """Persist a validated inbound attachment onto a ticket."""
    from tickets.models import TicketAttachment
    filename = (att.get("filename") or "").strip()
    data = att.get("data") or b""
    ext = os.path.splitext(filename)[1].lower().lstrip(".") \
        if filename else ""
    name = f"ticket_attachments/{uuid.uuid4().hex}" + \
        (f".{ext[:10]}" if ext else "")
    attachment = TicketAttachment(
        ticket=ticket, file=ContentFile(data, name=name),
        original_filename=filename[:255])
    attachment.save()
    return attachment


def _process_message(msg_dict, mailbox):
    """Core: turn one parsed inbound message into ticket activity.

    Returns (ticket, created, error_message).
    """
    msg_id = msg_dict.get("message_id") or ""
    if not msg_id:
        return None, False, "No Message-ID header"

    sender_email = (msg_dict.get("sender") or "").strip().lower()
    subject = msg_dict.get("subject") or ""
    body = msg_dict.get("body") or ""

    existing = EmailProcessing.objects.filter(message_id=msg_id).first()
    if existing is not None and existing.status == "processed" \
            and existing.ticket_id:
        return existing.ticket, False, None
    if existing is not None and existing.status != "processed":
        # Failed (or dangling) rows become pending again so retries work.
        EmailProcessing.objects.filter(pk=existing.pk).update(
            status="pending", error_details="", ticket=None,
            processed_at=None)

    sender_user = _find_user_by_email(sender_email)
    eligible = bool(sender_user) or bool(
        _allowed_sender_domain(sender_email))

    if not eligible:
        EmailProcessing.objects.update_or_create(
            message_id=msg_id,
            defaults={
                "mailbox": mailbox,
                "recipient": msg_dict.get("recipient") or "",
                "sender": sender_email,
                "subject": subject,
                "body_preview": body[:200],
                "status": "failed",
                "error_details": "Sender not recognized by the support mailbox.",
                "ticket": None, "processed_at": None,
            })
        return None, False, "Sender not recognized by the support mailbox."

    in_reply_to = msg_dict.get("in_reply_to") or ""
    ticket = None
    if in_reply_to or TICKET_REF_RE.search(subject or ""):
        ticket = _resolve_reply_ticket(in_reply_to, subject)

    attachments = msg_dict.get("attachments") or []
    valid_attachments = []
    attach_error = None
    for att in attachments:
        ok, err = validate_inbound_attachment(
            att.get("filename"), att.get("content_type"),
            att.get("data") or b"")
        if not ok:
            attach_error = err
            break
        valid_attachments.append(att)
    if attach_error is not None:
        EmailProcessing.objects.update_or_create(
            message_id=msg_id,
            defaults={
                "mailbox": mailbox,
                "recipient": msg_dict.get("recipient") or "",
                "sender": sender_email,
                "subject": subject,
                "body_preview": body[:200],
                "status": "failed",
                "error_details": f"Unsupported attachment: {attach_error}",
                "ticket": None, "processed_at": None,
            })
        return None, False, attach_error

    created = False
    is_internal = False
    if ticket is None:
        # New ticket from an eligible sender.
        user = sender_user or _ensure_requester_account(sender_email)
        category, _cat_created = TicketCategory.objects.get_or_create(
            name="General", defaults={"is_active": True})
        ticket = Ticket.objects.create(
            title=(subject or "").strip()[:255] or "Email-generated ticket",
            description=body or "",
            category=category,
            priority="medium",
            status="open",
            requester=user,
        )
        created = True
        is_internal = False
        # Creation confirmation to the requester (honors their preference).
        if user.email and _wants_ticket_email(user):
            from accounts import email_utils as _eu
            _eu.send_ticket_notification(
                user.email,
                f"Ticket #{ticket.pk} created: {ticket.title}",
                f"Your ticket was created.\nStatus: {ticket.status}\n"
                f"View: {_eu.ticket_links(ticket.pk)[1]}",
                ticket_id=ticket.pk)
    else:
        # Reply: staff replies are stored as internal notes (IT-only, never
        # emailed out); requester replies are stored as requester-visible
        # notes on the ticket.
        is_internal = bool(sender_user) and sender_user is not None and (
            sender_user.role in ("system_admin", "it_manager", "it_support")
            or sender_user.is_superuser)
        if sender_user is not None:
            TicketNote.objects.create(
                ticket=ticket, author=sender_user, body=body,
                is_internal=is_internal)

    # Persist processing state (idempotent by Message-ID).
    EmailProcessing.objects.update_or_create(
        message_id=msg_id,
        defaults={
            "mailbox": mailbox,
            "recipient": msg_dict.get("recipient") or "",
            "sender": sender_email,
            "subject": subject,
            "body_preview": body[:200],
            "status": "processed",
            "ticket": ticket,
            "processed_at": timezone.now(),
            "error_details": "",
        })

    if created:
        # Attachments ride along with the brand-new ticket.
        for att in valid_attachments:
            _save_attachment(ticket, att)

    if ticket is not None and not created and not is_internal:
        # Requester-visible reply: notify them (deduped outbound send).
        from accounts import email_utils as _eu
        _eu.send_ticket_notification(
            ticket.requester.email if ticket.requester else None,
            f"Re: {(subject or '')[:80]}",
            f"Reply received on ticket #{ticket.pk}: {(body or '')[:500]}",
            ticket_id=ticket.pk)

    return ticket, created, None


def process_inbound_email(msg_dict, mailbox="support"):
    """Process a single inbound email and create/attach a ticket.

    :param msg_dict: Dict with keys: message_id, sender, recipient, subject,
                    body (plus optional in_reply_to / attachments).
    :param mailbox: Name of the mailbox this email was received on.
    :returns: (ticket, created, error_message)
    """
    msg = dict(msg_dict or {})
    try:
        return _process_message(msg, mailbox or "support")
    except Exception as exc:  # one bad message must not kill the batch
        logger.exception("Failed to process inbound email %s",
                        msg.get("message_id") or "unknown")
        try:
            EmailProcessing.objects.update_or_create(
                message_id=msg.get("message_id") or "",
                defaults={
                    "mailbox": mailbox or "support",
                    "recipient": msg.get("recipient") or "",
                    "sender": msg.get("sender") or "",
                    "subject": msg.get("subject") or "",
                    "body_preview": (msg.get("body") or "")[:200],
                    "status": "failed",
                    "error_details": f"{type(exc).__name__}: "
                                      f"{(str(exc) or '')[:200]}",
                    "ticket": None, "processed_at": None,
                })
        except Exception:
            pass
        return None, False, f"{type(exc).__name__}: {(str(exc) or '')[:200]}"
