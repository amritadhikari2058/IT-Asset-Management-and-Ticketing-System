import io
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from accounts.models import Department
from accounts.tests import auth, make_users, _make_user
from tickets.models import (
    Ticket, TicketCategory, TicketAttachment, TicketBulkImportOperation,
    TicketQueue, TicketQueueMembership, CannedResponse, TicketTemplate,
    SavedTicketView, TicketMergeRecord, TicketSatisfactionSurvey, TicketHistory,
)


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def base(db):
    dep, admin, mgr, emp = make_users()
    dep2 = Department.objects.create(name="Other", code="OTHM")
    emp2 = _make_user("E2", "e2m@x", "e2m@x", "employee", dep)
    emp_other = _make_user("E3", "e3m@x", "e3m@x", "employee", dep2)
    support = _make_user("S1", "s1m@x", "s1m@x", "it_support", dep)
    cat = TicketCategory.objects.create(name="MatrixCat", is_active=True)
    t_owner = Ticket.objects.create(title="OwnerT", description="D", category=cat, requester=emp, department=dep)
    t_other = Ticket.objects.create(title="OtherT", description="D", category=cat, requester=emp_other, department=dep2)
    return {
        "dep": dep, "dep2": dep2, "admin": admin, "mgr": mgr, "emp": emp,
        "emp2": emp2, "emp_other": emp_other, "support": support, "cat": cat,
        "t_owner": t_owner, "t_other": t_other,
    }


def ids(results):
    if isinstance(results, dict):
        results = results.get("results", results)
    return {r["id"] for r in results}


@pytest.mark.django_db
class TestAttachmentAuthorizationMatrix:
    def test_unauthenticated_cannot_download_attachment(self, api, base):
        att = TicketAttachment.objects.create(
            ticket=base["t_owner"], original_filename="a.txt",
            file=SimpleUploadedFile("a.txt", b"secret"))
        res = api.get(f"/api/tickets/attachments/{att.pk}/download/")
        assert res.status_code in (401, 403)

    def test_other_dept_employee_cannot_download_attachment(self, api, base):
        att = TicketAttachment.objects.create(
            ticket=base["t_owner"], original_filename="a.txt",
            file=SimpleUploadedFile("a.txt", b"secret"))
        auth(api, base["emp_other"])
        res = api.get(f"/api/tickets/attachments/{att.pk}/download/")
        assert res.status_code in (403, 404)

    def test_owner_can_download_own_ticket_attachment(self, api, base):
        att = TicketAttachment.objects.create(
            ticket=base["t_owner"], original_filename="a.txt",
            file=SimpleUploadedFile("a.txt", b"secret"))
        auth(api, base["emp"])
        res = api.get(f"/api/tickets/attachments/{att.pk}/download/")
        assert res.status_code == 200

    def test_employee_cannot_delete_attachment(self, api, base):
        att = TicketAttachment.objects.create(
            ticket=base["t_owner"], original_filename="a.txt",
            file=SimpleUploadedFile("a.txt", b"secret"))
        auth(api, base["emp"])
        res = api.delete(f"/api/tickets/attachments/{att.pk}/")
        assert res.status_code in (403, 404)
        assert TicketAttachment.objects.filter(pk=att.pk).exists()


@pytest.mark.django_db
class TestHistoryAuthorizationMatrix:
    def test_employee_cannot_list_history(self, api, base):
        TicketHistory.objects.create(ticket=base["t_owner"], action="created", old_values={}, new_values={})
        auth(api, base["emp"])
        res = api.get(f"/api/tickets/histories/?ticket={base['t_owner'].pk}")
        assert res.status_code == 200
        assert ids(res.data) == set()

    def test_it_support_without_perm_cannot_list_history(self, api, base):
        TicketHistory.objects.create(ticket=base["t_owner"], action="created", old_values={}, new_values={})
        auth(api, base["support"])
        res = api.get(f"/api/tickets/histories/?ticket={base['t_owner'].pk}")
        assert res.status_code == 200
        assert ids(res.data) == set()

    def test_it_manager_can_list_history(self, api, base):
        h = TicketHistory.objects.create(ticket=base["t_owner"], action="created", old_values={}, new_values={})
        auth(api, base["mgr"])
        res = api.get(f"/api/tickets/histories/?ticket={base['t_owner'].pk}")
        assert res.status_code == 200
        assert h.pk in ids(res.data)


@pytest.mark.django_db
class TestBulkImportActionAuthorizationMatrix:
    def test_support_cannot_access_other_users_audit(self, api, base):
        op = TicketBulkImportOperation.objects.create(user=base["mgr"], token="tok-mgr", status=TicketBulkImportOperation.STATUS_PREVIEWED, total_rows=1)
        auth(api, base["support"])
        res = api.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/audit/")
        assert res.status_code == 404

    def test_support_cannot_finalize_other_users_operation(self, api, base):
        op = TicketBulkImportOperation.objects.create(user=base["mgr"], token="tok-mgr2", status=TicketBulkImportOperation.STATUS_PREVIEWED, total_rows=1)
        auth(api, base["support"])
        res = api.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/", {"reason": "x", "evidence_digest": "bad"}, format="json")
        assert res.status_code == 404
        op.refresh_from_db()
        assert op.status == TicketBulkImportOperation.STATUS_PREVIEWED


