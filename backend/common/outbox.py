"""Transactional notification outbox — durable asynchronous email delivery.

Phase 66. This module is the single service boundary for the outbox:

* :func:`enqueue_email` — insert an outbox row *inside the caller's current
  database transaction* so it commits atomically with the business change.
* :func:`claim_event` / :func:`claim_batch` — race-safe worker claiming.
* :func:`deliver_event_core` / :func:`process_pending_batch` — delivery with
  bounded exponential backoff, lease recovery and idempotent finalisation.
* :func:`get_outbox_stats` — operational visibility for the dashboard.
* :func:`retry_event` / :func:`cancel_event` — privileged manual recovery.

Design notes
------------
Atomicity
    ``enqueue_email`` performs a plain ``INSERT`` in the ambient transaction.
    It deliberately does NOT defer the write to ``transaction.on_commit`` — the
    row must share the business transaction's fate. ``on_commit`` is used only
    for a best-effort low-latency *wake-up* after the row is durably committed;
    correctness never depends on it (the periodic scanner re-discovers missed
    rows).

Claiming
    A claim is an atomic conditional ``UPDATE`` guarded on
    ``status IN (pending, retry)`` and the retry schedule. Two workers racing
    on the same row: exactly one ``UPDATE`` matches a still-claimable row, the
    other matches zero rows. On PostgreSQL the batch scanner additionally uses
    ``select_for_update(skip_locked=True)`` to avoid wasted work under
    contention; on other backends the conditional update remains the
    correctness guarantee.

Delivery guarantee
    At-least-once. A worker may hand a message to SMTP and crash before the
    success is persisted; the recovered lease then re-delivers, producing a
    duplicate. Exactly-once SMTP delivery is impossible without provider-side
    idempotency keys and is explicitly not claimed.
"""
import hashlib
import json
import logging
import os
import random
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from common.models import NotificationOutboxEvent

logger = logging.getLogger(__name__)

#: Default processing lease. Must comfortably exceed the slowest expected SMTP
#: round-trip so a healthy worker is not racing its own lease, while staying
#: short enough that a crashed worker's events recover promptly.
DEFAULT_LEASE_SECONDS = 120


def _lease_seconds():
    return int(getattr(settings, "NOTIFICATION_OUTBOX_LEASE_SECONDS",
                       DEFAULT_LEASE_SECONDS))


def _new_worker_id():
    return f"{os.getpid()}-{uuid.uuid4().hex[:12]}"


def _sanitize_error(value):
    """Return a short, secret-free, single-line failure summary.

    Reuses the centralized notification text sanitiser (redacts
    password/secret/token patterns, strips control chars, collapses
    whitespace) so an exception message can never leak credentials into a
    stored row, an API response, or a Celery log.
    """
    from common.notifications import _safe_notification_text
    if isinstance(value, BaseException):
        text = f"{type(value).__name__}: {value}"
    else:
        text = "" if value is None else str(value)
    return _safe_notification_text(text, 500)


def _backoff_seconds(attempts, rng=None):
    """Bounded exponential backoff (seconds) with jitter for attempt number
    ``attempts`` (1-based count of attempts already made)."""
    rng = rng or random
    base = float(getattr(settings, "NOTIFICATION_OUTBOX_RETRY_BASE_SECONDS", 30))
    ceiling = float(getattr(settings, "NOTIFICATION_OUTBOX_RETRY_MAX_SECONDS", 3600))
    exponent = max(0, int(attempts) - 1)
    delay = min(ceiling, base * (2 ** exponent))
    # +/-20% jitter avoids synchronised retry storms across workers.
    jitter = delay * 0.2 * rng.random()
    return min(ceiling, delay + jitter)


# ---------------------------------------------------------------------------
# Enqueue (atomic with the business transaction)
# ---------------------------------------------------------------------------

