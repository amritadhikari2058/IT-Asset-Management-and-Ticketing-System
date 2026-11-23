import pytest
from rest_framework.test import APIClient

from accounts.models import Department
from accounts.tests import auth, make_users, _make_user
from tickets.models import (
    Ticket, TicketCategory, TicketQueue, TicketQueueMembership,
    TicketBulkImportOperation,
)


@pytest.fixture
def env(db):
    dep, admin, mgr, emp = make_users()
    dep2 = Department.objects.create(name="OtherDep2", code="OTHC")
    support = _make_user("S1C", "s1c@x", "s1c@x", "it_support", dep)
    emp_other = _make_user("E3C", "e3c@x", "e3c@x", "employee", dep2)
    cat = TicketCategory.objects.create(name="CompCat", is_active=True)
    t1 = Ticket.objects.create(title="T1", description="d", category=cat, requester=emp, department=dep)
    t2 = Ticket.objects.create(title="T2", description="d", category=cat, requester=emp_other, department=dep2)
    return {"dep": dep, "dep2": dep2, "admin": admin, "mgr": mgr, "emp": emp, "support": support, "emp_other": emp_other, "cat": cat, "t1": t1, "t2": t2}


@pytest.mark.django_db
class TestQueueServiceDirectCallContracts:
    def test_auto_assign_requires_manager(self, env):
        from tickets.queue_services import auto_assign_queue
        q = TicketQueue.objects.create(name="QA", code="QA1", created_by=env["mgr"], manager=env["mgr"])
        env["t1"].queue = q
        env["t1"].assignee = None
        env["t1"].save(update_fields=["queue", "assignee"])
        with pytest.raises(Exception):
            auto_assign_queue(q, env["support"])
        env["t1"].refresh_from_db()
        assert env["t1"].assignee_id is None

    def test_auto_assign_rejects_inactive_manager(self, env):
        from tickets.queue_services import auto_assign_queue
        q = TicketQueue.objects.create(name="QB", code="QB1", created_by=env["mgr"], manager=env["mgr"])
        env["mgr"].is_active = False
        env["mgr"].save(update_fields=["is_active"])
        with pytest.raises(Exception):
            auto_assign_queue(q, env["mgr"])

    def test_claim_rejects_inactive_staff(self, env):
        from tickets.queue_services import claim_ticket
        q = TicketQueue.objects.create(name="QC", code="QC1", created_by=env["mgr"], manager=env["mgr"])
        TicketQueueMembership.objects.create(queue=q, user=env["support"], role="agent", created_by=env["mgr"])
        env["t1"].queue = q
        env["t1"].assignee = None
        env["t1"].save(update_fields=["queue", "assignee"])
        env["support"].is_active = False
        env["support"].save(update_fields=["is_active"])
        with pytest.raises(Exception):
            claim_ticket(env["t1"], env["support"])
        env["t1"].refresh_from_db()
        assert env["t1"].assignee_id is None

    def test_reassign_rejects_invalid_target(self, env):
        from tickets.queue_services import reassign_ticket
        q = TicketQueue.objects.create(name="QD", code="QD1", created_by=env["mgr"], manager=env["mgr"])
        env["t1"].queue = q
        env["t1"].assignee = env["support"]
        env["t1"].save(update_fields=["queue", "assignee"])
        with pytest.raises(Exception):
            reassign_ticket(env["t1"], env["emp"], env["mgr"], "reason")
        env["t1"].refresh_from_db()
        assert env["t1"].assignee_id == env["support"].pk

    def test_move_queue_rejects_inactive_queue(self, env):
        from tickets.queue_services import move_queue
        q1 = TicketQueue.objects.create(name="QE1", code="QE1", created_by=env["mgr"], manager=env["mgr"])
        q2 = TicketQueue.objects.create(name="QE2", code="QE2", created_by=env["mgr"], manager=env["mgr"], is_active=False)
        env["t1"].queue = q1
        env["t1"].save(update_fields=["queue"])
        with pytest.raises(Exception):
            move_queue(env["t1"], q2, env["mgr"], "reason")
        env["t1"].refresh_from_db()
        assert env["t1"].queue_id == q1.pk


