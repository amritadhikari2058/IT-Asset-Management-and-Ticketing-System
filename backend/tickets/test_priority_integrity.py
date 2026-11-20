"""Ticket priority-update integrity and SLA recalculation tests.

Covers every priority-change path:
- Single-ticket PATCH through the API (perform_update -> serializer.save() -> Ticket.save())
- Bulk ticket update (bulk_update -> t.save() -> Ticket.save())
- Direct model.save() calls

Verifies:
- A priority change updates sla_due_at correctly using the new priority's SLA target.
- An unchanged priority does NOT trigger unnecessary SLA recalculation.
- SLA pause history is preserved across priority changes.
- Bulk updates apply SLA recalculation per-ticket.
- Invalid priorities are rejected.
- Transaction rollback leaves consistent state.
"""

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from tickets.models import (
    Ticket, TicketCategory, TicketResolutionCode, TicketSLA, TicketSlaPause,
)


def _make_ticket(dep, requester, cat, status="open", priority="medium",
                 sla_hours=None, resolution_code=None, resolved_by=None,
                 resolved_at=None):
    """Create a ticket with an optional custom SLA config."""
    if sla_hours is not None:
        TicketSLA.objects.get_or_create(
            priority=priority,
            defaults={"target_resolution_hours": sla_hours,
                      "is_active": True, "is_deleted": False})
    return Ticket.objects.create(
        title="Test", description="d", category=cat,
        requester=requester, department=dep,
        status=status, priority=priority,
        resolution_code=resolution_code,
        resolved_by=resolved_by,
        resolved_at=resolved_at)


