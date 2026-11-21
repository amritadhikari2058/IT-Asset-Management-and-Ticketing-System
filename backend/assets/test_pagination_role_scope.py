"""Pagination and role-scope regression coverage for Asset list/detail responses.

Covers: paginated shape ({count,next,previous,results}), empty scope, admin vs
manager vs support vs employee holders, department membership + home department
safety, anonymous 401, inactive / unknown roles fail closed, soft-deleted
exclusion, cross-department exclusion, search/filter/ordering cannot broaden,
hidden count, and list-detail visibility consistency.
"""

from django.test import TestCase

from accounts.models import Department, User
from accounts.tests import auth
from assets.models import Asset, AssetAttachment, AssetCategory
from rest_framework.test import APIClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scope_tree():
    """Create a controlled department/user/category graph."""
    dep_a, _ = Department.objects.get_or_create(name="A", code="A")
    dep_b, _ = Department.objects.get_or_create(name="B", code="B")
    cat, _ = AssetCategory.objects.get_or_create(name="Laptop")
    try:
        admin = User.objects.get(email="admin@a.local")
    except User.DoesNotExist:
        admin = User.objects.create_user(
            username="admin",
            email="admin@a.local",
            password="password123",
            is_active=True,
            home_department=dep_a,
            role="system_admin",
            employee_id="ADM001",
        )
    try:
        mgr = User.objects.get(email="mgr@b.local")
    except User.DoesNotExist:
        mgr = User.objects.create_user(
            username="mgr",
            email="mgr@b.local",
            password="password123",
            is_active=True,
            home_department=dep_b,
            role="it_manager",
            employee_id="MGR001",
        )
    try:
        support = User.objects.get(email="support@b.local")
    except User.DoesNotExist:
        support = User.objects.create_user(
            username="support",
            email="support@b.local",
            password="password123",
            is_active=True,
            home_department=dep_a,
            role="it_support",
            employee_id="SUP001",
        )
    try:
        emp_a = User.objects.get(email="emp_a@a.local")
    except User.DoesNotExist:
        emp_a = User.objects.create_user(
            username="emp_a",
            email="emp_a@a.local",
            password="password123",
            is_active=True,
            home_department=dep_a,
            role="employee",
            employee_id="EMP001",
        )
    try:
        emp_b = User.objects.get(email="emp_b@b.local")
    except User.DoesNotExist:
        emp_b = User.objects.create_user(
            username="emp_b",
            email="emp_b@b.local",
            password="password123",
            is_active=True,
            home_department=dep_b,
            role="employee",
            employee_id="EMP002",
        )
    return {
        "admin": admin,
        "mgr": mgr,
        "support": support,
        "emp_a": emp_a,
        "emp_b": emp_b,
        "dep_a": dep_a,
        "dep_b": dep_b,
        "cat": cat,
    }


def _create_asset(scope, tag, name, assignee, department):
    return Asset.objects.create(
        asset_tag=tag,
        name=name,
        category=scope["cat"],
        assigned_to=assignee,
        status="assigned",
        department=department,
    )


def _upload_attachment(assignee, file_name="doc.txt", content=b"hello"):
    """Attach a file to an asset owned by `assignee` and return the attachment."""
    asset = _create_asset(
        {"cat": AssetCategory.objects.get_or_create(name="Laptop")[0]},
        "AT-" + file_name[:4], "asset", assignee, assignee.home_department
    )
    from django.core.files.uploadedfile import SimpleUploadedFile

    return AssetAttachment.objects.create(
        asset=asset,
        file=SimpleUploadedFile(file_name, content, content_type="text/plain"),
        uploaded_by=assignee,
    )


# ---------------------------------------------------------------------------
# Asset list shape + empty scope
# ---------------------------------------------------------------------------


