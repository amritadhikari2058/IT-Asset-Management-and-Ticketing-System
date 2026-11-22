"""Ticket APIs: categories, tickets, notes, history, bulk, reports.

Visibility:
- System Admin / IT Manager / IT Support: operational scope (all active).
- Employee: own tickets + tickets for home department. Internal notes and
  privileged history hidden (separate permission-checked endpoints).
"""
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.audit import log_action
from common.notifications import (
    TICKET_ASSIGNMENT_CATEGORY, TICKET_STATUS_CATEGORY, email_enabled_for,
)
from common.permissions import IsITStaff, IsSystemAdmin, is_system_admin
from tickets.attachment_storage import delete_stored_file, store_upload
from tickets.models import (
    Ticket, TicketAttachment, TicketBulkImportOperation,
    TicketBulkImportRowOutcome, TicketCategory,
    TicketHistory, TicketKbArticle, TicketNote, TicketSLA, TicketSlaPause,
)
from tickets.serializers import (
    TicketAttachmentSerializer, TicketBulkImportOperationSerializer,
    TicketCategorySerializer, TicketHistorySerializer,
    TicketKbArticleSerializer, TicketNoteSerializer,
    TicketBulkImportSerializer, TicketSerializer, TicketSLASerializer,
)


def _can_manage_categories(user):
    return bool(user and user.is_authenticated and (
        getattr(user, "role", "") in ("system_admin", "it_manager",
                                      "it_support") or user.is_superuser))


def _ticket_visible_qs(user):
    qs = Ticket.objects.select_related(
        "category", "requester", "assignee", "department").all()
    if is_system_admin(user) or getattr(user, "role", "") in ("it_manager",
                                                              "it_support"):
        return qs
    # Employee: own + home-department tickets.
    filt = Q(requester=user)
    if getattr(user, "home_department_id", None):
        filt |= Q(department_id=user.home_department_id)
    return qs.filter(filt)


#: Fields only IT staff may change (PERMISSIONS.md). Employees editing
#: tickets may resubmit current values but any *change* is rejected.
STAFF_ONLY_TICKET_FIELDS = ("assignee", "status", "priority", "category",
                            "resolution_notes", "asset")


#: Sortable list fields (strict allowlist — anything else falls back to
#: the default newest-first order). Priority sorts by severity, not
#: alphabetically. Every branch ends in a unique key so pages are stable.
_TICKET_ORDER_FIELDS = {"created_at", "priority", "status"}


def _apply_ticket_ordering(qs, raw):
    field = (raw or "").lstrip("-")
    if field not in _TICKET_ORDER_FIELDS:
        return qs.order_by("-created_at", "-id")
    desc = raw.startswith("-")
    if field == "priority":
        from django.db.models import Case, IntegerField, When
        qs = qs.annotate(_severity=Case(
            When(priority="low", then=0),
            When(priority="medium", then=1),
            When(priority="high", then=2),
            When(priority="critical", then=3),
            default=4, output_field=IntegerField()))
        key = "_severity"
    else:
        key = field
    head = f"-{key}" if desc else key
    tie = "-id" if desc else "id"
    return qs.order_by(head, tie)


def _is_ticket_staff(user):
    return bool(user and user.is_authenticated and (
        getattr(user, "role", "") in ("system_admin", "it_manager",
                                      "it_support")
        or getattr(user, "is_superuser", False)))


def _reject_staff_only_changes(old, validated_data):
    """Raise 403 if validated data changes a staff-only field.

    `old` holds current DB values (FKs as ids). Unchanged resubmitted
    values (e.g. the edit form always posts priority/category) pass.
    """
    for field in STAFF_ONLY_TICKET_FIELDS:
        if field not in validated_data:
            continue
        new = validated_data[field]
        if field in ("assignee", "category"):
            new_id = new.pk if new is not None else None
            changed = new_id != old[field]
        else:
            changed = new != old[field]
        if changed:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                "Only IT staff can change assignee, status, priority, "
                "category, or resolution notes.")


def _write_history(ticket, actor, action, old=None, new=None, note=""):
    TicketHistory.objects.create(ticket=ticket, actor=actor, action=action,
                                 old_values=old or {}, new_values=new or {},
                                 note=note)


def _notify_user(recipient, actor, title, body, ticket):
    """Create an in-app notification for a ticket event.

    Rules (mirror the email pattern, never noisier):
    - Never notify the actor about their own action.
    - Never notify inactive/deleted users or empty recipients.
    - Bodies carry only requester-visible summary text; internal-note
      content must never be passed in (callers decide who may see what).
    - Created inline with history/audit (the established pattern), so the
      notification shares the row's fate in tests and in rolled-back
      requests; no background worker is used.

    Delegates to ``common.notifications.notify_user`` for validation,
    sanitization, dedupe, and savepoint-safe creation while preserving
    immediate (rollback-with-transaction) semantics.
    """
    from common.notifications import notify_user as _central_notify_user

    return _central_notify_user(
        recipient,
        category="ticket_event",
        title=title,
        message=body,
        entity_type="tickets.Ticket",
        object_id=str(getattr(ticket, "pk", "") or ""),
        actor=actor,
        dedupe=True,
        post_commit=False,
    )


def _wants_ticket_email(person, category=None, preference_cache=None):
    """Ticket-event email opt-out check for one recipient object.

    Delegates to the centralized preference check in
    ``common.notifications.email_enabled_for`` so the global email master
    switch and the per-category opt-ins are applied in exactly one place.

    - ``category`` selects the notification category being delivered
      (``ticket_assignment`` / ``ticket_status_change`` / ``ticket_reply``);
      ``None`` applies the global master switch only (ticket creation
      acknowledgements).
    - Missing preference records default to enabled; essential transactional
      emails (verification / password reset) never consult this.
    """
    if preference_cache is None:
        return email_enabled_for(person, category=category)
    pk = getattr(person, "pk", None)
    if pk is None:
        return True
    if pk not in preference_cache:
        from common.models import UserNotificationPreference
        preference = UserNotificationPreference.objects.filter(
            user_id=pk).first()
        if preference is None:
            preference, _ = UserNotificationPreference.objects.get_or_create(
                user=person)
        preference_cache[pk] = preference
    return email_enabled_for(
        person, category=category, preference=preference_cache[pk])


class TicketCategoryViewSet(viewsets.ModelViewSet):
    queryset = TicketCategory.objects.annotate(
        ticket_count=Count("tickets")).all()
    serializer_class = TicketCategorySerializer

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
        count = obj.tickets.count()
        if count:
            return Response(
                {"detail": f"Category still used by {count} ticket(s).",
                 "hint": "Reassign tickets or deactivate the category."},
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
        obj = TicketCategory.all_objects.get(pk=pk)
        if obj.tickets.count():
            return Response({"detail": "Blocked: tickets reference it."},
                            status=409)
        from common.models import AuditLog
        with transaction.atomic():
            AuditLog.objects.create(
                actor=request.user, action="hard_delete",
                entity_type="tickets.TicketCategory",
                object_id=str(obj.pk), object_repr=str(obj)[:255],
                reason=request.data.get("reason", ""))
            obj.hard_delete()
        return Response({"permanently_deleted": True})


def _flatten_ticket_message(value, limit=500):
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


def _ticket_bulk_import_limits():
    from django.conf import settings
    mb = float(getattr(settings, "TICKET_BULK_IMPORT_MAX_FILE_SIZE_MB", 5) or 5)
    max_rows = int(getattr(settings, "TICKET_BULK_IMPORT_MAX_ROWS", 500) or 500)
    max_json_rows = int(getattr(
        settings, "TICKET_BULK_IMPORT_MAX_JSON_ROWS", max_rows) or max_rows)
    ttl_hours = int(getattr(
        settings, "TICKET_BULK_IMPORT_TOKEN_TTL_HOURS", 24) or 24)
    return {
        "max_file_bytes": int(mb * 1024 * 1024),
        "max_file_mb": mb,
        "max_rows": max(1, max_rows),
        "max_json_rows": max(1, max_json_rows),
        "ttl_hours": max(1, ttl_hours),
    }


def _ticket_bulk_import_fingerprint(rows_in, upload=None, return_count=False):
    import hashlib
    import json
    h = hashlib.sha256()
    if upload is not None:
        h.update(b"file\0")
        h.update((getattr(upload, "name", "") or "").encode("utf-8", "ignore"))
        h.update(b"\0")
        h.update(str(getattr(upload, "size", "") or "").encode("utf-8"))
        h.update(b"\0")
    else:
        h.update(b"json\0")
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, default=str)
    h.update(b"[")
    row_count = 0
    for row in rows_in:
        if row_count:
            h.update(b",")
        for chunk in encoder.iterencode(row):
            h.update(chunk.encode("utf-8"))
        row_count += 1
    h.update(b"]")
    fingerprint = h.hexdigest()
    return (fingerprint, row_count) if return_count else fingerprint