def _compute_dedupe_key(event_type, to_email, subject, ticket_id):
    raw = f"{event_type}|{(to_email or '').lower()}|{subject}|{ticket_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def enqueue_email(*, event_type, to_email, subject=None, body=None,
                  recipient=None, category="", template=None, context=None,
                  notification=None, ticket_id=None, dedupe=True,
                  max_attempts=None, wakeup=True):
    """Insert a pending outbox event in the current transaction.

    The row is written with a plain ``INSERT`` in the ambient transaction so it
    commits or rolls back with the caller's business change. Returns the
    created (or pre-existing active duplicate) event, or ``None`` when there is
    no recipient address.

    Raises ``ValueError`` for an oversized payload. A duplicate registration of
    the same logical delivery while an active row exists returns that row
    instead of creating a second one.
    """
    to_email = (to_email or "").strip()
    if not to_email:
        return None

    payload = {}
    if subject is not None:
        payload["subject"] = str(subject)
    if body is not None:
        payload["body"] = str(body)
    if template:
        payload["template"] = template
    if context is not None:
        payload["context"] = context
    if ticket_id is not None:
        payload["ticket_id"] = ticket_id

    payload_bytes = len(json.dumps(payload, default=str).encode("utf-8"))
    if payload_bytes > NotificationOutboxEvent.MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"notification outbox payload too large: {payload_bytes} bytes "
            f"(max {NotificationOutboxEvent.MAX_PAYLOAD_BYTES})")

    dedupe_key = None
    if dedupe:
        dedupe_key = _compute_dedupe_key(event_type, to_email, subject,
                                         ticket_id)

    if max_attempts is None:
        max_attempts = getattr(settings, "NOTIFICATION_OUTBOX_MAX_ATTEMPTS", 5)

    recipient_id = getattr(recipient, "pk", None) if recipient is not None else None

    try:
        with transaction.atomic():
            event = NotificationOutboxEvent.objects.create(
                event_type=event_type,
                channel="email",
                recipient_id=recipient_id,
                recipient_email=to_email,
                category=category or "",
                payload=payload,
                dedupe_key=dedupe_key,
                status="pending",
                next_attempt_at=None,
                max_attempts=max_attempts,
                notification=notification,
            )
    except IntegrityError:
        if dedupe_key:
            event = (NotificationOutboxEvent.objects
                     .filter(dedupe_key=dedupe_key)
                     .exclude(status__in=NotificationOutboxEvent.TERMINAL_STATUSES)
                     .first())
            if event is not None:
                return event
        raise

    if wakeup:
        transaction.on_commit(lambda: _schedule_delivery(event.id))
    return event


def _schedule_delivery(event_id):
    """Best-effort low-latency wake-up. Correctness does not depend on it."""
    try:
        from common.tasks import deliver_outbox_event
    except Exception:  # pragma: no cover - import must never break enqueue
        logger.exception("Could not import outbox delivery task")
        return
    if getattr(settings, "NOTIFICATION_OUTBOX_EAGER", False):
        # Test / single-process mode: run inline without a broker.
        try:
            deliver_outbox_event.apply(args=[str(event_id)])
        except Exception:
            logger.warning("Inline outbox delivery failed for %s", event_id)
        return
    try:
        deliver_outbox_event.delay(str(event_id))
    except Exception:
        # Broker unavailable: the periodic scanner delivers it later.
        logger.info("Outbox wake-up deferred to scanner for %s", event_id)


# ---------------------------------------------------------------------------
# Claiming (race-safe)
# ---------------------------------------------------------------------------

def _claimable_q(now):
    return (Q(status__in=NotificationOutboxEvent.CLAIMABLE_STATUSES)
            & (Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)))


def _claim_update(now, lease_seconds, worker_id):
    return NotificationOutboxEvent.objects.filter(
        status__in=NotificationOutboxEvent.CLAIMABLE_STATUSES
    ).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
    ).update(
        status="processing",
        attempts=F("attempts") + 1,
        last_attempt_at=now,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
        claimed_by=worker_id,
    )


def claim_event(event_id, now=None, lease_seconds=None, worker_id=None):
    """Atomically claim a single event. Returns True iff this caller won it."""
    now = now or timezone.now()
    lease_seconds = lease_seconds or _lease_seconds()
    worker_id = worker_id or _new_worker_id()
    claimed = NotificationOutboxEvent.objects.filter(
        id=event_id,
        status__in=NotificationOutboxEvent.CLAIMABLE_STATUSES,
    ).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
    ).update(
        status="processing",
        attempts=F("attempts") + 1,
        last_attempt_at=now,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
        claimed_by=worker_id,
    )
    return claimed == 1


