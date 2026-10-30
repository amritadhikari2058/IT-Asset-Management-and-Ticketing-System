p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\tests.py"
src = open(p, encoding="utf-8").read()

addition = '''


class DataIntegrityReportTests(TestCase):
    """READ-ONLY data-integrity report: identifies inconsistent records."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_employee_forbidden(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 403)

    def test_manager_forbidden(self):
        auth(self.c, self.mgr)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 403)

    def test_admin_reports_holder_without_open_assignment(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="LT-9", name="n", category=cat,
                             status="assigned", assigned_to=self.emp)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 200)
        codes = [i["code"] for i in res.data["issues"]]
        self.assertIn("holder_without_open_assignment", codes)

    def test_clean_state_has_no_issues(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="LT-8", name="n", category=cat)
        auth(self.c, self.admin)
        res = self.c.get("/api/common/data-integrity/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["issues"], [])


class ExportDatasetTests(TestCase):
    """Read-only multi-format exports (CSV / XLSX / PDF / DOCX)."""

    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()
        auth(self.c, self.mgr)

    def test_employees_csv(self):
        res = self.c.get("/api/exports/employees/?format=csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn("employees_", res["Content-Disposition"])
        self.assertTrue(res.content)

    def test_assets_xlsx(self):
        from assets.models import Asset, AssetCategory
        cat = AssetCategory.objects.create(name="Laptops")
        Asset.objects.create(asset_tag="A1", name="n", category=cat)
        res = self.c.get("/api/exports/assets/?format=xlsx")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet", res["Content-Type"])

    def test_tickets_pdf(self):
        res = self.c.get("/api/exports/tickets/?format=pdf")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/pdf", res["Content-Type"])

    def test_departments_docx(self):
        res = self.c.get("/api/exports/departments/?format=docx")
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document", res["Content-Type"])

    def test_unknown_dataset_404(self):
        res = self.c.get("/api/exports/nope/?format=csv")
        self.assertEqual(res.status_code, 404)

    def test_bad_format_400(self):
        res = self.c.get("/api/exports/assets/?format=exe")
        self.assertEqual(res.status_code, 400)

    def test_employee_forbidden_on_employees_export(self):
        auth(self.c, self.emp)
        res = self.c.get("/api/exports/employees/?format=csv")
        self.assertEqual(res.status_code, 403)

    def test_selected_scope_returns_only_requested_rows(self):
        from accounts.models import User
        extra = User.objects.create_user(
            username="e9@x", email="e9@example.com", employee_id="E9",
            password="pw12345678", home_department=self.dep)
        res = self.c.get(
            f"/api/exports/employees/?format=csv&scope=selected&ids={extra.pk},{self.emp.pk}")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode("utf-8")
        self.assertIn("e9@example.com", blob)
        self.assertIn("E9", blob)

    def test_export_writes_audit_log(self):
        from common.models import AuditLog
        before = AuditLog.objects.filter(action="export").count()
        res = self.c.get("/api/exports/tickets/?format=csv")
        self.assertEqual(res.status_code, 200)
        after = AuditLog.objects.filter(action="export").count()
        self.assertEqual(after, before + 1)
'''

src = src.rstrip("\n") + "\n" + addition
open(p, "w", encoding="utf-8").write(src)
print("common/tests appended")
