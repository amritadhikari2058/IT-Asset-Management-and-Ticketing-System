"""Tests for Licensing Data Export Builders and Formula Injection Protection."""

from decimal import Decimal
from django.test import TestCase

from accounts.models import Department, User
from licensing.exports import (
    agreement_rows,
    allocation_rows,
    export_dataset,
    product_rows,
)
from licensing.models import LicenseAgreement, LicenseAllocation, LicenseSecret, SoftwareProduct


class LicensingExportsTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Finance", code="FIN01")

        self.sys_admin = User.objects.create_user(
            username="admin@test.com", email="admin@test.com", employee_id="ADM-001", role="system_admin", home_department=self.dept
        )
        self.emp = User.objects.create_user(
            username="clerk@test.com", email="clerk@test.com", employee_id="EMP-501", role="employee", home_department=self.dept
        )

        self.product = SoftwareProduct.objects.create(
            name="=SUM(1+1)",  # Formula injection attempt in product name
            publisher="Test Publisher",
            category="finance",
            approved_status="approved",
            created_by=self.sys_admin,
        )

        self.agreement = LicenseAgreement.objects.create(
            agreement_number="LIC-2026-EXP-01",
            software_product=self.product,
            status="active",
            quantity_purchased=5,
            quantity_available=5,
            total_cost=Decimal("500.00"),
            currency="USD",
            created_by=self.sys_admin,
        )

        self.secret = LicenseSecret.objects.create(
            agreement=self.agreement,
            secret_type="license_key",
            label="Super Secret Key",
            encrypted_value="ENCRYPTED_SECRET_BYTES_DO_NOT_LEAK",
            value_fingerprint="abc123hash",
            last_four="7777",
            created_by=self.sys_admin,
        )

    def test_formula_injection_escaping_in_csv(self):
        """Values starting with =, +, -, @ are escaped with leading single quote in CSV."""
        csv_bytes = export_dataset("software_products", fmt="csv", user=self.sys_admin)
        content = csv_bytes.decode("utf-8")
        # In CSV, '=SUM(1+1)' is escaped with leading single quote: '=SUM(1+1)
        self.assertIn("'=SUM(1+1)", content)

    def test_secrets_never_exported(self):
        """Exported agreements and products never contain secret keys or tokens."""
        for ds in ("software_products", "license_agreements", "license_allocations"):
            csv_bytes = export_dataset(ds, fmt="csv", user=self.sys_admin)
            content = csv_bytes.decode("utf-8")
            self.assertNotIn("ENCRYPTED_SECRET_BYTES_DO_NOT_LEAK", content)
            self.assertNotIn("Super Secret Key", content)

    def test_employee_cannot_export_sensitive_agreements(self):
        """Regular employee gets empty rows when requesting agreement datasets."""
        rows = agreement_rows(user=self.emp)
        self.assertEqual(len(rows), 0)
