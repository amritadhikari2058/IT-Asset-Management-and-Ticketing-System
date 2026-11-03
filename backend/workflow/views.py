"""Workflow APIs (Phase 19): automation rules, executions, approvals.

Permissions (mirroring PERMISSIONS.md policies elsewhere in the project):
- Automation rules: IT staff can view; System Admins create/edit/delete.
- Rule executions are operational history: IT staff only.
- Approval requests: visibility mirrors ticket visibility (staff see all;
  employees only approvals on tickets they can see). IT staff decide;
  the requester can never decide their own request; a decided request
  cannot be decided again (409 for repeats/stale clients).
"""
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from common.audit import log_action
from common.permissions import IsITStaff, IsSystemAdmin
from tickets.models import Ticket

from .models import AutomationRule, ApprovalRequest, RuleExecution
from .serializers import (
    ApprovalRequestSerializer, AutomationRuleSerializer,
    RuleExecutionSerializer,
)
from .services import is_ticket_staff, ticket_visible_qs


def _ticket_visible_qs(user):
    return ticket_visible_qs(user)


def _write_history(ticket, actor, action, old=None, new=None, note=""):
    from tickets.models import TicketHistory
    TicketHistory.objects.create(
        ticket=ticket, actor=actor, action=action,
        old_values=old or {}, new_values=new or {}, note=note)


def _notify_user(recipient, actor, title, body, ticket):
    """In-app notification following the shared ticket-event rules."""
    from common.models import Notification
    if recipient is None or getattr(recipient, "pk", None) is None:
        return None
    if actor is not None and recipient.pk == getattr(actor, "pk", None):
        return None
    if not getattr(recipient, "is_active", True):
        return None
    if getattr(recipient, "is_deleted", False):
        return None
    return Notification.objects.create(
        recipient=recipient, title=title[:255], body=body or "",
        entity_type="tickets.Ticket", object_id=str(ticket.pk))


class AutomationRuleViewSet(viewsets.ModelViewSet):
    queryset = AutomationRule.objects.order_by("name")
    serializer_class = AutomationRuleSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsSystemAdmin()]
        return [IsITStaff()]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("trigger"):
            qs = qs.filter(trigger=p["trigger"])
        if p.get("is_enabled") in ("true", "1"):
            qs = qs.filter(is_enabled=True)
        elif p.get("is_enabled") in ("false", "0"):
            qs = qs.filter(is_enabled=False)
        q = (p.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q)
                           | Q(description__icontains=q))
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user)
        log_action(actor=self.request.user, action="create", instance=obj)

    def perform_update(self, serializer):
        obj = serializer.save(updated_by=self.request.user)
        log_action(actor=self.request.user, action="update", instance=obj)

    def destroy(self, request, *args, **kwargs):
        # Never hard-delete a rule: its RuleExecution rows are audit
        # history. Deactivate instead (mirrors the SLA-config policy).
        obj = self.get_object()
        obj.is_enabled = False
        obj.save(update_fields=["is_enabled", "updated_at"])
        log_action(actor=request.user, action="update", instance=obj,
                   details={"deactivated": True})
        return Response(status=status.HTTP_204_NO_CONTENT)


class RuleExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    """Rule execution history (IT staff only).

    Filters: ?rule= ?ticket= ?success=true|false ?status=success|failure
    ?trigger= ?date_from= ?date_to= ?q= (rule name / ticket title / id).
    """

    queryset = RuleExecution.objects.select_related("rule", "ticket").all()
    serializer_class = RuleExecutionSerializer
    permission_classes = [IsITStaff]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("rule"):
            qs = qs.filter(rule_id=p["rule"])
        if p.get("ticket"):
            qs = qs.filter(ticket_id=p["ticket"])
        status = p.get("status")
        if status == "success":
            qs = qs.filter(success=True)
        elif status == "failure":
            qs = qs.filter(success=False)
        elif p.get("success") in ("true", "1"):
            qs = qs.filter(success=True)
        elif p.get("success") in ("false", "0"):
            qs = qs.filter(success=False)
        trigger = p.get("trigger")
        if trigger:
            qs = qs.filter(
                rule__trigger=trigger)  # executions inherit rule triggers
        date_from = p.get("date_from")
        date_to = p.get("date_to")
        if date_from:
            qs = qs.filter(created_at__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)
        q = (p.get("q") or "").strip()
        if q:
            filt = Q(rule__name__icontains=q) | Q(
                ticket__title__icontains=q) | Q(detail__icontains=q)
            if q.isdigit():
                filt |= Q(ticket_id=int(q)) | Q(id=int(q))
            qs = qs.filter(filt)
        return qs


