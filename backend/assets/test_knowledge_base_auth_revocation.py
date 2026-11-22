"""Cross-module regressions for live KB permission revocation."""

import json

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from accounts.tests import make_users
from assets.models import KnowledgeBaseArticle, KnowledgeBaseCategory
from common.models import AuditLog, Notification, NotificationOutboxEvent


class KnowledgeBaseAuthenticationRevocationTests(TestCase):
    def setUp(self):
        self.department, self.admin, self.manager, self.employee = make_users()
        self.support = User.objects.create_user(
            username="kb-revocation-support",
            email="kb-revocation-support@example.test",
            employee_id="KB-REVOCATION-SUPPORT",
            password="test-password",
            role="it_support",
            home_department=self.department,
        )
        category = KnowledgeBaseCategory.objects.create(
            name="Revocation", code="revocation")
        self.draft = KnowledgeBaseArticle.objects.create(
            title="Restricted draft",
            slug="restricted-draft-revocation",
            summary="Draft for access revocation tests",
            content="Only current IT staff may read this draft.",
            category=category,
            status="draft",
            author=self.manager,
        )
        access = str(RefreshToken.for_user(self.support).access_token)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    def test_role_demotion_revokes_restricted_article_access_on_next_request(self):
        url = f"/api/assets/knowledge-base/{self.draft.pk}/"
        permitted = self.client.get(url)
        self.assertEqual(permitted.status_code, 200, permitted.data)

        self.support.role = "employee"
        self.support.save(update_fields=["role"])

        revoked = self.client.get(url)
        self.assertEqual(revoked.status_code, 404, revoked.data)

    def test_account_deactivation_revokes_existing_jwt(self):
        url = f"/api/assets/knowledge-base/{self.draft.pk}/"
        permitted = self.client.get(url)
        self.assertEqual(permitted.status_code, 200, permitted.data)

        self.support.is_active = False
        self.support.save(update_fields=["is_active"])

        revoked = self.client.get(url)
        self.assertEqual(revoked.status_code, 401, revoked.data)

    def test_notifications_and_audit_do_not_store_article_body(self):
        marker = "KB_PRIVATE_BODY_MARKER_83A2"
        self.draft.status = "pending_review"
        self.draft.review_decision = "pending"
        self.draft.content = marker
        self.draft.save(update_fields=["status", "review_decision", "content"])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/assets/knowledge-base/{self.draft.pk}/approve/",
                {"comment": "Reviewed"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        notification = Notification.objects.get(
            recipient=self.manager, object_id=str(self.draft.pk))
        event = NotificationOutboxEvent.objects.get(
            event_type="kb.article.approved",
            recipient_email=self.manager.email)
        audit = AuditLog.objects.get(
            entity_type="assets.knowledgebasearticle",
            object_id=str(self.draft.pk), details__action="approve")
        for payload in (
                notification.title, notification.body, event.payload,
                audit.object_repr, audit.details):
            self.assertNotIn(marker, json.dumps(payload, default=str))

        self.client.force_authenticate(user=self.employee)
        audit_response = self.client.get("/api/common/audit-logs/")
        self.assertEqual(audit_response.status_code, 403)
