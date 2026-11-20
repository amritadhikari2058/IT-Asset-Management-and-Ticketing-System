"""Focused tests for entitlement reconciliation, allocation enforcement and compliance re-evaluation."""

import threading
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Department, User
from assets.models import Asset, AssetCategory, Vendor
from licensing.models import (
    LicenseAgreement,
    LicenseAllocation,
    LicenseComplianceFinding,
    SoftwareProduct,
)
from licensing.services import (
    ACTIVE_ALLOCATED_STATUSES,
    CONSUMING_ALLOCATION_STATUSES,
    activate_allocation,
    allocate_license,
    evaluate_license_compliance,
    get_agreement_entitlement_limit,
    reconcile_agreement_entitlements,
    remediate_compliance_finding,
    resolve_compliance_finding,
    revoke_allocation,
    reconcile_entitlements_summary,
    suspend_allocation,
)


class LicensingReconciliationTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Engineering", code="REC-ENG")
        self.it_dept = Department.objects.create(name="IT Services", code="REC-IT")

        self.sys_admin = User.objects.create_user(
            username="rec-admin@test.com",
            email="rec-admin@test.com",
            employee_id="REC-ADM",
            role="system_admin",
            home_department=self.it_dept,
        )
        self.it_manager = User.objects.create_user(
            username="rec-manager@test.com",
            email="rec-manager@test.com",
            employee_id="REC-MGR",
            role="it_manager",
            home_department=self.it_dept,
        )
        self.it_support = User.objects.create_user(
            username="rec-support@test.com",
            email="rec-support@test.com",
            employee_id="REC-SUP",
            role="it_support",
            home_department=self.it_dept,
        )
        self.employee = User.objects.create_user(
            username="rec-employee@test.com",
            email="rec-employee@test.com",
            employee_id="REC-EMP",
            role="employee",
            home_department=self.dept,
        )
        self.other_employee = User.objects.create_user(
            username="rec-employee2@test.com",
            email="rec-employee2@test.com",
            employee_id="REC-EMP2",
            role="employee",
            home_department=self.dept,
        )

        self.vendor = Vendor.objects.create(name="Reconciliation Vendor", code="REC-V")
        self.category = AssetCategory.objects.create(name="Reconciliation Laptops")
        self.asset = Asset.objects.create(
            asset_tag="REC-ASSET-001",
            name="Reconciliation Laptop",
            category=self.category,
            department=self.dept,
            status="available",
        )

        self.product = SoftwareProduct.objects.create(
            name="Reconciliation Suite",
            publisher="Reconciliation Corp",
            code="REC-SUITE",
            category="development",
            license_model="named_user",
            license_required=True,
            approved_status="approved",
            created_by=self.sys_admin,
        )

        self.client = APIClient()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _agreement(self, number, *, quantity=5, status="active", license_model="named_user",
                   concurrent_limit=0, expiry_date=None, agreement_type="subscription", vendor=None):
        return LicenseAgreement.objects.create(
            agreement_number=number,
            software_product=self.product,
            vendor=vendor or self.vendor,
            status=status,
            license_model=license_model,
            agreement_type=agreement_type,
            quantity_purchased=quantity,
            concurrent_limit=concurrent_limit,
            start_date=timezone.now().date() - timedelta(days=30),
            expiry_date=expiry_date or (timezone.now().date() + timedelta(days=365)),
            created_by=self.sys_admin,
        )

    def _allocation(self, agreement, status_value, user=None, reference="REC-REF"):
        return LicenseAllocation.objects.create(
            agreement=agreement,
            allocation_type="user",
            assigned_user=user or self.employee,
            allocation_reference=reference,
            status=status_value,
        )

    # ------------------------------------------------------------------
    # entitlement calculation
    # ------------------------------------------------------------------
    def test_reconciliation_counts_only_consuming_statuses(self):
        agreement = self._agreement("LIC-REC-001", quantity=5)
        self._allocation(agreement, "active", self.employee, "REF-A")
        self._allocation(agreement, "assigned", self.other_employee, "REF-B")
        self._allocation(agreement, "reserved", reference="REF-C")
        self._allocation(agreement, "suspended", reference="REF-D")
        self._allocation(agreement, "revoked", reference="REF-E")
        self._allocation(agreement, "expired", reference="REF-F")

        rec = reconcile_agreement_entitlements(agreement)

        self.assertEqual(rec["purchased_entitlement_quantity"], 5)
        self.assertEqual(rec["active_allocated_quantity"], 2)
        self.assertEqual(rec["reserved_quantity"], 1)
        self.assertEqual(rec["consuming_quantity"], 3)
        self.assertEqual(rec["available_quantity"], 2)
        self.assertEqual(rec["overallocated_quantity"], 0)
        self.assertEqual(rec["suspended_allocation_quantity"], 1)
        self.assertEqual(rec["released_allocation_quantity"], 1)
        self.assertEqual(rec["expired_allocation_quantity"], 1)
        self.assertEqual(rec["utilization_percent"], 60.0)
        self.assertTrue(rec["utilization_calculable"])

    def test_concurrent_license_model_uses_concurrent_limit(self):
        agreement = self._agreement(
            "LIC-REC-002", quantity=500, license_model="concurrent", concurrent_limit=2
        )
        self._allocation(agreement, "active", self.employee, "REF-CONC-1")
        self._allocation(agreement, "active", self.other_employee, "REF-CONC-2")

        self.assertEqual(get_agreement_entitlement_limit(agreement), 2)
        rec = reconcile_agreement_entitlements(agreement)
        self.assertEqual(rec["purchased_entitlement_quantity"], 2)
        self.assertEqual(rec["available_quantity"], 0)
        self.assertEqual(rec["utilization_percent"], 100.0)

    def test_unlimited_and_non_seat_agreements_have_no_misleading_percentage(self):
        agreement = self._agreement(
            "LIC-REC-003", quantity=1, license_model="site", agreement_type="enterprise"
        )
        self._allocation(agreement, "active", self.employee, "REF-UNL-1")

        rec = reconcile_agreement_entitlements(agreement)

        self.assertTrue(rec["is_unlimited"])
        self.assertIsNone(rec["purchased_entitlement_quantity"])
        self.assertIsNone(rec["available_quantity"])
        self.assertIsNone(rec["utilization_percent"])
        self.assertFalse(rec["utilization_calculable"])
        self.assertIn("not calculated", rec["utilization_note"])

    # ------------------------------------------------------------------
    # allocation enforcement
    # ------------------------------------------------------------------
    def test_allocation_rejected_when_entitlement_exhausted(self):
        agreement = self._agreement("LIC-REC-004", quantity=1)
        allocate_license(
            agreement=agreement,
            allocation_type="user",
            assigned_user=self.employee,
            actor=self.it_support,
        )

        with self.assertRaises(ValidationError):
            allocate_license(
                agreement=agreement,
                allocation_type="user",
                assigned_user=self.other_employee,
                actor=self.it_support,
            )

        agreement.refresh_from_db()
        self.assertEqual(agreement.allocations.count(), 1)
        self.assertEqual(agreement.quantity_allocated, 1)
        self.assertEqual(agreement.quantity_available, 0)

    def test_allocation_rejected_for_expired_and_terminated_agreements(self):
        expired = self._agreement(
            "LIC-REC-005", status="active", expiry_date=timezone.now().date() - timedelta(days=1)
        )
        terminated = self._agreement("LIC-REC-006", status="terminated")

        for agreement in (expired, terminated):
            with self.assertRaises(ValidationError):
                allocate_license(
                    agreement=agreement,
                    allocation_type="user",
                    assigned_user=self.employee,
                    actor=self.it_support,
                )
            self.assertEqual(agreement.allocations.count(), 0)

    def test_reactivation_enforces_entitlement_and_release_restores_capacity(self):
        agreement = self._agreement("LIC-REC-007", quantity=1)
        first = allocate_license(
            agreement=agreement,
            allocation_type="user",
            assigned_user=self.employee,
            actor=self.it_support,
        )
        second = self._allocation(agreement, "suspended", self.other_employee, "REF-SUSP")
        agreement.recalculate_counters(save=True)

        with self.assertRaises(ValidationError):
            activate_allocation(second, actor=self.it_support)

        suspend_allocation(first, actor=self.it_support, reason="Temporary leave")
        agreement.refresh_from_db()
        self.assertEqual(agreement.quantity_allocated, 0)

        activated = activate_allocation(second, actor=self.it_support, reason="Back from leave")
        self.assertEqual(activated.status, "active")
        activated.refresh_from_db()
        agreement.refresh_from_db()
        self.assertEqual(agreement.quantity_allocated, 1)
        self.assertEqual(agreement.quantity_available, 0)

        revoke_allocation(activated, actor=self.it_support, reason="Left company")
        agreement.refresh_from_db()
        self.assertEqual(agreement.quantity_allocated, 0)
        self.assertEqual(agreement.quantity_available, 1)
        self.assertEqual(
            agreement.allocations.filter(status__in=ACTIVE_ALLOCATED_STATUSES).count(), 0
        )

    def test_reactivation_rejected_at_full_entitlement(self):
        """Ten consuming allocations plus one suspended allocation: the
        suspended seat cannot be reactivated because it would consume an
        eleventh entitlement from a ten-seat agreement."""
        agreement = self._agreement("LIC-REC-024", quantity=10)
        for idx in range(10):
            self._allocation(agreement, "active", self.employee, f"REF-FULL-{idx}")
        suspended = self._allocation(
            agreement, "suspended", self.other_employee, "REF-FULL-SUSP"
        )
        agreement.recalculate_counters(save=True)
        self.assertEqual(agreement.quantity_available, 0)

        with self.assertRaises(ValidationError):
            activate_allocation(suspended, actor=self.it_support)

        suspended.refresh_from_db()
        agreement.refresh_from_db()
        self.assertEqual(suspended.status, "suspended")
        self.assertEqual(agreement.quantity_allocated, 10)
        self.assertEqual(agreement.quantity_available, 0)

    def test_reactivation_rejected_for_expired_agreement(self):
        agreement = self._agreement(
            "LIC-REC-022",
            quantity=2,
            status="active",
            expiry_date=timezone.now().date() - timedelta(days=1),
        )
        suspended = self._allocation(
            agreement, "suspended", self.other_employee, "REF-EXP-SUSP"
        )

        with self.assertRaises(ValidationError):
            activate_allocation(suspended, actor=self.it_support)

        suspended.refresh_from_db()
        self.assertEqual(suspended.status, "suspended")

    def test_reactivation_locks_agreement_before_allocation(self):
        agreement = self._agreement("LIC-REC-023", quantity=2)
        suspended = self._allocation(
            agreement, "suspended", self.other_employee, "REF-LOCK-SUSP"
        )
        order = []

        original_agreement_lock = LicenseAgreement.objects.select_for_update
        original_allocation_lock = LicenseAllocation.objects.select_for_update

        def agreement_lock(*args, **kwargs):
            order.append("agreement")
            return original_agreement_lock(*args, **kwargs)

        def allocation_lock(*args, **kwargs):
            order.append("allocation")
            return original_allocation_lock(*args, **kwargs)

        with (
            mock.patch.object(
                LicenseAgreement.objects,
                "select_for_update",
                side_effect=agreement_lock,
            ),
            mock.patch.object(
                LicenseAllocation.objects,
                "select_for_update",
                side_effect=allocation_lock,
            ),
        ):
            activate_allocation(
                suspended, actor=self.it_support, reason="Lock order check"
            )

        self.assertEqual(order[:2], ["agreement", "allocation"])

    def test_allocation_path_uses_row_lock_and_transaction(self):
        agreement = self._agreement("LIC-REC-008", quantity=1)
        original = LicenseAgreement.objects.select_for_update
        observed = []

        def spy(*args, **kwargs):
            observed.append(True)
            return original(*args, **kwargs)

        with mock.patch.object(LicenseAgreement.objects, "select_for_update", side_effect=spy):
            allocate_license(
                agreement=agreement,
                allocation_type="user",
                assigned_user=self.employee,
                actor=self.it_support,
            )

        self.assertTrue(observed, "allocate_license must lock the agreement row")
        self.assertEqual(agreement.allocations.count(), 1)

        # A second allocation against the locked, exhausted agreement is rejected.
        with self.assertRaises(ValidationError):
            allocate_license(
                agreement=agreement,
                allocation_type="user",
                assigned_user=self.other_employee,
                actor=self.it_support,
            )

    # ------------------------------------------------------------------
    # compliance findings
    # ------------------------------------------------------------------
    def test_over_allocation_finding_is_deduplicated_and_resolved_by_reality(self):
        agreement = self._agreement("LIC-REC-009", quantity=1)
        first = self._allocation(agreement, "active", self.employee, "REF-OVER-1")
        self._allocation(agreement, "active", self.other_employee, "REF-OVER-2")

        evaluate_license_compliance(agreement=agreement)
        evaluate_license_compliance(agreement=agreement)

        findings = LicenseComplianceFinding.objects.filter(
            agreement=agreement, finding_type="over_allocated"
        )
        self.assertEqual(findings.count(), 1)
        self.assertEqual(findings.first().status, "open")

        revoke_allocation(first, actor=self.it_support, reason="Remove duplicate seat")
        evaluate_license_compliance(agreement=agreement)
        finding = findings.first()
        finding.refresh_from_db()
        self.assertEqual(finding.status, "resolved")

        # Re-detecting the condition reopens the same finding (no duplicate).
        self._allocation(agreement, "active", self.employee, "REF-OVER-3")
        evaluate_license_compliance(agreement=agreement)
        finding.refresh_from_db()
        self.assertEqual(finding.status, "open")
        self.assertEqual(findings.count(), 1)

    def test_false_positive_finding_is_not_reopened(self):
        agreement = self._agreement("LIC-REC-010", quantity=1)
        self._allocation(agreement, "active", self.employee, "REF-FP-1")
        self._allocation(agreement, "active", self.other_employee, "REF-FP-2")

        evaluate_license_compliance(agreement=agreement)
        finding = LicenseComplianceFinding.objects.get(
            agreement=agreement, finding_type="over_allocated"
        )
        finding.status = "false_positive"
        finding.save(update_fields=["status"])

        evaluate_license_compliance(agreement=agreement)
        finding.refresh_from_db()
        self.assertEqual(finding.status, "false_positive")
        self.assertEqual(
            LicenseComplianceFinding.objects.filter(
                agreement=agreement, finding_type="over_allocated"
            ).count(),
            1,
        )

    def test_remediation_records_action_but_does_not_resolve_live_condition(self):
        agreement = self._agreement("LIC-REC-011", quantity=1)
        first = self._allocation(agreement, "active", self.employee, "REF-REM-1")
        self._allocation(agreement, "active", self.other_employee, "REF-REM-2")
        evaluate_license_compliance(agreement=agreement)
        finding = LicenseComplianceFinding.objects.get(
            agreement=agreement, finding_type="over_allocated"
        )

        remediated = remediate_compliance_finding(
            finding,
            actor=self.it_manager,
            remediation_note="Investigating duplicate seat",
            reevaluate=True,
        )
        self.assertEqual(remediated.status, "acknowledged")

        with self.assertRaises(ValidationError):
            resolve_compliance_finding(
                remediated, actor=self.it_manager, resolution_note="Attempted closure"
            )

        revoke_allocation(first, actor=self.it_support, reason="Duplicate removed")
        reevaluated = remediate_compliance_finding(
            finding,
            actor=self.it_manager,
            remediation_note="Verified capacity",
            reevaluate=True,
        )
        self.assertEqual(reevaluated.status, "resolved")

    def test_terminated_and_expired_agreement_allocations_are_flagged(self):
        terminated = self._agreement("LIC-REC-012", status="terminated")
        term_alloc = self._allocation(terminated, "active", self.employee, "REF-TERM")
        expired = self._agreement(
            "LIC-REC-013", status="active", expiry_date=timezone.now().date() - timedelta(days=5)
        )
        exp_alloc = self._allocation(expired, "active", self.other_employee, "REF-EXP")

        evaluate_license_compliance(agreement=terminated)
        evaluate_license_compliance(agreement=expired)

        term_finding = LicenseComplianceFinding.objects.get(
            allocation=term_alloc, finding_type="terminated_agreement_allocation"
        )
        exp_finding = LicenseComplianceFinding.objects.get(
            allocation=exp_alloc, finding_type="expired_agreement_allocation"
        )
        self.assertEqual(term_finding.status, "open")
        self.assertEqual(exp_finding.status, "open")

        revoke_allocation(term_alloc, actor=self.it_support, reason="Terminated agreement cleanup")
        evaluate_license_compliance(agreement=terminated)
        term_finding.refresh_from_db()
        self.assertEqual(term_finding.status, "resolved")

        # The expired agreement finding itself remains while the agreement is expired.
        self.assertTrue(
            LicenseComplianceFinding.objects.filter(
                agreement=expired, finding_type="expired_agreement", status="open"
            ).exists()
        )
        self.assertEqual(expired.status, "active")

    def test_missing_entitlement_quantity_is_detected(self):
        agreement = self._agreement("LIC-REC-014", quantity=0)
        evaluate_license_compliance(agreement=agreement)
        self.assertTrue(
            LicenseComplianceFinding.objects.filter(
                agreement=agreement, finding_type="missing_entitlement_quantity", status="open"
            ).exists()
        )

    # ------------------------------------------------------------------
    # API endpoints, filters and permissions
    # ------------------------------------------------------------------
    def test_utilization_report_includes_reconciliation_and_filters(self):
        seat_agreement = self._agreement("LIC-REC-015", quantity=4)
        self._allocation(seat_agreement, "active", self.employee, "REF-UTIL-1")
        self._allocation(seat_agreement, "active", self.other_employee, "REF-UTIL-2")
        site_agreement = self._agreement(
            "LIC-REC-016", quantity=1, license_model="site", agreement_type="enterprise"
        )

        self.client.force_authenticate(user=self.it_support)
        response = self.client.get("/api/licensing/utilization-report/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        rows = {row["agreement_number"]: row for row in response.data["results"]}
        self.assertEqual(rows["LIC-REC-015"]["purchased_entitlement"], 4)
        self.assertEqual(rows["LIC-REC-015"]["current_usage"], 2)
        self.assertEqual(rows["LIC-REC-015"]["available_entitlement"], 2)
        self.assertEqual(rows["LIC-REC-015"]["utilization_percent"], 50.0)
        self.assertTrue(rows["LIC-REC-015"]["utilization_calculable"])
        self.assertIsNone(rows["LIC-REC-016"]["utilization_percent"])
        self.assertFalse(rows["LIC-REC-016"]["utilization_calculable"])
        self.assertTrue(rows["LIC-REC-016"]["utilization_note"])

        filtered = self.client.get(
            "/api/licensing/utilization-report/", {"vendor": "Reconciliation", "license_type": "named_user"}
        )
        self.assertEqual(filtered.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["agreement_number"] for row in filtered.data["results"]], ["LIC-REC-015"]
        )
        self.assertEqual(filtered.data["summary"]["current_usage"], 2)

    def test_dashboard_provides_entitlement_kpis_and_filters(self):
        agreement = self._agreement("LIC-REC-017", quantity=3)
        self._allocation(agreement, "active", self.employee, "REF-DASH-1")

        self.client.force_authenticate(user=self.it_manager)
        response = self.client.get("/api/licensing/dashboard/", {"license_type": "named_user"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_agreements"], 1)
        self.assertEqual(response.data["active_usage"], 1)
        self.assertEqual(response.data["total_entitlement_quantity"], 3)
        self.assertEqual(response.data["available_entitlements"], 2)
        self.assertEqual(response.data["overallocated_agreements"], 0)
        self.assertIn("agreements_requiring_attention", response.data)
        self.assertIn("open_compliance_findings", response.data)
        self.assertEqual(response.data["filters"]["license_type"], "named_user")

    def test_entitlement_reconciliation_endpoint_permissions(self):
        agreement = self._agreement("LIC-REC-018", quantity=2)
        self._allocation(agreement, "active", self.employee, "REF-RECON-1")

        self.client.force_authenticate(user=self.employee)
        denied = self.client.get("/api/licensing/entitlement-reconciliation/")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.it_support)
        allowed = self.client.get("/api/licensing/entitlement-reconciliation/")
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        self.assertEqual(allowed.data["count"], 1)
        row = allowed.data["results"][0]
        self.assertEqual(row["purchased_entitlement_quantity"], 2)
        self.assertEqual(row["consuming_quantity"], 1)
        self.assertEqual(row["available_quantity"], 1)

    def test_direct_allocation_mutation_endpoints_are_blocked(self):
        agreement = self._agreement("LIC-REC-019", quantity=2)
        allocation = self._allocation(agreement, "assigned", self.employee, "REF-DIRECT")

        self.client.force_authenticate(user=self.it_support)
        self.assertEqual(
            self.client.post("/api/licensing/allocations/", {}).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/licensing/allocations/{allocation.pk}/", {"status": "active"}
            ).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.delete(f"/api/licensing/allocations/{allocation.pk}/").status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        self.client.force_authenticate(user=self.employee)
        self.assertEqual(
            self.client.post("/api/licensing/allocations/", {}).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_allocation_activate_endpoint_returns_400_on_entitlement_violation(self):
        agreement = self._agreement("LIC-REC-020", quantity=1)
        allocate_license(
            agreement=agreement,
            allocation_type="user",
            assigned_user=self.employee,
            actor=self.it_support,
        )
        suspended = self._allocation(agreement, "suspended", self.other_employee, "REF-API-SUSP")

        self.client.force_authenticate(user=self.it_support)
        response = self.client.post(f"/api/licensing/allocations/{suspended.pk}/activate/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("capacity", response.data["detail"].lower())

    def test_agreement_utilization_endpoint_exposes_reconciliation(self):
        agreement = self._agreement("LIC-REC-021", quantity=2)
        self._allocation(agreement, "active", self.employee, "REF-AGR-UTIL")

        self.client.force_authenticate(user=self.it_support)
        response = self.client.get(f"/api/licensing/agreements/{agreement.pk}/utilization/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["purchased_entitlement_quantity"], 2)
        self.assertEqual(response.data["consuming_quantity"], 1)
        self.assertEqual(response.data["available_entitlement_quantity"], 1)
        self.assertEqual(response.data["reconciled_utilization_percent"], 50.0)


# ------------------------------------------------------------------
# reconcile_entitlements_summary service + endpoint
# ------------------------------------------------------------------
    def test_reconcile_entitlements_summary_service_shape(self):
        a1 = self._agreement("LIC-SUM-001", quantity=5)
        self._allocation(a1, "active", self.employee, "REF-SUM-1")
        self._allocation(a1, "assigned", self.other_employee, "REF-SUM-2")

        a2 = self._agreement("LIC-SUM-002", quantity=3)
        self._allocation(a2, "reserved", reference="REF-SUM-3")

        summary = reconcile_entitlements_summary(LicenseAgreement.objects.all())

        self.assertEqual(summary["total_entitlement_quantity"], 8)
        self.assertEqual(summary["current_usage"], 3)
        self.assertEqual(summary["available_entitlement"], 5)
        self.assertEqual(summary["overallocated_agreements"], 0)
        self.assertEqual(summary["utilization_percent"], 37.5)

    def test_reconcile_entitlements_summary_overallocated(self):
        a1 = self._agreement("LIC-SUM-010", quantity=1)
        self._allocation(a1, "active", self.employee, "REF-OVR-1")
        self._allocation(a1, "reserved", self.other_employee, "REF-OVR-2")

        summary = reconcile_entitlements_summary(LicenseAgreement.objects.all())

        self.assertEqual(summary["total_entitlement_quantity"], 1)
        self.assertEqual(summary["current_usage"], 2)
        self.assertEqual(summary["available_entitlement"], 0)
        self.assertEqual(summary["overallocated_agreements"], 1)
        self.assertEqual(summary["utilization_percent"], 200.0)

    def test_reconcile_entitlements_summary_empty(self):
        summary = reconcile_entitlements_summary(LicenseAgreement.objects.none())
        self.assertEqual(summary["total_entitlement_quantity"], 0)
        self.assertEqual(summary["current_usage"], 0)
        self.assertEqual(summary["available_entitlement"], 0)
        self.assertEqual(summary["overallocated_agreements"], 0)
        self.assertIsNone(summary["utilization_percent"])

    def test_reconcile_entitlements_summary_excludes_unlimited(self):
        self._agreement("LIC-SUM-020", quantity=0, license_model="site")
        self._agreement("LIC-SUM-021", quantity=0, license_model="freeware")

        summary = reconcile_entitlements_summary(LicenseAgreement.objects.all())
        self.assertEqual(summary["total_entitlement_quantity"], 0)
        self.assertEqual(summary["current_usage"], 0)
        self.assertEqual(summary["overallocated_agreements"], 0)
        self.assertIsNone(summary["utilization_percent"])

    def test_entitlement_reconciliation_endpoint_returns_summary(self):
        a1 = self._agreement("LIC-EP-001", quantity=4)
        self._allocation(a1, "active", self.employee, "REF-EP-1")
        self._allocation(a1, "reserved", self.other_employee, "REF-EP-2")

        self.client.force_authenticate(user=self.it_support)
        response = self.client.get("/api/licensing/entitlement-reconciliation/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        summary = response.data["summary"]
        self.assertEqual(summary["total_entitlement_quantity"], 4)
        self.assertEqual(summary["current_usage"], 2)
        self.assertEqual(summary["available_entitlement"], 2)
        self.assertEqual(summary["overallocated_agreements"], 0)
        self.assertEqual(summary["utilization_percent"], 50.0)

    def test_entitlement_reconciliation_endpoint_employee_forbidden(self):
        self.client.force_authenticate(user=self.employee)
        response = self.client.get("/api/licensing/entitlement-reconciliation/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class LicensingAllocationConcurrencyTests(TransactionTestCase):
    """Genuine multi-connection allocation race (PostgreSQL only).

    SQLite serialises writers with a database-wide lock, so it cannot exercise
    the row-level ``select_for_update`` guarantee. This test is skipped there
    and runs on PostgreSQL with two independent connections/transactions.
    """

    def setUp(self):
        self.dept = Department.objects.create(name="Concurrency", code="CONC")
        self.it_dept = Department.objects.create(name="Concurrency IT", code="CONC-IT")
        self.sys_admin = User.objects.create_user(
            username="conc-admin@test.com",
            email="conc-admin@test.com",
            employee_id="CONC-ADM",
            role="system_admin",
            home_department=self.it_dept,
        )
        self.it_support = User.objects.create_user(
            username="conc-support@test.com",
            email="conc-support@test.com",
            employee_id="CONC-SUP",
            role="it_support",
            home_department=self.it_dept,
        )
        self.employee = User.objects.create_user(
            username="conc-emp1@test.com",
            email="conc-emp1@test.com",
            employee_id="CONC-EMP1",
            role="employee",
            home_department=self.dept,
        )
        self.other_employee = User.objects.create_user(
            username="conc-emp2@test.com",
            email="conc-emp2@test.com",
            employee_id="CONC-EMP2",
            role="employee",
            home_department=self.dept,
        )
        self.product = SoftwareProduct.objects.create(
            name="Concurrency Suite",
            publisher="Concurrency Corp",
            code="CONC-SUITE",
            category="development",
            license_model="named_user",
            license_required=True,
            approved_status="approved",
            created_by=self.sys_admin,
        )
        self.agreement = LicenseAgreement.objects.create(
            agreement_number="LIC-CONC-001",
            software_product=self.product,
            status="active",
            license_model="named_user",
            agreement_type="subscription",
            quantity_purchased=1,
            start_date=timezone.now().date() - timedelta(days=30),
            expiry_date=timezone.now().date() + timedelta(days=365),
            created_by=self.sys_admin,
        )

    def test_concurrent_allocations_cannot_exceed_entitlement(self):
        if connection.vendor != "postgresql":
            self.skipTest("Row-level locking concurrency requires PostgreSQL.")

        barrier = threading.Barrier(2, timeout=15)
        successes = []
        failures = []

        def worker(user):
            try:
                barrier.wait()
                allocation = allocate_license(
                    agreement=self.agreement,
                    allocation_type="user",
                    assigned_user=user,
                    actor=self.it_support,
                )
                successes.append(allocation.pk)
            except BaseException as exc:  # noqa: BLE001 - surfaced in assertions
                failures.append(exc)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=worker, args=(user,))
            for user in (self.employee, self.other_employee)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(successes), 1, failures)
        self.assertEqual(len(failures), 1, failures)
        self.assertIsInstance(failures[0], ValidationError)
        self.assertIn("capacity", str(failures[0]).lower())

        self.agreement.refresh_from_db()
        self.assertEqual(
            self.agreement.allocations.filter(
                status__in=CONSUMING_ALLOCATION_STATUSES
            ).count(),
            1,
        )
        self.assertEqual(self.agreement.quantity_allocated, 1)
        self.assertEqual(self.agreement.quantity_available, 0)
