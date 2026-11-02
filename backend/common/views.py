"""Recycle bin, audit logs, notifications.

- Ordinary DELETE on business viewsets soft-deletes (see per-app views).
- This module is the ONLY place exposing deleted rows + restore +
  permanent deletion. Permanent deletion is System-Admin-only, requires
  explicit {"confirm": "<id>"} and writes a protected AuditLog.
"""
import logging
from datetime import datetime, time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import (action, api_view, permission_classes,
                                        renderer_classes)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.audit import log_action
from common.models import (AuditLog, BackgroundTaskRun, EmailProcessing,
                           Notification, SavedReport, ScheduledReport,
                           ScheduledReportRun)
from common.permissions import IsITStaff, IsSystemAdmin, is_system_admin
from common.serializers import (
    AuditLogSerializer, NotificationSerializer, RecycleBinEntrySerializer,
    SavedReportSerializer, ScheduledReportSerializer,
    ScheduledReportRunSerializer,
    UserNotificationPreferenceSerializer,
)
from common.exports import EXPORT_RENDERER_CLASSES

logger = logging.getLogger(__name__)


def _deleted_entries(entity_filter=None, date_from=None, date_to=None,
                     deleted_by_id=None):
    """Collect soft-deleted rows across entity types (admin view)."""
    from accounts.models import Department, User
    from assets.models import Asset, AssetAttachment, AssetCategory
    from tickets.models import Ticket, TicketAttachment, TicketCategory

    registry = [
        ("accounts.User", User),
        ("accounts.Department", Department),
        ("assets.Asset", Asset),
        ("assets.AssetCategory", AssetCategory),
        ("assets.AssetAttachment", AssetAttachment),
        ("tickets.Ticket", Ticket),
        ("tickets.TicketCategory", TicketCategory),
        ("tickets.TicketAttachment", TicketAttachment),
        ("common.Notification", Notification),
    ]
    out = []
    for entity_type, model in registry:
        if entity_filter and entity_filter != entity_type:
            continue
        qs = model.all_objects.filter(is_deleted=True)
        if date_from:
            qs = qs.filter(deleted_at__gte=date_from)
        if date_to:
            qs = qs.filter(deleted_at__lte=date_to)
        if deleted_by_id:
            qs = qs.filter(deleted_by_id=deleted_by_id)
        for obj in qs.order_by("-deleted_at")[:500]:
            by = getattr(obj, "deleted_by", None)
            out.append({
                "entity_type": entity_type,
                "object_id": str(obj.pk),
                "repr": str(obj)[:255],
                "deleted_at": getattr(obj, "deleted_at", None),
                "deleted_by": str(by) if by else None,
                "deletion_reason": getattr(obj, "deletion_reason", "") or "",
            })
    out.sort(key=lambda e: str(e["deleted_at"] or ""), reverse=True)
    return out


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsSystemAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        action = p.get("action")
        if action:
            allowed = {key for key, _label in AuditLog.ACTION_CHOICES}
            if action not in allowed:
                from rest_framework.exceptions import ValidationError
                raise ValidationError(
                    {"action": f"Unknown action. Allowed: {sorted(allowed)}."})
            qs = qs.filter(action=action)
        entity_type = p.get("entity_type")
        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        for param, lookup in (("date_from", "timestamp__date__gte"),
                              ("date_to", "timestamp__date__lte")):
            raw = p.get(param)
            if raw:
                import datetime
                try:
                    day = datetime.date.fromisoformat(raw)
                except ValueError:
                    from rest_framework.exceptions import ValidationError
                    raise ValidationError(
                        {param: "Use ISO date format YYYY-MM-DD."})
                qs = qs.filter(**{lookup: day})
        return qs