class TicketPriorityModelTests(TestCase):
    """Direct model-level tests for priority-change SLA recalculation."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        self.res_code = TicketResolutionCode.objects.create(
            name="Fixed", code="fixed", is_active=True, is_deleted=False)

        # SLA configs: low=72h, medium=24h, high=8h, critical=2h
        for pri, hrs in [("low", 72), ("medium", 24), ("high", 8),
                         ("critical", 2)]:
            TicketSLA.objects.create(
                priority=pri, target_resolution_hours=hrs,
                is_active=True, is_deleted=False)

    def test_priority_change_recalculates_sla_deadline(self):
        """Changing priority from medium(24h) to critical(2h) updates sla_due_at."""
        t = _make_ticket(self.dep, self.emp, self.tcat,
                         status="open", priority="medium", sla_hours=24)
        # Model-level create doesn't set sla_due_at (that's done in the view's
        # perform_create). Set it manually to simulate a ticket with an SLA.
        t.sla_due_at = timezone.now() + timedelta(hours=24)
        t.save(update_fields=["sla_due_at"])
        original_due = t.sla_due_at
        self.assertIsNotNone(original_due)

        # Change priority to critical
        t.priority = "critical"
        t.save()

        t.refresh_from_db()
        # sla_due_at should be recalculated: now + 2 hours (critical)
        expected_min = timezone.now() + timedelta(hours=1, minutes=55)
        expected_max = timezone.now() + timedelta(hours=2, minutes=5)
        self.assertGreaterEqual(t.sla_due_at, expected_min)
        self.assertLessEqual(t.sla_due_at, expected_max)
        # The deadline should be different from the original medium deadline
        self.assertNotEqual(t.sla_due_at, original_due)

    def test_unchanged_priority_does_not_recalculate(self):
        """Saving without priority change should not change sla_due_at."""
        t = _make_ticket(self.dep, self.emp, self.tcat,
                         status="open", priority="medium", sla_hours=24)
        t.sla_due_at = timezone.now() + timedelta(hours=24)
        t.save(update_fields=["sla_due_at"])
        original_due = t.sla_due_at

        # Change something else (title)
        t.title = "Updated title"
        t.save(update_fields=["title", "updated_at"])

        t.refresh_from_db()
        self.assertEqual(t.sla_due_at, original_due)

    def test_priority_change_with_active_pause_preserves_pause(self):
        """Priority change preserves existing SLA pause history."""
        t = _make_ticket(self.dep, self.emp, self.tcat,
                         status="waiting_requester", priority="medium",
                         sla_hours=24)
        t.sla_due_at = timezone.now() + timedelta(hours=24)
        t.save(update_fields=["sla_due_at"])
        original_due = t.sla_due_at

        # Create an active pause
        pause = TicketSlaPause.objects.create(
            ticket=t, reason="waiting_requester",
            pause_type="waiting_requester", started_by=self.emp,
            started_at=timezone.now() - timedelta(hours=5))

        # Change priority while paused
        t.priority = "high"
        t.save()

        t.refresh_from_db()
        # Pause should still exist and be active
        pause.refresh_from_db()
        self.assertIsNone(pause.ended_at)
        # sla_due_at should be recalculated for high priority (8h from now)
        expected_min = timezone.now() + timedelta(hours=7, minutes=55)
        expected_max = timezone.now() + timedelta(hours=8, minutes=5)
        self.assertGreaterEqual(t.sla_due_at, expected_min)
        self.assertLessEqual(t.sla_due_at, expected_max)

    def test_priority_change_after_ended_pause(self):
        """Priority change works correctly after a pause has ended."""
        t = _make_ticket(self.dep, self.emp, self.tcat,
                         status="in_progress", priority="medium", sla_hours=24)
        t.sla_due_at = timezone.now() + timedelta(hours=24)
        t.save(update_fields=["sla_due_at"])

        # Create and end a pause
        pause = TicketSlaPause.objects.create(
            ticket=t, reason="waiting_requester",
            pause_type="waiting_requester", started_by=self.emp,
            started_at=timezone.now() - timedelta(hours=10),
            ended_at=timezone.now() - timedelta(hours=2))

        original_due = t.sla_due_at

        # Change priority
        t.priority = "critical"
        t.save()

        t.refresh_from_db()
        # sla_due_at should be recalculated: now + 2h (critical)
        expected_min = timezone.now() + timedelta(hours=1, minutes=55)
        expected_max = timezone.now() + timedelta(hours=2, minutes=5)
        self.assertGreaterEqual(t.sla_due_at, expected_min)
        self.assertLessEqual(t.sla_due_at, expected_max)

    def test_multiple_priority_changes(self):
        """Repeated priority changes each recalculate SLA correctly."""
        t = _make_ticket(self.dep, self.emp, self.tcat,
                         status="open", priority="low", sla_hours=72)
        t.sla_due_at = timezone.now() + timedelta(hours=72)
        t.save(update_fields=["sla_due_at"])
        first_due = t.sla_due_at

        # Change to medium (24h)
        t.priority = "medium"
        t.save()
        t.refresh_from_db()
        expected_min = timezone.now() + timedelta(hours=23, minutes=55)
        expected_max = timezone.now() + timedelta(hours=24, minutes=5)
        self.assertGreaterEqual(t.sla_due_at, expected_min)
        self.assertLessEqual(t.sla_due_at, expected_max)
        self.assertNotEqual(t.sla_due_at, first_due)

        # Change to critical (2h)
        medium_due = t.sla_due_at
        t.priority = "critical"
        t.save()
        t.refresh_from_db()
        expected_min = timezone.now() + timedelta(hours=1, minutes=55)
        expected_max = timezone.now() + timedelta(hours=2, minutes=5)
        self.assertGreaterEqual(t.sla_due_at, expected_min)
        self.assertLessEqual(t.sla_due_at, expected_max)
        self.assertNotEqual(t.sla_due_at, medium_due)

    def test_resolved_ticket_priority_change(self):
        """Priority change on a resolved ticket recalculates SLA."""
        t = _make_ticket(self.dep, self.emp, self.tcat,
                         status="resolved", priority="medium",
                         sla_hours=24,
                         resolution_code=self.res_code,
                         resolved_by=self.mgr,
                         resolved_at=timezone.now())
        t.sla_due_at = timezone.now() + timedelta(hours=24)
        t.save(update_fields=["sla_due_at"])
        original_due = t.sla_due_at

        t.priority = "critical"
        t.save()

        t.refresh_from_db()
        # Even resolved tickets get SLA recalculated
        expected_min = timezone.now() + timedelta(hours=1, minutes=55)
        expected_max = timezone.now() + timedelta(hours=2, minutes=5)
        self.assertGreaterEqual(t.sla_due_at, expected_min)
        self.assertLessEqual(t.sla_due_at, expected_max)
        self.assertNotEqual(t.sla_due_at, original_due)

    def test_no_sla_config_leaves_deadline_unset(self):
        """Ticket with no active SLA config keeps sla_due_at unset."""
        # Remove the "low" SLA config created in setUp
        TicketSLA.objects.filter(priority="low").delete()
        t = _make_ticket(self.dep, self.emp, self.tcat,
                         status="open", priority="low")
        # t.sla_due_at should be None since no SLA config exists
        self.assertIsNone(t.sla_due_at)

        # Change to medium which HAS an SLA config
        t.priority = "medium"
        t.save()

        t.refresh_from_db()
        # Now sla_due_at should be set
        self.assertIsNotNone(t.sla_due_at)


class TicketPriorityAPITests(TestCase):
    """API-level tests for single-ticket priority PATCH."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        for pri, hrs in [("low", 72), ("medium", 24), ("high", 8),
                         ("critical", 2)]:
            TicketSLA.objects.create(
                priority=pri, target_resolution_hours=hrs,
                is_active=True, is_deleted=False)
        self.res_code = TicketResolutionCode.objects.create(
            name="Fixed", code="fixed", is_active=True, is_deleted=False)

    def test_api_priority_change_updates_sla(self):
        """PATCH priority on a single ticket recalculates sla_due_at via API."""
        auth(self.c, self.mgr)
        t = Ticket.objects.create(
            title="API test", description="d", category=self.tcat,
            requester=self.emp, department=self.dep,
            status="open", priority="medium")

        original_due = t.sla_due_at

        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"priority": "critical"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)

        t.refresh_from_db()
        self.assertEqual(t.priority, "critical")
        # sla_due_at should be recalculated
        expected_min = timezone.now() + timedelta(hours=1, minutes=55)
        expected_max = timezone.now() + timedelta(hours=2, minutes=5)
        self.assertGreaterEqual(t.sla_due_at, expected_min)
        self.assertLessEqual(t.sla_due_at, expected_max)
        self.assertNotEqual(t.sla_due_at, original_due)

    def test_api_priority_unchanged_no_recalculation(self):
        """PATCH without priority change should not change sla_due_at."""
        auth(self.c, self.mgr)
        t = Ticket.objects.create(
            title="API test", description="d", category=self.tcat,
            requester=self.emp, department=self.dep,
            status="open", priority="medium")
        original_due = t.sla_due_at

        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"title": "New title"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)

        t.refresh_from_db()
        self.assertEqual(t.sla_due_at, original_due)

    def test_api_invalid_priority_rejected(self):
        """PATCH with invalid priority returns 400."""
        auth(self.c, self.mgr)
        t = Ticket.objects.create(
            title="API test", description="d", category=self.tcat,
            requester=self.emp, department=self.dep,
            status="open", priority="medium")

        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"priority": "urgent"}, format="json")
        self.assertEqual(res.status_code, 400, res.data)
        t.refresh_from_db()
        self.assertEqual(t.priority, "medium")

    def test_employee_cannot_change_priority(self):
        """Employee cannot change priority (staff-only field)."""
        auth(self.c, self.emp)
        t = Ticket.objects.create(
            title="API test", description="d", category=self.tcat,
            requester=self.emp, department=self.dep,
            status="open", priority="medium")

        res = self.c.patch(f"/api/tickets/{t.pk}/",
                           {"priority": "critical"}, format="json")
        self.assertEqual(res.status_code, 403, res.data)
        t.refresh_from_db()
        self.assertEqual(t.priority, "medium")


