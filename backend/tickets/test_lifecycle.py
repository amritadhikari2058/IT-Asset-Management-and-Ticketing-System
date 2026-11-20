"""Ticket lifecycle regression tests: resolution, reopening, SLA pauses, history.

Covers the full ticket lifecycle from open through waiting, resolution,
reopening, and subsequent resolution. Tests timestamps, actor attribution,
history records, active pause count, and effective SLA state after each
transition sequence.
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from accounts.tests import auth, make_users
from tickets.models import (
    Ticket, TicketCategory, TicketResolutionCode, TicketHistory,
    TicketSlaPause, TicketSLA,
)
from tickets.resolution_services import (
    request_information, requester_replied, resolve_ticket,
    close_ticket, reopen_ticket, _active_pause,
)
from tickets.advanced_serializers import (
    RequestInformationSerializer, ResolveTicketSerializer,
    CloseTicketSerializer, ReopenTicketSerializer,
)


def make_resolution_code(name="fixed", code="fixed", **kw):
    defaults = {
        "name": name, "code": code, "is_active": True,
        "requires_summary": False, "requires_kb_link": False,
        "marks_known_error": False,
    }
    defaults.update(kw)
    return TicketResolutionCode.objects.create(**defaults)


class BaseTicketLifecycle(TestCase):
    """Shared setup for ticket lifecycle tests."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name="Hardware")
        self.rc = make_resolution_code()
        # Create SLA config so tickets get sla_due_at
        self.sla = TicketSLA.objects.create(
            priority="medium", target_resolution_hours=24,
            is_active=True, is_deleted=False,
        )

    def make_ticket(self, status="open", priority="medium", **kw):
        defaults = {
            "title": "Test Ticket",
            "description": "Test description",
            "category": self.tcat,
            "requester": self.emp,
            "department": self.dep,
            "priority": priority,
            "status": status,
        }
        defaults.update(kw)
        t = Ticket.objects.create(**defaults)
        # Ensure sla_due_at is set (mirrors perform_create behavior)
        if not t.sla_due_at:
            from tickets.models import TicketSLA
            sla = TicketSLA.objects.filter(
                priority=t.priority, is_active=True, is_deleted=False
            ).first()
            if sla:
                t.sla_due_at = timezone.now() + timedelta(
                    hours=sla.target_resolution_hours
                )
                t.save(update_fields=["sla_due_at"])
        return t

    def valid_request_info_data(self):
        ser = RequestInformationSerializer(data={
            "message": "Please provide more details",
        })
        ser.is_valid()
        return ser.validated_data

    def valid_resolve_data(self):
        ser = ResolveTicketSerializer(data={
            "resolution_code": self.rc.pk,
            "resolution_summary": "Fixed the issue",
        })
        assert ser.is_valid(), ser.errors
        return ser.validated_data

    def valid_reopen_data(self):
        ser = ReopenTicketSerializer(data={
            "reason": "Issue not actually fixed",
        })
        ser.is_valid()
        return ser.validated_data

    def valid_close_data(self):
        ser = CloseTicketSerializer(data={
            "reason": "Resolved and verified",
        })
        ser.is_valid()
        return ser.validated_data


