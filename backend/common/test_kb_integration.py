"""Phase 21: employee-facing KB search, KB export, KB workflow notifications.

Everything goes through the real API + database so the tests exercise the
same permission checks, transactions and audit writes as production.
"""
from django.core import mail
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from assets.models import (
    KnowledgeBaseArticle, KnowledgeBaseCategory, KnowledgeBaseTag,
)
from common.models import Notification, UserNotificationPreference


@override_settings(
    **{"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"})
class KnowledgeBaseSearchTests(TestCase):
    """Employee-facing published-only KB search at /api/common/knowledge-base/."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.category = KnowledgeBaseCategory.objects.create(
            name="Networking", code="networking")
        self.tag = KnowledgeBaseTag.objects.create(name="VPN", slug="vpn")
        self.tag_mail = KnowledgeBaseTag.objects.create(name="Mail", slug="mail")

    def _publish(self, **overrides):
        auth(self.c, self.mgr)
        payload = {
            "title": "VPN reset",
            "slug": "vpn-reset",
            "summary": "How to reset the VPN client",
            "content": "Step one",
            "status": "published",
            "category": "networking",
            "tags": ["vpn"],
        }
        payload.update(overrides)
        res = self.c.post("/api/assets/knowledge-base/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return res.data

    def _search(self, user, params=None):
        auth(self.c, user)
        return self.c.get("/api/common/knowledge-base/", params or {})

    def test_authenticated_employee_can_search(self):
        self._publish()
        res = self._search(self.emp, {"q": "vpn"})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn("results", res.data)
        self.assertTrue(any("vpn" in r["title"].lower()
                            for r in res.data["results"]))

    def test_search_matches_title_and_content(self):
        self._publish(title="Database backup", slug="db-backup",
                      content="Run pg_dump nightly.")
        self._publish(title="VPN reset", slug="vpn-reset",
                      content="Restart the VPN client.")
        res = self._search(self.emp, {"q": "pg_dump"})
        self.assertEqual(res.status_code, 200, res.data)
        titles = [r["title"] for r in res.data["results"]]
        self.assertIn("Database backup", titles)
        self.assertNotIn("VPN reset", titles)

    def test_search_category_and_tag_filter(self):
        self._publish(category="networking", tags=["vpn"])
        self._publish(title="Email setup", slug="email-setup",
                      category="networking", tags=["mail"])
        res = self._search(self.emp, {"tag": "vpn"})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(len(res.data["results"]), 1)
        self.assertEqual(res.data["results"][0]["title"], "VPN reset")

    def test_search_pagination(self):
        for index in range(25):
            self._publish(title=f"Article {index}", slug=f"article-{index}",
                          content="published content")
        res = self._search(self.emp)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["count"], 25)
        self.assertEqual(len(res.data["results"]), 20)  # default page size
        self.assertIsNotNone(res.data["next"])
        page2 = self._search(self.emp, {"page": 2})
        self.assertEqual(len(page2.data["results"]), 5)

    def test_search_empty_results(self):
        res = self._search(self.emp, {"q": "zzz-no-such-article"})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["count"], 0)
        self.assertEqual(res.data["results"], [])

    def test_unauthenticated_search_rejected(self):
        res = self.c.get("/api/common/knowledge-base/", {"q": "vpn"})
        self.assertEqual(res.status_code, 401, res.data)

    def test_unpublished_statuses_excluded(self):
        self._publish(status="published")
        for status in ("draft", "pending_review", "approved", "archived"):
            self._publish(status=status, title=f"{status} article",
                          slug=f"{status}-article")
        # All articles whose title contains "article" are unpublished, so
        # they must all be excluded.
        res = self._search(self.emp, {"q": "article"})
        self.assertEqual(res.status_code, 200, res.data)
        titles = [r["title"] for r in res.data["results"]]
        self.assertEqual(titles, [])
        # The published article remains findable by its own keyword.
        res = self._search(self.emp, {"q": "vpn"})
        self.assertEqual(res.status_code, 200, res.data)
        titles = [r["title"] for r in res.data["results"]]
        self.assertIn("VPN reset", titles)
        for status in ("draft", "pending_review", "approved", "archived"):
            self.assertNotIn(f"{status} article", titles)

    def test_employee_can_navigate_to_published_article_detail(self):
        data = self._publish()
        auth(self.c, self.emp)
        res = self.c.get(f"/api/assets/knowledge-base/{data['id']}/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["title"], "VPN reset")
        # Drafts remain invisible to employees (re-auth as emp after create).
        draft = self._publish(status="draft", title="Secret", slug="secret")
        auth(self.c, self.emp)
        res = self.c.get(f"/api/assets/knowledge-base/{draft['id']}/")
        self.assertEqual(res.status_code, 404, res.data)


@override_settings(
    **{"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"})
class KnowledgeBaseExportTests(TestCase):
    """KB export dataset integrated into the existing export infrastructure."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.category = KnowledgeBaseCategory.objects.create(
            name="Networking", code="networking")
        self.tag = KnowledgeBaseTag.objects.create(name="VPN", slug="vpn")

    def _publish(self, status="published", **overrides):
        auth(self.c, self.mgr)
        payload = {
            "title": "VPN reset",
            "slug": "vpn-reset",
            "summary": "How to reset the VPN client",
            "content": "Step one",
            "status": status,
            "category": "networking",
            "tags": ["vpn"],
        }
        payload.update(overrides)
        res = self.c.post("/api/assets/knowledge-base/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return res.data

    def _export(self, user, fmt="csv", **params):
        auth(self.c, user)
        return self.c.get(
            "/api/common/exports/knowledge_base/",
            {"format": fmt, **params})

    def test_knowledge_base_dataset_registered(self):
        res = self._export(self.emp)
        # Export endpoint streams a file (HttpResponse), not JSON.
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("attachment", res["Content-Disposition"])
        blob = res.content.decode("utf-8")
        self.assertIn("title", blob)
        self.assertIn("slug", blob)
        self.assertIn("status", blob)

    def test_knowledge_base_export_all_formats(self):
        self._publish()
        for fmt in ("csv", "xlsx", "pdf", "docx"):
            res = self._export(self.emp, fmt=fmt)
            self.assertEqual(res.status_code, 200, (fmt, res.content))
            self.assertTrue(res.content, f"empty {fmt}")

    def test_employee_can_export_knowledge_base(self):
        self._publish()
        res = self._export(self.emp)
        self.assertEqual(res.status_code, 200)

    def test_export_only_includes_published_articles(self):
        self._publish(status="published")
        self._publish(status="draft", title="Secret draft", slug="secret")
        self._publish(status="archived", title="Old", slug="old")
        res = self._export(self.emp)
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("VPN reset", blob)
        self.assertNotIn("Secret draft", blob)
        self.assertNotIn("Old", blob)

    def test_export_exported_fields(self):
        self._publish()
        res = self._export(self.emp)
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        header = blob.splitlines()[0]
        for field in ("id", "title", "slug", "summary", "category", "tags",
                      "status", "author", "created_at", "updated_at",
                      "revision_number"):
            self.assertIn(field, header)

    def test_export_search_filtering(self):
        self._publish(title="Alpha", slug="alpha")
        self._publish(title="Beta", slug="beta")
        # scope="filtered" applies query params (q) to the export rows.
        res = self._export(self.emp, scope="filtered", q="Alpha")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("Alpha", blob)
        self.assertNotIn("Beta", blob)

    def test_export_empty_dataset(self):
        res = self._export(self.emp)
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("title", blob)  # header only, no rows


@override_settings(
    **{"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"})
class KnowledgeBaseNotificationTests(TransactionTestCase):
    """KB workflow notifications: recipients, messages, preferences, dedup.

    TransactionTestCase is used because the notifications are delivered via
    ``transaction.on_commit()``, which only fires on a real transaction
    commit (rolled back under plain TestCase).
    """

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.category = KnowledgeBaseCategory.objects.create(
            name="Networking", code="networking")
        self.tag = KnowledgeBaseTag.objects.create(name="VPN", slug="vpn")
        mail.outbox = []

    def _create(self, status="draft"):
        auth(self.c, self.mgr)
        res = self.c.post("/api/assets/knowledge-base/", {
            "title": "VPN reset", "slug": "vpn-reset",
            "summary": "How to reset", "content": "Step one",
            "status": status, "category": "networking", "tags": ["vpn"],
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return res.data

    def _version(self, article_id):
        return KnowledgeBaseArticle.objects.get(pk=article_id).version

    def _count_notifications(self, recipient):
        return Notification.objects.filter(recipient=recipient).count()

    def test_submit_notifies_it_staff(self):
        data = self._create()
        before_admin = self._count_notifications(self.admin)
        auth(self.c, self.mgr)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/submit_review/",
            {"version": self._version(data['id']), "note": "Ready"},
            format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "pending_review")
        # admin (IT staff) gets notified; submitter mgr is the actor so is not
        # notified of their own action.
        self.assertEqual(
            self._count_notifications(self.admin), before_admin + 1)
        n = Notification.objects.filter(
            recipient=self.admin, entity_type="assets.KnowledgeBaseArticle"
        ).latest("created_at")
        self.assertIn("VPN reset", n.title)
        self.assertIn("submitted for review", n.body)

    def test_approve_notifies_author(self):
        data = self._create()
        auth(self.c, self.mgr)
        self.c.post(f"/api/assets/knowledge-base/{data['id']}/submit_review/",
                    {"version": self._version(data['id'])}, format="json")
        before = self._count_notifications(self.mgr)
        auth(self.c, self.admin)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/approve/",
            {"version": self._version(data['id']), "comment": "Looks accurate"},
            format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(
            self._count_notifications(self.mgr), before + 1)
        n = Notification.objects.filter(
            recipient=self.mgr).latest("created_at")
        self.assertIn("approved", n.title.lower())
        self.assertIn("VPN reset", n.body)

    def test_reject_notifies_author_with_reason(self):
        data = self._create()
        auth(self.c, self.mgr)
        self.c.post(f"/api/assets/knowledge-base/{data['id']}/submit_review/",
                    {"version": self._version(data['id'])}, format="json")
        before = self._count_notifications(self.mgr)
        auth(self.c, self.admin)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/reject/",
            {"version": self._version(data['id']), "comment": "Add screenshots"},
            format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(
            self._count_notifications(self.mgr), before + 1)
        n = Notification.objects.filter(
            recipient=self.mgr).latest("created_at")
        self.assertIn("rejected", n.title.lower())
        self.assertIn("Add screenshots", n.body)

    def test_publish_notifies_author(self):
        data = self._create()
        auth(self.c, self.mgr)
        self.c.post(f"/api/assets/knowledge-base/{data['id']}/submit_review/",
                    {"version": self._version(data['id'])}, format="json")
        auth(self.c, self.admin)
        self.c.post(f"/api/assets/knowledge-base/{data['id']}/approve/",
                    {"version": self._version(data['id'])}, format="json")
        before = self._count_notifications(self.mgr)
        # An admin other than the author publishes, so the author is notified
        # (self-notification is correctly skipped when the actor is the author).
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/publish/",
            {"version": self._version(data['id'])}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(
            self._count_notifications(self.mgr), before + 1)
        n = Notification.objects.filter(
            recipient=self.mgr).latest("created_at")
        self.assertIn("published", n.title.lower())

    def test_repeated_publish_does_not_duplicate_notification(self):
        data = self._create(status="approved")
        before = self._count_notifications(self.mgr)
        # Admin (not the author) publishes: author gets one notification.
        auth(self.c, self.admin)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/publish/",
            {"version": self._version(data['id'])}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(self._count_notifications(self.mgr), before + 1)
        # Second publish on an already-published article is idempotent: no
        # additional notification.
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/publish/",
            {"version": self._version(data['id'])}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(self._count_notifications(self.mgr), before + 1)

    def test_failed_submit_produces_no_notification(self):
        data = self._create(status="published")  # cannot submit a published article
        before = self._count_notifications(self.admin)
        auth(self.c, self.mgr)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/submit_review/",
            {"version": self._version(data['id'])}, format="json")
        self.assertEqual(res.status_code, 400, res.data)
        self.assertEqual(self._count_notifications(self.admin), before)

    def test_email_preference_gates_kb_email(self):
        from accounts import email_utils
        prefs, _ = UserNotificationPreference.objects.get_or_create(
            user=self.emp)
        prefs.categories = {"kb_review": False}
        prefs.save()
        # Disabled category -> no email.
        sent = email_utils.send_kb_notification(
            self.emp.email, "KB subject", "KB body",
            article=None, user=self.emp)
        self.assertFalse(sent)
        self.assertEqual(len(mail.outbox), 0)
        # Enabled category -> email sent (locmem backend).
        prefs.categories = {"kb_review": True}
        prefs.save()
        self._create()  # ensure an article exists for the email metadata
        article = KnowledgeBaseArticle.objects.first()
        self.assertIsNotNone(article)
        sent = email_utils.send_kb_notification(
            self.emp.email, "KB subject", "KB body",
            article=article, user=self.emp)
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("KB subject", mail.outbox[0].subject)
