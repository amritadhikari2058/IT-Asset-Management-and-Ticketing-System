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
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from assets.models import (
    Asset, AssetAttachment, AssetCategory, AssetHistory, Assignment,
)
from assets.serializers import (
    AssetAssignSerializer, AssetAttachmentSerializer,
    AssetCategorySerializer, AssetHistorySerializer, AssetSerializer,
    AssignmentSerializer,
)
from common.audit import log_action
from common.permissions import IsITStaff, IsSystemAdmin
from tickets.serializers import validate_attachment_file

logger = logging.getLogger(__name__)


def _can_manage(user):
    return bool(user and user.is_authenticated and (
        getattr(user, "role", "") in ("system_admin", "it_manager",
                                      "it_support") or user.is_superuser))


def _history(asset, actor, action, old=None, new=None, note=""):
    AssetHistory.objects.create(asset=asset, actor=actor, action=action,
                                old_values=old or {}, new_values=new or {},
                                note=note)


def _validation_error_payload(exc):
    """Flatten a Django ValidationError into a DRF-friendly payload."""
    if hasattr(exc, "error_dict") and exc.error_dict:
        return exc.error_dict
    errors = getattr(exc, "error_list", None) or [str(exc)]
    return {"non_field_errors": [str(e) for e in errors]}


def _notify_assignee(recipient, actor, title, body, asset):
    """Create an in-app notification for an asset assignment event.

    Same conventions as ticket notifications: never notify the actor
    about their own action, never notify inactive/deleted users or empty
    recipients. In-app only — asset events never send email. Created
    inline so the row shares the mutation's fate on rollback.
    """
    from common.models import Notification

    if recipient is None or getattr(recipient, "pk", None) is None:
        return None
    actor_pk = getattr(actor, "pk", None)
    if actor_pk is not None and recipient.pk == actor_pk:
        return None
    if not getattr(recipient, "is_active", True):
        return None
    if getattr(recipient, "is_deleted", False):
        return None
    return Notification.objects.create(
        recipient=recipient, title=title[:255], body=body or "",
        entity_type="assets.Asset", object_id=str(asset.pk))


def _as_key(value):
    """Normalize a business key to a stripped string (never None)."""
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def _validate_assignments(raw_rows):
    """Read-only per-row validation for bulk assignment. Never writes.

    Stricter than the single-assign endpoint on purpose: unknown assets or
    employees, ineligible employees, disallowed statuses, and conflicting
    active assignments are reported per row instead of silently applied.
    Rows already assigned go to ``skipped`` (return first); invalid rows
    go to ``failed``. Returns verdict dicts with ``valid`` + ``message``.
    """
    from accounts.models import User

    items = raw_rows if isinstance(raw_rows, list) else []
    seen_tags = set()
    results = []
    for pos, raw in enumerate(items, start=1):
        entry = raw if isinstance(raw, dict) else {}
        tag = _as_key(entry.get("asset_tag"))
        eid = _as_key(entry.get("employee_id"))
        base = {"row": pos, "asset_tag": tag, "employee_id": eid}
        if not tag:
            results.append({**base, "valid": False,
                            "message": "asset_tag required"})
            continue
        if not eid:
            results.append({**base, "valid": False,
                            "message": "employee_id required"})
            continue
        if tag in seen_tags:
            results.append({
                **base, "valid": False,
                "message": f"duplicate asset_tag {tag} in request"})
            continue
        seen_tags.add(tag)
        asset = Asset.objects.select_related("assigned_to").filter(
            asset_tag=tag).first()
        if asset is None:
            if Asset.all_objects.filter(asset_tag=tag).exists():
                msg = f"asset {tag} is deleted; restore it first"
            else:
                msg = f"asset {tag} not found"
            results.append({**base, "valid": False, "message": msg})
            continue
        user = User.objects.filter(employee_id=eid).first()
        if user is None:
            if User.objects.with_deleted().filter(
                    employee_id=eid).exists():
                msg = f"employee {eid} is deleted"
            else:
                msg = f"employee {eid} not found"
            results.append({**base, "valid": False, "message": msg})
            continue
        if not user.is_active:
            results.append({**base, "valid": False,
                            "message": f"employee {eid} is inactive"})
            continue
        if asset.assigned_to_id is not None:
            current = (asset.assigned_to.employee_id
                       if asset.assigned_to else "?")
            results.append({
                **base, "valid": False, "conflict": True,
                "message": f"already assigned to {current}; "
                           "return it first",
                "asset_id": asset.pk, "user_id": user.pk})
            continue
        if asset.status != "available":
            results.append({
                **base, "valid": False,
                "message": f"asset status is '{asset.status}'; only "
                           "'available' assets can be assigned"})
            continue
        note = entry.get("note", "")
        results.append({**base, "valid": True, "message": "",
                        "asset_id": asset.pk, "user_id": user.pk,
                        "note": note if isinstance(note, str) else ""})
    return results


