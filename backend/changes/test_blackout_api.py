from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Department, User
from changes.models import BlackoutPeriod


def _token(user):
    from rest_framework_simplejwt.tokens import RefreshToken
    return str(RefreshToken.for_user(user).access_token)


class BlackoutPeriodApiTests(TestCase):
    def setUp(self):
        self.dep = Department.objects.create(name="Eng", code="ENGX")
        self.admin = User.objects.create_user(
            username="a@x", email="a@x", employee_id="A1",
            password="pw12345678", role="system_admin", home_department=self.dep,
        )
        self.emp = User.objects.create_user(
            username="e@x", email="e@x", employee_id="E1",
            password="pw12345678", role="employee", home_department=self.dep,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(self.admin)}")

    def test_list_blackout_periods(self):
        BlackoutPeriod.objects.create(
            code="B1", name="Freeze", period_type="freeze",
            start_at=timezone.now(), end_at=timezone.now() + timezone.timedelta(hours=1),
            created_by=self.admin,
        )
        res = self.client.get("/api/blackout-periods/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data.get("results", res.data)), 1)

    def test_create_requires_manager(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(self.emp)}")
        res = self.client.post("/api/blackout-periods/", {
            "code": "B2", "name": "Freeze2", "period_type": "freeze",
            "start_at": timezone.now().isoformat(),
            "end_at": (timezone.now() + timezone.timedelta(hours=1)).isoformat(),
        }, format="json")
        self.assertEqual(res.status_code, 403)

    def test_create_and_toggle_status(self):
        res = self.client.post("/api/blackout-periods/", {
            "code": "B3", "name": "Freeze3", "period_type": "freeze",
            "start_at": timezone.now().isoformat(),
            "end_at": (timezone.now() + timezone.timedelta(hours=1)).isoformat(),
        }, format="json")
        self.assertEqual(res.status_code, 201)
        bp_id = res.data["id"]
        res2 = self.client.patch(f"/api/blackout-periods/{bp_id}/", {"status": "inactive"}, format="json")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data["status"], "inactive")

    def test_validation_end_after_start(self):
        res = self.client.post("/api/blackout-periods/", {
            "code": "B4", "name": "Bad", "period_type": "freeze",
            "start_at": (timezone.now() + timezone.timedelta(hours=1)).isoformat(),
            "end_at": timezone.now().isoformat(),
        }, format="json")
        self.assertEqual(res.status_code, 400)