class LifecycleTransitionTests(BaseTicketLifecycle):
    """Valid and invalid lifecycle transitions."""

    def test_open_to_waiting_requester(self):
        t = self.make_ticket(status="open")
        auth_client = self.mgr  # use directly, not APIClient

        ticket, note, pause = request_information(
            t, self.valid_request_info_data(), self.mgr,
        )

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "waiting_requester")
        self.assertIsNotNone(pause)
        self.assertEqual(pause.pause_type, "waiting_requester")
        self.assertEqual(pause.started_by, self.mgr)
        self.assertIsNone(pause.ended_at)
        # History record
        self.assertTrue(
            TicketHistory.objects.filter(
                ticket=ticket, action="request_information",
            ).exists()
        )

    def test_waiting_requester_to_in_progress_via_requester_reply(self):
        t = self.make_ticket(status="open")
        request_information(
            t, self.valid_request_info_data(), self.mgr,
        )
        t.refresh_from_db()

        ticket = requester_replied(t, self.emp, "Here are the details")

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")
        # Pause should be ended
        pause = _active_pause(ticket)
        self.assertIsNone(pause)
        # History
        self.assertTrue(
            TicketHistory.objects.filter(
                ticket=ticket, action="requester_replied",
            ).exists()
        )

    def test_requester_reply_invalid_status_raises(self):
        t = self.make_ticket(status="open")
        with self.assertRaises(Exception) as ctx:
            requester_replied(t, self.emp, "Details")
        # Should raise ValidationError for wrong status
        self.assertIn("waiting_requester", str(ctx.exception))

    def test_open_to_resolved(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        ticket = resolve_ticket(t, self.valid_resolve_data(), self.mgr)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")
        self.assertEqual(ticket.resolved_by, self.mgr)
        self.assertIsNotNone(ticket.resolved_at)
        self.assertFalse(ticket.sla_breached)
        # Pause should be ended if any
        pause = _active_pause(ticket)
        self.assertIsNone(pause)

    def test_resolve_clears_sla_breached(self):
        t = self.make_ticket(status="open", priority="high")
        # Manually breach the SLA
        t.sla_breached = True
        t.save(update_fields=["sla_breached"])

        ticket = resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        ticket.refresh_from_db()
        self.assertFalse(ticket.sla_breached)

    def test_resolve_creates_history(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()
        self.assertTrue(
            TicketHistory.objects.filter(
                ticket=t, action="resolved",
            ).exists()
        )

    def test_resolve_with_active_pause_ends_it(self):
        t = self.make_ticket(status="waiting_requester")
        # Create a pause manually (simulating direct status change path)
        pause = TicketSlaPause.objects.create(
            ticket=t, pause_type="waiting_requester",
            started_by=self.mgr, started_at=timezone.now(),
        )

        t.assignee = self.mgr
        t.save(update_fields=["assignee"])
        ticket = resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        ticket.refresh_from_db()

        pause.refresh_from_db()
        self.assertIsNotNone(pause.ended_at)
        self.assertEqual(pause.ended_by, self.mgr)

    def test_close_resolved_ticket(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        ticket = close_ticket(t, self.mgr, "All good", None)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "closed")
        self.assertIsNotNone(ticket.closed_at)

    def test_close_requires_resolved(self):
        t = self.make_ticket(status="open")
        with self.assertRaises(Exception) as ctx:
            close_ticket(t, self.mgr, "Oops", None)
        self.assertIn("resolved", str(ctx.exception))

    def test_reopen_resolved_ticket(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        ticket = reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")
        self.assertEqual(ticket.reopen_count, 1)
        self.assertIsNotNone(ticket.reopened_at)
        self.assertEqual(ticket.reopened_by, self.mgr)
        self.assertIsNone(ticket.resolved_at)
        self.assertIsNone(ticket.resolved_by)
        self.assertFalse(ticket.sla_breached)

    def test_reopen_by_requester(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        ticket = reopen_ticket(t, self.valid_reopen_data(), self.emp)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")
        self.assertEqual(ticket.reopened_by, self.emp)

    def test_reopen_clears_sla_breached(self):
        t = self.make_ticket(status="open", priority="high")
        t.sla_breached = True
        t.save(update_fields=["sla_breached"])
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()
        t.sla_breached = True
        t.save(update_fields=["sla_breached"])

        ticket = reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        ticket.refresh_from_db()
        self.assertFalse(ticket.sla_breached)

    def test_reopen_creates_history(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        t.refresh_from_db()
        self.assertTrue(
            TicketHistory.objects.filter(
                ticket=t, action="reopened",
            ).exists()
        )

    def test_reopen_invalid_status_raises(self):
        t = self.make_ticket(status="open")
        with self.assertRaises(Exception) as ctx:
            reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        self.assertIn("Cannot reopen", str(ctx.exception))

    def test_reopen_merged_ticket_raises(self):
        t = self.make_ticket(status="merged")
        with self.assertRaises(Exception) as ctx:
            reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        self.assertIn("merged", str(ctx.exception))

    def test_reopen_cancelled_ticket_raises(self):
        t = self.make_ticket(status="cancelled")
        with self.assertRaises(Exception) as ctx:
            reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        self.assertIn("cancelled", str(ctx.exception))

    def test_reopen_requires_reason(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        with self.assertRaises(Exception) as ctx:
            reopen_ticket(t, {"reason": ""}, self.mgr)
        self.assertIn("Reason is required", str(ctx.exception))


class LifecycleSequenceTests(BaseTicketLifecycle):
    """Realistic lifecycle sequences from the ticket requirements."""

    def test_sequence_1_open_to_waiting_requester_to_open(self):
        """Sequence 1: Open → waiting_requester → in_progress."""
        t = self.make_ticket(status="open")

        # Open → waiting_requester
        ticket, note, pause = request_information(
            t, self.valid_request_info_data(), self.mgr,
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "waiting_requester")
        self.assertIsNotNone(_active_pause(ticket))

        # waiting_requester → in_progress (via requester reply)
        ticket = requester_replied(ticket, self.emp, "Here are details")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")
        self.assertIsNone(_active_pause(ticket))

    def test_sequence_2_open_to_waiting_third_party_to_in_progress(self):
        """Sequence 2: Open → waiting_third_party → in_progress."""
        t = self.make_ticket(status="open")

        # Open → waiting_third_party via direct status change
        t.status = "waiting_third_party"
        t.version = (t.version or 1) + 1
        t.save(update_fields=["status", "version", "updated_at"])

        # Create pause (mirrors what _manage_sla_pause does in views)
        TicketSlaPause.objects.create(
            ticket=t, pause_type="waiting_third_party",
            started_by=self.mgr, started_at=timezone.now(),
            reason="waiting_third_party",
        )
        t.refresh_from_db()
        self.assertEqual(t.status, "waiting_third_party")
        self.assertIsNotNone(_active_pause(t))

        # waiting_third_party → in_progress
        t.status = "in_progress"
        t.version = (t.version or 1) + 1
        t.save(update_fields=["status", "version", "updated_at"])

        # Pause should be ended by model save() when leaving waiting state
        t.refresh_from_db()
        self.assertEqual(t.status, "in_progress")
        pause = _active_pause(t)
        self.assertIsNone(pause)

    def test_sequence_3_open_to_resolved_to_reopened(self):
        """Sequence 3: Open → resolved → reopened."""
        t = self.make_ticket(status="open", assignee=self.mgr)

        # Open → resolved
        ticket = resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")
        self.assertIsNotNone(ticket.resolved_at)
        self.assertEqual(ticket.resolved_by, self.mgr)

        # resolved → reopened
        ticket = reopen_ticket(ticket, self.valid_reopen_data(), self.mgr)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")
        self.assertEqual(ticket.reopen_count, 1)
        self.assertIsNotNone(ticket.reopened_at)
        self.assertEqual(ticket.reopened_by, self.mgr)
        self.assertIsNone(ticket.resolved_at)

    def test_sequence_4_reopened_to_waiting_requester_to_reopened(self):
        """Sequence 4: Reopened → waiting_requester → reopened."""
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()
        reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        t.refresh_from_db()

        # Reopened → waiting_requester
        ticket, note, pause = request_information(
            t, self.valid_request_info_data(), self.mgr,
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "waiting_requester")
        self.assertIsNotNone(_active_pause(ticket))

        # waiting_requester → resolved (reopened again)
        ticket = resolve_ticket(ticket, self.valid_resolve_data(), self.mgr)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")
        self.assertEqual(ticket.reopen_count, 1)

    def test_sequence_5_reopened_resolved_again(self):
        """Sequence 5: Reopened → resolved again."""
        t = self.make_ticket(status="open", assignee=self.mgr)

        # First resolution
        ticket = resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        ticket.refresh_from_db()
        first_resolved_at = ticket.resolved_at

        # Reopen
        ticket = reopen_ticket(ticket, self.valid_reopen_data(), self.mgr)
        ticket.refresh_from_db()
        self.assertEqual(ticket.reopen_count, 1)

        # Resolve again
        ticket = resolve_ticket(ticket, self.valid_resolve_data(), self.mgr)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "resolved")
        self.assertEqual(ticket.reopen_count, 1)
        # resolved_at should be updated to new time
        self.assertGreater(ticket.resolved_at, first_resolved_at)

    def test_sequence_6_repeated_resolve_reopen_cycles(self):
        """Sequence 6: Repeated resolve/reopen cycles."""
        t = self.make_ticket(status="open", assignee=self.mgr)

        for i in range(3):
            # Resolve
            ticket = resolve_ticket(t, self.valid_resolve_data(), self.mgr)
            ticket.refresh_from_db()
            self.assertEqual(ticket.status, "resolved")
            self.assertEqual(ticket.reopen_count, i)

            # Reopen
            ticket = reopen_ticket(ticket, self.valid_reopen_data(), self.mgr)
            ticket.refresh_from_db()
            self.assertEqual(ticket.status, "in_progress")
            self.assertEqual(ticket.reopen_count, i + 1)
            self.assertEqual(ticket.reopened_by, self.mgr)

        # Final state: reopened 3 times
        self.assertEqual(ticket.reopen_count, 3)

    def test_sequence_7_resolution_with_historical_pauses(self):
        """Sequence 7: Resolution while ticket has historical pause records."""
        t = self.make_ticket(status="open")

        # Create multiple historical pauses (e.g., from previous waiting states)
        for i in range(2):
            TicketSlaPause.objects.create(
                ticket=t, pause_type="waiting_requester",
                started_by=self.mgr,
                started_at=timezone.now() - timedelta(hours=i * 2),
                ended_at=timezone.now() - timedelta(hours=i * 2 + 1),
                ended_by=self.mgr,
            )

        # Now resolve
        t.assignee = self.mgr
        t.save(update_fields=["assignee"])
        ticket = resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        ticket.refresh_from_db()

        self.assertEqual(ticket.status, "resolved")
        # Historical pauses should be preserved
        self.assertEqual(ticket.sla_pauses.filter(is_deleted=False).count(), 2)
        # No active pause
        self.assertIsNone(_active_pause(ticket))


class LifecyclePermissionTests(BaseTicketLifecycle):
    """Permission checks for lifecycle operations."""

    def test_employee_cannot_resolve(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        with self.assertRaises(Exception) as ctx:
            resolve_ticket(t, self.valid_resolve_data(), self.emp)
        self.assertIn("Only IT staff", str(ctx.exception))

    def test_employee_cannot_reopen_as_non_requester(self):
        # Create a ticket where emp is the requester
        t = self.make_ticket(status="open", assignee=self.mgr, requester=self.emp)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        # Create another employee who is NOT the requester
        emp2 = self._make_employee("emp2@x", "E2")
        with self.assertRaises(Exception) as ctx:
            reopen_ticket(t, self.valid_reopen_data(), emp2)
        # Must be permission denied (not requester, not IT staff)
        self.assertIn("Only the requester or IT staff", str(ctx.exception))

    def test_employee_can_reopen_own_ticket(self):
        t = self.make_ticket(status="open", requester=self.emp, assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        ticket = reopen_ticket(t, self.valid_reopen_data(), self.emp)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "in_progress")

    def test_non_requester_employee_cannot_request_information(self):
        t = self.make_ticket(status="open", requester=self.emp)
        # Create an employee who is not the requester
        other_emp = self._make_employee("other@x", "O1")
        with self.assertRaises(Exception) as ctx:
            request_information(t, self.valid_request_info_data(), other_emp)
        # Employee is not IT staff, should fail
        self.assertIn("Only IT staff", str(ctx.exception))

    def test_unauthorized_reopen_raises_permission_denied(self):
        # Create a ticket where emp is the requester
        t = self.make_ticket(status="open", assignee=self.mgr, requester=self.emp)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        # Create an employee who is neither requester nor IT staff
        other_emp = self._make_employee("other@x", "O1")
        with self.assertRaises(Exception) as ctx:
            reopen_ticket(t, self.valid_reopen_data(), other_emp)
        # Must be permission denied (not requester, not IT staff)
        self.assertIn("Only the requester or IT staff", str(ctx.exception))

    def _make_employee(self, email, employee_id):
        from accounts.models import Department, User
        dep = Department.objects.first() or self.dep
        return User.objects.create_user(
            username=email, email=email, employee_id=employee_id,
            password="pw12345678", role="employee",
            home_department=dep, is_active=True)


class LifecycleHistoryIntegrityTests(BaseTicketLifecycle):
    """History records are created correctly for lifecycle transitions."""

    def test_request_information_history(self):
        t = self.make_ticket(status="open")
        ticket, note, pause = request_information(
            t, self.valid_request_info_data(), self.mgr,
        )
        hist = TicketHistory.objects.filter(
            ticket=ticket, action="request_information",
        ).first()
        self.assertIsNotNone(hist)
        self.assertEqual(hist.actor, self.mgr)
        self.assertEqual(hist.old_values.get("status"), "open")
        self.assertEqual(hist.new_values.get("status"), "waiting_requester")

    def test_resolve_history(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()
        hist = TicketHistory.objects.filter(
            ticket=t, action="resolved",
        ).first()
        self.assertIsNotNone(hist)
        self.assertEqual(hist.actor, self.mgr)
        self.assertIn("resolved_at", hist.new_values)

    def test_reopen_history(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()
        reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        t.refresh_from_db()
        hist = TicketHistory.objects.filter(
            ticket=t, action="reopened",
        ).first()
        self.assertIsNotNone(hist)
        self.assertEqual(hist.actor, self.mgr)
        self.assertEqual(hist.new_values.get("reopen_count"), 1)
        self.assertIn("note", hist.__dict__)
        self.assertEqual(hist.note, "Issue not actually fixed")


class LifecyclePauseTests(BaseTicketLifecycle):
    """SLA pause behavior during lifecycle transitions."""

    def test_pause_created_on_waiting_requester(self):
        t = self.make_ticket(status="open")
        ticket, note, pause = request_information(
            t, self.valid_request_info_data(), self.mgr,
        )
        self.assertIsNotNone(pause)
        self.assertEqual(pause.pause_type, "waiting_requester")
        self.assertEqual(pause.started_by, self.mgr)

    def test_pause_ended_on_requester_reply(self):
        t = self.make_ticket(status="open")
        ticket, note, pause = request_information(
            t, self.valid_request_info_data(), self.mgr,
        )
        self.assertIsNotNone(pause)

        ticket = requester_replied(ticket, self.emp, "Details")
        ticket.refresh_from_db()
        pause.refresh_from_db()
        self.assertIsNotNone(pause.ended_at)
        self.assertEqual(pause.ended_by, self.emp)

    def test_no_active_pause_after_resolution(self):
        t = self.make_ticket(status="waiting_requester")
        TicketSlaPause.objects.create(
            ticket=t, pause_type="waiting_requester",
            started_by=self.mgr, started_at=timezone.now(),
        )
        t.assignee = self.mgr
        t.save(update_fields=["assignee"])

        ticket = resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        ticket.refresh_from_db()
        pause = _active_pause(ticket)
        self.assertIsNone(pause)

    def test_no_active_pause_after_reopen(self):
        """Even if a pause somehow exists after resolution, reopen ends it."""
        t = self.make_ticket(status="open", assignee=self.mgr)

        # Create an orphan pause (edge case)
        TicketSlaPause.objects.create(
            ticket=t, pause_type="waiting_requester",
            started_by=self.mgr, started_at=timezone.now(),
        )

        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        ticket = reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        ticket.refresh_from_db()
        pause = _active_pause(ticket)
        self.assertIsNone(pause)

    def test_pause_attribution_on_request_information(self):
        t = self.make_ticket(status="open")
        ticket, note, pause = request_information(
            t, self.valid_request_info_data(), self.admin,
        )
        pause.refresh_from_db()
        self.assertEqual(pause.started_by, self.admin)
        self.assertEqual(pause.ended_by, None)

    def test_pause_attribution_on_requester_reply(self):
        t = self.make_ticket(status="open")
        ticket, note, pause = request_information(
            t, self.valid_request_info_data(), self.mgr,
        )
        ticket = requester_replied(ticket, self.emp, "Details")
        ticket.refresh_from_db()
        pause.refresh_from_db()
        self.assertEqual(pause.ended_by, self.emp)

    def test_pause_attribution_on_resolution(self):
        t = self.make_ticket(status="waiting_requester")
        TicketSlaPause.objects.create(
            ticket=t, pause_type="waiting_requester",
            started_by=self.mgr, started_at=timezone.now(),
        )
        t.assignee = self.admin
        t.save(update_fields=["assignee"])

        ticket = resolve_ticket(t, self.valid_resolve_data(), self.admin)
        ticket.refresh_from_db()
        pause = TicketSlaPause.objects.get(pk=t.pk)
        # The pause was ended by the resolver
        self.assertEqual(pause.ended_by, self.admin)


class LifecycleTimestampTests(BaseTicketLifecycle):
    """Timestamps are set correctly for lifecycle transitions."""

    def test_resolve_sets_resolved_at(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        before = timezone.now()
        ticket = resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        after = timezone.now()

        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.resolved_at)
        self.assertGreaterEqual(ticket.resolved_at, before)
        self.assertLessEqual(ticket.resolved_at, after)

    def test_reopen_sets_reopened_at(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        before = timezone.now()
        ticket = reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        after = timezone.now()

        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.reopened_at)
        self.assertGreaterEqual(ticket.reopened_at, before)
        self.assertLessEqual(ticket.reopened_at, after)
        # resolved_at should be cleared
        self.assertIsNone(ticket.resolved_at)

    def test_resolved_by_attribution(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        ticket = resolve_ticket(t, self.valid_resolve_data(), self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.resolved_by, self.admin)

    def test_reopened_by_attribution(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        ticket = reopen_ticket(t, self.valid_reopen_data(), self.emp)
        ticket.refresh_from_db()
        self.assertEqual(ticket.reopened_by, self.emp)

    def test_resolve_clears_resolved_fields_on_reopen(self):
        """Reopening clears all resolution-related fields."""
        t = self.make_ticket(status="open", assignee=self.mgr)
        ticket = resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        ticket.refresh_from_db()

        self.assertIsNotNone(ticket.resolved_at)
        self.assertIsNotNone(ticket.resolved_by)
        self.assertIsNotNone(ticket.resolution_code)

        ticket = reopen_ticket(ticket, self.valid_reopen_data(), self.mgr)
        ticket.refresh_from_db()

        self.assertIsNone(ticket.resolved_at)
        self.assertIsNone(ticket.resolved_by)
        self.assertIsNone(ticket.resolution_code)
        self.assertEqual(ticket.resolution_summary, "")

    def test_close_sets_closed_at(self):
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        before = timezone.now()
        ticket = close_ticket(t, self.mgr, "Done", None)
        after = timezone.now()

        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.closed_at)
        self.assertGreaterEqual(ticket.closed_at, before)
        self.assertLessEqual(ticket.closed_at, after)


class LifecycleTransactionRollbackTests(BaseTicketLifecycle):
    """Transaction rollback on failure preserves consistency."""

    def test_resolve_rollback_on_conflict(self):
        """Concurrent modification should rollback without partial writes."""
        t = self.make_ticket(status="open", assignee=self.mgr)

        with self.assertRaises(Exception) as ctx:
            resolve_ticket(t, {
                **self.valid_resolve_data(),
                "expected_ticket_version": 999,  # stale version
            }, self.mgr)

        self.assertIn("concurrently", str(ctx.exception))
        t.refresh_from_db()
        self.assertEqual(t.status, "open")  # unchanged

    def test_reopen_rollback_on_conflict(self):
        """Reopen with stale version should rollback."""
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        with self.assertRaises(Exception) as ctx:
            reopen_ticket(t, {
                **self.valid_reopen_data(),
                "expected_ticket_version": 999,
            }, self.mgr)

        self.assertIn("concurrently", str(ctx.exception))
        t.refresh_from_db()
        self.assertEqual(t.status, "resolved")  # unchanged

    def test_request_info_rollback_on_conflict(self):
        """Request info with stale version should rollback."""
        t = self.make_ticket(status="open")

        with self.assertRaises(Exception) as ctx:
            request_information(t, {
                **self.valid_request_info_data(),
                "expected_ticket_version": 999,
            }, self.mgr)

        self.assertIn("concurrently", str(ctx.exception))
        t.refresh_from_db()
        self.assertEqual(t.status, "open")  # unchanged


class LifecycleSLAStateTests(BaseTicketLifecycle):
    """Effective SLA state after lifecycle transitions."""

    def test_sla_due_at_preserved_on_reopen(self):
        """Reopening preserves the original sla_due_at (does not reset)."""
        t = self.make_ticket(status="open")
        original_sla_due = t.sla_due_at

        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        ticket = reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        ticket.refresh_from_db()

        # sla_due_at should be preserved
        self.assertEqual(ticket.sla_due_at, original_sla_due)

    def test_sla_paused_duration_calculated_correctly(self):
        """Paused duration is correctly added to sla_due_at."""
        t = self.make_ticket(status="open")
        original_due = t.sla_due_at

        # Create a 2-hour pause
        pause_start = timezone.now() - timedelta(hours=2)
        pause_end = timezone.now() - timedelta(hours=1)
        TicketSlaPause.objects.create(
            ticket=t, pause_type="waiting_requester",
            started_by=self.mgr,
            started_at=pause_start,
            ended_at=pause_end,
            ended_by=self.mgr,
        )

        t.refresh_from_db()
        effective_due = t.get_sla_due_at()
        # Effective due should be original + ~1 hour (the paused duration)
        expected = original_due + timedelta(hours=1)
        # Allow 2 second tolerance for test execution time
        diff = abs((effective_due - expected).total_seconds())
        self.assertLessEqual(diff, 2, 
            f"Effective due {effective_due} differs from expected {expected} by {diff}s")

    def test_multiple_pauses_merged_no_double_count(self):
        """Overlapping pauses are merged, not double-counted."""
        t = self.make_ticket(status="open")
        now = timezone.now()

        # Two overlapping pauses: 1-3 and 2-4 (should merge to 1-4 = 3 hours)
        TicketSlaPause.objects.create(
            ticket=t, pause_type="waiting_requester",
            started_by=self.mgr,
            started_at=now - timedelta(hours=3),
            ended_at=now - timedelta(hours=1),
            ended_by=self.mgr,
        )
        TicketSlaPause.objects.create(
            ticket=t, pause_type="waiting_requester",
            started_by=self.mgr,
            started_at=now - timedelta(hours=2),
            ended_at=now,
            ended_by=self.mgr,
        )

        t.refresh_from_db()
        paused_duration = t.get_paused_duration()
        # Should be 3 hours (merged), not 4 hours (sum)
        self.assertEqual(paused_duration, timedelta(hours=3))

    def test_get_effective_sla_with_no_pauses(self):
        """Tickets with no pause records return original sla_due_at."""
        t = self.make_ticket(status="open")
        self.assertEqual(t.get_sla_due_at(), t.sla_due_at)
        self.assertEqual(t.get_effective_sla_due_at(), t.sla_due_at)


class LifecycleDuplicateRecordTests(BaseTicketLifecycle):
    """Repeated operations don't create duplicate lifecycle records."""

    def test_resolve_already_resolved_no_duplicate_history(self):
        """Resolving an already-resolved ticket doesn't create duplicate history."""
        t = self.make_ticket(status="open", assignee=self.mgr)
        initial_history = TicketHistory.objects.filter(ticket=t).count()

        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()
        after_first = TicketHistory.objects.filter(ticket=t).count()

        # Try to resolve again - should return early
        result = resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()
        after_second = TicketHistory.objects.filter(ticket=t).count()

        # History should only increase once
        self.assertEqual(after_second - initial_history, 1)
        self.assertEqual(after_second, after_first)

    def test_reopen_increments_count(self):
        """Each reopen increments reopen_count."""
        t = self.make_ticket(status="open", assignee=self.mgr)
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()

        self.assertEqual(t.reopen_count, 0)

        reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        t.refresh_from_db()
        self.assertEqual(t.reopen_count, 1)

        # Need to resolve again before reopening
        resolve_ticket(t, self.valid_resolve_data(), self.mgr)
        t.refresh_from_db()
        reopen_ticket(t, self.valid_reopen_data(), self.mgr)
        t.refresh_from_db()
        self.assertEqual(t.reopen_count, 2)
