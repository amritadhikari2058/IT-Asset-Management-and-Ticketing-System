"""ProblemAction generic PATCH contract: metadata only, no lifecycle bypass."""
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from common.models import AuditLog
from problem_management import services
from problem_management.models import ProblemAction, ProblemHistory

BASE = "/api/problems"


def _user(role, n):
    return User.objects.create_user(
        username=f"patch_{role}_{n}", role=role,
        email=f"patch.{role}.{n}@example.test",
        employee_id=f"P{role}{n}"[:30],
    )


class ProblemActionPatchTests(TransactionTestCase):
    def setUp(self):
        self.support = _user("it_support", 1)
        self.manager = _user("it_manager", 1)
        self.problem = services.create_problem(
            actor=self.support, title="Patch problem", description="Desc",
            owner=self.manager)
        services.submit_problem(actor=self.support, problem=self.problem)
        services.accept_problem(actor=self.manager, problem=self.problem)
        self.action = services.create_problem_action(
            actor=self.support, problem=self.problem, title="Original action",
            description="Original description")
        self.client = APIClient()
        self.client.force_authenticate(self.support)

    def patch_action(self, payload):
        return self.client.patch(
            f"{BASE}/actions/{self.action.pk}/", payload, format="json")

    def snapshot(self):
        self.action.refresh_from_db()
        return {
            "title": self.action.title,
            "description": self.action.description,
            "action_type": self.action.action_type,
            "status": self.action.status,
            "version": self.action.version,
            "problem_id": self.action.problem_id,
            "assigned_to_id": self.action.assigned_to_id,
            "due_at": self.action.due_at,
            "completed_at": self.action.completed_at,
            "root_cause_analysis_id": self.action.root_cause_analysis_id,
            "validation_status": self.action.validation_status,
            "verified_by_id": self.action.verified_by_id,
            "verified_at": self.action.verified_at,
            "created_by_id": self.action.created_by_id,
            "created_at": self.action.created_at,
            "is_deleted": self.action.is_deleted,
        }

    def side_effect_counts(self):
        return (
            ProblemHistory.objects.filter(problem=self.problem).count(),
            AuditLog.objects.filter(
                entity_type="problem_management.problemaction",
                object_id=str(self.action.pk),
            ).count(),
        )

    def assert_unchanged(self, row, side_effects):
        self.assertEqual(self.snapshot(), row)
        self.assertEqual(self.side_effect_counts(), side_effects)

    def test_patch_status_is_rejected_without_partial_save(self):
        row = self.snapshot()
        side_effects = self.side_effect_counts()

        response = self.patch_action({
            "status": "approved",
            "title": "Must not be saved",
        })

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("status", response.data)
        self.assertIn("dedicated lifecycle", str(response.data["status"]).lower())
        self.assert_unchanged(row, side_effects)

    def test_patch_transition_metadata_is_rejected_without_partial_save(self):
        now = timezone.now()
        cases = (
            ("id", 999999),
            ("version", 99),
            ("approved_by", self.manager.pk),
            ("approved_at", now.isoformat()),
            ("status", "cancelled"),
            ("completed_at", now.isoformat()),
            ("completed_by", self.manager.pk),
            ("validation_status", "valid"),
            ("verified_by", self.manager.pk),
            ("verified_at", now.isoformat()),
            ("verified_by_username", self.manager.username),
            ("assigned_to_username", self.manager.username),
            ("created_by", self.manager.pk),
            ("created_at", "2020-01-01T00:00:00Z"),
            ("cancelled_by", self.manager.pk),
            ("cancelled_at", now.isoformat()),
            ("cancellation_reason", "should not be accepted"),
            ("is_deleted", True),
            ("deleted_at", now.isoformat()),
            ("deleted_by", self.manager.pk),
            ("deletion_reason", "should not be accepted"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                row = self.snapshot()
                side_effects = self.side_effect_counts()

                response = self.patch_action({
                    field: value,
                    "title": "Must not be saved",
                })

                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn(field, response.data)
                self.assert_unchanged(row, side_effects)

    def test_patch_cannot_reassign_parent_problem(self):
        other = services.create_problem(
            actor=self.support, title="Other problem", description="Desc",
            owner=self.manager)
        row = self.snapshot()
        side_effects = self.side_effect_counts()

        response = self.patch_action({
            "problem": other.pk,
            "title": "Must not be saved",
        })

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("problem", response.data)
        self.assertIn("cannot be changed", str(response.data["problem"]).lower())
        self.assert_unchanged(row, side_effects)

    def test_patch_cross_problem_rca_is_rejected_without_partial_save(self):
        other = services.create_problem(
            actor=self.support, title="RCA owner problem", description="Desc",
            owner=self.manager)
        services.submit_problem(actor=self.support, problem=other)
        services.accept_problem(actor=self.manager, problem=other)
        other_rca = services.create_root_cause_analysis(
            actor=self.support, problem=other, title="Other problem RCA")
        row = self.snapshot()
        side_effects = self.side_effect_counts()

        response = self.patch_action({
            "root_cause_analysis": other_rca.pk,
            "title": "Must not be saved",
        })

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("root_cause_analysis", response.data)
        self.assertIn("different problem", str(response.data).lower())
        self.assert_unchanged(row, side_effects)

    def test_patch_stale_version_still_returns_409_without_writes(self):
        row = self.snapshot()
        side_effects = self.side_effect_counts()

        response = self.patch_action({
            "title": "Must not be saved",
            "expected_record_version": 999,
        })

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("version", str(response.data).lower())
        self.assert_unchanged(row, side_effects)

    def test_ordinary_metadata_patch_succeeds_without_lifecycle_side_effects(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="Matching RCA")
        due_at = timezone.now() + timezone.timedelta(days=2)
        side_effects = self.side_effect_counts()

        response = self.patch_action({
            "title": "Updated action",
            "description": "Updated description",
            "action_type": "preventive",
            "assigned_to": self.manager.pk,
            "due_at": due_at.isoformat(),
            "root_cause_analysis": rca.pk,
            "expected_record_version": 1,
        })

        self.assertEqual(response.status_code, 200, response.data)
        self.action.refresh_from_db()
        self.assertEqual(self.action.title, "Updated action")
        self.assertEqual(self.action.description, "Updated description")
        self.assertEqual(self.action.action_type, "preventive")
        self.assertEqual(self.action.assigned_to_id, self.manager.pk)
        self.assertEqual(self.action.root_cause_analysis_id, rca.pk)
        self.assertEqual(self.action.status, "planned")
        self.assertEqual(self.action.version, 2)
        self.assertEqual(self.side_effect_counts(), side_effects)

    def test_dedicated_transition_endpoint_still_applies_lifecycle(self):
        side_effects = self.side_effect_counts()

        response = self.client.post(
            f"{BASE}/actions/{self.action.pk}/start/",
            {"expected_record_version": 1}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.action.refresh_from_db()
        self.assertEqual(self.action.status, "in_progress")
        self.assertEqual(self.action.version, 2)
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="action_started").exists())
        self.assertTrue(AuditLog.objects.filter(
            entity_type="problem_management.problemaction",
            object_id=str(self.action.pk),
            action="problem_action_started",
        ).exists())
        created_history, created_audit = side_effects
        self.assertEqual(
            ProblemHistory.objects.filter(problem=self.problem).count(),
            created_history + 1)
        self.assertEqual(
            AuditLog.objects.filter(
                entity_type="problem_management.problemaction",
                object_id=str(self.action.pk),
            ).count(),
            created_audit + 1)