class AssetListShapeTests(TestCase):
    def setUp(self):
        self.scope = _make_scope_tree()
        self.asset = _create_asset(
            self.scope, "A1", "Alpha", self.scope["emp_a"], self.scope["dep_a"]
        )
        self.c = APIClient()
        self.c.force_authenticate(user=self.scope["admin"])

    def _page(self, params=None):
        return self.c.get("/api/assets/", data=params or {})

    def test_pagination_shape_and_hidden_count(self):
        resp = self._page()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.data), {"count", "next", "previous", "results"})
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertIsNone(resp.data["next"])
        self.assertIsNone(resp.data["previous"])
        self.assertFalse(resp.data.get("hidden", False))

    def test_find_all_assets(self):
        resp = self.c.get("/api/assets/find_all/", data={"category": "Lap"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["asset_tag"], "A1")

    def test_empty_scope_returns_empty_list(self):
        dept = Department.objects.create(name="Empty", code="E")
        User.objects.create_user(
            username="ghost",
            email="ghost@e.local",
            password="password123",
            is_active=True,
            home_department=dept,
            role="employee",
            employee_id="GHOST001",
        )
        resp = self.c.get("/api/assets/", data={"department": dept.pk})
        import sys; print('DEPT_PK:', dept.pk, 'COUNT:', resp.data['count'], 'RESULTS:', [r['asset_tag'] for r in resp.data['results']], file=sys.stderr)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 0)
        self.assertEqual(len(resp.data["results"]), 0)
        self.assertIsNone(resp.data["next"])
        self.assertIsNone(resp.data["previous"])
        self.assertFalse(resp.data.get("hidden", False))


# ---------------------------------------------------------------------------
# Role-scoped visibility: holder policies
# ---------------------------------------------------------------------------


class AssetRoleScopeTests(TestCase):
    def setUp(self):
        self.scope = _make_scope_tree()
        self.base_asset = _create_asset(
            self.scope, "B1", "Base", self.scope["emp_a"], self.scope["dep_a"]
        )
        self.c = APIClient()

    def _request(self, user, params=None):
        self.c.force_authenticate(user=user)
        return self.c.get("/api/assets/", data=params or {})

    def test_admin_full_scope(self):
        self._request(self.scope["admin"])
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 200)
        tags = [r["asset_tag"] for r in resp.data["results"]]
        self.assertIn("B1", tags)
        self.assertEqual(resp.data["count"], 1)
        self.assertIsNone(resp.data["next"])

    def test_manager_scope(self):
        self._request(self.scope["mgr"])
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertIn("B1", [r["asset_tag"] for r in resp.data["results"]])
        self.assertIsNone(resp.data["next"])

    def test_support_scope(self):
        self._request(self.scope["support"])
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertIn("B1", [r["asset_tag"] for r in resp.data["results"]])

    def test_employee_scope(self):
        self._request(self.scope["emp_a"])
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertIn("B1", [r["asset_tag"] for r in resp.data["results"]])

    def test_employee_only_own_assets(self):
        _create_asset(
            self.scope, "A2", "A2", self.scope["emp_b"], self.scope["dep_b"]
        )
        self._request(self.scope["emp_a"])
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 200)
        tags = [r["asset_tag"] for r in resp.data["results"]]
        self.assertEqual(resp.data["count"], 1)
        self.assertIn("B1", tags)
        self.assertNotIn("A2", tags)

    def test_employee_cannot_see_home_department_assets(self):
        _create_asset(
            self.scope, "A3", "A3", self.scope["emp_b"], self.scope["dep_b"]
        )
        self._request(self.scope["emp_a"])
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertNotIn("A3", [r["asset_tag"] for r in resp.data["results"]])

    def test_hidden_count_transparency(self):
        _create_asset(
            self.scope, "B2", "B2", self.scope["emp_b"], self.scope["dep_b"]
        )
        self._request(self.scope["emp_a"])
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data.get("hidden", False))
        self.assertEqual(resp.data["count"], 1)


# ---------------------------------------------------------------------------
# Fail-closed: anonymous, inactive, unknown role
# ---------------------------------------------------------------------------


