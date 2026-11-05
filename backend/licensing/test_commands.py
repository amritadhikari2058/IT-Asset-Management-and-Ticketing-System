"""Tests for Licensing Management Commands."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from accounts.models import Department, User
from licensing.models import LicenseAgreement, SoftwareProduct


class LicensingManagementCommandsTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="IT Services", code="IT01")
        self.sys_admin = User.objects.create_user(
            username="admin@test.com", email="admin@test.com", employee_id="ADM-001", role="system_admin", home_department=self.dept
        )
        self.product = SoftwareProduct.objects.create(
            name="Command Test Tool",
            publisher="Test Corp",
            category="utility",
            approved_status="approved",
            created_by=self.sys_admin,
        )

    def test_evaluate_license_compliance_command_dry_run(self):
        """Dry-run command runs without error and outputs potential findings."""
        out = StringIO()
        call_command("evaluate_license_compliance", "--dry-run", stdout=out)
        output = out.getvalue()
        self.assertIn("Starting license compliance evaluation [DRY-RUN]", output)

    def test_evaluate_license_compliance_command_execute(self):
        """Execute command runs and commits findings."""
        out = StringIO()
        call_command("evaluate_license_compliance", "--execute", stdout=out)
        output = out.getvalue()
        self.assertIn("Starting license compliance evaluation [EXECUTE]", output)
        self.assertIn("Successfully evaluated and persisted", output)

    def test_verify_license_encryption_command_fails_safely_when_unavailable(self):
        """verify_license_encryption command exits nonzero with helpful message when encryption is missing."""
        out = StringIO()
        err = StringIO()
        with patch("licensing.management.commands.verify_license_encryption.is_encryption_available", return_value=(False, "Key not set")):
            with self.assertRaises(SystemExit) as ctx:
                call_command("verify_license_encryption", stdout=out, stderr=err)
            self.assertEqual(ctx.exception.code, 1)
            self.assertIn("FAIL: Encryption is unavailable", err.getvalue())

    def test_verify_license_encryption_command_succeeds_when_ready(self):
        """verify_license_encryption command passes when encryption is ready."""
        out = StringIO()
        err = StringIO()
        with patch("licensing.management.commands.verify_license_encryption.is_encryption_available", return_value=(True, "Ready")), \
             patch("licensing.management.commands.verify_license_encryption.encrypt_secret", return_value="ciphertext"), \
             patch("licensing.management.commands.verify_license_encryption.decrypt_secret", return_value="selftest_token_verification_0123456789"):
            call_command("verify_license_encryption", stdout=out, stderr=err)
            self.assertIn("PASS: Encryption subsystem is operational and valid.", out.getvalue())
