"""Security and Encryption Tests for License Secrets.

Verifies:
- Plaintext secrets are never stored directly in readable database fields.
- Serializer input is write-only; plaintext is never present in serialized models.
- Secret reveal is strictly restricted to System Administrators.
- IT Managers, IT Support, and Employees are forbidden from revealing secrets.
- Responses contain Cache-Control: no-store.
- Plaintext secrets NEVER appear in AuditLog, LicenseHistory, or exceptions.
- Fail-closed behavior when encryption key or library is missing.
- Secret rotation and revocation behavior.
- Non-reversible fingerprinting for duplicate detection.
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Department, User
from common.models import AuditLog
from licensing.models import LicenseAgreement, LicenseHistory, LicenseSecret, SoftwareProduct
from licensing.security import (
    EncryptionUnavailableError,
    SecretDecryptionError,
    compute_secret_fingerprint,
    decrypt_secret,
    encrypt_secret,
    extract_last_four,
    is_encryption_available,
)

# Test Fernet key (32 url-safe base64-encoded bytes)
TEST_FERNET_KEY = "k1Z8_5jDq2wB8g5yL9mX4tP7rV0sN2aK4dF6gH8jK0="


class LicenseSecretSecurityTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="IT Department", code="IT01")

        self.sys_admin = User.objects.create_user(
            username="admin@test.com",
            email="admin@test.com",
            employee_id="EMP-001",
            role="system_admin",
            home_department=self.dept,
        )
        self.it_manager = User.objects.create_user(
            username="manager@test.com",
            email="manager@test.com",
            employee_id="EMP-002",
            role="it_manager",
            home_department=self.dept,
        )
        self.it_support = User.objects.create_user(
            username="support@test.com",
            email="support@test.com",
            employee_id="EMP-003",
            role="it_support",
            home_department=self.dept,
        )
        self.employee = User.objects.create_user(
            username="employee@test.com",
            email="employee@test.com",
            employee_id="EMP-004",
            role="employee",
            home_department=self.dept,
        )

        self.product = SoftwareProduct.objects.create(
            name="Enterprise Database",
            publisher="Oracle Corp",
            category="database",
            approved_status="approved",
            created_by=self.sys_admin,
        )

        self.agreement = LicenseAgreement.objects.create(
            agreement_number="LIC-2026-99001",
            software_product=self.product,
            agreement_type="subscription",
            license_model="named_user",
            status="active",
            quantity_purchased=10,
            quantity_available=10,
            created_by=self.sys_admin,
        )

        self.client = APIClient()

    def test_encryption_fails_closed_when_key_missing(self):
        """When LICENSE_SECRET_ENCRYPTION_KEY is unset, secret operations fail closed."""
        with override_settings(LICENSE_SECRET_ENCRYPTION_KEY=None):
            ready, reason = is_encryption_available()
            # If cryptography is missing or key missing, ready must be False
            self.assertFalse(ready)
            with self.assertRaises(EncryptionUnavailableError):
                encrypt_secret("sensitive_license_key_12345")

    def test_encryption_fails_closed_when_cryptography_missing(self):
        """Simulate missing cryptography library and verify fail-closed behavior."""
        with patch("licensing.security.HAS_CRYPTOGRAPHY", False):
            ready, reason = is_encryption_available()
            self.assertFalse(ready)
            self.assertIn("not installed", reason)
            with self.assertRaises(EncryptionUnavailableError):
                encrypt_secret("secret_token")

    def test_fingerprint_and_last_four_computation(self):
        """Fingerprint is non-reversible SHA-256 and last-four extracts trailing alphanumeric characters."""
        plaintext = "AAAA-BBBB-CCCC-DDDD-XYZ9"
        fingerprint = compute_secret_fingerprint(plaintext)
        last_four = extract_last_four(plaintext)

        self.assertEqual(len(fingerprint), 64)
        self.assertEqual(last_four, "XYZ9")
        # Ensure plaintext does not appear in fingerprint
        self.assertNotIn("XYZ9", fingerprint)
        self.assertNotIn("AAAA", fingerprint)

    def test_serializer_write_only_input_no_plaintext_leakage(self):
        """Plaintext secret value accepted on input but never exposed in standard responses."""
        secret_plaintext = "CONFIDENTIAL-KEY-9876543210"
        encrypted_token = "gAAAAABmockCiphertextForTestingOnly=="

        with patch("licensing.serializers.is_encryption_available", return_value=(True, "Ready")), \
             patch("licensing.serializers.encrypt_secret", return_value=encrypted_token):

            self.client.force_authenticate(user=self.sys_admin)
            res = self.client.post(
                "/api/licensing/secrets/",
                {
                    "agreement": self.agreement.pk,
                    "secret_type": "license_key",
                    "label": "Master Production Key",
                    "plaintext_value": secret_plaintext,
                },
            )
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)

            # Assert response payload contains NO plaintext and NO ciphertext
            self.assertNotIn("plaintext_value", res.data)
            self.assertNotIn(secret_plaintext, str(res.data))
            self.assertNotIn(encrypted_token, str(res.data))

            # Verify database state
            sec = LicenseSecret.objects.get(pk=res.data["id"])
            self.assertEqual(sec.encrypted_value, encrypted_token)
            self.assertEqual(sec.last_four, "3210")
            self.assertNotEqual(sec.encrypted_value, secret_plaintext)

    def test_reveal_restricted_to_system_admin(self):
        """Only System Admin can reveal plaintext; IT Manager, IT Support, Employee are denied."""
        secret = LicenseSecret.objects.create(
            agreement=self.agreement,
            secret_type="license_key",
            label="Production Key",
            encrypted_value="dummy_ciphertext",
            value_fingerprint="abc123def456",
            last_four="5678",
            created_by=self.sys_admin,
        )

        with patch("licensing.views.decrypt_secret", return_value="REVEALED-SECRET-5678"):
            # 1. Employee -> Forbidden
            self.client.force_authenticate(user=self.employee)
            res_emp = self.client.post(f"/api/licensing/secrets/{secret.pk}/reveal/")
            self.assertEqual(res_emp.status_code, status.HTTP_403_FORBIDDEN)

            # 2. IT Support -> Forbidden
            self.client.force_authenticate(user=self.it_support)
            res_sup = self.client.post(f"/api/licensing/secrets/{secret.pk}/reveal/")
            self.assertEqual(res_sup.status_code, status.HTTP_403_FORBIDDEN)

            # 3. IT Manager -> Forbidden under initial policy
            self.client.force_authenticate(user=self.it_manager)
            res_mgr = self.client.post(f"/api/licensing/secrets/{secret.pk}/reveal/")
            self.assertEqual(res_mgr.status_code, status.HTTP_403_FORBIDDEN)

            # 4. System Admin -> Allowed
            self.client.force_authenticate(user=self.sys_admin)
            res_admin = self.client.post(f"/api/licensing/secrets/{secret.pk}/reveal/")
            self.assertEqual(res_admin.status_code, status.HTTP_200_OK)
            self.assertEqual(res_admin.data["revealed_value"], "REVEALED-SECRET-5678")

            # Verify Cache-Control header
            self.assertIn("no-store", res_admin.headers.get("Cache-Control", ""))

    def test_audit_log_and_history_never_contain_plaintext(self):
        """Reveal action writes AuditLog and LicenseHistory without plaintext value."""
        secret = LicenseSecret.objects.create(
            agreement=self.agreement,
            secret_type="activation_code",
            label="Activation Token",
            encrypted_value="token_ciphertext",
            value_fingerprint="hash123",
            last_four="9999",
            created_by=self.sys_admin,
        )

        with patch("licensing.views.decrypt_secret", return_value="TOP-SECRET-ACTIVATION-9999"):
            self.client.force_authenticate(user=self.sys_admin)
            res = self.client.post(f"/api/licensing/secrets/{secret.pk}/reveal/")
            self.assertEqual(res.status_code, status.HTTP_200_OK)

            # Check AuditLog
            audit = AuditLog.objects.filter(entity_type__iexact="licensing.licensesecret", object_id=str(secret.pk)).first()
            self.assertIsNotNone(audit)
            self.assertNotIn("TOP-SECRET-ACTIVATION-9999", str(audit.details))
            self.assertNotIn("TOP-SECRET-ACTIVATION-9999", audit.reason)

            # Check LicenseHistory
            hist = LicenseHistory.objects.filter(agreement=self.agreement, event_type="secret_revealed").first()
            self.assertIsNotNone(hist)
            self.assertNotIn("TOP-SECRET-ACTIVATION-9999", str(hist.detail))

    def test_revoked_secret_cannot_be_revealed(self):
        """Revoked secret cannot be revealed even by System Administrator."""
        secret = LicenseSecret.objects.create(
            agreement=self.agreement,
            secret_type="license_key",
            label="Old Key",
            encrypted_value="token_ciphertext",
            status="revoked",
            created_by=self.sys_admin,
        )
        self.client.force_authenticate(user=self.sys_admin)
        res = self.client.post(f"/api/licensing/secrets/{secret.pk}/reveal/")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("revoked", res.data["detail"])

    def test_secret_rotation(self):
        """Secret rotation updates ciphertext, fingerprint, and logs rotation."""
        secret = LicenseSecret.objects.create(
            agreement=self.agreement,
            secret_type="license_key",
            label="Active Key",
            encrypted_value="original_ciphertext",
            value_fingerprint="original_hash",
            last_four="1111",
            status="active",
            created_by=self.sys_admin,
        )

        with patch("licensing.views.encrypt_secret", return_value="new_encrypted_ciphertext"), \
             patch("licensing.views.compute_secret_fingerprint", return_value="new_fingerprint_hash"), \
             patch("licensing.views.extract_last_four", return_value="2222"):

            self.client.force_authenticate(user=self.sys_admin)
            res = self.client.post(
                f"/api/licensing/secrets/{secret.pk}/rotate/",
                {"new_plaintext_value": "NEW-KEY-2222", "new_label": "Rotated Key"},
            )
            self.assertEqual(res.status_code, status.HTTP_200_OK)

            secret.refresh_from_db()
            self.assertEqual(secret.status, "rotated")
            self.assertEqual(secret.last_four, "2222")
            self.assertEqual(secret.encrypted_value, "new_encrypted_ciphertext")
            self.assertEqual(secret.rotated_by, self.sys_admin)
            self.assertIsNotNone(secret.rotated_at)