@pytest.mark.django_db
class TestMergeServiceDirectCallContracts:
    def test_merge_rejects_non_manager(self, env):
        from tickets.merge_services import merge_tickets, MergeError
        before1, before2 = env["t1"].status, env["t2"].status
        with pytest.raises(Exception):
            merge_tickets(env["t1"], env["t2"], env["support"], "dup", {})
        env["t1"].refresh_from_db(); env["t2"].refresh_from_db()
        assert env["t1"].status == before1
        assert env["t2"].status == before2

    def test_merge_rejects_same_ticket(self, env):
        from tickets.merge_services import merge_tickets
        with pytest.raises(Exception):
            merge_tickets(env["t1"], env["t1"], env["mgr"], "dup", {})
        env["t1"].refresh_from_db()
        assert env["t1"].status != "merged"


@pytest.mark.django_db
class TestBulkImportDiagnosticCanary:
    def test_error_detail_canary_redacted_in_api(self, env):
        c = APIClient()
        op = TicketBulkImportOperation.objects.create(
            user=env["mgr"], token="tok-canary", status=TicketBulkImportOperation.STATUS_FAILED,
            total_rows=1,
            error_detail="Bearer eyJFAKECANARYTOKEN /var/secret/app.py C:\\secret\\app.py password=hunter2")
        auth(c, env["mgr"])
        res = c.get(f"/api/tickets/bulk-imports/{op.pk}/")
        assert res.status_code == 200
        body = str(res.data)
        assert "eyJFAKECANARYTOKEN" not in body
        assert "/var/secret/app.py" not in body
        assert "C:\\secret\\app.py" not in body
        assert "hunter2" not in body

    def test_error_detail_canary_not_in_logs(self, env, caplog):
        import logging
        c = APIClient()
        op = TicketBulkImportOperation.objects.create(
            user=env["mgr"], token="tok-log", status=TicketBulkImportOperation.STATUS_FAILED,
            total_rows=1,
            error_detail="Authorization: Bearer LOGCANARYSECRET1234567890")
        with caplog.at_level(logging.INFO):
            auth(c, env["mgr"])
            res = c.get(f"/api/tickets/bulk-imports/{op.pk}/")
        assert res.status_code == 200
        assert "LOGCANARYSECRET1234567890" not in caplog.text

    def test_legacy_error_detail_sanitized_at_read(self, env):
        c = APIClient()
        op = TicketBulkImportOperation.objects.create(
            user=env["mgr"], token="tok-legacy", status=TicketBulkImportOperation.STATUS_FAILED,
            total_rows=1,
            error_detail="Traceback (most recent call last):\n  File \"C:\\secret\\app.py\", line 1\npassword=hunter2")
        auth(c, env["mgr"])
        res = c.get(f"/api/tickets/bulk-imports/{op.pk}/")
        assert res.status_code == 200
        body = str(res.data)
        assert "hunter2" not in body
        assert "C:\\secret\\app.py" not in body
        assert "Traceback" not in body

    def test_sanitize_reason_canary(self, env):
        from tickets.bulk_import_reconciliation import sanitize_import_diagnostic
        assert "SECRETREASON" not in sanitize_import_diagnostic("Bearer SECRETREASON password=hunter2")


