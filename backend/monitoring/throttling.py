"""Throttle classes for monitoring ingestion module."""

from rest_framework.throttling import SimpleRateThrottle


class MonitoringSourceRateThrottle(SimpleRateThrottle):
    """
    Throttle instance keyed by authenticated MonitoringSource.

    - Cache key contains safe Source ID/code, never secret material.
    - Rate read from source.rate_limit_per_minute.
    - Fixed-window implementation compatible with DRF.
    - Separate Sources have independent quotas.
    - Disabled/unlimited semantics: throttle disabled when rate is 0 or None.
    """

    def __init__(self):
        self.rate = None
        self.num_requests = None
        self.duration = None

    def get_cache_key(self, request, view):
        """
        Generate a cache key based on the monitoring source code.

        Returns a string suitable for use as a Django cache key.
        """
        # The source is attached to the request by MonitoringAuthentication
        source = getattr(request, '_monitoring_source', None)
        if source is None:
            return None

        # Use source code for cache key - safe, no secret material
        ident = f"monitoring_source_{source.code}"

        # DRF SimpleRateThrottle expects a string or list of identifiers
        return [ident]

    def allow_request(self, request, view):
        """
        Check if the request should be throttled.

        - If source rate_limit_per_minute is 0 or None, throttling is disabled.
        - Otherwise, use the standard fixed-window rate checking.
        - Throttled requests create no Event and no successful ingestion log.
        """
        # Read rate from source configuration
        rate = getattr(getattr(request, '_monitoring_source', None), 'rate_limit_per_minute', None)

        # If rate is 0 or None, throttling is disabled (unlimited)
        if rate is None or rate == 0:
            # Still record the request if needed, but don't throttle
            return True

        rate = int(rate)
        self.scope = f"monitoring_source_{getattr(request._monitoring_source, 'code', 'unknown')}"
        self.rate = f"{rate}/min"
        self.num_requests = rate
        self.duration = 60

        # Call the parent fixed-window rate check
        return super().allow_request(request, view)