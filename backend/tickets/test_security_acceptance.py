import io
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from accounts.models import Department
from accounts.tests import auth, make_users, _make_user
from tickets.models import (
    Ticket, TicketCategory, TicketAttachment, TicketHistory,
    TicketBulkImportOperation, TicketQueue, TicketQueueMembership,
    SavedTicketView, TicketMergeRecord, TicketSatisfactionSurvey,
)


@pytest.fixture
def api(db):
    return APIClient()


@pytest.fixture
def env(db):
    dep, admin, mgr, emp = make_users()
    dep2 = Department.objects.create(name="OtherDep", code="OTHACC")
    emp_owner = emp
    emp_same = _make_user("E2A", "e2a@x", "e2a@x", "employee", dep)
    emp_other = _make_user("E3A", "e3a@x", "e3a@x", "employee", dep2)
    support = _make_user("S1A", "s1a@x", "s1a@x", "it_support", dep)
    cat = TicketCategory.objects.create(name="AccCat", is_active=True)
    t_owner = Ticket.objects.create(title="Owner", description="d", category=cat, requester=emp_owner, department=dep)
    t_other = Ticket.objects.create(title="Other", description="d", category=cat, requester=emp_other, department=dep2)
    return {
        "dep": dep, "dep2": dep2, "admin": admin, "mgr": mgr,
        "owner": emp_owner, "same": emp_same, "other": emp_other, "support": support,
        "cat": cat, "t_owner": t_owner, "t_other": t_other,
    }


def result_ids(data):
    rows = data.get("results", data) if isinstance(data, dict) else data
    return {r["id"] for r in rows}


@pytest.mark.parametrize("who,expected", [
    (None, {401, 403}),
    ("other", {403, 404}),
    ("same", {200}),  # same-department ticket is visible by current policy
    ("owner", {200}),
    ("support", {200}),
    ("mgr", {200}),
    ("admin", {200}),
])
@pytest.mark.django_db
def test_attachment_download_matrix(api, env, who, expected):
    att = TicketAttachment.objects.create(
        ticket=env["t_owner"], original_filename="secret.txt",
        file=SimpleUploadedFile("secret.txt", b"topsecret"))
    if who:
        auth(api, env[who])
    res = api.get(f"/api/tickets/attachments/{att.pk}/download/")
    assert res.status_code in expected
    if res.status_code != 200:
        assert b"topsecret" not in getattr(res, "content", b"")


@pytest.mark.parametrize("who,can_see", [
    ("owner", False),
    ("same", False),
    ("other", False),
    ("support", False),
    ("mgr", True),
    ("admin", True),
])
@pytest.mark.django_db
def test_history_list_visibility(api, env, who, can_see):
    h = TicketHistory.objects.create(ticket=env["t_owner"], action="created", old_values={}, new_values={})
    auth(api, env[who])
    res = api.get(f"/api/tickets/histories/?ticket={env['t_owner'].pk}")
    assert res.status_code == 200
    ids = result_ids(res.data)
    assert (h.pk in ids) is can_see


@pytest.mark.django_db
def test_bulk_import_cross_user_actions_no_side_effect(api, env):
    op = TicketBulkImportOperation.objects.create(
        user=env["mgr"], token="tok-acc", status=TicketBulkImportOperation.STATUS_PREVIEWED, total_rows=1)
    auth(api, env["support"])
    before = op.status
    res1 = api.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/")
    res2 = api.post(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/finalize/",
                    {"reason": "x", "evidence_digest": "bad"}, format="json")
    res3 = api.get(f"/api/tickets/bulk-imports/{op.pk}/reconciliation/audit/")
    assert res1.status_code == 404
    assert res2.status_code == 404
    assert res3.status_code == 404
    op.refresh_from_db()
    assert op.status == before


@pytest.mark.django_db
def test_saved_view_set_default_requires_owner(api, env):
    view = SavedTicketView.objects.create(owner=env["owner"], name="v1", filters={}, ordering="-created_at", columns=[])
    auth(api, env["same"])
    res = api.post(f"/api/tickets/saved-views/{view.pk}/set_default/")
    assert res.status_code in (403, 404)
    view.refresh_from_db()
    assert view.is_default is False


@pytest.mark.django_db
def test_saved_view_duplicate_shared_view_creates_private_copy(api, env):
    view = SavedTicketView.objects.create(owner=env["mgr"], name="shared", filters={}, ordering="-created_at", columns=[], is_shared=True)
    auth(api, env["owner"])
    res = api.post(f"/api/tickets/saved-views/{view.pk}/duplicate/")
    assert res.status_code == 201
    new_id = res.data["id"]
    new_view = SavedTicketView.objects.get(pk=new_id)
    assert new_view.owner_id == env["owner"].pk
    assert new_view.is_shared is False


@pytest.mark.django_db
def test_merge_record_retrieve_manager_only(api, env):
    rec = TicketMergeRecord.objects.create(primary_ticket=env["t_owner"], merged_ticket=env["t_other"], reason="dup")
    for who, expected in [(None, {401, 403}), ("owner", {403, 404}), ("same", {403, 404}), ("support", {403, 404}), ("mgr", {200}), ("admin", {200})]:
        client = APIClient()
        if who:
            auth(client, env[who])
        res = client.get(f"/api/tickets/merge-records/{rec.pk}/")
        assert res.status_code in expected


@pytest.mark.django_db
def test_queue_membership_list_create_manager_only(api, env):
    q = TicketQueue.objects.create(name="AccQ", code="ACCQ", created_by=env["mgr"], manager=env["mgr"])
    auth(api, env["support"])
    res_list = api.get("/api/tickets/queue-memberships/")
    assert res_list.status_code == 403
    res_create = api.post("/api/tickets/queue-memberships/", {"queue": q.pk, "user": env["support"].pk, "role": "agent"}, format="json")
    assert res_create.status_code == 403
    assert not TicketQueueMembership.objects.filter(queue=q, user=env["support"], is_deleted=False).exists()


@pytest.mark.django_db
def test_operations_dashboard_and_agent_workload_staff_only(api, env):
    auth(api, env["owner"])
    assert api.get("/api/tickets/operations-dashboard/").status_code == 403
    assert api.get("/api/tickets/agent-workload/").status_code == 403
    auth(api, env["support"])
    assert api.get("/api/tickets/operations-dashboard/").status_code == 200
    assert api.get("/api/tickets/agent-workload/").status_code == 200
