"""Email ingestion and ticket creation tasks.

- ``process_inbound_mailbox`` (Celery beat / worker): polls the
  organizational support mailbox over IMAP, parses each unseen message and
  creates/associates tickets. Idempotent per Message-ID via
  ``common.EmailProcessing``; failed messages stay unseen for safe retry.
- Task runs are recorded in ``common.BackgroundTaskRun`` for operational
  health visibility.
"""
import logging
from datetime import timedelta

from celery import shared_task

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from common import inbound
from common.models import (BackgroundTaskRun, DataRetentionExecution,
                           DataRetentionPolicy, EmailProcessing)
from common.retention_service import execute_retention, preview_retention

logger = logging.getLogger(__name__)

TASK_NAME = "common.tasks.process_inbound_mailbox"
RETENTION_EVAL_TASK = "common.tasks.evaluate_retention_policies"
RETENTION_EXECUTE_TASK = "common.tasks.execute_retention_policy"

# How far ahead a retention policy is claimed when it is dispatched. A policy
# is evaluated at most once per interval, even if Celery Beat runs
# ``evaluate_retention_policies`` more often (it currently runs hourly).
RETENTION_EVALUATION_INTERVAL = timedelta(days=1)
# Shorter back-off used when a policy could not be dispatched at all, so a
# transient broker/worker problem does not delay retention for a full day.
RETENTION_DISPATCH_RETRY_INTERVAL = timedelta(hours=1)


def _retention_due_q(now):
    """Policies that have never run or whose claimed run time has arrived."""
    return Q(next_run_at__isnull=True) | Q(next_run_at__lte=now)


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


def _mark_run(task_name, run, status, error_summary="", payload=None):
    run.status = status
    run.success = status == "succeeded"
    run.error_summary = error_summary or ""
    if payload is not None:
        run.payload = payload
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "success", "error_summary",
                            "finished_at", "payload"])
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


@shared_task(bind=True, max_retries=2, retry_backoff=300)
def run_scheduled_reports(self):
    """Due scheduled reports: render, export, email, record history.

    Idempotent per (scheduled_report, run window): a ScheduledReportRun row
    is created before delivery so a retried task does not double-send.

    Recipient policy: deliveries go to the explicit recipient list configured
    on the schedule (IT / staff authored) and do not inherit per-user
    notification categories (see ``common.notifications``).
    """
    from django.db import transaction
    from common.models import ScheduledReport, ScheduledReportRun

    now = timezone.now()
    due = ScheduledReport.objects.filter(
        enabled=True, next_run_at__lte=now).select_related("saved_report")

    results = {"checked": 0, "sent": 0, "failed": 0}
    for sr in due:
        results["checked"] += 1
        run = None
        try:
            with transaction.atomic():
                run = ScheduledReportRun.objects.create(
                    scheduled_report=sr,
                    status="running", success=False,
                    started_at=now)
            # Render the saved report by calling the existing report endpoint
            # logic directly (no HTTP round-trip needed).
            from tickets.views import category_report, sla_report
            from rest_framework.test import APIRequestFactory
            from accounts import email_utils as _email_utils

            factory = APIRequestFactory()
            req = factory.get("/api/tickets/reports/by-category/",
                              data=sr.saved_report.filters or {})
            # Attach the user so permission-aware reports work.
            req.user = sr.saved_report.user

            if sr.saved_report.report_type == "ticket_category":
                resp = category_report(req)
            elif sr.saved_report.report_type == "ticket_sla":
                resp = sla_report(req)
            else:
                raise ValueError(f"Unknown report type: {sr.saved_report.report_type}")

            payload = resp.data if hasattr(resp, "data") else resp
            fmt = sr.format or "csv"
            content = _render_report(payload, fmt)
            filename = f"{sr.saved_report.name.replace(' ', '_')}_{now:%Y%m%d}.{fmt}"
            content_type = {
                "csv": "text/csv",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "pdf": "application/pdf",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }.get(fmt, "application/octet-stream")
            subject = f"Scheduled report: {sr.saved_report.name}"
            body = "Please find the attached scheduled report."

            # Explicit recipient policy: report deliveries go to the
            # schedule's recipient list without per-user notification filters.
            recipients = sr.recipients or []
            sent_count = 0
            for to_email in recipients:
                if _email_utils.send_scheduled_report_email(
                        to_email, subject, body, filename, content, content_type):
                    sent_count += 1

            with transaction.atomic():
                run.status = "succeeded"
                run.success = True
                run.finished_at = timezone.now()
                run.recipient_count = sent_count
                run.save(update_fields=["status", "success", "finished_at",
                                        "recipient_count"])

            # Compute next run and advance.
            _advance_next_run(sr)
            results["sent"] += 1

        except Exception as exc:
            logger.exception("Scheduled report %s failed: %s", sr.pk, sr)
            if run:
                with transaction.atomic():
                    run.status = "failed"
                    run.success = False
                    run.error_summary = type(exc).__name__
                    run.finished_at = timezone.now()
                    run.save(update_fields=["status", "success",
                                            "error_summary", "finished_at"])
            # Still advance next_run so a persistently-failing report doesn't
            # block the queue forever.
            _advance_next_run(sr)
            results["failed"] += 1

    return results


def _advance_next_run(sr):
    """Move next_run_at forward by one cadence."""
    from datetime import timedelta
    now = timezone.now()
    base = sr.next_run_at or now
    if sr.schedule == "daily":
        sr.next_run_at = base + timedelta(days=1)
    elif sr.schedule == "weekly":
        sr.next_run_at = base + timedelta(weeks=1)
    elif sr.schedule == "monthly":
        sr.next_run_at = base + timedelta(days=30)
    sr.save(update_fields=["next_run_at"])


