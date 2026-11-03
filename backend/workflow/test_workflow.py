"""Workflow (Phase 19) API + engine tests.

Extends (does not replace) workflow/tests.py. Covers permissions, rule
validation, the automation engine (executions on ticket events), the
approval decide flow (comment, self-decision block, stale/duplicate
decisions, operation application) and execution-history filters.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from accounts.tests import auth, make_users
from common.models import Notification
from tickets.models import TicketCategory, TicketNote
from workflow.models import ApprovalRequest, AutomationRule, RuleExecution


def _mk_category():
    return TicketCategory.objects.first() or TicketCategory.objects.create(
        name="WfCat")


def _ticket(requester, department, title="Broken laptop", priority="medium",
            status="open"):
    from tickets.models import Ticket
    return Ticket.objects.create(
        title=title, description="Does not boot.", category=_mk_category(),
        priority=priority, status=status, requester=requester,
        department=department)


class WorkflowApiTestCase(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.support = User.objects.create_user(
            username="s@x", email="s@x", employee_id="S1",
            password="pw12345678", role="it_support",
            home_department=self.dep)
        self.c = APIClient()

    def rule_payload(self, name="Auto note", trigger="ticket_created"):
        return {
            "name": name,
            "description": "Adds a note when a ticket is created",
            "is_enabled": True,
            "trigger": trigger,
            "conditions": {"status": "open"},
            "actions": [{"type": "note", "text": "Auto triage started"}],
        }


class AutomationRuleApiTests(WorkflowApiTestCase):
    URL = "/api/workflow/automation-rules/"

    def test_employee_cannot_list_rules(self):
        auth(self.c, self.emp)
        self.assertEqual(self.c.get(self.URL).status_code, 403)

    def test_it_staff_can_list_rules(self):
        auth(self.c, self.support)
        self.assertEqual(self.c.get(self.URL).status_code, 200)

    def test_it_support_cannot_create_rule(self):
        auth(self.c, self.support)
        res = self.c.post(self.URL, self.rule_payload(), format="json")
        self.assertEqual(res.status_code, 403)

    def test_admin_can_create_rule(self):
        auth(self.c, self.admin)
        res = self.c.post(self.URL, self.rule_payload(), format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["created_by"], self.admin.pk)
        self.assertEqual(res.data["trigger_display"], "Ticket Created")

    def test_created_by_is_ignored_from_payload(self):
        auth(self.c, self.admin)
        payload = self.rule_payload("Created-by check")
        payload["created_by"] = self.emp.pk
        res = self.c.post(self.URL, payload, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertNotEqual(res.data["created_by"], self.emp.pk)

    def test_invalid_trigger_rejected(self):
        auth(self.c, self.admin)
        res = self.c.post(
            self.URL, self.rule_payload("Default trigger is valid"),
            format="json")
        self.assertEqual(res.status_code, 201)
        payload = self.rule_payload("Bad trigger 2")
        payload["trigger"] = "random_event"
        res = self.c.post(self.URL, payload, format="json")
        self.assertEqual(res.status_code, 400)
        # Unknown triggers are caught by the ChoiceField validation.
        self.assertIn("not a valid", str(res.data))

    def test_unsupported_condition_key_rejected(self):
        auth(self.c, self.admin)
        payload = self.rule_payload("Bad condition")
        payload["conditions"] = {"hair_color": "red"}
        res = self.c.post(self.URL, payload, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unsupported condition key", str(res.data))

    def test_invalid_condition_value_rejected(self):
        auth(self.c, self.admin)
        payload = self.rule_payload("Bad condition value")
        payload["conditions"] = {"priority": "urgent"}
        res = self.c.post(self.URL, payload, format="json")
        self.assertEqual(res.status_code, 400)

    def test_unsupported_action_type_rejected(self):
        auth(self.c, self.admin)
        payload = self.rule_payload("Bad action")
        payload["actions"] = [{"type": "reboot_server"}]
        res = self.c.post(self.URL, payload, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unsupported action type", str(res.data))

    def test_assign_action_requires_active_user(self):
        auth(self.c, self.admin)
        payload = self.rule_payload("Assign missing")
        payload["actions"] = [{"type": "assign", "user_id": 987654}]
        res = self.c.post(self.URL, payload, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("not found or inactive", str(res.data))

    def test_note_action_requires_text(self):
        auth(self.c, self.admin)
        payload = self.rule_payload("Empty note")
        payload["actions"] = [{"type": "note", "text": "   "}]
        res = self.c.post(self.URL, payload, format="json")
        self.assertEqual(res.status_code, 400)

    def test_duplicate_name_rejected(self):
        auth(self.c, self.admin)
        self.c.post(self.URL, self.rule_payload(), format="json")
        res = self.c.post(
            self.URL, self.rule_payload("AUTO NOTE"), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("already exists", str(res.data))

    def test_admin_can_edit_rule(self):
        auth(self.c, self.admin)
        rid = self.c.post(
            self.URL, self.rule_payload(), format="json").data["id"]
        payload = self.rule_payload("Renamed")
        payload["trigger"] = "status_changed"
        payload["conditions"] = {"priority": "critical"}
        payload["actions"] = [{"type": "priority", "value": "high"}]
        res = self.c.put(f"{self.URL}{rid}/", payload, format="json")
        self.assertEqual(res.status_code, 200)
        obj = AutomationRule.objects.get(pk=rid)
        self.assertEqual(obj.trigger, "status_changed")
        self.assertEqual(obj.conditions, {"priority": "critical"})
        self.assertEqual(obj.updated_by_id, self.admin.pk)
        self.assertEqual(obj.actions, [{"type": "priority",
                                        "value": "high"}])

    def test_toggle_is_enabled(self):
        auth(self.c, self.admin)
        rid = self.c.post(
            self.URL, self.rule_payload(), format="json").data["id"]
        res = self.c.patch(f"{self.URL}{rid}/", {"is_enabled": False},
                           format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(AutomationRule.objects.get(pk=rid).is_enabled)

    def test_it_support_cannot_delete_rule(self):
        auth(self.c, self.admin)
        rid = self.c.post(
            self.URL, self.rule_payload(), format="json").data["id"]
        auth(self.c, self.support)
        res = self.c.delete(f"{self.URL}{rid}/")
        self.assertEqual(res.status_code, 403)

    def test_admin_delete_deactivates_and_preserves_history(self):
        auth(self.c, self.admin)
        rid = self.c.post(
            self.URL, self.rule_payload(), format="json").data["id"]
        RuleExecution.objects.create(
            rule=AutomationRule.objects.get(pk=rid),
            ticket=_ticket(self.emp, self.dep), success=True, detail="OK")
        res = self.c.delete(f"{self.URL}{rid}/")
        self.assertEqual(res.status_code, 204)
        obj = AutomationRule.objects.get(pk=rid)
        self.assertFalse(obj.is_enabled)
        self.assertTrue(RuleExecution.objects.filter(
            rule_id=rid).exists())


class RuleEngineTests(WorkflowApiTestCase):
    def _rule(self, trigger="ticket_created", conditions=None, actions=None):
        return AutomationRule.objects.create(
            name=f"engine-rule-{AutomationRule.objects.count() + 1}",
            trigger=trigger,
            conditions=conditions if conditions is not None else {},
            actions=actions or [{"type": "note", "text": "Auto triage"}],
            is_enabled=True, created_by=self.admin)

    def test_ticket_created_rule_runs_all_actions(self):
        self._rule(actions=[
            {"type": "note", "text": "Auto triage"},
            {"type": "priority", "value": "high"},
            {"type": "assign", "user_id": self.support.pk},
        ])
        auth(self.c, self.emp)
        res = self.c.post("/api/tickets/", {
            "title": "Engine test", "description": "d",
            "category": _mk_category().pk, "priority": "medium",
        }, format="json")
        self.assertEqual(res.status_code, 201)
        from tickets.models import Ticket
        ticket = Ticket.objects.get(pk=res.data["id"])
        self.assertEqual(ticket.priority, "high")
        self.assertEqual(ticket.assignee_id, self.support.pk)
        self.assertTrue(TicketNote.objects.filter(
            ticket=ticket, body="Auto triage").exists())
        ex = RuleExecution.objects.get(rule__actions__icontains="priority",
                                       ticket=ticket)
        self.assertTrue(ex.success)
        self.assertIn("priority medium -> high", ex.detail)
        self.assertIn("note", ex.detail)

    def test_non_matching_conditions_skip_execution(self):
        self._rule(conditions={"priority": "critical"})
        auth(self.c, self.emp)
        self.c.post("/api/tickets/", {
            "title": "Skipped", "description": "d",
            "category": _mk_category().pk,
        }, format="json")
        self.assertEqual(RuleExecution.objects.count(), 0)

    def test_disabled_rule_does_not_run(self):
        rule = self._rule()
        rule.is_enabled = False
        rule.save()
        _ticket(self.emp, self.dep, "no run")
        self.assertEqual(RuleExecution.objects.count(), 0)

    def test_status_changed_trigger_fires_on_update(self):
        rule = self._rule(trigger="status_changed")
        ticket = _ticket(self.emp, self.dep)
        RuleExecution.objects.all().delete()
        auth(self.c, self.support)
        res = self.c.patch(f"/api/tickets/{ticket.pk}/",
                           {"status": "in_progress"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(RuleExecution.objects.filter(
            rule=rule, ticket=ticket).exists())

    def test_ticket_updated_trigger_fires_on_priority_change(self):
        rule = self._rule(trigger="ticket_updated")
        ticket = _ticket(self.emp, self.dep)
        RuleExecution.objects.all().delete()
        auth(self.c, self.support)
        res = self.c.patch(f"/api/tickets/{ticket.pk}/",
                           {"priority": "high"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(RuleExecution.objects.filter(
            rule=rule, ticket=ticket).exists())

    def test_failed_action_records_failed_execution(self):
        rule = self._rule(trigger="status_changed", actions=[
            {"type": "assign", "user_id": self.support.pk}])
        # ORM-created rules bypass serializer validation, so the assignee
        # can be deactivated after the rule exists.
        self.support.is_active = False
        self.support.save()
        ticket = _ticket(self.emp, self.dep)
        auth(self.c, self.admin)  # admin stays active and performs the update
        self.c.patch(f"/api/tickets/{ticket.pk}/",
                     {"status": "in_progress"}, format="json")
        ex = RuleExecution.objects.get(rule=rule, ticket=ticket)
        self.assertFalse(ex.success)
        self.assertIn("not found or inactive", ex.detail)
        ticket.refresh_from_db()
        self.assertNotEqual(ticket.assignee_id, self.support.pk)

    def test_invalid_status_action_marks_failure(self):
        rule = self._rule(
            trigger="status_changed",
            actions=[{"type": "status", "value": "archived"}])
        # in_progress -> archived is not an allowed transition.
        ticket = _ticket(self.emp, self.dep)
        auth(self.c, self.support)
        self.c.patch(f"/api/tickets/{ticket.pk}/",
                     {"status": "in_progress"}, format="json")
        ex = RuleExecution.objects.get(rule=rule, ticket=ticket)
        self.assertFalse(ex.success)
        self.assertIn("invalid transition in_progress -> archived", ex.detail)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")

    def test_notify_action_creates_notification(self):
        ticket = _ticket(self.emp, self.dep)
        ticket.assignee = self.support
        ticket.save()
        RuleExecution.objects.all().delete()
        Notification.objects.all().delete()
        self._rule(trigger="status_changed", actions=[
            {"type": "notify"}])
        auth(self.c, self.support)
        self.c.patch(f"/api/tickets/{ticket.pk}/",
                     {"status": "in_progress"}, format="json")
        self.assertTrue(Notification.objects.filter(
            recipient=self.support, title__startswith="Automation"
        ).exists())

    def test_reassign_notification_to_specific_user(self):
        RuleExecution.objects.all().delete()
        Notification.objects.all().delete()
        self._rule(actions=[{"type": "notify", "user_id": self.mgr.pk}])
        # Ticket creation via the API (not ORM) so rules actually run.
        auth(self.c, self.emp)
        self.c.post("/api/tickets/", {
            "title": "Notify mgr", "description": "d",
            "category": _mk_category().pk,
        }, format="json")
        self.assertTrue(Notification.objects.filter(
            recipient=self.mgr, title__startswith="Automation"
        ).exists())


class ApprovalApiTests(WorkflowApiTestCase):
    URL = "/api/workflow/approval-requests/"

    def setUp(self):
        super().setUp()
        self.ticket = _ticket(self.emp, self.dep)

    def payload(self, ticket=None, operation="change_priority",
                context=None):
        return {
            "ticket": (ticket or self.ticket).pk,
            "operation": operation,
            "context": context or {"priority": "critical"},
            "reason": "Hardware emergency confirmed by vendor",
        }

    def test_employee_can_request_approval_own_ticket(self):
        auth(self.c, self.emp)
        res = self.c.post(self.URL, self.payload(), format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["status"], "pending")
        self.assertEqual(res.data["requested_by"], self.emp.pk)
        obj = ApprovalRequest.objects.get(pk=res.data["id"])
        self.assertEqual(obj.context, {"priority": "critical"})
        self.assertTrue(self.ticket.history.filter(
            action="approval_requested").exists())
        # IT managers are told there is a pending request.
        self.assertTrue(Notification.objects.filter(
            recipient=self.mgr, title__icontains="Approval requested"
        ).exists())
        # But the requester is not self-notified.
        self.assertFalse(Notification.objects.filter(
            recipient=self.emp, title__icontains="your request"
        ).exists())

    def test_employee_cannot_request_for_invisible_ticket(self):
        from accounts.models import Department, User as U
        dep2 = Department.objects.create(name="WfFar", code="FAR2")
        far = U.objects.create_user(
            username="wf@x", email="wf@x", employee_id="WF",
            password="pw12345678", role="employee", home_department=dep2)
        far_ticket = _ticket(far, dep2)
        auth(self.c, self.emp)
        res = self.c.post(
            self.URL, self.payload(far_ticket), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("access", str(res.data))

    def test_invalid_context_rejected(self):
        auth(self.c, self.emp)
        res = self.c.post(self.URL, self.payload(
            context={"priority": "ultra"}), format="json")
        self.assertEqual(res.status_code, 400)
        res = self.c.post(self.URL, self.payload(
            operation="change_status", context={"status": "nope"}),
            format="json")
        self.assertEqual(res.status_code, 400)
        res = self.c.post(self.URL, self.payload(
            operation="delete_everything", context={}), format="json")
        self.assertEqual(res.status_code, 400)

    def test_reassign_context_validates_user(self):
        auth(self.c, self.emp)
        res = self.c.post(self.URL, self.payload(
            operation="reassign", context={"user_id": 424242}),
            format="json")
        self.assertEqual(res.status_code, 400)

    def test_employee_cannot_decide(self):
        obj = ApprovalRequest.objects.create(
            ticket=self.ticket, requested_by=self.emp,
            operation="change_priority", context={"priority": "critical"})
        auth(self.c, self.emp)
        res = self.c.post(f"{self.URL}{obj.pk}/approve/", {}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_requester_cannot_decide_own_request(self):
        obj = ApprovalRequest.objects.create(
            ticket=self.ticket, requested_by=self.mgr,
            operation="change_priority", context={"priority": "critical"})
        auth(self.c, self.mgr)
        res = self.c.post(f"{self.URL}{obj.pk}/approve/", {}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertIn("own", str(res.data))

    def _pending(self, **kw):
        defaults = dict(
            ticket=self.ticket, requested_by=self.emp,
            operation="change_priority", context={"priority": "critical"})
        defaults.update(kw)
        return ApprovalRequest.objects.create(**defaults)

    def test_approve_applies_operation_and_records_decision(self):
        obj = self._pending()
        auth(self.c, self.mgr)
        res = self.c.post(f"{self.URL}{obj.pk}/approve/",
                          {"comment": "Emergency confirmed"}, format="json")
        self.assertEqual(res.status_code, 200)
        obj.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(obj.status, "approved")
        self.assertEqual(obj.decided_by_id, self.mgr.pk)
        self.assertIsNotNone(obj.decided_at)
        self.assertEqual(obj.decision_comment, "Emergency confirmed")
        self.assertEqual(self.ticket.priority, "critical")
        self.assertTrue(self.ticket.history.filter(
            action="approval_approved").exists())
        self.assertTrue(self.ticket.history.filter(
            note__icontains="approval #").exists())
        # The requester learns about the decision.
        self.assertTrue(Notification.objects.filter(
            recipient=self.emp, title__icontains="approved").exists())

    def test_approve_change_status_respects_transitions(self):
        self.ticket.status = "resolved"
        self.ticket.save(update_fields=["status"])
        obj = self._pending(operation="change_status",
                            context={"status": "archived"})  # invalid
        auth(self.c, self.mgr)
        res = self.c.post(f"{self.URL}{obj.pk}/approve/", {}, format="json")
        self.assertEqual(res.status_code, 400)
        obj.refresh_from_db()
        self.assertEqual(obj.status, "pending")
        self.assertIsNone(obj.decided_by_id)

    def test_approve_change_status_valid_transition(self):
        obj = self._pending(operation="change_status",
                            context={"status": "resolved"})
        auth(self.c, self.mgr)
        res = self.c.post(f"{self.URL}{obj.pk}/approve/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "resolved")

    def test_approve_reassign_operation(self):
        obj = self._pending(operation="reassign",
                            context={"user_id": self.support.pk})
        auth(self.c, self.mgr)  # decider cannot be the requester (self.emp)
        res = self.c.post(f"{self.URL}{obj.pk}/approve/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee_id, self.support.pk)

    def test_reject_does_not_change_ticket(self):
        obj = self._pending()
        auth(self.c, self.mgr)
        res = self.c.post(f"{self.URL}{obj.pk}/reject/",
                          {"comment": "Not necessary"}, format="json")
        self.assertEqual(res.status_code, 200)
        obj.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(obj.status, "rejected")
        self.assertEqual(obj.decision_comment, "Not necessary")
        self.assertEqual(self.ticket.priority, "medium")
        self.assertTrue(self.ticket.history.filter(
            action="approval_rejected").exists())

    def test_duplicate_decision_returns_409(self):
        obj = self._pending()
        auth(self.c, self.mgr)
        first = self.c.post(f"{self.URL}{obj.pk}/approve/", {},
                            format="json")
        self.assertEqual(first.status_code, 200)
        second = self.c.post(f"{self.URL}{obj.pk}/approve/", {},
                             format="json")
        self.assertEqual(second.status_code, 409)
        self.assertIn("already been decided", str(second.data))

    def test_stale_request_decided_by_another_user_returns_409(self):
        obj = self._pending()
        auth(self.c, self.mgr)
        self.c.post(f"{self.URL}{obj.pk}/approve/", {}, format="json")
        auth(self.c, self.support)
        res = self.c.post(f"{self.URL}{obj.pk}/approve/", {}, format="json")
        self.assertEqual(res.status_code, 409)
        # The second decision must not have overwritten the first.
        obj.refresh_from_db()
        self.assertEqual(obj.decided_by_id, self.mgr.pk)

    def test_employee_sees_only_visible_ticket_approvals(self):
        from accounts.models import Department
        dep2 = Department.objects.create(name="WfOther", code="OTH9")
        TicketCategory.objects.create(name="WfCat2")
        far = User.objects.create_user(
            username="f2@x", email="f2@x", employee_id="F2",
            password="pw12345678", role="employee", home_department=dep2)
        other = _ticket(far, dep2, "Far ticket")
        far_appr = ApprovalRequest.objects.create(
            ticket=other, requested_by=far,
            operation="change_priority", context={"priority": "high"})
        mine = self._pending()
        auth(self.c, self.emp)
        res = self.c.get(self.URL)
        ids = [r["id"] for r in res.data["results"]]
        self.assertIn(mine.pk, ids)
        self.assertNotIn(far_appr.pk, ids)

    def test_staff_sees_all_and_filters(self):
        self._pending()
        ApprovalRequest.objects.create(
            ticket=self.ticket, requested_by=self.emp,
            operation="change_status", context={"status": "resolved"},
            status="approved")
        auth(self.c, self.mgr)
        self.assertEqual(self.c.get(self.URL).data["count"], 2)
        self.assertEqual(
            self.c.get(self.URL, {"status": "pending"}).data["count"], 1)
        self.assertEqual(
            self.c.get(self.URL, {"status": "approved"}).data["count"], 1)
        self.assertEqual(
            self.c.get(self.URL, {"status": "rejected"}).data["count"], 0)
        self.assertEqual(
            self.c.get(self.URL, {"ticket": self.ticket.pk}).data["count"],
            2)
        self.assertEqual(
            self.c.get(self.URL, {"operation": "change_priority"}).data
            ["count"], 1)
        self.assertEqual(
            self.c.get(self.URL, {"q": "Broken laptop"}).data["count"], 2)

    def test_detail_includes_full_context(self):
        obj = self._pending(reason="Hardware emergency confirmed by vendor")
        auth(self.c, self.mgr)
        res = self.c.get(f"{self.URL}{obj.pk}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["ticket_title"], self.ticket.title)
        self.assertEqual(res.data["requested_by_email"], self.emp.email)
        self.assertEqual(res.data["operation_display"], "Change priority")
        self.assertEqual(res.data["context"], {"priority": "critical"})
        self.assertEqual(res.data["reason"],
                         "Hardware emergency confirmed by vendor")

    def test_approvals_cannot_be_edited_directly(self):
        obj = self._pending()
        auth(self.c, self.admin)
        res = self.c.patch(f"{self.URL}{obj.pk}/", {"status": "approved"},
                           format="json")
        self.assertEqual(res.status_code, 405)

    def test_pending_request_can_be_withdrawn(self):
        obj = self._pending()
        auth(self.c, self.mgr)
        res = self.c.delete(f"{self.URL}{obj.pk}/")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(
            ApprovalRequest.objects.filter(pk=obj.pk).exists())

    def test_decided_request_cannot_be_deleted(self):
        obj = self._pending(status="approved", decided_by=self.mgr,
                            decided_at=timezone.now())
        auth(self.c, self.mgr)
        res = self.c.delete(f"{self.URL}{obj.pk}/")
        self.assertEqual(res.status_code, 409)

    def test_snooping_employees_cannot_read_hidden_approval(self):
        from accounts.models import Department
        dep2 = Department.objects.create(name="WfPen", code="PEN")
        far = User.objects.create_user(
            username="f3@x", email="f3@x", employee_id="F3",
            password="pw12345678", role="employee", home_department=dep2)
        TicketCategory.objects.create(name="WfCat3")
        TicketCategory.objects.get_or_create(name="WfCat")
        far_appr = ApprovalRequest.objects.create(
            ticket=_ticket(far, dep2), requested_by=far,
            operation="change_priority", context={"priority": "high"})
        auth(self.c, self.emp)
        res = self.c.get(f"{self.URL}{far_appr.pk}/")
        self.assertEqual(res.status_code, 404)


class ExecutionHistoryTests(WorkflowApiTestCase):
    URL = "/api/workflow/rule-executions/"

    def setUp(self):
        super().setUp()
        self.rule = AutomationRule.objects.create(
            name="History rule", trigger="ticket_created",
            conditions={}, actions=[], is_enabled=True,
            created_by=self.admin)
        self.t1 = _ticket(self.emp, self.dep, "First")
        self.t2 = _ticket(self.emp, self.dep, "Second")
        RuleExecution.objects.create(
            rule=self.rule, ticket=self.t1, success=True,
            detail="note #1 created")
        RuleExecution.objects.create(
            rule=self.rule, ticket=self.t2, success=False,
            detail="ValueError: boom")

    def test_employee_cannot_view_executions(self):
        auth(self.c, self.emp)
        self.assertEqual(self.c.get(self.URL).status_code, 403)

    def test_staff_can_view_executions(self):
        auth(self.c, self.support)
        res = self.c.get(self.URL)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 2)

    def test_detail_includes_rule_and_ticket(self):
        ex = RuleExecution.objects.order_by("id").first()
        auth(self.c, self.support)
        res = self.c.get(f"{self.URL}{ex.pk}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["rule_name"], "History rule")
        self.assertEqual(res.data["ticket_title"], "First")
        self.assertTrue(res.data["success"])

    def test_filter_by_rule(self):
        other = AutomationRule.objects.create(
            name="Other rule", trigger="status_changed",
            conditions={}, actions=[], is_enabled=True,
            created_by=self.admin)
        RuleExecution.objects.create(
            rule=other, ticket=self.t1, success=True, detail="OK")
        auth(self.c, self.support)
        self.assertEqual(
            self.c.get(self.URL, {"rule": self.rule.pk}).data["count"], 2)
        self.assertEqual(
            self.c.get(self.URL, {"rule": other.pk}).data["count"], 1)

    def test_filter_by_status(self):
        auth(self.c, self.support)
        self.assertEqual(
            self.c.get(self.URL, {"status": "success"}).data["count"], 1)
        self.assertEqual(
            self.c.get(self.URL, {"status": "failure"}).data["count"], 1)
        self.assertEqual(
            self.c.get(self.URL, {"success": "false"}).data["count"], 1)

    def test_filter_by_ticket(self):
        auth(self.c, self.support)
        self.assertEqual(
            self.c.get(self.URL, {"ticket": self.t1.pk}).data["count"], 1)

    def test_filter_by_date_range(self):
        RuleExecution.objects.update(
            created_at=timezone.now() - timedelta(days=2))
        old = RuleExecution.objects.order_by("id").first()
        old.created_at = timezone.now() + timedelta(hours=1)
        old.save(update_fields=["created_at"])
        auth(self.c, self.support)
        today = timezone.localdate().isoformat()
        res = self.c.get(self.URL, {"date_from": today})
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["id"], old.pk)
        res = self.c.get(self.URL, {"date_to": today})
        self.assertEqual(res.data["count"], 1)

    def test_search_by_rule_name_ticket_title_and_detail(self):
        auth(self.c, self.support)
        self.assertEqual(
            self.c.get(self.URL, {"q": "History rule"}).data["count"], 2)
        self.assertEqual(
            self.c.get(self.URL, {"q": "First"}).data["count"], 1)
        self.assertEqual(
            self.c.get(self.URL, {"q": "boom"}).data["count"], 1)

    def test_pagination(self):
        # Fill the default page (PAGE_SIZE=20) plus one overflow row.
        for i in range(19):
            RuleExecution.objects.create(
                rule=self.rule, ticket=self.t1, success=True, detail=f"n{i}")
        auth(self.c, self.support)
        res = self.c.get(self.URL)
        self.assertEqual(res.data["count"], 21)
        self.assertEqual(len(res.data["results"]), 20)
        self.assertIsNotNone(res.data["next"])
        res2 = self.c.get(res.data["next"].replace("http://testserver", ""))
        self.assertEqual(len(res2.data["results"]), 1)
        self.assertIsNone(res2.data["next"])
