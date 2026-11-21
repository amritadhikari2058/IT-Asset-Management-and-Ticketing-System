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

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from common.models import EmailProcessing
from common.notifications import TICKET_REPLY_CATEGORY
from tickets.attachment_storage import delete_stored_file, store_upload
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
    """Return real attachment parts in deterministic MIME walk order.

    Each item includes ``part_index``: the stable 0-based ordinal among the
    extracted attachment parts for this parse of the message. The same raw
    message parsed again yields the same ordinals, so retries can recognize the
    same original MIME part without collapsing distinct parts that share a
    filename or content.
    """
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
            "part_index": len(out),
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


def _wants_ticket_email(user, category=None):
    """Centralized ticket-email preference gate (see common.notifications).

    - ``category`` selects the notification category (``ticket_reply`` for
      inbound replies); ``None`` applies the global master switch.
    - Missing preference records default to enabled.
    """
    from common.notifications import email_enabled_for
    return email_enabled_for(user, category=category)


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


def _save_attachment(ticket, att, source_message_id=None, source_part_index=None):
    """Persist a validated inbound attachment onto a ticket, idempotently.

    The file is written through the model's configured storage first so the
    exact stored object name is known, then the database row is created inside
    its own transaction. If the row cannot be written, exactly the object this
    call stored is removed again and the original exception is re-raised.

    Deduplication for inbound email parts is based on the stable source
    identity ``(source_message_id, source_part_index)``. The same MIME part
    retried is recognized and not duplicated; distinct parts remain distinct
    even when filenames and content are identical. A SHA-256 content hash is
    stored for integrity/diagnostics.

    For legacy rows saved before source identity existed, a conservative
    fallback matches a unique pre-identity row on the same ticket with the same
    filename and content hash to avoid duplicating partially-saved attachments
    after upgrade. Blank source identity is never treated as a safe dedup key.
    """
    import hashlib
    from django.db import IntegrityError, transaction as db_transaction
    from tickets.models import TicketAttachment

    filename = (att.get("filename") or "").strip()
    data = att.get("data") or b""
    content_hash = hashlib.sha256(data).hexdigest()

    msg_id = (source_message_id or "").strip()
    part_index = source_part_index
    has_source_identity = bool(msg_id) and part_index is not None

    if has_source_identity:
        existing = TicketAttachment.objects.filter(
            ticket=ticket,
            source_message_id=msg_id,
            source_part_index=part_index,
        ).first()
        if existing is not None:
            return existing

        # Conservative legacy fallback: only when exactly one pre-identity row
        # on this ticket matches filename+hash. Avoids duplicating a legacy
        # partial-save attachment while refusing to guess among multiple
        # candidates. Blank/default source identity is not used as the key.
        legacy = list(TicketAttachment.objects.filter(
            ticket=ticket,
            original_filename=filename[:255],
            content_hash=content_hash,
            source_message_id="",
            source_part_index__isnull=True,
        )[:2])
        if len(legacy) == 1:
            return legacy[0]
    else:
        # Non-source-identity callers (unexpected for inbound): preserve a
        # content-based best-effort dedup scoped to the ticket.
        existing = TicketAttachment.objects.filter(
            ticket=ticket, original_filename=filename[:255],
            content_hash=content_hash,
        ).first()
        if existing is not None:
            return existing

    stored_name = store_upload(
        TicketAttachment, ContentFile(data, name=filename or "attachment"))
    try:
        with db_transaction.atomic():
            attachment = TicketAttachment.objects.create(
                ticket=ticket,
                file=stored_name,
                original_filename=filename[:255],
                content_hash=content_hash,
                source_message_id=msg_id if has_source_identity else "",
                source_part_index=part_index if has_source_identity else None,
            )
    except IntegrityError:
        # Concurrent/retry race or recovery against a stale ticket: another row
        # owns the same source part identity. Remove only the object we just
        # stored and adopt the existing row.
        delete_stored_file(TicketAttachment, stored_name)
        if has_source_identity:
            existing = TicketAttachment.all_objects.filter(
                source_message_id=msg_id,
                source_part_index=part_index,
            ).first()
            if existing is not None:
                # If the source part already exists, associate it with the
                # authoritative ticket for this email when recovering from a
                # stale/deleted ticket reference.
                update_fields = []
                if existing.ticket_id != ticket.pk:
                    existing.ticket = ticket
                    update_fields.append("ticket")
                # Do not resurrect intentionally soft-deleted attachments except
                # as part of the same source part identity; keep state stable.
                if update_fields:
                    existing.save(update_fields=update_fields)
                return existing
        raise
    except Exception:
        # No row references ``stored_name``: the transaction (or its
        # savepoint) rolled back. Remove only that object, best effort, then
        # let the original exception surface unchanged.
        delete_stored_file(TicketAttachment, stored_name)
        raise
    return attachment


