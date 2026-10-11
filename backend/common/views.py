"""Recycle bin, audit logs, notifications.

- Ordinary DELETE on business viewsets soft-deletes (see per-app views).
- This module is the ONLY place exposing deleted rows + restore +
  permanent deletion. Permanent deletion is System-Admin-only, requires
  explicit {"confirm": "<id>"} and writes a protected AuditLog.
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.audit import log_action
from common.models import AuditLog, Notification
from common.permissions import IsSystemAdmin, is_system_admin
from common.serializers import (
    AuditLogSerializer, NotificationSerializer, RecycleBinEntrySerializer,
)


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


class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

    def perform_create(self, serializer):
        serializer.save(recipient=self.request.user)

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


def _resolve(entity_type, pk):
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
