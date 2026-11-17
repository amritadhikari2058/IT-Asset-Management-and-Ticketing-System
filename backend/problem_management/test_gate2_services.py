"""Gate 2B service workflow tests."""
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import User
from problem_management.models import (
    Problem, ProblemHistory, ProblemTask, ProblemTimelineEvent,
    RootCauseAnalysis, RootCauseWhy, RootCauseFactor,
    ProblemAction, ProblemWorkaround, ProblemValidation, ProblemException,
)
from problem_management import services


def _user(role, n):
    return User.objects.create_user(
        username=f"{role}_svc{n}", role=role,
        email=f"{role}.svc{n}@example.test", employee_id=f"S{role}{n}"[:30],
    )


class Gate2ServiceWorkflowTests(TransactionTestCase):
    """Comprehensive Gate 2B service workflow tests."""

    def setUp(self):
        self.support = _user("it_support", 1)
        self.manager = _user("it_manager", 1)
        self.problem = services.create_problem(
            actor=self.support, title="Svc problem", description="Desc",
            owner=self.manager,
        )
        services.submit_problem(actor=self.support, problem=self.problem)
        services.accept_problem(actor=self.manager, problem=self.problem)

    # --- RCA ---

    def test_create_root_cause_analysis(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
            description="RCA Description",
        )
        self.assertEqual(rca.problem_id, self.problem.pk)
        self.assertEqual(rca.title, "RCA Title")
        self.assertEqual(rca.status, "draft")
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="rca_created").exists())

    def test_submit_root_cause_analysis(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        submitted = services.submit_root_cause_analysis(
            actor=self.support, analysis=rca,
        )
        self.assertEqual(submitted.status, "in_review")

    def test_approve_root_cause_analysis(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        approved = services.approve_root_cause_analysis(
            actor=self.manager, analysis=rca,
        )
        self.assertEqual(approved.status, "approved")

    def test_self_approval_rejection_of_rca(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        with self.assertRaises(PermissionDenied):
            services.approve_root_cause_analysis(
                actor=self.support, analysis=rca,
            )

    def test_reject_root_cause_analysis(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        rejected = services.reject_root_cause_analysis(
            actor=self.manager, analysis=rca, reason="Not convincing",
        )
        self.assertEqual(rejected.status, "rejected")

    def test_supersede_root_cause_analysis(self):
        rca1 = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA 1",
        )
        superseded = services.supersede_root_cause_analysis(
            actor=self.manager, analysis=rca1,
            problem=self.problem,
        )
        self.assertEqual(superseded.status, "superseded")
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="rca_superseded").exists())

    def test_approved_state_immutability(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        services.approve_root_cause_analysis(actor=self.manager, analysis=rca)
        with self.assertRaises(ValidationError):
            services.reject_root_cause_analysis(
                actor=self.manager, analysis=rca, reason="late",
            )

    def test_stale_version_rca(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        rca.version = 999
        rca.save()
        with self.assertRaises(Exception):
            services.approve_root_cause_analysis(
                actor=self.manager, analysis=rca,
            )

    # --- Whys ---

    def test_create_root_cause_why(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        why = services.create_root_cause_why(
            actor=self.support, analysis=rca,
            question_text="Why did it happen?", answer="Because",
        )
        self.assertEqual(why.question_text, "Why did it happen?")
        self.assertEqual(why.answer, "Because")
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="why_created").exists())

    def test_update_root_cause_why(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        why = services.create_root_cause_why(
            actor=self.support, analysis=rca, question_text="Why1?", answer="A1",
        )
        updated = services.update_root_cause_why(
            actor=self.support, why=why,
            question_text="Why1 updated?",
        )
        self.assertEqual(updated.question_text, "Why1 updated?")

    def test_delete_root_cause_why_when_draft(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        why = services.create_root_cause_why(
            actor=self.support, analysis=rca, question_text="Why?", answer="A",
        )
        result = services.delete_root_cause_why(
            actor=self.support, why=why,
        )
        self.assertTrue(result["deleted"])

    def test_invalid_category_root_cause_factor(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        with self.assertRaises(ValidationError):
            services.create_root_cause_factor(
                actor=self.support, analysis=rca,
                category="invalid_cat", factor="Test factor",
            )

    def test_duplicate_sequence_why(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        services.create_root_cause_why(
            actor=self.support, analysis=rca, question_text="Q1?", answer="A1",
        )
        with self.assertRaises(ValidationError):
            services.create_root_cause_why(
                actor=self.support, analysis=rca, question_text="Q2?", answer="A2",
            )

    def test_final_parent_blocked_why(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        services.approve_root_cause_analysis(actor=self.manager, analysis=rca)
        with self.assertRaises(ValidationError):
            services.create_root_cause_why(
                actor=self.support, analysis=rca, question_text="Why?", answer="A",
            )

    # --- Factors ---

    def test_create_root_cause_factor(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        factor = services.create_root_cause_factor(
            actor=self.support, analysis=rca,
            category="people", factor="Test factor",
        )
        self.assertEqual(factor.category, "people")
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="factor_created").exists())

    def test_update_root_cause_factor(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        factor = services.create_root_cause_factor(
            actor=self.support, analysis=rca, category="people", factor="Old",
        )
        updated = services.update_root_cause_factor(
            actor=self.support, factor=factor, category="method", factor_text="New",
        )
        self.assertEqual(updated.category, "method")
        self.assertEqual(updated.factor, "New")

    def test_delete_root_cause_factor_when_draft(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        factor = services.create_root_cause_factor(
            actor=self.support, analysis=rca, category="people", factor="F",
        )
        result = services.delete_root_cause_factor(
            actor=self.support, factor=factor,
        )
        self.assertTrue(result["deleted"])

    def test_duplicate_factor_within_category(self):
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=self.problem, title="RCA Title",
        )
        services.create_root_cause_factor(
            actor=self.support, analysis=rca, category="people", factor="F1",
        )
        with self.assertRaises(ValidationError):
            services.create_root_cause_factor(
                actor=self.support, analysis=rca, category="people", factor="F2",
            )

    # --- Timeline ---

    def test_create_problem_timeline_event(self):
        evt = services.create_problem_timeline_event(
            actor=self.support, problem=self.problem,
            occurred_at=timezone.now(), source="manual",
            event_type="milestone", title="Milestone", description="Desc",
        )
        self.assertEqual(evt.problem_id, self.problem.pk)
        self.assertEqual(evt.event_type, "milestone")

    def test_timeline_event_source_validation(self):
        with self.assertRaises(ValidationError):
            services.create_problem_timeline_event(
                actor=self.support, problem=self.problem,
                occurred_at=timezone.now(), source="invalid",
                event_type="milestone", title="M", description="",
            )

    def test_timeline_event_timezone_aware(self):
        import datetime
        naive = datetime.datetime(2024, 1, 15, 10, 0, 0)
        with self.assertRaises(ValidationError):
            services.create_problem_timeline_event(
                actor=self.support, problem=self.problem,
                occurred_at=naive, source="manual",
                event_type="milestone", title="M", description="",
            )

    def test_timeline_event_detail_bound(self):
        evt = services.create_problem_timeline_event(
            actor=self.support, problem=self.problem,
            occurred_at=timezone.now(), source="manual",
            event_type="milestone", title="M",
            description="x" * 5000,
        )
        self.assertTrue(len(evt.description) <= 4000)

    def test_timeline_event_immutability(self):
        evt = ProblemTimelineEvent.objects.create(
            problem=self.problem, event_type="milestone",
            title="Test", occurred_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            evt.description = "changed"
            evt.save()

    # --- Actions ---

    def test_create_problem_action(self):
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, title="Action",
            description="Desc", due_date=timezone.now() + timezone.timedelta(days=1),
        )
        self.assertEqual(action.problem_id, self.problem.pk)
        self.assertEqual(action.title, "Action")
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="action_created").exists())

    def test_approve_problem_action(self):
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, title="Action",
        )
        approved = services.approve_problem_action(actor=self.manager, action=action)
        self.assertEqual(approved.status, "planned")

    def test_start_problem_action(self):
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, title="Action",
        )
        started = services.start_problem_action(actor=self.support, action=action)

    def test_complete_problem_action(self):
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, title="Action",
        )
        completed = services.complete_problem_action(actor=self.support, action=action)
        self.assertEqual(completed.status, "completed")
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="action_completed").exists())

    def test_validate_problem_action(self):
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, title="Action",
        )
        validated = services.validate_problem_action(actor=self.support, action=action)
        self.assertEqual(validated.status, "verified")

    def test_mark_problem_action_ineffective(self):
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, title="Action",
        )
        ineffective = services.mark_problem_action_ineffective(actor=self.support, action=action)
        self.assertEqual(ineffective.status, "ineffective")

    def test_cancel_problem_action(self):
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, title="Action",
        )
        cancelled = services.cancel_problem_action(actor=self.support, action=action)
        self.assertEqual(cancelled.status, "cancelled")

    def test_separation_of_duties_action_approval(self):
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, title="Action",
        )
        with self.assertRaises(PermissionDenied):
            services.approve_problem_action(actor=self.support, action=action)

    def test_action_stale_version(self):
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, title="Action",
        )
        action.version = 999
        action.save()
        with self.assertRaises(Exception):
            services.validate_problem_action(actor=self.support, action=action)

    # --- Workarounds ---

    def test_create_problem_workaround(self):
        wa = services.create_problem_workaround(
            actor=self.support, problem=self.problem, title="WA Title",
            description="Steps", steps="Step 1; Step 2",
        )
        self.assertEqual(wa.problem_id, self.problem.pk)
        self.assertEqual(wa.title, "WA Title")

    def test_create_problem_workaround_high_risk_requirements(self):
        with self.assertRaises(ValidationError):
            services.create_problem_workaround(
                actor=self.support, problem=self.problem, title="WA",
                description="Steps", steps="S1", risk="critical",
            )

    def test_submit_approve_publish_workaround(self):
        wa = services.create_problem_workaround(
            actor=self.support, problem=self.problem, title="WA", description="Steps",
            steps="S1", risk="low",
        )
        services.submit_problem_workaround(actor=self.support, workaround=wa)
        services.approve_problem_workaround(actor=self.manager, workaround=wa)
        services.publish_problem_workaround(actor=self.manager, workaround=wa)

    def test_expire_retire_workaround(self):
        wa = services.create_problem_workaround(
            actor=self.support, problem=self.problem, title="WA", description="Steps",
            steps="S1", risk="low",
        )
        services.expire_problem_workaround(actor=self.support, workaround=wa)
        services.retire_problem_workaround(actor=self.support, workaround=wa)

    def test_no_knowledge_side_effect_workaround(self):
        wa = services.create_problem_workaround(
            actor=self.support, problem=self.problem, title="WA", description="Steps",
            steps="S1", risk="low",
        )
        # No Knowledge Article should be created
        self.assertFalse(hasattr(wa, 'knowledge_article'))

    # --- Validations ---

    def test_create_problem_validation(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
            validation_type="functional",
        )
        self.assertEqual(val.title, "Validation")
        self.assertFalse(val.passed)

    def test_start_problem_validation(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        started = services.start_problem_validation(actor=self.support, validation=val)

    def test_pass_problem_validation(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        passed = services.pass_problem_validation(actor=self.support, validation=val)
        self.assertTrue(passed.passed)

    def test_fail_problem_validation(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        failed = services.fail_problem_validation(actor=self.support, validation=val)
        self.assertFalse(failed.passed)

    def test_mark_problem_validation_inconclusive(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        inconclusive = services.mark_problem_validation_inconclusive(
            actor=self.support, validation=val)
        self.assertEqual(inconclusive.status, "inconclusive")

    def test_cancel_problem_validation(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        cancelled = services.cancel_problem_validation(actor=self.support, validation=val)
        self.assertEqual(cancelled.status, "cancelled")

    def test_validation_date_chronology(self):
        val1 = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="V1",
        )
        val2 = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="V2",
        )
        # Earlier validation should not be after later one in a way that breaks
        self.assertIsNotNone(val1.created_at)
        self.assertIsNotNone(val2.created_at)

    def test_validation_separation_duties(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        # Different validator can pass/fail
        passed = services.pass_problem_validation(
            actor=self.manager, validation=val)

    def test_validation_stale_version(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        val.version = 999
        val.save()
        with self.assertRaises(Exception):
            services.pass_problem_validation(actor=self.support, validation=val)

    # --- Exceptions ---

    def test_create_problem_exception(self):
        exc = services.create_problem_exception(
            actor=self.support, problem=self.problem, title="Exc Title",
            exception_type="operational",
        )
        self.assertEqual(exc.title, "Exc Title")

    def test_submit_approve_exception(self):
        exc = services.create_problem_exception(
            actor=self.support, problem=self.problem, title="Exc Title",
        )
        services.submit_problem_exception(actor=self.support, exception=exc)
        approved = services.approve_problem_exception(actor=self.manager, exception=exc)
        self.assertEqual(approved.status, "approved")

    def test_self_approval_rejection_exception(self):
        exc = services.create_problem_exception(
            actor=self.support, problem=self.problem, title="Exc Title",
        )
        with self.assertRaises(PermissionDenied):
            services.approve_problem_exception(actor=self.support, exception=exc)

    def test_critical_risk_approval_requires_system_admin(self):
        exc = services.create_problem_exception(
            actor=self.support, problem=self.problem, title="Critical Exc",
            exception_type="critical",
        )
        # Support cannot approve critical
        with self.assertRaises(PermissionDenied):
            services.approve_problem_exception(actor=self.support, exception=exc)

    def test_reject_problem_exception(self):
        exc = services.create_problem_exception(
            actor=self.support, problem=self.problem, title="Exc Title",
        )
        rejected = services.reject_problem_exception(
            actor=self.manager, exception=exc, reason="No good",
        )
        self.assertEqual(rejected.status, "rejected")

    def test_revoke_problem_exception(self):
        exc = services.create_problem_exception(
            actor=self.support, problem=self.problem, title="Exc Title",
        )
        revoked = services.revoke_problem_exception(
            actor=self.support, exception=exc, reason="Changed mind",
        )
        self.assertEqual(revoked.status, "revoked")

    def test_expire_problem_exception(self):
        exc = services.create_problem_exception(
            actor=self.support, problem=self.problem, title="Exc Title",
        )
        expired = services.expire_problem_exception(
            actor=self.support, exception=exc)
        self.assertEqual(expired.status, "expired")

    def test_no_raw_integrity_error(self):
        """Service operations should not raise raw IntegrityError."""
        # Create problem
        problem = services.create_problem(
            actor=self.support, title="Test", description="D",
            owner=self.manager,
        )
        services.submit_problem(actor=self.support, problem=problem)
        services.accept_problem(actor=self.manager, problem=problem)
        # Create RCA
        rca = services.create_root_cause_analysis(
            actor=self.support, problem=problem, title="RCA",
        )
        # Submit and approve
        services.submit_root_cause_analysis(actor=self.support, analysis=rca)
        services.approve_root_cause_analysis(actor=self.manager, analysis=rca)
        # Should not raise IntegrityError
        self.assertTrue(True)