def _can_select_for_update():
    try:
        from django.db import connection
        return bool(getattr(connection.features, "has_select_for_update", False))
    except Exception:
        return False


def _lock_processing_record(msg_id):
    """Return the EmailProcessing row for ``msg_id`` locked for update when
    supported. Call inside a transaction.
    """
    qs = EmailProcessing.objects.filter(message_id=msg_id)
    if _can_select_for_update():
        qs = qs.select_for_update()
    return qs.first()


def _get_or_create_processing_record(msg_id, defaults):
    """Get or create the EmailProcessing row, tolerating concurrent inserts."""
    from django.db import IntegrityError, transaction as db_transaction

    if _can_select_for_update():
        try:
            with db_transaction.atomic():
                existing = _lock_processing_record(msg_id)
                if existing is not None:
                    return existing, False
                return EmailProcessing.objects.create(
                    message_id=msg_id, **defaults), True
        except IntegrityError:
            with db_transaction.atomic():
                existing = _lock_processing_record(msg_id)
                if existing is not None:
                    return existing, False
            raise
    # Fallback (e.g. SQLite without row locking): use update_or_create-like flow.
    try:
        with db_transaction.atomic():
            existing = EmailProcessing.objects.filter(message_id=msg_id).first()
            if existing is not None:
                return existing, False
            return EmailProcessing.objects.create(
                message_id=msg_id, **defaults), True
    except IntegrityError:
        existing = EmailProcessing.objects.filter(message_id=msg_id).first()
        if existing is not None:
            return existing, False
        raise


def _update_processing(proc, **fields):
    for key, value in fields.items():
        setattr(proc, key, value)
    if fields:
        proc.save(update_fields=list(fields.keys()))