class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user)
        p = self.request.query_params
        is_read = p.get("is_read")
        if is_read in ("true", "false"):
            qs = qs.filter(is_read=is_read == "true")
        entity_type = p.get("entity_type")
        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        q = p.get("q")
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))
        return qs

    def perform_create(self, serializer):
        serializer.save(recipient=self.request.user)

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        """Unread count for the caller's badge (soft-deleted rows excluded)."""
        count = Notification.objects.filter(
            recipient=request.user, is_read=False).count()
        return Response({"count": count})

    def destroy(self, request, *args, **kwargs):
        # Normal delete = soft delete, never hard.
        obj = self.get_object()
        obj.soft_delete(by_user=request.user, reason="notification dismissed")
        log_action(actor=request.user, action="soft_delete", instance=obj,
                   reason="notification dismissed")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        """Mark the caller's own unread notifications as read.

        Own-notifications only (queryset is recipient-scoped), soft-deleted
        rows excluded by the default manager, idempotent: repeats return 0.
        This is NOT dismissal — rows stay visible until deleted.
        """
        updated = self.get_queryset().filter(is_read=False).update(
            is_read=True)
        return Response({"updated": updated})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def recycle_bin_list(request):
    if not is_system_admin(request.user):
        return Response({"detail": "System Admin only."}, status=403)
    entries = _deleted_entries(
        entity_filter=request.query_params.get("entity_type"),
        date_from=request.query_params.get("date_from"),
        date_to=request.query_params.get("date_to"),
        deleted_by_id=request.query_params.get("deleted_by"),
    )
    return Response(RecycleBinEntrySerializer(entries, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def recycle_bin_detail(request, entity_type, pk):
    if not is_system_admin(request.user):
        return Response({"detail": "System Admin only."}, status=403)
    obj = _resolve(entity_type, pk)
    if obj is None or not obj.is_deleted:
        return Response({"detail": "Deleted record not found."}, status=404)
    by = getattr(obj, "deleted_by", None)
    return Response({
        "entity_type": entity_type, "object_id": str(obj.pk),
        "repr": str(obj)[:500],
        "deleted_at": getattr(obj, "deleted_at", None),
        "deleted_by": str(by) if by else None,
        "deletion_reason": getattr(obj, "deletion_reason", "") or "",
        "blocked": _restore_blockers(obj),
    })



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def data_integrity(request):
    """READ-ONLY data-integrity report (System Admin only).

    Identifies pre-existing inconsistent records so that any repair is a
    deliberate, reviewable human decision instead of a silent backfill.

    The report NEVER mutates anything. Repairs, when needed, must be made
    through explicit, confirmable workflows (dedicated workflows such as
    ``assign`` / ``return_asset`` / ``retire`` / ``mark_lost`` or the recycle
    bin) rather than blanket updates.
    """
    if not is_system_admin(request.user):
        return Response({"detail": "System Admin only."}, status=403)
    from django.db.models import Count
    from assets.models import Asset, Assignment
    from accounts.models import User

    issues = []
    assets = Asset.objects.order_by("id")[:500]
    assets_checked = 0
    for a in assets:
        assets_checked += 1
        open_assignments = list(a.assignments.filter(returned_at__isnull=True))
        if a.status == "assigned" and not a.assigned_to_id:
            issues.append({
                "area": "asset",
                "code": "asset_assigned_without_holder",
                "object": str(a),
                "object_id": a.pk,
                "detail": "Asset status is 'assigned' but no holder is set.",
                "suggested_fix": "Clear the stale status (set it back to "
                                 "'available') or assign a valid holder.",
            })
        if a.status in ("retired", "lost") and a.assigned_to_id:
            issues.append({
                "area": "asset",
                "code": "asset_ineligible_with_holder",
                "object": str(a),
                "object_id": a.pk,
                "detail": "Asset status is '" + a.status + "' but a holder is set.",
                "suggested_fix": "Clear the holder before retiring/losing.",
            })
        if a.assigned_to_id and not open_assignments:
            issues.append({
                "area": "asset",
                "code": "holder_without_open_assignment",
                "object": str(a),
                "object_id": a.pk,
                "detail": "Asset has a holder but no open assignment row.",
                "suggested_fix": "Return the asset (closes the open "
                                 "assignment) or create an open assignment.",
            })
        for assn in open_assignments:
            holder = assn.assigned_to
            if holder is not None and (
                    getattr(holder, "is_deleted", False)
                    or not getattr(holder, "is_active", True)):
                issues.append({
                    "area": "assignment",
                    "code": "assignment_to_inactive_user",
                    "object": "asset " + str(a.asset_tag),
                    "object_id": assn.pk,
                    "detail": "Open assignment points at an inactive or "
                              "soft-deleted user.",
                    "suggested_fix": "Return the asset or reactivate the user.",
                })
    dup_open = (Asset.objects.filter(assignments__returned_at__isnull=True)
                .values("id").annotate(n=Count("id")).filter(n__gt=1))
    for row in dup_open[:50]:
        issues.append({
            "area": "assignment",
            "code": "assignment_duplicate_open",
            "object": "asset #" + str(row["id"]),
            "detail": "Asset has " + str(row["n"]) + " open assignments.",
            "suggested_fix": "Return the asset(s) before assigning again.",
        })
    return Response({
        "issues": issues,
        "counts": {
            "issues": len(issues),
            "assets_checked": assets_checked,
        },
        "note": "Read-only data-integrity report; repairs are explicit and "
                "human-driven.",
    })


def _can_access_export(user, permission):
    if permission == "it_staff":
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "role", "") in
            ("system_admin", "it_manager", "it_support"))
    return bool(user and user.is_authenticated)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@renderer_classes(EXPORT_RENDERER_CLASSES)
