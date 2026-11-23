from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase


class QualityGateHealthIntegrationTests(APITestCase):
    def test_liveness_and_readiness_endpoints_report_real_database_state(self):
        liveness = self.client.get("/health/")
        self.assertEqual(liveness.status_code, 200)
        self.assertEqual(liveness.json(), {"status": "ok"})

        readiness = self.client.get("/ready/")
        self.assertEqual(readiness.status_code, 200)
        self.assertEqual(
            readiness.json(),
            {"status": "ready", "database": "ok"},
        )

    def test_login_issues_access_and_refresh_tokens(self):
        user = get_user_model().objects.create_user(
            username="quality.employee",
            email="quality.employee@example.com",
            password="quality-test-password",
            role="employee",
        )

        response = self.client.post(
            "/api/token/",
            {
                "email": "quality.employee@example.com",
                "password": "quality-test-password",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertIn("refresh", response.json())
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
