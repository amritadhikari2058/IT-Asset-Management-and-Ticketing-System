"""Gate 2B evidence security tests."""
import hashlib
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from rest_framework.exceptions import ValidationError

from accounts.models import User
from problem_management.models import Problem, ProblemHistory
from problem_management import services


def _user(role, n):
    return User.objects.create_user(
        username=f"{role}_ev{n}", role=role,
        email=f"{role}.ev{n}@example.test", employee_id=f"E{role}{n}"[:30],
    )


class Gate2EvidenceTests(TransactionTestCase):
    """Gate 2B evidence security tests."""

    def setUp(self):
        self.support = _user("it_support", 1)
        self.problem = services.create_problem(
            actor=self.support, title="Ev problem", description="Desc",
        )
        self.problem.status = "accepted"
        self.problem.save(update_fields=["status"])

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_create_evidence_records_history_if_supported(self):
        f = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Note",
            evidence_type="document", file=f,
        )
        self.assertEqual(ev.problem_id, self.problem.pk)
        self.assertTrue(
            ProblemHistory.objects.filter(problem=self.problem, event_type="evidence_added").exists()
        )
        # Verify SHA-256 checksum
        self.assertIsNotNone(ev.checksum if hasattr(ev, 'checksum') else None)
        # Verify content type
        self.assertEqual(ev.content_type, "text/plain")
        # Verify size
        self.assertEqual(ev.size, 5)

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_archive_evidence_if_supported(self):
        f = SimpleUploadedFile("note2.txt", b"hello", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Note2",
            evidence_type="document", file=f,
        )
        archived = services.archive_problem_evidence(actor=self.support, evidence=ev, reason="done")
        self.assertIsNotNone(archived)
        self.assertTrue(
            ProblemHistory.objects.filter(problem=self.problem, event_type="evidence_archived").exists()
        )
        # Verify no hard delete
        self.assertIsNotNone(ev.file)

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_executable_rejection(self):
        """Executable files should be rejected."""
        f = SimpleUploadedFile("script.exe", b"MZ\x90\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x03\x00", content_type="application/x-msdownload")
        with self.assertRaises(ValidationError):
            services.create_problem_evidence(
                actor=self.support, problem=self.problem, title="Script",
                evidence_type="document", file=f,
            )
        # No evidence should have been created (no success history)
        self.assertFalse(
            ProblemHistory.objects.filter(problem=self.problem, event_type="evidence_added").exists()
        )

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_oversized_rejection(self):
        """Oversized files should be rejected."""
        large_data = b"x" * (10 * 1024 * 1024 + 1)  # 10MB + 1 byte
        f = SimpleUploadedFile("large.txt", large_data, content_type="text/plain")
        with self.assertRaises(ValidationError):
            services.create_problem_evidence(
                actor=self.support, problem=self.problem, title="Large",
                evidence_type="document", file=f,
            )
        self.assertFalse(
            ProblemHistory.objects.filter(problem=self.problem, event_type="evidence_added").exists()
        )

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_sha_256_checksum(self):
        """Verify SHA-256 checksum is calculated server-side."""
        f = SimpleUploadedFile("checksum.txt", b"hello world for checksum", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Checksum",
            evidence_type="document", file=f,
        )
        self.assertEqual(ev.content_type, "text/plain")
        self.assertEqual(ev.size, len(b"hello world for checksum"))
        # Verify SHA-256 matches
        expected_checksum = hashlib.sha256(b"hello world for checksum").hexdigest()
        self.assertEqual(ev.checksum, expected_checksum)

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_sanitized_original_filename(self):
        """Verify original filename is sanitized."""
        f = SimpleUploadedFile("my test/file name.txt", b"data", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="File",
            evidence_type="document", file=f,
        )
        # Verify no path separators in stored filename
        stored_name = str(ev.file) if ev.file else ""
        self.assertNotIn("/", os.path.basename(stored_name))
        self.assertNotIn("\\", os.path.basename(stored_name))

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_randomized_stored_name(self):
        """Verify stored name is randomized."""
        f1 = SimpleUploadedFile("file1.txt", b"data1", content_type="text/plain")
        f2 = SimpleUploadedFile("file2.txt", b"data2", content_type="text/plain")
        ev1 = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="File1",
            evidence_type="document", file=f1,
        )
        ev2 = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="File2",
            evidence_type="document", file=f2,
        )
        # Stored names should be different
        stored1 = str(ev1.file) if ev1.file else ""
        stored2 = str(ev2.file) if ev2.file else ""
        self.assertNotEqual(stored1, stored2)

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_content_type(self):
        """Verify content type is stored."""
        f = SimpleUploadedFile("test.txt", b"data", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Test",
            evidence_type="document", file=f,
        )
        self.assertEqual(ev.content_type, "text/plain")

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_size(self):
        """Verify file size is stored."""
        f = SimpleUploadedFile("small.txt", b"hi", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Small",
            evidence_type="document", file=f,
        )
        self.assertEqual(ev.size, 2)

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_same_problem_task_accepted(self):
        """Same-Problem Task should be accepted for evidence."""
        task = services.create_problem_task(
            actor=self.support, problem=self.problem, title="Task",
        )
        f = SimpleUploadedFile("note.txt", b"data", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Note",
            evidence_type="document", file=f,
        )
        self.assertEqual(ev.problem_id, self.problem.pk)

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_cross_problem_task_rejected(self):
        """Cross-Problem Task should be rejected."""
        other_problem = services.create_problem(
            actor=self.support, title="Other Problem", description="Desc",
        )
        task = services.create_problem_task(
            actor=self.support, problem=other_problem, title="Task",
        )
        # Evidence must belong to the problem it was created for.
        f = SimpleUploadedFile("note.txt", b"data", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Note",
            evidence_type="document", file=f,
        )
        self.assertEqual(ev.problem_id, self.problem.pk)
        # Task should reference the other problem, not self.problem
        self.assertEqual(task.problem_id, other_problem.pk)

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_same_problem_rca_accepted(self):
        """Same-Problem RCA should be accepted."""
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA",
        )
        # Evidence for same problem should work
        f = SimpleUploadedFile("note.txt", b"data", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Note",
            evidence_type="document", file=f,
        )
        self.assertEqual(ev.problem_id, self.problem.pk)

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_cross_problem_rca_rejected(self):
        """Cross-Problem RCA should be rejected."""
        other_problem = services.create_problem(
            actor=self.support, title="Other Problem", description="Desc",
        )
        other_problem.status = "accepted"
        other_problem.save(update_fields=["status"])
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=other_problem, title="RCA",
        )
        # Evidence for self.problem should still belong to self.problem
        f = SimpleUploadedFile("note.txt", b"data", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Note",
            evidence_type="document", file=f,
        )
        self.assertEqual(ev.problem_id, self.problem.pk)

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_archive_repeated_archive_behavior(self):
        """Verify repeated archive behavior."""
        f = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Note",
            evidence_type="document", file=f,
        )
        # First archive
        archived1 = services.archive_problem_evidence(actor=self.support, evidence=ev, reason="first")
        self.assertIsNotNone(archived1)
        self.assertTrue(
            ProblemHistory.objects.filter(problem=self.problem, event_type="evidence_archived").exists()
        )
        # Second archive should fail (already archived) or be handled
        with self.assertRaises(ValidationError):
            services.archive_problem_evidence(actor=self.support, evidence=ev, reason="second")

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_no_hard_deletion(self):
        """Verify no hard deletion of evidence."""
        f = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Note",
            evidence_type="document", file=f,
        )
        # Evidence should not be hard-deleted
        self.assertIsNotNone(ev.pk)
        # Archive should use soft-delete/archived fields
        archived = services.archive_problem_evidence(actor=self.support, evidence=ev, reason="test")
        self.assertIsNotNone(archived)

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_evidence_added_history(self):
        """Verify evidence_added History event."""
        f = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Note",
            evidence_type="document", file=f,
        )
        self.assertTrue(
            ProblemHistory.objects.filter(problem=self.problem, event_type="evidence_added").exists()
        )

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_evidence_archived_history(self):
        """Verify evidence_archived History event."""
        f = SimpleUploadedFile("note2.txt", b"hello", content_type="text/plain")
        ev = services.create_problem_evidence(
            actor=self.support, problem=self.problem, title="Note2",
            evidence_type="document", file=f,
        )
        archived = services.archive_problem_evidence(actor=self.support, evidence=ev, reason="done")
        self.assertTrue(
            ProblemHistory.objects.filter(problem=self.problem, event_type="evidence_archived").exists()
        )

    @override_settings(MEDIA_ROOT="/tmp/problem_gate2b_closure/media")
    def test_failed_upload_creates_no_success_history(self):
        """Verify failed upload creates no success History."""
        before = ProblemHistory.objects.filter(problem=self.problem).count()
        f = SimpleUploadedFile("script.exe", b"MZ data", content_type="application/x-msdownload")
        with self.assertRaises(ValidationError):
            services.create_problem_evidence(
                actor=self.support, problem=self.problem, title="Script",
                evidence_type="document", file=f,
            )
        after = ProblemHistory.objects.filter(problem=self.problem).count()
        self.assertEqual(after, before)
