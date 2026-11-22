"""API authorization and information-disclosure regressions for the KB."""

from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from assets.models import (
    KnowledgeBaseArticle, KnowledgeBaseArticleRevision, KnowledgeBaseCategory,
    KnowledgeBaseFeedback,
)
from common.models import AuditLog, Notification, NotificationOutboxEvent


class KnowledgeBaseAuthorizationSecurityTests(TestCase):
    def setUp(self):
        self.department, self.admin, self.manager, self.employee = make_users()
        self.support = type(self.manager).objects.create_user(
            employee_id="S-KB", username="support-kb", email="support-kb@x",
            password="test-password", role="it_support",
            home_department=self.department)
        self.category = KnowledgeBaseCategory.objects.create(
            name="Security KB", code="security-kb")
        self.client = APIClient()
        self.published = self._article(
            "Published guide", "published-guide", "published",
            author=self.manager, reviewed_by=self.admin,
            review_decision="approved", review_comment="Internal review note",
        )
        self.draft = self._article(
            "Confidential draft", "confidential-draft", "draft",
            author=self.employee)
        self.pending = self._article(
            "Pending guide", "pending-guide", "pending_review",
            author=self.manager, review_decision="pending")
        self.approved = self._article(
            "Approved guide", "approved-guide", "approved",
            author=self.manager, reviewed_by=self.admin,
            review_decision="approved")
        self.rejected = self._article(
            "Rejected guide", "rejected-guide", "draft",
            author=self.manager, reviewed_by=self.admin,
            review_decision="rejected", review_comment="Add a security step")
        self.archived = self._article(
            "Archived guide", "archived-guide", "archived",
            author=self.manager)

    def _article(self, title, slug, status, **extra):
        return KnowledgeBaseArticle.objects.create(
            title=title, slug=slug, summary=f"Summary for {title}",
            content=f"Secret body for {title}", category=self.category,
            status=status, **extra)

    def test_anonymous_cannot_list_retrieve_or_search(self):
        for url in (
                "/api/assets/knowledge-base/",
                f"/api/assets/knowledge-base/{self.published.pk}/",
                "/api/common/knowledge-base/?q=Published"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 401)
        response = self.client.post("/api/assets/knowledge-base/", {
            "title": "Anonymous article", "slug": "anonymous-article",
            "content": "No",
        }, format="json")
        self.assertEqual(response.status_code, 401)

    def test_employee_lists_only_published_before_search_and_pagination(self):
        auth(self.client, self.employee)
        response = self.client.get("/api/assets/knowledge-base/?page_size=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual([row["id"] for row in response.data["results"]],
                         [self.published.pk])
        for query in ("Confidential", "Pending", "Rejected", "Archived"):
            search = self.client.get(
                "/api/assets/knowledge-base/", {"q": query})
            self.assertEqual(search.status_code, 200)
            self.assertEqual(search.data["count"], 0)
        for state in ("draft", "pending_review", "approved", "archived"):
            filtered = self.client.get(
                "/api/assets/knowledge-base/", {"status": state})
            self.assertEqual(filtered.status_code, 200)
            self.assertEqual(filtered.data["count"], 0)

    def test_employee_direct_ids_hide_all_unpublished_states(self):
        auth(self.client, self.employee)
        protected = (
            ("draft", self.draft), ("pending_review", self.pending),
            ("approved", self.approved),
            ("rejected draft", self.rejected), ("archived", self.archived),
        )
        for state, article in protected:
            with self.subTest(state=state):
                response = self.client.get(
                    f"/api/assets/knowledge-base/{article.pk}/")
                self.assertEqual(response.status_code, 404)

    def test_employee_cannot_read_revision_or_workflow_endpoints_by_id(self):
        revision = KnowledgeBaseArticleRevision.objects.create(
            article=self.published, revision_number=1,
            title=self.published.title, slug=self.published.slug,
            summary=self.published.summary, content=self.published.content,
            category=self.category, category_name=self.category.name,
            status="published", author=self.manager, editor=self.admin,
            editor_name="Review Admin", change_note="Internal note")
        auth(self.client, self.manager)
        staff_detail = self.client.get(
            f"/api/assets/knowledge-base/{self.published.pk}/revisions/1/")
        self.assertEqual(staff_detail.status_code, 200, staff_detail.data)
        self.assertEqual(staff_detail.data["change_note"], "Internal note")
        auth(self.client, self.employee)
        urls = (
            f"/api/assets/knowledge-base/{self.published.pk}/revisions/",
            f"/api/assets/knowledge-base/{self.published.pk}/revisions/{revision.revision_number}/",
            f"/api/assets/knowledge-base/{self.published.pk}/compare/?from_revision=1&to_revision=1",
            f"/api/assets/knowledge-base/{self.draft.pk}/restore/",
            "/api/assets/knowledge-base/pending_review/",
        )
        for url in urls:
            with self.subTest(url=url):
                response = (self.client.post(url, {"revision_number": 1},
                                             format="json")
                            if url.endswith("restore/") else
                            self.client.get(url))
                self.assertEqual(response.status_code, 403)

    def test_published_article_hides_review_and_rejection_metadata_from_employee(self):
        auth(self.client, self.employee)
        response = self.client.get(
            f"/api/assets/knowledge-base/{self.published.pk}/")
        self.assertEqual(response.status_code, 200)
        for field in ("submitted_at", "reviewed_by", "reviewed_by_name",
                      "reviewed_at", "review_decision", "review_comment"):
            self.assertNotIn(field, response.data)
        self.assertEqual(response.data["content"], self.published.content)

    def test_it_staff_can_access_governance_metadata_and_unpublished_articles(self):
        auth(self.client, self.support)
        response = self.client.get(
            f"/api/assets/knowledge-base/{self.pending.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "pending_review")
        self.assertIn("review_decision", response.data)

    def test_it_support_can_approve_another_authors_pending_article(self):
        auth(self.client, self.support)
        response = self.client.post(
            f"/api/assets/knowledge-base/{self.pending.pk}/approve/",
            {"comment": "Support review"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, "approved")
        self.assertEqual(self.pending.reviewed_by, self.support)

    def test_employee_cannot_create_or_change_articles(self):
        auth(self.client, self.employee)
        response = self.client.post("/api/assets/knowledge-base/", {
            "title": "Unauthorized", "slug": "unauthorized",
            "content": "No", "status": "published",
        }, format="json")
        self.assertEqual(response.status_code, 403)
        response = self.client.patch(
            f"/api/assets/knowledge-base/{self.published.pk}/",
            {"title": "Modified"}, format="json")
        self.assertEqual(response.status_code, 403)
        response = self.client.delete(
            f"/api/assets/knowledge-base/{self.published.pk}/")
        self.assertEqual(response.status_code, 403)
        self.published.refresh_from_db()
        self.assertEqual(self.published.title, "Published guide")
        self.assertTrue(KnowledgeBaseArticle.objects.filter(
            pk=self.published.pk).exists())

    def test_create_cannot_mass_assign_review_fields_or_initial_publication(self):
        auth(self.client, self.manager)
        base = {"title": "Workflow required", "slug": "workflow-required",
                "content": "Draft text"}
        bypass = self.client.post(
            "/api/assets/knowledge-base/",
            {**base, "status": "published", "author": self.employee.pk,
             "reviewed_by": self.admin.pk, "review_decision": "approved",
             "review_comment": "Forged approval"}, format="json")
        self.assertEqual(bypass.status_code, 400)
        self.assertFalse(KnowledgeBaseArticle.objects.filter(
            slug="workflow-required").exists())
        response = self.client.post(
            "/api/assets/knowledge-base/",
            {**base, "author": self.employee.pk,
             "reviewed_by": self.admin.pk, "review_decision": "approved",
             "review_comment": "Forged approval"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        created = KnowledgeBaseArticle.objects.get(pk=response.data["id"])
        self.assertEqual(created.status, "draft")
        self.assertEqual(created.author, self.manager)
        self.assertIsNone(created.reviewed_by)
        self.assertEqual(created.review_decision, "")
        self.assertEqual(created.review_comment, "")

    def test_update_cannot_mass_assign_author_or_review_fields(self):
        auth(self.client, self.manager)
        response = self.client.patch(
            f"/api/assets/knowledge-base/{self.published.pk}/", {
                "title": "Edited safely", "author": self.employee.pk,
                "reviewed_by": None, "review_decision": "rejected",
                "review_comment": "Forged update", "reviewed_at": None,
            }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.published.refresh_from_db()
        self.assertEqual(self.published.title, "Edited safely")
        self.assertEqual(self.published.author, self.manager)
        self.assertEqual(self.published.reviewed_by, self.admin)
        self.assertEqual(self.published.review_decision, "approved")
        self.assertEqual(self.published.review_comment, "Internal review note")

    def test_unauthorized_review_actions_do_not_mutate_records(self):
        auth(self.client, self.employee)
        actions = {
            "submit_review": {},
            "approve": {},
            "reject": {"comment": "No"},
            "publish": {},
            "archive": {},
        }
        before = (self.pending.status, self.pending.version,
                  self.pending.review_decision, self.pending.review_comment)
        notifications_before = Notification.objects.count()
        outbox_before = NotificationOutboxEvent.objects.count()
        audit_before = AuditLog.objects.count()
        for action, payload in actions.items():
            response = self.client.post(
                f"/api/assets/knowledge-base/{self.pending.pk}/{action}/",
                payload, format="json")
            self.assertEqual(response.status_code, 403, (action, response.data))
        self.pending.refresh_from_db()
        after = (self.pending.status, self.pending.version,
                 self.pending.review_decision, self.pending.review_comment)
        self.assertEqual(after, before)
        self.assertEqual(Notification.objects.count(), notifications_before)
        self.assertEqual(NotificationOutboxEvent.objects.count(), outbox_before)
        self.assertEqual(AuditLog.objects.count(), audit_before)

    def test_author_can_manage_own_draft_but_cannot_self_approve(self):
        auth(self.client, self.manager)
        response = self.client.get(
            f"/api/assets/knowledge-base/{self.draft.pk}/")
        self.assertEqual(response.status_code, 200)
        pending = self._article(
            "Own pending", "own-pending", "pending_review",
            author=self.manager, review_decision="pending")
        response = self.client.post(
            f"/api/assets/knowledge-base/{pending.pk}/approve/", {},
            format="json")
        self.assertEqual(response.status_code, 403)
        pending.refresh_from_db()
        self.assertEqual(pending.status, "pending_review")

    def test_feedback_cannot_be_created_or_moved_to_unpublished_article(self):
        auth(self.client, self.employee)
        response = self.client.post(
            "/api/assets/knowledge-base-feedback/",
            {"article": self.draft.pk, "helpful": True,
             "comment": "Draft feedback"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(KnowledgeBaseFeedback.objects.filter(
            user=self.employee, article=self.draft).exists())

        feedback = KnowledgeBaseFeedback.objects.create(
            article=self.published, user=self.employee, helpful=True)
        response = self.client.patch(
            f"/api/assets/knowledge-base-feedback/{feedback.pk}/",
            {"article": self.pending.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        feedback.refresh_from_db()
        self.assertEqual(feedback.article, self.published)

    def test_approved_rejected_and_published_events_are_registered_in_outbox(self):
        auth(self.client, self.admin)
        approved = self.client.post(
            f"/api/assets/knowledge-base/{self.pending.pk}/approve/",
            {"comment": "Reviewed"}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        published = self.client.post(
            f"/api/assets/knowledge-base/{self.pending.pk}/publish/",
            {}, format="json")
        self.assertEqual(published.status_code, 200, published.data)

        rejected = self._article(
            "Rejected for reason", "rejected-for-reason", "pending_review",
            author=self.manager, review_decision="pending")
        rejected_response = self.client.post(
            f"/api/assets/knowledge-base/{rejected.pk}/reject/",
            {"comment": "Needs a valid source"}, format="json")
        self.assertEqual(rejected_response.status_code, 200,
                         rejected_response.data)

        for event_type in ("kb.article.approved", "kb.article.rejected",
                           "kb.article.published"):
            with self.subTest(event_type=event_type):
                self.assertTrue(NotificationOutboxEvent.objects.filter(
                    event_type=event_type,
                    recipient_email=self.manager.email).exists())

    def test_review_outbox_failure_rolls_back_article_transition(self):
        auth(self.client, self.admin)
        before = NotificationOutboxEvent.objects.count()
        notifications_before = Notification.objects.count()
        with patch("assets.kb_services.enqueue_email",
                   side_effect=RuntimeError("simulated outbox failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    f"/api/assets/knowledge-base/{self.pending.pk}/approve/",
                    {}, format="json")
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, "pending_review")
        self.assertEqual(NotificationOutboxEvent.objects.count(), before)
        self.assertEqual(Notification.objects.count(), notifications_before)
