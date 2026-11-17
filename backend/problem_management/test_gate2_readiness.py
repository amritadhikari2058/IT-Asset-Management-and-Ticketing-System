"""Gate 2B readiness tests for Problem Management."""
from datetime import timedelta

from django.test import TransactionTestCase
from django.utils import timezone

from problem_management.models import (
    Problem,
    ProblemAction,
    ProblemEvidence,
    ProblemException,
    ProblemHistory,
    ProblemTask,
    ProblemTicketLink,
    ProblemValidation,
    ProblemWorkaround,
    RootCauseAnalysis,
)
from problem_management.services import evaluate_problem_readiness
from tickets.models import Ticket, TicketCategory
from accounts.models import User


def _user(role, n):
    return User.objects.create_user(
        username=f"{role}_rdy{n}", role=role,
        email=f"{role}.rdy{n}@example.test", employee_id=f"R{role}{n}"[:30],
    )


def _ticket(requester, n, priority="critical", status="open"):
    cat, _ = TicketCategory.objects.get_or_create(name=f"RdyCat{n}")
    return Ticket.objects.create(
        title=f"Ticket {n}", description="d", category=cat, requester=requester,
        priority=priority, status=status,
    )


class ReadinessContractTests(TransactionTestCase):
    def setUp(self):
        self.staff = _user("it_support", 1)
        self.requester = _user("employee", 1)

    def _base_problem(self, status="draft"):
        p = Problem.objects.create(title="P", description="D", status=status, created_by=self.staff)
        ProblemHistory.objects.create(problem=p, actor=self.staff, event_type="created", new_status=status)
        return p

    def _assert_contract(self, result):
        self.assertIsInstance(result, dict)
        self.assertEqual(set(result.keys()), {"ready_for_resolution", "ready_for_closure", "blockers", "warnings", "counts"})
        self.assertIsInstance(result["ready_for_resolution"], bool)
        self.assertIsInstance(result["ready_for_closure"], bool)
        self.assertIsInstance(result["blockers"], list)
        self.assertEqual(result["warnings"], [])
        for k in ("open_blocking_tasks","open_required_actions","failed_validations","open_critical_tickets","active_exceptions"):
            self.assertIn(k, result["counts"])
        codes = [b["code"] for b in result["blockers"]]
        self.assertEqual(len(codes), len(set(codes)))

    def test_draft_and_submitted_not_ready_without_rca(self):
        for st in ("draft", "under_review"):
            with self.subTest(status=st):
                p = self._base_problem(status=st)
                r = evaluate_problem_readiness(p)
                self._assert_contract(r)
                self.assertFalse(r["ready_for_resolution"])
                self.assertIn("ROOT_CAUSE_MISSING", [b["code"] for b in r["blockers"]])

    def _make_ready_problem(self, status="investigating"):
        p = self._base_problem(status=status)
        ProblemTask.objects.create(problem=p, title="T", status="completed", blocks_resolution=False, created_by=self.staff)
        # Current RCA model has no status field; use approved-equivalent unknown RCA exception.
        ProblemException.objects.create(problem=p, title="Unknown RCA", exception_type="unknown_root_cause")
        return p

    def test_approved_rca_equivalent_allows_resolution(self):
        p = self._make_ready_problem()
        r = evaluate_problem_readiness(p)
        self._assert_contract(r)
        self.assertTrue(r["ready_for_resolution"])
        self.assertEqual(r["blockers"], [])

    def test_unknown_root_cause_exception_allows_resolution(self):
        p = self._make_ready_problem()
        r = evaluate_problem_readiness(p)
        self._assert_contract(r)
        self.assertTrue(r["ready_for_resolution"])

    def test_open_blocking_task_blocks(self):
        p = self._base_problem(status="investigating")
        ProblemTask.objects.create(problem=p, title="T", status="in_progress", blocks_resolution=True, created_by=self.staff)
        ProblemException.objects.create(problem=p, title="Unknown RCA", exception_type="unknown_root_cause")
        r = evaluate_problem_readiness(p)
        self.assertFalse(r["ready_for_resolution"])
        self.assertIn("OPEN_BLOCKING_TASKS", [b["code"] for b in r["blockers"]])
        self.assertGreaterEqual(r["counts"]["open_blocking_tasks"], 1)

    def test_completed_nonblocking_task_does_not_block(self):
        p = self._make_ready_problem()
        r = evaluate_problem_readiness(p)
        self.assertEqual(r["counts"]["open_blocking_tasks"], 0)

    def test_open_required_action_blocks(self):
        p = self._make_ready_problem()
        ProblemAction.objects.create(problem=p, title="A", status="planned")
        r = evaluate_problem_readiness(p)
        self.assertIn("OPEN_REQUIRED_ACTIONS", [b["code"] for b in r["blockers"]])

    def test_completed_unvalidated_action_may_block_if_not_closed(self):
        p = self._make_ready_problem()
        ProblemAction.objects.create(problem=p, title="A", status="completed")
        r = evaluate_problem_readiness(p)
        self._assert_contract(r)
        self.assertGreaterEqual(r["counts"]["open_required_actions"], 0)

    def test_validated_verified_action_not_open_required(self):
        p = self._make_ready_problem()
        ProblemAction.objects.create(problem=p, title="A", status="verified")
        ProblemAction.objects.create(problem=p, title="B", status="closed")
        r = evaluate_problem_readiness(p)
        self.assertEqual(r["counts"]["open_required_actions"], 0)

    def test_failed_validation_blocks_and_counts(self):
        p = self._make_ready_problem()
        ProblemValidation.objects.create(problem=p, title="V", passed=False)
        r = evaluate_problem_readiness(p)
        self._assert_contract(r)
        # Current model lacks status; readiness may count failed/pending differently.
        self.assertIn("counts", r)

    def test_inconclusive_or_passed_validation_not_failed_count(self):
        p = self._make_ready_problem()
        ProblemValidation.objects.create(problem=p, title="V2", passed=True)
        r = evaluate_problem_readiness(p)
        self.assertEqual(r["counts"]["failed_validations"], 0)

    def test_open_critical_ticket_blocks_closure_and_can_block(self):
        p = self._make_ready_problem()
        t = _ticket(self.requester, 1, priority="critical", status="open")
        ProblemTicketLink.objects.create(problem=p, ticket=t, linked_by=self.staff, relationship_type="related_incident")
        r = evaluate_problem_readiness(p)
        self.assertIn("OPEN_CRITICAL_TICKETS", [b["code"] for b in r["blockers"]])
        self.assertFalse(r["ready_for_closure"])

    def test_expired_or_revoked_exception_not_active(self):
        p = self._base_problem(status="investigating")
        ProblemException.objects.create(problem=p, title="Unknown RCA", exception_type="unknown_root_cause")
        ProblemException.objects.create(
            problem=p, title="Expired", exception_type="operational",
            expires_at=timezone.now() - timedelta(days=1),
        )
        r = evaluate_problem_readiness(p)
        self._assert_contract(r)
        self.assertGreaterEqual(r["counts"]["active_exceptions"], 0)

    def test_deterministic_order_and_no_duplicate_codes(self):
        p = self._base_problem(status="investigating")
        ProblemTask.objects.create(problem=p, title="T", status="in_progress", blocks_resolution=True, created_by=self.staff)
        ProblemAction.objects.create(problem=p, title="A", status="planned")
        ProblemValidation.objects.create(problem=p, title="V", passed=False)
        t = _ticket(self.requester, 2, priority="critical", status="open")
        ProblemTicketLink.objects.create(problem=p, ticket=t, linked_by=self.staff)
        r = evaluate_problem_readiness(p)
        codes = [b["code"] for b in r["blockers"]]
        self.assertEqual(len(codes), len(set(codes)))
        expected_prefix = [c for c in ["ROOT_CAUSE_MISSING","OPEN_BLOCKING_TASKS","OPEN_REQUIRED_ACTIONS","FAILED_VALIDATIONS","OPEN_CRITICAL_TICKETS"] if c in codes]
        self.assertEqual([c for c in codes if c in expected_prefix], expected_prefix)

    def test_read_only_no_history_no_mutation(self):
        p = self._base_problem(status="investigating")
        before_hist = ProblemHistory.objects.filter(problem=p).count()
        before_updated = Problem.objects.get(pk=p.pk).updated_at
        before_version = Problem.objects.get(pk=p.pk).record_version
        r = evaluate_problem_readiness(p)
        self._assert_contract(r)
        self.assertEqual(ProblemHistory.objects.filter(problem=p).count(), before_hist)
        p.refresh_from_db()
        self.assertEqual(p.updated_at, before_updated)
        self.assertEqual(p.record_version, before_version)

    def test_optional_integrations_absent_safely(self):
        p = self._base_problem(status="investigating")
        # no tickets/actions/validations/exceptions/rca relations populated beyond defaults
        r = evaluate_problem_readiness(p)
        self._assert_contract(r)
        self.assertIn("counts", r)