def _public_assignment_row(verdict):
    return {k: verdict.get(k, "") for k in
            ("row", "asset_tag", "employee_id", "valid", "message")}


def _flatten_message(value, limit=500):
    """Flatten error details to one short CSV-safe line.

    Only short server-generated text is ever returned; full row payloads
    are never included (callers pass just the errors/reason, never rows).
    """
    if isinstance(value, dict):
        parts = []
        for field, errs in value.items():
            if isinstance(errs, (list, tuple)):
                errs = "; ".join(str(e) for e in errs)
            parts.append(f"{field}: {errs}")
        text = "; ".join(parts)
    elif value is None:
        text = ""
    else:
        text = str(value)
    return " ".join(text.split())[:limit]


def _csv_report_response(filename, rows):
    """Downloadable per-row outcome report: row,key,outcome,message."""
    from django.http import HttpResponse
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(resp)
    writer.writerow(["row", "key", "outcome", "message"])
    for r in rows:
        writer.writerow([r.get("row", ""), r.get("key", ""),
                         r.get("outcome", ""), r.get("message", "")])
    return resp


def _asset_report_rows(source_rows, ok, skipped, failed):
    """Build CSV rows from a bulk_create confirmation result.

    Success row numbers are recovered from the source rows (first
    occurrence of each created tag); skips/failures already carry their
    source row number. Keys are asset tags only — never full row data.
    """
    first_row = {}
    for i, r in enumerate(source_rows, start=2):
        t = str(r.get("asset_tag", "")).strip() if isinstance(r, dict) \
            else ""
        if t and t not in first_row:
            first_row[t] = i
    rows = []
    for tag in ok:
        rows.append({"row": first_row.get(tag, ""), "key": tag,
                     "outcome": "successful", "message": "created"})
    for entry in skipped:
        entry = entry if isinstance(entry, dict) else {}
        rows.append({"row": entry.get("row", ""),
                     "key": entry.get("asset_tag", ""),
                     "outcome": "skipped",
                     "message": _flatten_message(entry.get("reason", ""))})
    for entry in failed:
        if not isinstance(entry, dict):
            rows.append({"row": "", "key": "", "outcome": "failed",
                         "message": _flatten_message(entry)})
            continue
        key = entry.get("asset_tag", "") or ""
        if not key:
            data = entry.get("row")
            if isinstance(data, dict):
                key = str(data.get("asset_tag", "")).strip()
        rows.append({"row": entry.get("row", "") if not isinstance(
                        entry.get("row"), dict) else "", "key": key,
                     "outcome": "failed",
                     "message": _flatten_message(entry.get("errors", ""))})
    rows.sort(key=lambda d: (d["row"] if isinstance(d["row"], int)
                             else 10 ** 9))
    return rows


class AssetCategoryViewSet(viewsets.ModelViewSet):
    queryset = AssetCategory.objects.annotate(
        asset_count=Count("assets")).all()
    serializer_class = AssetCategorySerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsITStaff()]
        return super().get_permissions()

    def perform_create(self, serializer):
        obj = serializer.save()
        log_action(actor=self.request.user, action="create", instance=obj)

    def perform_update(self, serializer):
        obj = serializer.save()
        log_action(actor=self.request.user, action="update", instance=obj)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        count = obj.assets.count()
        if count:
            return Response(
                {"detail": f"Category still used by {count} asset(s).",
                 "hint": "Reassign assets or deactivate the category."},
                status=409)
        obj.soft_delete(by_user=request.user,
                        reason=request.data.get("reason", ""))
        log_action(actor=request.user, action="soft_delete", instance=obj,
                   reason=request.data.get("reason", ""))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"],
            permission_classes=[IsSystemAdmin])
    def hard_delete(self, request, pk=None):
        if request.data.get("confirm") != str(pk):
            return Response({"detail": "Confirmation required."}, status=400)
        obj = AssetCategory.all_objects.get(pk=pk)
        if obj.assets.count():
            return Response({"detail": "Blocked: assets still reference it."},
                            status=409)
        from common.models import AuditLog
        with transaction.atomic():
            AuditLog.objects.create(
                actor=request.user, action="hard_delete",
                entity_type="assets.AssetCategory", object_id=str(obj.pk),
                object_repr=str(obj)[:255],
                reason=request.data.get("reason", ""))
            obj.hard_delete()
        return Response({"permanently_deleted": True})


