"""PostgreSQL-backed KB workflow race regressions.

SQLite cannot exercise the row locks used by KB transitions. These tests run
only against PostgreSQL and use a barrier to start both API requests together.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from accounts.models import User
from accounts.tests import make_users
from assets.models import (
    KnowledgeBaseArticle, KnowledgeBaseCategory,
)
from common.models import AuditLog, NotificationOutboxEvent


@skipUnless(connection.vendor == "postgresql",
            "KB transition races require PostgreSQL row locks")
class KnowledgeBaseWorkflowPostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.department, self.admin, self.manager, self.employee = make_users()
        self.support = User.objects.create_user(
            username="kb-race-support", email="kb-race-support@example.test",
            employee_id="KB-RACE-SUPPORT", password="test-password",
            role="it_support", home_department=self.department)
        self.category = KnowledgeBaseCategory.objects.create(
            name="KB Race", code="kb-race")

    def _create_article(self, slug="kb-race-article"):
        client = APIClient()
        client.force_authenticate(user=self.manager)
        response = client.post("/api/assets/knowledge-base/", {
            "title": "Race article", "slug": slug,
            "summary": "Race summary", "content": "Initial content",
            "category": self.category.code,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return KnowledgeBaseArticle.objects.get(pk=response.data["id"])

    def _submit(self, article):
        client = APIClient()
        client.force_authenticate(user=self.manager)
        response = client.post(
            f"/api/assets/knowledge-base/{article.pk}/submit_review/",
            {"version": article.version}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        article.refresh_from_db()
        return article

    def _approve(self, article, reviewer=None):
        client = APIClient()
        client.force_authenticate(user=reviewer or self.admin)
        response = client.post(
            f"/api/assets/knowledge-base/{article.pk}/approve/",
            {"version": article.version}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        article.refresh_from_db()
        return article

    def _race(self, calls):
        barrier = threading.Barrier(len(calls))

        def run(call):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                return call()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = [pool.submit(run, call) for call in calls]
            return [future.result(timeout=60) for future in futures]

    def _request(self, user, method, path, payload=None):
        client = APIClient()
        client.force_authenticate(user=user)
        response = getattr(client, method)(path, payload or {}, format="json")
        return response.status_code, getattr(response, "data", {})

    def test_two_approvals_commit_one_transition_and_one_notification(self):
        article = self._submit(self._create_article())
        path = f"/api/assets/knowledge-base/{article.pk}/approve/"
        results = self._race([
            lambda: self._request(self.admin, "post", path,
                                  {"version": article.version}),
            lambda: self._request(self.support, "post", path,
                                  {"version": article.version}),
        ])
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        article.refresh_from_db()
        self.assertEqual(article.status, "approved")
        self.assertEqual(article.version, 3)
        self.assertEqual(article.revisions.count(), 1)
        self.assertEqual(AuditLog.objects.filter(
            entity_type="assets.knowledgebasearticle", object_id=str(article.pk),
            details__action="approve").count(), 1)
        self.assertEqual(NotificationOutboxEvent.objects.filter(
            event_type="kb.article.approved",
            recipient_email=self.manager.email).count(), 1)

    def test_approval_racing_rejection_commits_only_one_decision(self):
        article = self._submit(self._create_article("kb-approve-reject"))
        approve_path = f"/api/assets/knowledge-base/{article.pk}/approve/"
        reject_path = f"/api/assets/knowledge-base/{article.pk}/reject/"
        results = self._race([
            lambda: self._request(
                self.admin, "post", approve_path,
                {"version": article.version, "comment": "Approved"}),
            lambda: self._request(
                self.support, "post", reject_path,
                {"version": article.version, "comment": "Needs changes"}),
        ])
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        article.refresh_from_db()
        self.assertIn((article.status, article.review_decision), (
            ("approved", "approved"), ("draft", "rejected")))
        self.assertEqual(article.version, 3)
        self.assertEqual(article.revisions.count(), 1)
        event_types = NotificationOutboxEvent.objects.filter(
            recipient_email=self.manager.email,
            event_type__in=("kb.article.approved", "kb.article.rejected"),
        ).values_list("event_type", flat=True)
        self.assertEqual(len(event_types), 1)
        self.assertEqual(AuditLog.objects.filter(
            entity_type="assets.knowledgebasearticle", object_id=str(article.pk),
            details__action__in=("approve", "reject")).count(), 1)

    def test_concurrent_versioned_edits_create_one_revision(self):
        article = self._create_article("kb-concurrent-edits")
        path = f"/api/assets/knowledge-base/{article.pk}/"
        results = self._race([
            lambda: self._request(self.manager, "patch", path, {
                "version": article.version, "title": "First edit"}),
            lambda: self._request(self.admin, "patch", path, {
                "version": article.version, "title": "Second edit"}),
        ])
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        article.refresh_from_db()
        self.assertEqual(article.version, 2)
        self.assertEqual(article.revision_number, 2)
        self.assertEqual(list(article.revisions.order_by(
            "revision_number").values_list("revision_number", flat=True)),
            [1, 2])
        self.assertIn(article.title, ("First edit", "Second edit"))

    def test_publish_racing_update_leaves_one_valid_versioned_result(self):
        article = self._submit(self._create_article("kb-publish-update"))
        article = self._approve(article)
        version = article.version
        publish_path = f"/api/assets/knowledge-base/{article.pk}/publish/"
        detail_path = f"/api/assets/knowledge-base/{article.pk}/"
        results = self._race([
            lambda: self._request(self.admin, "post", publish_path,
                                  {"version": version}),
            lambda: self._request(self.manager, "patch", detail_path,
                                  {"version": version,
                                   "title": "Concurrent content edit"}),
        ])
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        article.refresh_from_db()
        if article.status == "published":
            self.assertEqual(article.version, version + 1)
            self.assertEqual(article.title, "Race article")
            self.assertEqual(article.revisions.count(), 1)
            self.assertEqual(NotificationOutboxEvent.objects.filter(
                event_type="kb.article.published",
                recipient_email=self.manager.email).count(), 1)
        else:
            self.assertEqual(article.status, "approved")
            self.assertEqual(article.version, version + 1)
            self.assertEqual(article.title, "Concurrent content edit")
            self.assertEqual(article.revisions.count(), 2)
            self.assertFalse(NotificationOutboxEvent.objects.filter(
                event_type="kb.article.published",
                recipient_email=self.manager.email).exists())

    def test_unauthorized_approval_racing_valid_approval_has_no_side_effect(self):
        article = self._submit(self._create_article("kb-unauthorized-race"))
        path = f"/api/assets/knowledge-base/{article.pk}/approve/"
        before = NotificationOutboxEvent.objects.count()
        results = self._race([
            lambda: self._request(self.admin, "post", path,
                                  {"version": article.version}),
            lambda: self._request(self.employee, "post", path,
                                  {"version": article.version}),
        ])
        self.assertEqual(sorted(status for status, _ in results), [200, 403])
        article.refresh_from_db()
        self.assertEqual(article.status, "approved")
        self.assertEqual(NotificationOutboxEvent.objects.count(), before + 1)
        self.assertEqual(NotificationOutboxEvent.objects.filter(
            event_type="kb.article.approved",
            recipient_email=self.manager.email).count(), 1)