def claim_batch(limit, now=None, lease_seconds=None, worker_id=None):
    """Claim up to ``limit`` due events and return their ids.

    On PostgreSQL the candidate rows are locked with ``skip_locked`` so
    concurrent scanners do not contend. On every backend the per-row
    conditional update guarantees exactly one winner even if two scanners read
    the same candidate list.
    """
    now = now or timezone.now()
    lease_seconds = lease_seconds or _lease_seconds()
    worker_id = worker_id or _new_worker_id()
    limit = max(1, int(limit))

    base = (NotificationOutboxEvent.objects
            .filter(status__in=NotificationOutboxEvent.CLAIMABLE_STATUSES)
            .filter(Q(next_attempt_at__isnull=True)
                    | Q(next_attempt_at__lte=now)))

    claimed_ids = []
    with transaction.atomic():
        if connection.vendor == "postgresql":
            candidates = list(
                base.select_for_update(skip_locked=True)
                .order_by("next_attempt_at", "created_at")
                .values_list("id", flat=True)[:limit])
        else:  # SQLite (dev / non-postgres CI): conditional update is the guard.
            candidates = list(
                base.order_by("next_attempt_at", "created_at")
                .values_list("id", flat=True)[:limit])
        for cid in candidates:
            won = NotificationOutboxEvent.objects.filter(
                id=cid,
                status__in=NotificationOutboxEvent.CLAIMABLE_STATUSES,
            ).filter(
                Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
            ).update(
                status="processing",
                attempts=F("attempts") + 1,
                last_attempt_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                claimed_by=worker_id,
            )
            if won == 1:
                claimed_ids.append(cid)
    return claimed_ids


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def _deliver_email(event):
    """Attempt one external email delivery.

    Returns ``(outcome, error)`` where outcome is one of ``delivered``,
    ``retry``, ``failed``, ``cancelled``.
    """
    if event.channel != "email":
        return "failed", f"unsupported_channel:{event.channel}"

    to_email = (event.recipient_email or "").strip()
    if not to_email:
        return "cancelled", "missing_recipient"

    # Recipient re-validation: never mail a deactivated / soft-deleted account.
    user = None
    if event.recipient_id:
        from accounts.models import User
        user = User.objects.filter(pk=event.recipient_id).first()
        if user is None or not getattr(user, "is_active", True):
            return "cancelled", "recipient_inactive_or_deleted"

    # Preference re-check at delivery time (a user may have opted out after the
    # event was enqueued). Essential categories are never suppressed here
    # because this path is never used for them.
    category = event.category or None
    if user is not None:
        from common.notifications import email_enabled_for
        if not email_enabled_for(user, category=category):
            return "cancelled", "recipient_opted_out"

    payload = event.payload if isinstance(event.payload, dict) else {}
    subject = payload.get("subject") or event.event_type
    body = payload.get("body", "")

    from common.email import send_email
    ok = send_email(subject, body, to_email)
    if ok:
        return "delivered", ""
    # SMTP failures are usually transient (connection / timeout): retry with
    # bounded backoff until max_attempts, then mark failed.
    return "retry", "smtp_send_failed"


def finalize_event(event_id, worker_id, outcome, error, now=None):
    """Persist a delivery outcome for a row this worker still owns.

    Returns the resulting row status, or ``None`` if this worker no longer owns
    the row (its lease expired and another worker recovered it).
    """
    now = now or timezone.now()
    fields = ["status", "lease_expires_at", "updated_at"]
    with transaction.atomic():
        event = (NotificationOutboxEvent.objects
                 .filter(id=event_id, status="processing", claimed_by=worker_id)
                 .first())
        if event is None:
            # Lease expired and another worker recovered it, or already final.
            return None
        event.lease_expires_at = None
        if outcome == "delivered":
            event.status = "delivered"
            event.delivered_at = now
            event.last_error = ""
            fields += ["delivered_at", "last_error"]
        elif outcome == "cancelled":
            event.status = "cancelled"
            event.cancel_reason = _sanitize_error(error)[:255]
            fields += ["cancel_reason"]
        elif outcome == "retry" and event.attempts < event.max_attempts:
            event.status = "retry"
            event.next_attempt_at = now + timedelta(
                seconds=_backoff_seconds(event.attempts))
            event.last_error = _sanitize_error(error)
            fields += ["next_attempt_at", "last_error"]
        else:
            event.status = "failed"
            event.last_error = _sanitize_error(error)
            fields += ["last_error"]
        event.save(update_fields=fields)
        return event.status


def deliver_event_core(event_id, worker_id=None, now=None):
    """Claim and deliver a single event end-to-end. Returns the final status
    (``delivered`` / ``retry`` / ``failed`` / ``cancelled``), or ``skipped`` /
    ``missing`` when the row was not claimable / vanished.

    Used by the per-event wake-up task and directly by tests. Claiming is
    idempotent: if another worker already owns the row, this is a no-op and
    returns ``skipped``.
    """
    worker_id = worker_id or _new_worker_id()
    if not claim_event(event_id, now=now, worker_id=worker_id):
        return "skipped"
    event = NotificationOutboxEvent.objects.filter(id=event_id).first()
    if event is None:  # pragma: no cover - defensive
        return "missing"
    try:
        outcome, error = _deliver_email(event)
    except Exception as exc:  # noqa: BLE001 - never let delivery raise
        outcome, error = "retry", _sanitize_error(exc)
    return finalize_event(event_id, worker_id, outcome, error) or "skipped"


