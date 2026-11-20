"""Compliance remediation authorization and audit-integrity tests."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Department, User
from licensing.models import (
    LicenseAgreement,
    LicenseComplianceFinding,
    LicenseHistory,
    SoftwareProduct,
)
from licensing.services import (
    AUTO_RESOLVED_NOTE,
    compute_finding_fingerprint,
    evaluate_license_compliance,
    remediate_compliance_finding,
)


class ComplianceRemediationAPITests(TestCase):
    """Manager-only remediation with non-destructive audit notes."""

    def setUp(self):
        self.dept = Department.objects.create(name="Engineering", code="ENG01")
        self.it_dept = Department.objects.create(name="IT Services", code="IT01")

        self.sys_admin = User.objects.create_user(
            username="admin@test.com", email="admin@test.com",
            employee_id="ADM-001", role="system_admin", home_department=self.it_dept,
        )
        self.it_manager = User.objects.create_user(
            username="manager@test.com", email="manager@test.com",
            employee_id="MGR-001", role="it_manager", home_department=self.it_dept,
        )
        self.it_support = User.objects.create_user(
            username="support@test.com", email="support@test.com",
            employee_id="SUP-001", role="it_support", home_department=self.it_dept,
        )
        self.employee = User.objects.create_user(
            username="alice@test.com", email="alice@test.com",
            employee_id="EMP-101", role="employee", home_department=self.dept,
        )

        self.product = SoftwareProduct.objects.create(
            name="Acrobat Pro", publisher="Adobe", code="ADOBE-ACRO",
            category="design", approved_status="approved", created_by=self.sys_admin,
        )
        self.agreement = LicenseAgreement.objects.create(
            agreement_number="LIC-2026-REM-001",
            software_product=self.product,
            status="active",
            start_date=timezone.now().date(),
            expiry_date=timezone.now().date() + timezone.timedelta(days=90),
            quantity_purchased=5,
            quantity_available=5,
            unit_cost=Decimal("10.00"),
            total_cost=Decimal("50.00"),
            currency="USD",
            created_by=self.sys_admin,
        )
        self.finding = LicenseComplianceFinding.objects.create(
            finding_type="expired_agreement",
            severity="high",
            software_product=self.product,
            agreement=self.agreement,
            title="Compliance fixture finding",
            description="Fixture used to exercise remediation transitions.",
            fingerprint=compute_finding_fingerprint(
                "expired_agreement",
                agreement_id=self.agreement.pk,
                product_id=self.product.pk,
            ),
            status="open",
        )
        self.client = APIClient()

    def _remediate(self, user, payload=None, finding=None):
        self.client.force_authenticate(user=user)
        target = finding or self.finding
        return self.client.post(
            f"/api/licensing/findings/{target.pk}/remediate/",
            payload or {"remediation_note": "Patched the affected install"},
            format="json",
        )

    def _assert_untouched(self):
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, "open")
        self.assertEqual(self.finding.remediation_note, "")
        self.assertEqual(self.finding.resolution_note, "")
        self.assertIsNone(self.finding.resolved_at)
        self.assertIsNone(self.finding.resolved_by)

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def test_it_support_remediation_is_forbidden_and_does_not_mutate(self):
        before_history = LicenseHistory.objects.count()

        res = self._remediate(self.it_support, {"remediation_note": "Trying to bypass UI"})

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self._assert_untouched()
        self.assertEqual(LicenseHistory.objects.count(), before_history)

    def test_employee_remediation_is_forbidden(self):
        res = self._remediate(self.employee, {"remediation_note": "Employee attempt"})

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self._assert_untouched()

    def test_it_manager_remediation_is_allowed_and_persists_operator_note(self):
        res = self._remediate(self.it_manager, {"remediation_note": "Applied vendor hotfix"})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "acknowledged")
        self.assertIn("Applied vendor hotfix", res.data["remediation_note"])
        self.assertEqual(res.data["resolution_note"], "")

        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, "acknowledged")
        self.assertIn("Applied vendor hotfix", self.finding.remediation_note)
        self.assertIn(self.it_manager.email, self.finding.remediation_note)
        self.assertEqual(self.finding.resolution_note, "")

        event = LicenseHistory.objects.get(
            agreement=self.agreement, event_type="compliance_changed",
        )
        self.assertEqual(event.detail.get("action"), "remediation_recorded")
        self.assertEqual(event.detail.get("note"), "Applied vendor hotfix")
        self.assertEqual(event.actor, self.it_manager)

    def test_system_admin_remediation_is_allowed(self):
        res = self._remediate(self.sys_admin, {"remediation_note": "Admin remediation"})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "acknowledged")
        self.assertIn("Admin remediation", res.data["remediation_note"])

    def test_service_layer_still_rejects_non_manager_without_mutation(self):
        with self.assertRaises(ValidationError):
            remediate_compliance_finding(
                self.finding, actor=self.it_support, remediation_note="Service-level bypass",
            )

        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, "open")
        self.assertEqual(self.finding.remediation_note, "")

    # ------------------------------------------------------------------
    # Audit integrity on re-evaluation
    # ------------------------------------------------------------------

    def test_remediation_note_survives_automatic_resolution(self):
        res = self._remediate(
            self.it_manager,
            {"remediation_note": "Vendor confirmed the seat is unused", "reevaluate": True},
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "resolved")
        self.assertIn("Vendor confirmed the seat is unused", res.data["remediation_note"])
        self.assertEqual(res.data["resolution_note"], AUTO_RESOLVED_NOTE)
        self.assertEqual(res.data["resolved_by"], self.it_manager.pk)

        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, "resolved")
        self.assertIn("Vendor confirmed the seat is unused", self.finding.remediation_note)
        self.assertEqual(self.finding.resolution_note, AUTO_RESOLVED_NOTE)
        self.assertIsNotNone(self.finding.resolved_at)
        self.assertEqual(self.finding.resolved_by, self.it_manager)

    def test_automatic_resolution_preserves_existing_human_resolution_text(self):
        self.finding.resolution_note = "Operator: verified vendor decommission record."
        self.finding.save(update_fields=["resolution_note"])

        res = self._remediate(
            self.it_manager,
            {"remediation_note": "Evidence attached", "reevaluate": True},
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, "resolved")
        self.assertEqual(
            self.finding.resolution_note,
            f"Operator: verified vendor decommission record.\n{AUTO_RESOLVED_NOTE}",
        )
        self.assertIn("Evidence attached", self.finding.remediation_note)

    def test_reopened_finding_drops_only_the_generated_resolution_line(self):
        self.finding.resolution_note = f"Operator context.\n{AUTO_RESOLVED_NOTE}"
        self.finding.status = "resolved"
        self.finding.save(update_fields=["resolution_note", "status"])

        # Make the underlying expiry condition true so the engine reopens it.
        self.agreement.expiry_date = timezone.now().date() - timezone.timedelta(days=1)
        self.agreement.save(update_fields=["expiry_date"])
        evaluate_license_compliance(agreement=self.agreement)

        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, "open")
        self.assertEqual(self.finding.resolution_note, "Operator context.")

    # ------------------------------------------------------------------
    # Unchanged acknowledge / resolve / false-positive behaviour
    # ------------------------------------------------------------------

    def test_acknowledge_still_allowed_for_it_support(self):
        self.client.force_authenticate(user=self.it_support)
        res = self.client.post(f"/api/licensing/findings/{self.finding.pk}/acknowledge/")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "acknowledged")

    def test_resolve_requires_manager_and_records_resolution_note(self):
        self.client.force_authenticate(user=self.it_support)
        denied = self.client.post(
            f"/api/licensing/findings/{self.finding.pk}/resolve/",
            {"resolution_note": "Support attempt"},
            format="json",
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.it_manager)
        res = self.client.post(
            f"/api/licensing/findings/{self.finding.pk}/resolve/",
            {"resolution_note": "Verified vendor retirement"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "resolved")
        self.assertEqual(res.data["resolution_note"], "Verified vendor retirement")
        self.assertEqual(res.data["resolved_by"], self.it_manager.pk)

    def test_false_positive_requires_manager(self):
        self.client.force_authenticate(user=self.it_support)
        denied = self.client.post(
            f"/api/licensing/findings/{self.finding.pk}/false-positive/",
            {"resolution_note": "Support attempt"},
            format="json",
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.it_manager)
        res = self.client.post(
            f"/api/licensing/findings/{self.finding.pk}/false-positive/",
            {"resolution_note": "Approved trial install"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "false_positive")
        self.assertEqual(res.data["resolution_note"], "Approved trial install")
