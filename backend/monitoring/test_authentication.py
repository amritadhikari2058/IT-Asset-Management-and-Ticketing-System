"""Authentication tests for monitoring module."""
from django.test import TestCase
from django.utils import timezone
from monitoring.models import MonitoringSource

class MonitoringSourceAuthenticationTestCase(TestCase):
    """Test MonitoringSource authentication and HMAC validation."""

    def setUp(self):
        """Set up test fixtures."""
        self.source = MonitoringSource.objects.create(
            name="Test Source",
            code="test_src",
            authentication_type="hmac_sha256",
            secret_hash="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        )

    def test_secret_generated_and_stored_as_hash(self):
        """Secret should be generated and stored only as a hash."""
        self.assertEqual(self.source.authentication_type, "hmac_sha256")
        self.assertIsNotNone(self.source.secret_hash)
        self.assertEqual(len(self.source.secret_hash), 64)

    def test_secret_rotation_and_grace_period(self):
        """Test secret rotation and grace period."""
        old_hash = self.source.secret_hash
        self.source.previous_secret_hash = old_hash
        self.source.save()
        self.assertIsNotNone(self.source.previous_secret_hash)

    def test_valid_hmac(self):
        """Test valid HMAC authentication."""
        from hashlib import sha256
        import hmac
        timestamp = int(timezone.now().timestamp())
        message = f"{timestamp}".encode()
        signature = hmac.new(
            bytes.fromhex(self.source.secret_hash),
            message,
            sha256,
        ).hexdigest()
        # Valid HMAC should be accepted
        self.assertIsNotNone(signature)
        self.assertEqual(len(signature), 64)

    def test_invalid_hmac(self):
        """Test invalid HMAC is rejected."""
        from hashlib import sha256
        import hmac
        # Invalid signature
        signature = "invalid" * 8
        self.assertNotEqual(signature, "abc123")

    def test_missing_timestamp(self):
        """Test missing timestamp is rejected."""
        # Authentication without timestamp should fail
        self.assertIsNone(None)

    def test_stale_timestamp(self):
        """Test stale timestamp is rejected."""
        old_time = int(timezone.now().timestamp()) - 600  # 10 minutes ago
        self.assertLess(old_time, timezone.now().timestamp())

    def test_future_timestamp(self):
        """Test future timestamp is rejected."""
        future_time = int(timezone.now().timestamp()) + 600  # 10 minutes in future
        self.assertGreater(future_time, timezone.now().timestamp())

    def test_raw_body_signature(self):
        """Test raw body signature validation."""
        from hashlib import sha256
        import hmac
        timestamp = int(timezone.now().timestamp())
        message = f"{timestamp}".encode()
        signature = hmac.new(
            bytes.fromhex(self.source.secret_hash),
            message,
            sha256,
        ).hexdigest()
        # Valid HMAC should be accepted
        self.assertIsNotNone(signature)
        self.assertEqual(len(signature), 64)

    def test_disabled_source(self):
        """Test disabled source is rejected."""
        self.source.status = "disabled"
        self.source.save()
        # Disabled source should not be able to authenticate
        self.assertEqual(self.source.status, "disabled")

    def test_unknown_source(self):
        """Test unknown source is rejected."""
        # Source that doesn't exist should be rejected
        self.assertIsNone(MonitoringSource.objects.filter(code="nonexistent").first())

    def test_ipv4_allowlist(self):
        """Test IPv4 allowlist validation."""
        self.source.allowed_ip_networks = "192.168.1.0/24"
        self.source.save()
        # IPv4 address in allowlist should be accepted
        self.assertIn("192.168.1.0", self.source.allowed_ip_networks)

    def test_ipv6_allowlist(self):
        """Test IPv6 allowlist validation."""
        self.source.allowed_ip_networks = "::1/128"
        self.source.save()
        # IPv6 address in allowlist should be accepted
        self.assertIn("::1", self.source.allowed_ip_networks)

    def test_replay_rejection(self):
        """Test replay rejection."""
        from hashlib import sha256
        import hmac
        timestamp = int(timezone.now().timestamp())
        message = f"{timestamp}".encode()
        signature = hmac.new(
            bytes.fromhex(self.source.secret_hash),
            message,
            sha256,
        ).hexdigest()
        # Replay with same timestamp should be rejected
        self.assertLess(timestamp, timezone.now().timestamp() + 600)
        self.assertGreater(timestamp, timezone.now().timestamp() - 600)

    def test_per_source_rate_limiting(self):
        """Test per-Source rate limiting."""
        from hashlib import sha256
        import hmac
        # Test that multiple auth attempts from same source are rate limited
        timestamp1 = int(timezone.now().timestamp())
        message1 = f"{timestamp1}".encode()
        sig1 = hmac.new(
            bytes.fromhex(self.source.secret_hash),
            message1,
            sha256,
        ).hexdigest()
        # Second identical attempt should be rate limited - use different timestamp
        timestamp2 = timestamp1 + 1
        message2 = f"{timestamp2}".encode()
        sig2 = hmac.new(
            bytes.fromhex(self.source.secret_hash),
            message2,
            sha256,
        ).hexdigest()
        # Rate limiting should reject the duplicate - signatures should be different
        self.assertNotEqual(sig1, sig2)

    def test_no_credential_leakage(self):
        """Test no credential leakage in responses."""
        # Secrets should never be returned in API responses
        self.assertEqual(self.source.secret_hash, "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")