def recover_expired_claims(now=None, limit=500):
    """Return abandoned ``processing`` rows whose lease expired to ``retry``
    (or ``failed`` once attempts are exhausted). Returns the count recovered."""
    now = now or timezone.now()
    recovered = 0
    with transaction.atomic():
        expired = list(
            NotificationOutboxEvent.objects
            .filter(status="processing", lease_expires_at__isnull=False,
                    lease_expires_at__lte=now)
            .order_by("lease_expires_at")
            .values_list("id", "attempts", "max_attempts")[:limit])
        for eid, attempts, max_attempts in expired:
            if attempts >= max_attempts:
                n = NotificationOutboxEvent.objects.filter(
                    id=eid, status="processing").update(
                    status="failed", lease_expires_at=None, claimed_by="",
                    last_error="lease_expired_max_attempts")
            else:
                n = NotificationOutboxEvent.objects.filter(
                    id=eid, status="processing").update(
                    status="retry", lease_expires_at=None, claimed_by="",
                    next_attempt_at=now)
            recovered += n
    return recovered


def process_pending_batch(batch_size=None, worker_id=None):
    """Periodic worker entry point: recover expired leases, then claim and
    deliver a bounded batch of due events."""
    if batch_size is None:
        batch_size = getattr(settings, "NOTIFICATION_OUTBOX_BATCH_SIZE", 100)
    worker_id = worker_id or _new_worker_id()
    now = timezone.now()
    recovered = recover_expired_claims(now)
    ids = claim_batch(batch_size, now=now, worker_id=worker_id)
    results = {"claimed": len(ids), "delivered": 0, "retry": 0,
               "failed": 0, "cancelled": 0, "recovered": recovered}
    for eid in ids:
        event = NotificationOutboxEvent.objects.filter(id=eid).first()
        if event is None:  # pragma: no cover - defensive
            continue
        try:
            outcome, error = _deliver_email(event)
        except Exception as exc:  # noqa: BLE001
            outcome, error = "retry", _sanitize_error(exc)
        final_status = finalize_event(eid, worker_id, outcome, error)
        if final_status in ("delivered", "retry", "failed", "cancelled"):
            results[final_status] += 1
    try:
        results["alerts"] = evaluate_outbox_alerts()
    except Exception:
        logger.exception("Outbox alert evaluation failed")
        results["alerts"] = {"evaluated": False, "reason": "exception"}
    return results


# ---------------------------------------------------------------------------
# Retention / cleanup
# ---------------------------------------------------------------------------

def cleanup_outbox_events(retention_days=None):
    """Delete terminal outbox rows older than the retention window.

    Only ``delivered`` / ``failed`` / ``cancelled`` rows past the cutoff are
    removed; pending / retry / processing rows are never touched, so an
    in-flight or retrying delivery can never be lost to cleanup. Returns the
    number of rows deleted. Runs on the periodic schedule, so it is bounded
    and never blocks a request.
    """
    if retention_days is None:
        retention_days = getattr(
            settings, "NOTIFICATION_OUTBOX_RETENTION_DAYS", 30)
    cutoff = timezone.now() - timedelta(days=int(retention_days))
    deleted, _ = NotificationOutboxEvent.objects.filter(
        status__in=NotificationOutboxEvent.TERMINAL_STATUSES,
        updated_at__lt=cutoff,
    ).delete()
    return deleted


# ---------------------------------------------------------------------------
# Privileged manual operations
# ---------------------------------------------------------------------------

RETRYABLE_STATUSES = ("failed", "cancelled")
CANCELLABLE_STATUSES = ("pending", "retry", "processing")


