"""Centralized outbound email notification preference checks.

Single source of truth for "should <user> receive an email for <category>?".

Every outbound email path (ticket events, SLA, maintenance, asset/system
alerts, scheduled reports) MUST resolve its decision through
:meth:`email_enabled_for` instead of inlining preference logic locally.

Policy:
- Essential / security transactional emails (email verification, password
  reset, security alerts) are NEVER suppressed by user preferences
  (:data:`ESSENTIAL_EMAIL_CATEGORIES` short-circuits to enabled).
- The global master switch is ``UserNotificationPreference.email_enabled``
  (falling back to the legacy ``User.receive_ticket_emails`` ticket-email
  master when no preference row exists yet). A disabled master switch stops
  all non-essential categories at once.
- Category-level opt-outs only affect their own category; disabling
  ``ticket_assignment`` must not block ``ticket_status_change`` or any
  unrelated category.
- Missing preference rows use sensible defaults (email enabled, every
  category enabled) so no user silently loses mail they never configured.
- In-app notifications are created independently of this module (they are
  always delivered) and must NOT route through preference checks.
- Scheduled report deliveries follow an explicit recipient policy: they go
  to the recipient list configured on the schedule and do not inherit
  unrelated per-user notification categories. That policy is expressed once
  via :func:`scheduled_report_delivery_enabled` instead of being applied ad
  hoc inside each delivery loop.

In-app notification helpers:
- `notify_user(user, category, title, message)` — creates an in-app
  notification for a single user.
- `notify_watchers(ticket, actor, title, message)` — creates in-app
  notifications for all watchers of a ticket.
"""
import hashlib
import re

from django.db import IntegrityError, transaction

from common.models import Notification, UserNotificationPreference

#: Transactional / security emails that are never suppressed by user
#: notification preferences (verification, password reset, security alerts).
ESSENTIAL_EMAIL_CATEGORIES = frozenset({
    "email_verification",
    "password_reset",
    "security_alert",
})

#: Category keys used by the email notification paths.
TICKET_ASSIGNMENT_CATEGORY = "ticket_assignment"
TICKET_STATUS_CATEGORY = "ticket_status_change"
TICKET_REPLY_CATEGORY = "ticket_reply"
SLA_CATEGORY = "sla_escalation"
MAINTENANCE_CATEGORY = "maintenance_reminder"
ASSET_CATEGORY = "asset_assignment"
SYSTEM_CATEGORY = "system_alert"
#: Knowledge Base review / publication events (submission, approval,
#: rejection, publication). In-app notifications are always delivered; email
#: is gated by this category preference.
KB_REVIEW_CATEGORY = "kb_review"


def get_user_preferences(user):
    """Return the user's notification preference row, creating it with
    defaults when missing. ``None`` when no user account is resolvable.
    """
    if user is None or not getattr(user, "pk", None):
        return None
    prefs, _created = UserNotificationPreference.objects.get_or_create(
        user=user)
    return prefs


_UNSET_PREFERENCE = object()


def email_enabled_for(user, category=None,
                      preference=_UNSET_PREFERENCE):
    """Centralized: should ``user`` receive an email for ``category``?

    - ``category`` is optional; ``None`` means "global master switch only".
    - Essential categories (verification, password reset, security alerts)
      always return True and are never suppressed.
    - Missing preference rows default to enabled (all categories opt-in by
      default), so legacy users keep receiving mail until they opt out.
    - The master switch (preference row or legacy ticket-email flag) wins
      over category-level opt-outs.
    - A disabled category never disables unrelated categories: each event
      passes its own category and only that category is evaluated.
    """
    if category in ESSENTIAL_EMAIL_CATEGORIES:
        return True
    if user is None or not getattr(user, "pk", None):
        # Unresolvable / system recipients fail open (current behaviour).
        return True
    prefs = (get_user_preferences(user) if preference is _UNSET_PREFERENCE
             else preference)
    master_enabled = True
    if prefs is not None and not prefs.email_enabled:
        master_enabled = False
    # Legacy global ticket-email master (self-service / profile toggle).
    if not master_enabled or not getattr(user, "receive_ticket_emails", True):
        return False
    if category is None:
        # Global switch only (e.g. ticket creation acknowledgements).
        return True
    if prefs is None:
        # No preference record yet -> sensible default (opt-in default True).
        return True
    return bool(prefs.categories.get(category, True))