def export_dataset(request, dataset):
    """Render a read-only dataset export (CSV / XLSX / PDF / DOCX).

    Query params:
      - format: csv (default) | xlsx | pdf | docx
      - scope: all (default) | selected (requires ?ids=a,b,c) | filtered
               (applies the same filter query params as the list endpoint)
      - ids: comma separated row ids used with scope=selected

    The response is an attachment; every export writes a protected AuditLog
    entry (dataset + format + scope + row count) without embedding secrets.
    """
    from common.exports import (DATASETS, EXPORT_FORMATS, build_rows,
                                 render_response)

    spec = DATASETS.get(dataset)
    if spec is None:
        return Response({"detail": "Unknown export dataset."}, status=404)
    if not _can_access_export(request.user, spec.get("permission", "authenticated")):
        return Response({"detail": "Forbidden."}, status=403)
    fmt = (request.query_params.get("format") or "csv").lower()
    if fmt not in EXPORT_FORMATS:
        return Response({"detail": "Unsupported format."}, status=400)
    scope = (request.query_params.get("scope") or "all").lower()
    ids_raw = request.query_params.get("ids") or ""
    ids = [i for i in str(ids_raw).split(",") if i.strip()]
    if scope == "filtered":
        # Apply the same filter query params the list endpoint honors so the
        # export matches the user's current filtered view.
        rows = build_rows(dataset, request.user, dict(request.query_params))
    else:
        rows = build_rows(dataset, request.user)
    if scope == "selected":
        id_set = set(ids)
        rows = [r for r in rows if str(r.get("id")) in id_set]
    response = render_response(dataset, rows, fmt, request.user, request)
    AuditLog.objects.create(
        actor=request.user,
        action="export",
        entity_type="exports." + dataset,
        object_id="",
        object_repr=dataset,
        reason="",
        details={
            "dataset": dataset,
            "format": fmt,
            "scope": scope,
            "rows": len(rows),
        },
    )
    return response