@pytest.mark.django_db
class TestSavedViewResultVisibility:
    def test_saved_view_results_do_not_expose_invisible_tickets(self, api, base):
        view = SavedTicketView.objects.create(owner=base["emp_other"], name="v", filters={}, ordering="-created_at", columns=[], is_shared=True)
        auth(api, base["emp"])
        res = api.get(f"/api/tickets/saved-views/{view.pk}/results/")
        assert res.status_code == 200
        returned = ids(res.data.get("results", []))
        assert base["t_other"].pk not in returned


@pytest.mark.django_db
class TestMergeRecordMatrix:
    def test_support_cannot_retrieve_merge_record(self, api, base):
        rec = TicketMergeRecord.objects.create(primary_ticket=base["t_owner"], merged_ticket=base["t_other"], reason="dup")
        auth(api, base["support"])
        res = api.get(f"/api/tickets/merge-records/{rec.pk}/")
        assert res.status_code in (403, 404)

    def test_employee_cannot_list_merge_records(self, api, base):
        auth(api, base["emp"])
        res = api.get("/api/tickets/merge-records/")
        assert res.status_code == 403


@pytest.mark.django_db
class TestQueueMembershipDirectService:
    def test_unclaim_rejects_non_staff_actor(self, api, base):
        from tickets.queue_services import unclaim_ticket
        q = TicketQueue.objects.create(name="Qm", code="QM", created_by=base["mgr"], manager=base["mgr"])
        base["t_other"].queue = q
        base["t_other"].assignee = base["support"]
        base["t_other"].save(update_fields=["queue", "assignee"])
        with pytest.raises(Exception):
            unclaim_ticket(base["t_other"], base["emp"], "reason")
        base["t_other"].refresh_from_db()
        assert base["t_other"].assignee_id == base["support"].pk

    def test_move_queue_rejects_non_staff_actor(self, api, base):
        from tickets.queue_services import move_queue
        q1 = TicketQueue.objects.create(name="Qm1", code="QM1", created_by=base["mgr"], manager=base["mgr"])
        q2 = TicketQueue.objects.create(name="Qm2", code="QM2", created_by=base["mgr"], manager=base["mgr"])
        base["t_other"].queue = q1
        base["t_other"].save(update_fields=["queue"])
        with pytest.raises(Exception):
            move_queue(base["t_other"], q2, base["emp"], "reason")
        base["t_other"].refresh_from_db()
        assert base["t_other"].queue_id == q1.pk


@pytest.mark.django_db
class TestSavedViewColumnsAllowlist:
    def test_rejects_unknown_column(self, api, base):
        auth(api, base["emp"])
        res = api.post("/api/tickets/saved-views/", {
            "name": "badcols", "filters": {}, "ordering": "-created_at",
            "columns": ["title", "__class__"], "is_shared": False, "is_default": False,
        }, format="json")
        assert res.status_code == 400

    def test_accepts_safe_columns(self, api, base):
        auth(api, base["emp"])
        res = api.post("/api/tickets/saved-views/", {
            "name": "okcols", "filters": {}, "ordering": "-created_at",
            "columns": ["title", "status", "priority"], "is_shared": False, "is_default": False,
        }, format="json")
        assert res.status_code == 201


@pytest.mark.django_db
class TestQueueServiceDirectCallBoundaries:
    def test_claim_rejects_non_staff(self, api, base):
        from tickets.queue_services import claim_ticket
        q = TicketQueue.objects.create(name="Qc", code="QC", created_by=base["mgr"], manager=base["mgr"])
        base["t_owner"].queue = q
        base["t_owner"].assignee = None
        base["t_owner"].save(update_fields=["queue", "assignee"])
        with pytest.raises(Exception):
            claim_ticket(base["t_owner"], base["emp"])
        base["t_owner"].refresh_from_db()
        assert base["t_owner"].assignee_id is None

    def test_reassign_rejects_non_staff(self, api, base):
        from tickets.queue_services import reassign_ticket
        q = TicketQueue.objects.create(name="Qr", code="QR", created_by=base["mgr"], manager=base["mgr"])
        base["t_owner"].queue = q
        base["t_owner"].assignee = base["support"]
        base["t_owner"].save(update_fields=["queue", "assignee"])
        with pytest.raises(Exception):
            reassign_ticket(base["t_owner"], base["mgr"], base["emp"], "reason")
        base["t_owner"].refresh_from_db()
        assert base["t_owner"].assignee_id == base["support"].pk
