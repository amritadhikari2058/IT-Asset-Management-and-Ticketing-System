"""Test-only Django settings.

Imported by ``pytest.ini`` so the automated suite runs against a
configuration that is fast and deterministic but otherwise identical to
``config.settings``.

The single override here is ``PASSWORD_HASHERS``: production-strength
PBKDF2 costs ~1.5s per hash on the CI/local hardware used for this project,
and every ``TestCase.setUp`` hashes several fixture passwords. That alone
pushed the suite past any reasonable timeout. MD5 is *only* used for test
runs and never affects production or development settings.
"""

from .settings import *  # noqa: F401,F403

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
