"""PM1 focused tests — Gate 1.

Numbering, create, status protection, stale version, permissions, ticket
links, CI/Service/Asset/Software links, history immutability, IDOR.
All tests run in Django's isolated test database only.
"""
import threading
import time
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from assets.models import Asset, AssetCategory
from cmdb.models import ConfigurationItem, ConfigurationItemType
from licensing.models import SoftwareProduct
from services.models import ServiceCatalogueItem
from tickets.models import Ticket, TicketCategory

from .models import (
    Problem,
    ProblemConfigurationItemLink,
    ProblemHistory,
    ProblemNumberSequence,
    ProblemTask,
    ProblemTicketLink,
)

BASE = "/api/problems/"
_seq = [0]


# ---------------------------------------------------------------------------
# Helpers (users are created WITHOUT passwords: PBKDF2 dominated suite
# runtime in past workstreams; tests authenticate via force_authenticate).
# ---------------------------------------------------------------------------

def make_user(role, suffix=None):
    _seq[0] += 1
    tag = suffix or str(_seq[0])
    return User.objects.create_user(
        username=f"{role}_pm{tag}",
        role=role,
        email=f"{role}.pm{tag}@example.test",
        employee_id=f"P{role}{tag}"[:30],
    )


def api_client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def make_category(name=None):
    return TicketCategory.objects.create(
        name=name or f"Cat {uuid.uuid4().hex[:8]}"
    )


def make_ticket(requester, category, **fields):
    return Ticket.objects.create(
        title=fields.pop("title", "Recurring failure"),
        description=fields.pop("description", "Service degraded."),
        category=category,
        requester=requester,
        **fields,
    )


def make_service(name=None):
    return ServiceCatalogueItem.objects.create(
        name=name or f"Svc {uuid.uuid4().hex[:8]}"
    )


def make_ci(name=None, code=None):
    tag = uuid.uuid4().hex[:8]
    ci_type, _created = ConfigurationItemType.objects.get_or_create(
        code=code or f"T{tag}",
        defaults={"name": f"Type {tag}"},
    )
    return ConfigurationItem.objects.create(
        ci_type=ci_type,
        name=name or f"CI {tag}",
    )


def make_asset():
    tag = uuid.uuid4().hex[:8]
    category, _created = AssetCategory.objects.get_or_create(
        name=f"Cat {tag}",
    )
    return Asset.objects.create(
        asset_tag=f"AST{tag}",
        name=f"Asset {tag}",
        category=category,
    )


def make_product():
    tag = uuid.uuid4().hex[:8]
    return SoftwareProduct.objects.create(
        name=f"Product {tag}",
        publisher="Example Publisher",
    )


def create_problem_via_api(client, **payload):
    body = {
        "title": "Disk failures on ERP cluster",
        "description": "Repeated disk failures observed on ERP nodes.",
        "problem_type": "recurring_incident",
        "priority": "high",
    }
    body.update(payload)
    return client.post(f"{BASE}problems/", body, format="json")


class ProblemTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.support = make_user("it_support")
        cls.support2 = make_user("it_support", suffix="b")
        cls.manager = make_user("it_manager")
        cls.admin = make_user("system_admin")
        cls.employee = make_user("employee")
        cls.inactive = make_user("it_support", suffix="off")
        cls.inactive.is_active = False
        cls.inactive.save(update_fields=["is_active"])
        cls.category = make_category("ERP")
        cls.requester = make_user("employee", suffix="req")

    def make_problem(self, owner=None, status="draft", **fields):
        problem = Problem.objects.create(
            title=fields.pop("title", "Test problem"),
            description=fields.pop("description", "Test description."),
            status=status,
            owner=owner,
            created_by=fields.pop("created_by", self.support),
            **fields,
        )
        ProblemHistory.objects.create(
            problem=problem,
            actor=problem.created_by,
            event_type="created",
            new_status=status,
            detail="Problem created (test fixture).",
        )
        return problem


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------

