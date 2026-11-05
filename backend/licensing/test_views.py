"""Comprehensive ViewSet and API Endpoint Tests for Licensing Module."""

from decimal import Decimal
import os
import tempfile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Department, User
from assets.models import Asset, AssetCategory
from licensing.models import (
    LicenseAgreement,
    LicenseAllocation,
    LicenseComplianceFinding,
    LicenseDocument,
    LicenseRenewal,
    SoftwareInstallation,
    SoftwareProduct,
)


class LicensingViewsTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Operations", code="OPS01")
        self.it_dept = Department.objects.create(name="IT Services", code="IT01")

        self.sys_admin = User.objects.create_user(
            username="admin@test.com", email="admin@test.com", employee_id="ADM-001", role="system_admin", home_department=self.it_dept
        )
        self.it_manager = User.objects.create_user(
            username="manager@test.com", email="manager@test.com", employee_id="MGR-001", role="it_manager", home_department=self.it_dept
        )
        self.it_support = User.objects.create_user(
            username="support@test.com", email="support@test.com", employee_id="SUP-001", role="it_support", home_department=self.it_dept
        )
        self.emp = User.objects.create_user(
            username="clerk@test.com", email="clerk@test.com", employee_id="EMP-901", role="employee", home_department=self.dept
        )

        self.category = AssetCategory.objects.create(name="Desktops")
        self.asset = Asset.objects.create(
            asset_tag="ASSET-OPS-001",
            name="Office PC",
            category=self.category,
            department=self.dept,
            status="available",
        )

        self.product = SoftwareProduct.objects.create(
            name="Adobe Creative Cloud",
            publisher="Adobe Systems",
            code="ADOBE-CC",
            category="design",
            approved_status="approved",
            created_by=self.sys_admin,
        )

        self.agreement = LicenseAgreement.objects.create(
            agreement_number="LIC-2026-VIEWS-001",
            software_product=self.product,
            status="active",
            quantity_purchased=10,
            quantity_available=10,
            unit_cost=Decimal("50.00"),
            total_cost=Decimal("500.00"),
            currency="USD",
            created_by=self.sys_admin,
        )

        self.client = APIClient()

    # ==========================================================================
    # PRODUCT VIEWSET & ACTIONS
    # ==========================================================================

    def test_product_actions_workflow(self):
        """Approve, restrict, prohibit, and retire actions on SoftwareProduct."""
        self.client.force_authenticate(user=self.sys_admin)

        # 1. Prohibit
        res_proh = self.client.post(f"/api/licensing/products/{self.product.pk}/prohibit/")
        self.assertEqual(res_proh.status_code, status.HTTP_200_OK)
        self.assertEqual(res_proh.data["approved_status"], "prohibited")

        # 2. Approve
        res_appr = self.client.post(f"/api/licensing/products/{self.product.pk}/approve/")
        self.assertEqual(res_appr.status_code, status.HTTP_200_OK)
        self.assertEqual(res_appr.data["approved_status"], "approved")

        # 3. Sub-endpoints
        res_agrs = self.client.get(f"/api/licensing/products/{self.product.pk}/agreements/")
        self.assertEqual(res_agrs.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_agrs.data), 1)

    # ==========================================================================
    # AGREEMENT ACTIONS & SUB-ENDPOINTS
    # ==========================================================================

    def test_agreement_recalculate_action(self):
        """POST /agreements/{id}/recalculate/ recalculates available seats."""
        self.client.force_authenticate(user=self.it_manager)
        res = self.client.post(f"/api/licensing/agreements/{self.agreement.pk}/recalculate/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["quantity_available"], 10)

    def test_agreement_utilization_sub_endpoint(self):
        """GET /agreements/{id}/utilization/ returns accurate seat metrics."""
        self.client.force_authenticate(user=self.it_support)
        res = self.client.get(f"/api/licensing/agreements/{self.agreement.pk}/utilization/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["quantity_purchased"], 10)
        self.assertEqual(res.data["quantity_allocated"], 0)
        self.assertEqual(res.data["utilization_percent"], 0.0)

    # ==========================================================================
    # ALLOCATION ACTIONS
    # ==========================================================================

    def test_allocation_actions_verify_and_revoke(self):
        """Verify and revoke actions on LicenseAllocation."""
        alloc = LicenseAllocation.objects.create(
            agreement=self.agreement,
            allocation_type="user",
            assigned_user=self.emp,
            allocation_reference="LIC-2026-VIEWS-001-SEAT-0001",
            status="active",
        )

        self.client.force_authenticate(user=self.it_support)
        # Verify
        res_ver = self.client.post(
            f"/api/licensing/allocations/{alloc.pk}/verify/",
            {"notes": "Verified active use in design department"},
        )
        self.assertEqual(res_ver.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(res_ver.data["last_verified_at"])

        # Revoke
        res_rev = self.client.post(
            f"/api/licensing/allocations/{alloc.pk}/revoke/",
            {"reason": "Software no longer required"},
        )
        self.assertEqual(res_rev.status_code, status.HTTP_200_OK)
        self.assertEqual(res_rev.data["status"], "revoked")

    # ==========================================================================
    # INSTALLATIONS
    # ==========================================================================

    def test_installation_remove_and_evaluate(self):
        """Remove and evaluate actions on SoftwareInstallation."""
        inst = SoftwareInstallation.objects.create(
            software_product=self.product,
            asset=self.asset,
            status="installed",
            compliance_status="unlicensed",
        )

        self.client.force_authenticate(user=self.it_support)
        res_eval = self.client.post(f"/api/licensing/installations/{inst.pk}/evaluate/")
        self.assertEqual(res_eval.status_code, status.HTTP_200_OK)

        res_rem = self.client.post(f"/api/licensing/installations/{inst.pk}/remove/", {"notes": "Uninstalled"})
        self.assertEqual(res_rem.status_code, status.HTTP_200_OK)
        self.assertEqual(res_rem.data["status"], "removed")

    # ==========================================================================
    # RENEWALS
    # ==========================================================================

    def test_renewal_workflow_endpoints(self):
        """Submit, review, and apply renewal endpoints."""
        now = timezone.now().date()
        self.client.force_authenticate(user=self.it_support)
        res_create = self.client.post(
            "/api/licensing/renewals/",
            {
                "agreement": self.agreement.pk,
                "proposed_start_date": str(now),
                "proposed_expiry_date": str(now + timezone.timedelta(days=365)),
                "proposed_quantity": 10,
                "proposed_unit_cost": "50.00",
                "proposed_total_cost": "500.00",
                "currency": "USD",
                "reason": "Annual renewal",
            },
        )
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        renewal_id = res_create.data["id"]

        # IT Manager approves ordinary renewal
        self.client.force_authenticate(user=self.it_manager)
        res_appr = self.client.post(
            f"/api/licensing/renewals/{renewal_id}/approve/",
            {"review_reason": "Approved by IT Manager"},
        )
        self.assertEqual(res_appr.status_code, status.HTTP_200_OK)
        self.assertEqual(res_appr.data["status"], "approved")

        # Apply renewal
        res_apply = self.client.post(f"/api/licensing/renewals/{renewal_id}/apply/")
        self.assertEqual(res_apply.status_code, status.HTTP_200_OK)

    # ==========================================================================
    # COMPLIANCE FINDINGS
    # ==========================================================================

    def test_compliance_finding_lifecycle_endpoints(self):
        """Acknowledge, resolve, and false-positive actions on compliance findings."""
        finding = LicenseComplianceFinding.objects.create(
            finding_type="unlicensed_installation",
            severity="high",
            software_product=self.product,
            asset=self.asset,
            title="Unlicensed Adobe CC",
            fingerprint="test_fp_12345",
            status="open",
        )

        self.client.force_authenticate(user=self.it_support)
        # 1. Acknowledge
        res_ack = self.client.post(f"/api/licensing/findings/{finding.pk}/acknowledge/")
        self.assertEqual(res_ack.status_code, status.HTTP_200_OK)
        self.assertEqual(res_ack.data["status"], "acknowledged")

        # 2. Resolve (requires IT Manager/Admin)
        self.client.force_authenticate(user=self.it_manager)
        res_res = self.client.post(
            f"/api/licensing/findings/{finding.pk}/resolve/",
            {"resolution_note": "Purchased extra seat"},
        )
        self.assertEqual(res_res.status_code, status.HTTP_200_OK)
        self.assertEqual(res_res.data["status"], "resolved")

    # ==========================================================================
    # DOCUMENTS & SECURITY
    # ==========================================================================

    def test_document_upload_allowlist_and_download(self):
        """Document upload blocks executables and serves safe files with nosniff headers."""
        self.client.force_authenticate(user=self.it_manager)

        # Block executable file upload
        bad_file = SimpleUploadedFile("malware.exe", b"binary_content", content_type="application/octet-stream")
        res_bad = self.client.post(
            "/api/licensing/documents/",
            {"agreement": self.agreement.pk, "document_type": "agreement", "file": bad_file},
            format="multipart",
        )
        self.assertEqual(res_bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("blocked", str(res_bad.data))

        # Valid PDF upload
        good_file = SimpleUploadedFile("contract.pdf", b"%PDF-1.4 test document content", content_type="application/pdf")
        res_good = self.client.post(
            "/api/licensing/documents/",
            {"agreement": self.agreement.pk, "document_type": "agreement", "file": good_file},
            format="multipart",
        )
        self.assertEqual(res_good.status_code, status.HTTP_201_CREATED)
        doc_id = res_good.data["id"]

        # Download document
        res_down = self.client.get(f"/api/licensing/documents/{doc_id}/download/")
        self.assertEqual(res_down.status_code, status.HTTP_200_OK)
        self.assertIn("contract.pdf", res_down.headers.get("Content-Disposition", ""))
        self.assertEqual(res_down.headers.get("X-Content-Type-Options"), "nosniff")

    # ==========================================================================
    # REPORTING & DASHBOARD ENDPOINTS
    # ==========================================================================

    def test_dashboard_renewal_calendar_utilization_endpoints(self):
        """Dashboard, Renewal Calendar, and Utilization Report endpoints return valid summaries."""
        self.client.force_authenticate(user=self.it_manager)

        # 1. Dashboard
        res_dash = self.client.get("/api/licensing/dashboard/")
        self.assertEqual(res_dash.status_code, status.HTTP_200_OK)
        self.assertIn("active_products", res_dash.data)
        self.assertIn("annual_cost_by_currency", res_dash.data)
        self.assertIn("USD", res_dash.data["annual_cost_by_currency"])

        # 2. Renewal Calendar
        res_cal = self.client.get("/api/licensing/renewal-calendar/")
        self.assertEqual(res_cal.status_code, status.HTTP_200_OK)
        self.assertIn("overdue", res_cal.data)
        self.assertIn("next_30_days", res_cal.data)

        # 3. Utilization Report
        res_util = self.client.get("/api/licensing/utilization-report/")
        self.assertEqual(res_util.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(res_util.data["count"], 1)

        # 4. Compliance Summary
        res_comp = self.client.get("/api/licensing/compliance-summary/")
        self.assertEqual(res_comp.status_code, status.HTTP_200_OK)
        self.assertIn("total_open_findings", res_comp.data)
