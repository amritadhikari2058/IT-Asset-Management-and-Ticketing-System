"""Email ingestion and ticket creation tasks.

- ``process_inbound_mailbox`` (Celery beat / worker): polls the
  organizational support mailbox over IMAP, parses each unseen message and
  creates/associates tickets. Idempotent per Message-ID via
  ``common.EmailProcessing``; failed messages stay unseen for safe retry.
- Task runs are recorded in ``common.BackgroundTaskRun`` for operational
  health visibility.
"""
import hashlib
import logging
import threading
import uuid
from datetime import timedelta

from celery import shared_task

from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from common import inbound
from common.models import (BackgroundTaskRun, DataRetentionExecution,
                           DataRetentionPolicy, EmailProcessing)
from common.retention_service import execute_retention, preview_retention

logger = logging.getLogger(__name__)

TASK_NAME = "common.tasks.process_inbound_mailbox"
RETENTION_EVAL_TASK = "common.tasks.evaluate_retention_policies"
RETENTION_EXECUTE_TASK = "common.tasks.execute_retention_policy"
OUTBOX_DELIVER_TASK = "common.tasks.deliver_outbox_event"
OUTBOX_BATCH_TASK = "common.tasks.process_notification_outbox"
OUTBOX_CLEANUP_TASK = "common.tasks.cleanup_notification_outbox"

# How far ahead a retention policy is claimed when it is dispatched. A policy
# is evaluated at most once per interval, even if Celery Beat runs
# ``evaluate_retention_policies`` more often (it currently runs hourly).
RETENTION_EVALUATION_INTERVAL = timedelta(days=1)
# Shorter back-off used when a policy could not be dispatched at all, so a
# transient broker/worker problem does not delay retention for a full day.
RETENTION_DISPATCH_RETRY_INTERVAL = timedelta(hours=1)

