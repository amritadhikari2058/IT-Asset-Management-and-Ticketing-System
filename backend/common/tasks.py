"""Email ingestion and ticket creation tasks."""
from datetime import timedelta
import hashlib
import re

from django.conf import settings
from django.core.mail import mail
from django.utils import timezone

from common.models import EmailProcessing
from tickets.models import Ticket, TicketCategory


def _hash_email(msg):
    """Create a stable hash from the email's key identifying fields."""
    parts = [msg.get("message_id", ""), msg.get("sender", ""), msg.get("subject", "")]
    return hashlib.sha256("".join(parts).encode()).hexdigest()[:40]


def _find_or_create_ticket(sender_email, subject, body, mailbox):
    """Try to find or create a ticket from an email.

    Returns (ticket, created) tuple.
    """
    # Try to find employee by email
    try:
        from accounts.models import User
        user = User.objects.get(email=sender_email)
    except User.DoesNotExist:
        # Create a minimal user record if none exists (will need later cleanup)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        # Use get_or_create with a temporary password; in production this
        # would be handled by the normal employee onboarding flow.
        user, _ = User.objects.get_or_create(
            email=sender_email,
            defaults={
                "username": sender_email,
                "role": "employee",
                "employee_id": sender_email.split("@")[0].upper(),
                "can_create_tickets": True,
                "receive_ticket_emails": True,
            },
        )

    # Try to find or create a category for unsorted tickets
    category, _ = TicketCategory.objects.get_or_create(
        name="General", code="gen", defaults={"is_active": True})

    # Try to find an existing ticket from this email (idempotency)
    email_processing = EmailProcessing.objects.filter(
        message_id=msg.get("message_id", ""),
        recipient=msg.get("recipient", ""),
    ).first()
    if email_processing and email_processing.ticket:
        return email_processing.ticket, False

    # Create a new ticket
    ticket = Ticket.objects.create(
        title=subject or "Email-generated ticket",
        description=body or "",
        category=category,
        requester=user,
        status="open",
    )

    # Record the email processing
    EmailProcessing.objects.create(
        message_id=msg.get("message_id", ""),
        mailbox=mailbox or "",
        recipient=sender_email,
        sender=sender_email,
        subject=subject or "",
        body_preview=body[:200] if body else "",
        status="processed",
        ticket=ticket,
    )

    return ticket, True


def process_inbound_email(msg_dict, mailbox="support"):
    """Process a single inbound email and create a ticket if eligible.

    :param msg_dict: Dict with keys: message_id, sender, recipient, subject, body
    :param mailbox: Name of the mailbox this email was received on
    :returns: (ticket, created, error_message)
    """
    # Idempotency check
    msg_id = msg_dict.get("message_id", "")
    if not msg_id:
        return None, False, "No Message-ID header"

    try:
        existing = EmailProcessing.objects.get(message_id=msg_id)
        if existing.status == "processed" and existing.ticket:
            return existing.ticket, True, None
        if existing.status == "failed":
            # Allow retry once
            existing.status = "pending"
            existing.save(update_fields=["status"])
    except EmailProcessing.DoesNotExist:
        pass

    # Create or find the ticket
    ticket, created = _find_or_create_ticket(
        sender_email=msg_dict.get("sender", ""),
        subject=msg_dict.get("subject", ""),
        body=msg_dict.get("body", ""),
        mailbox=mailbox,
    )

    # Mark as processed
    EmailProcessing.objects.update_or_create(
        message_id=msg_id,
        defaults={
            "mailbox": mailbox,
            "recipient": msg_dict.get("recipient", ""),
            "sender": msg_dict.get("sender", ""),
            "subject": msg_dict.get("subject", ""),
            "body_preview": msg_dict.get("body", "")[:200],
            "status": "processed",
            "ticket": ticket,
        },
    )

    return ticket, created, None