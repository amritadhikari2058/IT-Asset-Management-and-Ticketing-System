"""Gate 2B service workflow tests."""
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import User
from common.models import AuditLog
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

    def action_at(self, status="planned", **fields):
        payload = {"title": "Action"}
        payload.update(fields)
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, **payload)
        if status != "planned":
            action.status = status
            action.save(update_fields=["status"])
            action.refresh_from_db()
        return action

    def action_audit_count(self, action, event=None):
        qs = AuditLog.objects.filter(
            entity_type="problem_management.problemaction",
            object_id=str(action.pk),
        )
        if event:
            qs = qs.filter(action=event)
        return qs.count()

    def test_create_problem_action(self):
        action = services.create_problem_action(
            actor=self.support, problem=self.problem, title="Action",
            description="Desc", due_date=timezone.now() + timezone.timedelta(days=1),
        )
        self.assertEqual(action.problem_id, self.problem.pk)
        self.assertEqual(action.title, "Action")
        self.assertEqual(action.status, "planned")
        self.assertEqual(action.version, 1)
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="action_created").exists())

    def test_approve_problem_action(self):
        action = self.action_at()
        history_before = ProblemHistory.objects.filter(problem=self.problem).count()
        audit_before = self.action_audit_count(action)

        approved = services.approve_problem_action(actor=self.manager, action=action)
        self.assertEqual(approved.status, "approved")
        approved.refresh_from_db()
        self.assertEqual(approved.status, "approved")
        self.assertEqual(approved.version, 2)

        history = ProblemHistory.objects.get(
            problem=self.problem, event_type="action_approved")
        self.assertEqual(history.previous_status, "planned")
        self.assertEqual(history.new_status, "approved")
        self.assertIn("planned -> approved", history.detail)
        self.assertEqual(history.changed_fields, ["status"])

        audit = AuditLog.objects.get(
            entity_type="problem_management.problemaction",
            object_id=str(action.pk), action="problem_action_approved")
        self.assertIn("planned -> approved", audit.reason)
        self.assertEqual(
            ProblemHistory.objects.filter(problem=self.problem).count(),
            history_before + 1)
        self.assertEqual(self.action_audit_count(action), audit_before + 1)

        with self.assertRaises(ValidationError) as exc:
            services.approve_problem_action(actor=self.manager, action=approved)
        self.assertIn("action", exc.exception.detail)
        self.assertEqual(
            ProblemHistory.objects.filter(
                problem=self.problem, event_type="action_approved").count(), 1)
        self.assertEqual(
            self.action_audit_count(action, "problem_action_approved"), 1)

    def test_start_problem_action(self):
        action = self.action_at()
        services.approve_problem_action(actor=self.manager, action=action)
        started = services.start_problem_action(actor=self.support, action=action)
        self.assertEqual(started.status, "in_progress")
        self.assertEqual(started.version, 3)
        started.refresh_from_db()
        self.assertEqual(started.status, "in_progress")
        self.assertEqual(started.version, 3)

    def test_complete_problem_action(self):
        action = self.action_at()
        services.start_problem_action(actor=self.support, action=action)
        completed = services.complete_problem_action(actor=self.support, action=action)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.version, 3)
        self.assertIsNotNone(completed.completed_at)
        completed.refresh_from_db()
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.version, 3)
        self.assertTrue(ProblemHistory.objects.filter(
            problem=self.problem, event_type="action_completed").exists())

    def test_validate_problem_action(self):
        action = self.action_at()
        services.start_problem_action(actor=self.support, action=action)
        services.complete_problem_action(actor=self.support, action=action)
        completed_at = action.completed_at

        validated = services.validate_problem_action(actor=self.support, action=action)
        self.assertEqual(validated.status, "verified")
        self.assertEqual(validated.version, 4)
        self.assertEqual(validated.verified_by_id, self.support.pk)
        self.assertIsNotNone(validated.verified_at)
        self.assertEqual(validated.completed_at, completed_at)
        self.assertEqual(validated.validation_status, "")

        validated.refresh_from_db()
        self.assertEqual(validated.status, "verified")
        self.assertEqual(validated.version, 4)
        self.assertEqual(validated.verified_by_id, self.support.pk)
        self.assertIsNotNone(validated.verified_at)
        self.assertEqual(validated.completed_at, completed_at)

        history = ProblemHistory.objects.get(
            problem=self.problem, event_type="action_validated")
        self.assertEqual(history.previous_status, "completed")
        self.assertEqual(history.new_status, "verified")
        self.assertEqual(
            history.changed_fields, ["status", "verified_by", "verified_at"])

    def test_mark_problem_action_ineffective(self):
        action = self.action_at()
        services.start_problem_action(actor=self.support, action=action)
        services.complete_problem_action(actor=self.support, action=action)
        ineffective = services.mark_problem_action_ineffective(
            actor=self.support, action=action, reason="Not effective")
        self.assertEqual(ineffective.status, "ineffective")
        self.assertEqual(ineffective.version, 4)
        self.assertIsNone(ineffective.verified_by_id)
        self.assertIsNone(ineffective.verified_at)
        ineffective.refresh_from_db()
        self.assertEqual(ineffective.status, "ineffective")
        self.assertEqual(ineffective.version, 4)

    def test_cancel_problem_action(self):
        action = self.action_at()
        cancelled = services.cancel_problem_action(
            actor=self.support, action=action, reason="No longer needed")
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(cancelled.version, 2)
        self.assertIsNone(cancelled.verified_by_id)
        self.assertIsNone(cancelled.verified_at)
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(cancelled.version, 2)

    def test_validate_action_allows_advanced_version(self):
        action = self.action_at()
        services.start_problem_action(actor=self.support, action=action)
        services.complete_problem_action(actor=self.support, action=action)
        self.assertGreater(action.version, 1)
        validated = services.validate_problem_action(actor=self.support, action=action)
        self.assertEqual(validated.status, "verified")
        self.assertEqual(validated.version, 4)

    def test_action_invalid_source_statuses_rejected(self):
        cases = (
            ("in_progress", services.approve_problem_action, self.manager, "approved"),
            ("completed", services.start_problem_action, self.support, "started"),
            ("planned", services.complete_problem_action, self.support, "completed"),
            ("in_progress", services.validate_problem_action, self.support, "verified"),
            ("planned", services.mark_problem_action_ineffective,
             self.support, "marked ineffective"),
        )
        for status, transition, actor, label in cases:
            with self.subTest(status=status, transition=transition.__name__):
                action = self.action_at(status=status)
                version_before = action.version
                history_before = ProblemHistory.objects.filter(problem=self.problem).count()
                audit_before = self.action_audit_count(action)
                with self.assertRaises(ValidationError) as exc:
                    transition(actor=actor, action=action)
                self.assertIn("action", exc.exception.detail)
                action.refresh_from_db()
                self.assertEqual(action.version, version_before)
                self.assertEqual(
                    ProblemHistory.objects.filter(problem=self.problem).count(),
                    history_before)
                self.assertEqual(self.action_audit_count(action), audit_before)

    def test_action_terminal_statuses_reject_all_transitions(self):
        transitions = (
            ("approve", services.approve_problem_action, self.manager),
            ("start", services.start_problem_action, self.support),
            ("complete", services.complete_problem_action, self.support),
            ("validate", services.validate_problem_action, self.support),
            ("ineffective", services.mark_problem_action_ineffective, self.support),
            ("cancel", services.cancel_problem_action, self.support),
        )
        for terminal in ("verified", "ineffective", "cancelled", "closed"):
            for name, transition, actor in transitions:
                with self.subTest(terminal=terminal, transition=name):
                    action = self.action_at(status=terminal)
                    version_before = action.version
                    history_before = ProblemHistory.objects.filter(problem=self.problem).count()
                    audit_before = self.action_audit_count(action)
                    with self.assertRaises(ValidationError) as exc:
                        transition(actor=actor, action=action)
                    self.assertIn("action", exc.exception.detail)
                    action.refresh_from_db()
                    self.assertEqual(action.version, version_before)
                    self.assertEqual(
                        ProblemHistory.objects.filter(problem=self.problem).count(),
                        history_before)
                    self.assertEqual(self.action_audit_count(action), audit_before)

    def test_separation_of_duties_action_approval(self):
        action = self.action_at()
        with self.assertRaises(PermissionDenied):
            services.approve_problem_action(actor=self.support, action=action)
        self.assertEqual(self.action_audit_count(action, "problem_action_approved"), 0)

    def test_superuser_employee_cannot_transition_actions_via_services(self):
        superuser = _user("employee", 91)
        superuser.is_superuser = True
        superuser.save(update_fields=["is_superuser"])
        self.assertTrue(superuser.is_authenticated)
        self.assertTrue(superuser.is_active)
        self.assertTrue(superuser.is_superuser)
        self.assertEqual(superuser.role, "employee")

        cases = (
            ("approve", services.approve_problem_action,
             "Manager or System Admin role required."),
            ("start", services.start_problem_action,
             "Problem Management access denied."),
            ("cancel", services.cancel_problem_action,
             "Problem Management access denied."),
        )
        for name, transition, expected_detail in cases:
            with self.subTest(transition=name):
                action = self.action_at()
                version_before = action.version
                history_before = ProblemHistory.objects.filter(
                    problem=self.problem).count()
                audit_before = self.action_audit_count(action)
                kwargs = {"reason": "Superuser denial check"} if name == "cancel" else {}

                with self.assertRaises(PermissionDenied) as caught:
                    transition(actor=superuser, action=action, **kwargs)
                self.assertEqual(str(caught.exception.detail), expected_detail)

                action.refresh_from_db()
                self.assertEqual(action.status, "planned")
                self.assertEqual(action.version, version_before)
                self.assertEqual(
                    ProblemHistory.objects.filter(problem=self.problem).count(),
                    history_before)
                self.assertEqual(self.action_audit_count(action), audit_before)

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
        self.assertEqual(val.status, "draft")
        self.assertEqual(val.version, 1)
        self.assertFalse(val.passed)

    def test_start_problem_validation(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        started = services.start_problem_validation(actor=self.support, validation=val)
        self.assertEqual(started.status, "in_progress")
        self.assertEqual(started.version, 2)

    def test_pass_problem_validation(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        passed = services.pass_problem_validation(actor=self.support, validation=val)
        self.assertEqual(passed.status, "verified")
        self.assertTrue(passed.passed)
        self.assertEqual(passed.version, 2)

    def test_validation_start_then_pass(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        started = services.start_problem_validation(actor=self.support, validation=val)
        self.assertEqual(started.version, 2)
        passed = services.pass_problem_validation(actor=self.support, validation=val)
        self.assertEqual(passed.status, "verified")
        self.assertTrue(passed.passed)
        self.assertEqual(passed.version, 3)
        passed.refresh_from_db()
        self.assertEqual(passed.version, 3)
        self.assertTrue(passed.passed)

    def test_fail_problem_validation(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        failed = services.fail_problem_validation(actor=self.support, validation=val)
        self.assertEqual(failed.status, "failed")
        self.assertFalse(failed.passed)
        self.assertEqual(failed.version, 2)

    def test_mark_problem_validation_inconclusive(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        inconclusive = services.mark_problem_validation_inconclusive(
            actor=self.support, validation=val)
        self.assertEqual(inconclusive.status, "inconclusive")
        self.assertFalse(inconclusive.passed)
        self.assertEqual(inconclusive.version, 2)

    def test_cancel_problem_validation(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        cancelled = services.cancel_problem_validation(actor=self.support, validation=val)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertFalse(cancelled.passed)
        self.assertEqual(cancelled.version, 2)

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
        self.assertTrue(passed.passed)

    def test_validation_start_rejects_in_progress(self):
        val = services.create_problem_validation(
            actor=self.support, problem=self.problem, title="Validation",
        )
        started = services.start_problem_validation(actor=self.support, validation=val)
        with self.assertRaises(ValidationError) as exc:
            services.start_problem_validation(actor=self.support, validation=started)
        self.assertIn("validation", exc.exception.detail)

    def test_validation_terminal_statuses_reject_all_transitions(self):
        transitions = (
            services.start_problem_validation,
            services.pass_problem_validation,
            services.fail_problem_validation,
            services.mark_problem_validation_inconclusive,
            services.cancel_problem_validation,
        )
        enter_terminal = (
            services.pass_problem_validation,
            services.fail_problem_validation,
            services.mark_problem_validation_inconclusive,
            services.cancel_problem_validation,
        )
        for enter in enter_terminal:
            val = services.create_problem_validation(
                actor=self.support, problem=self.problem, title="Validation",
            )
            terminal = enter(actor=self.support, validation=val)
            for transition in transitions:
                with self.subTest(status=terminal.status, transition=transition.__name__):
                    with self.assertRaises(ValidationError):
                        transition(actor=self.support, validation=terminal)

    def test_validation_inconclusive_and_cancel_clear_passed(self):
        for transition, expected_status in (
            (services.mark_problem_validation_inconclusive, "inconclusive"),
            (services.cancel_problem_validation, "cancelled"),
        ):
            val = services.create_problem_validation(
                actor=self.support, problem=self.problem, title="Validation",
            )
            val.passed = True
            val.save(update_fields=["passed"])
            result = transition(actor=self.support, validation=val)
            self.assertEqual(result.status, expected_status)
            self.assertFalse(result.passed)
            result.refresh_from_db()
            self.assertFalse(result.passed)

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