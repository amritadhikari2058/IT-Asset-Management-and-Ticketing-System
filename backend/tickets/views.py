"""Ticket APIs: categories, tickets, notes, history, bulk, reports.

Visibility:
- System Admin / IT Manager / IT Support: operational scope (all active).
- Employee: own tickets + tickets for home department. Internal notes and
  privileged history hidden (separate permission-checked endpoints).
"""
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.audit import log_action
from common.permissions import IsITStaff, IsSystemAdmin, is_system_admin
from tickets.models import (
    Ticket, TicketAttachment, TicketCategory, TicketHistory, TicketNote,
)
from tickets.serializers import (
    TicketAttachmentSerializer, TicketCategorySerializer,
    TicketHistorySerializer, TicketNoteSerializer, TicketSerializer,
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
        entity_type="tickets.Ticket", object_id=str(ticket.pk))


def _wants_ticket_email(person):
    """Ticket-event email opt-out check for one recipient object.

    Missing flag defaults to True so a lookup can never silently break
    ticket flows. Verification / password-reset mail never consults this.
    """
    return bool(getattr(person, "receive_ticket_emails", True))


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


class TicketViewSet(viewsets.ModelViewSet):
    serializer_class = TicketSerializer

    def get_queryset(self):
        qs = _ticket_visible_qs(self.request.user)
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
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if not getattr(user, "can_create_tickets", True) and not is_system_admin(
                user) and getattr(user, "role", "") not in ("it_manager",
                                                            "it_support"):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Ticket creation disabled for this user.")
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
        obj = serializer.save(requester=user)
        _write_history(obj, user, "created", new={"status": "open"})
        log_action(actor=user, action="create", instance=obj)
        # In-app: the assignee learns they own it (the requester is the
        # actor, so they are never notified of their own action).
        _notify_user(obj.assignee, user,
                     f"Ticket #{obj.pk} assigned to you",
                     f"{obj.title}\nPriority: {obj.priority}", obj)
        from accounts.email_utils import (
            send_ticket_notification, ticket_links,
        )
        try:
            fe, _ = ticket_links(obj.pk)
            if _wants_ticket_email(user):
                send_ticket_notification(
                    user.email, f"Ticket #{obj.pk} created: {obj.title}",
                    f"Your ticket was created.\nStatus: {obj.status}\n"
                    f"View: {fe}")
            if (obj.assignee and obj.assignee.email
                    and _wants_ticket_email(obj.assignee)):
                send_ticket_notification(
                    obj.assignee.email,
                    f"Ticket #{obj.pk} assigned to you",
                    f"{obj.title}\nPriority: {obj.priority}\nView: {fe}")
        except Exception:
            pass

    def perform_update(self, serializer):
        obj = self.get_object()
        old = {"status": obj.status, "priority": obj.priority,
               "category": obj.category_id, "assignee": obj.assignee_id}
        new_status = serializer.validated_data.get("status")
        if new_status and not Ticket.can_transition(obj.status, new_status):
            from rest_framework.exceptions import ValidationError
            raise ValidationError(
                {"status": f"Invalid transition {obj.status} -> {new_status}."})
        updated = serializer.save()
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
        if new_status and new_status != old["status"]:
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
            from accounts.email_utils import (
                send_ticket_notification, ticket_links,
            )
            try:
                fe, _ = ticket_links(updated.pk)
                if (updated.requester and updated.requester.email
                        and _wants_ticket_email(updated.requester)):
                    send_ticket_notification(
                        updated.requester.email,
                        f"Ticket #{updated.pk} status: {new_status}",
                        f"{updated.title}\nChanged {old['status']} -> "
                        f"{new_status}\nView: {fe}")
            except Exception:
                pass
        log_action(actor=self.request.user, action="update", instance=updated,
                   details={"changes": str(changes)})

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
        if request.method == "get":
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
        tickets = list(_ticket_visible_qs(request.user).filter(id__in=ids))
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
                            t.assignee = User.objects.filter(
                                pk=val).first() if val else None
                        else:
                            setattr(t, field, val)
                    if changes.get("status") == "resolved":
                        t.resolved_at = timezone.now()
                    if changes.get("status") == "closed":
                        t.closed_at = timezone.now()
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
        tickets = list(_ticket_visible_qs(request.user).filter(id__in=ids))
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
        resp["Content-Disposition"] = f'attachment; filename="{name}"'
        return resp


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