def _ticket_bulk_import_row_fingerprint(row_data):
    """Stable hash of a canonical normalized row payload (evidence only)."""
    import hashlib
    import json
    payload = json.dumps(row_data if isinstance(row_data, dict) else {},
                         sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _record_ticket_bulk_import_row_failure(operation, row_index, row_number,
                                           row_data, error):
    """Durably record a failed row outcome when feasible.

    Must never overwrite a previously committed successful outcome for the same
    (operation, row_index). Best-effort: failures here must not mask the row's
    actual error or abort the import.
    """
    if operation is None:
        return
    try:
        msg = _flatten_ticket_message(error)
        fp = _ticket_bulk_import_row_fingerprint(row_data)
        existing = TicketBulkImportRowOutcome.objects.filter(
            operation=operation, row_index=row_index).first()
        if existing:
            if existing.outcome == TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED:
                return
            existing.outcome = TicketBulkImportRowOutcome.OUTCOME_FAILED
            existing.ticket = None
            existing.error_message = msg
            existing.row_number = row_number
            existing.row_fingerprint = fp
            existing.save(update_fields=[
                "outcome", "ticket", "error_message", "row_number",
                "row_fingerprint", "updated_at"])
            return
        TicketBulkImportRowOutcome.objects.create(
            operation=operation,
            row_index=row_index,
            row_number=row_number,
            row_fingerprint=fp,
            outcome=TicketBulkImportRowOutcome.OUTCOME_FAILED,
            ticket=None,
            error_message=msg,
        )
    except Exception:
        pass


def _ticket_csv_report_response(filename, rows):
    from django.http import HttpResponse
    import csv
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(resp)
    writer.writerow(["row", "key", "outcome", "message"])
    for r in rows:
        writer.writerow([r.get("row", ""), r.get("key", ""),
                         r.get("outcome", ""), r.get("message", "")])
    return resp


def _ticket_report_rows(ok, failed):
    rows = []
    for entry in ok:
        entry = entry if isinstance(entry, dict) else {}
        key = entry.get("id", "")
        title = entry.get("title", "")
        rows.append({"row": entry.get("row", ""),
                     "key": key if key != "" else title,
                     "outcome": "successful",
                     "message": "created"})
    for entry in failed:
        if not isinstance(entry, dict):
            rows.append({"row": "", "key": "", "outcome": "failed",
                         "message": _flatten_ticket_message(entry)})
            continue
        title = ""
        if isinstance(entry.get("row"), int):
            pass
        data = entry.get("data")
        if isinstance(data, dict):
            title = str(data.get("title", "")).strip()
        if not title and isinstance(entry.get("errors"), dict):
            pass
        key = entry.get("asset_tag", "") or title
        rows.append({"row": entry.get("row", ""),
                     "key": key,
                     "outcome": "failed",
                     "message": _flatten_ticket_message(entry.get("errors", ""))})
    rows.sort(key=lambda d: (d["row"] if isinstance(d["row"], int)
                             else 10 ** 9))
    return rows


def _manage_sla_pause(ticket, old_status, new_status, actor):
    """Create/end TicketSlaPause rows when a ticket enters/leaves a waiting
    state via a direct status change (single-ticket PATCH or bulk update).

    Mirrors resolution_services.request_information / requester_replied so
    that pause durations accumulate correctly regardless of which API path
    drives the transition.

    The ticket instance must already be locked via select_for_update() in the
    calling transaction, so we use the locked ticket's current state rather
    than re-querying.

    Actor is passed from the calling view to preserve attribution in
    started_by/ended_by fields on the SLA pause record.
    """
    WAITING = {"waiting_requester", "waiting_third_party"}
    entering = bool(new_status and new_status in WAITING
                    and old_status not in WAITING)
    # Only end a pause if we actually have a new status to transition to;
    # priority-only changes (new_status=None) must not end a pause.
    leaving = bool(new_status and old_status in WAITING
                   and new_status not in WAITING)
    if entering:
        # End any existing active pause before creating a new one
        # to prevent overlapping active pauses.
        TicketSlaPause.objects.filter(
            ticket=ticket, ended_at__isnull=True, is_deleted=False
        ).update(ended_at=timezone.now(), ended_by=actor)
        TicketSlaPause.objects.create(
            ticket=ticket, reason=new_status,
            started_by=actor, pause_type=new_status,
            started_at=timezone.now())
    elif leaving:
        TicketSlaPause.objects.filter(
            ticket=ticket, ended_at__isnull=True, is_deleted=False
        ).update(ended_at=timezone.now(), ended_by=actor)


class TicketViewSet(viewsets.ModelViewSet):
    serializer_class = TicketSerializer

    def get_permissions(self):
        # Bulk ticket mutation is staff-only work (every whitelisted
        # bulk field is staff-only). Single updates stay open so
        # employees can edit their own tickets, but staff-only *fields*
        # are guarded per-change in perform_update. Deletion (single +
        # bulk) is staff-only: employees cannot soft-delete tickets.
        # Resolution/merge are IT-staff workflows; services enforce the
        # same rule as defense in depth.
        if self.action in ("bulk_update", "destroy", "bulk_delete",
                           "resolve", "close", "merge"):
            return [IsITStaff()]
        return super().get_permissions()

    def get_queryset(self):
        from services.models import ServiceRequest

        qs = _ticket_visible_qs(self.request.user).prefetch_related(
            Prefetch(
                "service_requests",
                queryset=ServiceRequest.objects.filter(
                    is_deleted=False,
                ).select_related("catalogue_item").order_by(
                    "-submitted_at",
                )[:1],
                to_attr="_ticket_source_service_requests",
            )
        )
        p = self.request.query_params
        if p.get("q"):
            qs = qs.filter(title__icontains=p["q"]) | qs.filter(
                description__icontains=p["q"])
        if p.get("category"):
            qs = qs.filter(category_id=p["category"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("priority"):
            qs = qs.filter(priority=p["priority"])
        if p.get("department"):
            qs = qs.filter(department_id=p["department"])
        if p.get("assignee"):
            qs = qs.filter(assignee_id=p["assignee"])
        return _apply_ticket_ordering(qs, p.get("ordering"))

    def perform_create(self, serializer):
        user = self.request.user
        if not getattr(user, "can_create_tickets", True) and not is_system_admin(
                user) and getattr(user, "role", "") not in ("it_manager",
                                                            "it_support"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Ticket creation disabled for this user.")
        # Employees cannot choose an assignee at creation (staff-only, like
        # updates). Omitted/null stays valid. Checked before any save or
        # side effect.
        if (not _is_ticket_staff(user)
                and serializer.validated_data.get("assignee") is not None):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only IT staff can assign tickets.")
        # Employees cannot assign assets at creation (staff-only).
        # The asset field ties into duplicate detection and accountability.
        if (not _is_ticket_staff(user)
                and serializer.validated_data.get("asset") is not None):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only IT staff can assign assets to tickets.")
        dept = serializer.validated_data.get("department")
        if dept is None and getattr(user, "home_department_id", None):
            serializer.validated_data["department_id"] = user.home_department_id
        # Cross-department filing requires a reason (your guardrail).
        target = serializer.validated_data.get("department") or getattr(
            user, "home_department", None)
        if (target and getattr(user, "home_department_id", None)
                and target.pk != user.home_department_id
                and not serializer.validated_data.get("on_behalf_reason")):
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"on_behalf_reason":
                                   "Required when filing for another department."})
        obj = None
        with transaction.atomic():
            obj = serializer.save(requester=user)
            # Compute the SLA due date from the active priority target, so the
            # ticket carries a resolvable clock from creation. Missing/inactive
            # SLA config leaves sla_due_at unset (no overdue clock).
            from tickets.models import TicketSLA
            sla = TicketSLA.objects.filter(
                priority=obj.priority, is_active=True,
                is_deleted=False).first()
            if sla:
                from django.utils import timezone
                from datetime import timedelta
                obj.sla_due_at = timezone.now() + timedelta(
                    hours=sla.target_resolution_hours)
                obj.save(update_fields=["sla_due_at"])
            _write_history(obj, user, "created", new={"status": "open"})
            log_action(actor=user, action="create", instance=obj)
            # Automation rules (workflows app): evaluate ticket_created
            # rules inline, inside the transaction, so a rule's ticket
            # mutations and its RuleExecution rows share this row's fate.
            from workflow.services import run_rules
            run_rules("ticket_created", obj)
            # In-app: the assignee learns they own it (the requester is the
            # actor, so they are never notified of their own action).
            _notify_user(obj.assignee, user,
                         f"Ticket #{obj.pk} assigned to you",
                         f"{obj.title}\nPriority: {obj.priority}", obj)
            # Phase 66: enqueue durable email deliveries in THIS transaction so
            # they commit atomically with the ticket (a crash after commit can
            # never lose the queued email; a rollback removes them). Each
            # enqueue registers a best-effort on_commit wake-up.
            from common.outbox import enqueue_email
            from accounts.email_utils import ticket_links as _ticket_links
            ticket_pk = obj.pk
            ticket_title = obj.title
            ticket_status = obj.status
            ticket_priority = obj.priority
            ticket_asset_id = obj.asset_id
            requester_email = getattr(user, "email", "")
            requester_wants = _wants_ticket_email(user)
            assignee = obj.assignee
            assignee_email = getattr(assignee, "email", "") if assignee else ""
            assignee_wants = bool(
                assignee and assignee_email
                and _wants_ticket_email(assignee,
                                        category=TICKET_ASSIGNMENT_CATEGORY))
            if requester_wants and requester_email:
                _fe, _ = _ticket_links(ticket_pk)
                enqueue_email(
                    event_type="ticket.email.created",
                    to_email=requester_email,
                    subject=f"Ticket #{ticket_pk} created: {ticket_title}",
                    body=(f"Your ticket was created.\nStatus: {ticket_status}\n"
                          f"View: {_fe}"),
                    recipient=user, category="", ticket_id=ticket_pk)
            if assignee_wants:
                _fe, _ = _ticket_links(ticket_pk)
                enqueue_email(
                    event_type="ticket.email.assigned",
                    to_email=assignee_email,
                    subject=f"Ticket #{ticket_pk} assigned to you",
                    body=f"{ticket_title}\nPriority: {ticket_priority}\n"
                         f"View: {_fe}",
                    recipient=assignee,
                    category=TICKET_ASSIGNMENT_CATEGORY, ticket_id=ticket_pk)
        # SLA / maintenance side-effects still run AFTER the outer commit via
        # on_commit (unchanged behaviour): they are secondary notifications,
        # best-effort, and never affect the committed ticket.
        from accounts.email_utils import (
            _notify_sla_approaching, _notify_sla_breached,
            _notify_maintenance_reminder
        )

        def _send_followup_notifications():
            try:
                ticket = Ticket.objects.filter(pk=ticket_pk).first()
                if ticket is None:
                    return
                if requester_wants:
                    _notify_sla_approaching(ticket)
                    _notify_sla_breached(ticket)
                    if ticket_asset_id:
                        from assets.models import Maintenance
                        maint = Maintenance.objects.filter(
                            asset=ticket_asset_id).first()
                        if maint:
                            _notify_maintenance_reminder(maint)
                if assignee_wants:
                    _notify_sla_approaching(ticket)
                    _notify_sla_breached(ticket)
                    if ticket_asset_id:
                        from assets.models import Maintenance
                        maint = Maintenance.objects.filter(
                            asset=ticket_asset_id).first()
                        if maint:
                            _notify_maintenance_reminder(maint)
            except Exception:
                pass

        transaction.on_commit(_send_followup_notifications)

    @transaction.atomic
    def perform_update(self, serializer):
        # select_for_update() inside the transaction boundary prevents
        # concurrent lost updates: two writers cannot both read the same
        # ticket state, validate transitions against it, and then both write
        # the second one silently overwriting the first.
        queryset = self.filter_queryset(self.get_queryset())
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]
        obj = queryset.select_for_update(of=("self",)).get(
            **{self.lookup_field: lookup_value})
        self.check_object_permissions(self.request, obj)
        old = {"status": obj.status, "priority": obj.priority,
               "category": obj.category_id, "assignee": obj.assignee_id,
               "resolution_notes": obj.resolution_notes,
               "asset": obj.asset_id}
        if not _is_ticket_staff(self.request.user):
            if obj.requester_id != self.request.user.pk:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    "You can only modify tickets you requested.")
            _reject_staff_only_changes(old, serializer.validated_data)
        new_status = serializer.validated_data.get("status")
        if new_status and not Ticket.can_transition(obj.status, new_status):
            from rest_framework.exceptions import ValidationError
            raise ValidationError(
                {"status": f"Invalid transition {obj.status} -> {new_status}."})
        # Cross-department changes require justification (same rule as
        # perform_create). Department is not a staff-only field, so an
        # employee may change it, but must state why when moving away from
        # their home department.
        new_dept = serializer.validated_data.get("department")
        actor = self.request.user
        if (new_dept is not None and not _is_ticket_staff(actor)
                and getattr(actor, "home_department_id", None)
                and new_dept.pk != actor.home_department_id
                and not serializer.validated_data.get("on_behalf_reason")):
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"on_behalf_reason":
                                   "Required when moving a ticket to another department."})
        # Stamp/clear the resolution timestamps on REAL transitions so the
        # single-ticket path matches bulk_update (which already stamps):
        # -> resolved sets resolved_at, -> closed sets closed_at, and a
        # reopen clears both. Same-status resubmits never touch them.
        status_changed = bool(new_status and new_status != old["status"])
        if status_changed:
            if new_status == "resolved":
                serializer.validated_data["resolved_at"] = timezone.now()
            elif new_status == "closed":
                serializer.validated_data["closed_at"] = timezone.now()
            elif new_status in ("reopened", "in_progress", "open"):
                serializer.validated_data["resolved_at"] = None
                serializer.validated_data["closed_at"] = None
        # SLA pause management: create a pause when entering a waiting state,
        # end the active pause when leaving one. Mirrors resolution_services.
        # Called inside the transaction so a rollback undoes both the ticket
        # change and the SLA pause record together.
        updated = None
        with transaction.atomic():
            updated = serializer.save()
            _manage_sla_pause(updated, old["status"],
                              new_status if status_changed else None,
                              self.request.user)
            changes = {k: (old.get(k), getattr(updated, k if k != "category"
                                               else "category_id"))
                       for k in old}
            _write_history(updated, self.request.user, "updated",
                           old=old, new={k: str(v) for k, v in
                                         serializer.validated_data.items()})
            # In-app: the new assignee learns they own it (only on change).
            if (updated.assignee_id is not None
                    and updated.assignee_id != old["assignee"]):
                _notify_user(updated.assignee, self.request.user,
                             f"Ticket #{updated.pk} assigned to you",
                             f"{updated.title}\nPriority: {updated.priority}",
                             updated)
            status_changed = bool(new_status
                                  and new_status != old["status"])
            if status_changed:
                _write_history(updated, self.request.user, "status_change",
                               old={"status": old["status"]},
                               new={"status": new_status})
                log_action(actor=self.request.user, action="status_change",
                           instance=updated,
                           details={"from": old["status"], "to": new_status})
                # In-app: the requester learns the status (unless they made it).
                _notify_user(updated.requester, self.request.user,
                             f"Ticket #{updated.pk} status: {new_status}",
                             f"{updated.title}\nChanged {old['status']} -> "
                             f"{new_status}", updated)
                # Phase 66: enqueue the durable status-change email in THIS
                # transaction so it commits atomically with the status change.
                from common.outbox import enqueue_email
                from accounts.email_utils import ticket_links as _ticket_links
                ticket_pk = updated.pk
                old_status = old["status"]
                ticket_title = updated.title
                ticket_asset_id = updated.asset_id
                requester = updated.requester
                requester_email = (getattr(requester, "email", "")
                                   if requester else "")
                requester_wants = bool(
                    requester and requester_email
                    and _wants_ticket_email(
                        requester, category=TICKET_STATUS_CATEGORY))
                if requester_wants:
                    _fe, _ = _ticket_links(ticket_pk)
                    enqueue_email(
                        event_type="ticket.email.status_change",
                        to_email=requester_email,
                        subject=f"Ticket #{ticket_pk} status: {new_status}",
                        body=(f"{ticket_title}\nChanged {old_status} -> "
                              f"{new_status}\nView: {_fe}"),
                        recipient=requester,
                        category=TICKET_STATUS_CATEGORY, ticket_id=ticket_pk)
            # Automation rules (workflows app): fire the trigger(s)
            # matching the real change(s) made in this update. Executions
            # are recorded inside the transaction, same fate as the
            # ticket itself.
            from workflow.services import run_rules
            if (updated.assignee_id != old["assignee"]
                    or updated.priority != old["priority"]
                    or status_changed):
                run_rules("ticket_updated", updated)
            if status_changed:
                run_rules("status_changed", updated)
            log_action(actor=self.request.user, action="update",
                       instance=updated, details={"changes": str(changes)})
        # SLA / maintenance side-effects still run AFTER the outer commit via
        # on_commit (unchanged behaviour). The primary status-change email was
        # already enqueued durably inside the transaction above.
        if new_status and new_status != old["status"]:
            from accounts.email_utils import (
                _notify_sla_approaching, _notify_sla_breached,
                _notify_maintenance_reminder
            )

            def _send_followup_notifications():
                try:
                    ticket = Ticket.objects.filter(pk=ticket_pk).first()
                    if ticket is None:
                        return
                    if requester_wants:
                        _notify_sla_approaching(ticket)
                        _notify_sla_breached(ticket)
                        if ticket_asset_id:
                            from assets.models import Maintenance
                            maint = Maintenance.objects.filter(asset=ticket_asset_id).first()
                            if maint:
                                _notify_maintenance_reminder(maint)
                except Exception:
                    pass

            transaction.on_commit(_send_followup_notifications)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        # Prefer archival for history rows; soft delete still allowed.
        obj.soft_delete(by_user=request.user,
                        reason=request.data.get("reason", ""))
        _write_history(obj, request.user, "soft_deleted",
                       note=request.data.get("reason", ""))
        log_action(actor=request.user, action="soft_delete", instance=obj,
                   reason=request.data.get("reason", ""))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"],
            permission_classes=[IsSystemAdmin])
    def hard_delete(self, request, pk=None):
        if request.data.get("confirm") != str(pk):
            return Response({"detail": "Confirmation required."}, status=400)
        obj = Ticket.all_objects.get(pk=pk)
        refs = {"history": obj.history.count(), "notes": obj.notes.count(),
                "attachments": obj.attachments.count()}
        if any(refs.values()):
            return Response({"detail": "Blocked: history exists.",
                             "references": refs,
                             "hint": "Prefer archival/soft deletion."},
                            status=409)
        from common.models import AuditLog
        with transaction.atomic():
            AuditLog.objects.create(
                actor=request.user, action="hard_delete",
                entity_type="tickets.Ticket", object_id=str(obj.pk),
                object_repr=str(obj)[:255],
                reason=request.data.get("reason", ""))
            obj.hard_delete()
        return Response({"permanently_deleted": True})

    @action(detail=True, methods=["get", "post"])
    def notes(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "GET":
            notes = ticket.notes.all()
            # Employees see only requester-visible updates on their tickets.
            if getattr(request.user, "role", "") == "employee":
                notes = notes.filter(is_internal=False)
            return Response(TicketNoteSerializer(notes, many=True).data)
        body = request.data.get("body", "").strip()
        if not body:
            return Response({"detail": "Body required."}, status=400)
        is_internal = bool(request.data.get("is_internal", True))
        if getattr(request.user, "role", "") == "employee" and is_internal:
            return Response({"detail": "Employees cannot add internal notes."},
                            status=403)
        note = TicketNote.objects.create(ticket=ticket, author=request.user,
                                         body=body, is_internal=is_internal)
        _write_history(ticket, request.user, "note_added",
                       new={"internal": is_internal}, note=body[:200])
        log_action(actor=request.user, action="note", instance=ticket)
        # In-app: requester-visible notes notify the requester and the
        # assignee (distinct, excluding the author). Internal notes notify
        # nobody: their content must never reach employees.
        if not is_internal:
            excerpt = body[:200]
            _notify_user(ticket.requester, request.user,
                         f"Ticket #{ticket.pk} update: {ticket.title}",
                         excerpt, ticket)
            if (ticket.assignee_id is not None
                    and (ticket.requester_id is None
                         or ticket.assignee_id != ticket.requester_id)):
                _notify_user(ticket.assignee, request.user,
                             f"Ticket #{ticket.pk} update: {ticket.title}",
                             excerpt, ticket)
        return Response(TicketNoteSerializer(note).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get", "post"])
    def bulk_create(self, request):
        if request.method == "GET":
            columns = ["title", "description", "category", "priority",
                       "department", "on_behalf_reason", "asset_tag",
                       "assignee_employee_id"]
            if request.query_params.get("download") == "csv":
                from django.http import HttpResponse
                import csv
                resp = HttpResponse(content_type="text/csv")
                resp["Content-Disposition"] = (
                    'attachment; filename="ticket_import_template.csv"')
                csv.writer(resp).writerow(columns)
                return resp
            return Response({"template_columns": columns,
                             "matching_key": "title"})
        """Create many tickets at once.

        Body: {"tickets": [{title, description, category, priority?,
        department?, on_behalf_reason?, asset?, assignee?}],
        "preview": true, "confirm": true}
        Same rules as single creation, applied per row: the requester is
        always the caller (payload requester keys are ignored), employees
        cannot set an assignee, assignees must be eligible, home-department
        defaulting and cross-department justification apply. Preview
        validates without writing; confirm executes each valid row in its
        own transaction (save + history + audit + notification), with
        emails sent afterwards so failures stay swallowed and can never
        undo or precede a commit. Partial success with per-row results.
        """
        user = self.request.user
        if not getattr(user, "can_create_tickets", True) and not is_system_admin(
                user) and getattr(user, "role", "") not in ("it_manager",
                                                            "it_support"):
            return Response(
                {"detail": "Ticket creation disabled for this user."},
                status=403)

        import io
        from datetime import timedelta
        from django.conf import settings
        from django.db import transaction
        from django.utils import timezone
        from accounts.models import User, Department
        from assets.models import Asset
        from tickets.models import TicketCategory, TicketSLA, TicketBulkImportOperation

        limits = _ticket_bulk_import_limits()
        max_file_bytes = limits["max_file_bytes"]
        max_rows = limits["max_rows"]
        max_json_rows = limits["max_json_rows"]
        token_ttl_hours = limits["ttl_hours"]

        def _truthy_flag(value, default):
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            if isinstance(value, int):
                return value != 0
            if isinstance(value, str):
                v = value.strip().lower()
                if v in ("true", "1", "yes", "on"):
                    return True
                if v in ("false", "0", "no", "off", ""):
                    return False
            return bool(value)

        preview_flag = _truthy_flag(request.data.get("preview", True), True)
        import_token = (request.data.get("import_token")
                        or request.query_params.get("import_token") or "")
        if isinstance(import_token, str):
            import_token = import_token.strip()
        else:
            import_token = str(import_token).strip()
        if import_token and len(import_token) > 64:
            return Response({"detail": "Invalid import token."}, status=400)

        upload = request.FILES.get("file")
        allowed_columns = {
            "title", "description", "category", "priority", "department",
            "on_behalf_reason", "asset_tag", "assignee_employee_id",
            "department_code", "department_name", "asset", "asset_id",
            "on_behalf", "assignee", "employee_id",
        }
        from common.import_stream import batches, iter_uploaded_rows

        if upload is not None:
            file_size = getattr(upload, "size", None)
            if file_size is not None and file_size > max_file_bytes:
                return Response(
                    {"file": f"Uploaded file is too large. Maximum size is "
                             f"{limits['max_file_mb']:.0f} MB."},
                    status=400)
            row_offset = 2

            def _iter_input_rows():
                return iter_uploaded_rows(
                    upload, allowed_columns, max_file_bytes, max_rows,
                    skip_empty_xlsx_rows=True,
                    skip_empty_csv_rows=True,
                    reject_duplicate_headers=True,
                    strip_empty_xlsx_values=True)

            request_fingerprint, row_count = _ticket_bulk_import_fingerprint(
                _iter_input_rows(), upload=upload, return_count=True)
        else:
            rows_in = request.data.get("tickets", request.data.get("rows", []))
            if not isinstance(rows_in, list):
                rows_in = []
            if len(rows_in) > max_json_rows:
                return Response(
                    {"detail": f"Too many rows in request body ({len(rows_in)}). "
                               f"Maximum is {max_json_rows}."},
                    status=400)
            row_offset = 1

            def _iter_input_rows():
                return iter(rows_in)

            request_fingerprint, row_count = _ticket_bulk_import_fingerprint(
                rows_in, return_count=True)

        if row_count == 0:
            return Response({"detail": "Provide 'tickets' or a non-empty "
                                       "uploaded file."}, status=400)

        def _resolve_references(raw_rows, include_ids=True):
            cat_ids, cat_names = set(), set()
            dept_ids, dept_codes, dept_names = set(), set(), set()
            asset_ids, asset_tags = set(), set()
            assignee_ids, assignee_eids = set(), set()
            for raw in raw_rows:
                if not isinstance(raw, dict):
                    continue
                cat = raw.get("category")
                if cat not in (None, "") and not isinstance(cat, bool):
                    try:
                        category_id = int(cat)
                    except (TypeError, ValueError, OverflowError):
                        cat_names.add(str(cat).strip())
                    else:
                        if include_ids:
                            cat_ids.add(category_id)
                dept = (raw.get("department") or raw.get("department_code")
                        or raw.get("department_name"))
                if dept not in (None, ""):
                    if (isinstance(dept, int)
                            or isinstance(dept, str)
                            and str(dept).strip().isdigit()):
                        if include_ids:
                            dept_ids.add(int(dept))
                    else:
                        department_value = str(dept).strip()
                        dept_codes.add(department_value)
                        dept_names.add(department_value)
                asset = (raw.get("asset") or raw.get("asset_tag")
                         or raw.get("asset_id"))
                if asset not in (None, "") and _is_ticket_staff(user):
                    if (isinstance(asset, int)
                            or isinstance(asset, str)
                            and str(asset).strip().isdigit()):
                        if include_ids:
                            asset_ids.add(int(asset))
                    else:
                        asset_tags.add(str(asset).strip())
                assignee = (raw.get("assignee")
                            or raw.get("assignee_employee_id")
                            or raw.get("employee_id"))
                if assignee not in (None, ""):
                    if (isinstance(assignee, int)
                            or isinstance(assignee, str)
                            and str(assignee).strip().isdigit()):
                        if include_ids:
                            assignee_ids.add(int(assignee))
                    else:
                        assignee_eids.add(str(assignee).strip())

            from django.db.models import Q

            category_by_id = {}
            category_by_name = {}
            if cat_ids or cat_names:
                query = Q()
                if cat_ids:
                    query |= Q(pk__in=cat_ids)
                if cat_names:
                    query |= Q(name__in=cat_names)
                for category in TicketCategory.objects.filter(query):
                    category_by_id[category.pk] = category
                    category_by_name[category.name] = category
                    category_by_name[str(category.name).strip()] = category

            department_by_id = {}
            department_by_code = {}
            department_by_name = {}
            if dept_ids or dept_codes or dept_names:
                query = Q()
                if dept_ids:
                    query |= Q(pk__in=dept_ids)
                if dept_codes:
                    query |= Q(code__in=dept_codes)
                if dept_names:
                    query |= Q(name__in=dept_names)
                for department in Department.objects.filter(query):
                    department_by_id[department.pk] = department
                    if department.code:
                        department_by_code[department.code] = department
                    if department.name:
                        department_by_name[department.name] = department

            asset_by_id = {}
            asset_by_tag = {}
            if asset_ids or asset_tags:
                query = Q()
                if asset_ids:
                    query |= Q(pk__in=asset_ids)
                if asset_tags:
                    query |= Q(asset_tag__in=asset_tags)
                for asset in Asset.objects.filter(query):
                    asset_by_id[asset.pk] = asset
                    if asset.asset_tag:
                        asset_by_tag[asset.asset_tag] = asset

            user_by_id = {}
            user_by_employee_id = {}
            if assignee_ids or assignee_eids:
                query = Q()
                if assignee_ids:
                    query |= Q(pk__in=assignee_ids)
                if assignee_eids:
                    query |= Q(employee_id__in=assignee_eids)
                for assignee in User.objects.filter(query):
                    user_by_id[assignee.pk] = assignee
                    if assignee.employee_id:
                        user_by_employee_id[assignee.employee_id] = assignee

            return {
                "category_by_id": category_by_id,
                "category_by_name": category_by_name,
                "department_by_id": department_by_id,
                "department_by_code": department_by_code,
                "department_by_name": department_by_name,
                "asset_by_id": asset_by_id,
                "asset_by_tag": asset_by_tag,
                "user_by_id": user_by_id,
                "user_by_employee_id": user_by_employee_id,
                "related_objects": {
                    "category": category_by_id,
                    "department": department_by_id,
                    "asset": asset_by_id,
                    "assignee": user_by_id,
                },
            }

        def _norm(raw, references):
            data = raw if isinstance(raw, dict) else {}
            out = {}
            title = data.get("title")
            if title is not None:
                out["title"] = str(title).strip()
            desc = data.get("description")
            if desc is not None:
                out["description"] = str(desc).strip()
            priority = data.get("priority")
            if priority not in (None, ""):
                out["priority"] = str(priority).strip().lower()
            cat = data.get("category")
            if cat not in (None, ""):
                if isinstance(cat, bool):
                    pass
                else:
                    try:
                        cid = int(cat)
                        tc = references["category_by_id"].get(cid)
                        out["category"] = tc.pk if tc is not None else cid
                    except (TypeError, ValueError):
                        name = str(cat).strip()
                        tc = references["category_by_name"].get(name)
                        out["category"] = tc.pk if tc is not None else name
            dept = (data.get("department")
                    or data.get("department_code")
                    or data.get("department_name"))
            if dept not in (None, ""):
                if isinstance(dept, int) or (
                        isinstance(dept, str) and str(dept).strip().isdigit()):
                    try:
                        did = int(dept)
                    except Exception:
                        did = str(dept).strip()
                    d = (references["department_by_id"].get(did)
                         if isinstance(did, int) else None)
                    out["department"] = d.pk if d is not None else did
                else:
                    ds = str(dept).strip()
                    d = (references["department_by_code"].get(ds)
                         or references["department_by_name"].get(ds))
                    out["department"] = d.pk if d is not None else ds
            reason = (data.get("on_behalf_reason")
                      or data.get("on_behalf"))
            if reason not in (None, ""):
                out["on_behalf_reason"] = str(reason).strip()
            asset = (data.get("asset") or data.get("asset_tag")
                     or data.get("asset_id"))
            if asset not in (None, ""):
                if not _is_ticket_staff(user):
                    # Employees cannot assign assets; strip the field
                    pass  # deliberately omit from out
                elif isinstance(asset, int) or (
                        isinstance(asset, str) and str(asset).strip().isdigit()):
                    try:
                        aid = int(asset)
                    except Exception:
                        aid = str(asset).strip()
                    a = (references["asset_by_id"].get(aid)
                         if isinstance(aid, int) else None)
                    out["asset"] = a.pk if a is not None else aid
                else:
                    tag = str(asset).strip()
                    a = references["asset_by_tag"].get(tag)
                    out["asset"] = a.pk if a is not None else tag
            assignee = (data.get("assignee")
                        or data.get("assignee_employee_id")
                        or data.get("employee_id"))
            if assignee not in (None, ""):
                if isinstance(assignee, int) or (
                        isinstance(assignee, str)
                        and str(assignee).strip().isdigit()):
                    try:
                        uid = int(assignee)
                    except Exception:
                        uid = str(assignee).strip()
                    u = (references["user_by_id"].get(uid)
                         if isinstance(uid, int) else None)
                    out["assignee"] = u.pk if u is not None else uid
                else:
                    eid = str(assignee).strip()
                    u = references["user_by_employee_id"].get(eid)
                    out["assignee"] = u.pk if u is not None else eid
            return out

        def _iter_normalized_rows(include_ids=True):
            for batch in batches(_iter_input_rows()):
                references = _resolve_references(
                    batch, include_ids=include_ids)
                related_objects = references["related_objects"]
                for original in batch:
                    yield original, _norm(original, references), related_objects
                # Release references to free memory after each batch
                references.clear()
                related_objects.clear()

        def _iter_normalized_batches(include_ids=True):
            """Yield bounded normalized batches for confirmation."""
            start_index = 0
            for batch in batches(_iter_input_rows()):
                references = _resolve_references(
                    batch, include_ids=include_ids)
                normalized = [
                    (original, _norm(original, references), references)
                    for original in batch
                ]
                yield start_index, normalized
                start_index += len(normalized)
                references.clear()

        def _lock_reference_batch(normalized_batch):
            """Lock the unique references used by one bounded batch once."""
            category_ids, department_ids, asset_ids, assignee_ids = (
                set(), set(), set(), set())
            for _original, data, _references in normalized_batch:
                category = data.get("category")
                department = data.get("department")
                asset = data.get("asset")
                assignee = data.get("assignee")
                if isinstance(category, int):
                    category_ids.add(category)
                if isinstance(department, int):
                    department_ids.add(department)
                elif department in (None, ""):
                    home_department_id = getattr(
                        user, "home_department_id", None)
                    if isinstance(home_department_id, int):
                        department_ids.add(home_department_id)
                if isinstance(asset, int):
                    asset_ids.add(asset)
                if isinstance(assignee, int):
                    assignee_ids.add(assignee)

            return {
                "category": TicketCategory._default_manager.select_for_update(
                ).filter(pk__in=category_ids).in_bulk()
                if category_ids else {},
                "department": Department._default_manager.select_for_update(
                ).filter(pk__in=department_ids).in_bulk()
                if department_ids else {},
                "asset": Asset._default_manager.select_for_update(
                ).filter(pk__in=asset_ids).in_bulk()
                if asset_ids else {},
                "assignee": User._default_manager.select_for_update(
                ).filter(pk__in=assignee_ids).in_bulk()
                if assignee_ids else {},
            }

        def _validate_row(data, related_objects):
            """Validate once and retain the serializer for confirmation."""
            serializer = TicketBulkImportSerializer(
                data=data, context={"bulk_related_objects": related_objects})
            if not serializer.is_valid():
                return serializer.errors, None
            vd = serializer.validated_data
            if (not _is_ticket_staff(user)
                    and vd.get("assignee") is not None):
                return {"assignee": "Only IT staff can assign tickets."}, None
            # Employees cannot assign assets via bulk creation either.
            if (not _is_ticket_staff(user)
                    and vd.get("asset") is not None):
                return {"asset": "Only IT staff can assign assets to tickets."}, None
            target = vd.get("department") or getattr(
                user, "home_department", None)
            if (target and getattr(user, "home_department_id", None)
                    and target.pk != user.home_department_id
                    and not vd.get("on_behalf_reason")):
                return ({"on_behalf_reason":
                         "Required when filing for another department."},
                        None)
            return None, serializer

        def _lock_row_references(data):
            """Load current reference state under the row's transaction lock."""
            department = data.get("department")
            if department in (None, ""):
                department = getattr(user, "home_department_id", None)
            references = (
                ("category", TicketCategory),
                ("department", Department),
                ("asset", Asset),
                ("assignee", User),
            )
            locked = {}
            for field, model in references:
                value = department if field == "department" else data.get(field)
                if isinstance(value, bool):
                    continue
                if isinstance(value, int):
                    pk = value
                elif isinstance(value, str) and value.strip().isdigit():
                    pk = int(value.strip())
                else:
                    continue
                locked[field] = (
                    model._default_manager.select_for_update()
                    .filter(pk=pk)
                    .in_bulk()
                )
            return locked

        operation = None
        if import_token:
            expires_at = timezone.now() + timedelta(hours=token_ttl_hours)
            op, created = TicketBulkImportOperation.objects.get_or_create(
                user=user, token=import_token,
                defaults={
                    "status": TicketBulkImportOperation.STATUS_PREVIEWED,
                    "request_fingerprint": request_fingerprint,
                    "expires_at": expires_at,
                })
            operation = op
            if operation.is_expired:
                return Response(
                    {"detail": "This import token has expired. Start a new import."},
                    status=410)
            # If token is already associated with a different payload, reject.
            if (not created and operation.request_fingerprint
                    and operation.request_fingerprint != request_fingerprint):
                return Response(
                    {"detail": "This import token is already associated with a different import."},
                    status=409)
            if created or not operation.request_fingerprint:
                operation.request_fingerprint = request_fingerprint
            if not operation.expires_at:
                operation.expires_at = expires_at
            # Keep token alive on use.
            operation.expires_at = max(operation.expires_at, expires_at)
            operation.save(update_fields=["request_fingerprint", "expires_at", "updated_at"])

        if preview_flag:
            preview, invalid = [], []
            for idx, (orig, raw, related_objects) in enumerate(
                    _iter_normalized_rows()):
                i = idx + row_offset
                data = raw if isinstance(raw, dict) else {}
                errors, _ = _validate_row(data, related_objects)
                # Check the original row because normalization omits employee assets.
                if (not _is_ticket_staff(user)
                        and isinstance(orig, dict)
                        and (orig.get("asset") not in (None, "")
                             or orig.get("asset_tag") not in (None, "")
                             or orig.get("asset_id") not in (None, ""))):
                    if errors is None:
                        errors = {}
                    errors["asset"] = "Only IT staff can assign assets to tickets."
                entry = {"row": i, "valid": errors is None,
                         "title": data.get("title", ""),
                         "errors": errors or {}}
                preview.append(entry)
                if errors:
                    invalid.append(entry)
            payload = {
                "preview": preview,
                "affected": len(preview) - len(invalid),
                "invalid": invalid,
                "note": "No tickets created. Re-run with confirm:true "
                        "to execute.",
            }
            if operation is not None:
                # Do not overwrite a completed/processing confirmation result.
                if operation.status == TicketBulkImportOperation.STATUS_PREVIEWED:
                    operation.preview_payload = payload
                    operation.save(update_fields=["preview_payload", "updated_at"])
                elif operation.status == TicketBulkImportOperation.STATUS_COMPLETED:
                    # Same operation already confirmed: keep preview semantics, but
                    # returning stored confirmation is handled on confirm path.
                    pass
            return Response(payload)

        confirm = request.data.get("confirm")
        if not _truthy_flag(confirm, False):
            return Response({"detail": "Confirmation required."}, status=400)

        def _stored_confirm_response(op):
            if op.result_format == "csv":
                from django.http import HttpResponse
                resp = HttpResponse(op.result_csv or "", content_type="text/csv")
                resp["Content-Disposition"] = 'attachment; filename="ticket_import_report.csv"'
                return resp
            return Response(op.result_json or {}, status=op.result_status_code or 200)

        if operation is not None:
            # Replay completed confirmations for the same operation/token.
            if operation.status == TicketBulkImportOperation.STATUS_COMPLETED:
                return _stored_confirm_response(operation)
            if operation.status == TicketBulkImportOperation.STATUS_PROCESSING:
                # Concurrent or stale processing. Do not re-run to avoid duplicates.
                stale_after = int(getattr(settings, "TICKET_BULK_IMPORT_PROCESSING_STALE_SECONDS", 300) or 300)
                if operation.started_at and timezone.now() - operation.started_at > timedelta(seconds=stale_after):
                    return Response(
                        {"detail": "A previous confirmation for this import appears interrupted or stalled. "
                                   "Do not retry automatically; inspect the import operation and reconcile committed tickets/results before starting a new import.",
                         "operation": {
                             "status": operation.status,
                             "started_at": operation.started_at,
                             "total_rows": getattr(operation, "total_rows", 0),
                             "processed_count": getattr(operation, "processed_count", 0),
                             "successful_count": getattr(operation, "successful_count", 0),
                             "failed_count": getattr(operation, "failed_count", 0),
                         }},
                        status=409)
                return Response(
                    {"detail": "This import confirmation is already in progress."},
                    status=409)
            if operation.status == TicketBulkImportOperation.STATUS_FAILED:
                # Failed before completion: require a new import token to avoid ambiguity.
                return Response(
                    {"detail": operation.error_detail or "This import confirmation failed. Start a new import."},
                    status=409)
            # Claim previewed operation for processing.
            with transaction.atomic():
                locked = (TicketBulkImportOperation.objects
                          .select_for_update()
                          .get(pk=operation.pk, user=user))
                if locked.request_fingerprint != request_fingerprint:
                    return Response(
                        {"detail": "This import token is already associated with a different import."},
                        status=409)
                if locked.is_expired:
                    return Response(
                        {"detail": "This import token has expired. Start a new import."},
                        status=410)
                if locked.status == TicketBulkImportOperation.STATUS_COMPLETED:
                    operation = locked
                    return _stored_confirm_response(operation)
                if locked.status == TicketBulkImportOperation.STATUS_PROCESSING:
                    return Response(
                        {"detail": "This import confirmation is already in progress."},
                        status=409)
                locked.status = TicketBulkImportOperation.STATUS_PROCESSING
                locked.started_at = timezone.now()
                locked.error_detail = ""
                locked.total_rows = row_count
                locked.processed_count = 0
                locked.successful_count = 0
                locked.failed_count = 0
                locked.save(update_fields=[
                    "status", "started_at", "error_detail", "total_rows",
                    "processed_count", "successful_count", "failed_count",
                    "updated_at"])
                operation = locked

        from accounts.email_utils import (
            send_ticket_notification, ticket_links,
            _notify_sla_approaching, _notify_sla_breached,
            _notify_maintenance_reminder,
        )

        # Cache SLA configs and (best-effort) maintenance lookups within request.
        sla_cache = {}
        maint_cache = {}

        def _sla_for(priority):
            if priority in sla_cache:
                return sla_cache[priority]
            sla_cache[priority] = TicketSLA.objects.filter(
                priority=priority, is_active=True, is_deleted=False).first()
            return sla_cache[priority]

        ok, failed, skipped = [], [], []

        def _persist_operation_progress():
            if operation is None:
                return
            try:
                TicketBulkImportOperation.objects.filter(
                    pk=operation.pk, user=user).update(
                    total_rows=row_count,
                    processed_count=len(ok) + len(failed) + len(skipped),
                    successful_count=len(ok),
                    failed_count=len(failed),
                    updated_at=timezone.now())
            except Exception:
                # Progress persistence is best-effort observability; never abort
                # the import or mask row outcomes because of it.
                pass

        try:
            email_preference_cache = {}
            automation_rule_cache = {}
            idx = -1
            for batch_start, normalized_batch in _iter_normalized_batches(
                    include_ids=True):
                for batch_idx, (orig, raw, _related_objects) in enumerate(
                        normalized_batch):
                    idx = batch_start + batch_idx
                    i = idx + row_offset
                    data = raw if isinstance(raw, dict) else {}
                    try:
                        with transaction.atomic():
                            current_references = _lock_row_references(data)
                            errors, serializer = _validate_row(
                                data, current_references)
                            if (not _is_ticket_staff(user)
                                    and isinstance(orig, dict)
                                    and (orig.get("asset") not in (None, "")
                                         or orig.get("asset_tag") not in (None, "")
                                         or orig.get("asset_id") not in (None, ""))):
                                if errors is None:
                                    errors = {}
                                errors["asset"] = (
                                    "Only IT staff can assign assets to tickets.")
                            if errors:
                                failed.append({"row": i, "errors": errors})
                                if operation is not None:
                                    _record_ticket_bulk_import_row_failure(
                                        operation, idx, i, data, errors)
                                _persist_operation_progress()
                                continue
                            vd = serializer.validated_data
                            if vd.get("department") is None and getattr(
                                    user, "home_department_id", None):
                                vd["department_id"] = user.home_department_id
                            obj = serializer.save(requester=user)
                            sla = _sla_for(obj.priority)
                            if sla:
                                obj.sla_due_at = timezone.now() + timedelta(
                                    hours=sla.target_resolution_hours)
                                obj.save(update_fields=["sla_due_at"])
                            _write_history(obj, user, "created",
                                           new={"status": "open"})
                            log_action(actor=user, action="create", instance=obj)
                            from workflow.services import run_rules
                            run_rules(
                                "ticket_created", obj,
                                enabled_rules_cache=automation_rule_cache)
                            _notify_user(
                                obj.assignee, user,
                                f"Ticket #{obj.pk} assigned to you",
                                f"{obj.title}\nPriority: {obj.priority}", obj)
                            from common.outbox import enqueue_email
                            from accounts.email_utils import ticket_links as _tl
                            ticket_pk = obj.pk
                            ticket_title = obj.title
                            ticket_status = obj.status
                            ticket_priority = obj.priority
                            ticket_asset_id = obj.asset_id
                            requester_email = getattr(user, "email", "")
                            requester_wants = _wants_ticket_email(
                                user, preference_cache=email_preference_cache)
                            assignee = obj.assignee
                            assignee_email = (getattr(assignee, "email", "")
                                              if assignee else "")
                            assignee_wants = bool(
                                assignee and assignee_email
                                and _wants_ticket_email(
                                    assignee,
                                    category=TICKET_ASSIGNMENT_CATEGORY,
                                    preference_cache=email_preference_cache))
                            if requester_wants and requester_email:
                                _fe, _ = _tl(ticket_pk)
                                enqueue_email(
                                    event_type="ticket.email.created",
                                    to_email=requester_email,
                                    subject=(f"Ticket #{ticket_pk} created: "
                                             f"{ticket_title}"),
                                    body=(f"Your ticket was created.\n"
                                          f"Status: {ticket_status}\nView: {_fe}"),
                                    recipient=user, category="", ticket_id=ticket_pk)
                            if assignee_wants:
                                _fe, _ = _tl(ticket_pk)
                                enqueue_email(
                                    event_type="ticket.email.assigned",
                                    to_email=assignee_email,
                                    subject=f"Ticket #{ticket_pk} assigned to you",
                                    body=(f"{ticket_title}\nPriority: "
                                          f"{ticket_priority}\nView: {_fe}"),
                                    recipient=assignee,
                                    category=TICKET_ASSIGNMENT_CATEGORY,
                                    ticket_id=ticket_pk)
                            if operation is not None:
                                TicketBulkImportRowOutcome.objects.create(
                                    operation=operation,
                                    row_index=idx,
                                    row_number=i,
                                    row_fingerprint=_ticket_bulk_import_row_fingerprint(data),
                                    outcome=TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED,
                                    ticket=obj,
                                    error_message="",
                                )
                            def _send_bulk_followups(
                                _ticket=obj, _asset_id=ticket_asset_id,
                                _req_wants=requester_wants,
                                _assignee_wants=assignee_wants,
                                _maint_cache=maint_cache,
                                _sla=sla,
                            ):
                                try:
                                    ticket = _ticket
                                    if ticket is None:
                                        return
                                    if _req_wants:
                                        if _sla:
                                            _notify_sla_approaching(ticket)
                                            _notify_sla_breached(ticket)
                                        if _asset_id:
                                            from assets.models import Maintenance
                                            if _asset_id not in _maint_cache:
                                                _maint_cache[_asset_id] = Maintenance.objects.filter(
                                                    asset=_asset_id).first()
                                            maint = _maint_cache[_asset_id]
                                            if maint:
                                                _notify_maintenance_reminder(maint)
                                    if _assignee_wants:
                                        if _sla:
                                            _notify_sla_approaching(ticket)
                                            _notify_sla_breached(ticket)
                                        if _asset_id:
                                            from assets.models import Maintenance
                                            if _asset_id not in _maint_cache:
                                                _maint_cache[_asset_id] = Maintenance.objects.filter(
                                                    asset=_asset_id).first()
                                            maint = _maint_cache[_asset_id]
                                            if maint:
                                                _notify_maintenance_reminder(maint)
                                except Exception:
                                    pass
                            transaction.on_commit(_send_bulk_followups)
                            ok.append({"row": i, "id": obj.pk, "title": obj.title})
                    except Exception as exc:
                        failed.append({"row": i, "errors": str(exc)})
                        if operation is not None:
                            _record_ticket_bulk_import_row_failure(
                                operation, idx, i, data, exc)
                    _persist_operation_progress()
        except Exception as exc:
            # Unexpected failure during processing/finalization; record as failed
            # operation so a retry does not blindly duplicate work. Manual review
            # may be required if any per-row commits already occurred.
            if operation is not None:
                try:
                    now = timezone.now()
                    counts = {
                        "total_rows": row_count,
                        "processed_count": len(ok) + len(failed) + len(skipped),
                        "successful_count": len(ok),
                        "failed_count": len(failed),
                    }
                    TicketBulkImportOperation.objects.filter(
                        pk=operation.pk, user=user).update(
                        status=TicketBulkImportOperation.STATUS_FAILED,
                        error_detail=_flatten_ticket_message(exc),
                        updated_at=now,
                        **counts)
                    op = TicketBulkImportOperation.objects.filter(
                        pk=operation.pk, user=user).first()
                    if op and op.status != TicketBulkImportOperation.STATUS_FAILED:
                        op.status = TicketBulkImportOperation.STATUS_FAILED
                        op.error_detail = _flatten_ticket_message(exc)
                        op.updated_at = now
                        for k, v in counts.items():
                            setattr(op, k, v)
                        op.save(update_fields=[
                            "status", "error_detail", "total_rows",
                            "processed_count", "successful_count",
                            "failed_count", "updated_at"])
                except Exception:
                    # Best-effort: do not mask the original processing error.
                    pass
            raise

        # Build and persist the final response (after durable per-row outcomes).
        if request.query_params.get("download") == "csv":
            import csv as _csv
            report_rows = _ticket_report_rows(ok, failed)
            out = io.StringIO()
            writer = _csv.writer(out)
            writer.writerow(["row", "key", "outcome", "message"])
            for r in report_rows:
                writer.writerow([r.get("row", ""), r.get("key", ""),
                                 r.get("outcome", ""), r.get("message", "")])
            csv_body = out.getvalue()
            if operation is not None:
                TicketBulkImportOperation.objects.filter(
                    pk=operation.pk, user=user).update(
                    status=TicketBulkImportOperation.STATUS_COMPLETED,
                    result_format="csv",
                    result_csv=csv_body,
                    result_json=None,
                    result_status_code=200,
                    total_rows=row_count,
                    processed_count=len(ok) + len(failed) + len(skipped),
                    successful_count=len(ok),
                    failed_count=len(failed),
                    completed_at=timezone.now(),
                    error_detail="",
                    updated_at=timezone.now())
            from django.http import HttpResponse
            resp = HttpResponse(csv_body, content_type="text/csv")
            resp["Content-Disposition"] = 'attachment; filename="ticket_import_report.csv"'
            return resp

        payload = {"successful": ok, "skipped": skipped,
                   "failed": failed,
                   "summary": {"ok": len(ok),
                               "skipped": len(skipped),
                               "failed": len(failed)}}
        if operation is not None:
            TicketBulkImportOperation.objects.filter(
                pk=operation.pk, user=user).update(
                status=TicketBulkImportOperation.STATUS_COMPLETED,
                result_format="json",
                result_json=payload,
                result_csv="",
                result_status_code=200,
                total_rows=row_count,
                processed_count=len(ok) + len(failed) + len(skipped),
                successful_count=len(ok),
                failed_count=len(failed),
                completed_at=timezone.now(),
                error_detail="",
                updated_at=timezone.now())
        return Response(payload)

    @action(detail=False, methods=["post"])
    def bulk_update(self, request):
        """Explicit bulk ops: assign / priority / category / status.

        Body: {"ids": [...], "changes": {...}, "preview": true, "confirm": true}
        Each ticket validated individually; partial per-row results.
        """
        ids = request.data.get("ids", [])
        changes = request.data.get("changes", {})
        allowed = {"assignee", "priority", "category", "status"}
        unknown = set(changes) - allowed
        if unknown:
            return Response({"detail": f"Only {sorted(allowed)} allowed.",
                             "unknown": sorted(unknown)}, status=400)
        tickets = list(_ticket_visible_qs(request.user).filter(
            id__in=ids).select_for_update(of=("self",)))
        if request.data.get("preview", True) in (True, "true", "1", 1):
            invalid = []
            for t in tickets:
                if "status" in changes and not Ticket.can_transition(
                        t.status, changes["status"]):
                    invalid.append({"id": t.pk, "from": t.status,
                                    "to": changes["status"]})
            return Response({"preview": [{"id": t.pk, "title": t.title,
                                           "status": t.status} for t in tickets],
                             "affected": len(tickets),
                             "invalid_transitions": invalid,
                             "changes": changes})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed, skipped = [], [], []
        for t in tickets:
            try:
                with transaction.atomic():
                    old = {"status": t.status, "priority": t.priority,
                           "category": t.category_id, "assignee": t.assignee_id}
                    if "status" in changes and not Ticket.can_transition(
                            t.status, changes["status"]):
                        skipped.append({"id": t.pk,
                                        "reason": f"invalid {t.status}->{changes['status']}"})
                        continue
                    for field, val in changes.items():
                        if field == "category":
                            from tickets.models import TicketCategory as TC
                            cat = TC.objects.filter(pk=val).first()
                            if not cat or not cat.is_active:
                                raise ValueError("invalid/inactive category")
                            t.category = cat
                        elif field == "assignee":
                            from accounts.models import User
                            if not val:
                                t.assignee = None
                            else:
                                target = User.objects.filter(
                                    pk=val).first()
                                if target is None:
                                    raise ValueError(
                                        f"unknown assignee {val}")
                                if not target.is_active:
                                    raise ValueError(
                                        "assignee "
                                        f"{target.employee_id} is inactive")
                                t.assignee = target
                        elif field == "priority":
                            # Validate priority against allowed choices,
                            # mirroring serializer validation for single-ticket PATCH.
                            if val not in dict(Ticket.PRIORITY_CHOICES):
                                raise ValueError(
                                    f"Invalid priority: {val}. "
                                    f"Must be one of: {', '.join(dict(Ticket.PRIORITY_CHOICES))}."
                                )
                            setattr(t, field, val)
                        else:
                            setattr(t, field, val)
                    # Same timestamp rule as the single-ticket path:
                    # -> resolved stamps resolved_at, -> closed stamps
                    # closed_at, reopen clears both; no-ops never touch
                    # them (mirrors perform_update).
                    target_status = changes.get("status")
                    if target_status and target_status != old["status"]:
                        if target_status == "resolved":
                            t.resolved_at = timezone.now()
                        elif target_status == "closed":
                            t.closed_at = timezone.now()
                        elif target_status in ("reopened", "in_progress",
                                               "open"):
                            t.resolved_at = None
                            t.closed_at = None
                    # SLA pause management: create/end pauses when entering
                    # or leaving a waiting state (mirrors perform_update).
                    _manage_sla_pause(t, old["status"],
                                      target_status if target_status != old["status"] else None,
                                      request.user)
                    t.save()
                    _write_history(t, request.user, "bulk_change",
                                   old=old, new=dict(changes))
                    log_action(actor=request.user, action="bulk_update",
                               instance=t, details={"changes": changes})
                    # In-app: same recipients as single-ticket changes.
                    if ("assignee" in changes and t.assignee_id is not None
                            and t.assignee_id != old["assignee"]):
                        _notify_user(
                            t.assignee, request.user,
                            f"Ticket #{t.pk} assigned to you",
                            f"{t.title}\nPriority: {t.priority}", t)
                    if ("status" in changes
                            and changes["status"] != old["status"]):
                        _notify_user(
                            t.requester, request.user,
                            f"Ticket #{t.pk} status: {changes['status']}",
                            f"{t.title}\nChanged {old['status']} -> "
                            f"{changes['status']}", t)
                    ok.append(t.pk)
            except Exception as exc:
                failed.append({"id": t.pk, "errors": str(exc)})
        return Response({"successful": ok, "skipped": skipped,
                         "failed": failed,
                         "summary": {"ok": len(ok),
                                     "skipped": len(skipped),
                                     "failed": len(failed)}})

    @action(detail=False, methods=["post"])
    def bulk_delete(self, request):
        """Bulk SOFT delete only. Never hard-deletes (spec)."""
        ids = request.data.get("ids", [])
        tickets = list(_ticket_visible_qs(request.user).filter(
            id__in=ids).select_for_update(of=("self",)))
        if request.data.get("preview", True) in (True, "true", "1", 1):
            return Response({"preview": [{"id": t.pk, "title": t.title}
                                          for t in tickets],
                             "affected": len(tickets),
                             "note": "soft delete only; history preserved"})
        if not request.data.get("confirm"):
            return Response({"detail": "Confirmation required."}, status=400)
        ok, failed = [], []
        for t in tickets:
            try:
                with transaction.atomic():
                    t.soft_delete(
                        by_user=request.user,
                        reason=request.data.get("reason", "bulk soft delete"))
                    _write_history(t, request.user, "soft_deleted",
                                   note="bulk")
                    log_action(actor=request.user, action="bulk_soft_delete",
                               instance=t)
                    ok.append(t.pk)
            except Exception as exc:
                failed.append({"id": t.pk, "errors": str(exc)})
        return Response({"successful": ok, "failed": failed})


class TicketHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TicketHistory.objects.select_related("ticket", "actor").all()
    serializer_class = TicketHistorySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        ticket_id = self.request.query_params.get("ticket")
        if ticket_id:
            qs = qs.filter(ticket_id=ticket_id)
        user = self.request.user
        if is_system_admin(user) or getattr(user, "role", "") == "it_manager":
            return qs
        if getattr(user, "role", "") == "it_support":
            if not user.has_perm("tickets.view_ticket_history"):
                return qs.none()
            return qs
        return qs.none()



class TicketAttachmentViewSet(viewsets.ModelViewSet):
    queryset = TicketAttachment.objects.all()
    serializer_class = TicketAttachmentSerializer

    def get_permissions(self):
        # Uploads stay available to anyone who can see the ticket (the
        # serializer and perform_create enforce that scope), but editing or
        # deleting an existing attachment is an IT-staff operation — the UI
        # exposes those controls to staff only.
        if self.action in ("update", "partial_update", "destroy"):
            return [IsITStaff()]
        return super().get_permissions()

    def get_queryset(self):
        # Only attachments on visible tickets (private files, no public URLs).
        visible_ids = _ticket_visible_qs(self.request.user).values("pk")
        return TicketAttachment.objects.filter(ticket_id__in=visible_ids)

    def perform_create(self, serializer):
        ticket = serializer.validated_data.get("ticket")
        if ticket and ticket.pk:
            visible = _ticket_visible_qs(self.request.user).filter(
                pk=ticket.pk).exists()
            if not visible:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Cannot attach to this ticket.")
        upload = serializer.validated_data.get("file")
        filename = (getattr(upload, "name", "") or "")[:255]
        size = getattr(upload, "size", None)
        # Write the physical file first so the exact storage object this
        # request created is known. Django's own FileField.save() writes the
        # file *before* the INSERT, leaving an unreferenced file behind if
        # the row (or the history/audit rows written with it) fails.
        # Passing the resulting name back as a plain string keeps Django
        # from writing the file a second time.
        stored_name = store_upload(TicketAttachment, upload)
        try:
            with transaction.atomic():
                save_kwargs = {
                    "uploaded_by": self.request.user,
                    "original_filename": filename,
                }
                if stored_name:
                    save_kwargs["file"] = stored_name
                obj = serializer.save(**save_kwargs)
                _write_history(
                    obj.ticket, self.request.user, "attachment_added",
                    new={"attachment_id": obj.pk, "filename": filename,
                         "size": size})
                log_action(actor=self.request.user, action="create",
                           instance=obj)
        except Exception:
            # The transaction rolled back, so no row references the file
            # this request just wrote. Remove exactly that file (never the
            # client-supplied name, which may belong to another row) and let
            # the original exception surface unchanged.
            delete_stored_file(TicketAttachment, stored_name)
            raise

    def perform_update(self, serializer):
        """Replace the file (if one was sent) without orphaning it on failure.

        The superseded file is still left in storage after a successful
        replacement, matching the pre-existing retention behaviour; only a
        failed database write is cleaned up here.
        """
        upload = serializer.validated_data.get("file")
        stored_name = store_upload(TicketAttachment, upload)
        try:
            with transaction.atomic():
                save_kwargs = {}
                if stored_name:
                    save_kwargs["file"] = stored_name
                    save_kwargs["original_filename"] = (
                        getattr(upload, "name", "") or "")[:255]
                obj = serializer.save(**save_kwargs)
                if stored_name:
                    _write_history(
                        obj.ticket, self.request.user, "attachment_updated",
                        new={"attachment_id": obj.pk,
                             "filename": obj.original_filename,
                             "size": getattr(upload, "size", None)})
                    log_action(actor=self.request.user, action="update",
                               instance=obj)
        except Exception:
            delete_stored_file(TicketAttachment, stored_name)
            raise

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        # Soft delete keeps the physical file (record retained). History is
        # written in the same transaction so a failed delete leaves neither a
        # deleted row nor a misleading timeline entry.
        with transaction.atomic():
            obj.soft_delete(by_user=request.user, reason="attachment removed")
            _write_history(
                obj.ticket, request.user, "attachment_removed",
                old={"attachment_id": obj.pk,
                     "filename": obj.original_filename})
            log_action(actor=request.user, action="soft_delete", instance=obj)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Permission-checked download. Never expose storage URLs directly."""
        import mimetypes
        import os

        from django.http import FileResponse
        from common.attachment_security import (
            add_download_security_headers,
            safe_content_disposition_filename,
        )
        obj = self.get_object()  # scoped to visible tickets above
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
        safe_name = safe_content_disposition_filename(name)
        resp["Content-Disposition"] = f'attachment; filename="{safe_name}"'
        add_download_security_headers(resp)
        return resp


class TicketKbArticleViewSet(viewsets.ModelViewSet):
    """Links KB articles to tickets.

    Permissions:
    - IT staff can create/list/update/delete links (curate articles for a
      ticket).
    - Employees can only PATCH the `helpful` flag on links to tickets they
      can see (their own + home-department tickets), marking an article as
      solving/not solving their issue.
    """
    serializer_class = TicketKbArticleSerializer

    def get_queryset(self):
        user = self.request.user
        visible_ids = _ticket_visible_qs(user).values("pk")
        qs = TicketKbArticle.objects.filter(ticket_id__in=visible_ids)
        if not _is_ticket_staff(user):
            # Employees see links on tickets they can see, and can only
            # vote on their own ticket links.
            return qs.filter(ticket__requester=user)
        return qs

    def get_permissions(self):
        # Employees may vote ``helpful`` on links for their own tickets; all
        # other mutations (including unlink/delete) are staff operations.
        if self.action in ("create", "destroy"):
            return [IsITStaff()]
        return super().get_permissions()

    def perform_create(self, serializer):
        if not _is_ticket_staff(self.request.user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                "Only IT staff can link KB articles to tickets.")
        serializer.save(linked_by=self.request.user)

    def perform_update(self, serializer):
        obj = self.get_object()
        if not _is_ticket_staff(self.request.user):
            # Employees may only toggle `helpful` on their own ticket links.
            allowed = {"helpful"}
            changed = set(serializer.validated_data.keys()) - allowed
            if changed:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    "Employees can only update the helpful flag.")
        serializer.save()


class TicketSLAViewSet(viewsets.ModelViewSet):
    """Admin-configurable SLA targets per ticket priority."""

    queryset = TicketSLA.objects.all().order_by("priority")
    serializer_class = TicketSLASerializer
    permission_classes = [IsSystemAdmin]

    def perform_create(self, serializer):
        obj = serializer.save()
        log_action(actor=self.request.user, action="create", instance=obj)

    def perform_update(self, serializer):
        obj = serializer.save()
        log_action(actor=self.request.user, action="update", instance=obj)

    def destroy(self, request, *args, **kwargs):
        # Never hard-delete SLA config; deactivate instead.
        obj = self.get_object()
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        log_action(actor=request.user, action="update", instance=obj,
                   details={"deactivated": True})
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsITStaff])
def sla_report(request):
    """SLA health: overdue count + average resolution time by priority.

    Query params: ?date_from=&date_to= filter created_at window.
    IT staff only (matches the report audience; SLA config is admin-only).
    """
    from django.utils import timezone
    from tickets.models import Ticket

    base = Ticket.objects.all()
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    if date_from:
        base = base.filter(created_at__gte=date_from)
    if date_to:
        base = base.filter(created_at__lte=date_to)

    now = timezone.now()
    overdue = base.filter(
        sla_due_at__lt=now).exclude(
        status__in=["resolved", "closed", "archived"]).count()

    resolved = base.exclude(resolved_at__isnull=True)
    by_priority = []
    for priority, _label in Ticket.PRIORITY_CHOICES:
        pq = resolved.filter(priority=priority)
        # Compute mean resolution hours in Python to stay DB-agnostic
        # (sqlite cannot Avg date/time fields stored as text).
        deltas = [
            (t.resolved_at - t.created_at).total_seconds() / 3600
            for t in pq.only("created_at", "resolved_at")]
        avg_hours = round(sum(deltas) / len(deltas), 2) if deltas else None
        by_priority.append({
            "priority": priority,
            "resolved": pq.count(),
            "avg_resolution_hours": avg_hours,
        })

    return Response({
        "overdue": overdue,
        "by_priority": by_priority,
        "filters": {"date_from": date_from, "date_to": date_to},
        "generated_at": now.isoformat(),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def category_report(request):
    """Tickets-by-category aggregation (ORM, permission-aware, date filter).

    Returns per-category: total, open/unresolved, resolved/closed,
    high_count, critical_count, and urgent (= high + critical, kept for
    backward compatibility). Optional ?date_from & ?date_to filter
    created_at. Categories with zero matching tickets are omitted, as
    before.
    """
    from django.db.models import Count, Q
    from tickets.models import TicketCategory

    if getattr(request.user, "role", "") == "employee" and not (
            is_system_admin(request.user)):
        base = _ticket_visible_qs(request.user)
    else:
        base = Ticket.objects.all()
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    if date_from:
        base = base.filter(created_at__gte=date_from)
    if date_to:
        base = base.filter(created_at__lte=date_to)
    open_statuses = ["open", "in_progress", "reopened"]
    closed_statuses = ["resolved", "closed"]
    rows = (TicketCategory.objects.filter(
        id__in=base.values("category_id")).annotate(
        total=Count("tickets", filter=Q(tickets__in=base)),
        open_count=Count("tickets", filter=Q(tickets__in=base,
                                             tickets__status__in=open_statuses)),
        closed_count=Count("tickets", filter=Q(
            tickets__in=base, tickets__status__in=closed_statuses)),
        high_count=Count("tickets", filter=Q(tickets__in=base,
                                             tickets__priority="high")),
        critical_count=Count("tickets", filter=Q(
            tickets__in=base, tickets__priority="critical")),
        urgent=Count("tickets", filter=Q(tickets__in=base,
                                         tickets__priority__in=["high",
                                                               "critical"])),
    ).values("id", "name", "total", "open_count", "closed_count",
             "high_count", "critical_count", "urgent"))
    return Response({"results": list(rows),
                     "filters": {"date_from": date_from, "date_to": date_to}})

    @action(detail=True, methods=["post"])
    def watch(self, request, pk=None):
        from tickets.collaboration_services import add_watcher
        from tickets.advanced_serializers import TicketWatcherCreateSerializer
        from accounts.models import User
        ticket = self.get_object()
        ser = TicketWatcherCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user_id = ser.validated_data.get("user")
        user = User.objects.get(pk=user_id) if user_id else request.user
        try:
            watcher = add_watcher(ticket, {"user": user,
                                           "watch_type": ser.validated_data.get(
                                               "watch_type", "watcher")},
                                  request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"detail": "watcher added", "id": watcher.pk})

    @action(detail=True, methods=["post"])
    def unwatch(self, request, pk=None):
        from tickets.collaboration_services import remove_watcher
        from accounts.models import User
        ticket = self.get_object()
        user_id = request.data.get("user")
        user = User.objects.get(pk=user_id) if user_id else request.user
        try:
            remove_watcher(ticket, user, request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"detail": "watcher removed"})

    @action(detail=True, methods=["get"])
    def watchers(self, request, pk=None):
        from tickets.collaboration_services import list_watchers
        from tickets.advanced_serializers import TicketWatcherSerializer
        ticket = self.get_object()
        qs = list_watchers(ticket, request.user)
        return Response(TicketWatcherSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"])
    def request_information(self, request, pk=None):
        from tickets.resolution_services import request_information
        from tickets.advanced_serializers import RequestInformationSerializer
        ticket = self.get_object()
        ser = RequestInformationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            ticket, note, pause = request_information(
                ticket, ser.validated_data, request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(TicketSerializer(ticket).data)


    @action(detail=True, methods=["post"])
    def apply_canned_response(self, request, pk=None):
        from tickets.template_services import apply_canned_response
        from tickets.advanced_serializers import CannedResponseApplySerializer
        ticket = self.get_object()
        ser = CannedResponseApplySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            note = apply_canned_response(ticket, ser.validated_data, request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"detail": "applied", "note_id": note.pk})


class TicketBulkImportOperationViewSet(viewsets.ReadOnlyModelViewSet):
    """Staff-only operational inspection for ticket bulk imports.

    Exposes status, timestamps, counts, and error/result metadata without
    returning import tokens, payload fingerprints, preview payloads, or
    stored result bodies.
    """

    serializer_class = TicketBulkImportOperationSerializer
    permission_classes = [IsITStaff]
    queryset = TicketBulkImportOperation.objects.select_related("user").all()

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        user_id = self.request.query_params.get("user")
        if user_id:
            qs = qs.filter(user_id=user_id)
        return qs.order_by("-created_at")

    @action(detail=True, methods=["get"], url_path="reconciliation")
    def reconciliation(self, request, pk=None):
        """Read-only reconciliation preview based on durable row-outcome evidence.

        Uses recorded row outcomes (not aggregate counters) as the source of
        truth for committed/failed rows. Legacy operations created before
        row-level tracking may be incomplete or ambiguous. The response
        includes a structured assessment and evidence digest for safe,
        staff-authorized finalization confirmation.
        """
        from tickets.bulk_import_reconciliation import build_preview_payload

        op = self.get_object()
        assessment = build_preview_payload(op)

        # Backward-compatible fields for existing inspection consumers/tests.
        committed_ticket_ids = list(
            TicketBulkImportRowOutcome.objects.filter(
                operation=op,
                outcome=TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED,
                ticket_id__isnull=False)
            .order_by("row_index")
            .values_list("ticket_id", flat=True))
        legacy_possible = bool(
            assessment.get("legacy_or_ambiguous_indicators")
            and "legacy_or_ambiguous_evidence" in (assessment.get("reasons") or []))
        ambiguous = ("legacy_or_ambiguous_evidence" in (assessment.get("reasons") or [])
                     or assessment.get("unprocessed_row_count", 0) > 0)
        investigation_reasons = list(assessment.get("reasons") or [])
        if assessment.get("is_stale_processing") and "stale_or_interrupted" not in investigation_reasons:
            investigation_reasons.append("stale_or_interrupted")
        if (op.status == TicketBulkImportOperation.STATUS_COMPLETED
                and not assessment.get("result_stored")
                and "completed_without_stored_result" not in investigation_reasons):
            investigation_reasons.append("completed_without_stored_result")
        # Backward-compatible aliases for existing consumers.
        if "legacy_or_ambiguous_evidence" in investigation_reasons and "ambiguous_or_legacy_evidence" not in investigation_reasons:
            investigation_reasons.append("ambiguous_or_legacy_evidence")
        if "unprocessed_or_unrecorded_rows" in investigation_reasons and "unprocessed_or_unrecorded_rows" not in investigation_reasons:
            pass

        payload = {
            **assessment,
            "operation_id": op.pk,
            "status": assessment.get("current_status", op.status),
            "expected_rows": assessment.get("expected_row_count", 0),
            "recorded_successful_rows": assessment.get("succeeded_outcome_count", 0),
            "recorded_failed_rows": assessment.get("failed_outcome_count", 0),
            "unprocessed_or_unrecorded_rows": assessment.get("unprocessed_row_count", 0),
            "unprocessed_or_unrecorded_note": (
                "Derived from durable row-outcome evidence and expected row coverage."
                if assessment.get("has_row_level_evidence") or assessment.get("expected_row_count", 0) > 0
                else "No durable row-level outcomes recorded."),
            "committed_ticket_ids": committed_ticket_ids,
            "result_stored": assessment.get("result_stored", False),
            "last_processing_activity": op.completed_at or op.started_at or op.updated_at,
            "evidence": {
                "has_row_level_outcomes": assessment.get("has_row_level_evidence", False),
                "row_level_tracking_available": assessment.get("has_row_level_evidence", False) or not legacy_possible,
                "legacy_or_pre_tracking": legacy_possible,
                "ambiguous": ambiguous,
                "notes": list(assessment.get("legacy_or_ambiguous_indicators") or []),
            },
            "eligible_for_investigation": bool(investigation_reasons),
            "investigation_reasons": investigation_reasons,
        }
        return Response(payload)

    @action(detail=True, methods=["post"], url_path="reconciliation/finalize")
    def reconciliation_finalize(self, request, pk=None):
        """Staff-authorized, audited, idempotent finalization from durable evidence.

        Requires a reason and the evidence digest from a current read-only
        reconciliation preview. The operation is re-evaluated under lock; stale
        or ineligible requests are rejected without mutating state.
        """
        from tickets.bulk_import_reconciliation import (
            BulkImportNotEligible, BulkImportReconciliationError,
            BulkImportStaleEvidence, finalize_operation,
        )

        op = self.get_object()
        reason = str(request.data.get("reason") or "").strip()
        evidence_digest = str(request.data.get("evidence_digest") or "").strip()
        expected_status = request.data.get("expected_status")
        if expected_status is not None:
            expected_status = str(expected_status)

        if not reason:
            return Response({"detail": "A reason is required for finalization."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not evidence_digest:
            return Response({"detail": "Evidence digest from a current reconciliation preview is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            result = finalize_operation(
                operation_id=op.pk,
                user_id=op.user_id,
                actor=request.user,
                reason=reason,
                evidence_digest=evidence_digest,
                expected_status=expected_status,
            )
            return Response(result, status=status.HTTP_200_OK)
        except BulkImportStaleEvidence as exc:
            detail = exc.args[0] if exc.args else "Stale reconciliation evidence."
            payload = detail if isinstance(detail, dict) else {"detail": str(detail)}
            payload.setdefault("code", getattr(exc, "code", "stale_evidence"))
            return Response(payload, status=status.HTTP_409_CONFLICT)
        except BulkImportNotEligible as exc:
            detail = exc.args[0] if exc.args else "Operation is not eligible for finalization."
            payload = detail if isinstance(detail, dict) else {"detail": str(detail)}
            payload.setdefault("code", getattr(exc, "code", "not_eligible"))
            return Response(payload, status=status.HTTP_409_CONFLICT)
        except BulkImportReconciliationError as exc:
            detail = exc.args[0] if exc.args else "Reconciliation request is invalid."
            payload = detail if isinstance(detail, dict) else {"detail": str(detail)}
            payload.setdefault("code", getattr(exc, "code", "reconciliation_error"))
            return Response(payload, status=getattr(exc, "status_code", status.HTTP_400_BAD_REQUEST))
        except TicketBulkImportOperation.DoesNotExist:
            return Response({"detail": "Operation not found."}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=["get"], url_path="reconciliation/audit")
    def reconciliation_audit(self, request, pk=None):
        """Read-only finalization audit history for authorized staff."""
        from common.models import AuditLog

        op = self.get_object()
        logs = (AuditLog.objects
                .filter(entity_type="tickets.ticketbulkimportoperation",
                        object_id=str(op.pk))
                .select_related("actor")
                .order_by("-timestamp"))
        entries = []
        for log in logs:
            details = log.details or {}
            # Expose finalization-related audit entries (and keep generic context minimal).
            if details.get("action_type") != "finalize" and "finalization_outcome" not in details:
                continue
            entries.append({
                "id": log.pk,
                "actor": log.actor_id,
                "actor_email": getattr(log.actor, "email", None),
                "timestamp": log.timestamp,
                "action": log.action,
                "reason": log.reason or "",
                "previous_operation_state": details.get("previous_operation_state"),
                "resulting_operation_state": details.get("resulting_operation_state"),
                "expected_row_count": details.get("expected_row_count"),
                "succeeded_row_count": details.get("succeeded_row_count"),
                "failed_row_count": details.get("failed_row_count"),
                "evidence_digest": details.get("evidence_digest"),
                "finalization_outcome": details.get("finalization_outcome"),
                "integrity_assessment": details.get("integrity_assessment"),
            })
        return Response({"operation_id": op.pk, "audit": entries})

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        from tickets.resolution_services import resolve_ticket
        from tickets.advanced_serializers import ResolveTicketSerializer
        ticket = self.get_object()
        ser = ResolveTicketSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            ticket = resolve_ticket(ticket, ser.validated_data, request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        from tickets.resolution_services import close_ticket
        from tickets.advanced_serializers import CloseTicketSerializer
        ticket = self.get_object()
        ser = CloseTicketSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            ticket = close_ticket(ticket, request.user,
                                 ser.validated_data.get("reason", ""),
                                 ser.validated_data.get("expected_ticket_version"))
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(TicketSerializer(ticket).data)


    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        from tickets.resolution_services import reopen_ticket
        from tickets.advanced_serializers import ReopenTicketSerializer
        ticket = self.get_object()
        ser = ReopenTicketSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            ticket = reopen_ticket(ticket, ser.validated_data, request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        from tickets.merge_services import merge_tickets
        from tickets.advanced_serializers import TicketMergeSerializer
        primary = self.get_object()
        ser = TicketMergeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        duplicate_id = ser.validated_data["duplicate_ticket_id"]
        try:
            duplicate = _ticket_visible_qs(request.user).get(
                pk=duplicate_id, is_deleted=False)
        except Ticket.DoesNotExist:
            return Response({"detail": "Duplicate ticket not found."}, status=404)
        options = {"transfer_watchers": ser.validated_data.get(
            "transfer_watchers", True)}
        try:
            primary, duplicate, record = merge_tickets(
                primary, duplicate, request.user,
                ser.validated_data["reason"], options)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"primary": primary.pk, "merged": duplicate.pk,
                         "record": record.pk})

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        from tickets.models import TicketHistory
        ticket = self.get_object()
        user = request.user
        role = getattr(user, "role", "")
        is_admin_or_manager = role in ("system_admin", "it_manager") or getattr(
            user, "is_superuser", False)
        is_support = role == "it_support"
        if is_admin_or_manager:
            pass
        elif is_support and not user.has_perm("tickets.view_ticket_history"):
            return Response(
                {"detail": "You do not have permission to view ticket history."},
                status=403)
        elif not is_admin_or_manager and not is_support:
            return Response(
                {"detail": "You do not have permission to view ticket history."},
                status=403)
        qs = TicketHistory.objects.filter(ticket=ticket).order_by("timestamp")
        events = []
        for h in qs:
            events.append({
                "id": str(h.pk),
                "source": "history",
                "actor": str(h.actor) if h.actor else None,
                "actor_email": getattr(h.actor, "email", None),
                "timestamp": h.timestamp,
                "action": h.action,
                "summary": h.note or h.action,
                "internal": False,
                "url": None,
            })
        page = int(request.query_params.get("page", 1) or 1)
        size = int(request.query_params.get("page_size", 20) or 20)
        start = (page - 1) * size
        end = start + size
        return Response({"results": events[start:end], "count": len(events)})

    @action(detail=True, methods=["get"])
    def satisfaction(self, request, pk=None):
        from tickets.satisfaction_services import get_survey
        from tickets.advanced_serializers import TicketSatisfactionSurveySerializer
        ticket = self.get_object()
        survey = get_survey(ticket, request.user)
        if not survey:
            return Response({"detail": "No survey found."}, status=404)
        return Response(TicketSatisfactionSurveySerializer(survey).data)

    @action(detail=True, methods=["post"], url_path="satisfaction/submit")
    def satisfaction_submit(self, request, pk=None):
        from tickets.satisfaction_services import submit_survey
        from tickets.advanced_serializers import (
            SatisfactionSubmitSerializer, TicketSatisfactionSurveySerializer)
        ticket = self.get_object()
        ser = SatisfactionSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            survey = submit_survey(ticket, ser.validated_data, request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(TicketSatisfactionSurveySerializer(survey).data)


    @action(detail=False, methods=["post"], url_path="check-duplicates")
    def check_duplicates(self, request):
        from tickets.duplicate_services import find_duplicates
        from tickets.advanced_serializers import DuplicateCheckSerializer, DuplicateSuggestionSerializer
        ser = DuplicateCheckSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        candidates = find_duplicates(ser.validated_data, request.user)
        return Response({"results": candidates})

    @action(detail=False, methods=["get"], url_path="operations-dashboard")
    def operations_dashboard(self, request):
        from tickets.metrics_services import operations_dashboard
        filters = {
            "date_from": request.query_params.get("date_from"),
            "date_to": request.query_params.get("date_to"),
            "department": request.query_params.get("department"),
            "queue": request.query_params.get("queue"),
            "assignee": request.query_params.get("assignee"),
            "category": request.query_params.get("category"),
            "priority": request.query_params.get("priority"),
        }
        try:
            data = operations_dashboard(filters, request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(data)

    @action(detail=False, methods=["get"], url_path="agent-workload")
    def agent_workload(self, request):
        from tickets.metrics_services import agent_workload
        filters = {
            "date_from": request.query_params.get("date_from"),
            "date_to": request.query_params.get("date_to"),
            "department": request.query_params.get("department"),
            "queue": request.query_params.get("queue"),
            "assignee": request.query_params.get("assignee"),
            "category": request.query_params.get("category"),
            "priority": request.query_params.get("priority"),
        }
        try:
            data = agent_workload(filters, request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(data)

    @action(detail=False, methods=["get"], url_path="satisfaction-report")
    def satisfaction_report(self, request):
        from tickets.satisfaction_services import satisfaction_report
        filters = {
            "date_from": request.query_params.get("date_from"),
            "date_to": request.query_params.get("date_to"),
        }
        try:
            data = satisfaction_report(filters, request.user)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(data)