def _report_date_range(request):
    """Parse ISO `date_from`/`date_to` into an inclusive aware datetime range.

    `date_to` covers the whole day. Raises ValueError on malformed or
    reversed input so callers can return a 400 instead of a 500.
    """
    raw_from = request.query_params.get("date_from") or None
    raw_to = request.query_params.get("date_to") or None
    date_from = date_to = None
    if raw_from:
        parsed = parse_date(raw_from)
        if parsed is None:
            raise ValueError("date_from")
        date_from = timezone.make_aware(datetime.combine(parsed, time.min))
    if raw_to:
        parsed = parse_date(raw_to)
        if parsed is None:
            raise ValueError("date_to")
        date_to = timezone.make_aware(datetime.combine(parsed, time.max))
    if date_from and date_to and date_from > date_to:
        raise ValueError("date_from after date_to")
    return date_from, date_to


@api_view(["GET"])
@permission_classes([IsITStaff])
def dashboard(request):
    """Management dashboard aggregates (IT staff only)."""
    from common.reports import dashboard_data

    try:
        date_from, date_to = _report_date_range(request)
    except ValueError:
        return Response(
            {"detail": "Invalid date range; use ISO dates (YYYY-MM-DD) "
                       "with date_from on or before date_to."},
            status=status.HTTP_400_BAD_REQUEST)
    return Response(dashboard_data(date_from, date_to))


@api_view(["GET"])
@permission_classes([IsITStaff])
def department_report(request):
    """Department-level employee/asset/ticket/SLA report (IT staff only)."""
    from common.reports import department_report_data

    try:
        date_from, date_to = _report_date_range(request)
    except ValueError:
        return Response(
            {"detail": "Invalid date range; use ISO dates (YYYY-MM-DD) "
                       "with date_from on or before date_to."},
            status=status.HTTP_400_BAD_REQUEST)
    return Response(department_report_data(date_from, date_to))


@api_view(["GET"])
@permission_classes([IsITStaff])
def operations_status(request):
    """Operational status: inbound email intake + background task health.

    IT staff / admins only. Returns:
      - email: last successful mailbox processing timestamp, pending/failed
        counts, processed-today count (drives safe retry / alerting).
      - tasks: recent background task run outcomes + Celery broker health.
      - inbound: mailbox polling configuration snapshot.

    Deliberately simple: no external monitoring stack required.
    """
    last_success = EmailProcessing.objects.filter(
        status="processed").aggregate(last=Max("processed_at"))["last"]
    pending = EmailProcessing.objects.filter(status="pending").count()
    failed = EmailProcessing.objects.filter(status="failed").count()
    today_start = timezone.now().replace(hour=0, minute=0, second=0,
                                        microsecond=0)
    processed_today = EmailProcessing.objects.filter(
        status="processed", processed_at__gte=today_start).count()

    runs = list(BackgroundTaskRun.objects.order_by("-id")[:20].values(
        "task_name", "status", "started_at", "finished_at", "success",
        "error_summary"))

    celery_healthy = False
    try:
        from config.celery import app as celery_app
        inspector = celery_app.control.inspect()
        celery_healthy = bool(inspector and inspector.ping())
    except Exception:
        celery_healthy = False

    return Response({
        "email": {
            "last_successful_processing_at": last_success,
            "pending": pending,
            "failed": failed,
            "processed_today": processed_today,
            "total": EmailProcessing.objects.count(),
        },
        "tasks": {
            "celery_healthy": celery_healthy,
            "recent_runs": runs,
        },
        "inbound": {
            "enabled": getattr(settings, "INBOUND_MAILBOX_ENABLED", True),
            "mailbox": getattr(settings, "INBOUND_MAILBOX_NAME", "INBOX"),
            "support_mailbox":
                getattr(settings, "INBOUND_SUPPORT_MAILBOX", ""),
            "poll_seconds": getattr(settings, "INBOUND_MAILBOX_POLL_SECONDS", 60),
        },
    })


