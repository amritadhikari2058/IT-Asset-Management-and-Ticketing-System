"""Phase 20 tests: KB article versioning, review workflow, concurrency.

Everything goes through the real API + database so the tests exercise the
same permission checks, transactions and audit writes as production.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.tests import auth, make_users
from assets.models import (
    KnowledgeBaseArticle, KnowledgeBaseArticleRevision, KnowledgeBaseCategory,
    KnowledgeBaseTag,
)
from common.models import AuditLog


class KnowledgeBaseTestBase(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        self.category = KnowledgeBaseCategory.objects.create(
            name="Networking", code="networking")
        self.tag = KnowledgeBaseTag.objects.create(name="VPN", slug="vpn")

    def create_article(self, **overrides):
        auth(self.c, self.mgr)
        payload = {
            "title": "VPN reset",
            "slug": "vpn-reset",
            "summary": "How to reset the VPN client",
            "content": "Step one",
            "status": "draft",
            "category": "networking",
            "tags": ["vpn"],
            "change_note": "Initial draft",
        }
        payload.update(overrides)
        res = self.c.post("/api/assets/knowledge-base/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return res.data

    def patch_article(self, article_id, payload, user=None):
        auth(self.c, user or self.mgr)
        res = self.c.patch(
            f"/api/assets/knowledge-base/{article_id}/", payload, format="json")
        return res

    def get_article(self, article_id, user=None):
        auth(self.c, user or self.mgr)
        return self.c.get(f"/api/assets/knowledge-base/{article_id}/")

    def revisions(self, article_id, user=None):
        auth(self.c, user or self.mgr)
        return self.c.get(
            f"/api/assets/knowledge-base/{article_id}/revisions/")


class RevisionCreationTests(KnowledgeBaseTestBase):
    def test_create_article_creates_initial_revision(self):
        data = self.create_article()
        article = KnowledgeBaseArticle.objects.get(pk=data["id"])
        self.assertEqual(article.version, 1)
        self.assertEqual(article.revision_number, 1)
        revision = article.revisions.get(revision_number=1)
        self.assertEqual(revision.title, "VPN reset")
        self.assertEqual(revision.summary, "How to reset the VPN client")
        self.assertEqual(revision.content, "Step one")
        self.assertEqual(revision.category_name, "Networking")
        self.assertEqual(revision.tags, [{"name": "VPN", "slug": "vpn"}])
        self.assertEqual(revision.editor, self.mgr)
        self.assertEqual(revision.change_note, "Initial draft")
        self.assertEqual(revision.status, "draft")
        # Read API exposes the full article so edit forms are populated.
        self.assertEqual(data["content"], "Step one")
        self.assertEqual(data["summary"], "How to reset the VPN client")
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["revision_number"], 1)

    def test_update_creates_sequential_revisions(self):
        data = self.create_article()
        res = self.patch_article(data["id"], {
            "title": "VPN reset v2",
            "change_note": "Clarified step one",
            "version": data["version"],
        })
        self.assertEqual(res.status_code, 200, res.data)
        res = self.patch_article(data["id"], {
            "content": "Step one\nStep two",
            "version": res.data["version"],
        })
        self.assertEqual(res.status_code, 200, res.data)

        article = KnowledgeBaseArticle.objects.get(pk=data["id"])
        numbers = list(
            article.revisions.order_by("revision_number")
            .values_list("revision_number", flat=True))
        self.assertEqual(numbers, [1, 2, 3])
        self.assertEqual(article.revision_number, 3)
        self.assertEqual(article.version, 3)
        self.assertEqual(article.revisions.get(revision_number=2).title,
                         "VPN reset v2")
        self.assertEqual(article.revisions.get(revision_number=2).change_note,
                         "Clarified step one")
        self.assertEqual(
            article.revisions.get(revision_number=3).content,
            "Step one\nStep two")

    def test_unchanged_update_creates_no_revision(self):
        data = self.create_article()
        res = self.patch_article(data["id"], {
            "title": "VPN reset",
            "summary": "How to reset the VPN client",
            "content": "Step one",
            "category": "networking",
            "tags": ["vpn"],
            "version": data["version"],
        })
        self.assertEqual(res.status_code, 200, res.data)
        article = KnowledgeBaseArticle.objects.get(pk=data["id"])
        self.assertEqual(article.revisions.count(), 1)
        self.assertEqual(article.version, 1)
        self.assertEqual(article.revision_number, 1)

    def test_revision_history_permissions(self):
        data = self.create_article()
        res = self.revisions(data["id"], user=self.emp)
        self.assertEqual(res.status_code, 403, res.data)
        res = self.revisions(data["id"], user=self.mgr)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["revision_number"], 1)
        self.assertEqual(res.data[0]["editor_name"],
                         self.mgr.get_full_name() or self.mgr.email)

    def test_employee_cannot_see_draft_or_revision(self):
        data = self.create_article()
        res = self.get_article(data["id"], user=self.emp)
        self.assertEqual(res.status_code, 404, res.data)
        article = KnowledgeBaseArticle.objects.get(pk=data["id"])
        article.status = "published"
        article.save(update_fields=["status"])
        res = self.get_article(data["id"], user=self.emp)
        self.assertEqual(res.status_code, 200, res.data)
        res = self.revisions(data["id"], user=self.emp)
        self.assertEqual(res.status_code, 403, res.data)

    def test_employee_cannot_create_or_edit_articles(self):
        auth(self.c, self.emp)
        res = self.c.post("/api/assets/knowledge-base/", {
            "title": "Nope", "slug": "nope", "content": "x",
        }, format="json")
        self.assertEqual(res.status_code, 403, res.data)
        data = self.create_article()
        res = self.patch_article(data["id"], {"title": "Hijacked"},
                                 user=self.emp)
        self.assertEqual(res.status_code, 403, res.data)


class RevisionComparisonTests(KnowledgeBaseTestBase):
    def test_compare_returns_ordered_human_readable_diff(self):
        data = self.create_article()
        res = self.patch_article(data["id"], {
            "title": "VPN reset guide",
            "summary": "A better summary",
            "content": "Step one\nStep two",
            "version": data["version"],
        })
        self.assertEqual(res.status_code, 200, res.data)

        auth(self.c, self.mgr)
        res = self.c.get(
            f"/api/assets/knowledge-base/{data['id']}/compare/",
            {"from_revision": 2, "to_revision": 1})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["older"]["revision_number"], 1)
        self.assertEqual(res.data["newer"]["revision_number"], 2)
        self.assertTrue(res.data["fields"]["title"]["changed"])
        self.assertTrue(res.data["fields"]["summary"]["changed"])
        lines = res.data["fields"]["content"]["lines"]
        self.assertIn({"type": "added", "text": "Step two"}, lines)
        added = [line["text"] for line in lines if line["type"] == "added"]
        self.assertIn("Step two", added)

    def test_compare_rejects_revision_from_another_article(self):
        first = self.create_article()
        second = self.create_article(title="Second", slug="second")
        auth(self.c, self.mgr)
        res = self.c.get(
            f"/api/assets/knowledge-base/{first['id']}/compare/",
            {"from_revision": 1, "to_revision": 99})
        self.assertEqual(res.status_code, 404, res.data)
        res = self.c.get(
            f"/api/assets/knowledge-base/{second['id']}/revisions/99/")
        self.assertEqual(res.status_code, 404, res.data)

    def test_compare_requires_permission(self):
        data = self.create_article()
        auth(self.c, self.emp)
        res = self.c.get(
            f"/api/assets/knowledge-base/{data['id']}/compare/",
            {"from_revision": 1, "to_revision": 1})
        self.assertEqual(res.status_code, 403, res.data)


class RevisionRestoreTests(KnowledgeBaseTestBase):
    def test_restore_creates_new_revision_and_preserves_history(self):
        data = self.create_article(content="one")
        res = self.patch_article(data["id"], {
            "content": "two", "version": data["version"]})
        res = self.patch_article(data["id"], {
            "content": "three", "version": res.data["version"]})
        self.assertEqual(res.status_code, 200, res.data)

        auth(self.c, self.mgr)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/restore/",
            {"revision_number": 1, "version": res.data["version"]},
            format="json")
        self.assertEqual(res.status_code, 200, res.data)
        article = KnowledgeBaseArticle.objects.get(pk=data["id"])
        self.assertEqual(article.content, "one")
        self.assertEqual(article.revision_number, 4)
        self.assertEqual(article.revisions.count(), 4)
        numbers = list(article.revisions.order_by("revision_number")
                       .values_list("revision_number", flat=True))
        self.assertEqual(numbers, [1, 2, 3, 4])
        restored = article.revisions.get(revision_number=4)
        self.assertEqual(restored.content, "one")
        self.assertEqual(restored.restored_from_revision, 1)
        self.assertIn("Restored from revision 1", restored.change_note)
        self.assertEqual(restored.editor, self.mgr)
        # Newer revisions are still intact.
        self.assertEqual(article.revisions.get(revision_number=2).content,
                         "two")
        self.assertEqual(article.revisions.get(revision_number=3).content,
                         "three")

    def test_restore_conflict_returns_409_and_changes_nothing(self):
        data = self.create_article(content="one")
        res = self.patch_article(data["id"], {
            "content": "two", "version": data["version"]})
        stale_version = data["version"]
        auth(self.c, self.mgr)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/restore/",
            {"revision_number": 1, "version": stale_version},
            format="json")
        self.assertEqual(res.status_code, 409, res.data)
        article = KnowledgeBaseArticle.objects.get(pk=data["id"])
        self.assertEqual(article.content, "two")
        self.assertEqual(article.revisions.count(), 2)

    def test_restore_requires_staff(self):
        data = self.create_article()
        auth(self.c, self.emp)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/restore/",
            {"revision_number": 1}, format="json")
        self.assertEqual(res.status_code, 403, res.data)


class ReviewWorkflowTests(KnowledgeBaseTestBase):
    def test_submit_approve_publish_flow_records_reviewer(self):
        data = self.create_article()
        auth(self.c, self.mgr)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/submit_review/",
            {"version": data["version"], "note": "Ready for review"},
            format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "pending_review")
        self.assertEqual(res.data["review_decision"], "pending")
        self.assertIsNotNone(res.data["submitted_at"])

        # Author cannot approve their own article.
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/approve/",
            {"version": res.data["version"]}, format="json")
        self.assertEqual(res.status_code, 403, res.data)

        auth(self.c, self.admin)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/approve/",
            {"version": data["version"] + 1, "comment": "Looks accurate"},
            format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "approved")
        self.assertEqual(res.data["review_decision"], "approved")
        self.assertEqual(res.data["reviewed_by"], self.admin.pk)
        self.assertEqual(res.data["review_comment"], "Looks accurate")

        auth(self.c, self.mgr)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/publish/",
            {"version": res.data["version"]}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "published")

        # Employees can now retrieve it and see the current content.
        auth(self.c, self.emp)
        res = self.c.get(f"/api/assets/knowledge-base/{data['id']}/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["content"], "Step one")

    def test_reject_requires_reason_and_returns_to_draft(self):
        data = self.create_article()
        auth(self.c, self.mgr)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/submit_review/",
            {"version": data["version"]}, format="json")
        pending_version = res.data["version"]

        auth(self.c, self.admin)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/reject/",
            {"version": pending_version, "comment": ""}, format="json")
        self.assertEqual(res.status_code, 400, res.data)

        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/reject/",
            {"version": pending_version, "comment": "Add screenshots"},
            format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "draft")
        self.assertEqual(res.data["review_decision"], "rejected")
        self.assertEqual(res.data["review_comment"], "Add screenshots")
        self.assertEqual(res.data["reviewed_by"], self.admin.pk)

    def test_unauthorized_employee_cannot_publish_or_review(self):
        data = self.create_article()
        auth(self.c, self.mgr)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/submit_review/",
            {"version": data["version"]}, format="json")
        pending_version = res.data["version"]

        auth(self.c, self.emp)
        for action, payload in (
                ("approve", {"version": pending_version}),
                ("reject", {"version": pending_version, "comment": "no"}),
                ("publish", {"version": pending_version}),
                ("submit_review", {"version": pending_version})):
            res = self.c.post(
                f"/api/assets/knowledge-base/{data['id']}/{action}/",
                payload, format="json")
            self.assertEqual(res.status_code, 403, (action, res.data))

    def test_publish_requires_approval(self):
        data = self.create_article()
        auth(self.c, self.mgr)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/publish/",
            {"version": data["version"]}, format="json")
        self.assertEqual(res.status_code, 400, res.data)
        article = KnowledgeBaseArticle.objects.get(pk=data["id"])
        self.assertEqual(article.status, "draft")

    def test_pending_review_queue_is_staff_only(self):
        data = self.create_article(title="Queued", slug="queued")
        auth(self.c, self.mgr)
        self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/submit_review/",
            {"version": data["version"]}, format="json")
        res = self.c.get("/api/assets/knowledge-base/pending_review/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["id"], data["id"])
        auth(self.c, self.emp)
        res = self.c.get("/api/assets/knowledge-base/pending_review/")
        self.assertEqual(res.status_code, 403, res.data)

    def test_archive_requires_staff_and_is_audited(self):
        data = self.create_article(status="published")
        auth(self.c, self.emp)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/archive/",
            {"version": data["version"]}, format="json")
        self.assertEqual(res.status_code, 403, res.data)
        auth(self.c, self.mgr)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/archive/",
            {"version": data["version"]}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "archived")
        self.assertTrue(AuditLog.objects.filter(
            entity_type="assets.knowledgebasearticle",
            action="status_change",
            object_id=str(data["id"]),
            details__action="archive").exists())


class ConcurrentEditingTests(KnowledgeBaseTestBase):
    def test_stale_version_returns_409_and_does_not_overwrite(self):
        data = self.create_article(content="original")
        res = self.patch_article(data["id"], {
            "content": "first editor", "version": data["version"]})
        self.assertEqual(res.status_code, 200, res.data)

        # Second editor still holds the version they originally loaded.
        res = self.patch_article(data["id"], {
            "content": "second editor", "version": data["version"]})
        self.assertEqual(res.status_code, 409, res.data)
        self.assertIn("detail", res.data)
        self.assertEqual(int(res.data["current_version"]), data["version"] + 1)
        article = KnowledgeBaseArticle.objects.get(pk=data["id"])
        self.assertEqual(article.content, "first editor")
        self.assertEqual(article.revisions.count(), 2)

    def test_review_action_with_stale_version_returns_409(self):
        data = self.create_article()
        auth(self.c, self.mgr)
        self.c.patch(f"/api/assets/knowledge-base/{data['id']}/",
                     {"title": "Changed", "version": data["version"]},
                     format="json")
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/submit_review/",
            {"version": data["version"]}, format="json")
        self.assertEqual(res.status_code, 409, res.data)

    def test_audit_trail_covers_create_edit_revision_restore_and_review(self):
        data = self.create_article(content="one")
        res = self.patch_article(data["id"], {
            "content": "two", "version": data["version"]})
        auth(self.c, self.mgr)
        restored = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/restore/",
            {"revision_number": 1, "version": res.data["version"]},
            format="json")
        self.assertEqual(restored.status_code, 200, restored.data)
        res = self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/submit_review/",
            {"version": restored.data["article"]["version"]},
            format="json")
        self.assertEqual(res.status_code, 200, res.data)
        auth(self.c, self.admin)
        self.c.post(
            f"/api/assets/knowledge-base/{data['id']}/approve/",
            {"version": res.data["version"], "comment": "ok"}, format="json")

        article_audit = AuditLog.objects.filter(
            entity_type="assets.knowledgebasearticle",
            object_id=str(data["id"]))
        self.assertTrue(article_audit.filter(action="create").exists())
        self.assertTrue(article_audit.filter(action="update").exists())
        self.assertTrue(article_audit.filter(action="status_change").exists())
        revision_audit = AuditLog.objects.filter(
            entity_type="assets.knowledgebasearticlerevision")
        self.assertEqual(revision_audit.count(), 3)

    def test_revision_number_and_rows_stay_consistent(self):
        data = self.create_article(content="a")
        version = data["version"]
        for index in range(1, 6):
            res = self.patch_article(data["id"], {
                "content": f"content {index}", "version": version})
            self.assertEqual(res.status_code, 200, res.data)
            version = res.data["version"]
        article = KnowledgeBaseArticle.objects.get(pk=data["id"])
        numbers = list(article.revisions.order_by("revision_number")
                       .values_list("revision_number", flat=True))
        self.assertEqual(numbers, [1, 2, 3, 4, 5, 6])
        self.assertEqual(article.revision_number, 6)
        self.assertEqual(article.version, 6)
        self.assertEqual(article.revisions.count(), article.revision_number)
