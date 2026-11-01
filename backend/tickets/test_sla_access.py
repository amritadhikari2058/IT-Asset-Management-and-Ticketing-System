"""SLA report is IT-staff only; SLA target config is System-Admin only."""
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.tests import auth, make_users


class SLAReportAccessTests(TestCase):
    def setUp(self):
        self.dep, self.admin, self.mgr, self.emp = make_users()
        self.c = APIClient()

    def test_employee_cannot_view_sla_report(self):
        auth(self.c, self.emp)
        self.assertEqual(
            self.c.get("/api/tickets/reports/sla/").status_code, 403)

    def test_it_staff_can_view_sla_report(self):
        auth(self.c, self.mgr)
        self.assertEqual(
            self.c.get("/api/tickets/reports/sla/").status_code, 200)

    def test_only_admin_can_change_sla_targets(self):
        auth(self.c, self.mgr)
        self.assertEqual(self.c.get("/api/tickets/sla/").status_code, 403)
        auth(self.c, self.admin)
        self.assertEqual(self.c.get("/api/tickets/sla/").status_code, 200)