class NumberingTests(ProblemTestBase):
    def test_number_format_and_sequence(self):
        p1 = self.make_problem()
        p2 = self.make_problem()
        year = timezone.localtime().year
        self.assertEqual(p1.problem_number, f"PRB-{year}-000001")
        self.assertEqual(p2.problem_number, f"PRB-{year}-000002")
        self.assertNotEqual(p1.problem_number, p2.problem_number)

    def test_number_unique_constraint(self):
        first = self.make_problem()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Problem.objects.create(
                    title="dup", description="dup",
                    problem_number=first.problem_number,
                )

    def test_api_client_cannot_set_number(self):
        client = api_client(self.support)
        res = client.post(
            f"{BASE}problems/",
            {
                "title": "Client-set attempt",
                "description": "Should be ignored.",
                "problem_number": "PRB-1999-999999",
                "status": "accepted",
                "record_version": 99,
                "linked_ticket_count": 42,
                "recurrence_count": 7,
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.data)
        problem = Problem.objects.get(pk=res.data["id"])
        year = timezone.localtime().year
        self.assertTrue(problem.problem_number.startswith(f"PRB-{year}-"))
        self.assertNotEqual(problem.problem_number, "PRB-1999-999999")
        self.assertEqual(problem.status, "draft")
        self.assertEqual(problem.record_version, 1)
        self.assertEqual(problem.linked_ticket_count, 0)
        self.assertEqual(problem.recurrence_count, 0)

    def test_next_number_independent_prefixes(self):
        a = ProblemNumberSequence.objects.create(prefix="X-TEST-", last_value=5)
        from .models import next_number

        self.assertEqual(next_number("X-TEST-"), "X-TEST-000006")
        a.refresh_from_db()
        self.assertEqual(a.last_value, 6)
        self.assertEqual(next_number("Y-TEST-"), "Y-TEST-000001")


class ConcurrentNumberingTests(TransactionTestCase):
    def test_parallel_creates_get_unique_numbers(self):
        results = []
        errors = []
        lock = threading.Lock()

        def worker():
            try:
                for _ in range(3):
                    for attempt in range(50):
                        try:
                            problem = Problem.objects.create(
                                title="Concurrent problem",
                                description="Created under concurrency.",
                            )
                            with lock:
                                results.append(problem.problem_number)
                            break
                        except Exception as exc:  # noqa: BLE001 — SQLite shared-cache lock retry
                            if attempt == 49:
                                raise
                            time.sleep(0.01)
            except Exception as exc:  # noqa: BLE001 — collected for assertion
                with lock:
                    errors.append(repr(exc))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(errors, [], f"thread errors: {errors}")
        self.assertEqual(len(results), 9)
        self.assertEqual(len(set(results)), 9, results)


# ---------------------------------------------------------------------------
# Create + status protection
# ---------------------------------------------------------------------------

class ProblemCreateAPITests(ProblemTestBase):
    def test_create_201_defaults(self):
        client = api_client(self.support)
        res = create_problem_via_api(client)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "draft")
        self.assertEqual(res.data["record_version"], 1)
        self.assertEqual(res.data["linked_ticket_count"], 0)
        self.assertTrue(res.data["first_detected_at"])
        self.assertTrue(res.data["problem_number"].startswith("PRB-"))

    def test_create_requires_title_and_description(self):
        client = api_client(self.support)
        res = client.post(f"{BASE}problems/", {"title": "", "description": ""}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_client_rejected_monitoring_source(self):
        client = api_client(self.support)
        res = create_problem_via_api(client, source="monitoring")
        self.assertEqual(res.status_code, 400)

    def test_create_writes_history(self):
        client = api_client(self.support)
        res = create_problem_via_api(client)
        events = ProblemHistory.objects.filter(
            problem_id=res.data["id"], event_type="created",
        )
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().actor_id, self.support.pk)


