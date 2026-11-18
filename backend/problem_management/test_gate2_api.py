"""Gate 2 API contract tests: RCA, whys, factors, evidence, workflows, access."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from problem_management import services
from problem_management.models import ProblemHistory, RootCauseAnalysis

BASE = "/api/problems"


def _user(role, n, active=True):
    return User.objects.create_user(
        username=f"{role}_api{n}", role=role,
        email=f"{role}.api{n}@example.test",
        employee_id=f"A{role}{n}"[:30], is_active=active,
    )


class Gate2ApiTestCase(TransactionTestCase):
    def setUp(self):
        self.support = _user("it_support", 1)
        self.manager = _user("it_manager", 1)
        self.problem = services.create_problem(
            actor=self.support, title="API problem", description="Desc",
            owner=self.manager)
        services.submit_problem(actor=self.support, problem=self.problem)
        services.accept_problem(actor=self.manager, problem=self.problem)
        self.client = APIClient()
        self.client.force_authenticate(self.support)

    def post(self, path, payload=None, fmt="json", **extra):
        return self.client.post(f"{BASE}{path}", payload or {}, format=fmt, **extra)

    def get(self, path):
        return self.client.get(f"{BASE}{path}")

    def rca(self, **fields):
        payload = {"problem": self.problem.pk, "title": "RCA", "description": "d"}
        payload.update(fields)
        return self.post("/root-cause-analyses/", payload)

    # --- RCA ---

    def test_rca_create_and_nested_retrieve(self):
        resp = self.rca(analysis_method="five_whys", findings="disk full")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["status"], "draft")
        self.assertEqual(resp.data["version"], 1)
        self.assertNotIn("expected_record_version", resp.data)
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="rca_created").exists())
        detail = self.get(f"/problems/{self.problem.pk}/root-cause-analysis/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["id"], resp.data["id"])

    def test_rca_submit_transition(self):
        rca_id = self.rca().data["id"]
        resp = self.post(f"/root-cause-analyses/{rca_id}/submit/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "in_review")

    def test_rca_approve_by_governance(self):
        rca_id = self.rca().data["id"]
        self.post(f"/root-cause-analyses/{rca_id}/submit/")
        self.client.force_authenticate(self.manager)
        resp = self.post(f"/root-cause-analyses/{rca_id}/approve/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "approved")
        self.assertEqual(resp.data["approved_by"], self.manager.pk)

    def test_rca_reject_requires_reason(self):
        rca_id = self.rca().data["id"]
        self.client.force_authenticate(self.manager)
        self.assertEqual(
            self.post(f"/root-cause-analyses/{rca_id}/reject/").status_code, 400)
        resp = self.post(f"/root-cause-analyses/{rca_id}/reject/", {"reason": "Weak"})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "rejected")

    def test_rca_supersede(self):
        rca_id = self.rca().data["id"]
        self.client.force_authenticate(self.manager)
        resp = self.post(f"/root-cause-analyses/{rca_id}/supersede/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "superseded")

    def test_rca_creator_cannot_approve_own(self):
        self.client.force_authenticate(self.manager)
        rca_id = self.rca().data["id"]
        resp = self.post(f"/root-cause-analyses/{rca_id}/approve/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("creator", str(resp.data).lower())

    def test_rca_stale_version_conflict(self):
        rca_id = self.rca().data["id"]
        self.client.force_authenticate(self.manager)
        resp = self.post(f"/root-cause-analyses/{rca_id}/approve/",
                         {"expected_record_version": 999})
        self.assertEqual(resp.status_code, 409)

    def test_rca_approved_is_immutable(self):
        rca_id = self.rca().data["id"]
        self.client.force_authenticate(self.manager)
        self.post(f"/root-cause-analyses/{rca_id}/approve/")
        resp = self.client.patch(f"{BASE}/root-cause-analyses/{rca_id}/",
                                 {"title": "reopened"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_rca_nested_detail_missing_404(self):
        self.assertEqual(
            self.get(f"/problems/{self.problem.pk}/root-cause-analysis/").status_code,
            404)

    # --- Five Whys and factors ---

    def accepted_problem(self, title):
        problem = services.create_problem(
            actor=self.support, title=title, description="x", owner=self.manager)
        services.submit_problem(actor=self.support, problem=problem)
        services.accept_problem(actor=self.manager, problem=problem)
        return problem

    def why(self, analysis_id, number=1, **fields):
        payload = {"analysis": analysis_id, "question_number": number,
                   "question_text": "Why?", "answer": "Because."}
        payload.update(fields)
        return self.post(f"/problems/{self.problem.pk}/five-whys/", payload)

    def test_why_create_patch_delete(self):
        rca_id = self.rca().data["id"]
        created = self.why(rca_id)
        self.assertEqual(created.status_code, 201, created.data)
        listed = self.get(f"/problems/{self.problem.pk}/five-whys/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data), 1)
        patched = self.client.patch(f"{BASE}/root-cause-whys/{created.data['id']}/",
                                    {"answer": "Disk filled."}, format="json")
        self.assertEqual(patched.status_code, 200, patched.data)
        self.assertEqual(patched.data["answer"], "Disk filled.")
        deleted = self.client.delete(f"{BASE}/root-cause-whys/{created.data['id']}/")
        self.assertEqual(deleted.status_code, 204)

    def test_why_duplicate_sequence_rejected(self):
        rca_id = self.rca().data["id"]
        self.assertEqual(self.why(rca_id).status_code, 201)
        self.assertEqual(self.why(rca_id).status_code, 400)

    def test_why_cross_problem_analysis_rejected(self):
        other = self.accepted_problem("Other problem")
        other_rca = services.create_root_cause_analysis(
            actor=self.support, problem=other, title="Other RCA")
        self.assertEqual(self.why(other_rca.pk).status_code, 400)

    def test_factor_category_allowlist(self):
        rca_id = self.rca().data["id"]
        path = f"/problems/{self.problem.pk}/root-cause-factors/"
        good = self.post(path, {"analysis": rca_id, "category": "method",
                                "factor": "No capacity alerts"})
        self.assertEqual(good.status_code, 201, good.data)
        bad = self.post(path, {"analysis": rca_id, "category": "gremlins",
                               "factor": "x"})
        self.assertEqual(bad.status_code, 400)

    def test_factor_cross_problem_rejected(self):
        other = self.accepted_problem("Factor other")
        other_rca = services.create_root_cause_analysis(
            actor=self.support, problem=other, title="Other RCA")
        resp = self.post(f"/problems/{self.problem.pk}/root-cause-factors/",
                         {"analysis": other_rca.pk, "category": "people", "factor": "x"})
        self.assertEqual(resp.status_code, 400)

    # --- Evidence ---

    def upload(self, name="note.txt", content=b"payload",
               content_type="text/plain", **fields):
        upload = SimpleUploadedFile(name, content, content_type=content_type)
        data = {"problem": self.problem.pk, "title": "Log",
                "evidence_type": "other", "file": upload}
        data.update(fields)
        return self.post(f"/problems/{self.problem.pk}/evidence/", data,
                         fmt="multipart")

    def test_evidence_upload_metadata_only(self):
        resp = self.upload()
        self.assertEqual(resp.status_code, 201, resp.data)
        filename = resp.data["original_filename"]
        self.assertTrue(filename.endswith(".txt"), filename)
        self.assertNotIn("/", filename)
        self.assertNotIn("\\", filename)
        self.assertEqual(resp.data["file_size"], 7)
        self.assertTrue(resp.data["checksum"])
        self.assertNotIn("file", resp.data)
        self.assertFalse(resp.data["archived"])
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="evidence_added").exists())

    def test_evidence_executable_rejected_without_history(self):
        before = ProblemHistory.objects.count()
        resp = self.upload(name="bad.exe",
                           content_type="application/x-msdownload")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ProblemHistory.objects.count(), before)

    def test_evidence_oversized_rejected(self):
        resp = self.upload(content=b"x" * (1024 * 1024 + 1))
        self.assertEqual(resp.status_code, 400)

    def test_evidence_archive_and_no_unarchive_route(self):
        evidence_id = self.upload().data["id"]
        archived = self.post(f"/evidence/{evidence_id}/archive/", {"reason": "dup"})
        self.assertEqual(archived.status_code, 200, archived.data)
        self.assertTrue(archived.data["archived"])
        self.assertEqual(
            self.post(f"/evidence/{evidence_id}/archive/").status_code, 400)
        self.assertEqual(
            self.post(f"/evidence/{evidence_id}/unarchive/").status_code, 404)

    # --- Timeline and actions ---

    def test_timeline_create_and_list(self):
        payload = {"occurred_at": timezone.now().isoformat(), "source": "manual",
                   "event_type": "milestone", "title": "Kickoff",
                   "description": "start"}
        created = self.post(f"/problems/{self.problem.pk}/timeline/", payload)
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["recorded_by"], self.support.pk)
        listed = self.get(f"/problems/{self.problem.pk}/timeline/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data), 1)

    def action(self, **fields):
        payload = {"title": "Replace disk", "description": "swap"}
        payload.update(fields)
        return self.post(f"/problems/{self.problem.pk}/actions/", payload)

    def test_action_lifecycle(self):
        created = self.action()
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["status"], "planned")
        action_id = created.data["id"]
        self.client.force_authenticate(self.manager)
        approved = self.post(f"/actions/{action_id}/approve/")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.client.force_authenticate(self.support)
        started = self.post(f"/actions/{action_id}/start/")
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(started.data["status"], "in_progress")
        completed = self.post(f"/actions/{action_id}/complete/")
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(completed.data["status"], "completed")
        self.assertIsNotNone(completed.data["completed_at"])

    def test_action_validate_fresh_record(self):
        action_id = self.action().data["id"]
        resp = self.post(f"/actions/{action_id}/validate/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "verified")

    def test_action_stale_unknown_and_missing(self):
        action_id = self.action().data["id"]
        self.assertEqual(
            self.post(f"/actions/{action_id}/cancel/",
                      {"expected_record_version": 999}).status_code, 409)
        self.assertEqual(self.post(f"/actions/{action_id}/bogus/").status_code, 404)
        self.assertEqual(self.post("/actions/999999/start/").status_code, 404)

    # --- Workarounds, validations, exceptions ---

    def workaround(self, **fields):
        payload = {"title": "Restart service", "steps": "1. restart"}
        payload.update(fields)
        return self.post(f"/problems/{self.problem.pk}/workarounds/", payload)

    def test_workaround_lifecycle(self):
        created = self.workaround()
        self.assertEqual(created.status_code, 201, created.data)
        wid = created.data["id"]
        submitted = self.post(f"/workarounds/{wid}/submit/")
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["status"], "submitted")
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.post(f"/workarounds/{wid}/approve/").status_code, 200)
        published = self.post(f"/workarounds/{wid}/publish/")
        self.assertEqual(published.status_code, 200, published.data)
        self.assertEqual(published.data["status"], "published")

    def validation(self, **fields):
        payload = {"title": "Failover test", "test_plan": "kill node"}
        payload.update(fields)
        return self.post(f"/problems/{self.problem.pk}/validations/", payload)

    def test_validation_pass_contract(self):
        created = self.validation()
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["status"], "draft")
        self.assertFalse(created.data["passed"])
        passed = self.post(f"/validations/{created.data['id']}/pass/")
        self.assertEqual(passed.status_code, 200, passed.data)
        self.assertEqual(passed.data["status"], "verified")
        self.assertTrue(passed.data["passed"])

    def test_validation_start_then_cancel(self):
        vid = self.validation().data["id"]
        started = self.post(f"/validations/{vid}/start/")
        self.assertEqual(started.data["status"], "in_progress")
        cancelled = self.post(f"/validations/{vid}/cancel/")
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["status"], "cancelled")

    def exception(self, **fields):
        payload = {"title": "Accept risk", "description": "temporary"}
        payload.update(fields)
        return self.post(f"/problems/{self.problem.pk}/exceptions/", payload)

    def test_exception_lifecycle_and_separation_of_duties(self):
        future = (timezone.now() + timezone.timedelta(days=7)).isoformat()
        created = self.exception(expires_at=future)
        self.assertEqual(created.status_code, 201, created.data)
        eid = created.data["id"]
        self.assertEqual(self.post(f"/exceptions/{eid}/approve/").status_code, 403)
        submitted = self.post(f"/exceptions/{eid}/submit/")
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["status"], "active")
        self.client.force_authenticate(self.manager)
        approved = self.post(f"/exceptions/{eid}/approve/")
        self.assertEqual(approved.status_code, 200, approved.data)
        revoked = self.post(f"/exceptions/{eid}/revoke/", {"reason": "fixed"})
        self.assertEqual(revoked.status_code, 200, revoked.data)
        self.assertEqual(revoked.data["status"], "revoked")

    def test_exception_past_expiry_rejected(self):
        past = (timezone.now() - timezone.timedelta(days=1)).isoformat()
        self.assertEqual(self.exception(expires_at=past).status_code, 400)

    # --- Readiness, linked relations, access control ---

    def test_readiness_contract_is_read_only(self):
        before = ProblemHistory.objects.count()
        resp = self.get(f"/problems/{self.problem.pk}/readiness/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(
            set(resp.data),
            {"ready_for_resolution", "ready_for_closure", "blockers",
             "warnings", "counts"})
        self.assertEqual(
            set(resp.data["counts"]),
            {"open_blocking_tasks", "open_required_actions", "failed_validations",
             "open_critical_tickets", "active_exceptions"})
        self.assertEqual(ProblemHistory.objects.count(), before)

    def test_linked_changes_unsupported_products_available(self):
        self.assertEqual(
            self.get(f"/problems/{self.problem.pk}/linked-changes/").status_code,
            404)
        products = self.get(f"/problems/{self.problem.pk}/linked-products/")
        self.assertEqual(products.status_code, 200)
        self.assertEqual(list(products.data), [])

    def test_employee_inactive_and_unknown_roles_denied(self):
        for index, (role, active) in enumerate(
                (("employee", True), ("it_support", False), ("gremlin", True)), 1):
            user = _user(role, index, active=active)
            self.client.force_authenticate(user)
            resp = self.get(f"/problems/{self.problem.pk}/readiness/")
            self.assertEqual(resp.status_code, 403, f"{role}/{active}")

    def test_anonymous_denied(self):
        self.client.force_authenticate(None)
        resp = self.get(f"/problems/{self.problem.pk}/readiness/")
        self.assertIn(resp.status_code, (401, 403))

    def test_missing_problem_returns_404(self):
        self.assertEqual(self.get("/problems/999999/readiness/").status_code, 404)

    # --- Governed cross-cutting contracts ---

    def test_gate2_mutations_deny_employee(self):
        employee = _user("employee", 90)
        self.client.force_authenticate(employee)
        self.assertEqual(
            self.post("/root-cause-analyses/",
                      {"problem": self.problem.pk, "title": "x"}).status_code, 403)
        self.assertEqual(
            self.get(f"/problems/{self.problem.pk}/evidence/").status_code, 403)
        self.assertEqual(self.post("/actions/1/start/").status_code, 403)

    def test_invalid_transition_returns_400(self):
        rca_id = self.rca().data["id"]
        self.client.force_authenticate(self.manager)
        self.assertEqual(
            self.post(f"/root-cause-analyses/{rca_id}/approve/").status_code, 200)
        resp = self.post(f"/root-cause-analyses/{rca_id}/approve/")
        self.assertEqual(resp.status_code, 400)

    def test_exception_creator_cannot_self_approve(self):
        self.client.force_authenticate(self.manager)
        future = (timezone.now() + timezone.timedelta(days=7)).isoformat()
        eid = self.exception(expires_at=future).data["id"]
        self.assertEqual(self.post(f"/exceptions/{eid}/submit/").status_code, 200)
        resp = self.post(f"/exceptions/{eid}/approve/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("self-approve", str(resp.data).lower())

    def test_action_cross_problem_rca_rejected(self):
        other = self.accepted_problem("Action other")
        other_rca = services.create_root_cause_analysis(
            actor=self.support, problem=other, title="Other RCA")
        resp = self.action(root_cause_analysis=other_rca.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("different problem", str(resp.data).lower())

    def test_action_patch_cross_problem_rca_rejected(self):
        other = self.accepted_problem("Patch other")
        other_rca = services.create_root_cause_analysis(
            actor=self.support, problem=other, title="Other RCA")
        action_id = self.action().data["id"]
        resp = self.client.patch(
            f"{BASE}/actions/{action_id}/",
            {"root_cause_analysis": other_rca.pk}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_factor_returns_400_not_500(self):
        rca_id = self.rca().data["id"]
        path = f"/problems/{self.problem.pk}/root-cause-factors/"
        payload = {"analysis": rca_id, "category": "people", "factor": "F"}
        self.assertEqual(self.post(path, payload).status_code, 201)
        self.assertEqual(self.post(path, payload).status_code, 400)

    def test_evidence_list_exposes_no_private_path(self):
        self.upload()
        resp = self.get(f"/problems/{self.problem.pk}/evidence/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("problem_evidence/", str(resp.data))
        for row in resp.data:
            self.assertNotIn("file", row)
            self.assertNotIn("/", row["original_filename"])
            self.assertNotIn("\\", row["original_filename"])
