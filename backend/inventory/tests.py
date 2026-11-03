from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from assets.models import Vendor
from .models import StockItem

User = get_user_model()


class InventoryTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="pass", role="system_admin", employee_id="ADM1", email="a@x.com")
        self.emp = User.objects.create_user(username="emp", password="pass", role="employee", employee_id="EMP1", email="e@x.com")
        self.item = StockItem.objects.create(name="Mouse", sku="M1", quantity=10, reorder_threshold=2, unit_cost=5)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_create_item(self):
        r = self.client.post("/api/inventory/stock-items/", {"name": "Kb", "sku": "K1", "quantity": 0, "reorder_threshold": 1})
        self.assertEqual(r.status_code, 201)

    def test_receive(self):
        r = self.client.post(f"/api/inventory/stock-items/{self.item.id}/receive/", {"quantity": 5})
        self.assertEqual(r.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 15)

    def test_issue(self):
        r = self.client.post(f"/api/inventory/stock-items/{self.item.id}/issue/", {"quantity": 3, "employee": self.emp.id})
        self.assertEqual(r.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 7)

    def test_issue_insufficient(self):
        r = self.client.post(f"/api/inventory/stock-items/{self.item.id}/issue/", {"quantity": 100})
        self.assertEqual(r.status_code, 400)

    def test_adjust_negative_prevented(self):
        r = self.client.post(f"/api/inventory/stock-items/{self.item.id}/adjust/", {"quantity": -100, "reason": "x"})
        self.assertEqual(r.status_code, 400)

    def test_employee_cannot_create(self):
        c = APIClient(); c.force_authenticate(self.emp)
        r = c.post("/api/inventory/stock-items/", {"name": "X", "sku": "X1", "quantity": 0})
        self.assertIn(r.status_code, (403, 401))

    def test_movement_history(self):
        self.client.post(f"/api/inventory/stock-items/{self.item.id}/receive/", {"quantity": 2})
        r = self.client.get(f"/api/inventory/stock-items/{self.item.id}/movements/" if False else "/api/inventory/stock-items/movements/?stock_item=" + str(self.item.id))
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.data), 1)
