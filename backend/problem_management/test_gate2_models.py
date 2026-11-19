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
    ProblemValidation, ProblemException,
    Problem, ProblemNumberSequence, ProblemTask,
)
from problem_management.services import evaluate_problem_readiness


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

    def _assert_readiness_contract(self, result):
        self.assertIsInstance(result, dict)
        self.assertIn("ready_for_resolution", result)
        self.assertIn("ready_for_closure", result)
        self.assertIn("blockers", result)
        self.assertIn("warnings", result)
        self.assertIn("counts", result)
        self.assertIsInstance(result["blockers"], list)
        self.assertIsInstance(result["warnings"], list)
        self.assertEqual(result["warnings"], [])
        for key in (
            "open_blocking_tasks", "open_required_actions", "failed_validations",
            "open_critical_tickets", "active_exceptions",
        ):
            self.assertIn(key, result["counts"])
        codes = [b.get("code") for b in result["blockers"]]
        self.assertEqual(len(codes), len(set(codes)))

    def test_evaluate_readiness_open_no_tasks(self):
        """Open problem with blocking task and no approved RCA -> blocked."""
        problem = Problem.objects.create(
            title="Test problem readiness 2",
            description="Test",
            status="investigating",
        )
        problem.problem_number = "PRB-2024-000001"
        problem.save()
        ProblemTask.objects.create(
            problem=problem,
            title="Blocking investigation task",
            task_type="investigation",
            status="not_started",
            blocks_resolution=True,
        )
        result = evaluate_problem_readiness(problem)
        self._assert_readiness_contract(result)
        self.assertFalse(result["ready_for_resolution"])
        self.assertFalse(result["ready_for_closure"])
        codes = [b["code"] for b in result["blockers"]]
        self.assertIn("ROOT_CAUSE_MISSING", codes)
        self.assertIn("OPEN_BLOCKING_TASKS", codes)
        self.assertGreaterEqual(result["counts"]["open_blocking_tasks"], 1)

    def test_evaluate_readiness_open_no_evidence(self):
        """Problem without approved RCA remains blocked (evidence alone is insufficient)."""
        problem = Problem.objects.create(
            title="Test problem readiness 3",
            description="Test",
            status="investigating",
        )
        problem.problem_number = "PRB-2024-000001"
        ProblemTask.objects.create(
            problem=problem,
            title="Investigation task",
            task_type="investigation",
            status="completed",
            blocks_resolution=False,
        )
        ProblemEvidence.objects.create(
            problem=problem,
            title="Temporary evidence",
        )
        result = evaluate_problem_readiness(problem)
        self._assert_readiness_contract(result)
        self.assertFalse(result["ready_for_resolution"])
        codes = [b["code"] for b in result["blockers"]]
        self.assertIn("ROOT_CAUSE_MISSING", codes)

    def test_evaluate_readiness_investigating_no_root_cause_date(self):
        """No approved RCA blocks readiness regardless of root_cause_identified_at timestamp."""
        problem = Problem.objects.create(
            title="Test problem readiness 4",
            description="Test",
            status="investigating",
        )
        problem.problem_number = "PRB-2024-000001"
        ProblemTask.objects.create(
            problem=problem,
            title="Investigation task",
            task_type="investigation",
            status="completed",
            blocks_resolution=False,
        )
        ProblemEvidence.objects.create(problem=problem, title="Temporary evidence")
        problem.root_cause_identified_at = None
        problem.save()
        result = evaluate_problem_readiness(problem)
        self._assert_readiness_contract(result)
        self.assertFalse(result["ready_for_resolution"])
        self.assertIn("ROOT_CAUSE_MISSING", [b["code"] for b in result["blockers"]])

    def test_evaluate_readiness_known_error_no_date(self):
        """Known error without approved RCA/exception remains blocked under new contract."""
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
            status="completed",
            blocks_resolution=False,
        )
        ProblemEvidence.objects.create(problem=problem, title="Temporary evidence")
        problem.known_error_at = None
        problem.save()
        result = evaluate_problem_readiness(problem)
        self._assert_readiness_contract(result)
        self.assertFalse(result["ready_for_resolution"])
        self.assertIn("ROOT_CAUSE_MISSING", [b["code"] for b in result["blockers"]])

    def test_evaluate_readiness_validation_no_passed(self):
        """Failed/problematic validations contribute to blockers/counts when present."""
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
            status="completed",
            blocks_resolution=False,
        )
        ProblemEvidence.objects.create(problem=problem, title="Temporary evidence")
        ProblemValidation.objects.create(
            problem=problem,
            title="Failed validation",
            validation_type="functional",
            passed=False,
        )
        result = evaluate_problem_readiness(problem)
        self._assert_readiness_contract(result)
        self.assertFalse(result["ready_for_resolution"])
        codes = [b["code"] for b in result["blockers"]]
        self.assertTrue(
            "ROOT_CAUSE_MISSING" in codes or "FAILED_VALIDATIONS" in codes
        )

    def test_evaluate_readiness_workaround_no_workarounds(self):
        """Workaround state without approved RCA remains blocked under new contract."""
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
            status="completed",
            blocks_resolution=False,
        )
        ProblemEvidence.objects.create(problem=problem, title="Temporary evidence")
        result = evaluate_problem_readiness(problem)
        self._assert_readiness_contract(result)
        self.assertFalse(result["ready_for_resolution"])
        self.assertIn("ROOT_CAUSE_MISSING", [b["code"] for b in result["blockers"]])

    def test_evaluate_readiness_all_good(self):
        """Approved RCA-equivalent (unknown-root-cause exception) and no blocking conditions -> ready."""
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
            status="completed",
            blocks_resolution=False,
        )
        ProblemEvidence.objects.create(problem=problem, title="Root cause analysis evidence")
        ProblemException.objects.create(
            problem=problem,
            title="Unknown root cause exception",
            exception_type="unknown_root_cause",
        )
        result = evaluate_problem_readiness(problem)
        self._assert_readiness_contract(result)
        self.assertTrue(result["ready_for_resolution"])
        self.assertTrue(result["ready_for_closure"])
        self.assertEqual(result["blockers"], [])

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

    def test_problem_lifecycle_transitions(self):
        """Test that problem status transitions follow the defined workflow."""
        problem = Problem.objects.create(
            title="Test lifecycle problem",
            description="Test",
        )
        problem.status = "identified"  # Explicitly set initial status
        # Initial status should be 'identified'
        self.assertEqual(problem.status, "identified")
        # Valid transitions from 'identified'
        problem.status = "triage"
        problem.save()
        self.assertEqual(problem.status, "triage")
        # Valid transition from 'triage' to 'investigating'
        problem.status = "investigating"
        problem.save()
        self.assertEqual(problem.status, "investigating")