class StatusProtectionTests(ProblemTestBase):
    def test_patch_cannot_change_status(self):
        problem = self.make_problem(status="draft")
        client = api_client(self.manager)
        res = client.patch(
            f"{BASE}problems/{problem.pk}/",
            {"status": "accepted", "title": "Renamed"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        problem.refresh_from_db()
        self.assertEqual(problem.status, "draft")
        self.assertEqual(problem.title, "Renamed")

    def test_patch_cannot_change_server_fields(self):
        problem = self.make_problem(status="draft")
        client = api_client(self.manager)
        res = client.patch(
            f"{BASE}problems/{problem.pk}/",
            {
                "problem_number": "PRB-1999-000001",
                "record_version": 99,
                "linked_ticket_count": 50,
                "root_cause_summary": "spoofed",
                "resolved_at": "2020-01-01T00:00:00Z",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        problem.refresh_from_db()
        self.assertNotEqual(problem.problem_number, "PRB-1999-000001")
        self.assertEqual(problem.record_version, 1)
        self.assertEqual(problem.linked_ticket_count, 0)
        self.assertEqual(problem.root_cause_summary, "")
        self.assertIsNone(problem.resolved_at)

    def test_patch_bumps_record_version(self):
        problem = self.make_problem()
        client = api_client(self.support)
        res = client.patch(
            f"{BASE}problems/{problem.pk}/", {"title": "v2 title"}, format="json",
        )
        self.assertEqual(res.status_code, 200)
        problem.refresh_from_db()
        self.assertEqual(problem.record_version, 2)


# ---------------------------------------------------------------------------
# Gate 1 workflow transitions
# ---------------------------------------------------------------------------

class WorkflowGate1Tests(ProblemTestBase):
    def _act(self, client, problem, name, payload=None):
        return client.post(
            f"{BASE}problems/{problem.pk}/{name}/",
            payload or {}, format="json",
        )

    def test_submit_draft(self):
        problem = self.make_problem()
        res = self._act(api_client(self.support), problem, "submit")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "under_review")
        event = problem.history_records.latest("created_at")
        self.assertEqual(event.event_type, "submitted")

    def test_submit_invalid_transition_409(self):
        problem = self.make_problem(status="draft")
        self._act(api_client(self.support), problem, "submit")
        res = self._act(api_client(self.support), problem, "submit")
        self.assertEqual(res.status_code, 409)

    def test_accept_requires_owner(self):
        problem = self.make_problem(status="under_review")
        res = self._act(api_client(self.manager), problem, "accept")
        self.assertEqual(res.status_code, 400)
        self.assertIn("owner", res.data)

    def test_accept_as_manager_with_owner(self):
        problem = self.make_problem(status="under_review", owner=self.support)
        res = self._act(api_client(self.manager), problem, "accept")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "accepted")

    def test_support_cannot_accept(self):
        problem = self.make_problem(status="under_review", owner=self.support)
        res = self._act(api_client(self.support), problem, "accept")
        self.assertEqual(res.status_code, 403)

    def test_reject_requires_reason_and_governance(self):
        problem = self.make_problem(status="under_review")
        client = api_client(self.manager)
        res = self._act(client, problem, "reject", {"reason": ""})
        self.assertEqual(res.status_code, 400)
        res = self._act(client, problem, "reject", {"reason": "Duplicate of PRB-1"})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "rejected")

    def test_start_investigation_sets_timestamp(self):
        problem = self.make_problem(status="accepted", owner=self.support)
        res = self._act(api_client(self.support), problem, "start-investigation")
        self.assertEqual(res.status_code, 200, res.data)
        problem.refresh_from_db()
        self.assertEqual(problem.status, "investigating")
        self.assertIsNotNone(problem.investigation_started_at)

    def test_cancel_governance_and_reason(self):
        problem = self.make_problem()
        res = self._act(api_client(self.support), problem, "cancel", {"reason": "x"})
        self.assertEqual(res.status_code, 403)
        res = self._act(api_client(self.manager), problem, "cancel", {})
        self.assertEqual(res.status_code, 400)
        res = self._act(api_client(self.manager), problem, "cancel", {"reason": "Superseded."})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "cancelled")

    def test_reopen_from_closed(self):
        problem = self.make_problem(status="closed")
        problem.resolved_at = timezone.now()
        problem.closed_at = timezone.now()
        problem.resolution_summary = "Fixed."
        problem.save()
        res = self._act(api_client(self.manager), problem, "reopen", {"reason": "Recurrence."})
        self.assertEqual(res.status_code, 200, res.data)
        problem.refresh_from_db()
        self.assertEqual(problem.status, "reopened")
        self.assertIsNotNone(problem.reopened_at)
        self.assertEqual(problem.resolution_summary, "Fixed.")

    def test_stale_version_conflict_409(self):
        problem = self.make_problem(status="under_review", owner=self.support)
        client = api_client(self.manager)
        res = self._act(
            client, problem, "accept",
            {"expected_record_version": problem.record_version + 5},
        )
        self.assertEqual(res.status_code, 409)
        res = self._act(
            client, problem, "accept",
            {"expected_record_version": problem.record_version},
        )
        self.assertEqual(res.status_code, 200, res.data)


# ---------------------------------------------------------------------------
# Permissions / IDOR
# ---------------------------------------------------------------------------

