"""Management command to test encryption subsystem configuration."""

import sys
from django.core.management.base import BaseCommand
from licensing.security import (
    decrypt_secret,
    encrypt_secret,
    is_encryption_available,
)


class Command(BaseCommand):
    help = "Verify the license secret encryption key configuration via an in-memory self-test."

    def handle(self, *args, **options):
        self.stdout.write("Checking license secret encryption subsystem...")

        ready, reason = is_encryption_available()
        if not ready:
            self.stderr.write(self.style.ERROR(f"FAIL: Encryption is unavailable: {reason}"))
            self.stderr.write("To enable secret encryption:")
            self.stderr.write("  1. Ensure the 'cryptography' package is installed.")
            self.stderr.write("  2. Set LICENSE_SECRET_ENCRYPTION_KEY in your environment.")
            sys.exit(1)

        # In-memory round-trip test (never reads stored secrets, never prints key or test text)
        test_payload = "selftest_token_verification_0123456789"
        try:
            ciphertext = encrypt_secret(test_payload)
            decrypted = decrypt_secret(ciphertext)
            if decrypted != test_payload:
                self.stderr.write(self.style.ERROR("FAIL: Decrypted payload did not match test payload."))
                sys.exit(1)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"FAIL: Encryption round-trip failed: {exc}"))
            sys.exit(1)

        self.stdout.write(self.style.SUCCESS("PASS: Encryption subsystem is operational and valid."))