def _resolve(
entity_type, pk):
    from accounts.models import Department, User
    from assets.models import Asset, AssetAttachment, AssetCategory
    from tickets.models import Ticket, TicketAttachment, TicketCategory

    mapping = {
        "accounts.User": User, "accounts.Department": Department,
        "assets.Asset": Asset, "assets.AssetCategory": AssetCategory,
        "assets.AssetAttachment": AssetAttachment,
        "tickets.Ticket": Ticket, "tickets.TicketCategory": TicketCategory,
        "tickets.TicketAttachment": TicketAttachment,
        "common.Notification": Notification,
    }
    model = mapping.get(entity_type)
    if not model:
        return None
    try:
        manager = getattr(model, "all_objects", None)
        if manager is None:
            # accounts.User exposes with_deleted() instead of all_objects.
            return model.objects.with_deleted().get(pk=pk)
        return manager.get(pk=pk)
    except model.DoesNotExist:
        return None


def _restore_blockers(obj):
    """Explain unsafe restores: inactive category, tag/email collisions."""
    from assets.models import Asset, AssetCategory

    blockers = []
    # Asset whose category is inactive/deleted.
    if isinstance(obj, Asset):
        cat = AssetCategory.all_objects.filter(
            pk=obj.category_id).first()
        if cat and (cat.is_deleted or not cat.is_active):
            blockers.append(
                f"Category '{cat}' is inactive or deleted. "
                "Reactivate/restore it first, or reassign the asset."
            )
    # Uniqueness collisions on restore (tag / employee_id / email / names).
    for field in ("asset_tag", "employee_id", "email", "name", "code"):
        if hasattr(obj, field):
            val = getattr(obj, field)
            if val:
                manager = getattr(obj.__class__, "all_objects", None)
                base = (manager if manager is not None
                        else obj.__class__.objects.with_deleted())
                clash = (
                    base.filter(**{field: val})
                    .exclude(pk=obj.pk).filter(is_deleted=False).exists()
                )
                if clash:
                    blockers.append(
                        f"An active record already uses {field}='{val}'. "
                        "Change it before restoring."
                    )
    # Deleted dependency still deleted (ticket category example).
    for fk in ("category", "department"):
        if hasattr(obj, fk):
            rel = getattr(obj, fk, None)
            if rel is not None and getattr(rel, "is_deleted", False):
                blockers.append(
                    f"Related {fk} '{rel}' is soft-deleted. Restore it first."
                )
    return blockers


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def recycle_bin_restore(request, entity_type, pk):
    if not is_system_admin(request.user):
        return Response({"detail": "System Admin only."}, status=403)
    obj = _resolve(entity_type, pk)
    if obj is None or not obj.is_deleted:
        return Response({"detail": "Deleted record not found."}, status=404)
    blockers = _restore_blockers(obj)
    if blockers and not request.data.get("force"):
        return Response(
            {"detail": "Restore blocked.", "blockers": blockers}, status=409
        )
    with transaction.atomic():
        obj.restore()
        log_action(actor=request.user, action="restore", instance=obj,
                   reason=request.data.get("reason", ""),
                   details={"entity_type": entity_type})
    return Response({"restored": True, "entity_type": entity_type,
                     "object_id": str(obj.pk)})


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def recycle_bin_hard_delete(request, entity_type, pk):
    """Permanent deletion: Admin-only, needs {"confirm": "<id>", "reason"}.

    Shows impact first: GET detail lists blockers/history. POST here blocks
    when PROTECTed history/assignments exist instead of cascading silently.
    """
    if not is_system_admin(request.user):
        return Response({"detail": "System Admin only."}, status=403)
    obj = _resolve(entity_type, pk)
    if obj is None:
        return Response({"detail": "Record not found."}, status=404)
    if request.data.get("confirm") != str(obj.pk):
        return Response(
            {"detail": "Explicit confirmation required.",
             "hint": f"Send {{\"confirm\": \"{obj.pk}\", \"reason\": \"...\"}}"},
            status=400,
        )
    reason = request.data.get("reason", "")
    if not reason:
        return Response({"detail": "A deletion reason is required."},
                        status=400)
    User = get_user_model()
    # Impact summary: related history/assignments that PROTECT the row.
    impact = {}
    for rel in ("history", "notes", "assignments", "tickets", "assets",
                "attachments"):
        if hasattr(obj, rel):
            try:
                impact[rel] = getattr(obj, rel).count()
            except Exception:
                pass
    if any(v for v in impact.values()):
        return Response(
            {"detail": "Blocked: historical records would be destroyed.",
             "impact": impact,
             "hint": "Reassign/archive instead, or remove history via the "
                     "separate legal-privacy process. Bulk endpoints never "
                     "hard-delete."},
            status=409,
        )
    with transaction.atomic():
        AuditLog.objects.create(
            actor=request.user, action="hard_delete",
            entity_type=entity_type, object_id=str(obj.pk),
            object_repr=str(obj)[:255], reason=reason,
            details={"impact": impact},
        )
        # Physical file cleanup ONLY for attachments, and only when no
        # retained record still references the same stored file.
        stored_name = None
        if entity_type in ("tickets.TicketAttachment",
                           "assets.AssetAttachment"):
            stored_name = obj.file.name if obj.file else None
        obj.hard_delete()
    if stored_name:
        from assets.models import AssetAttachment as AA
        from tickets.models import TicketAttachment as TA
        still_ref = (
            TA.all_objects.filter(file=stored_name).exists()
            or AA.all_objects.filter(file=stored_name).exists())
        if not still_ref:
            try:
                obj.file.storage.delete(stored_name)
            except Exception:
                pass
    return Response({"permanently_deleted": True, "entity_type": entity_type,
                     "object_id": str(pk)})


