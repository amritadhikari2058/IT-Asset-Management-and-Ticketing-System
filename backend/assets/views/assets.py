"""Asset APIs: categories, assets, assignment, history, bulk.

- Ordinary asset updates pop 'assigned_to' (no silent overwrite).
- Assignment changes are explicit + write Assignment + AssetHistory rows.
- Bulk delete = soft delete only, blocked when history exists.
"""
import csv
import io
import logging
from zipfile import BadZipFile

from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from openpyxl import load_workbook
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from common.permissions import IsActiveAuthenticated
from rest_framework.response import Response

from assets.models import (
    Asset, AssetAttachment, AssetCategory, AssetHistory, Assignment,
    Disposal, Maintenance, Vendor,
)
from common.attachment_security import safe_original_filename
from assets import reports
from assets import reports
from assets.serializers import (
    AssetAssignSerializer, AssetAttachmentSerializer,
    AssetCategorySerializer, AssetHistorySerializer, AssetSerializer,
    AssignmentSerializer, DisposalSerializer, MaintenanceSerializer,
    KnowledgeBaseArticleSerializer,
    KnowledgeBaseArticleCreateUpdateSerializer,
    KnowledgeBaseArticleRevisionSerializer,
    KnowledgeBaseCategorySerializer,
    KnowledgeBaseCategoryCreateUpdateSerializer,
    KnowledgeBaseFeedbackSerializer,
    KnowledgeBaseRejectSerializer,
    KnowledgeBaseRestoreSerializer,
    KnowledgeBaseReviewDecisionSerializer,
    KnowledgeBaseSubmitReviewSerializer,
    KnowledgeBaseTagSerializer,
    KnowledgeBaseTagCreateUpdateSerializer,
    VendorSerializer,
)
from assets import kb_services
from assets.models import (KnowledgeBaseArticle, KnowledgeBaseArticleRevision,
                           KnowledgeBaseCategory, KnowledgeBaseTag,
                           KnowledgeBaseFeedback)
from common.audit import log_action
from common.models import Notification
from common.notifications import notify_user
from common.permissions import IsITStaff, IsSystemAdmin, is_system_admin
from tickets.serializers import validate_attachment_file

logger = logging.getLogger(__name__)



from .shared import (
    ASSET_IMPORT_FIELDS, _apply_asset_ordering, _asset_import_batch_lookup,
    _asset_report_rows, _asset_visible_qs, _csv_report_response,
    _flatten_message, _history, _iter_asset_import_rows, _notify_assignee,
    _public_assignment_row, _validate_assignments, _validation_error_payload,
)

