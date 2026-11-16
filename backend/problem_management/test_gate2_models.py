"""Gate 2 model tests for Problem Management.

Tests for: ProblemEvidence, RootCauseAnalysis, RootCauseWhy, RootCauseFactor,
ProblemTimelineEvent, ProblemAction, ProblemWorkaround, ProblemValidation,
ProblemException, evaluate_problem_readiness.
"""
from datetime import datetime

from django.test import TransactionTestCase

from problem_management.models import (
    ProblemEvidence, RootCauseAnalysis, RootCauseWhy, RootCauseFactor,
    ProblemTimelineEvent, ProblemAction, ProblemWorkaround,
    ProblemValidation, ProblemException, evaluate_problem_readiness,
    Problem, ProblemNumberSequence, ProblemTask,
)


class Gate2ModelTests(TransactionTestCase):
    """Focused model/constraint tests for Gate 2."""

    def test_problem_evidence_creation(self):
        problem = Problem.objects.create(
            title="Test problem for evidence",
            description="Test",
        )
        evidence = ProblemEvidence.objects.create(
            problem=problem,
            title="Test evidence",
            evidence_type="documentation",
        )
        self.assertEqual(str(evidence), f"{problem.id}: Test evidence")
        self.assertEqual(problem.evidence.count(), 1)

    def test_problem_evidence_with_file(self):
        problem = Problem.objects.create(
            title="Test problem for evidence",
            description="Test",
        )
        evidence = ProblemEvidence.objects.create(
            problem=problem,
            title="Test evidence with file",
            evidence_type="file",
        )
        # FileField is optional (null=True, blank=True)
        # Django's FileField stores None as the name when no file uploaded
        self.assertIsNone(evidence.file.name)

    def test_root_cause_analysis_creation(self):
        problem = Problem.objects.create(
            title="Test problem for RCA",
            description="Test",
        )
        rca = RootCauseAnalysis.objects.create(
            problem=problem,
            title="Test RCA",
            analysis_method="five_whys",
        )
        self.assertEqual(str(rca), f"{problem.id}: Test RCA")
        self.assertIn(rca, problem.root_cause_analyses.all())

    def test_root_cause_why_creation(self):
        problem = Problem.objects.create(
            title="Test problem for whys",
            description="Test",
        )
        rca = RootCauseAnalysis.objects.create(
            problem=problem,
            title="Test WHYs",
        )
        why1 = RootCauseWhy.objects.create(
            analysis=rca,
            question_number=1,
            question_text="Why did the incident occur?",
            answer="Because of a system failure.",
        )
        why2 = RootCauseWhy.objects.create(
            analysis=rca,
            question_number=2,
            question_text="Why did the system fail?",
            answer="Because of a database corruption.",
        )
        self.assertEqual(rca.whys.count(), 2)
        self.assertEqual(why1.question_number, 1)
        self.assertEqual(why2.question_number, 2)
        self.assertEqual(str(why1), "WHY 1: Because of a system failure.")

    def test_root_cause_factor_fishbone(self):
        problem = Problem.objects.create(
            title="Test problem for factors",
            description="Test",
        )
        rca = RootCauseAnalysis.objects.create(
            problem=problem,
            title="Test Fishbone",
        )
        factor1 = RootCauseFactor.objects.create(
            analysis=rca,
            category="people",
            factor="inadequate training",
        )
        factor2 = RootCauseFactor.objects.create(
            analysis=rca,
            category="method",
            factor="missing procedure",
        )
        self.assertEqual(rca.fishbone_factors.count(), 2)
        self.assertEqual(factor1.category, "people")
        self.assertEqual(factor2.category, "method")
        self.assertEqual(str(factor1), "People: inadequate training")

    def test_problem_timeline_event(self):
        problem = Problem.objects.create(
            title="Test problem for timeline",
            description="Test",
        )
        occurred = datetime(2024, 1, 15, 10, 0, 0)
        event = ProblemTimelineEvent.objects.create(
            problem=problem,
            event_type="milestone",
            title="Problem Created",
            description="Initial problem creation",
            occurred_at=occurred,
        )
        expected = f"{problem.id}: Milestone @ 2024-01-15 10:00"
        self.assertEqual(str(event), expected)
        self.assertIn(event, problem.timeline_events.all())

    def test_problem_timeline_event_different_types(self):
        problem = Problem.objects.create(
            title="Test problem for timeline types",
            description="Test",
        )
        ProblemTimelineEvent.objects.create(
            problem=problem,
            event_type="investigation_start",
            title="Investigation Started",
            occurred_at=datetime(2024, 1, 15, 10, 0, 0),
        )
        ProblemTimelineEvent.objects.create(
            problem=problem,
            event_type="root_cause_found",
            title="Root Cause Found",
            occurred_at=datetime(2024, 1, 20, 14, 30, 0),
        )
        ProblemTimelineEvent.objects.create(
            problem=problem,
            event_type="workaround_implemented",
            title="Workaround Implemented",
            occurred_at=datetime(2024, 1, 25, 9, 0, 0),
        )
        self.assertEqual(problem.timeline_events.count(), 3)

    def test_problem_action_corrective(self):
        problem = Problem.objects.create(
            title="Test problem for action",
            description="Test",
        )
        action = ProblemAction.objects.create(
            problem=problem,
            title="Corrective Action",
            action_type="corrective",
            description="Fix the root cause",
        )
        self.assertEqual(action.action_type, "corrective")
        self.assertEqual(action.status, "planned")
        self.assertEqual(str(action), f"{problem.id}: Corrective Action (planned)")

    def test_problem_action_preventive_with_status(self):
        problem = Problem.objects.create(
            title="Test problem for preventive action",
            description="Test",
        )
        action = ProblemAction.objects.create(
            problem=problem,
            title="Preventive Action",
            action_type="preventive",
            status="in_progress",
        )
        self.assertEqual(action.action_type, "preventive")
        self.assertEqual(action.status, "in_progress")

    def test_problem_workaround_creation(self):
        problem = Problem.objects.create(
            title="Test problem for workaround",
            description="Test",
        )
        workaround = ProblemWorkaround.objects.create(
            problem=problem,
            title="Temporary workaround",
            description="Use system reboot as temp fix",
            workaround_type="temporary",
        )
        self.assertEqual(workaround.workaround_type, "temporary")
        self.assertEqual(workaround.effectiveness_rating, 3)
        self.assertEqual(str(workaround), f"{problem.id}: Temporary workaround")

    def test_problem_workaround_with_ratings(self):
        problem = Problem.objects.create(
            title="Test problem for workaround ratings",
            description="Test",
        )
        workaround = ProblemWorkaround.objects.create(
            problem=problem,
            title="Workaround with rating 5",
            description="Highly effective",
            effectiveness_rating=5,
        )
        self.assertEqual(workaround.effectiveness_rating, 5)

    def test_problem_validation_creation(self):
        problem = Problem.objects.create(
            title="Test problem for validation",
            description="Test",
        )
        validation = ProblemValidation.objects.create(
            problem=problem,
            title="Functional validation",
            validation_type="functional",
        )
        self.assertEqual(validation.validation_type, "functional")
        self.assertFalse(validation.passed)
        self.assertEqual(str(validation), f"{problem.id}: Functional validation (failed)")

    def test_problem_validation_passed(self):
        problem = Problem.objects.create(
            title="Test problem for validation passed",
            description="Test",
        )
        validation = ProblemValidation.objects.create(
            problem=problem,
            title="Integration validation",
            validation_type="integration",
            passed=True,
        )
        self.assertTrue(validation.passed)
        self.assertEqual(str(validation), f"{problem.id}: Integration validation (passed)")

    def test_problem_exception_creation(self):
        problem = Problem.objects.create(
            title="Test problem for exception",
            description="Test",
        )
        exception = ProblemException.objects.create(
            problem=problem,
            title="Operational exception",
            exception_type="operational",
        )
        self.assertEqual(exception.exception_type, "operational")
        self.assertFalse(exception.granted_at)
        self.assertEqual(str(exception), f"{problem.id}: Operational exception")

    def test_evaluate_readiness_open_no_tasks(self):
        """Open problem with no tasks -> blocked."""
        problem = Problem.objects.create(
            title="Test problem readiness 2",
            description="Test",
            status="investigating",
        )
        problem.problem_number = "PRB-2024-000001"
        problem.save()
        ready, reason, blocking = evaluate_problem_readiness(problem)
        self.assertFalse(ready)
        self.assertIn("no_tasks", blocking)
        self.assertIn("Open problems must have at least one task", reason)

    def test_evaluate_readiness_open_no_evidence(self):
        """Open problem with tasks but no evidence -> blocked."""
        problem = Problem.objects.create(
            title="Test problem readiness 3",
            description="Test",
            status="investigating",
        )
        problem.problem_number = "PRB-2024-000001"
        # Create a task so the "no_tasks" check passes
        ProblemTask.objects.create(
            problem=problem,
            title="Investigation task",
            task_type="investigation",
            status="not_started",
        )
        ready, reason, blocking = evaluate_problem_readiness(problem)
        self.assertFalse(ready)
        self.assertIn("no_evidence", blocking)
        self.assertIn("Open problems must have at least one evidence record", reason)

    def test_evaluate_readiness_investigating_no_root_cause_date(self):
        """Investigating problem without root cause date -> blocked."""
        problem = Problem.objects.create(
            title="Test problem readiness 4",
            description="Test",
            status="investigating",
        )
        problem.problem_number = "PRB-2024-000001"
        # Create a task so "no_tasks" check passes
        ProblemTask.objects.create(
            problem=problem,
            title="Investigation task",
            task_type="investigation",
            status="not_started",
        )
        # Also create evidence so the evidence check passes,
        # allowing the status-specific check to be evaluated
        ProblemEvidence.objects.create(
            problem=problem,
            title="Temporary evidence",
        )
        problem.root_cause_identified_at = None
        problem.save()
        ready, reason, blocking = evaluate_problem_readiness(problem)
        self.assertFalse(ready)
        self.assertIn("root_cause_not_identified", blocking)

    def test_evaluate_readiness_known_error_no_date(self):
        """Known error problem without date -> blocked."""
        problem = Problem.objects.create(
            title="Test problem readiness 7",
            description="Test",
            status="known_error",
        )
        problem.problem_number = "PRB-2024-000001"
        ProblemTask.objects.create(
            problem=problem,
            title="Task for known error test",
            task_type="investigation",
            status="not_started",
        )
        # Create evidence so the evidence check passes
        ProblemEvidence.objects.create(
            problem=problem,
            title="Temporary evidence",
        )
        problem.known_error_at = None
        problem.save()
        ready, reason, blocking = evaluate_problem_readiness(problem)
        self.assertFalse(ready)
        self.assertIn("known_error_date_missing", blocking)

    def test_evaluate_readiness_validation_no_passed(self):
        """Validation problem without passed validations -> blocked."""
        problem = Problem.objects.create(
            title="Test problem readiness 6",
            description="Test",
            status="validation",
        )
        problem.problem_number = "PRB-2024-000001"
        ProblemTask.objects.create(
            problem=problem,
            title="Validation task",
            task_type="validation",
            status="not_started",
        )
        # Create evidence so the evidence check passes
        ProblemEvidence.objects.create(
            problem=problem,
            title="Temporary evidence",
        )
        ready, reason, blocking = evaluate_problem_readiness(problem)
        self.assertFalse(ready)
        self.assertIn("no_validation_passed", blocking)

    def test_evaluate_readiness_workaround_no_workarounds(self):
        """Workaround available problem without workarounds -> blocked."""
        problem = Problem.objects.create(
            title="Test problem readiness 5",
            description="Test",
            status="workaround_available",
        )
        problem.problem_number = "PRB-2024-000001"
        ProblemTask.objects.create(
            problem=problem,
            title="Workaround task",
            task_type="workaround",
            status="not_started",
        )
        # Create evidence so the evidence check passes
        ProblemEvidence.objects.create(
            problem=problem,
            title="Temporary evidence",
        )
        ready, reason, blocking = evaluate_problem_readiness(problem)
        self.assertFalse(ready)
        self.assertIn("no_workaround", blocking)

    def test_evaluate_readiness_all_good(self):
        """Problem with all requirements met -> ready."""
        problem = Problem.objects.create(
            title="Test problem readiness 8",
            description="Test",
            status="investigating",
        )
        problem.problem_number = "PRB-2024-000001"
        ProblemTask.objects.create(
            problem=problem,
            title="Investigation task",
            task_type="investigation",
            status="not_started",
        )
        # Create evidence so all checks pass
        ProblemEvidence.objects.create(
            problem=problem,
            title="Root cause analysis evidence",
        )
        problem.root_cause_identified_at = "2024-01-20T14:30:00Z"
        problem.save()
        ready, reason, blocking = evaluate_problem_readiness(problem)
        self.assertTrue(ready)
        self.assertEqual(blocking, [])

    def test_model_ordering(self):
        """Verify Meta ordering on all Gate 2 models."""
        problem = Problem.objects.create(
            title="Test problem ordering",
            description="Test",
        )
        models_to_check = {
            ProblemEvidence: ["-created_at"],
            RootCauseAnalysis: ["-created_at"],
            RootCauseWhy: ["question_number"],
            RootCauseFactor: ["factor"],
            ProblemTimelineEvent: ["occurred_at"],
            ProblemAction: ["-created_at"],
            ProblemWorkaround: ["-created_at"],
            ProblemValidation: ["-created_at"],
            ProblemException: ["-created_at"],
        }
        for model_class, expected_ordering in models_to_check.items():
            with self.subTest(model=model_class.__name__):
                meta_ordering = model_class._meta.ordering
                self.assertEqual(meta_ordering, expected_ordering)

    def test_problem_evidence_related_name(self):
        problem = Problem.objects.create(
            title="Test problem EN",
            description="Test",
        )
        self.assertTrue(hasattr(problem, "evidence"))

    def test_root_cause_analysis_related_name(self):
        problem = Problem.objects.create(
            title="Test problem RCA EN",
            description="Test",
        )
        self.assertTrue(hasattr(problem, "root_cause_analyses"))

    def test_problem_timeline_events_related_name(self):
        problem = Problem.objects.create(
            title="Test problem timeline EN",
            description="Test",
        )
        self.assertTrue(hasattr(problem, "timeline_events"))

    def test_problem_actions_related_name(self):
        problem = Problem.objects.create(
            title="Test problem actions EN",
            description="Test",
        )
        self.assertTrue(hasattr(problem, "actions"))

    def test_problem_workarounds_related_name(self):
        problem = Problem.objects.create(
            title="Test problem workarounds EN",
            description="Test",
        )
        self.assertTrue(hasattr(problem, "workarounds"))

    def test_problem_validations_related_name(self):
        problem = Problem.objects.create(
            title="Test problem validations EN",
            description="Test",
        )
        self.assertTrue(hasattr(problem, "validations"))

    def test_problem_exceptions_related_name(self):
        problem = Problem.objects.create(
            title="Test problem exceptions EN",
            description="Test",
        )
        self.assertTrue(hasattr(problem, "exceptions"))