def retry_event(event_id, now=None):
    """Re-queue a failed/cancelled event for a fresh delivery budget.

    Returns ``(ok, event_or_reason)``. Only failed/cancelled rows are eligible;
    active or delivered rows are rejected so a manual action cannot duplicate
    an in-flight or completed delivery. The status guard makes the transition
    race-safe against a concurrent worker without requiring row locks.
    """
    now = now or timezone.now()
    with transaction.atomic():
        claimed = NotificationOutboxEvent.objects.filter(
            id=event_id, status__in=RETRYABLE_STATUSES).update(
            status="pending", attempts=0, next_attempt_at=None,
            lease_expires_at=None, claimed_by="", cancel_reason="")
        if not claimed:
            exists = NotificationOutboxEvent.objects.filter(id=event_id).exists()
            return False, ("not_found" if not exists else "not_retryable")
        event = NotificationOutboxEvent.objects.filter(id=event_id).first()
    transaction.on_commit(lambda: _schedule_delivery(event.id))
    return True, event


def cancel_event(event_id, reason="", now=None):
    """Cancel a pending/retry/processing event so it is never delivered."""
    now = now or timezone.now()
    with transaction.atomic():
        claimed = NotificationOutboxEvent.objects.filter(
            id=event_id, status__in=CANCELLABLE_STATUSES).update(
            status="cancelled",
            cancel_reason=_sanitize_error(reason)[:255] or "cancelled_by_admin",
            lease_expires_at=None, claimed_by="")
        if not claimed:
            exists = NotificationOutboxEvent.objects.filter(id=event_id).exists()
            return False, ("not_found" if not exists else "not_cancellable")
        event = NotificationOutboxEvent.objects.filter(id=event_id).first()
    return True, event


# ---------------------------------------------------------------------------
# Operational visibility
# ---------------------------------------------------------------------------

def get_outbox_stats():
    """Aggregate delivery metrics for the operations dashboard."""
    now = timezone.now()
    counts = NotificationOutboxEvent.objects.aggregate(
        pending=Count("id", filter=Q(status="pending")),
        retry=Count("id", filter=Q(status="retry")),
        processing=Count("id", filter=Q(status="processing")),
        delivered=Count("id", filter=Q(status="delivered")),
        failed=Count("id", filter=Q(status="failed")),
        cancelled=Count("id", filter=Q(status="cancelled")),
    )
    oldest = (NotificationOutboxEvent.objects
              .filter(status__in=NotificationOutboxEvent.CLAIMABLE_STATUSES)
              .filter(Q(next_attempt_at__isnull=True)
                      | Q(next_attempt_at__lte=now))
              .order_by("created_at")
              .values_list("created_at", flat=True).first())
    oldest_age = int((now - oldest).total_seconds()) if oldest else None
    expired = NotificationOutboxEvent.objects.filter(
        status="processing", lease_expires_at__isnull=False,
        lease_expires_at__lte=now).count()
    delivered_24h = NotificationOutboxEvent.objects.filter(
        status="delivered", delivered_at__gte=now - timedelta(hours=24)).count()
    failed_24h = NotificationOutboxEvent.objects.filter(
        status="failed", updated_at__gte=now - timedelta(hours=24)).count()
    recent_failures = list(
        NotificationOutboxEvent.objects.filter(status="failed")
        .order_by("-updated_at")
        .values("id", "event_type", "recipient_email", "attempts",
                "last_error", "updated_at")[:10])
    return {
        "pending": counts["pending"],
        "retry": counts["retry"],
        "processing": counts["processing"],
        "delivered": counts["delivered"],
        "failed": counts["failed"],
        "cancelled": counts["cancelled"],
        "total": NotificationOutboxEvent.objects.count(),
        "oldest_pending_age_seconds": oldest_age,
        "expired_claims": expired,
        "delivered_last_24h": delivered_24h,
        "failed_last_24h": failed_24h,
        "recent_failures": recent_failures,
    }


# ---------------------------------------------------------------------------
# Operational alerting (Phase 66 hardening)
# ---------------------------------------------------------------------------

OUTBOX_ALERT_DEDUPE_PREFIX = "outbox.health"


def _resolve_outbox_alert(dedup_key, now=None):
    """Resolve an open/acknowledged outbox alert when condition clears."""
    from common.models import OperationalAlert
    now = now or timezone.now()
    OperationalAlert.objects.filter(
        dedup_key=dedup_key,
        status__in=["open", "acknowledged"],
    ).update(
        status="resolved",
        resolved=True,
        resolved_at=now,
        resolved_by=None,
        last_occurred=now,
    )