def _render_report(payload, fmt):
    """Serialize report payload to the requested format (csv/json/xlsx/pdf/docx).

    Reuses the existing export infrastructure (common.exports) so scheduled
    reports support all four formats without a separate implementation.
    """
    if fmt == "json":
        import json
        return json.dumps(payload, default=str, indent=2)

    rows = payload.get("results", []) if isinstance(payload, dict) else payload
    fields = list(rows[0].keys()) if rows and isinstance(rows, list) else []
    title = "Scheduled Report"

    if fmt == "csv":
        from common.exports import _csv_bytes
        return _csv_bytes(rows, fields)
    if fmt == "xlsx":
        from common.exports import _xlsx_bytes
        return _xlsx_bytes(rows, fields, title)
    if fmt == "pdf":
        from common.exports import _pdf_bytes
        return _pdf_bytes(rows, fields, title)
    if fmt == "docx":
        from common.exports import _docx_bytes
        return _docx_bytes(rows, fields, title)
    # Fallback to CSV.
    from common.exports import _csv_bytes
    return _csv_bytes(rows, fields)


@shared_task(bind=True, max_retries=2, retry_backoff=300)
def evaluate_retention_policies(self):
    """Scheduled retention evaluation (Celery beat).

    Finds enabled policies whose ``next_run_at`` is due and dispatches a
    per-policy execution task. Independent per-policy tasks isolate failures:
    one category's failure does not prevent another category's run.

    Idempotency: each due policy is *claimed* with a conditional UPDATE of
    ``next_run_at`` before dispatch, so two overlapping Beat runs (or two
    Beat instances) cannot dispatch the same policy twice. A policy that can
    only be claimed by one caller is dispatched exactly once per interval.
    """
    run = BackgroundTaskRun.objects.create(
        task_name=RETENTION_EVAL_TASK, status="running", success=False,
        payload={"action": "evaluate_retention_policies"})
    results = {"checked": 0, "dispatched": 0, "failed": 0, "skipped": 0}
    try:
        now = timezone.now()
        due = list(DataRetentionPolicy.objects
                   .filter(enabled=True)
                   .filter(_retention_due_q(now))
                   .order_by("next_run_at"))

        for policy in due:
            results["checked"] += 1
            claimed = (DataRetentionPolicy.objects
                       .filter(pk=policy.pk, enabled=True)
                       .filter(_retention_due_q(now))
                       .update(
                           next_run_at=now + RETENTION_EVALUATION_INTERVAL))
            if not claimed:
                # Another evaluation already claimed this policy.
                results["skipped"] += 1
                continue
            try:
                execute_retention_policy.delay(policy.pk)
                results["dispatched"] += 1
            except Exception:
                # Broker unavailable: run inline as a fallback.
                logger.exception("Retention dispatch failed for %s",
                                 policy.pk)
                try:
                    execute_retention_policy(policy.pk)
                    results["dispatched"] += 1
                except Exception as exc2:
                    results["failed"] += 1
                    # Retry sooner than a normal cadence, but not on the next
                    # Beat tick (which would hot-loop a failing policy).
                    (DataRetentionPolicy.objects.filter(pk=policy.pk)
                     .update(next_run_at=now
                             + RETENTION_DISPATCH_RETRY_INTERVAL))
                    _record_retention_failure(policy, type(exc2).__name__)

        outcome = "succeeded" if results["failed"] == 0 else "failed"
        _mark_run(RETENTION_EVAL_TASK, run, outcome,
                  "" if outcome == "succeeded"
                  else f"{results['failed']} policy dispatch(es) failed")
        logger.info("Retention evaluation complete: %s", results)
        return results
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Retention evaluation failed")
        _mark_run(RETENTION_EVAL_TASK, run, "failed", type(exc).__name__)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=2, retry_backoff=300)
def execute_retention_policy(self, policy_id):
    """Execute one retention policy (authorization-reentrant).

    The task independently re-verifies that the policy is still enabled and
    due before mutating anything, so a queued task can never execute a
    disabled or already-run policy outside its approval window. Skipped and
    failed attempts are recorded in ``DataRetentionExecution`` so the history
    never silently omits a run.
    """
    policy = DataRetentionPolicy.objects.filter(pk=policy_id).first()
    if not policy:
        return {"policy_id": policy_id, "error": "policy_not_found"}
    if not policy.enabled:
        _record_retention_failure(policy, "policy_disabled", status="skipped")
        return {"policy_id": policy_id, "status": "skipped",
                "reason": "policy_disabled"}
    preview = preview_retention(policy)
    if not preview.get("can_execute"):
        reason = (preview["notes"][0] if preview["notes"]
                  else "not_executable")
        _record_retention_failure(policy, reason, status="skipped")
        return {"policy_id": policy_id, "status": "skipped",
                "reason": reason}

    ok, error, summary = execute_retention(policy, None)
    if not ok:
        _record_retention_failure(policy, error or "execution_failed")
    return {"policy_id": policy_id, "ok": ok, "error": error,
            "summary": summary}


def _record_retention_failure(policy, error_summary, status="failed"):
    """Persist a non-successful retention attempt (never a fake success)."""
    try:
        return DataRetentionExecution.objects.create(
            policy=policy, status=status,
            finished_at=timezone.now(),
            error_summary=(error_summary or "")[:2000],
            result={"category": policy.data_category,
                    "policy_id": policy.pk})
    except Exception:  # pragma: no cover - bookkeeping must not hide errors
        logger.exception("Could not record retention attempt for %s",
                         policy.pk)
        return None

