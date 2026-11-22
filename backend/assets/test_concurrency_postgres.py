"""PostgreSQL-only concurrency tests for asset assignment/lifecycle invariants.

These tests require real PostgreSQL row locking and independent transactions.
They are skipped on SQLite.
"""
import threading
from unittest import skipUnless

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from accounts.tests import auth, make_users
from assets.models import Asset, AssetCategory, Assignment, Maintenance


def _is_postgresql():
    return connection.vendor == "postgresql"


@skipUnless(_is_postgresql(), "PostgreSQL-only: requires real row locks/constraints (SQLite skipped)")
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AssetAssignmentConcurrencyPostgresTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.emp2 = User.objects.create_user(
            username="E2", email="e2@x", password="pw12345678",
            role="employee", employee_id="E2", home_department=self.dep)
        self.cat = AssetCategory.objects.create(name="Laptop")

    def _make_asset(self, tag="A1", **kw):
        defaults = dict(asset_tag=tag, name=f"Asset {tag}", category=self.cat, status="available")
        defaults.update(kw)
        return Asset.objects.create(**defaults)

    def _run_concurrent(self, fn1, fn2):
        barrier = threading.Barrier(2)
        results = [None, None]
        errors = [None, None]

        def worker(idx, fn):
            try:
                close_old_connections()
                c = APIClient()
                barrier.wait(timeout=15)
                results[idx] = fn(c)
            except Exception as exc:
                errors[idx] = exc
            finally:
                connections.close_all()

        t1 = threading.Thread(target=worker, args=(0, fn1))
        t2 = threading.Thread(target=worker, args=(1, fn2))
        t1.start(); t2.start()
        t1.join(timeout=60); t2.join(timeout=60)
        if t1.is_alive() or t2.is_alive():
            self.fail("Concurrent workers did not complete within timeout")
        for e in errors:
            if e is not None:
                raise e
        return results[0], results[1]

    def _resp(self, resp):
        return {"status": resp.status_code, "data": getattr(resp, "data", None)}

    def test_concurrent_assign_same_asset_different_employees(self):
        """Scenario A: at most one open assignment; no duplicate active assignment."""
        asset = self._make_asset("PA1")

        def a1(c):
            auth(c, self.mgr)
            r = c.post(f"/api/assets/{asset.pk}/assign/", {"assigned_to": self.emp.pk}, format="json")
            return self._resp(r)

        def a2(c):
            auth(c, self.mgr)
            r = c.post(f"/api/assets/{asset.pk}/assign/", {"assigned_to": self.emp2.pk}, format="json")
            return self._resp(r)

        r1, r2 = self._run_concurrent(a1, a2)
        statuses = sorted([r1["status"], r2["status"]])
        self.assertIn(statuses, [[200, 400], [200, 409]], (r1, r2))

        asset.refresh_from_db()
        open_assignments = list(Assignment.objects.filter(asset=asset, returned_at__isnull=True))
        self.assertEqual(len(open_assignments), 1, (r1, r2))
        winner = open_assignments[0].assigned_to_id
        self.assertIn(winner, [self.emp.pk, self.emp2.pk])
        self.assertEqual(asset.status, "assigned")
        self.assertEqual(asset.assigned_to_id, winner)

    def test_concurrent_assign_and_return(self):
        """Scenario B: serialized ordering yields consistent state; no duplicates."""
        asset = self._make_asset("PA2")
        # Pre-assign to emp so return is meaningful; also allows assign-to-emp2 race.
        Assignment.objects.create(asset=asset, assigned_to=self.emp, assigned_by=self.admin)
        asset.assigned_to = self.emp
        asset.status = "assigned"
        asset.save(update_fields=["assigned_to", "status"])

        def do_return(c):
            auth(c, self.mgr)
            r = c.post(f"/api/assets/{asset.pk}/return_asset/", {}, format="json")
            return self._resp(r)

        def do_assign(c):
            auth(c, self.mgr)
            r = c.post(f"/api/assets/{asset.pk}/assign/", {"assigned_to": self.emp2.pk}, format="json")
            return self._resp(r)

        r1, r2 = self._run_concurrent(do_return, do_assign)
        self.assertNotIn(500, [r1["status"], r2["status"]], (r1, r2))
        self.assertTrue(all(s in (200, 400, 409) for s in [r1["status"], r2["status"]]), (r1, r2))

        asset.refresh_from_db()
        open_assignments = list(Assignment.objects.filter(asset=asset, returned_at__isnull=True))
        self.assertLessEqual(len(open_assignments), 1, (r1, r2))
        if len(open_assignments) == 1:
            self.assertEqual(asset.status, "assigned")
            self.assertEqual(asset.assigned_to_id, open_assignments[0].assigned_to_id)
        else:
            self.assertEqual(asset.status, "available")
            self.assertIsNone(asset.assigned_to_id)

    def test_concurrent_assign_and_retire(self):
        """Scenario C: no duplicate open assignment; retired asset has no active holder."""
        asset = self._make_asset("PA3")

        def do_assign(c):
            auth(c, self.mgr)
            r = c.post(f"/api/assets/{asset.pk}/assign/", {"assigned_to": self.emp.pk}, format="json")
            return self._resp(r)

        def do_retire(c):
            auth(c, self.mgr)
            r = c.post(f"/api/assets/{asset.pk}/retire/", {}, format="json")
            return self._resp(r)

        r1, r2 = self._run_concurrent(do_assign, do_retire)
        self.assertNotIn(500, [r1["status"], r2["status"]], (r1, r2))

        asset.refresh_from_db()
        open_assignments = list(Assignment.objects.filter(asset=asset, returned_at__isnull=True))
        self.assertLessEqual(len(open_assignments), 1, (r1, r2))
        if asset.status == "retired":
            self.assertIsNone(asset.assigned_to_id)
            self.assertEqual(len(open_assignments), 0)
        elif asset.status == "assigned":
            self.assertEqual(len(open_assignments), 1)
            self.assertEqual(asset.assigned_to_id, open_assignments[0].assigned_to_id)
        else:
            self.fail(f"Unexpected final status {asset.status}: {(r1, r2)}")

    def test_concurrent_hard_delete_and_protected_reference_creation(self):
        """Scenario D: no 500; DB constraints intact; no broken references."""
        asset = self._make_asset("PA4")
        asset_pk = asset.pk

        def do_hard_delete(c):
            auth(c, self.admin)
            r = c.post(f"/api/assets/{asset_pk}/hard_delete/", {"confirm": str(asset_pk)}, format="json")
            return self._resp(r)

        def do_create_maintenance(c):
            auth(c, self.mgr)
            r = c.post("/api/assets/maintenance/", {
                "asset": asset_pk,
                "title": "Concurrent maint",
                "maintenance_type": "preventive",
                "status": "scheduled",
                "scheduled_date": timezone.now().isoformat(),
            }, format="json")
            return self._resp(r)

        r1, r2 = self._run_concurrent(do_hard_delete, do_create_maintenance)
        self.assertNotIn(500, [r1["status"], r2["status"]], (r1, r2))

        asset_exists = Asset.all_objects.filter(pk=asset_pk).exists()
        maints = Maintenance.objects.filter(asset_id=asset_pk).count()
        if not asset_exists:
            # Asset deleted - maintenance must not reference a nonexistent asset.
            self.assertEqual(maints, 0, (r1, r2))
            self.assertIn(r1["status"], (200, 409), r1)
            # maintenance create should have failed if asset gone
            self.assertIn(r2["status"], (400, 404, 409), r2)
        else:
            # Asset still exists; hard delete must have been rejected or not won.
            self.assertIn(r1["status"], (409, 400), r1)
            # maintenance may or may not exist depending on ordering
            self.assertIn(r2["status"], (201, 400, 409), r2)

    def test_concurrent_duplicate_assignment_same_employee(self):
        """Scenario E: unique constraint + app handling yield single active assignment."""
        asset = self._make_asset("PA5")

        def do_assign(c):
            auth(c, self.mgr)
            r = c.post(f"/api/assets/{asset.pk}/assign/", {"assigned_to": self.emp.pk}, format="json")
            return self._resp(r)

        r1, r2 = self._run_concurrent(do_assign, do_assign)
        statuses = sorted([r1["status"], r2["status"]])
        self.assertIn(statuses, [[200, 400], [200, 409]], (r1, r2))

        asset.refresh_from_db()
        open_assignments = Assignment.objects.filter(asset=asset, returned_at__isnull=True)
        self.assertEqual(open_assignments.count(), 1)
        self.assertEqual(asset.status, "assigned")
        self.assertEqual(asset.assigned_to_id, self.emp.pk)
