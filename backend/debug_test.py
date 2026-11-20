"""Debug test for ticket reuse on retry."""
import os, shutil, tempfile
from email.message import EmailMessage
from django.core.files.storage import FileSystemStorage
from django.db import IntegrityError
from django.test import override_settings
from unittest.mock import patch

from tickets.models import Ticket, TicketAttachment
from common.models import EmailProcessing
from common import inbound

_SETTINGS = {
    'INBOUND_ALLOWED_SENDER_DOMAINS': 'example.com',
    'ATTACHMENT_MAX_SIZE_MB': 10,
    'ATTACHMENT_ALLOWED_EXTENSIONS': 'pdf,png,jpg,jpeg,txt,csv,log,docx,xlsx',
}

def _message(attachments=(), body='Printer is broken', message_id='<inbound-attach@example.com>', subject='Printer broken'):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = 'user@example.com'
    msg['To'] = 'support@example.com'
    msg['Message-ID'] = message_id
    msg.set_content(body)
    for name, data, ctype in attachments:
        maintype, subtype = ctype.split('/', 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg

def _ingest(attachments, message_id='<inbound-attach@example.com>', subject='Printer broken'):
    msg = _message(attachments=attachments, message_id=message_id, subject=subject)
    return inbound.process_inbound_email(inbound.build_inbound_message(msg))

media_root = tempfile.mkdtemp(prefix='debug3-')
override = override_settings(MEDIA_ROOT=media_root, **_SETTINGS)
override.enable()

attachments = [
    ("report.pdf", b"January data", "application/pdf"),
    ("report.pdf", b"February data", "application/pdf"),
    ("summary.pdf", b"Summary data", "application/pdf"),
]

# First attempt
ticket, created, error = _ingest(attachments)
print(f'After first attempt:')
print(f'  error={error}')
print(f'  Ticket: {ticket.pk if ticket else None}')
print(f'  Attachments: {TicketAttachment.objects.count()}')
for att in TicketAttachment.objects.all():
    print(f'    - {att.original_filename}, content_hash={att.content_hash[:8] if att.content_hash else None}, ticket={att.ticket_id}')
print(f'  EmailProcessing: try to get...')
try:
    proc = EmailProcessing.objects.get(message_id='<inbound-attach@example.com>')
    print(f'    status={proc.status}, ticket_id={proc.ticket_id}')
except EmailProcessing.DoesNotExist:
    print('    No EmailProcessing record')

# Reset EmailProcessing to failed
print(f'\nResetting EmailProcessing to failed...')
try:
    proc = EmailProcessing.objects.get(message_id='<inbound-attach@example.com>')
    EmailProcessing.objects.filter(pk=proc.pk).update(status='failed')
    proc = EmailProcessing.objects.get(message_id='<inbound-attach@example.com>')
    print(f'  After reset: status={proc.status}, ticket_id={proc.ticket_id}')
except EmailProcessing.DoesNotExist:
    print('  No EmailProcessing record to reset')

# Retry
ticket2, created2, error2 = _ingest(attachments)
print(f'\nAfter retry:')
print(f'  error={error2}')
print(f'  Ticket2: {ticket2.pk if ticket2 else None}')
print(f'  Attachments: {TicketAttachment.objects.count()}')
for att in TicketAttachment.objects.all():
    print(f'    - {att.original_filename}, content_hash={att.content_hash[:8] if att.content_hash else None}, ticket={att.ticket_id}')

shutil.rmtree(media_root)
override.disable()