def evaluate_outbox_alerts(stats=None, now=None):
    """Create/update/resolve outbox operational alerts.

    Thresholds are configurable via settings/env vars with conservative
    defaults. Alerting failures must never stop outbox processing.
    """
    now = now or timezone.now()
    stats = stats or get_outbox_stats()

    try:
        from common.monitoring_service import create_or_update_alert
    except Exception:
        logger.exception("Outbox alerting unavailable: cannot import alert service")
        return {"evaluated": False, "reason": "import_error"}

    thresholds = {
        "failed": int(getattr(settings, "NOTIFICATION_OUTBOX_ALERT_FAILED_COUNT", 10)),
        "expired_claims": int(getattr(settings, "NOTIFICATION_OUTBOX_ALERT_EXPIRED_CLAIMS", 1)),
        "oldest_pending_age_seconds": int(getattr(settings, "NOTIFICATION_OUTBOX_ALERT_OLDEST_PENDING_SECONDS", 900)),
        "oldest_retry_age_seconds": int(getattr(settings, "NOTIFICATION_OUTBOX_ALERT_OLDEST_RETRY_SECONDS", 1800)),
        "backlog": int(getattr(settings, "NOTIFICATION_OUTBOX_ALERT_BACKLOG", 100)),
    }

    oldest_retry_age = None
    try:
        oldest_retry = (NotificationOutboxEvent.objects
                        .filter(status="retry")
                        .order_by("next_attempt_at", "created_at")
                        .values_list("created_at", flat=True).first())
        if oldest_retry:
            oldest_retry_age = int((now - oldest_retry).total_seconds())
    except Exception:
        logger.exception("Outbox alerting: failed to compute oldest retry age")

    backlog = int(stats.get("pending", 0)) + int(stats.get("retry", 0)) + int(stats.get("processing", 0))

    checks = [
        {
            "key": f"{OUTBOX_ALERT_DEDUPE_PREFIX}.failed_count",
            "value": int(stats.get("failed", 0)),
            "threshold": thresholds["failed"],
            "severity": "critical",
            "title": "Outbox failed-event threshold exceeded",
            "description": "Notification outbox has accumulated failed events above threshold.",
        },
        {
            "key": f"{OUTBOX_ALERT_DEDUPE_PREFIX}.expired_claims",
            "value": int(stats.get("expired_claims", 0)),
            "threshold": thresholds["expired_claims"],
            "severity": "warning",
            "title": "Outbox expired claims detected",
            "description": "Processing outbox events have expired leases and may indicate worker crashes.",
        },
        {
            "key": f"{OUTBOX_ALERT_DEDUPE_PREFIX}.oldest_pending_age",
            "value": int(stats.get("oldest_pending_age_seconds") or 0),
            "threshold": thresholds["oldest_pending_age_seconds"],
            "severity": "warning",
            "title": "Outbox oldest pending age exceeded",
            "description": "Oldest claimable outbox event has exceeded the pending-age threshold.",
        },
        {
            "key": f"{OUTBOX_ALERT_DEDUPE_PREFIX}.oldest_retry_age",
            "value": int(oldest_retry_age or 0),
            "threshold": thresholds["oldest_retry_age_seconds"],
            "severity": "warning",
            "title": "Outbox oldest retry age exceeded",
            "description": "Oldest retry outbox event has exceeded the retry-age threshold.",
        },
        {
            "key": f"{OUTBOX_ALERT_DEDUPE_PREFIX}.backlog",
            "value": backlog,
            "threshold": thresholds["backlog"],
            "severity": "warning",
            "title": "Outbox backlog threshold exceeded",
            "description": "Pending/retry/processing outbox backlog exceeded threshold.",
        },
    ]

    results = []
    for check in checks:
        dedup_key = check["key"]
        try:
            if check["value"] >= check["threshold"]:
                create_or_update_alert(
                    component="email",
                    severity=check["severity"],
                    title=check["title"],
                    description=check["description"],
                    dedup_key=dedup_key,
                    details={
                        "metric": dedup_key,
                        "value": check["value"],
                        "threshold": check["threshold"],
                        "pending": stats.get("pending"),
                        "retry": stats.get("retry"),
                        "processing": stats.get("processing"),
                        "failed": stats.get("failed"),
                        "oldest_pending_age_seconds": stats.get("oldest_pending_age_seconds"),
                        "expired_claims": stats.get("expired_claims"),
                    },
                )
                results.append({"key": dedup_key, "state": "active"})
            else:
                _resolve_outbox_alert(dedup_key, now=now)
                results.append({"key": dedup_key, "state": "resolved"})
        except Exception:
            logger.exception("Outbox alert evaluation failed for %s", dedup_key)
            results.append({"key": dedup_key, "state": "error"})

    return {"evaluated": True, "results": results, "thresholds": thresholds}