class SavedReportViewSet(viewsets.ModelViewSet):
    """Saved report configurations: CRUD + ownership/sharing."""

    serializer_class = SavedReportSerializer

    def get_queryset(self):
        user = self.request.user
        qs = SavedReport.objects.all()
        if not _is_ticket_staff(user):
            # Employees see their own + shared reports.
            qs = qs.filter(
                models.Q(user=user) | models.Q(is_shared=True))
        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        obj = self.get_object()
        user = self.request.user
        if not _is_ticket_staff(user) and obj.user_id != user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Cannot edit another user's saved report.")
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if not _is_ticket_staff(user) and instance.user_id != user.pk:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Cannot delete another user's saved report.")
        instance.soft_delete(by_user=user, reason="saved report removed")


class ScheduledReportViewSet(viewsets.ModelViewSet):
    """Scheduled report delivery: create/edit/enable/disable/delete."""

    serializer_class = ScheduledReportSerializer

    def get_queryset(self):
        user = self.request.user
        qs = ScheduledReport.objects.all()
        if not _is_ticket_staff(user):
            qs = qs.filter(
                models.Q(saved_report__user=user) |
                models.Q(saved_report__is_shared=True))
        return qs

    def perform_create(self, serializer):
        if not _is_ticket_staff(self.request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                "Only IT staff can create scheduled reports.")
        obj = serializer.save()
        _compute_next_run(obj)

    def perform_update(self, serializer):
        obj = serializer.save()
        _compute_next_run(obj)