@pytest.mark.django_db
class TestCollaborationServiceDirectCallContracts:
    def test_add_watcher_rejects_invisible_ticket(self, env):
        from tickets.collaboration_services import add_watcher, PermissionDenied as CDenied
        with pytest.raises(CDenied):
            add_watcher(env["t2"], {"user": env["emp"], "watch_type": "watcher"}, env["emp"])
        from tickets.models import TicketWatcher
        assert not TicketWatcher.objects.filter(ticket=env["t2"], user=env["emp"]).exists()

    def test_add_watcher_employee_cannot_add_other(self, env):
        from tickets.collaboration_services import add_watcher, PermissionDenied as CDenied
        with pytest.raises(CDenied):
            add_watcher(env["t1"], {"user": env["emp_other"], "watch_type": "watcher"}, env["emp"])

    def test_remove_watcher_employee_cannot_remove_other(self, env):
        from tickets.collaboration_services import add_watcher, remove_watcher, PermissionDenied as CDenied
        add_watcher(env["t1"], {"user": env["support"], "watch_type": "watcher"}, env["mgr"])
        with pytest.raises(CDenied):
            remove_watcher(env["t1"], env["support"], env["emp"])
        from tickets.models import TicketWatcher
        assert TicketWatcher.objects.filter(ticket=env["t1"], user=env["support"], is_active=True).exists()

    def test_mute_unmute_rejects_cross_user_employee(self, env):
        from tickets.collaboration_services import add_watcher, mute_watcher, unmute_watcher, PermissionDenied as CDenied
        from django.utils import timezone
        import datetime
        add_watcher(env["t1"], {"user": env["support"], "watch_type": "watcher"}, env["mgr"])
        with pytest.raises(CDenied):
            mute_watcher(env["t1"], env["support"], timezone.now() + datetime.timedelta(hours=1), env["emp"])
        with pytest.raises(CDenied):
            unmute_watcher(env["t1"], env["support"], env["emp"])


@pytest.mark.django_db
class TestSatisfactionServiceDirectCallContracts:
    def _make_survey(self, env):
        from tickets.models import TicketSatisfactionSurvey
        return TicketSatisfactionSurvey.objects.create(
            ticket=env["t1"], requester=env["emp"], status="pending")

    def test_submit_rejects_non_requester(self, env):
        from tickets.satisfaction_services import submit_survey, PermissionDenied as SDenied
        self._make_survey(env)
        with pytest.raises(SDenied):
            submit_survey(env["t1"], {"rating": 5}, env["emp_other"])
        from tickets.models import TicketSatisfactionSurvey
        s = TicketSatisfactionSurvey.objects.get(ticket=env["t1"], requester=env["emp"])
        assert s.status == "pending"

    def test_submit_rejects_invalid_rating(self, env):
        from tickets.satisfaction_services import submit_survey, ValidationError as SVal
        self._make_survey(env)
        with pytest.raises(SVal):
            submit_survey(env["t1"], {"rating": 0}, env["emp"])

    def test_report_rejects_non_manager(self, env):
        from tickets.satisfaction_services import satisfaction_report, PermissionDenied as SDenied
        with pytest.raises(SDenied):
            satisfaction_report({}, env["support"])
        with pytest.raises(SDenied):
            satisfaction_report({}, env["emp"])


@pytest.mark.django_db
class TestTemplateServiceDirectCallContracts:
    def test_create_shared_template_rejects_support(self, env):
        from tickets.template_services import create_template, PermissionDenied as TDenied
        with pytest.raises(TDenied):
            create_template({"name": "T", "title_template": "t", "description_template": "d", "is_shared": True}, env["support"])

    def test_update_template_rejects_non_owner_non_manager(self, env):
        from tickets.template_services import create_template, update_template, PermissionDenied as TDenied
        tpl = create_template({"name": "T2", "title_template": "t", "description_template": "d", "is_shared": False}, env["support"])
        with pytest.raises(TDenied):
            update_template(tpl, {"name": "X"}, env["emp"])
        tpl.refresh_from_db()
        assert tpl.name == "T2"

    def test_delete_template_rejects_non_owner(self, env):
        from tickets.template_services import create_template, delete_template, PermissionDenied as TDenied
        tpl = create_template({"name": "T3", "title_template": "t", "description_template": "d", "is_shared": False}, env["support"])
        with pytest.raises(TDenied):
            delete_template(tpl, env["emp_other"])
        tpl.refresh_from_db()
        assert not tpl.is_deleted

    def test_canned_response_owner_enforced(self, env):
        from tickets.template_services import create_canned_response, update_canned_response, delete_canned_response, PermissionDenied as TDenied
        cr = create_canned_response({"title": "R1", "body": "b", "is_shared": False}, env["support"])
        with pytest.raises(TDenied):
            update_canned_response(cr, {"title": "X"}, env["emp"])
        with pytest.raises(TDenied):
            delete_canned_response(cr, env["emp"])
        cr.refresh_from_db()
        assert cr.title == "R1"
        assert not cr.is_deleted
