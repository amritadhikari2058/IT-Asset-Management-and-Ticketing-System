from datetime import datetime, timedelta, timezone

from django.core.cache import cache
from rest_framework.throttling import AnonRateThrottle


def _utc_now():
    return datetime.now(timezone.utc)


class AuthRateThrottle(AnonRateThrottle):
    """Rate limit for authenticationadjacent endpoints.

    Inherits DRF's AnonRateThrottle behaviour (limited by the ``auth`` scope
    in DEFAULT_THROTTLE_RATES) so that anonymous and authenticated clients are
    both constrained at login/password-reset/verification/password-change.

    Account-level cooldown for password-reset/verification is handled separately
    by ``account_action_cooldown`` so a single account cannot be hammered even
    when the client changes IP/anonymous identity.
    """
    scope = 'auth'


def account_action_cooldown(key_prefix, window_seconds):
    """Return True when the named account-level action is within its cooldown.

    Uses the Django cache backend so it survives across worker processes and is
    naturally rate-limited by the cache layer. Keys are namespaced to avoid
    collisions with other cached values.
    """
    key = f"auth:cooldown:{key_prefix}"
    deadline = cache.get(key)
    now = _utc_now()
    if deadline is None:
        cache.set(key, now + timedelta(seconds=window_seconds),
                  timeout=window_seconds + 60)
        return False
    # Cache may store a naive datetime from an older process; compare in UTC.
    if isinstance(deadline, datetime) and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if now < deadline:
        return True
    cache.delete(key)
    return False