# How long a scheduled-report execution owns its run before another worker may
# treat it as abandoned. The owner renews this lease with heartbeats while the
# report renders and delivers, so a legitimately long-running report keeps its
# ownership. A crashed worker stops renewing and the lease lapses, at which
# point exactly one recovery worker can reclaim the run (guarded by the row
# lock and the optimistic token/lease condition).
SCHEDULED_REPORT_LEASE_SECONDS = 300
# How often the in-process heartbeat helper renews an active lease. One third
# of the lease leaves room for two missed renewals before a worker is presumed
# dead.
SCHEDULED_REPORT_HEARTBEAT_INTERVAL = max(
    1, SCHEDULED_REPORT_LEASE_SECONDS // 3)
# Maximum number of delivery attempts per recipient within a single run.
# Bounded so a repeatedly failing recipient does not block the run forever.
SCHEDULED_REPORT_MAX_DELIVERY_ATTEMPTS = 3


def _normalize_email(email):
    """Normalize an email address for dedupe-key calculation.

    Lowercases and strips surrounding whitespace so that
    ``Ops@example.com`` and ``ops@example.com`` resolve to the same
    delivery identity without changing the stored recipient address.
    """
    if not email:
        return ""
    return email.strip().lower()


def _delivery_dedupe_key(run, to_email):
    """Stable per-(occurrence, recipient) deduplication key.

    Uses the run's ``occurrence_id`` so that the same logical scheduled
    occurrence + recipient always produces the same dedupe key, even when
    replacement runs are created after lease expiration or worker crashes.
    """
    normalized = _normalize_email(to_email)
    return hashlib.sha256(
        f"{run.occurrence_id}|{normalized}".encode("utf-8")).hexdigest()[:64]


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


def _lease_deadline(now=None):
    """Return the timestamp at which a freshly renewed lease expires."""
    now = now or timezone.now()
    return now + timedelta(seconds=SCHEDULED_REPORT_LEASE_SECONDS)


def _scheduled_run_lease_expired(run, now=None):
    """Whether another worker may treat ``run`` as abandoned.

    A run is reclaimable only once its lease has lapsed. Legacy rows created
    before leases existed have no ``lease_expires_at``; they fall back to the
    old fixed grace window measured from ``started_at``.
    """
    now = now or timezone.now()
    if run.lease_expires_at is not None:
        return run.lease_expires_at <= now
    return run.started_at <= now - timedelta(seconds=SCHEDULED_REPORT_LEASE_SECONDS)


def _renew_scheduled_report_lease(run_id, token):
    """Conditionally extend an execution lease.

    Returns ``True`` only while ``token`` still owns the running row. A worker
    whose execution was recovered by another scanner will see ``False`` and
    must stop touching the report.
    """
    from common.models import ScheduledReportRun

    now = timezone.now()
    updated = ScheduledReportRun.objects.filter(
        pk=run_id, status="running", execution_token=token,
    ).update(lease_expires_at=_lease_deadline(now), last_heartbeat_at=now)
    return bool(updated)


def _finalize_scheduled_report_run(run_id, token, **fields):
    """Ownership-checked finalization of a scheduled report run.

    Only the worker that still holds ``token`` and whose run is still
    ``running`` may write the terminal state. A stale worker whose lease was
    recovered gets ``False`` here and therefore cannot overwrite the newer
    execution's state or advance the schedule.
    """
    from common.models import ScheduledReportRun

    return bool(
        ScheduledReportRun.objects.filter(
            pk=run_id, status="running", execution_token=token,
        ).update(**fields)
    )


class _ScheduledReportLeaseKeeper:
    """Renew a run lease in the background while a long report executes.

    Report rendering and delivery are synchronous, so a lease renewed only at
    entry would lapse for a genuinely long report and let a second scanner
    reclaim it mid-flight. This bounded helper renews every
    ``SCHEDULED_REPORT_HEARTBEAT_INTERVAL`` seconds until the block exits,
    then stops and joins the thread. If the lease can no longer be renewed the
    worker has lost ownership and ``lost`` is set.
    """

    def __init__(self, run_id, token, interval=None):
        self.run_id = run_id
        self.token = token
        self.interval = interval or SCHEDULED_REPORT_HEARTBEAT_INTERVAL
        self.lost = False
        self._stop = threading.Event()
        self._thread = None

    def _loop(self):
        try:
            while not self._stop.wait(self.interval):
                try:
                    if not _renew_scheduled_report_lease(self.run_id, self.token):
                        self.lost = True
                        return
                except Exception:  # pragma: no cover - defensive
                    logger.exception(
                        "Failed to renew lease for scheduled report run %s",
                        self.run_id)
        finally:
            # Each worker/heartbeat thread owns its own Django DB connection;
            # close it when the thread exits so connections do not leak and
            # block test teardown or exhaust the pool in production.
            try:
                from django.db import connections
                connections.close_all()
            except Exception:  # pragma: no cover - defensive
                pass

    def __enter__(self):
        self._thread = threading.Thread(
            target=self._loop, name=f"sr-lease-{self.run_id}", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 1)
        return False


@shared_task(bind=True, max_retries=2, retry_backoff=300)
def run_scheduled_reports(self):
    """Due scheduled reports: render, export, email, record history.

    Idempotent per (scheduled_report, run window): a ScheduledReportRun row
    is created before delivery so a retried task does not double-send.

    Concurrency safety rests on three mechanisms:

    * A unique partial constraint allows at most one ``running`` run per
      scheduled report, so two scanners cannot both start a run.
    * Each execution carries an ``execution_token`` and a renewable lease
      (``lease_expires_at`` / ``last_heartbeat_at``). Only an execution whose
      lease has lapsed is considered abandoned and recovered.
    * Finalization is ownership-checked, so a worker that lost its lease to a
      recovery worker cannot later overwrite the newer execution's state.

    Recipient policy: deliveries go to the explicit recipient list configured
    on the schedule (IT / staff authored) and do not inherit per-user
    notification categories (see ``common.notifications``).
    """
    from django.db import transaction
    from common.models import ScheduledReport, ScheduledReportRun

    now = timezone.now()

    results = {"checked": 0, "sent": 0, "failed": 0, "recovered": 0}

    # Reclaim abandoned executions whose schedule is no longer due. A worker
    # that crashes after advancing ``next_run_at`` but before finalizing would
    # otherwise leave its run ``running`` until the next scheduled period (a
    # week for weekly reports). Recover those rows and re-arm the schedule so
    # the due pass below re-runs the missed occurrence. Delivery is
    # at-least-once: a crash after a successful send may re-send, which the
    # per-run delivery dedupe cannot detect across runs.
    expired_running = list(
        ScheduledReportRun.objects.filter(
            status="running", lease_expires_at__isnull=False,
            lease_expires_at__lte=now).select_related("scheduled_report")
    )
    for stale in expired_running:
        reclaimed = ScheduledReportRun.objects.filter(
            pk=stale.pk, status="running",
            lease_expires_at=stale.lease_expires_at,
            execution_token=stale.execution_token,
        ).update(
            status="failed", success=False,
            error_summary="stale_worker_recovered", finished_at=now)
        if not reclaimed:
            continue
        results["recovered"] += 1
        # Pending deliveries for the reclaimed run belong to a dead worker.
        # Mark them failed so they don't stay pending forever; the re-armed
        # schedule will create a new run with fresh delivery rows.
        ScheduledReportDelivery.objects.filter(
            scheduled_report_run=stale.pk, status="pending"
        ).update(status="failed", error_message="worker_crashed_before_send",
                 updated_at=now)
        ScheduledReport.objects.filter(
            pk=stale.scheduled_report_id, enabled=True,
            next_run_at__gt=now,
        ).update(next_run_at=now)

    due = list(
        ScheduledReport.objects.filter(
            enabled=True, next_run_at__lte=now).select_related("saved_report")
    )

    for sr in due:
        results["checked"] += 1
        run = None
        token = uuid.uuid4().hex
        # Serialize workers per scheduled report so two scanners cannot both
        # start a run for the same report and double-deliver it. The row lock
        # is held only for the quick claim + next_run_at advance; rendering
        # and delivery then run outside the lock while the lease protects the
        # execution from being reclaimed by another scanner.
        try:
            with transaction.atomic():
                locked = ScheduledReport.objects.select_for_update().get(
                    pk=sr.pk)
                if not locked.enabled or locked.next_run_at is None \
                        or locked.next_run_at > now:
                    # Another worker already advanced this report.
                    continue
                existing_run = ScheduledReportRun.objects.filter(
                    scheduled_report=locked, status="running").first()
                if existing_run is not None:
                    if not _scheduled_run_lease_expired(existing_run, now):
                        # A live worker still owns this execution; leave it
                        # alone and do not start a competing run.
                        continue
                    # The lease lapsed: the owner is presumed dead. Recover
                    # with an optimistic guard so only one scanner wins even
                    # if several reach this point concurrently.
                    recovered = ScheduledReportRun.objects.filter(
                        pk=existing_run.pk, status="running",
                        lease_expires_at=existing_run.lease_expires_at,
                        execution_token=existing_run.execution_token,
                    ).update(
                        status="failed", success=False,
                        error_summary="stale_worker_recovered",
                        finished_at=now)
                    if not recovered:
                        # Someone else recovered it first; back off.
                        continue
                    results["recovered"] += 1
                run = ScheduledReportRun.objects.create(
                    scheduled_report=locked,
                    status="running", success=False,
                    started_at=now,
                    execution_token=token,
                    lease_expires_at=_lease_deadline(now),
                    last_heartbeat_at=now)
                # Advance next_run_at under the same lock so a concurrent
                # scanner cannot read a stale next_run_at and produce a
                # duplicate run / lost update.
                _advance_next_run(locked)
        except Exception as exc:
            logger.exception(
                "Scheduled report %s failed to start: %s", sr.pk, sr)
            results["failed"] += 1
            continue

        # Render and deliver outside the row lock, renewing the lease so a
        # long-running report is never mistaken for an abandoned execution.
        try:
            from tickets.views import category_report, sla_report
            from rest_framework.test import APIRequestFactory
            from accounts import email_utils as _email_utils

            with _ScheduledReportLeaseKeeper(run.pk, token) as keeper:
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
                    raise ValueError(
                        f"Unknown report type: {sr.saved_report.report_type}")

                payload = resp.data if hasattr(resp, "data") else resp
                fmt = sr.format or "csv"
                content = _render_report(payload, fmt)
                filename = (
                    f"{sr.saved_report.name.replace(' ', '_')}_"
                    f"{now:%Y%m%d}.{fmt}")
                content_type = {
                    "csv": "text/csv",
                    "xlsx": (
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"),
                    "pdf": "application/pdf",
                    "docx": (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"),
                }.get(fmt, "application/octet-stream")
                subject = f"Scheduled report: {sr.saved_report.name}"
                body = "Please find the attached scheduled report."

                # Renew once more right before delivery so a report that
                # rendered near the lease deadline still delivers.
                if not _renew_scheduled_report_lease(run.pk, token):
                    keeper.lost = True
                    raise _ScheduledReportOwnershipLost()

                # Explicit recipient policy: report deliveries go to the
                # schedule's recipient list without per-user notification
                # filters.
                recipients = sr.recipients or []
                sent_count = 0
                from common.models import ScheduledReportDelivery
                for to_email in recipients:
                    normalized_email = _normalize_email(to_email)
                    dedupe_key = _delivery_dedupe_key(run, to_email)

                    # Durable per-recipient dedupe within this run: a pending
                    # row is inserted before SMTP so a worker crash cannot
                    # silently lose the delivery, and a ``sent`` row prevents
                    # a recovered/retrying worker from re-sending to the same
                    # recipient in the same run.
                    existing = (
                        ScheduledReportDelivery.objects.filter(
                            delivery_dedupe_key=dedupe_key).first())
                    if existing is not None:
                        if existing.status == "sent":
                            sent_count += 1
                            continue
                        if existing.status == "failed" \
                                and existing.attempts >= \
                                SCHEDULED_REPORT_MAX_DELIVERY_ATTEMPTS:
                            # Bounded retry exhausted; skip this recipient.
                            continue
                        # Pending or retryable failed: attempt delivery.
                        delivery = existing
                    else:
                        delivery = ScheduledReportDelivery.objects.create(
                            scheduled_report_run=run,
                            recipient_email=normalized_email,
                            delivery_dedupe_key=dedupe_key,
                            status="pending",
                            attempts=1)

                    # Atomic claim: only this worker may deliver this row.
                    claimed = ScheduledReportDelivery.objects.filter(
                        pk=delivery.pk, status__in=("pending", "failed"),
                        attempts__lt=SCHEDULED_REPORT_MAX_DELIVERY_ATTEMPTS,
                    ).update(
                        status="pending",
                        attempts=models.F("attempts") + 1,
                    )
                    if not claimed:
                        # Another worker already claimed this delivery or
                        # retry budget is exhausted; skip.
                        continue

                    if _email_utils.send_scheduled_report_email(
                            to_email, subject, body, filename, content,
                            content_type):
                        updated = ScheduledReportDelivery.objects.filter(
                            pk=delivery.pk, status="pending").update(
                            status="sent", sent_at=timezone.now())
                        if updated:
                            sent_count += 1
                    else:
                        ScheduledReportDelivery.objects.filter(
                            pk=delivery.pk, status="pending").update(
                            status="failed",
                            error_message="smtp_send_failed",
                            updated_at=timezone.now())

            finalized = _finalize_scheduled_report_run(
                run.pk, token,
                status="succeeded", success=True,
                finished_at=timezone.now(),
                recipient_count=sent_count)
            if finalized:
                results["sent"] += 1
            else:
                # We lost the lease while delivering; another worker owns the
                # report now. Do not count this attempt or touch its state.
                logger.warning(
                    "Scheduled report %s run %s lost ownership before "
                    "finalization", sr.pk, run.pk)
                results["failed"] += 1

        except _ScheduledReportOwnershipLost:
            logger.warning(
                "Scheduled report %s run %s lease was recovered during "
                "execution", sr.pk, run.pk)
            results["failed"] += 1
        except Exception as exc:
            logger.exception("Scheduled report %s failed: %s", sr.pk, sr)
            _finalize_scheduled_report_run(
                run.pk, token,
                status="failed", success=False,
                error_summary=type(exc).__name__,
                finished_at=timezone.now())
            results["failed"] += 1

    return results


class _ScheduledReportOwnershipLost(Exception):
    """Raised when a worker discovers another worker recovered its run."""



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


@shared_task(name=OUTBOX_DELIVER_TASK, max_retries=0)
def deliver_outbox_event(event_id):
    """Deliver a single outbox event (low-latency ``on_commit`` wake-up).

    Delivery success/failure is recorded on the outbox row itself; the task
    never raises so a failed SMTP hand-off cannot surface as a Celery failure
    (the row is retried by the scanner under bounded backoff instead).
    """
    from common.outbox import deliver_event_core

    return deliver_event_core(str(event_id))


@shared_task(bind=True, name=OUTBOX_BATCH_TASK, max_retries=0)
def process_notification_outbox(self, batch_size=None):
    """Periodic scanner: recover expired leases and deliver a bounded batch.

    This is the durable safety net for the transactional outbox. It re-discovers
    any event the best-effort ``on_commit`` wake-up missed (broker outage, crash
    after commit) and drives retries to completion. One ``BackgroundTaskRun``
    row records each sweep for operational visibility.
    """
    from common.outbox import process_pending_batch

    run = BackgroundTaskRun.objects.create(
        task_name=OUTBOX_BATCH_TASK, status="running", success=False,
        payload={"action": "process_notification_outbox"})
    try:
        summary = process_pending_batch(batch_size=batch_size)
        run.status = "succeeded"
        run.success = True
        run.payload = summary
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "success", "payload", "finished_at"])
        return summary
    except Exception as exc:  # noqa: BLE001 - defensive: never hot-loop
        logger.exception("Outbox batch delivery failed")
        run.status = "failed"
        run.success = False
        run.error_summary = type(exc).__name__
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "success", "error_summary",
                                "finished_at"])
        return {"error": type(exc).__name__}


@shared_task(bind=True, name=OUTBOX_CLEANUP_TASK, max_retries=1,
             default_retry_delay=300)
def cleanup_notification_outbox(self, retention_days=None):
    """Periodic retention: delete terminal outbox rows past the cutoff.

    Only delivered/failed/cancelled rows are eligible; in-flight rows are never
    removed. One ``BackgroundTaskRun`` row records each cleanup for visibility.
    """
    from common.outbox import cleanup_outbox_events

    run = BackgroundTaskRun.objects.create(
        task_name=OUTBOX_CLEANUP_TASK, status="running", success=False,
        payload={"action": "cleanup_notification_outbox"})
    try:
        deleted = cleanup_outbox_events(retention_days=retention_days)
        run.status = "succeeded"
        run.success = True
        run.payload = {"deleted": deleted}
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "success", "payload", "finished_at"])
        return {"deleted": deleted}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Outbox cleanup failed")
        run.status = "failed"
        run.success = False
        run.error_summary = type(exc).__name__
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "success", "error_summary",
                                "finished_at"])
        return {"error": type(exc).__name__}


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

