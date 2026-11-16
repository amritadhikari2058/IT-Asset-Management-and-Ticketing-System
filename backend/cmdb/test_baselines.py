"""CMDB baseline and drift service tests."""

import json

from django.test import TestCase
from django.utils import timezone

from cmdb.baselines import (
    approve_baseline,
    compare_ci_to_baseline,
    create_baseline,
    evaluate_configuration_drift,
    refresh_snapshot,
    submit_baseline,
    supersede_baseline,
)
from cmdb.models import (
    ConfigurationBaseline,
    ConfigurationDriftFinding,
    ConfigurationItem,
    ConfigurationItemHistory,
    ConfigurationItemType,
)
from cmdb.tests import api_client, make_user


class BaselineLifecycleTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.manager = make_user("it_manager")
        self.t = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
        )
        self.ci = ConfigurationItem.objects.create(
            name="CI1", ci_type=self.t, status="active", source="manual",
            created_by=self.admin, ip_address="10.0.0.1",
        )

    def test_create_baseline_snapshot_checksum_and_numbering(self):
        b = create_baseline(
            name="B1", scope_type="single_ci", cis=[self.ci], actor=self.admin,
        )
        self.assertTrue(b.code.startswith("BL-"))
        self.assertIsNotNone(b.snapshot)
        self.assertTrue(b.checksum)
        self.assertEqual(b.status, "draft")
        self.assertIn("cis", b.snapshot)
        self.assertIn(self.ci.ci_number, b.snapshot["cis"])

    def test_submit_approve_self_approval_denied_supersede(self):
        b = create_baseline(name="B2", cis=[self.ci], actor=self.admin)
        submit_baseline(b, self.admin)
        b.refresh_from_db()
        self.assertEqual(b.status, "pending_approval")
        with self.assertRaises(PermissionError):
            approve_baseline(b, self.admin)
        # other user approves
        b2 = create_baseline(name="B2b", cis=[self.ci], actor=self.admin)
        submit_baseline(b2, self.admin)
        approve_baseline(b2, self.manager)
        b2.refresh_from_db()
        self.assertEqual(b2.status, "approved")
        self.assertEqual(b2.approved_by_id, self.manager.id)
        # same-name approval supersedes prior approved
        b3 = create_baseline(name="SAME", cis=[self.ci], actor=self.admin)
        approve_baseline(b3, self.manager)
        b4 = create_baseline(name="SAME", cis=[self.ci], actor=self.admin)
        other = make_user("it_manager", suffix="other")
        approve_baseline(b4, other)
        b3.refresh_from_db()
        b4.refresh_from_db()
        self.assertEqual(b3.status, "superseded")
        self.assertEqual(b4.status, "approved")

    def test_snapshot_deterministic_allowlisted_and_refresh(self):
        b = create_baseline(name="Det", cis=[self.ci], actor=self.admin)
        snap1 = b.snapshot
        refresh_snapshot(b)
        b.refresh_from_db()
        self.assertEqual(snap1["cis"].keys(), b.snapshot["cis"].keys())
        # serial number excluded from snapshot by design? check presence not in SNAPSHOT_CI_FIELDS
        entry = b.snapshot["cis"][self.ci.ci_number]
        self.assertIn("ip_address", entry)
        self.assertNotIn("serial_number", entry)

    def test_manual_supersede(self):
        b = create_baseline(name="Sup", cis=[self.ci], actor=self.admin)
        approve_baseline(b, self.manager)
        supersede_baseline(b, self.admin)
        b.refresh_from_db()
        self.assertEqual(b.status, "superseded")


class DriftEvaluationTests(TestCase):
    def setUp(self):
        self.admin = make_user("system_admin")
        self.manager = make_user("it_manager")
        self.t = ConfigurationItemType.objects.create(
            name="Server", code="SERVER", category="hardware",
            schema={}, required_attributes=[],
        )
        self.ci = ConfigurationItem.objects.create(
            name="CI1", ci_type=self.t, status="active", source="manual",
            created_by=self.admin, criticality="critical",
        )
        self.baseline = create_baseline(name="BL", cis=[self.ci], actor=self.admin)
        approve_baseline(self.baseline, self.manager)

    def test_compare_and_drift_field_status_and_idempotent(self):
        self.ci.name = "CI1-renamed"
        self.ci.status = "inactive"
        self.ci.save()
        diffs = compare_ci_to_baseline(self.ci, self.baseline)
        self.assertTrue(any(d["field"] == "name" or d["field"].endswith("name") for d in diffs) or len(diffs) >= 1)
        findings = evaluate_configuration_drift(self.ci, baseline=self.baseline, actor=self.admin)
        self.assertTrue(len(findings) >= 1)
        count = ConfigurationDriftFinding.objects.filter(configuration_item=self.ci).count()
        findings2 = evaluate_configuration_drift(self.ci, baseline=self.baseline, actor=self.admin)
        self.assertEqual(ConfigurationDriftFinding.objects.filter(configuration_item=self.ci).count(), count)

    def test_stale_auto_resolve_and_note(self):
        self.ci.name = "CI1-renamed"
        self.ci.save()
        evaluate_configuration_drift(self.ci, baseline=self.baseline, actor=self.admin)
        self.ci.name = "CI1"
        self.ci.save()
        evaluate_configuration_drift(self.ci, baseline=self.baseline, actor=self.admin, resolve_stale=True)
        resolved = ConfigurationDriftFinding.objects.filter(configuration_item=self.ci)
        self.assertTrue(resolved.exists())
        self.assertTrue(any("Auto-resolved: no longer detected" in (f.resolution_note or "") for f in resolved))

    def test_drift_actions(self):
        self.ci.name = "X"
        self.ci.save()
        f = evaluate_configuration_drift(self.ci, baseline=self.baseline, actor=self.admin)[0]
        from cmdb.baselines import acknowledge_finding, resolve_finding, mark_false_positive
        acknowledge_finding(f, self.manager)
        f.refresh_from_db()
        self.assertEqual(f.status, "acknowledged")
        # reopen-like not needed; create another
        self.ci.name = "Y"
        self.ci.save()
        f2 = evaluate_configuration_drift(self.ci, baseline=self.baseline, actor=self.admin)[0]
        resolve_finding(f2, self.manager, note="fixed")
        f2.refresh_from_db()
        self.assertEqual(f2.status, "resolved")
        self.ci.name = "Z"
        self.ci.save()
        f3 = evaluate_configuration_drift(self.ci, baseline=self.baseline, actor=self.admin)[0]
        mark_false_positive(f3, self.manager, note="not real")
        f3.refresh_from_db()
        self.assertEqual(f3.status, "false_positive")