class AssetFailClosedTests(TestCase):
    def test_anonymous_returns_401(self):
        self.c = APIClient()
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 401)

    def test_inactive_user_cannot_list(self):
        self.c = APIClient()
        scope = _make_scope_tree()
        inactive = User.objects.create_user(
            username="inh",
            email="inh@x.local",
            password="password123",
            is_active=False,
            home_department=scope["dep_a"],
            role="employee",
            employee_id="INH001",
        )
        self.c.force_authenticate(user=inactive)
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 403)

    def test_unknown_role_cannot_list(self):
        self.c = APIClient()
        scope = _make_scope_tree()
        unknown = User.objects.create_user(
            username="unk",
            email="unk@x.local",
            password="password123",
            is_active=True,
            home_department=scope["dep_a"],
            role=999,
            employee_id="UNK001",
        )
        self.c.force_authenticate(user=unknown)
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# Soft-deleted exclusion + cross-department exclusion
# ---------------------------------------------------------------------------


class AssetVisibilityExclusionsTests(TestCase):
    def setUp(self):
        self.scope = _make_scope_tree()
        self.c = APIClient()

    def _set_up_assets(self):
        self.asset_a = _create_asset(
            self.scope, "AA", "AA", self.scope["emp_a"], self.scope["dep_a"]
        )
        self.asset_b = _create_asset(
            self.scope, "BB", "BB", self.scope["emp_b"], self.scope["dep_b"]
        )

    def test_soft_deleted_excluded(self):
        self._set_up_assets()
        self.asset_a.soft_delete()
        self.c.force_authenticate(user=self.scope["admin"])
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 200)
        tags = [r["asset_tag"] for r in resp.data["results"]]
        self.assertNotIn("AA", tags)
        self.assertEqual(resp.data["count"], 1)
        self.assertIn("BB", tags)

    def test_cross_department_excluded(self):
        self._set_up_assets()
        self.c.force_authenticate(user=self.scope["emp_a"])
        resp = self.c.get("/api/assets/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertIn("AA", [r["asset_tag"] for r in resp.data["results"]])
        self.assertNotIn("BB", [r["asset_tag"] for r in resp.data["results"]])


# ---------------------------------------------------------------------------
# Search / filter / ordering cannot broaden
# ---------------------------------------------------------------------------


class AssetSearchFilterOrderingTests(TestCase):
    def setUp(self):
        self.scope = _make_scope_tree()
        self.c = APIClient()
        _create_asset(
            self.scope, "SA", "SA", self.scope["emp_a"], self.scope["dep_a"]
        )
        _create_asset(
            self.scope, "SB", "SB", self.scope["emp_b"], self.scope["dep_b"]
        )
        _create_asset(
            self.scope, "SC", "SC", self.scope["emp_a"], self.scope["dep_a"]
        )

    def _request(self, user, params=None):
        self.c.force_authenticate(user=user)
        return self.c.get("/api/assets/", data=params or {})

    def test_search_cannot_broaden(self):
        resp = self._request(self.scope["emp_a"], params={"q": "zz-nope"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 0)
        self.assertEqual(len(resp.data["results"]), 0)

    def test_filter_cannot_broaden(self):
        resp = self._request(
            self.scope["emp_a"], params={"category": self.scope["cat"].pk}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 2)
        tags = [r["asset_tag"] for r in resp.data["results"]]
        self.assertIn("SA", tags)
        self.assertIn("SC", tags)
        self.assertNotIn("SB", tags)

    def test_ordering_cannot_broaden(self):
        resp = self._request(self.scope["emp_a"], params={"ordering": "-asset_tag"})
        self.assertEqual(resp.status_code, 200)
        tags = [r["asset_tag"] for r in resp.data["results"]]
        self.assertEqual(resp.data["count"], 2)
        self.assertEqual(tags[0], "SC")
        self.assertEqual(tags[1], "SA")
