from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Department, User
from lifecycle import models as lm


def make_user(email, employee_id, role="employee", home_department=None):
    return User.objects.create_user(
        username=email, email=email, employee_id=employee_id,
        password="pw12345678", role=role, home_department=home_department)


class LifecycleSecurityTests(TestCase):
    def setUp(self):
        self.dep = Department.objects.create(name="IT", code="IT")
        self.admin = make_user("admin@x", "A1", "system_admin", self.dep)
        self.emp = make_user("emp@x", "E1", "employee", self.dep)
        self.emp2 = make_user("emp2@x", "E2", "employee", self.dep)
        self.case = lm.LifecycleCase.objects.create(
            case_number="ONB-2026-00001", case_type="onboarding",
            employee=self.emp, status="draft")
        self.task = lm.LifecycleTask.objects.create(
            case=self.case, sequence=1, title="T", assigned_to=self.emp)

    def test_unauthenticated_case_list_denied(self):
        c = APIClient()
        resp = c.get(reverse("lifecycle-case-list"))
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED,
                                         status.HTTP_403_FORBIDDEN))

    def test_employee_cannot_see_other_case(self):
        c = APIClient()
        c.force_authenticate(user=self.emp2)
        resp = c.get(reverse("lifecycle-case-detail", args=[self.case.pk]))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_employee_cannot_update_other_task(self):
        c = APIClient()
        c.force_authenticate(user=self.emp2)
        resp = c.patch(reverse("lifecycle-task-detail", args=[self.task.pk]),
                       {"status": "completed"}, format="json")
        self.assertIn(resp.status_code, (status.HTTP_403_FORBIDDEN,
                                         status.HTTP_404_NOT_FOUND))

    def test_from_service_request_requires_staff(self):
        c = APIClient()
        c.force_authenticate(user=self.emp)
        resp = c.post(reverse("lifecycle-case-from-service-request"))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
