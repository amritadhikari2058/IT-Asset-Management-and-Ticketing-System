"""Email ingestion and ticket creation tasks.

- ``process_inbound_mailbox`` (Celery beat / worker): polls the
  organizational support mailbox over IMAP, parses each unseen message and
  creates/associates tickets. Idempotent per Message-ID via
  ``common.EmailProcessing``; failed messages stay unseen for safe retry.
- Task runs are recorded in ``common.BackgroundTaskRun`` for operational
  health visibility.
"""
import logging

from celery import shared_task

from django.conf import settings
from django.utils import timezone

from common import inbound
from common.models import BackgroundTaskRun, EmailProcessing

logger = logging.getLogger(__name__)

TASK_NAME = "common.tasks.process_inbound_mailbox"


def record_task_run(task_name, status, error_summary="", payload=None):
    """Persist a task execution outcome (running -> succeeded/failed)."""
    run = BackgroundTaskRun.objects.create(
        task_name=task_name, status=status,
        success=(status == "succeeded"),
        error_summary=error_summary or "",
        payload=payload or {})
    if status in ("succeeded", "failed", "skipped"):
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "success", "error_summary",
                                "finished_at"])
    return run


def _mark_run(task_name, run, status, error_summary=""):
    run.status = status
    run.success = status == "succeeded"
    run.error_summary = error_summary or ""
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "success", "error_summary",
                            "finished_at"])
    return run


@shared_task(bind=True, max_retries=3, retry_backoff=60)
def process_inbound_mailbox(self):
    """Poll the support mailbox for unseen messages and ingest them."""
    run = BackgroundTaskRun.objects.create(
        task_name=TASK_NAME, status="running", success=False,
        payload={"action": "poll_mailbox"})
    try:
        summary = poll_support_mailbox()
        _mark_run(TASK_NAME, run, "succeeded")
        logger.info("Inbound email poll completed: %s", summary)
        return summary
    except Exception as exc:  # -> Celery retry with backoff
        logger.exception("Inbound email poll task failed: %s", TASK_NAME)
        _mark_run(TASK_NAME, run, "failed", error_summary=type(exc).__name__)
        raise self.retry(exc, args=(), kwargs={}) from exc


def poll_support_mailbox():
    """Fetch UNSEEN messages from the configured IMAP support mailbox."""
    if not getattr(settings, "INBOUND_MAILBOX_ENABLED", True):
        return {"status": "disabled", "processed": 0, "fetched": 0}
    host = (getattr(settings, "INBOUND_MAILBOX_HOST", "") or "").strip()
    if not host:
        # No IMAP host configured: nothing to poll (dev / tests).
        return {"status": "disabled", "processed": 0, "fetched": 0}

    import imaplib
    import ssl
    from email import message_from_bytes
    from email.utils import getaddresses

    user = (getattr(settings, "INBOUND_MAILBOX_USER", "") or "").strip()
    password = (getattr(settings, "INBOUND_MAILBOX_PASSWORD", "") or "")
    port = int(getattr(settings, "INBOUND_MAILBOX_PORT", 993) or 993)
    use_tls = bool(getattr(settings, "INBOUND_MAILBOX_USE_TLS", True))
    mailbox_name = (getattr(settings, "INBOUND_MAILBOX_NAME", "INBOX")
                    or "INBOX")

    if use_tls:
        ctx = ssl.create_default_context()
        client = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    else:
        client = imaplib.IMAP4(host, port)
    try:
        if user and password:
            client.login(user, password)
        client.select(mailbox_name)
        typ, data = client.search(None, "UNSEEN")
        if typ != "OK":
            raise RuntimeError(f"IMAP search failed: {typ}")
        nums = [n for n in (data[0].split() if data[0] else [])]
        processed = 0
        for num in nums:
            typ, msg_data = client.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue
            raw = msg_data[0][1]
            if not raw:
                continue
            msg = message_from_bytes(raw)
            pairs = getaddresses(msg.get_all("From", []) or [])
            sender = ""
            for _n, addr in pairs:
                sender = (addr or "").strip().lower()
                if sender:
                    break
            recip_pairs = getaddresses(msg.get_all("To", []) or [])
            recipient = ""
            for _n, addr in recip_pairs:
                recipient = (addr or "").strip().lower()
                if recipient:
                    break
            msg_dict = inbound.build_inbound_message(msg, mailbox=mailbox_name)
            ticket, created, error = inbound.process_inbound_email(
                msg_dict, mailbox=mailbox_name)
            if error:
                logger.warning(
                    "Inbound email %s failed: %s", msg_dict.get("message_id"),
                    error)
                # Leave the message UNSEEN so the next poll retries safely.
                continue
            processed += 1
            # Only mark seen when the message was handled successfully.
            try:
                client.store(num, "+FLAGS", "\\Seen")
            except Exception:
                pass
        return {"status": "ok", "processed": processed, "fetched": len(nums)}
    finally:
        try:
            client.logout()
        except Exception:
            pass


@shared_task(bind=True, max_retries=2, retry_backoff=120)
def process_inbound_email_task(self):  # pragma: no cover - operational entry
    """Manual/safe-retry entry that runs one mailbox poll."""
    return poll_support_mailbox()