def scheduled_report_delivery_enabled():
    """Explicit scheduled-report recipient policy.

    Scheduled reports are delivered to the recipient list explicitly chosen
    when the schedule was created (IT / staff authored). Deliveries do NOT
    inherit unrelated per-user notification categories; they are direct
    report emails. Always enabled at the preference layer.
    """
    return True


_SENSITIVE_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|signature|authorization|"
    r"credential|private[_-]?key)\b\s*[:=]\s*[\"']?[^\s,;}\"']+"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _safe_notification_text(value, limit):
    text = "" if value is None else str(value)
    text = _SENSITIVE_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _notification_recipient_allowed(user, actor=None):
    if user is None or not getattr(user, "pk", None):
        return False
    if not getattr(user, "is_active", True) or getattr(user, "is_deleted", False):
        return False
    if actor is not None and getattr(actor, "pk", None) == user.pk:
        return False
    return True


def _compute_dedupe_key(user, title, body, entity_type, object_id):
    """Compute a deterministic dedupe fingerprint from sanitized fields."""
    raw = f"{user.pk}|{title}|{body}|{entity_type}|{object_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def notify_user(
    user,
    category,
    title,
    message,
    entity_type=None,
    object_id=None,
    actor=None,
    dedupe=True,
    post_commit=True,
):
    """Create a real in-app Notification after the caller's commit.

    In-app delivery is independent of email preferences. Recipients are
    validated, content is sanitized, and no monitoring code is invoked, so
    notification delivery can never re-enter ticket automation.

    Database-level uniqueness on ``dedupe_key`` (conditional on
    ``is_deleted=False``) guarantees race-safe deduplication: concurrent
    attempts to create the same active notification result in exactly one
    row.  The duplicate caller receives ``None`` (consistent with the
    existing "already exists" return contract).
    """
    if not _notification_recipient_allowed(user, actor):
        return None

    safe_title = _safe_notification_text(title or "Notification", 255) or "Notification"
    safe_body = _safe_notification_text(message, 2000)
    safe_entity = _safe_notification_text(
        entity_type or f"notification.{category or 'general'}", 100
    ) or "notification.general"
    safe_object_id = _safe_notification_text(object_id, 100)
    dedupe_key = (
        _compute_dedupe_key(user, safe_title, safe_body, safe_entity, safe_object_id)
        if dedupe else None
    )

    def _write():
        # Fast path: Python-level check using the same fingerprint identity
        # enforced by the database constraint.  Avoids exception overhead in
        # the common case where no equivalent active notification exists.
        if dedupe and dedupe_key:
            existing = (
                Notification.objects.filter(
                    dedupe_key=dedupe_key,
                    is_deleted=False,
                )
                .first()
            )
            if existing:
                return None
        try:
            # Nested atomic savepoint so an IntegrityError here only rolls
            # back this insert, not the caller's surrounding transaction.
            with transaction.atomic():
                return Notification.objects.create(
                    recipient=user,
                    title=safe_title,
                    body=safe_body,
                    entity_type=safe_entity,
                    object_id=safe_object_id,
                    dedupe_key=dedupe_key,
                )
        except IntegrityError:
            # A concurrent request may have committed the equivalent
            # notification first.  Confirm before treating as dedup so
            # unrelated integrity errors (e.g. a FK violation on a
            # different column) still propagate.
            if dedupe and dedupe_key:
                existing = (
                    Notification.objects.filter(
                        dedupe_key=dedupe_key,
                        is_deleted=False,
                    )
                    .first()
                )
                if existing:
                    return None
            raise

    if post_commit:
        transaction.on_commit(_write)
        return None
    return _write()


def notify_watchers(
    ticket,
    actor,
    title,
    message,
    category=None,
    entity_type=None,
    dedupe=True,
    post_commit=True,
):
    """Notify distinct active watchers of ``ticket`` through Notification rows."""
    if ticket is None or not getattr(ticket, "pk", None):
        return

    recipients = {}
    for watch in ticket.watchers.filter(is_active=True, is_deleted=False):
        if _notification_recipient_allowed(watch.user, actor):
            recipients[watch.user_id] = watch.user

    for watcher in sorted(recipients.values(), key=lambda item: item.pk):
        notify_user(
            watcher,
            category,
            title,
            message,
            entity_type=entity_type or "tickets.Ticket",
            object_id=str(ticket.pk),
            actor=actor,
            dedupe=dedupe,
            post_commit=post_commit,
        )
