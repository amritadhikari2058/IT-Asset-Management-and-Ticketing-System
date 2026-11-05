"""Satisfaction survey lifecycle and aggregate reporting."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone

from common.audit import log_action
from tickets.models import Ticket, TicketSatisfactionSurvey

User = get_user_model()


def _is_it_staff(user):
    return bool(
        user and user.is_authenticated
        and (getattr(user, "role", "") in ("system_admin", "it_manager", "it_support")
             or getattr(user, "is_superuser", False))
    )


def _is_manager_plus(user):
    return bool(
        user and user.is_authenticated
        and (getattr(user, "role", "") in ("system_admin", "it_manager")
             or getattr(user, "is_superuser", False))
    )


def get_survey(ticket, user):
    """Requester: own survey. Staff: authorized ticket survey."""
    try:
        return TicketSatisfactionSurvey.objects.get(
            ticket=ticket, requester=user, is_deleted=False)
    except TicketSatisfactionSurvey.DoesNotExist:
        return None


def submit_survey(ticket, validated_data, actor):
    """Authenticated requester submits a pending, non-expired survey."""
    if not getattr(actor, "is_authenticated", False):
        raise PermissionDenied("Authentication required.")
    if ticket.requester_id != actor.pk:
        raise PermissionDenied("Only the requester may submit this survey.")
    survey = TicketSatisfactionSurvey.objects.filter(
        ticket=ticket, requester=actor, is_deleted=False,
        status="pending").first()
    if not survey:
        raise ValidationError("No pending survey for this ticket.")
    if survey.expires_at and timezone.now() > survey.expires_at:
        survey.status = "expired"
        survey.save(update_fields=["status", "updated_at"])
        raise ValidationError("Survey has expired.")
    if survey.status != "pending":
        raise ValidationError("Survey already submitted.")

    rating = validated_data.get("rating")
    if rating is None or not (1 <= int(rating) <= 5):
        raise ValidationError("Rating must be between 1 and 5.")
    comments = (validated_data.get("comments") or "")[:1000]

    with transaction.atomic():
        survey.rating = int(rating)
        survey.resolution_helpful = validated_data.get("resolution_helpful")
        survey.response_time_satisfied = validated_data.get("response_time_satisfied")
        survey.communication_satisfied = validated_data.get("communication_satisfied")
        survey.comments = comments
        survey.status = "submitted"
        survey.submitted_at = timezone.now()
        survey.save(update_fields=[
            "rating", "resolution_helpful", "response_time_satisfied",
            "communication_satisfied", "comments", "status",
            "submitted_at", "updated_at"])
        _write_history(ticket, actor, "satisfaction_submitted",
                       new={"rating": survey.rating})
        log_action(actor=actor, action="update", instance=ticket,
                   details={"satisfaction_rating": survey.rating})
    return survey


class PermissionDenied(Exception):
    pass


class ValidationError(Exception):
    pass


def _write_history(ticket, actor, action, old=None, new=None, note=""):
    from tickets.models import TicketHistory
    TicketHistory.objects.create(ticket=ticket, actor=actor, action=action,
                                 old_values=old or {}, new_values=new or {},
                                 note=note or "")


def satisfaction_report(filters, user):
    """Aggregate satisfaction metrics for IT Manager / System Admin."""
    if not _is_manager_plus(user):
        raise PermissionDenied("Management metrics are staff-only.")
    qs = TicketSatisfactionSurvey.objects.filter(
        is_deleted=False, status="submitted")
    qs = _apply_report_filters(qs, filters)
    total = qs.count()
    if total == 0:
        return {
            "response_count": 0, "average_rating": None,
            "rating_distribution": {str(i): 0 for i in range(1, 6)},
            "satisfaction_percentage": None,
            "resolution_helpful_percentage": None,
            "response_time_satisfied_percentage": None,
            "communication_satisfied_percentage": None,
            "by_category": [], "by_queue": [], "by_assignee": [],
            "by_department": [], "reopened_vs_not": {},
        }
    avg = qs.aggregate(avg=Avg("rating"))["avg"]
    dist = {str(i): 0 for i in range(1, 6)}
    for row in qs.values("rating").annotate(c=Count("id")):
        dist[str(row["rating"])] = row["c"]
    helpful = qs.filter(resolution_helpful=True).count()
    rt = qs.filter(response_time_satisfied=True).count()
    comm = qs.filter(communication_satisfied=True).count()
    return {
        "response_count": total,
        "average_rating": round(avg, 2) if avg is not None else None,
        "rating_distribution": dist,
        "satisfaction_percentage": round(
            qs.filter(rating__gte=4).count() * 100.0 / total, 2),
        "resolution_helpful_percentage": round(helpful * 100.0 / total, 2),
        "response_time_satisfied_percentage": round(rt * 100.0 / total, 2),
        "communication_satisfied_percentage": round(comm * 100.0 / total, 2),
        "by_category": [], "by_queue": [], "by_assignee": [],
        "by_department": [], "reopened_vs_not": {},
    }


def _apply_report_filters(qs, filters):
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if date_from:
        qs = qs.filter(submitted_at__gte=date_from)
    if date_to:
        qs = qs.filter(submitted_at__lte=date_to)
    return qs
