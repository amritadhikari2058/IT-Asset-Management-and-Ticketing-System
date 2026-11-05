"""License Secret Security and Encryption Boundary.

This module enforces safe handling of confidential credentials (license keys,
activation codes, admin passwords, subscription tokens).

Design and Policy:
- Plaintext secrets are NEVER stored directly in the database.
- Plaintext secrets are NEVER logged, included in AuditLog, exceptions, exports,
  or standard API serializer outputs.
- Encryption uses Fernet (symmetric authenticated cryptography) via the
  `cryptography` library and a key loaded from `LICENSE_SECRET_ENCRYPTION_KEY`.
- If the `cryptography` dependency is missing or `LICENSE_SECRET_ENCRYPTION_KEY`
  is not configured, secret storage operations FAIL CLOSED with
  `EncryptionUnavailableError`.
- No fallback production key is ever hardcoded or silently generated.
- Unreversible SHA-256 fingerprints are computed for duplicate detection.
- Safe last-four characters are retained for identification only.

Key Rotation Strategy:
1. When rotating the master key, configure `LICENSE_SECRET_ENCRYPTION_KEY` with the
   new primary key and configure `LICENSE_SECRET_ENCRYPTION_FALLBACK_KEYS` (a comma-
   separated list) with previous active keys.
2. The `MultiFernet` engine will decrypt with any valid fallback key and encrypt with
   the new primary key.
3. A future maintenance command (`reencrypt_license_secrets`) can iterate active
   secrets, decrypt them using the fallback key, and save them re-encrypted with
   the primary key.
"""

import hashlib
import hmac
import os
import re
from typing import Optional, Tuple

from django.conf import settings

try:
    from cryptography.fernet import Fernet, MultiFernet, InvalidToken
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False
    Fernet = None
    MultiFernet = None
    InvalidToken = Exception


class EncryptionUnavailableError(RuntimeError):
    """Raised when encryption or decryption cannot be performed safely."""
    pass


class SecretDecryptionError(RuntimeError):
    """Raised when decryption fails due to invalid key or tampered ciphertext."""
    pass


def get_encryption_key() -> Optional[str]:
    """Retrieve the primary encryption key from settings or environment."""
    key = getattr(settings, "LICENSE_SECRET_ENCRYPTION_KEY", None)
    if not key:
        key = os.environ.get("LICENSE_SECRET_ENCRYPTION_KEY", "").strip()
    return key or None


def get_fallback_keys() -> list[str]:
    """Retrieve any previous encryption keys for rotation."""
    raw = getattr(settings, "LICENSE_SECRET_ENCRYPTION_FALLBACK_KEYS", None)
    if not raw:
        raw = os.environ.get("LICENSE_SECRET_ENCRYPTION_FALLBACK_KEYS", "").strip()
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(k).strip() for k in raw if str(k).strip()]
    return [k.strip() for k in str(raw).split(",") if k.strip()]


def is_encryption_available() -> Tuple[bool, str]:
    """Check if the encryption subsystem is ready to operate safely."""
    if not HAS_CRYPTOGRAPHY:
        return False, "The 'cryptography' Python package is not installed."
    key = get_encryption_key()
    if not key:
        return False, "LICENSE_SECRET_ENCRYPTION_KEY is not configured in settings or environment."
    try:
        # Validate primary key format
        Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except Exception as exc:
        return False, f"Configured LICENSE_SECRET_ENCRYPTION_KEY is invalid: {exc}"
    return True, "Encryption subsystem ready."


def _get_fernet_suite():
    """Build the Fernet/MultiFernet encryption engine. Fail closed if unavailable."""
    ready, reason = is_encryption_available()
    if not ready:
        raise EncryptionUnavailableError(f"Secret operations disabled: {reason}")

    primary_key = get_encryption_key()
    fernets = [Fernet(primary_key.encode("utf-8") if isinstance(primary_key, str) else primary_key)]

    for fb in get_fallback_keys():
        try:
            fernets.append(Fernet(fb.encode("utf-8") if isinstance(fb, str) else fb))
        except Exception:
            # Skip malformed fallback keys with fail-safe continuation of primary
            continue

    if len(fernets) == 1:
        return fernets[0]
    return MultiFernet(fernets)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a plaintext secret string into ciphertext.

    Fails closed if encryption key or library is missing.
    """
    if not plaintext:
        raise ValueError("Secret plaintext cannot be empty.")
    suite = _get_fernet_suite()
    try:
        token = suite.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")
    except Exception as exc:
        raise EncryptionUnavailableError(f"Failed to encrypt secret safely: {exc}") from exc


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a ciphertext string back into plaintext.

    Fails closed if encryption key or library is missing or invalid.
    """
    if not ciphertext:
        raise ValueError("Secret ciphertext cannot be empty.")
    suite = _get_fernet_suite()
    try:
        plain_bytes = suite.decrypt(ciphertext.encode("utf-8"))
        return plain_bytes.decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError("Ciphertext cannot be decrypted with the available key(s).") from exc
    except Exception as exc:
        raise SecretDecryptionError(f"Decryption failed: {exc}") from exc


def compute_secret_fingerprint(plaintext: str) -> str:
    """Compute a non-reversible HMAC-SHA256 fingerprint for duplicate detection.

    Uses Django SECRET_KEY as salt so external observers cannot pre-compute hashes.
    """
    if not plaintext:
        return ""
    salt = getattr(settings, "SECRET_KEY", "it-asset-licensing-salt").encode("utf-8")
    h = hmac.new(salt, plaintext.strip().encode("utf-8"), hashlib.sha256)
    return h.hexdigest()


def extract_last_four(plaintext: str) -> str:
    """Extract safe last four alphanumeric characters for user identification."""
    if not plaintext:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", plaintext)
    if len(cleaned) < 4:
        return cleaned
    return cleaned[-4:]