class ApprovalRequestViewSet(viewsets.ModelViewSet):
    """Approval requests for sensitive ticket operations.

    POST creates a pending request; decisions only via /approve/ and
    /reject/ actions. Approving applies the requested operation to the
    ticket (invalid transitions fail 400 and leave the request pending).
    """
    queryset = ApprovalRequest.objects.select_related(
        "ticket", "requested_by", "approver", "decided_by").all()
    serializer_class = ApprovalRequestSerializer
    http_method_names = ["get", "post", "head", "options", "delete"]

    def get_permissions(self):
        if self.action in ("approve", "reject", "destroy"):
            return [IsITStaff()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if not is_ticket_staff(user):
            qs = qs.filter(ticket__in=_ticket_visible_qs(user).values("id"))
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("ticket"):
            qs = qs.filter(ticket_id=p["ticket"])
        if p.get("operation"):
            qs = qs.filter(operation=p["operation"])
        if p.get("requested_by"):
            qs = qs.filter(requested_by_id=p["requested_by"])
        q = (p.get("q") or "").strip()
        if q:
            filt = Q(ticket__title__icontains=q) | Q(reason__icontains=q)
            if q.isdigit():
                filt |= Q(ticket_id=int(q)) | Q(pk=int(q))
            qs = qs.filter(filt)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(requested_by=self.request.user,
                              status="pending")
        _write_history(
            obj.ticket, self.request.user, "approval_requested",
            new={"approval_id": obj.pk, "operation": obj.operation,
                 "context": obj.context},
            note=obj.reason[:200])
        log_action(actor=self.request.user, action="approval_requested",
                   instance=obj)
        # Queue visibility: IT managers and system admins learn about the
        # pending request (never the requester themselves).
        from accounts.models import User
        recipients = set()
        for u in User.objects.filter(
                is_active=True, is_deleted=False,
                role="it_manager").exclude(pk=self.request.user.pk):
            recipients.add(u.pk)
        for u in User.objects.filter(
                is_active=True, is_deleted=False, is_superuser=True):
            recipients.add(u.pk)
        for rid in recipients:
            _notify_user(
                User.objects.get(pk=rid), self.request.user,
                f"Approval requested for ticket #{obj.ticket_id}",
                f"{obj.get_operation_display()}: {obj.ticket.title}"
                + (f"\nReason: {obj.reason}" if obj.reason else ""),
                obj.ticket)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.is_decided:
            return Response(
                {"detail": "Decided approvals cannot be deleted."},
                status=409)
        obj.delete()
        _write_history(obj.ticket, request.user, "approval_withdrawn",
                       old={"approval_id": obj.pk})
        log_action(actor=request.user, action="approval_withdrawn",
                   instance=obj)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, approve=True)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, approve=False)

    def _decide(self, request, approve):
        obj = self.get_object()
        comment = (request.data.get("comment") or "").strip()
        if obj.requested_by_id == request.user.pk:
            return Response(
                {"detail": "You cannot decide your own approval request."},
                status=403)
        if obj.is_decided:
            return Response(
                {"detail": "This approval has already been decided."},
                status=409)
        ticket = obj.ticket
        try:
            with transaction.atomic():
                locked = (ApprovalRequest.objects.select_for_update()
                          .get(pk=obj.pk))
                if locked.is_decided:
                    # Another approver decided while this client was open.
                    return Response(
                        {"detail": "This approval has already been decided "
                                   "by another user."},
                        status=409)
                if approve and locked.status == "pending":
                    self._apply_operation(locked, ticket, request.user)
                locked.status = "approved" if approve else "rejected"
                locked.decided_by = request.user
                locked.decided_at = timezone.now()
                locked.decision_comment = comment
                locked.save(update_fields=[
                    "status", "decided_by", "decided_at",
                    "decision_comment", "approver", "updated_at"])
                _write_history(
                    locked.ticket, request.user,
                    "approval_" + ("approved" if approve else "rejected"),
                    old={"approval_id": locked.pk},
                    new={"operation": locked.operation,
                         "approval_status": locked.status,
                         "comment": comment[:200]})
                log_action(
                    actor=request.user,
                    action="approve" if approve else "reject",
                    instance=locked,
                    details={"ticket": locked.ticket_id,
                             "operation": locked.operation})
        except ApprovalRequest.DoesNotExist:
            raise NotFound()
        except ValidationError as exc:
            return Response(exc.detail, status=400)
        # Notify the requester about the decision (approver is the actor).
        _notify_user(
            locked.requested_by, request.user,
            f"Approval {'approved' if approve else 'rejected'}: "
            f"ticket #{locked.ticket_id}",
            f"{locked.get_operation_display()}\n"
            + (f"Comment: {comment}" if comment else ""),
            locked.ticket)
        return Response(ApprovalRequestSerializer(locked).data)

    def _apply_operation(self, approval, ticket, approver):
        ctx = approval.context or {}
        if approval.operation == "change_priority":
            old = ticket.priority
            ticket.priority = ctx.get("priority")
            ticket.save(update_fields=["priority", "updated_at"])
            _write_history(ticket, approver, "updated",
                           old={"priority": old},
                           new={"priority": ticket.priority},
                           note=f"Applied from approval #{approval.pk}")
            return
        if approval.operation == "change_status":
            target = ctx.get("status")
            if not Ticket.can_transition(ticket.status, target):
                raise ValidationError(
                    {"detail": f"Cannot transition {ticket.status} -> "
                               f"{target}."})
            old = ticket.status
            ticket.status = target
            if target == "resolved":
                ticket.resolved_at = timezone.now()
            elif target == "closed":
                ticket.closed_at = timezone.now()
            elif target in ("reopened", "in_progress", "open"):
                ticket.resolved_at = None
                ticket.closed_at = None
            ticket.save(update_fields=["status", "resolved_at",
                                       "closed_at", "updated_at"])
            _write_history(ticket, approver, "updated",
                           old={"status": old},
                           new={"status": ticket.status},
                           note=f"Applied from approval #{approval.pk}")
            return
        if approval.operation == "reassign":
            from accounts.models import User
            old = ticket.assignee_id
            user = User.objects.filter(
                pk=int(ctx.get("user_id")), is_active=True).first()
            if user is None:
                raise ValidationError(
                    {"detail": "Assignee not found or inactive."})
            ticket.assignee = user
            ticket.save(update_fields=["assignee", "updated_at"])
            _write_history(ticket, approver, "updated",
                           old={"assignee": old},
                           new={"assignee": user.pk},
                           note=f"Applied from approval #{approval.pk}")
            return
        # operation "other": recorded decision only, nothing applied.