def _process_message(msg_dict, mailbox):
    """Core: turn one parsed inbound message into ticket activity.

    Returns (ticket, created, error_message).

    Ticket reuse: if EmailProcessing already references a valid ticket, that
    ticket is the primary source of truth and is reused regardless of retry
    state. Attachment persistence for a new-ticket email is idempotent per
    stable MIME source-part identity and the ticket relationship is persisted
    before attachments are processed.
    """
    from django.db import transaction as db_transaction

    msg_id = (msg_dict.get("message_id") or "").strip()
    if not msg_id:
        return None, False, "No Message-ID header"

    sender_email = (msg_dict.get("sender") or "").strip().lower()
    subject = msg_dict.get("subject") or ""
    body = msg_dict.get("body") or ""
    recipient = msg_dict.get("recipient") or ""
    in_reply_to = msg_dict.get("in_reply_to") or ""
    is_reply_email = bool(in_reply_to or TICKET_REF_RE.search(subject or ""))

    # --- claim / load processing record (serialized per message id) ---
    with db_transaction.atomic():
        proc, proc_created = _get_or_create_processing_record(msg_id, {
            "mailbox": mailbox,
            "recipient": recipient,
            "sender": sender_email,
            "subject": subject,
            "body_preview": body[:200],
            "status": "pending",
            "ticket": None,
            "processed_at": None,
            "error_details": "",
        })

        # Idempotent replay of a fully processed email.
        if proc.status == "processed" and proc.ticket_id:
            try:
                ticket = Ticket.objects.get(pk=proc.ticket_id)
                return ticket, False, None
            except Ticket.DoesNotExist:
                # Processed record points to a missing ticket: fall through to
                # recover safely.
                proc.ticket = None
                proc.ticket_id = None

        # Any non-processed state is retryable. Preserve existing ticket link.
        _update_processing(
            proc,
            mailbox=mailbox,
            recipient=recipient,
            sender=sender_email,
            subject=subject,
            body_preview=body[:200],
            status="pending",
            error_details="",
            processed_at=None,
        )

    # --- validate sender / attachments (outside the claim transaction) ---
    sender_user = _find_user_by_email(sender_email)
    eligible = bool(sender_user) or bool(_allowed_sender_domain(sender_email))

    if not eligible:
        with db_transaction.atomic():
            proc = _lock_processing_record(msg_id) or proc
            _update_processing(
                proc,
                status="failed",
                error_details="Sender not recognized by the support mailbox.",
                ticket=None,
                processed_at=None,
            )
        return None, False, "Sender not recognized by the support mailbox."

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
        with db_transaction.atomic():
            proc = _lock_processing_record(msg_id) or proc
            _update_processing(
                proc,
                status="failed",
                error_details=f"Unsupported attachment: {attach_error}",
                ticket=None,
                processed_at=None,
            )
        return None, False, attach_error

    # --- resolve or reuse ticket ---
    created = False
    is_internal = False
    ticket = None
    save_attachments = False
    new_ticket_user = None

    # Serialize ticket resolution/creation per message id. The processing row
    # is locked for the duration of this transaction so concurrent workers
    # wait for the first one to commit its ticket link before deciding.
    with db_transaction.atomic():
        proc = _lock_processing_record(msg_id) or proc

        # Primary source of truth: reuse a valid ticket already linked to this
        # processing record, regardless of retryable status.
        if proc.ticket_id:
            try:
                ticket = Ticket.objects.get(pk=proc.ticket_id)
            except Ticket.DoesNotExist:
                ticket = None
                _update_processing(proc, ticket=None)
                proc.ticket = None
                proc.ticket_id = None

        if ticket is not None:
            # Existing linked ticket: decide flow. If the message is reply-shaped
            # and resolves to the same linked ticket, treat as reply (no
            # attachment saving, preserve existing behavior). Otherwise reconcile
            # attachments for the ticket owned by this email (new-ticket or
            # reply-marker-without-resolvable-target cases).
            resolved = _resolve_reply_ticket(in_reply_to, subject) \
                if is_reply_email else None
            if resolved is not None and resolved.pk == ticket.pk:
                save_attachments = False
                created = False
            else:
                save_attachments = True
                created = False
        else:
            # No authoritative linked ticket: first-time routing.
            if is_reply_email:
                ticket = _resolve_reply_ticket(in_reply_to, subject)
            if ticket is None:
                # New ticket for this email (including reply-marker messages whose
                # target could not be resolved).
                user = sender_user or _ensure_requester_account(sender_email)
                category, _cat_created = TicketCategory.objects.get_or_create(
                    name="General", defaults={"is_active": True})
                ticket = Ticket.objects.create(
                    title=(subject or "").strip()[:255]
                    or "Email-generated ticket",
                    description=body or "",
                    category=category,
                    priority="medium",
                    status="open",
                    requester=user,
                )
                _update_processing(proc, ticket=ticket)
                created = True
                save_attachments = True
                new_ticket_user = user
            else:
                # Reply to an existing ticket (resolved target).
                created = False
                save_attachments = False
                _update_processing(proc, ticket=ticket)

    # Creation confirmation to the requester (honors their preference), sent
    # only after the ticket/link transaction has committed.
    if created and new_ticket_user is not None:
        user = new_ticket_user
        if user.email and _wants_ticket_email(user):
            from accounts import email_utils as _eu
            _eu.send_ticket_notification(
                user.email,
                f"Ticket #{ticket.pk} created: {ticket.title}",
                f"Your ticket was created.\nStatus: {ticket.status}\n"
                f"View: {_eu.ticket_links(ticket.pk)[1]}",
                ticket_id=ticket.pk)

    # --- reply note handling (idempotent per inbound message) ---
    reply_note_created = False
    if ticket is not None and not created and not save_attachments:
        is_internal = bool(sender_user) and sender_user is not None and (
            sender_user.role in ("system_admin", "it_manager", "it_support")
            or sender_user.is_superuser)
        if (body or not attachments) and sender_user is not None:
            existing_note = TicketNote.objects.filter(
                ticket=ticket, source_message_id=msg_id).first()
            if existing_note is None:
                try:
                    with transaction.atomic():
                        TicketNote.objects.create(
                            ticket=ticket,
                            author=sender_user,
                            body=body,
                            is_internal=is_internal,
                            source_message_id=msg_id,
                        )
                    reply_note_created = True
                except Exception as exc:
                    # Concurrent or retried create: reuse the committed note.
                    from django.db import IntegrityError
                    if isinstance(exc, IntegrityError):
                        existing_note = TicketNote.objects.filter(
                            ticket=ticket, source_message_id=msg_id).first()
                        if existing_note is None:
                            raise
                        reply_note_created = False
                    else:
                        raise
            else:
                reply_note_created = False
            # Preserve the note's effective visibility for downstream behavior.
            if existing_note is not None:
                is_internal = existing_note.is_internal
        # If body is empty and attachments exist, or sender is not a known user,
        # preserve existing behavior: no reply note is created.

    # --- attachment persistence (idempotent, before success status) ---
    if ticket is not None and save_attachments:
        for idx, att in enumerate(valid_attachments):
            part_index = att.get("part_index", idx)
            _save_attachment(
                ticket, att,
                source_message_id=msg_id,
                source_part_index=part_index,
            )

    # Mark processed only after required work has succeeded.
    with db_transaction.atomic():
        proc = _lock_processing_record(msg_id) or proc
        _update_processing(
            proc,
            status="processed",
            ticket=ticket,
            processed_at=timezone.now(),
            error_details="",
        )

    if ticket is not None and not created and not save_attachments and not is_internal:
        # Requester-visible reply: notify them (deduped outbound send).
        from accounts import email_utils as _eu
        _eu.send_ticket_notification(
            ticket.requester.email if ticket.requester else None,
            f"Re: {(subject or '')[:80]}",
            f"Reply received on ticket #{ticket.pk}: {(body or '')[:500]}",
            ticket_id=ticket.pk,
            user=ticket.requester,
            category=TICKET_REPLY_CATEGORY)

    return ticket, created, None