class PermissionsIDORTests(ProblemTestBase):
    def _staff_endpoints(self, problem):
        return [
            ("get", f"{BASE}problems/"),
            ("get", f"{BASE}problems/{problem.pk}/"),
            ("post", f"{BASE}problems/{problem.pk}/submit/"),
            ("get", f"{BASE}problems/{problem.pk}/history/"),
            ("get", f"{BASE}history/?problem={problem.pk}"),
            ("post", f"{BASE}tasks/"),
            ("get", f"{BASE}ticket-links/"),
            ("post", f"{BASE}ci-links/"),
        ]

    def test_employee_denied_everywhere(self):
        problem = self.make_problem(owner=self.manager)
        client = api_client(self.employee)
        for method, url in self._staff_endpoints(problem):
            payload = {"problem": problem.pk, "title": "x"} if method == "post" else {}
            res = getattr(client, method)(url, payload, format="json")
            with self.subTest(url=url, method=method):
                self.assertEqual(res.status_code, 403)

    def test_employee_cannot_list_or_read(self):
        problem = self.make_problem()
        client = api_client(self.employee)
        self.assertEqual(client.get(f"{BASE}problems/").status_code, 403)
        self.assertEqual(client.get(f"{BASE}problems/{problem.pk}/").status_code, 403)

    def test_inactive_user_denied(self):
        client = api_client(self.inactive)
        self.assertEqual(client.get(f"{BASE}problems/").status_code, 403)

    def test_anonymous_denied(self):
        client = api_client()
        res = client.get(f"{BASE}problems/")
        self.assertIn(res.status_code, (401, 403))

    def test_support_can_create_and_submit_but_not_govern(self):
        problem = self.make_problem(status="under_review")
        client = api_client(self.support)
        res = create_problem_via_api(client)
        self.assertEqual(res.status_code, 201)
        for action in ("accept", "reject", "cancel", "reopen"):
            payload = {"reason": "x"} if action in {"reject", "cancel", "reopen"} else {}
            res = client.post(f"{BASE}problems/{problem.pk}/{action}/", payload, format="json")
            with self.subTest(action=action):
                self.assertEqual(res.status_code, 403)

    def test_governance_update_fields_restricted_for_support(self):
        problem = self.make_problem(owner=None)
        res = api_client(self.support).patch(
            f"{BASE}problems/{problem.pk}/",
            {"owner": self.manager.pk, "title": "kept"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        problem.refresh_from_db()
        self.assertIsNone(problem.owner)
        self.assertEqual(problem.title, "kept")


# ---------------------------------------------------------------------------
# Ticket links
# ---------------------------------------------------------------------------

class TicketLinkTests(ProblemTestBase):
    def _link(self, client, problem, ticket, **extra):
        body = {"problem": problem.pk, "ticket": ticket.pk}
        body.update(extra)
        return client.post(f"{BASE}ticket-links/", body, format="json")

    def test_create_link_history_and_counters(self):
        problem = self.make_problem()
        ticket = make_ticket(self.requester, self.category)
        res = self._link(api_client(self.support), problem, ticket)
        self.assertEqual(res.status_code, 201, res.data)
        problem.refresh_from_db()
        self.assertEqual(problem.linked_ticket_count, 1)
        self.assertEqual(problem.open_ticket_count, 1)
        self.assertEqual(problem.recurrence_count, 0)
        self.assertTrue(
            problem.history_records.filter(event_type="ticket_linked").exists(),
        )

    def test_duplicate_active_link_rejected(self):
        problem = self.make_problem()
        ticket = make_ticket(self.requester, self.category)
        self._link(api_client(self.support), problem, ticket)
        res = self._link(api_client(self.support), problem, ticket)
        self.assertEqual(res.status_code, 400)

    def test_confirmed_recurring_link_increments_recurrence(self):
        problem = self.make_problem()
        ticket = make_ticket(self.requester, self.category)
        res = self._link(
            api_client(self.support), problem, ticket,
            relationship_type="recurring_incident", relevance="confirmed",
        )
        self.assertEqual(res.status_code, 201, res.data)
        problem.refresh_from_db()
        self.assertEqual(problem.recurrence_count, 1)

    def test_candidate_link_does_not_count_recurrence(self):
        problem = self.make_problem()
        ticket = make_ticket(self.requester, self.category)
        res = self._link(
            api_client(self.support), problem, ticket,
            relationship_type="recurring_incident", relevance="candidate",
        )
        self.assertEqual(res.status_code, 201, res.data)
        problem.refresh_from_db()
        self.assertEqual(problem.recurrence_count, 0)

    def test_linked_ticket_not_mutated(self):
        problem = self.make_problem()
        ticket = make_ticket(self.requester, self.category)
        self._link(api_client(self.support), problem, ticket)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "open")

    def test_unlink_updates_counters_and_history(self):
        problem = self.make_problem()
        ticket = make_ticket(self.requester, self.category)
        res = self._link(api_client(self.support), problem, ticket)
        link_id = res.data["id"]
        res = api_client(self.support).delete(f"{BASE}ticket-links/{link_id}/")
        self.assertEqual(res.status_code, 204, res.data if hasattr(res, "data") else "")
        problem.refresh_from_db()
        self.assertEqual(problem.linked_ticket_count, 0)
        self.assertTrue(
            problem.history_records.filter(event_type="ticket_unlinked").exists(),
        )

    def test_employee_cannot_link_or_list(self):
        problem = self.make_problem()
        ticket = make_ticket(self.requester, self.category)
        client = api_client(self.employee)
        self.assertEqual(
            self._link(client, problem, ticket).status_code, 403,
        )
        self.assertEqual(client.get(f"{BASE}ticket-links/").status_code, 403)


# ---------------------------------------------------------------------------
# CI / Service / Asset / Software links
# ---------------------------------------------------------------------------

class ObjectLinkTests(ProblemTestBase):
    def test_ci_service_asset_software_links(self):
        problem = self.make_problem()
        client = api_client(self.support)
        ci = make_ci()
        service = make_service()
        asset = make_asset()
        product = make_product()
        cases = [
            ("ci-links", "configuration_item", ci.pk, "dependency", "root_cause", "confirmed"),
            ("service-links", "service", service.pk, "direct", "affected", "high"),
            ("asset-links", "asset", asset.pk, "suspected", "suspected_cause", "low"),
            ("software-links", "software_product", product.pk, "direct", "fix_target", "medium"),
        ]
        for route, field, pk, impact, role, confidence in cases:
            res = client.post(
                f"{BASE}{route}/",
                {
                    "problem": problem.pk, field: pk,
                    "impact_type": impact, "role": role,
                    "confidence": confidence, "notes": "checked",
                },
                format="json",
            )
            with self.subTest(route=route):
                self.assertEqual(res.status_code, 201, res.data)
                self.assertEqual(res.data["impact_type"], impact)
                self.assertEqual(res.data["role"], role)
                self.assertEqual(res.data["confidence"], confidence)
        self.assertEqual(problem.ci_links.filter(is_deleted=False).count(), 1)
        self.assertEqual(problem.service_links.filter(is_deleted=False).count(), 1)
        self.assertEqual(problem.asset_links.filter(is_deleted=False).count(), 1)
        self.assertEqual(problem.software_links.filter(is_deleted=False).count(), 1)
        self.assertTrue(problem.history_records.filter(event_type="linked").exists())

    def test_duplicate_ci_link_rejected(self):
        problem = self.make_problem()
        ci = make_ci()
        client = api_client(self.support)
        body = {"problem": problem.pk, "configuration_item": ci.pk}
        self.assertEqual(client.post(f"{BASE}ci-links/", body, format="json").status_code, 201)
        self.assertEqual(client.post(f"{BASE}ci-links/", body, format="json").status_code, 400)

    def test_ci_link_employee_denied(self):
        problem = self.make_problem()
        ci = make_ci()
        res = api_client(self.employee).post(
            f"{BASE}ci-links/",
            {"problem": problem.pk, "configuration_item": ci.pk},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_link_does_not_mutate_target(self):
        problem = self.make_problem()
        asset = make_asset()
        original_status = asset.status
        api_client(self.support).post(
            f"{BASE}asset-links/",
            {"problem": problem.pk, "asset": asset.pk},
            format="json",
        )
        asset.refresh_from_db()
        self.assertEqual(asset.status, original_status)
        self.assertFalse(asset.is_deleted)


# ---------------------------------------------------------------------------
# History immutability
# ---------------------------------------------------------------------------

class HistoryImmutabilityTests(ProblemTestBase):
    def test_history_row_cannot_be_updated_or_deleted(self):
        problem = self.make_problem()
        row = problem.history_records.first()
        self.assertIsNotNone(row)
        row.detail = "tampered"
        with self.assertRaises(DjangoValidationError):
            row.save()
        with self.assertRaises(DjangoValidationError):
            row.delete()

    def test_history_detail_bounded(self):
        problem = self.make_problem()
        with self.assertRaises(DjangoValidationError):
            ProblemHistory.objects.create(
                problem=problem, event_type="other", detail="x" * 5000,
            )

    def test_history_api_read_only(self):
        problem = self.make_problem()
        client = api_client(self.manager)
        res = client.get(f"{BASE}history/", {"problem": problem.pk})
        self.assertEqual(res.status_code, 200)
        res = client.post(f"{BASE}history/", {"problem": problem.pk, "event_type": "created"}, format="json")
        self.assertEqual(res.status_code, 405)
        row = problem.history_records.first()
        res = client.patch(f"{BASE}history/{row.pk}/", {"detail": "hack"}, format="json")
        self.assertEqual(res.status_code, 405)

    def test_transitions_recorded(self):
        problem = self.make_problem(status="under_review", owner=self.support)
        client = api_client(self.manager)
        client.post(f"{BASE}problems/{problem.pk}/accept/", {}, format="json")
        events = list(
            problem.history_records.order_by("created_at").values_list(
                "event_type", "previous_status", "new_status",
            ),
        )
        self.assertEqual(events[-1], ("accepted", "under_review", "accepted"))
        self.assertEqual(events[-1][1:], ("under_review", "accepted"))


# ---------------------------------------------------------------------------
# Tasks (Gate 1 surface) + soft delete
# ---------------------------------------------------------------------------

class TaskGate1Tests(ProblemTestBase):
    def test_create_task_auto_sequence_and_history(self):
        p1 = self.make_problem()
        client = api_client(self.support)
        res1 = client.post(
            f"{BASE}tasks/",
            {"problem": p1.pk, "title": "Collect logs"},
            format="json",
        )
        self.assertEqual(res1.status_code, 201, res1.data)
        p2 = self.make_problem()
        res2 = client.post(
            f"{BASE}tasks/",
            {"problem": p2.pk, "title": "Interview supplier"},
            format="json",
        )
        self.assertEqual(res2.status_code, 201, res2.data)
        self.assertEqual(res2.data["sequence"], 1)

        self.assertEqual(res1.data["status"], "not_started")

        self.assertEqual(
            p1.history_records.filter(event_type="task_created").count(),
            1,
        )  # tasks created for other problem

        # NOTE: ProblemHistory events are scoped to each problem
        self.assertTrue(
            ProblemHistory.objects.filter(problem=p1.pk, event_type="task_created").count()
            >= 1,
        )
        self.assertTrue(
            ProblemHistory.objects.filter(problem=p2.pk, event_type="task_created").count()
            >= 1,
        )
    def test_task_status_readonly_via_patch(self):
        problem = self.make_problem()
        client = api_client(self.support)
        res = client.post(
            f"{BASE}tasks/", {"problem": problem.pk, "title": "T1"}, format="json",
        )
        task_id = res.data["id"]
        res = client.patch(
            f"{BASE}tasks/{task_id}/",
            {"status": "completed", "title": "T1 updated"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        task = ProblemTask.objects.get(pk=task_id)
        self.assertEqual(task.status, "not_started")
        self.assertEqual(task.title, "T1 updated")

    def test_task_employee_denied(self):
        problem = self.make_problem()
        res = api_client(self.employee).post(
            f"{BASE}tasks/", {"problem": problem.pk, "title": "x"}, format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_task_list_filter_by_problem(self):
        p1 = self.make_problem()
        p2 = self.make_problem()
        client = api_client(self.support)
        client.post(f"{BASE}tasks/", {"problem": p1.pk, "title": "A"}, format="json")
        client.post(f"{BASE}tasks/", {"problem": p2.pk, "title": "B"}, format="json")
        res = client.get(f"{BASE}tasks/", {"problem": p1.pk})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)


class SoftDeleteGate1Tests(ProblemTestBase):
    def test_manager_soft_delete_without_links(self):
        problem = self.make_problem()
        res = api_client(self.manager).delete(f"{BASE}problems/{problem.pk}/")
        self.assertEqual(res.status_code, 204)
        problem.refresh_from_db()
        self.assertTrue(problem.is_deleted)

    def test_delete_blocked_with_active_links(self):
        problem = self.make_problem()
        ticket = make_ticket(self.requester, self.category)
        api_client(self.support).post(
            f"{BASE}ticket-links/",
            {"problem": problem.pk, "ticket": ticket.pk},
            format="json",
        )
        res = api_client(self.manager).delete(f"{BASE}problems/{problem.pk}/")
        self.assertEqual(res.status_code, 400)
        problem.refresh_from_db()
        self.assertFalse(problem.is_deleted)

    def test_support_delete_denied(self):
        problem = self.make_problem()
        res = api_client(self.support).delete(f"{BASE}problems/{problem.pk}/")
        self.assertEqual(res.status_code, 403)
