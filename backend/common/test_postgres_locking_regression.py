"""PostgreSQL row-locking regression tests for nullable outer-join scenarios.

These tests verify that ``select_for_update()`` querysets that also load
nullable related rows (via ``select_related()``) execute correctly against
PostgreSQL.  Django 6 generates a LEFT OUTER JOIN for nullable
``select_related()`` relationships, and PostgreSQL rejects

    FOR UPDATE cannot be applied to the nullable side of an outer join

when the lock targets the joined table.  The correct pattern is to scope the
lock to the primary table only with ``select_for_update(of=("self",))``,
then load related data separately.

Tests use ``TransactionTestCase`` so changes are visible to concurrent
threads, and each test creates its own fixtures with NULL related rows to
exercise the problematic outer-join code path.
"""
from django.db import transaction
from django.test import TransactionTestCase
from django.utils import timezone

from assets.models import KnowledgeBaseArticle, KnowledgeBaseCategory
from common.tasks import run_scheduled_reports
from common.models import ScheduledReport, SavedReport
from accounts.tests import make_users
from tickets.models import TicketCategory


class KnowledgeBaseNullableOuterJoinTests(TransactionTestCase):
    """KnowledgeBaseArticle.category is nullable; locking must work with NULL."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.category = KnowledgeBaseCategory.objects.create(name="General")

    def test_article_with_null_category_locked_with_of_self(self):
        """Locking an article whose category is NULL must not raise on PG."""
        article = KnowledgeBaseArticle.objects.create(
            slug="nullable-article-1", title="Nullable Article",
            summary="", category=None, author=self.mgr)
        with transaction.atomic():
            locked = (KnowledgeBaseArticle.objects
                      .select_for_update(of=("self",))
                      .get(pk=article.pk))
            self.assertIsNone(locked.category)
            locked.title = "Updated"
            locked.save(update_fields=["title", "updated_at"])

    def test_article_with_null_category_select_related_then_of_self(self):
        """select_related + select_for_update(of=("self",)) works with NULL FK."""
        article = KnowledgeBaseArticle.objects.create(
            slug="nullable-article-2", title="Nullable Article 2",
            summary="", category=self.category, author=self.mgr)
        KnowledgeBaseArticle.objects.filter(pk=article.pk).update(
            category=None)
        with transaction.atomic():
            locked = (KnowledgeBaseArticle.objects
                      .select_related("category")
                      .select_for_update(of=("self",))
                      .get(pk=article.pk))
            self.assertIsNone(locked.category)


class ScheduledReportLockScopeTests(TransactionTestCase):
    """ScheduledReport locking scope: of=("self",) is sufficient."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.tcat = TicketCategory.objects.create(name="HW")
        self.saved = SavedReport.objects.create(
            user=self.mgr, report_type="ticket_category",
            name="Lock scope report", filters={"category": self.tcat.pk})

    def test_report_locked_with_of_self_only(self):
        """Locking the scheduled report row with of=("self",) is sufficient."""
        report = ScheduledReport.objects.create(
            saved_report=self.saved, schedule="weekly",
            recipients=["ops@example.com"], format="csv", enabled=True,
            next_run_at=timezone.now())
        with transaction.atomic():
            locked = (ScheduledReport.objects
                      .select_for_update(of=("self",))
                      .get(pk=report.pk))
            self.assertEqual(locked.pk, report.pk)