class AssetViewSet(viewsets.ModelViewSet):
    queryset = Asset.objects.select_related(
        "category", "assigned_to", "department").all()
    serializer_class = AssetSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy",
                           "assign", "retire", "mark_lost", "bulk_create",
                           "bulk_update", "bulk_delete", "bulk_assign"):
            return [IsITStaff()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
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
            qs = qs.filter(name__icontains=q) | qs.filter(
                asset_tag__icontains=q) | qs.filter(
                serial_number__icontains=q) | qs.filter(
                location__icontains=q) | qs.filter(
                department__name__icontains=q) | qs.filter(
                department__code__icontains=q)
        if params.get("category"):
            qs = qs.filter(category_id=params["category"])
        if params.get("department"):
            qs = qs.filter(department_id=params["department"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        return _apply_asset_ordering(qs, params.get("ordering"))

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
                        original_filename=(upload.name or "")[:255])
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
        obj = serializer.save()
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
        old = {"assigned_to": obj.assigned_to_id, "status": obj.status}
        assignment = None
        try:
            with transaction.atomic():
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
        previous_holder = obj.assigned_to
        with transaction.atomic():
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
        if request.data.get("confirm") != str(pk):
            return Response({"detail": "Confirmation required."}, status=400)
        obj = Asset.all_objects.get(pk=pk)
        refs = {"assignments": obj.assignments.count(),
                "history": obj.history.count(),
                "tickets": obj.tickets.count(),
                "attachments": obj.attachments.count()}
        if any(refs.values()):
            return Response({"detail": "Blocked: history exists.",
                             "references": refs}, status=409)
        from common.models import AuditLog
        with transaction.atomic():
            AuditLog.objects.create(
                actor=request.user, action="hard_delete",
                entity_type="assets.Asset", object_id=str(obj.pk),
                object_repr=str(obj)[:255],
                reason=request.data.get("reason", ""))
            obj.hard_delete()
        return Response({"permanently_deleted": True})

    # ---------- bulk ----------
    def _parse(self, request):
        """Parse an uploaded CSV/XLSX or fall back to JSON rows.

        Every unreadable-file failure (bad encoding, corrupt/not-a-zip
        workbook, empty file) is converted into a 400 with a clear field
        error instead of a raw Django 500 page; the full exception goes
        to the server log only.
        """
        upload = request.FILES.get("file")
        if not upload:
            rows = request.data.get("rows", [])
            if isinstance(rows, list) and rows:
                allowed = {"asset_tag", "name", "description", "category",
                           "serial_number", "status", "department", "location",
                           "purchase_date", "warranty_expiry", "purchase_cost"}
                unknown = set()
                for r in rows:
                    if isinstance(r, dict):
                        unknown |= set(r) - allowed
                if unknown:
                    raise ValidationError(
                        {"file": "unknown columns: "
                                 + ", ".join(sorted(unknown))})
            return rows
        name = (upload.name or "").lower()
        allowed = {"asset_tag", "name", "description", "category",
                   "serial_number", "status", "department", "location",
                   "purchase_date", "warranty_expiry", "purchase_cost"}
        try:
            if name.endswith((".xlsx", ".xlsm")):
                wb = load_workbook(upload, read_only=True, data_only=True)
                ws = wb.active
                if ws is None:
                    raise ValueError("workbook has no worksheets")
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    raise ValueError("spreadsheet is empty; header row missing")
                header = [str(h or "").strip() for h in rows[0]]
                unknown = [h for h in header if h and h not in allowed]
                if unknown:
                    raise ValueError("unknown columns: " + ", ".join(unknown))
                if not any(h in allowed for h in header):
                    raise ValueError("header row missing")
                return [dict(zip(header, r)) for r in rows[1:] if any(r)]
            text = upload.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames:
                raise ValueError("CSV is empty; header row missing")
            header = [str(h or "").strip() for h in reader.fieldnames]
            unknown = [h for h in header if h and h not in allowed]
            if unknown:
                raise ValueError("unknown columns: " + ", ".join(unknown))
            if not any(h in allowed for h in header):
                raise ValueError("header row missing")
            return list(reader)
        except ValidationError:
            raise
        except Exception:
            logger.exception("Could not parse bulk asset upload %r", name)
            raise ValidationError(
                {"file": f"Could not read the uploaded file '{name}'. "
                         "Expected a UTF-8 CSV or a valid XLSX workbook "
                         "with a header row."})

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
        rows = self._parse(request)
        if request.data.get("preview", True) in (True, "true", "1", 1):
            ok, errors = [], []
            seen = set()
            seen_serials = set()
            for i, r in enumerate(rows, start=2):
                tag = str(r.get("asset_tag", "")).strip()
                serial = str(r.get("serial_number") or "").strip()
                if not tag:
                    errors.append({"row": i, "errors": "asset_tag required"})
                elif tag in seen or Asset.all_objects.filter(
                        asset_tag=tag).exists():
                    errors.append({"row": i, "errors": f"duplicate tag {tag}"})
                elif (serial and (serial in seen_serials
                                  or Asset.all_objects.filter(
                                      serial_number=serial).exists())):
                    errors.append(
                        {"row": i,
                         "errors": f"duplicate serial number {serial}"})
                else:
                    seen.add(tag)
                    if serial:
                        seen_serials.add(serial)
                    if str(r.get("status") or "available") == "assigned":
                        errors.append(
                            {"row": i,
                             "errors": "status 'assigned' cannot be imported; "
                                      "use the assign workflow"})
                    else:
                        ok.append({"row": i, "asset_tag": tag})
            return Response({"preview": ok, "errors": errors})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed, skipped = [], [], []
        for i, r in enumerate(rows, start=2):
            tag = ""
            try:
                with transaction.atomic():
                    tag = str(r.get("asset_tag", "")).strip()
                    if Asset.all_objects.filter(asset_tag=tag).exists():
                        skipped.append({"row": i, "asset_tag": tag,
                                        "reason": "exists; use bulk_update"})
                        continue
                    cat = AssetCategory.objects.filter(
                        name=r.get("category")).first()
                    if not cat:
                        failed.append({"row": i, "asset_tag": tag,
                                       "errors": "unknown category"})
                        continue
                    serial = str(r.get("serial_number") or "").strip()
                    if serial and Asset.all_objects.filter(
                            serial_number=serial).exists():
                        failed.append(
                            {"row": i, "asset_tag": tag,
                             "errors": f"duplicate serial number {serial}"})
                        continue
                    from accounts.models import Department as Dept
                    dept = None
                    raw_dept = r.get("department")
                    if raw_dept not in (None, ""):
                        dept = (Dept.objects.filter(code=raw_dept).first()
                                or Dept.objects.filter(name=raw_dept).first())
                        if raw_dept not in ("", None) and dept is None:
                            try:
                                dept = Dept.objects.filter(pk=int(raw_dept)).first()
                            except (TypeError, ValueError):
                                dept = None
                    cost = r.get("purchase_cost")
                    try:
                        cost = cost if cost in (None, "") else float(cost)
                    except (TypeError, ValueError):
                        cost = None
                    if str(r.get("status") or "available") == "assigned":
                        failed.append(
                            {"row": i, "asset_tag": tag,
                             "errors": "status 'assigned' cannot be imported; "
                                       "use the assign workflow"})
                        continue
                    obj = Asset(asset_tag=tag, name=r.get("name", tag),
                                category=cat,
                                serial_number=serial,
                                status=r.get("status", "available") or "available",
                                department=dept,
                                location=str(r.get("location") or "").strip(),
                                description=str(r.get("description") or "").strip(),
                                purchase_date=r.get("purchase_date") or None,
                                warranty_expiry=r.get("warranty_expiry") or None,
                                purchase_cost=cost)
                    obj.save()
                    _history(obj, request.user, "created",
                             new={"asset_tag": tag, "bulk": True})
                    log_action(actor=request.user, action="bulk_create",
                               instance=obj)
                    ok.append(tag)
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
                _asset_report_rows(rows, ok, skipped, failed))
        return Response({"successful": ok, "skipped": skipped,
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


def _asset_visible_qs(user):
    """Assets visible to the user (mirrors AssetViewSet: no role scoping).

    Attachment reads reuse this so files are exactly as visible as their
    asset — never more.
    """
    return Asset.objects.select_related(
        "category", "assigned_to", "department").all()


#: Sortable list fields (strict allowlist — anything else falls back to
#: tag order). Every branch ends in a unique key so pages are stable.
_ASSET_ORDER_FIELDS = {"asset_tag", "name", "status"}


def _apply_asset_ordering(qs, raw):
    field = (raw or "").lstrip("-")
    if field not in _ASSET_ORDER_FIELDS:
        return qs.order_by("asset_tag", "id")
    desc = raw.startswith("-")
    head = f"-{field}" if desc else field
    tie = "-id" if desc else "id"
    return qs.order_by(head, tie)


class AssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Assignment.objects.select_related(
        "asset", "assigned_to", "assigned_by").all()
    serializer_class = AssignmentSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        asset_id = self.request.query_params.get("asset")
        if asset_id:
            qs = qs.filter(asset_id=asset_id)
        return qs


class AssetHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AssetHistory.objects.select_related("asset", "actor").all()
    serializer_class = AssetHistorySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        asset_id = self.request.query_params.get("asset")
        if asset_id:
            qs = qs.filter(asset_id=asset_id)
        user = self.request.user
        if getattr(user, "role", "") in ("system_admin", "it_manager"):
            return qs
        if getattr(user, "role", "") == "it_support":
            if not user.has_perm("assets.view_asset_history"):
                return qs.none()
            return qs
        return qs.none()


class AssetAttachmentViewSet(viewsets.ModelViewSet):
    """Private asset files. Same lifecycle as ticket attachments.

    Reads (list/retrieve/download) are scoped to assets visible to the
    caller. Writes (upload/edit/delete) require IT staff, matching the
    asset mutation rules. No public URLs are ever generated.
    """

    queryset = AssetAttachment.objects.all()
    serializer_class = AssetAttachmentSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsITStaff()]
        return super().get_permissions()

    def get_queryset(self):
        # Only attachments on visible assets (private files, no public URLs).
        visible_ids = _asset_visible_qs(self.request.user).values("pk")
        qs = AssetAttachment.objects.filter(asset_id__in=visible_ids)
        asset_id = self.request.query_params.get("asset")
        if asset_id:
            qs = qs.filter(asset_id=asset_id)
        return qs

    def perform_create(self, serializer):
        asset = serializer.validated_data.get("asset")
        if asset and asset.pk:
            visible = _asset_visible_qs(self.request.user).filter(
                pk=asset.pk).exists()
            if not visible:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Cannot attach to this asset.")
        obj = serializer.save(
            uploaded_by=self.request.user,
            original_filename=getattr(
                serializer.validated_data.get("file"), "name", "")[:255])
        log_action(actor=self.request.user, action="create", instance=obj)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        # Soft delete keeps the physical file (record retained).
        obj.soft_delete(by_user=request.user, reason="attachment removed")
        log_action(actor=request.user, action="soft_delete", instance=obj)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Permission-checked download. Never expose storage URLs directly."""
        import mimetypes
        import os

        from django.http import FileResponse
        obj = self.get_object()  # scoped to visible assets above
        if obj.is_deleted:
            return Response({"detail": "Attachment is deleted."}, status=404)
        try:
            handle = obj.file.open("rb")
        except FileNotFoundError:
            return Response({"detail": "File missing from storage."},
                            status=410)
        name = obj.original_filename or os.path.basename(obj.file.name)
        resp = FileResponse(
            handle,
            content_type=mimetypes.guess_type(name)[0]
            or "application/octet-stream")
        resp["Content-Disposition"] = f'attachment; filename="{name}"'
        return resp
