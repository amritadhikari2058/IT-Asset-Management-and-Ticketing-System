"""Permission, Separation of Duties, and Anti-IDOR Tests for Licensing API."""

from decimal import Decimal
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Department, User
from licensing.models import LicenseAgreement, LicenseAllocation, SoftwareProduct


class LicensingPermissionsTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Engineering", code="ENG01")
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
        self.emp1 = User.objects.create_user(
            username="alice@test.com", email="alice@test.com", employee_id="EMP-101", role="employee", home_department=self.dept
        )
        self.emp2 = User.objects.create_user(
            username="bob@test.com", email="bob@test.com", employee_id="EMP-102", role="employee", home_department=self.dept
        )

        self.product = SoftwareProduct.objects.create(
            name="Slack Enterprise",
            publisher="Slack Technologies",
            category="communication",
            approved_status="approved",
            notes="Confidential vendor discount terms",
            created_by=self.sys_admin,
        )

        self.agreement = LicenseAgreement.objects.create(
            agreement_number="LIC-2026-00055",
            software_product=self.product,
            status="active",
            quantity_purchased=10,
            quantity_available=10,
            unit_cost=Decimal("15.00"),
            total_cost=Decimal("150.00"),
            currency="USD",
            created_by=self.sys_admin,
        )

        self.alloc_alice = LicenseAllocation.objects.create(
            agreement=self.agreement,
            allocation_type="user",
            assigned_user=self.emp1,
            allocation_reference="LIC-2026-00055-SEAT-0001",
            status="active",
        )
        self.alloc_bob = LicenseAllocation.objects.create(
            agreement=self.agreement,
            allocation_type="user",
            assigned_user=self.emp2,
            allocation_reference="LIC-2026-00055-SEAT-0002",
            status="active",
        )

        self.client = APIClient()

    def test_unauthenticated_requests_denied(self):
        """Unauthenticated requests are rejected with 401."""
        res = self.client.get("/api/licensing/products/")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

        res2 = self.client.get("/api/licensing/agreements/")
        self.assertEqual(res2.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_employee_product_field_exposure_restricted(self):
        """Employees see safe fields only; internal notes and costs are omitted."""
        self.client.force_authenticate(user=self.emp1)
        res = self.client.get(f"/api/licensing/products/{self.product.pk}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertIn("name", res.data)
        self.assertIn("publisher", res.data)
        # Sensitive internal notes omitted from Employee view
        self.assertNotIn("notes", res.data)
        self.assertNotIn("created_by", res.data)

    def test_employee_denied_agreement_endpoints(self):
        """Employees are forbidden from viewing or modifying License Agreements."""
        self.client.force_authenticate(user=self.emp1)
        res_list = self.client.get("/api/licensing/agreements/")
        self.assertEqual(res_list.status_code, status.HTTP_403_FORBIDDEN)

        res_detail = self.client.get(f"/api/licensing/agreements/{self.agreement.pk}/")
        self.assertEqual(res_detail.status_code, status.HTTP_403_FORBIDDEN)

    def test_anti_idor_employee_cannot_view_other_users_allocations(self):
        """Alice can view her own allocation but gets 404 when querying Bob's allocation."""
        self.client.force_authenticate(user=self.emp1)

        # Alice views own allocation -> 200 OK
        res_own = self.client.get(f"/api/licensing/allocations/{self.alloc_alice.pk}/")
        self.assertEqual(res_own.status_code, status.HTTP_200_OK)
        self.assertEqual(res_own.data["allocation_reference"], "LIC-2026-00055-SEAT-0001")

        # Alice attempts to access Bob's allocation -> Scoped 404 Not Found (anti-IDOR)
        res_other = self.client.get(f"/api/licensing/allocations/{self.alloc_bob.pk}/")
        self.assertEqual(res_other.status_code, status.HTTP_404_NOT_FOUND)

    def test_my_software_endpoint_scoped_to_current_user(self):
        """GET /api/licensing/allocations/my-software/ returns only current employee's seats."""
        self.client.force_authenticate(user=self.emp1)
        res = self.client.get("/api/licensing/allocations/my-software/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["allocation_reference"], "LIC-2026-00055-SEAT-0001")

    def test_dashboard_access_denied_for_employee(self):
        """Employees are forbidden from accessing administrative dashboard metrics."""
        self.client.force_authenticate(user=self.emp1)
        res = self.client.get("/api/licensing/dashboard/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_it_support_can_view_agreements_but_cannot_terminate(self):
        """IT Support has operational view access but cannot terminate contracts."""
        self.client.force_authenticate(user=self.it_support)
        res = self.client.get("/api/licensing/agreements/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Termination attempt -> 400 with validation error (System Admin required)
        res_term = self.client.post(
            f"/api/licensing/agreements/{self.agreement.pk}/terminate/",
            {"reason": "Terminate now"},
        )
        self.assertEqual(res_term.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("System Administrators", res_term.data["detail"])