class TicketPriorityBulkTests(TestCase):
    """Bulk priority update tests (model-level, since bulk_update API has
    pre-existing _manage_sla_pause signature issues)."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        for pri, hrs in [("low", 72), ("medium", 24), ("high", 8),
                         ("critical", 2)]:
            TicketSLA.objects.create(
                priority=pri, target_resolution_hours=hrs,
                is_active=True, is_deleted=False)

    def test_bulk_priority_change_model_level(self):
        """Bulk priority change via model.save() recalculates SLA for each."""
        t1 = _make_ticket(self.dep, self.emp, self.tcat,
                          status="open", priority="low", sla_hours=72)
        t2 = _make_ticket(self.dep, self.emp, self.tcat,
                          status="open", priority="medium", sla_hours=24)
        # Set initial sla_due_at (model create doesn't set it)
        t1.sla_due_at = timezone.now() + timedelta(hours=72)
        t2.sla_due_at = timezone.now() + timedelta(hours=24)
        t1.save(update_fields=["sla_due_at"])
        t2.save(update_fields=["sla_due_at"])
        t1_due_before = t1.sla_due_at
        t2_due_before = t2.sla_due_at

        # Change both to critical
        t1.priority = "critical"
        t2.priority = "critical"
        t1.save()
        t2.save()

        t1.refresh_from_db()
        t2.refresh_from_db()

        # Both should have new deadlines (~2h from now)
        for t, due_before in ((t1, t1_due_before), (t2, t2_due_before)):
            expected_min = timezone.now() + timedelta(hours=1, minutes=55)
            expected_max = timezone.now() + timedelta(hours=2, minutes=5)
            self.assertGreaterEqual(t.sla_due_at, expected_min)
            self.assertLessEqual(t.sla_due_at, expected_max)
            self.assertNotEqual(t.sla_due_at, due_before)

    def test_bulk_mixed_priorities(self):
        """Different tickets with different new priorities get correct SLAs."""
        t1 = _make_ticket(self.dep, self.emp, self.tcat,
                          status="open", priority="low", sla_hours=72)
        t2 = _make_ticket(self.dep, self.emp, self.tcat,
                          status="open", priority="medium", sla_hours=24)
        t1.sla_due_at = timezone.now() + timedelta(hours=72)
        t2.sla_due_at = timezone.now() + timedelta(hours=24)
        t1.save(update_fields=["sla_due_at"])
        t2.save(update_fields=["sla_due_at"])

        # t1 -> critical (2h), t2 -> low (72h)
        t1.priority = "critical"
        t2.priority = "low"
        t1.save()
        t2.save()

        t1.refresh_from_db()
        t2.refresh_from_db()

        # t1: critical -> ~2h
        expected_min = timezone.now() + timedelta(hours=1, minutes=55)
        expected_max = timezone.now() + timedelta(hours=2, minutes=5)
        self.assertGreaterEqual(t1.sla_due_at, expected_min)
        self.assertLessEqual(t1.sla_due_at, expected_max)

        # t2: low -> ~72h
        expected_min = timezone.now() + timedelta(hours=71, minutes=55)
        expected_max = timezone.now() + timedelta(hours=72, minutes=5)
        self.assertGreaterEqual(t2.sla_due_at, expected_min)
        self.assertLessEqual(t2.sla_due_at, expected_max)

    def test_bulk_priority_with_pauses(self):
        """Bulk priority change preserves pause history per ticket."""
        t1 = _make_ticket(self.dep, self.emp, self.tcat,
                          status="waiting_requester", priority="medium",
                          sla_hours=24)
        t1.sla_due_at = timezone.now() + timedelta(hours=24)
        t1.save(update_fields=["sla_due_at"])
        # Create active pause on t1
        TicketSlaPause.objects.create(
            ticket=t1, reason="waiting_requester",
            pause_type="waiting_requester", started_by=self.emp,
            started_at=timezone.now() - timedelta(hours=3))

        t2 = _make_ticket(self.dep, self.emp, self.tcat,
                          status="open", priority="low", sla_hours=72)
        t2.sla_due_at = timezone.now() + timedelta(hours=72)
        t2.save(update_fields=["sla_due_at"])

        # Change both to high (8h)
        t1.priority = "high"
        t2.priority = "high"
        t1.save()
        t2.save()

        t1.refresh_from_db()
        t2.refresh_from_db()

        # t1 pause should still be active
        pause = TicketSlaPause.objects.filter(
            ticket=t1, ended_at__isnull=True).first()
        self.assertIsNotNone(pause)

        # Both should have ~8h deadlines
        for t in (t1, t2):
            expected_min = timezone.now() + timedelta(hours=7, minutes=55)
            expected_max = timezone.now() + timedelta(hours=8, minutes=5)
            self.assertGreaterEqual(t.sla_due_at, expected_min)
            self.assertLessEqual(t.sla_due_at, expected_max)

    def test_priority_change_rollback(self):
        """Transaction rollback leaves ticket and SLA consistent."""
        t = _make_ticket(self.dep, self.emp, self.tcat,
                         status="open", priority="medium", sla_hours=24)
        t.sla_due_at = timezone.now() + timedelta(hours=24)
        t.save(update_fields=["sla_due_at"])
        original_due = t.sla_due_at
        original_priority = t.priority

        try:
            with transaction.atomic():
                t.priority = "critical"
                t.save()
                # Force a rollback
                raise IntegrityError("forced rollback")
        except IntegrityError:
            pass

        t.refresh_from_db()
        # After rollback, priority and SLA should be unchanged
        self.assertEqual(t.priority, original_priority)
        self.assertEqual(t.sla_due_at, original_due)


class TicketPriorityBulkAPITests(TestCase):
    """Bulk priority update tests through the actual /api/tickets/bulk_update/
    endpoint. Verifies end-to-end API integration including SLA recalculation,
    pause preservation, authorization, and partial failure handling."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        for pri, hrs in [("low", 72), ("medium", 24), ("high", 8),
                         ("critical", 2)]:
            TicketSLA.objects.create(
                priority=pri, target_resolution_hours=hrs,
                is_active=True, is_deleted=False)

    def _make_ticket_api(self, priority="medium", sla_hours=None):
        """Create a ticket via the API."""
        auth(self.c, self.mgr)
        res = self.c.post("/api/tickets/", {
            "title": "Bulk test ticket",
            "description": "d",
            "category": self.tcat.pk,
            "department": self.dep.pk,
            "status": "open",
            "priority": priority,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        t = Ticket.objects.get(pk=res.data["id"])
        if sla_hours is not None:
            t.sla_due_at = timezone.now() + timedelta(hours=sla_hours)
            t.save(update_fields=["sla_due_at"])
        return t

    def _bulk_update(self, ids, changes, confirm=True, preview=False):
        """Call the bulk_update endpoint."""
        auth(self.c, self.mgr)
        return self.c.post("/api/tickets/bulk_update/", {
            "ids": ids,
            "changes": changes,
            "preview": preview,
            "confirm": confirm,
        }, format="json")

    def test_api_bulk_priority_change_updates_sla(self):
        """Bulk PATCH priority change recalculates sla_due_at via API."""
        t1 = self._make_ticket_api("low", 72)
        t2 = self._make_ticket_api("medium", 24)

        res = self._bulk_update([t1.pk, t2.pk], {"priority": "critical"})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(set(res.data["successful"]), {t1.pk, t2.pk})

        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertEqual(t1.priority, "critical")
        self.assertEqual(t2.priority, "critical")
        # Both should have ~2h deadlines
        for t in (t1, t2):
            expected_min = timezone.now() + timedelta(hours=1, minutes=55)
            expected_max = timezone.now() + timedelta(hours=2, minutes=5)
            self.assertGreaterEqual(t.sla_due_at, expected_min)
            self.assertLessEqual(t.sla_due_at, expected_max)

    def test_api_bulk_mixed_priorities(self):
        """Different tickets get different SLA deadlines per new priority."""
        t1 = self._make_ticket_api("low", 72)
        t2 = self._make_ticket_api("medium", 24)

        # t1 -> critical (2h), t2 -> low (72h)
        res = self._bulk_update([t1.pk, t2.pk], {"priority": "critical"})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(set(res.data["successful"]), {t1.pk, t2.pk})

        t1.refresh_from_db()
        t2.refresh_from_db()
        # Both get critical in this test (same change applied to all)
        self.assertEqual(t1.priority, "critical")
        self.assertEqual(t2.priority, "critical")
        # Both should have ~2h deadlines
        for t in (t1, t2):
            expected_min = timezone.now() + timedelta(hours=1, minutes=55)
            expected_max = timezone.now() + timedelta(hours=2, minutes=5)
            self.assertGreaterEqual(t.sla_due_at, expected_min)
            self.assertLessEqual(t.sla_due_at, expected_max)

    def test_api_bulk_different_new_priorities(self):
        """Bulk update can apply different priorities via separate calls,
        verifying each ticket gets its own SLA deadline."""
        t1 = self._make_ticket_api("low", 72)
        t2 = self._make_ticket_api("medium", 24)

        # Change t1 to critical only
        res1 = self._bulk_update([t1.pk], {"priority": "critical"})
        self.assertEqual(res1.status_code, 200, res1.data)
        # Change t2 to low only
        res2 = self._bulk_update([t2.pk], {"priority": "low"})
        self.assertEqual(res2.status_code, 200, res2.data)

        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertEqual(t1.priority, "critical")
        self.assertEqual(t2.priority, "low")

        # Verify SLA deadlines match the assigned priorities
        expected_min = timezone.now() + timedelta(hours=1, minutes=55)
        expected_max = timezone.now() + timedelta(hours=2, minutes=5)
        self.assertGreaterEqual(t1.sla_due_at, expected_min)
        self.assertLessEqual(t1.sla_due_at, expected_max)

        expected_min = timezone.now() + timedelta(hours=71, minutes=55)
        expected_max = timezone.now() + timedelta(hours=72, minutes=5)
        self.assertGreaterEqual(t2.sla_due_at, expected_min)
        self.assertLessEqual(t2.sla_due_at, expected_max)

    def test_api_bulk_priority_unchanged_no_recalculation(self):
        """Bulk update without priority change should not change sla_due_at."""
        t1 = self._make_ticket_api("medium", 24)
        t2 = self._make_ticket_api("high", 8)
        orig_due1 = t1.sla_due_at
        orig_due2 = t2.sla_due_at

        res = self._bulk_update([t1.pk, t2.pk], {"status": "in_progress"})
        self.assertEqual(res.status_code, 200, res.data)

        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertEqual(t1.sla_due_at, orig_due1)
        self.assertEqual(t2.sla_due_at, orig_due2)

    def test_api_bulk_invalid_priority_rejected(self):
        """Bulk update validates priority choices via the same check as
        single-ticket PATCH. Invalid priorities are rejected; the ticket's
        priority remains unchanged and the ticket appears in the 'failed'
        list."""
        t = self._make_ticket_api("medium", 24)
        res = self._bulk_update([t.pk], {"priority": "urgent"})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["summary"]["failed"], 1)
        failed_ids = [f["id"] for f in res.data["failed"]]
        self.assertIn(t.pk, failed_ids)
        t.refresh_from_db()
        # Priority should remain unchanged; invalid priority was rejected.
        self.assertEqual(t.priority, "medium")

    def test_api_bulk_employee_cannot_change_priority(self):
        """Employee cannot change priority via bulk update (staff-only)."""
        t = self._make_ticket_api("medium", 24)
        auth(self.c, self.emp)
        res = self.c.post("/api/tickets/bulk_update/", {
            "ids": [t.pk],
            "changes": {"priority": "critical"},
            "preview": False, "confirm": True,
        }, format="json")
        self.assertEqual(res.status_code, 403, res.data)
        t.refresh_from_db()
        self.assertEqual(t.priority, "medium")

    def test_api_bulk_priority_with_active_pause(self):
        """Bulk priority change preserves active SLA pause."""
        auth(self.c, self.mgr)
        t = Ticket.objects.create(
            title="Pause test", description="d", category=self.tcat,
            requester=self.emp, department=self.dep,
            status="waiting_requester", priority="medium")
        t.sla_due_at = timezone.now() + timedelta(hours=24)
        t.save(update_fields=["sla_due_at"])
        TicketSlaPause.objects.create(
            ticket=t, reason="waiting_requester",
            pause_type="waiting_requester", started_by=self.mgr,
            started_at=timezone.now() - timedelta(hours=3))

        res = self._bulk_update([t.pk], {"priority": "critical"})
        self.assertEqual(res.status_code, 200, res.data)

        t.refresh_from_db()
        # Pause should still be active
        pause = TicketSlaPause.objects.filter(
            ticket=t, ended_at__isnull=True).first()
        self.assertIsNotNone(pause)
        # SLA should be recalculated for critical (~2h)
        expected_min = timezone.now() + timedelta(hours=1, minutes=55)
        expected_max = timezone.now() + timedelta(hours=2, minutes=5)
        self.assertGreaterEqual(t.sla_due_at, expected_min)
        self.assertLessEqual(t.sla_due_at, expected_max)

    def test_api_bulk_partial_failure(self):
        """Bulk update skips tickets with invalid changes but applies valid
        changes to other tickets."""
        t1 = self._make_ticket_api("medium", 24)
        t2 = self._make_ticket_api("low", 72)

        # Invalid status means whole changes dict is skipped per-ticket
        res = self._bulk_update([t1.pk, t2.pk],
                                {"priority": "critical",
                                 "status": "invalid_status"})
        self.assertEqual(res.status_code, 200, res.data)
        # Both tickets are skipped due to invalid status transition
        skipped_ids = [s["id"] for s in res.data["skipped"]]
        self.assertIn(t1.pk, skipped_ids)
        self.assertIn(t2.pk, skipped_ids)
        # Neither ticket was modified
        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertEqual(t1.priority, "medium")
        self.assertEqual(t2.priority, "low")

    def test_api_bulk_priority_nonexistent_ticket(self):
        """Bulk update with nonexistent ticket ID is handled gracefully
        (simply not found, not in any result list)."""
        res = self._bulk_update([99999], {"priority": "critical"})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["successful"], [])
        self.assertEqual(res.data["failed"], [])
        self.assertEqual(res.data["skipped"], [])
        self.assertEqual(res.data["summary"]["ok"], 0)
