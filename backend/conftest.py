"""Shared pytest fixtures.

The project uses Django's cache for outbound email deduplication
(``accounts.email_utils.send_ticket_notification`` keys on
``(ticket_id, subject, recipient)``). The cache is process-global and is
*not* rolled back with the database transaction that Django's
``TestCase`` uses, so a value written by one test can leak into the next
test that happens to reuse the same primary keys after rollback. That
leak manifests as spurious "duplicate email suppressed" results and makes
the suite order-dependent.

Clearing the cache before every test restores isolation without changing
any production behavior, and it does not weaken within-test dedup checks
because the cache is only cleared *between* tests.
"""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    cache.clear()
    yield
    cache.clear()
