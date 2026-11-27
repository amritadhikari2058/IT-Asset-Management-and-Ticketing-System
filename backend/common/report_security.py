"""Authorization helpers for scheduled report generation outside HTTP views.

Scheduled reports are rendered by calling report view functions directly from
Celery tasks and retry helpers. DRF decorators on those view functions are not
a sufficient authorization boundary for direct calls, so this module provides
one explicit, fail-closed check shared by every execution path.
"""
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.exceptions import PermissionDenied

from common.permissions import is_it_staff


def validate_scheduled_report_owner(saved_report):
    """Return the saved report's active IT-staff owner, or raise.

    Missing/deleted reports, missing/inactive/unauthenticated owners, and
    non-IT-staff owners are all rejected before any report data is generated
    or delivered.
    """
    if saved_report is None or getattr(saved_report, "is_deleted", False):
        raise PermissionDenied(
            "Scheduled report references a missing or deleted saved report.")
    try:
        owner = saved_report.user
    except ObjectDoesNotExist:
        owner = None
    if owner is None or not getattr(owner, "pk", None):
        raise PermissionDenied("Scheduled report owner is missing.")
    if not getattr(owner, "is_authenticated", False):
        raise PermissionDenied("Scheduled report owner is unauthenticated.")
    if not getattr(owner, "is_active", False):
        raise PermissionDenied("Scheduled report owner is inactive.")
    if not is_it_staff(owner):
        raise PermissionDenied("Scheduled report owner must be IT staff.")
    return owner
