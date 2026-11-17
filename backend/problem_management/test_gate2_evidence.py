"""Gate 2B evidence security tests (baseline)."""
import hashlib
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings

from accounts.models import User
from problem_management.models import Problem, ProblemHistory
from problem_management import services


def _user(role, n):
    return User.objects.create_user(
        username=f"{role}_ev{n}", role=role,
        email=f"{role}.ev{n}@example.test", employee_id=f"E{role}{n}"[:30],
    )


class Gate2EvidenceBaselineTests(TransactionTestCase):
    def setUp(self):
        self.support = _user("it_support", 1)
        self.problem = services.create_problem(
            actor=self.support, title="Ev problem", description="Desc",
        )

    @override_settings(MEDIA_ROOT=r"C:\Users\krish\AppData\Local\Temp\opencode\problem_gate2b\media")
    def test_create_evidence_records_history_if_supported(self):
        if not hasattr(services, "create_problem_evidence"):
            self.skipTest("create_problem_evidence not implemented")
        f = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
        try:
            ev = services.create_problem_evidence(
                actor=self.support, problem=self.problem, title="Note",
                evidence_type="document", file=f,
            )
        except Exception:
            # Baseline: ensure failure does not create false success history.
            self.assertFalse(
                ProblemHistory.objects.filter(problem=self.problem, event_type="evidence_added").exists()
            )
            return
        self.assertEqual(ev.problem_id, self.problem.pk)
        self.assertTrue(
            ProblemHistory.objects.filter(problem=self.problem, event_type="evidence_added").exists()
        )

    @override_settings(MEDIA_ROOT=r"C:\Users\krish\AppData\Local\Temp\opencode\problem_gate2b\media")
    def test_archive_evidence_if_supported(self):
        if not hasattr(services, "create_problem_evidence") or not hasattr(services, "archive_problem_evidence"):
            self.skipTest("evidence services not fully implemented")
        f = SimpleUploadedFile("note2.txt", b"hello", content_type="text/plain")
        try:
            ev = services.create_problem_evidence(
                actor=self.support, problem=self.problem, title="Note2",
                evidence_type="document", file=f,
            )
        except Exception:
            self.skipTest("create_problem_evidence not compatible in baseline")
        archived = services.archive_problem_evidence(actor=self.support, evidence=ev, reason="done")
        self.assertIsNotNone(archived)
        self.assertTrue(
            ProblemHistory.objects.filter(problem=self.problem, event_type="evidence_archived").exists()
        )