class AssetViewSet(viewsets.ModelViewSet):
    queryset = Asset.objects.select_related(
        "category", "assigned_to", "department", "vendor").all()
    serializer_class = AssetSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        # Respect explicit action-level permission_classes (@action permission_classes=...).
        handler = getattr(self, self.action, None) if self.action else None
        if handler is not None:
            action_perms = getattr(handler, "kwargs", {}).get("permission_classes")
            if action_perms:
                return [permission() for permission in action_perms]

        if self.action in ("create", "update", "partial_update", "destroy",
                           "assign", "return_asset", "retire", "mark_lost",
                           "bulk_create", "bulk_update", "bulk_delete",
                           "bulk_assign"):
            return [IsITStaff()]

        from rest_framework.permissions import IsAuthenticated

        class _ActiveAuthenticated(IsAuthenticated):
            def has_permission(self, request, view):
                if not super().has_permission(request, view):
                    return False
                if not getattr(request.user, "is_active", False):
                    return False
                role = getattr(request.user, "role", "")
                return role in ("system_admin", "it_manager", "it_support",
                                "employee") or getattr(
                                    request.user, "is_superuser", False)

        return [_ActiveAuthenticated()]

    def get_queryset(self):
        qs = _asset_visible_qs(self.request.user)
        image_qs = AssetAttachment.objects.filter(
            asset=OuterRef("pk"), is_deleted=False).filter(
            Q(file__iendswith=".png") | Q(file__iendswith=".jpg")
            | Q(file__iendswith=".jpeg") | Q(file__iendswith=".gif")
            | Q(file__iendswith=".webp") | Q(file__iendswith=".bmp"))
        qs = qs.annotate(photo_attachment_id=Subquery(
            image_qs.order_by("-created_at").values("pk")[:1]))
        params = self.request.query_params
        if params.get("q"):
            q = params["q"]
            qs = qs.filter(
                Q(name__icontains=q) | Q(asset_tag__icontains=q) |
                Q(serial_number__icontains=q) | Q(location__icontains=q) |
                Q(department__name__icontains=q) | Q(department__code__icontains=q)
            )
        if params.get("category"):
            qs = qs.filter(category_id=params["category"])
        if params.get("department"):
            qs = qs.filter(department_id=params["department"])
        if params.get("vendor"):
            qs = qs.filter(vendor_id=params["vendor"])
        qs = _apply_asset_ordering(qs, params.get("ordering"))
        return qs

    def perform_create(self, serializer):
        """Create the asset; optionally attach an uploaded file atomically.

        A multipart POST may carry a ``file`` next to the asset fields.
        The file is validated BEFORE anything is saved and the asset +
        attachment are written in one transaction, so a rejected file can
        never leave a file-less asset behind (no silent drop, no partial
        state to clean up on retry). The canonical client flow remains
        two-step (create, then POST /assets/attachments/ with the new id).
        """
        upload = self.request.FILES.get("file")
        if upload is not None:
            try:
                validate_attachment_file(upload)  # 400 before any row exists
            except ValidationError as exc:
                # Key it to 'file' so clients can render it as a field
                # error instead of an anonymous message.
                raise ValidationError({"file": exc.detail}) from exc
        try:
            with transaction.atomic():
                obj = serializer.save()
                if upload is not None:
                    att = AssetAttachment.objects.create(
                        asset=obj, file=upload,
                        uploaded_by=self.request.user,
                        original_filename=safe_original_filename(
                            upload.name))
                    log_action(actor=self.request.user, action="create",
                               instance=att)
        except IntegrityError:
            # Concurrent duplicate serial (DB trigger backstop): the
            # serializer check ran before the competing write committed.
            serial = (serializer.validated_data.get("serial_number")
                      or "").strip()
            if serial and Asset.all_objects.filter(
                    serial_number=serial).exists():
                raise ValidationError({"serial_number": (
                    f"Serial number '{serial}' is already used by another "
                    "asset. Serial numbers must be unique.")})
            raise ValidationError({"detail": "Could not save the asset: a "
                                             "concurrent write conflicted."})
        _history(obj, self.request.user, "created",
                 new={"asset_tag": obj.asset_tag})
        log_action(actor=self.request.user, action="create", instance=obj)

    def perform_update(self, serializer):
        if self.request.FILES.get("file") is not None:
            # Never silently drop an upload: attachments have their own
            # endpoint and this payload format cannot store the file.
            raise ValidationError({"file": "Files cannot be changed here. "
                                           "Use /api/assets/<id>/attachments/."})
        serializer.validated_data.pop("assigned_to", None)  # never silently
        old = {f: getattr(self.get_object(), f, None) for f in
               ("name", "status", "location")}
        new_status = serializer.validated_data.get("status")
        # Dedicated workflows own these transitions: assign/return_asset,
        # retire, mark_lost. Resubmitting the current value (as edit forms
        # do) is fine; only an actual change is rejected.
        if (new_status is not None and new_status != old["status"]
                and new_status in ("assigned", "retired", "lost")):
            raise ValidationError(
                {"status": f"Status '{new_status}' must be set through "
                           "its dedicated workflow (assign, retire, or "
                           "mark lost), not generic editing."})
        try:
            obj = serializer.save()
        except IntegrityError:
            # Concurrent duplicate serial (DB trigger backstop): the
            # serializer check ran before the competing write committed.
            serial = (serializer.validated_data.get("serial_number")
                      or "").strip()
            if serial and Asset.all_objects.filter(
                    serial_number=serial).exclude(
                    pk=self.get_object().pk).exists():
                raise ValidationError({"serial_number": (
                    f"Serial number '{serial}' is already used by another "
                    "asset. Serial numbers must be unique.")})
            raise ValidationError({"detail": "Could not save the asset: a "
                                             "concurrent write conflicted."})
        _history(obj, self.request.user, "updated", old=old,
                 new={"name": obj.name, "status": obj.status})
        log_action(actor=self.request.user, action="update", instance=obj)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        refs = {"assignments": obj.assignments.count(),
                "history": obj.history.count(),
                "tickets": obj.tickets.count()}
        if any(refs.values()):
            return Response(
                {"detail": "Asset has history. Prefer retirement.",
                 "references": refs,
                 "hint": "Use retire instead of deletion."}, status=409)
        obj.soft_delete(by_user=request.user,
                        reason=request.data.get("reason", ""))
        log_action(actor=request.user, action="soft_delete", instance=obj,
                   reason=request.data.get("reason", ""))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """Explicit assignment change (recorded in history)."""
        obj = self.get_object()
        ser = AssetAssignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.db import IntegrityError as DjangoIntegrityError
        from django.utils import timezone
        from accounts.models import User
        target_id = ser.validated_data.get("assigned_to")
        target = User.objects.filter(pk=target_id).first() if target_id else None
        assignment = None
        # An asset undergoing maintenance cannot be assigned.
        if target and obj.has_open_maintenance:
            m = obj.upcoming_maintenance
            return Response(
                {"detail": "Assignment blocked: asset is undergoing "
                           f"maintenance ({m.title}, {m.status}).",
                 "maintenance_id": m.pk},
                status=status.HTTP_409_CONFLICT)
        try:
            with transaction.atomic():
                # Serialize concurrent assignment changes for this asset (row
                # lock on PostgreSQL, no-op on SQLite; same convention as
                # bulk_assign). Without it, two assignments can both pass the
                # "one open assignment" check before either commits.
                obj = Asset.objects.select_for_update().get(pk=obj.pk)
                old = {"assigned_to": obj.assigned_to_id, "status": obj.status}
                if target:
                    # Record the open assignment first so the asset clean()
                    # (status == assigned requires a holder + open assignment)
                    # passes when we flip the asset below.
                    assignment = Assignment.objects.create(
                        asset=obj, assigned_to=target,
                        assigned_by=request.user,
                        note=ser.validated_data.get("note", ""))
                    obj.assigned_to = target
                    obj.status = "assigned"
                else:
                    # Unassign: close any open assignment, clear the holder.
                    for open_a in obj.assignments.filter(
                            returned_at__isnull=True):
                        open_a.returned_at = timezone.now()
                        open_a.save(update_fields=["returned_at"])
                    obj.assigned_to = None
                    obj.status = "available"
                obj.save(update_fields=["assigned_to", "status"])
                _history(obj, request.user, "assigned", old=old,
                         new={"assigned_to": obj.assigned_to_id,
                              "status": obj.status,
                              **({"assignment_id": assignment.pk}
                                 if assignment else {})},
                         note=ser.validated_data.get("note", ""))
                _notify_assignee(target, request.user,
                                 f"Asset {obj.asset_tag} assigned to you",
                                 f"{obj.name}", obj)
                log_action(actor=request.user, action="assignment",
                           instance=obj, details={"assigned_to": obj.assigned_to_id})
        except DjangoValidationError as exc:
            # Integrity rules (ineligible holder, already assigned, retired/
            # lost asset, ...) are business errors -> clean 400, never a 500.
            return Response(
                {"detail": "Assignment rejected by the data-integrity rules.",
                 "errors": _validation_error_payload(exc)},
                status=status.HTTP_400_BAD_REQUEST)
        except DjangoIntegrityError:
            return Response(
                {"detail": "Assignment could not be recorded: the asset may "
                           "already be assigned to another employee."},
                status=status.HTTP_409_CONFLICT)
        return Response(AssetSerializer(obj).data)

    @action(detail=True, methods=["post"])
    def return_asset(self, request, pk=None):
        obj = self.get_object()
        with transaction.atomic():
            # Same asset row lock as assign()/bulk_assign so a concurrent
            # assignment cannot slip in between closing the old assignment
            # and clearing the holder.
            obj = Asset.objects.select_for_update().get(pk=obj.pk)
            previous_holder = obj.assigned_to
            last = obj.assignments.filter(returned_at__isnull=True).last()
            if last:
                from django.utils import timezone
                last.returned_at = timezone.now()
                last.save(update_fields=["returned_at"])
            old = {"assigned_to": obj.assigned_to_id}
            obj.assigned_to = None
            obj.status = "available"
            obj.save(update_fields=["assigned_to", "status"])
            _history(obj, request.user, "returned", old=old,
                     new={"assigned_to": None})
            _notify_assignee(previous_holder, request.user,
                             f"Asset {obj.asset_tag} was returned",
                             f"{obj.name}", obj)
            log_action(actor=request.user, action="assignment", instance=obj,
                       details={"returned": True})
        return Response(AssetSerializer(obj).data)

    @action(detail=True, methods=["post"])
    def retire(self, request, pk=None):
        obj = self.get_object()
        old = {"assigned_to": obj.assigned_to_id, "status": obj.status}
        with transaction.atomic():
            # Serialize concurrent mutation of this asset (row lock on
            # PostgreSQL) so a concurrent assign()/return_asset() cannot
            # interleave between closing the open assignment and flipping
            # status to retired.
            obj = Asset.objects.select_for_update().get(pk=obj.pk)
            # A retired asset cannot keep a holder: close the open
            # assignment and clear the holder so the asset's clean()
            # (retired != assigned with a holder) passes.
            if obj.assigned_to_id is not None:
                from django.utils import timezone
                obj.assignments.filter(
                    returned_at__isnull=True).update(
                        returned_at=timezone.now())
            obj.assigned_to = None
            obj.status = "retired"
            obj.save(update_fields=["assigned_to", "status"])
            _history(obj, request.user, "retired", old=old,
                     new={"assigned_to": None, "status": "retired"})
            log_action(actor=request.user, action="retire", instance=obj)
        return Response(AssetSerializer(obj).data)

    @action(detail=True, methods=["post"])
    def mark_lost(self, request, pk=None):
        """Dedicated lost-asset workflow: reason required, atomic.

        Closes any open assignment (returned_at) and clears the holder —
        the Assignment rows keep the full record — then flips status to
        lost with history + audit. Repeating on an already-lost asset is
        idempotent: 200 with no new rows.
        """
        obj = self.get_object()
        reason = (request.data.get("reason", "")
                  if isinstance(request.data.get("reason", ""), str)
                  else "")
        if not reason.strip():
            return Response({"detail": "A reason is required to mark an "
                                       "asset lost."}, status=400)
        if obj.status == "lost":
            return Response(AssetSerializer(obj).data)
        with transaction.atomic():
            # Serialize concurrent mutation of this asset (row lock on
            # PostgreSQL) so a concurrent assign()/return_asset() cannot
            # interleave between closing the open assignment and flipping
            # status to lost.
            obj = Asset.objects.select_for_update().get(pk=obj.pk)
            if obj.assigned_to_id is not None:
                from django.utils import timezone
                obj.assignments.filter(
                    returned_at__isnull=True).update(
                        returned_at=timezone.now())
            old = {"assigned_to": obj.assigned_to_id,
                   "status": obj.status}
            obj.assigned_to = None
            obj.status = "lost"
            obj.save(update_fields=["assigned_to", "status"])
            _history(obj, request.user, "lost", old=old,
                     new={"assigned_to": None, "status": "lost"},
                     note=reason.strip()[:500])
            log_action(actor=request.user, action="status_change",
                       instance=obj,
                       details={"from": old["status"], "to": "lost",
                                "reason": reason.strip()[:500]})
        return Response(AssetSerializer(obj).data)

    @action(detail=False, methods=["post"])
    def bulk_assign(self, request):
        """Explicit bulk assignment keyed on asset_tag + employee_id.

        Body: {"assignments": [{"asset_tag", "employee_id", "note"?}],
               "preview": true, "confirm": true}
        Preview validates without writing anything; confirmation executes
        each valid row in its own transaction. Already-assigned assets are
        skipped (return first) rather than silently overwritten; anything
        invalid fails per row. Generic bulk_update still rejects
        assignment fields — this is the only bulk assignment path.
        """
        from accounts.models import User

        rows = request.data.get("assignments")
        if not isinstance(rows, list) or not rows:
            return Response({"detail": "Provide 'assignments' as a "
                                       "non-empty list."}, status=400)
        results = _validate_assignments(rows)
        if request.data.get("preview", True) in (True, "true", "1", 1):
            invalid = [r for r in results if not r["valid"]]
            return Response({
                "preview": [_public_assignment_row(r) for r in results],
                "affected": sum(1 for r in results if r["valid"]),
                "invalid": [_public_assignment_row(r) for r in invalid],
                "note": "assignment only; no changes written. "
                        "Re-run with confirm:true to execute."})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, skipped, failed = [], [], []
        for r in results:
            if not r["valid"]:
                entry = {"row": r["row"], "asset_tag": r["asset_tag"],
                         "employee_id": r["employee_id"]}
                if r.get("conflict"):
                    skipped.append({**entry, "reason": r["message"]})
                else:
                    failed.append({**entry, "errors": r["message"]})
                continue
            try:
                with transaction.atomic():
                    obj = Asset.objects.select_for_update().get(
                        pk=r["asset_id"])
                    target = User.objects.get(pk=r["user_id"])
                    if (obj.assigned_to_id is not None
                            or obj.status != "available"):
                        skipped.append({
                            "row": r["row"], "asset_tag": r["asset_tag"],
                            "employee_id": r["employee_id"],
                            "reason": "already assigned; return it first"})
                        continue
                    if not target.is_active:
                        failed.append({
                            "row": r["row"], "asset_tag": r["asset_tag"],
                            "employee_id": r["employee_id"],
                            "errors": "employee is no longer eligible"})
                        continue
                    old = {"assigned_to": obj.assigned_to_id,
                           "status": obj.status}
                    obj.assigned_to = target
                    obj.status = "assigned"
                    obj.save(update_fields=["assigned_to", "status"])
                    Assignment.objects.create(
                        asset=obj, assigned_to=target,
                        assigned_by=request.user, note=r.get("note", ""))
                    _history(obj, request.user, "assigned", old=old,
                             new={"assigned_to": target.pk,
                                  "status": obj.status,
                                  "bulk": True},
                             note=r.get("note", ""))
                    _notify_assignee(target, request.user,
                                     f"Asset {obj.asset_tag} assigned to you",
                                     f"{obj.name}", obj)
                    log_action(actor=request.user, action="assignment",
                               instance=obj,
                               details={"assigned_to": target.pk,
                                        "employee_id": r["employee_id"],
                                        "bulk": True})
                    ok.append({"row": r["row"], "asset_tag": r["asset_tag"],
                               "employee_id": r["employee_id"]})
            except (Asset.DoesNotExist, User.DoesNotExist):
                failed.append({
                    "row": r["row"], "asset_tag": r["asset_tag"],
                    "employee_id": r["employee_id"],
                    "errors": "record no longer available"})
            except Exception as exc:
                failed.append({
                    "row": r["row"], "asset_tag": r["asset_tag"],
                    "employee_id": r["employee_id"],
                    "errors": _flatten_message(str(exc))})
        return Response({"successful": ok, "skipped": skipped,
                         "failed": failed,
                         "summary": {"ok": len(ok),
                                     "skipped": len(skipped),
                                     "failed": len(failed)}})

    @action(detail=True, methods=["post"],
            permission_classes=[IsSystemAdmin])
    def hard_delete(self, request, pk=None):
        from common.permissions import is_system_admin
        if not is_system_admin(request.user):
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
        if request.data.get("confirm") != str(pk):
            return Response({"detail": "Confirmation required."}, status=400)
        from django.db.models.deletion import ProtectedError
        from common.models import AuditLog

        obj = Asset.all_objects.get(pk=pk)
        refs = {
            "assignments": obj.assignments.count(),
            "asset_assignments": obj.asset_assignments.count(),
            "history": obj.history.count(),
            "attachments": obj.attachments.count(),
            "maintenance": obj.maintenance.count(),
            "disposals": obj.disposals.count(),
            "tickets": obj.tickets.count(),
        }
        try:
            obj.procurement_receipt_item
            refs["procurement_receipt_item"] = 1
        except Exception:
            # OneToOne reverse accessor may raise RelatedObjectDoesNotExist
            refs["procurement_receipt_item"] = 0
        blocking = {k: v for k, v in refs.items() if v}
        if blocking:
            return Response(
                {"detail": "Blocked: related records prevent permanent deletion.",
                 "references": blocking,
                 "hint": "Retire/archive the asset or remove protected references before hard delete."},
                status=409)
        try:
            with transaction.atomic():
                AuditLog.objects.create(
                    actor=request.user, action="hard_delete",
                    entity_type="assets.Asset", object_id=str(obj.pk),
                    object_repr=str(obj)[:255],
                    reason=request.data.get("reason", ""))
                obj.hard_delete()
        except ProtectedError as exc:
            protected = []
            for p in exc.protected_objects:
                protected.append({
                    "type": p._meta.label,
                    "id": str(p.pk),
                })
            return Response(
                {"detail": "Blocked: protected related records prevent permanent deletion.",
                 "protected_objects": protected[:50],
                 "hint": "Remove or reassign protected references before hard delete."},
                status=409)
        return Response({"permanently_deleted": True})

    # ---------- bulk ----------
    def _parse(self, request):
        """Return JSON rows or a bounded-memory iterator for CSV/XLSX."""
        upload = request.FILES.get("file")
        from django.conf import settings
        from common.import_stream import iter_uploaded_rows
        max_rows = settings.ASSET_BULK_IMPORT_MAX_ROWS
        if not upload:
            rows = request.data.get("rows", [])
            if isinstance(rows, list) and rows:
                unknown = set()
                for r in rows:
                    if isinstance(r, dict):
                        unknown |= set(r) - ASSET_IMPORT_FIELDS
                if unknown:
                    raise ValidationError(
                        {"file": "unknown columns: "
                                 + ", ".join(sorted(unknown))})
                if len(rows) > max_rows:
                    raise ValidationError({
                        "file": f"Too many rows in request body. Maximum is "
                                f"{max_rows}."})
            return rows
        filename = (upload.name or "").lower()
        if not filename.endswith((".csv", ".xlsx", ".xlsm")):
            raise ValidationError({
                "file": "Unsupported file type. Upload a CSV or XLSX file."})
        max_file_bytes = int(
            settings.ASSET_BULK_IMPORT_MAX_FILE_SIZE_MB * 1024 * 1024)
        name = upload.name or ""
        return iter_uploaded_rows(
            upload, ASSET_IMPORT_FIELDS, max_file_bytes, max_rows,
            reject_extra_csv_values=True,
            error_message=f"Could not read the uploaded file '{name}'. "
                          "Expected a UTF-8 CSV or a valid XLSX workbook "
                          "with a header row.",
        )

    @action(detail=False, methods=["get"])
    def find_all(self, request):
        """Return all assets (unpaginated) with optional filtering."""
        qs = _asset_visible_qs(request.user)
        params = request.query_params
        if params.get("category"):
            cat_filter = params["category"]
            qs = qs.filter(category__name__icontains=cat_filter)
        if params.get("department"):
            qs = qs.filter(department_id=params["department"])
        if params.get("q"):
            q = params["q"]
            qs = qs.filter(
                Q(name__icontains=q) | Q(asset_tag__icontains=q) |
                Q(serial_number__icontains=q) | Q(location__icontains=q)
            )
        serializer = AssetSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get", "post"])
    def bulk_create(self, request):
        if request.method == "GET":
            columns = ["asset_tag", "name", "category", "serial_number",
                       "status", "department", "location",
                       "description", "purchase_date", "warranty_expiry",
                       "purchase_cost"]
            if request.query_params.get("download") == "csv":
                # Downloadable CSV template: header row only.
                # NOTE: the param is named "download", not "format": DRF
                # reserves ?format= for renderer selection and would 404.
                from django.http import HttpResponse
                resp = HttpResponse(content_type="text/csv")
                resp["Content-Disposition"] = (
                    'attachment; filename="asset_import_template.csv"')
                csv.writer(resp).writerow(columns)
                return resp
            return Response({
                "template_columns": columns,
                "matching_key": "asset_tag"})
        from django.conf import settings
        from common.import_stream import batches, count_uploaded_rows
        upload = request.FILES.get("file")
        max_rows = settings.ASSET_BULK_IMPORT_MAX_ROWS
        max_file_bytes = int(
            settings.ASSET_BULK_IMPORT_MAX_FILE_SIZE_MB * 1024 * 1024)
        rows = self._parse(request)
        preview_requested = request.data.get(
            "preview", True) in (True, "true", "1", 1)
        if upload and not preview_requested and request.data.get("confirm"):
            count_uploaded_rows(
                upload, ASSET_IMPORT_FIELDS, max_file_bytes, max_rows,
                reject_extra_csv_values=True)
            rows = self._parse(request)
        if preview_requested:
            ok, errors = [], []
            seen = set()
            seen_serials = set()
            for row_batch in batches(enumerate(rows, start=2)):
                lookups = _asset_import_batch_lookup(row_batch)
                existing_tags, existing_serials, categories = lookups[:3]
                for i, r in row_batch:
                    if not isinstance(r, dict):
                        errors.append({"row": i,
                                       "errors": "row must be an object"})
                        continue
                    tag = str(r.get("asset_tag", "")).strip()
                    serial = str(r.get("serial_number") or "").strip()
                    category = str(r.get("category") or "").strip()
                    if not tag:
                        errors.append({"row": i,
                                       "errors": "asset_tag required"})
                    elif tag in seen or tag in existing_tags:
                        errors.append({"row": i,
                                       "errors": f"duplicate tag {tag}"})
                    elif (serial and (serial in seen_serials
                                      or serial in existing_serials)):
                        errors.append({
                            "row": i,
                            "errors": f"duplicate serial number {serial}"})
                    elif not category:
                        errors.append({"row": i,
                                       "errors": "category required"})
                    elif category not in categories:
                        errors.append({"row": i,
                                       "errors": "unknown category"})
                    elif str(r.get("status") or "available").strip().lower() not in (
                            "available", "assigned", "in_repair", "retired",
                            "lost", "disposed"):
                        errors.append({"row": i, "errors": "unknown status"})
                    else:
                        seen.add(tag)
                        if serial:
                            seen_serials.add(serial)
                        if str(r.get("status") or "available") == "assigned":
                            errors.append({
                                "row": i,
                                "errors": "status 'assigned' cannot be imported; "
                                          "use the assign workflow"})
                        else:
                            ok.append({"row": i, "asset_tag": tag})
            return Response({"preview": ok, "errors": errors})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed, skipped = [], [], []
        for i, r, lookups in _iter_asset_import_rows(rows):
            (existing_tags, existing_serials, categories,
             departments_by_code, departments_by_name,
             departments_by_id) = lookups
            tag = ""
            try:
                with transaction.atomic():
                    tag = str(r.get("asset_tag", "")).strip()
                    if tag in existing_tags:
                        skipped.append({"row": i, "asset_tag": tag,
                                        "reason": "exists; use bulk_update"})
                        continue
                    cat = categories.get(
                        str(r.get("category") or "").strip())
                    if not cat:
                        failed.append({"row": i, "asset_tag": tag,
                                       "errors": "unknown category"})
                        continue
                    serial = str(r.get("serial_number") or "").strip()
                    if serial and serial in existing_serials:
                        failed.append(
                            {"row": i, "asset_tag": tag,
                             "errors": f"duplicate serial number {serial}"})
                        continue
                    dept = None
                    raw_dept = r.get("department")
                    if raw_dept not in (None, ""):
                        if isinstance(raw_dept, int):
                            dept = departments_by_id.get(raw_dept)
                        else:
                            dept = (departments_by_code.get(str(raw_dept))
                                    or departments_by_name.get(
                                        str(raw_dept).strip()))
                        if dept is None:
                            try:
                                dept = departments_by_id.get(int(raw_dept))
                            except (TypeError, ValueError):
                                dept = None
                    cost = r.get("purchase_cost")
                    try:
                        cost = cost if cost in (None, "") else float(cost)
                    except (TypeError, ValueError):
                        cost = None
                    if str(r.get("status") or "available").strip().lower() not in (
                            "available", "assigned", "in_repair", "retired",
                            "lost", "disposed"):
                        failed.append({"row": i, "asset_tag": tag,
                                       "errors": "unknown status"})
                        continue
                    if str(r.get("status") or "available").strip().lower() == "assigned":
                        failed.append(
                            {"row": i, "asset_tag": tag,
                             "errors": "status 'assigned' cannot be imported; "
                                       "use the assign workflow"})
                        continue
                    obj = Asset(asset_tag=tag, name=(str(r.get("name") or "").strip() or tag),
                                category=cat,
                                serial_number=serial,
                                status=(str(r.get("status") or "available").strip().lower()
                                        or "available"),
                                department=dept,
                                location=str(r.get("location") or "").strip(),
                                description=str(r.get("description") or "").strip(),
                                purchase_date=r.get("purchase_date") or None,
                                warranty_expiry=r.get("warranty_expiry") or None,
                                purchase_cost=cost)
                    obj.save_from_import()
                    _history(obj, request.user, "created",
                             new={"asset_tag": tag, "bulk": True})
                    log_action(actor=request.user, action="bulk_create",
                               instance=obj)
                    ok.append({"row": i, "asset_tag": tag})
                    existing_tags.add(tag)
                    if serial:
                        existing_serials.add(serial)
            except IntegrityError:
                # DB backstop (unique tag / serial trigger) hit despite
                # the pre-checks - i.e. a concurrent write. Row-level,
                # clean message; no internal error text leaks.
                failed.append(
                    {"row": i, "asset_tag": tag,
                     "errors": "rejected by a uniqueness constraint "
                               "(duplicate tag or serial number)"})
            except Exception as exc:
                logger.exception("bulk_create row %s failed", i)
                failed.append({"row": i, "asset_tag": tag,
                               "errors": str(exc)})
        if request.query_params.get("download") == "csv":
            # Same executed import, CSV representation of the per-row
            # outcomes. JSON remains the default when absent.
            return _csv_report_response(
                "asset_import_report.csv",
                _asset_report_rows(ok, skipped, failed))
        return Response({"successful": [item["asset_tag"] for item in ok],
                         "skipped": skipped,
                         "failed": failed})

    @action(detail=False, methods=["post"])
    def bulk_update(self, request):
        """Bulk update keyed on asset_tag. Assignment changes rejected here."""
        rows = request.data.get("rows", [])
        ids = request.data.get("ids")
        if ids and not rows:
            rows = [{"asset_tag": Asset.objects.get(pk=i).asset_tag,
                     **request.data.get("changes", {})} for i in ids]
        if request.data.get("preview", True) in (True, "true", "1", 1):
            return Response({"preview": rows, "affected": len(rows),
                             "note": "assignment changes must use assign"})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed, skipped = [], [], []
        allowed = {"name", "description", "category", "serial_number",
                   "status", "department", "location", "purchase_date",
                   "warranty_expiry", "purchase_cost"}
        for r in rows:
            try:
                with transaction.atomic():
                    obj = Asset.objects.filter(
                        asset_tag=r.get("asset_tag")).first()
                    if not obj:
                        skipped.append({**r, "reason": "not found"})
                        continue
                    if "assigned_to" in r or "assigned_to_id" in r:
                        failed.append({"asset_tag": r.get("asset_tag"),
                                       "errors": "assignment must use assign endpoint"})
                        continue
                    changes = {k: v for k, v in r.items() if k in allowed}
                    if "category" in changes:
                        cat = AssetCategory.objects.filter(
                            name=changes.pop("category")).first()
                        if cat:
                            obj.category = cat
                    if "department" in changes:
                        raw = changes.pop("department")
                        if raw in ("", None):
                            obj.department = None
                        else:
                            from accounts.models import Department as Dept
                            dept = (Dept.objects.filter(code=raw).first()
                                    or Dept.objects.filter(name=raw).first())
                            if dept is None:
                                try:
                                    dept = Dept.objects.filter(
                                        pk=int(raw)).first()
                                except (TypeError, ValueError):
                                    dept = None
                            if dept is not None:
                                obj.department = dept
                    if "serial_number" in changes:
                        new_serial = str(
                            changes["serial_number"] or "").strip()
                        if (new_serial and Asset.all_objects
                                .exclude(pk=obj.pk)
                                .filter(serial_number=new_serial).exists()):
                            failed.append({
                                "asset_tag": r.get("asset_tag"),
                                "errors": f"duplicate serial number "
                                          f"{new_serial}"})
                            continue
                        changes["serial_number"] = new_serial
                    new_status = changes.get("status")
                    if (new_status is not None and new_status != obj.status
                            and new_status in ("assigned", "retired", "lost")):
                        failed.append(
                            {"asset_tag": r.get("asset_tag"),
                             "errors": f"Status '{new_status}' must be set "
                                       f"through its dedicated workflow "
                                       f"(assign, retire, or mark lost), not "
                                       f"generic editing."})
                        continue
                    for k, v in changes.items():
                        setattr(obj, k, v)
                    obj.save()
                    _history(obj, request.user, "bulk_update",
                             new={**changes, "bulk": True})
                    log_action(actor=request.user, action="bulk_update",
                               instance=obj, details={"changes": changes})
                    ok.append(obj.asset_tag)
            except IntegrityError:
                failed.append({"asset_tag": r.get("asset_tag"),
                               "errors": "rejected by a uniqueness "
                                         "constraint (duplicate serial "
                                         "number)"})
            except Exception as exc:
                logger.exception("bulk_update row failed")
                failed.append({"asset_tag": r.get("asset_tag"),
                               "errors": str(exc)})
        return Response({"successful": ok, "skipped": skipped,
                         "failed": failed})

    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        ids = request.data.get("ids", [])
        objs = list(Asset.objects.filter(id__in=ids))
        if request.data.get("preview", True) in (True, "true", "1", 1):
            blocked = [o.asset_tag for o in objs if o.assignments.count()
                       or o.history.count() or o.tickets.count()]
            return Response({"preview": [o.asset_tag for o in objs],
                             "affected": len(objs), "blocked": blocked,
                             "note": "soft delete only; use retire for history rows"})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, skipped, failed = [], [], []
        for obj in objs:
            try:
                with transaction.atomic():
                    if (obj.assignments.count() or obj.history.count()
                            or obj.tickets.count()):
                        skipped.append({"id": obj.pk,
                                        "reason": "has history; retire"})
                        continue
                    obj.soft_delete(
                        by_user=request.user,
                        reason=request.data.get("reason", "bulk soft delete"))
                    log_action(actor=request.user, action="bulk_soft_delete",
                               instance=obj)
                    ok.append(obj.pk)
            except Exception as exc:
                failed.append({"id": obj.pk, "errors": str(exc)})
        return Response({"successful": ok, "skipped": skipped,
                         "failed": failed})


