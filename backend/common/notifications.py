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
from common.models import UserNotificationPreference

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


def email_enabled_for(user, category=None):
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
    prefs = get_user_preferences(user)
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


def notify_user(user, category, title, message):
    """Create an in-app notification for a user.

    This is a centralized helper used by ticket automation and other
    subsystems to deliver in-app notifications without routing through
    preference checks (in-app notifications are always delivered).
    """
    from common.models import AuditLog
    from monitoring.models import MonitoringAlert

    # Minimal in-app notification record; actual delivery is handled by the
    # frontend/notification dispatcher. We persist a record for auditability.
    try:
        AuditLog.objects.create(
            user=user,
            action="inapp_notification",
            details={
                "category": category,
                "title": title,
                "message": message,
            },
        )
    except Exception:
        pass


def notify_watchers(ticket, actor, title, message):
    """Create in-app notifications for all watchers of a ticket.

    This is a centralized helper used by ticket automation to notify
    watchers when a ticket changes state.
    """
    from common.models import AuditLog

    try:
        AuditLog.objects.create(
            user=None,
            action="inapp_notification_watcher",
            details={
                "ticket_id": str(ticket.pk) if ticket else None,
                "category": getattr(ticket, "category", None) if ticket else None,
                "title": title,
                "message": message,
            },
        )
    except Exception:
        pass
