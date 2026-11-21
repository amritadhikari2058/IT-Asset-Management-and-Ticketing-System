from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Department, User
from assets.models import Asset, AssetCategory
from lifecycle import models as lm


def make_user(email, employee_id, role="employee", home_department=None):
    return User.objects.create_user(
        username=email, email=email, employee_id=employee_id,
        password="pw12345678", role=role, home_department=home_department)


class LifecycleHardeningTests(TestCase):
    def setUp(self):
        self.dep = Department.objects.create(name="IT", code="IT")
        self.admin = make_user("admin@x", "A1", "system_admin", self.dep)
        self.emp = make_user("emp@x", "E1", "employee", self.dep)
        self.emp2 = make_user("emp2@x", "E2", "employee", self.dep)
        self.case = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00001", case_type="onboarding",
            employee=self.emp, status="in_progress")
        self.case2 = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00002", case_type="onboarding",
            employee=self.emp2, status="in_progress")
        task = lm.LifecycleTask.objects.create(
            case=self.case2, sequence=1, title="Failing",
            automation_type="notification",
            automation_status="failed")
        cat = AssetCategory.objects.create(name="Laptop")
        self.asset = Asset.objects.create(
            asset_tag="A1", name="Laptop", category=cat, status="assigned",
            assigned_to=self.emp2, serial_number="SN-A1")
        self.res = lm.LifecycleAssetResolution.objects.create(
            case=self.case2, asset=self.asset, status="pending",
            resolution="pending")

    def test_employee_dashboard_does_not_include_other_user_failed_automation(self):
        c = APIClient()
        c.force_authenticate(user=self.emp)
        resp = c.get(reverse("lifecycle-dashboard"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["failed_automations"], 0)
        self.assertEqual(resp.data["overdue_tasks"], 0)

    def test_duplicate_asset_resolution_is_rejected(self):
        from django.core.exceptions import ValidationError
        from lifecycle import services
        services._resolve_asset(self.case2, self.asset, "returned",
                               self.admin)
        with self.assertRaises(ValidationError):
            services._resolve_asset(self.case2, self.asset, "returned",
                                   self.admin)

    def test_manual_review_automation_does_not_become_succeeded(self):
        c = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00003", case_type="onboarding",
            employee=self.emp, status="draft")
        t = lm.LifecycleTask.objects.create(
            case=c, sequence=1, title="T",
            automation_type="create_ticket")
        from lifecycle.services import _run_task_automation
        _run_task_automation(t, self.admin)
        t.refresh_from_db()
        self.assertEqual(t.automation_status, "manual_review")
