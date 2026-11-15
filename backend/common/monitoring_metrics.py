"""Phase 26 — lightweight API performance monitoring.

Middleware aggregates request counts, response times and status distribution
into Django cache (LocMem in dev, Redis in prod). No database record is
written per request, so the per-request overhead is minimal and no sensitive
query parameters or request bodies are stored.

An endpoint view aggregates the cached counters into endpoint-level summaries
for the operational dashboard.
"""
import time
import logging

from django.conf import settings
from django.core.cache import cache
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

# Paths excluded from performance metrics (noise, auth tokens, health itself).
EXCLUDED_PREFIXES = (
    "/static/",
    "/media/",
    "/favicon.ico",
    "/api/common/health/",
    "/api/common/operations/status/",
)

# Max timings kept per endpoint-minute to bound memory.
MAX_TIMINGS_PER_KEY = 50


def _metric_key(endpoint, status, minute):
    return f"api:metric:{endpoint}:{status}:{minute}"


def _timings_key(endpoint, minute):
    return f"api:timings:{endpoint}:{minute}"


def _sanitize_endpoint(path):
    """Return a route-like endpoint without query params or sensitive data."""
    endpoint = path.split("?", 1)[0]
    # Collapse numeric ids into a placeholder so /tickets/1/ and /tickets/2/
    # share one metric key.
    import re
    endpoint = re.sub(r"/\d+/", "/{id}/", endpoint)
    endpoint = re.sub(r"/\d+$", "/{id}", endpoint)
    return endpoint or "/"


class ApiPerformanceMiddleware(MiddlewareMixin):
    """Record lightweight per-request performance metrics into cache."""

    def process_request(self, request):
        request._api_monitor_start = time.perf_counter()
        return None

    def process_response(self, request, response):
        try:
            self._record(request, response)
        except Exception:  # noqa: BLE001
            logger.debug("API performance metric recording failed", exc_info=True)
        return response

    def _record(self, request, response):
        path = getattr(request, "path", "") or ""
        if any(path.startswith(p) for p in EXCLUDED_PREFIXES):
            return
        endpoint = _sanitize_endpoint(path)
        if not endpoint:
            return
        status = getattr(response, "status_code", 0) or 0
        start = getattr(request, "_api_monitor_start", None)
        if start is None:
            return
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        minute = int(time.time() // 60)

        # Increment counters (cheap, atomic cache incr).
        count_key = _metric_key(endpoint, status, minute)
        cache.incr(count_key)
        cache.expire(count_key, 86400 * 2)

        # Record a capped sample of timings.
        t_key = _timings_key(endpoint, minute)
        existing = cache.get(t_key) or []
        if len(existing) >= MAX_TIMINGS_PER_KEY:
            existing = existing[-(MAX_TIMINGS_PER_KEY - 1):]
        existing.append(elapsed_ms)
        cache.set(t_key, existing, 86400 * 2)

        # Rolling request counter across all statuses for the endpoint.
        all_key = _metric_key(endpoint, "all", minute)
        cache.incr(all_key)
        cache.expire(all_key, 86400 * 2)


def aggregate_api_metrics(minutes=60):
    """Aggregate cached API metrics into endpoint summaries.

    Returns a list of endpoint metric dicts over the last ``minutes``.
    """
    now_minute = int(time.time() // 60)
    minutes = max(1, min(minutes, 1440))
    endpoints = {}
    for offset in range(minutes):
        minute = now_minute - offset
        # We cannot list cache keys reliably on all backends (LocMem can,
        # Redis cannot without SCAN). Instead, we aggregate from a small
        # in-process registry maintained by the middleware.
        pass
    # Fall back to the in-process registry for accurate, dependency-free
    # aggregation. The middleware also updates _REGISTRY.
    from common.monitoring_metrics import _REGISTRY  # noqa: F401
    return _aggregate_from_registry(_REGISTRY, minutes)


_REGISTRY = {
    "counts": {},      # (endpoint, status, minute) -> int
    "timings": {},     # (endpoint, minute) -> [float]
    "all_counts": {},  # (endpoint, minute) -> int
}


def _record_registry(endpoint, status, elapsed_ms, minute):
    _REGISTRY["counts"][(endpoint, status, minute)] = \
        _REGISTRY["counts"].get((endpoint, status, minute), 0) + 1
    _REGISTRY["all_counts"][(endpoint, minute)] = \
        _REGISTRY["all_counts"].get((endpoint, minute), 0) + 1
    timings = _REGISTRY["timings"].setdefault((endpoint, minute), [])
    timings.append(elapsed_ms)
    if len(timings) > MAX_TIMINGS_PER_KEY:
        del timings[:-MAX_TIMINGS_PER_KEY]


def _aggregate_from_registry(registry, minutes):
    now_minute = int(time.time() // 60)
    minutes = max(1, min(minutes, 1440))
    out = {}
    for offset in range(minutes):
        minute = now_minute - offset
        for (ep, m), count in list(registry["all_counts"].items()):
            if m != minute:
                continue
            entry = out.setdefault(ep, {
                "endpoint": ep,
                "request_count": 0,
                "error_count": 0,
                "slow_request_count": 0,
                "status_distribution": {},
                "avg_response_ms": None,
                "max_response_ms": None,
                "min_response_ms": None,
            })
            entry["request_count"] += count
            for (e2, s, m2), c2 in registry["counts"].items():
                if e2 == ep and m2 == minute:
                    entry["status_distribution"][str(s)] = \
                        entry["status_distribution"].get(str(s), 0) + c2
                    if s >= 500:
                        entry["error_count"] += c2
            timings = registry["timings"].get((ep, minute), [])
            if timings:
                entry.setdefault("_raw", []).extend(timings)
    result = []
    for ep, entry in out.items():
        raw = entry.pop("_raw", [])
        if raw:
            entry["avg_response_ms"] = round(sum(raw) / len(raw), 2)
            entry["max_response_ms"] = round(max(raw), 2)
            entry["min_response_ms"] = round(min(raw), 2)
        # Slow request threshold: > 1000 ms.
        entry["slow_request_count"] = sum(
            1 for t in raw if t > 1000)
        entry["error_rate"] = round(
            (entry["error_count"] / entry["request_count"] * 100), 2
        ) if entry["request_count"] else 0.0
        result.append(entry)
    result.sort(key=lambda e: e["request_count"], reverse=True)
    return result


# Patch ApiPerformanceMiddleware to also update the in-process registry so
# aggregation works regardless of cache backend capabilities.
_original_record = ApiPerformanceMiddleware._record


def _patched_record(self, request, response):
    _original_record(self, request, response)
    try:
        path = getattr(request, "path", "") or ""
        if any(path.startswith(p) for p in EXCLUDED_PREFIXES):
            return
        endpoint = _sanitize_endpoint(path)
        start = getattr(request, "_api_monitor_start", None)
        if start is None:
            return
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        status = getattr(response, "status_code", 0) or 0
        minute = int(time.time() // 60)
        _record_registry(endpoint, status, elapsed_ms, minute)
    except Exception:  # noqa: BLE001
        pass


ApiPerformanceMiddleware._record = _patched_record