def process_inbound_email(msg_dict, mailbox="support"):
    """Process a single inbound email and create/attach a ticket.

    :param msg_dict: Dict with keys: message_id, sender, recipient, subject,
                    body (plus optional in_reply_to / attachments).
    :param mailbox: Name of the mailbox this email was received on.
    :returns: (ticket, created, error_message)
    """
    from django.db import transaction as db_transaction

    msg = dict(msg_dict or {})
    mailbox_name = mailbox or "support"
    try:
        return _process_message(msg, mailbox_name)
    except Exception as exc:  # one bad message must not kill the batch
        msg_id = (msg.get("message_id") or "").strip()
        logger.exception("Failed to process inbound email %s",
                        msg_id or "unknown")
        if msg_id:
            try:
                with db_transaction.atomic():
                    proc = _lock_processing_record(msg_id)
                    if proc is None:
                        EmailProcessing.objects.create(
                            message_id=msg_id,
                            mailbox=mailbox_name,
                            recipient=msg.get("recipient") or "",
                            sender=msg.get("sender") or "",
                            subject=msg.get("subject") or "",
                            body_preview=(msg.get("body") or "")[:200],
                            status="failed",
                            error_details=f"{type(exc).__name__}: "
                                          f"{(str(exc) or '')[:200]}",
                            ticket=None,
                            processed_at=None,
                        )
                    else:
                        _update_processing(
                            proc,
                            mailbox=mailbox_name,
                            recipient=msg.get("recipient") or "",
                            sender=msg.get("sender") or "",
                            subject=msg.get("subject") or "",
                            body_preview=(msg.get("body") or "")[:200],
                            status="failed",
                            error_details=f"{type(exc).__name__}: "
                                          f"{(str(exc) or '')[:200]}",
                            processed_at=None,
                            # Preserve any ticket relationship already persisted
                            # so retries can reuse the same ticket and dedup
                            # attachments safely.
                        )
            except Exception:
                pass
        return None, False, f"{type(exc).__name__}: {(str(exc) or '')[:200]}"
