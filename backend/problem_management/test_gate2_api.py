"""Gate 2 API contract tests: RCA, whys, factors, evidence, workflows, access."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Department, User
from common.models import AuditLog
from problem_management import services
from problem_management.models import (
    ProblemAction, ProblemHistory, ProblemTicketLink, RootCauseAnalysis,
)
from tickets.models import Ticket, TicketCategory

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

    def set_action_status(self, action_id, status):
        ProblemAction.objects.filter(pk=action_id).update(status=status)

    def test_action_lifecycle(self):
        created = self.action()
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["status"], "planned")
        self.assertEqual(created.data["version"], 1)
        action_id = created.data["id"]

        self.client.force_authenticate(self.manager)
        approved = self.post(
            f"/actions/{action_id}/approve/",
            {"expected_record_version": 1})
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], "approved")
        self.assertEqual(approved.data["version"], 2)

        self.client.force_authenticate(self.support)
        started = self.post(
            f"/actions/{action_id}/start/",
            {"expected_record_version": approved.data["version"]})
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(started.data["status"], "in_progress")
        self.assertEqual(started.data["version"], 3)

        completed = self.post(
            f"/actions/{action_id}/complete/",
            {"expected_record_version": started.data["version"]})
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(completed.data["status"], "completed")
        self.assertEqual(completed.data["version"], 4)
        self.assertIsNotNone(completed.data["completed_at"])

        current = self.get(f"/actions/{action_id}/")
        self.assertEqual(current.data["status"], "completed")
        self.assertEqual(current.data["version"], 4)

    def test_action_full_lifecycle_with_current_versions_and_validation(self):
        created = self.action()
        action_id = created.data["id"]
        version = created.data["version"]

        started = self.post(
            f"/actions/{action_id}/start/",
            {"expected_record_version": version})
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(started.data["status"], "in_progress")
        self.assertEqual(started.data["version"], version + 1)
        version = started.data["version"]

        completed = self.post(
            f"/actions/{action_id}/complete/",
            {"expected_record_version": version})
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(completed.data["status"], "completed")
        self.assertEqual(completed.data["version"], version + 1)
        completed_at = completed.data["completed_at"]
        self.assertIsNotNone(completed_at)
        version = completed.data["version"]

        validated = self.post(
            f"/actions/{action_id}/validate/",
            {"expected_record_version": version})
        self.assertEqual(validated.status_code, 200, validated.data)
        self.assertEqual(validated.data["status"], "verified")
        self.assertEqual(validated.data["version"], version + 1)
        self.assertEqual(validated.data["verified_by"], self.support.pk)
        self.assertIsNotNone(validated.data["verified_at"])
        self.assertEqual(validated.data["completed_at"], completed_at)

        current = self.get(f"/actions/{action_id}/")
        self.assertEqual(current.data["status"], "verified")
        self.assertEqual(current.data["version"], version + 1)
        self.assertEqual(current.data["verified_by"], self.support.pk)

    def test_action_validate_rejects_fresh_planned_record(self):
        created = self.action()
        action_id = created.data["id"]
        resp = self.post(f"/actions/{action_id}/validate/")
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("action", resp.data)
        current = self.get(f"/actions/{action_id}/")
        self.assertEqual(current.data["status"], "planned")
        self.assertEqual(current.data["version"], 1)
        self.assertFalse(ProblemHistory.objects.filter(
            problem=self.problem, event_type="action_validated").exists())

    def test_action_stale_unknown_and_missing(self):
        created = self.action()
        action_id = created.data["id"]
        stale = self.post(
            f"/actions/{action_id}/cancel/",
            {"expected_record_version": 999, "reason": "Stale token test"})
        self.assertEqual(stale.status_code, 409, stale.data)
        self.assertIn("version", str(stale.data).lower())
        current = self.get(f"/actions/{action_id}/")
        self.assertEqual(current.data["status"], "planned")
        self.assertEqual(current.data["version"], 1)
        self.assertEqual(self.post(f"/actions/{action_id}/bogus/").status_code, 404)
        self.assertEqual(self.post("/actions/999999/start/").status_code, 404)

    def test_action_approval_persists_and_versions(self):
        action_id = self.action().data["id"]

        denied = self.post(f"/actions/{action_id}/approve/")
        self.assertEqual(denied.status_code, 403, denied.data)

        self.client.force_authenticate(self.manager)
        approved = self.post(
            f"/actions/{action_id}/approve/",
            {"expected_record_version": 1})
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], "approved")
        self.assertEqual(approved.data["version"], 2)

        self.client.force_authenticate(self.support)
        current = self.get(f"/actions/{action_id}/")
        self.assertEqual(current.data["status"], "approved")
        self.assertEqual(current.data["version"], 2)

        self.client.force_authenticate(self.manager)
        repeated = self.post(
            f"/actions/{action_id}/approve/",
            {"expected_record_version": 2})
        self.assertEqual(repeated.status_code, 400, repeated.data)
        self.assertIn("action", repeated.data)
        self.assertEqual(ProblemHistory.objects.filter(
            problem=self.problem, event_type="action_approved").count(), 1)

    def test_action_invalid_source_statuses_rejected(self):
        cases = (
            ("in_progress", "approve", self.manager),
            ("completed", "start", self.support),
            ("planned", "complete", self.support),
            ("in_progress", "validate", self.support),
            ("planned", "ineffective", self.support),
        )
        for status, action_name, actor in cases:
            with self.subTest(status=status, transition=action_name):
                action_id = self.action().data["id"]
                self.set_action_status(action_id, status)
                self.client.force_authenticate(actor)
                resp = self.post(
                    f"/actions/{action_id}/{action_name}/",
                    {"expected_record_version": 1})
                self.assertEqual(resp.status_code, 400, resp.data)
                self.assertIn("action", resp.data)
                current = self.get(f"/actions/{action_id}/")
                self.assertEqual(current.data["status"], status)
                self.assertEqual(current.data["version"], 1)

    def test_action_terminal_statuses_reject_transitions(self):
        transitions = (
            ("approve", self.manager),
            ("start", self.support),
            ("complete", self.support),
            ("validate", self.support),
            ("ineffective", self.support),
            ("cancel", self.support),
        )
        for terminal in ("verified", "ineffective", "cancelled", "closed"):
            for action_name, actor in transitions:
                with self.subTest(terminal=terminal, transition=action_name):
                    action_id = self.action().data["id"]
                    self.set_action_status(action_id, terminal)
                    self.client.force_authenticate(actor)
                    history_before = ProblemHistory.objects.filter(
                        problem=self.problem).count()
                    resp = self.post(
                        f"/actions/{action_id}/{action_name}/",
                        {"expected_record_version": 1})
                    self.assertEqual(resp.status_code, 400, resp.data)
                    self.assertIn("action", resp.data)
                    self.assertEqual(
                        ProblemHistory.objects.filter(problem=self.problem).count(),
                        history_before)
                    current = self.get(f"/actions/{action_id}/")
                    self.assertEqual(current.data["status"], terminal)
                    self.assertEqual(current.data["version"], 1)

    def test_superuser_employee_cannot_transition_actions_via_api(self):
        superuser = _user("employee", 91)
        superuser.is_superuser = True
        superuser.save(update_fields=["is_superuser"])
        self.assertTrue(superuser.is_authenticated)
        self.assertTrue(superuser.is_active)
        self.assertTrue(superuser.is_superuser)
        self.assertEqual(superuser.role, "employee")

        events = {
            "approve": ("action_approved", "problem_action_approved"),
            "start": ("action_started", "problem_action_started"),
            "cancel": ("action_cancelled", "problem_action_cancelled"),
        }
        for transition, (event_type, audit_action) in events.items():
            with self.subTest(transition=transition):
                self.client.force_authenticate(self.support)
                created = self.action()
                self.assertEqual(created.status_code, 201, created.data)
                action_id = created.data["id"]
                history_before = ProblemHistory.objects.filter(
                    problem=self.problem).count()
                audit_before = AuditLog.objects.filter(
                    entity_type="problem_management.problemaction",
                    object_id=str(action_id),
                ).count()

                self.client.force_authenticate(superuser)
                payload = {"expected_record_version": 1}
                if transition == "cancel":
                    payload["reason"] = "Superuser denial check"
                resp = self.post(
                    f"/actions/{action_id}/{transition}/", payload)
                self.assertEqual(resp.status_code, 403, resp.data)

                current = ProblemAction.objects.get(pk=action_id)
                self.assertEqual(current.status, "planned")
                self.assertEqual(current.version, 1)
                self.assertEqual(
                    ProblemHistory.objects.filter(problem=self.problem).count(),
                    history_before)
                self.assertEqual(
                    AuditLog.objects.filter(
                        entity_type="problem_management.problemaction",
                        object_id=str(action_id),
                    ).count(),
                    audit_before)
                self.assertFalse(ProblemHistory.objects.filter(
                    problem=self.problem, event_type=event_type).exists())
                self.assertFalse(AuditLog.objects.filter(
                    entity_type="problem_management.problemaction",
                    object_id=str(action_id), action=audit_action).exists())

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
        self.assertEqual(created.data["version"], 1)
        self.assertFalse(created.data["passed"])
        passed = self.post(f"/validations/{created.data['id']}/pass/")
        self.assertEqual(passed.status_code, 200, passed.data)
        self.assertEqual(passed.data["status"], "verified")
        self.assertEqual(passed.data["version"], 2)
        self.assertTrue(passed.data["passed"])
        current = self.get(f"/validations/{created.data['id']}/")
        self.assertEqual(current.data["status"], "verified")
        self.assertEqual(current.data["version"], 2)
        self.assertTrue(current.data["passed"])

    def test_validation_start_then_pass(self):
        vid = self.validation().data["id"]
        started = self.post(
            f"/validations/{vid}/start/",
            {"expected_record_version": 1},
        )
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(started.data["status"], "in_progress")
        self.assertEqual(started.data["version"], 2)
        passed = self.post(
            f"/validations/{vid}/pass/",
            {"expected_record_version": started.data["version"]},
        )
        self.assertEqual(passed.status_code, 200, passed.data)
        self.assertEqual(passed.data["status"], "verified")
        self.assertEqual(passed.data["version"], 3)
        self.assertTrue(passed.data["passed"])
        current = self.get(f"/validations/{vid}/")
        self.assertEqual(current.data["status"], "verified")
        self.assertEqual(current.data["version"], 3)
        self.assertTrue(current.data["passed"])

    def test_validation_stale_version_conflict(self):
        vid = self.validation().data["id"]
        started = self.post(f"/validations/{vid}/start/")
        self.assertEqual(started.status_code, 200, started.data)
        stale = self.post(
            f"/validations/{vid}/pass/", {"expected_record_version": 1})
        self.assertEqual(stale.status_code, 409, stale.data)
        self.assertIn("version", str(stale.data).lower())
        current = self.get(f"/validations/{vid}/")
        self.assertEqual(current.data["status"], "in_progress")
        self.assertEqual(current.data["version"], 2)
        self.assertFalse(current.data["passed"])

    def test_validation_start_then_cancel(self):
        vid = self.validation().data["id"]
        started = self.post(f"/validations/{vid}/start/")
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(started.data["status"], "in_progress")
        cancelled = self.post(
            f"/validations/{vid}/cancel/",
            {"expected_record_version": started.data["version"]},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["status"], "cancelled")
        self.assertEqual(cancelled.data["version"], 3)
        self.assertFalse(cancelled.data["passed"])

    def test_validation_start_only_from_draft(self):
        vid = self.validation().data["id"]
        self.assertEqual(self.post(f"/validations/{vid}/start/").status_code, 200)
        again = self.post(f"/validations/{vid}/start/")
        self.assertEqual(again.status_code, 400, again.data)
        self.assertIn("validation", again.data)

    def test_validation_terminal_statuses_reject_transitions(self):
        transitions = ("start", "pass", "fail", "inconclusive", "cancel")
        for terminal, enter in (
            ("verified", "pass"),
            ("failed", "fail"),
            ("inconclusive", "inconclusive"),
            ("cancelled", "cancel"),
        ):
            vid = self.validation().data["id"]
            entered = self.post(f"/validations/{vid}/{enter}/")
            self.assertEqual(entered.status_code, 200, entered.data)
            self.assertEqual(entered.data["status"], terminal)
            for action in transitions:
                with self.subTest(terminal=terminal, action=action):
                    resp = self.post(f"/validations/{vid}/{action}/")
                    self.assertEqual(resp.status_code, 400, resp.data)
                    self.assertIn("validation", resp.data)

    def test_validation_inconclusive_and_cancel_clear_passed(self):
        for action, expected_status in (
            ("inconclusive", "inconclusive"),
            ("cancel", "cancelled"),
        ):
            val = services.create_problem_validation(
                actor=self.support, problem=self.problem, title="Legacy passed",
            )
            val.passed = True
            val.save(update_fields=["passed"])
            resp = self.post(f"/validations/{val.pk}/{action}/")
            self.assertEqual(resp.status_code, 200, resp.data)
            self.assertEqual(resp.data["status"], expected_status)
            self.assertFalse(resp.data["passed"])
            self.assertEqual(resp.data["version"], 3)

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

    def test_linked_ticket_endpoints_expose_read_only_ticket_metadata(self):
        cat = TicketCategory.objects.create(name="API Ticket Cat")
        ticket = Ticket.objects.create(
            title="VPN outage", description="d", category=cat,
            requester=self.support, priority="critical", status="open",
        )
        link = ProblemTicketLink.objects.create(
            problem=self.problem, ticket=ticket, linked_by=self.support,
            relationship_type="related_incident", relevance="high",
            is_primary=True, note="Primary incident",
        )

        for path, use_base in (
            (f"/problems/{self.problem.pk}/linked-tickets/", True),
            (f"/ticket-links/?problem={self.problem.pk}", True),
        ):
            with self.subTest(path=path):
                resp = self.get(path) if use_base else self.client.get(path)
                self.assertEqual(resp.status_code, 200, resp.data)
                rows = resp.data["results"] if isinstance(resp.data, dict) and "results" in resp.data else resp.data
                row = next(r for r in rows if r["id"] == link.id)
                self.assertEqual(row["ticket"], ticket.id)
                self.assertEqual(row["ticket_display"], f"#{ticket.id}")
                self.assertEqual(row["ticket_title"], "VPN outage")
                self.assertEqual(row["ticket_status"], "open")
                self.assertEqual(row["ticket_priority"], "critical")
                self.assertEqual(row["ticket_category_name"], "API Ticket Cat")
                self.assertEqual(row["relationship_type"], "related_incident")
                self.assertEqual(row["relevance"], "high")
                self.assertTrue(row["is_primary"])
                self.assertEqual(row["note"], "Primary incident")
                self.assertIn("linked_by", row)
                self.assertIn("linked_at", row)
                self.assertIn("is_deleted", row)

        # Read-only metadata cannot be changed through relationship updates.
        patch = self.client.patch(
            f"{BASE}/ticket-links/{link.id}/",
            {"ticket_title": "Mutated", "ticket_status": "closed", "note": "Updated note"},
            format="json",
        )
        self.assertEqual(patch.status_code, 200, patch.data)
        link.refresh_from_db()
        ticket.refresh_from_db()
        self.assertEqual(ticket.title, "VPN outage")
        self.assertEqual(ticket.status, "open")
        self.assertEqual(link.note, "Updated note")
        self.assertEqual(patch.data["ticket_title"], "VPN outage")
        self.assertEqual(patch.data["ticket_status"], "open")

        # Soft-delete lifecycle remains intact.
        delete = self.client.delete(f"{BASE}/ticket-links/{link.id}/")
        self.assertEqual(delete.status_code, 204, getattr(delete, "data", None))
        link.refresh_from_db()
        self.assertTrue(link.is_deleted)
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="ticket_unlinked").exists())

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

    @staticmethod
    def _rows(response):
        return response.data["results"] if isinstance(response.data, dict) else response.data

    def test_other_staff_can_access_and_transition_action_created_by_another_staff(self):
        created = self.action()
        self.assertEqual(created.status_code, 201, created.data)
        action_id = created.data["id"]
        stored = ProblemAction.objects.get(pk=action_id)
        self.assertEqual(stored.created_by_id, self.support.pk)
        self.assertIsNone(stored.assigned_to_id)
        self.assertNotEqual(self.support.pk, self.manager.pk)
        self.assertEqual(self.support.role, "it_support")
        self.assertEqual(self.manager.role, "it_manager")
        self.assertTrue(self.support.is_active)
        self.assertTrue(self.manager.is_active)

        self.client.force_authenticate(self.manager)
        detail = self.get(f"/actions/{action_id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["id"], action_id)

        listed = self.get("/actions/")
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertIn(action_id, [row["id"] for row in self._rows(listed)])

        nested = self.get(f"/problems/{self.problem.pk}/actions/")
        self.assertEqual(nested.status_code, 200, nested.data)
        self.assertIn(action_id, [row["id"] for row in self._rows(nested)])

        history_before = ProblemHistory.objects.filter(problem=self.problem).count()
        audit_before = AuditLog.objects.filter(
            entity_type="problem_management.problemaction",
            object_id=str(action_id),
        ).count()
        approval_audit_before = AuditLog.objects.filter(
            entity_type="problem_management.problemaction",
            object_id=str(action_id), action="problem_action_approved",
        ).count()
        approved = self.post(
            f"/actions/{action_id}/approve/",
            {"expected_record_version": 1},
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], "approved")
        self.assertEqual(approved.data["version"], 2)
        self.assertEqual(
            ProblemHistory.objects.filter(
                problem=self.problem, event_type="action_approved",
                actor=self.manager,
            ).count(),
            1,
        )
        self.assertEqual(
            ProblemHistory.objects.filter(problem=self.problem).count(),
            history_before + 1,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                entity_type="problem_management.problemaction",
                object_id=str(action_id), action="problem_action_approved",
            ).count(),
            approval_audit_before + 1,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                entity_type="problem_management.problemaction",
                object_id=str(action_id),
            ).count(),
            audit_before + 1,
        )
        stored.refresh_from_db()
        self.assertEqual(stored.status, "approved")
        self.assertEqual(stored.version, 2)

    def test_other_department_staff_can_read_problem_and_actions(self):
        dept_a = Department.objects.create(name="PM Dept A", code="PM-A")
        dept_b = Department.objects.create(name="PM Dept B", code="PM-B")
        self.support.home_department = dept_a
        self.support.save(update_fields=["home_department"])
        self.manager.home_department = dept_b
        self.manager.save(update_fields=["home_department"])
        self.support.refresh_from_db()
        self.manager.refresh_from_db()
        self.assertNotEqual(
            self.support.home_department_id, self.manager.home_department_id)
        self.assertTrue(self.support.is_active)
        self.assertTrue(self.manager.is_active)

        created = self.action()
        self.assertEqual(created.status_code, 201, created.data)
        action_id = created.data["id"]

        self.client.force_authenticate(self.manager)
        problem_detail = self.get(f"/problems/{self.problem.pk}/")
        self.assertEqual(problem_detail.status_code, 200, problem_detail.data)
        self.assertEqual(problem_detail.data["id"], self.problem.pk)

        nested = self.get(f"/problems/{self.problem.pk}/actions/")
        self.assertEqual(nested.status_code, 200, nested.data)
        self.assertIn(action_id, [row["id"] for row in self._rows(nested)])

        detail = self.get(f"/actions/{action_id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["id"], action_id)
        self.assertEqual(detail.data["problem"], self.problem.pk)

    def test_action_access_does_not_depend_on_assignment(self):
        assigned = self.action(assigned_to=self.manager.pk)
        self.assertEqual(assigned.status_code, 201, assigned.data)
        assigned_id = assigned.data["id"]
        unassigned = self.action()
        self.assertEqual(unassigned.status_code, 201, unassigned.data)
        unassigned_id = unassigned.data["id"]
        self.assertEqual(assigned.data["assigned_to"], self.manager.pk)
        self.assertIsNone(unassigned.data["assigned_to"])
        self.assertNotEqual(self.support.pk, self.manager.pk)

        self.client.force_authenticate(self.support)
        assigned_detail = self.get(f"/actions/{assigned_id}/")
        self.assertEqual(assigned_detail.status_code, 200, assigned_detail.data)
        self.assertEqual(assigned_detail.data["id"], assigned_id)
        self.assertEqual(assigned_detail.data["created_by"], self.support.pk)
        self.assertEqual(assigned_detail.data["assigned_to"], self.manager.pk)
        self.assertNotEqual(assigned_detail.data["assigned_to"], self.support.pk)

        self.client.force_authenticate(self.manager)
        unassigned_detail = self.get(f"/actions/{unassigned_id}/")
        self.assertEqual(unassigned_detail.status_code, 200, unassigned_detail.data)
        self.assertEqual(unassigned_detail.data["id"], unassigned_id)
        self.assertEqual(unassigned_detail.data["created_by"], self.support.pk)
        self.assertIsNone(unassigned_detail.data["assigned_to"])
        self.assertNotEqual(unassigned_detail.data["created_by"], self.manager.pk)

        listed = self.get("/actions/")
        self.assertEqual(listed.status_code, 200, listed.data)
        ids = [row["id"] for row in self._rows(listed)]
        self.assertIn(assigned_id, ids)
        self.assertIn(unassigned_id, ids)

    def test_soft_deleted_actions_are_hidden_from_action_endpoints(self):
        created = self.action()
        self.assertEqual(created.status_code, 201, created.data)
        action_id = created.data["id"]
        action = ProblemAction.objects.get(pk=action_id)
        action.soft_delete(by_user=self.support, reason="Visibility test")
        stored = ProblemAction.all_objects.get(pk=action_id)
        self.assertTrue(stored.is_deleted)
        status_before = stored.status
        version_before = stored.version
        history_before = ProblemHistory.objects.filter(problem=self.problem).count()
        audit_before = AuditLog.objects.filter(
            entity_type="problem_management.problemaction",
            object_id=str(action_id),
        ).count()

        self.client.force_authenticate(self.manager)
        listed = self.get("/actions/")
        self.assertEqual(listed.status_code, 200, listed.data)
        self.assertNotIn(action_id, [row["id"] for row in self._rows(listed)])

        nested = self.get(f"/problems/{self.problem.pk}/actions/")
        self.assertEqual(nested.status_code, 200, nested.data)
        self.assertNotIn(action_id, [row["id"] for row in self._rows(nested)])

        detail = self.get(f"/actions/{action_id}/")
        self.assertEqual(detail.status_code, 404, detail.data)
        patched = self.client.patch(
            f"{BASE}/actions/{action_id}/", {"title": "Must not be saved"},
            format="json",
        )
        self.assertEqual(patched.status_code, 404, patched.data)

        for transition in (
            "approve", "start", "complete", "validate", "ineffective", "cancel",
        ):
            with self.subTest(transition=transition):
                payload = {"expected_record_version": version_before}
                if transition in ("cancel", "ineffective"):
                    payload["reason"] = "Deleted record"
                resp = self.post(f"/actions/{action_id}/{transition}/", payload)
                self.assertEqual(resp.status_code, 404, resp.data)

        stored.refresh_from_db()
        self.assertEqual(stored.status, status_before)
        self.assertEqual(stored.version, version_before)
        self.assertTrue(stored.is_deleted)
        self.assertEqual(
            ProblemHistory.objects.filter(problem=self.problem).count(),
            history_before,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                entity_type="problem_management.problemaction",
                object_id=str(action_id),
            ).count(),
            audit_before,
        )

    def test_put_and_delete_action_methods_are_not_allowed(self):
        created = self.action()
        self.assertEqual(created.status_code, 201, created.data)
        action_id = created.data["id"]
        history_before = ProblemHistory.objects.filter(problem=self.problem).count()
        audit_before = AuditLog.objects.filter(
            entity_type="problem_management.problemaction",
            object_id=str(action_id),
        ).count()

        put = self.client.put(
            f"{BASE}/actions/{action_id}/", {"title": "Must not be saved"},
            format="json",
        )
        self.assertEqual(put.status_code, 405, getattr(put, "data", None))
        deleted = self.client.delete(f"{BASE}/actions/{action_id}/")
        self.assertEqual(deleted.status_code, 405, getattr(deleted, "data", None))

        stored = ProblemAction.objects.get(pk=action_id)
        self.assertEqual(stored.title, "Replace disk")
        self.assertEqual(stored.status, "planned")
        self.assertEqual(stored.version, 1)
        self.assertFalse(stored.is_deleted)
        self.assertEqual(
            ProblemHistory.objects.filter(problem=self.problem).count(),
            history_before,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                entity_type="problem_management.problemaction",
                object_id=str(action_id),
            ).count(),
            audit_before,
        )
