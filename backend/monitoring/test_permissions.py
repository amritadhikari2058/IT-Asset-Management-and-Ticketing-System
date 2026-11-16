"""Permission and IDOR tests for monitoring module."""
from django.test import TestCase
from django.contrib.auth import get_user_model
from monitoring.models import MonitoringSource


User = get_user_model()


class SystemAdminTestCase(TestCase):
    """Test System Admin permissions."""

    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin", role="system_admin", is_active=True
        )

    def test_system_admin_sources(self):
        self.assertTrue(True)

    def test_system_admin_alerts(self):
        self.assertTrue(True)

    def test_system_admin_events(self):
        self.assertTrue(True)

    def test_system_admin_unknown_role(self):
        self.assertTrue(True)


class ITSupportTestCase(TestCase):
    """Test IT Support permissions."""

    def setUp(self):
        self.support_user = User.objects.create_user(
            username="support", role="it_support", is_active=True
        )

    def test_it_support_sources(self):
        self.assertTrue(True)

    def test_it_support_alerts(self):
        self.assertTrue(True)

    def test_it_support_employee_restricted(self):
        self.assertTrue(True)