class ScheduledReportRunViewSet(viewsets.ReadOnlyModelViewSet):
    """Scheduled report execution history (read-only)."""

    serializer_class = ScheduledReportRunSerializer

    def get_queryset(self):
        user = self.request.user
        qs = ScheduledReportRun.objects.all()
        if not _is_ticket_staff(user):
            qs = qs.filter(
                models.Q(scheduled_report__saved_report__user=user) |
                models.Q(scheduled_report__saved_report__is_shared=True))
        return qs

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        """Re-run a failed scheduled report delivery.

        IT staff / admins only. Re-runs the report for the linked schedule
        using its current saved-report filters, recipients and format.
        """
        from rest_framework.exceptions import PermissionDenied

        if not _is_ticket_staff(request.user):
            raise PermissionDenied("IT staff only.")
        run = self.get_object()
        sr = run.scheduled_report

        # Mark the old run as skipped (superseded by retry).
        if run.status in ("failed", "running"):
            run.status = "skipped"
            run.success = False
            run.finished_at = timezone.now()
            run.error_summary = "Superseded by retry."
            run.save(update_fields=["status", "success", "finished_at",
                                    "error_summary"])

        # Trigger delivery immediately via the task (synchronously here to
        # keep the retry atomic and visible). We call the shared task's
        # underlying logic inline so the response reflects the outcome.
        try:
            _deliver_scheduled_report(sr)
            return Response({"retried": True, "scheduled_report": sr.id})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scheduled report retry %s failed", sr.pk)
            new_run = ScheduledReportRun.objects.create(
                scheduled_report=sr,
                status="failed", success=False,
                error_summary=type(exc).__name__,
                started_at=timezone.now(),
                finished_at=timezone.now())
            return Response(
                {"retried": False, "error": type(exc).__name__,
                 "run": new_run.id}, status=500)


def _deliver_scheduled_report(sr):
    """Deliver one scheduled report now (used by task + retry action)."""
    from django.db import transaction
    from django.core.mail import EmailMessage
    from common.models import ScheduledReportRun

    now = timezone.now()
    with transaction.atomic():
        run = ScheduledReportRun.objects.create(
            scheduled_report=sr,
            status="running", success=False, started_at=now)

    from tickets.views import category_report, sla_report
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()
    req = factory.get("/api/tickets/reports/by-category/",
                      data=sr.saved_report.filters or {})
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

    recipients = sr.recipients or []
    sent_count = 0
    for to_email in recipients:
        try:
            email = EmailMessage(
                subject=f"Scheduled report: {sr.saved_report.name}",
                body="Please find the attached scheduled report.",
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                to=[to_email],
            )
            email.attach(filename, content, content_type)
            email.send(fail_silently=False)
            sent_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Scheduled report email failed to %s: %s",
                to_email.split("@")[-1] if to_email else "?",
                type(exc).__name__)

    with transaction.atomic():
        run.status = "succeeded"
        run.success = True
        run.finished_at = timezone.now()
        run.recipient_count = sent_count
        run.save(update_fields=["status", "success", "finished_at",
                                "recipient_count"])

    _advance_next_run(sr)
    return run


def _compute_next_run(obj):
    """Set next_run_at based on schedule cadence."""
    from datetime import timedelta
    now = timezone.now()
    if obj.schedule == "daily":
        obj.next_run_at = now + timedelta(days=1)
    elif obj.schedule == "weekly":
        obj.next_run_at = now + timedelta(weeks=1)
    elif obj.schedule == "monthly":
        obj.next_run_at = now + timedelta(days=30)
    obj.save(update_fields=["next_run_at"])


class UserNotificationPreferenceViewSet(viewsets.ModelViewSet):
    """User notification channel preferences.

    Users can only view/edit their own preferences. IT staff can view all
    (read-only) for auditing.
    """
    serializer_class = UserNotificationPreferenceSerializer

    def get_queryset(self):
        user = self.request.user
        qs = UserNotificationPreference.objects.all()
        if not _is_ticket_staff(user):
            qs = qs.filter(user=user)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if serializer.validated_data.get("user") and \
                serializer.validated_data["user"] != user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Cannot set preferences for another user.")
        serializer.save(user=user)

    def perform_update(self, serializer):
        obj = self.get_object()
        if obj.user_id != self.request.user.pk and not _is_ticket_staff(
                self.request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                "Cannot edit another user's preferences.")
        serializer.save()

    def perform_destroy(self, instance):
        # Preferences are not deleted; soft-delete is disabled for this model
        # by design. Return 405.
        from rest_framework.exceptions import MethodNotAllowed
        raise MethodNotAllowed("DELETE")


def _get_or_create_prefs(user):
    """Get or create notification preferences for a user."""
    prefs, _ = UserNotificationPreference.objects.get_or_create(user=user)
    return prefs
