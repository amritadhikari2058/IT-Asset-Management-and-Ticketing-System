"""Regression tests for the Procurement P2.1 extensions.

Covers the aggregate dashboard, server-side filtering/ordering, protected
attachments, Purchase Order PDF, request/order cancellation and closure,
structured receipt discrepancies, accepted-only inventory posting, and
receipt-to-asset traceability.
"""
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Department, User
from assets.models import Asset, AssetCategory, Vendor
from common.models import Notification
from inventory.models import StockItem, StockMovement

from .models import (
    GoodsReceipt, GoodsReceiptItem, ProcurementAssetReceiptItem,
    ProcurementAttachment, ProcurementHistory, PurchaseOrder,
    PurchaseOrderItem, PurchaseQuotation, PurchaseRequest, PurchaseRequestItem,
    ProcurementSetting,
)

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def make_user(email, role, employee_id):
    return User.objects.create_user(
        username=employee_id, email=email, password="test-pass-123",
        role=role, employee_id=employee_id,
    )


@override_settings(PASSWORD_HASHERS=PASSWORD_HASHERS)
class ProcurementP21Base(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="IT", code="IT")
        self.vendor = Vendor.objects.create(
            name="Acme Supplies", code="ACME", address="1 Market St",
            email="sales@acme.test", phone="555-0100")
        self.admin = make_user("admin@example.test", "system_admin", "T-ADM")
        self.manager = make_user("manager@example.test", "it_manager", "T-MGR")
        self.support = make_user("support@example.test", "it_support", "T-SUP")
        self.employee = make_user("employee@example.test", "employee", "T-EMP")
        for user in (self.support, self.manager, self.admin):
            user.home_department = self.department
            user.save(update_fields=["home_department"])
        ProcurementSetting.objects.update_or_create(
            pk=1,
            defaults={
                "approval_threshold": Decimal("1000.00"),
                "organization_name": "Example Org",
                "delivery_address": "HQ Loading Bay",
                "po_terms": "Net 30",
                "authorized_signatory_name": "A. Signatory",
                "authorized_signatory_title": "IT Manager",
            },
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    # ---- fixtures ----

    def make_request(self, user=None, status="draft", total="500.00"):
        pr = PurchaseRequest.objects.create(
            requester=user or self.support, department=self.department,
            reason="Need laptops for new hires", status=status,
            estimated_total=Decimal(total),
        )
        PurchaseRequestItem.objects.create(
            purchase_request=pr, item_name="Laptop", quantity=2,
            estimated_unit_price=Decimal("250.00"),
            estimated_total=Decimal("500.00"),
        )
        return pr

    def make_order(self, status="sent_to_vendor", currency="NPR",
                   quantity=2, unit_price="250.00", serialized=False,
                   stock_item=None, category=None):
        pr = self.make_request(status="po_generated")
        po = PurchaseOrder.objects.create(
            purchase_request=pr, vendor=self.vendor, created_by=self.manager,
            status=status, currency=currency,
            delivery_address="HQ Loading Bay", terms="Net 30",
            expected_delivery_date=None,
        )
        line = PurchaseOrderItem.objects.create(
            purchase_order=po, item_name="Laptop", quantity=quantity,
            unit_price=Decimal(unit_price), is_serialized=serialized,
            stock_item=stock_item, asset_category=category,
        )
        po.subtotal = Decimal(quantity) * Decimal(unit_price)
        po.save()
        return po, line

    def make_receipt(self, po, line, received, rejected=0, damaged=0):
        receipt = GoodsReceipt.objects.create(
            purchase_order=po, received_by=self.support)
        response = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": received,
                "quantity_rejected": rejected,
                "quantity_damaged": damaged,
            },
            format="json",
        )
        receipt.refresh_from_db()
        return receipt, response


class DashboardTests(ProcurementP21Base):
    def test_counts_and_role_scope(self):
        self.make_request(status="draft")
        self.make_request(status="pending_approval")
        self.make_request(status="approved")
        response = self.client_for(self.manager).get(
            "/api/procurement/dashboard/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["purchase_requests"]["draft"], 1)
        self.assertEqual(
            response.data["purchase_requests"]["pending_manager_approval"], 1)
        self.assertEqual(response.data["purchase_requests"]["approved"], 1)

    def test_employee_is_denied(self):
        response = self.client_for(self.employee).get(
            "/api/procurement/dashboard/")
        self.assertEqual(response.status_code, 403)

    def test_it_support_receives_scoped_counts(self):
        self.make_request(user=self.support, status="draft")
        self.make_request(user=self.manager, status="draft")
        response = self.client_for(self.support).get(
            "/api/procurement/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["purchase_requests"]["draft"], 1)

    def test_currency_totals_are_never_combined(self):
        self.make_order(currency="NPR", quantity=2, unit_price="100.00")
        self.make_order(currency="USD", quantity=1, unit_price="50.00")
        response = self.client_for(self.manager).get(
            "/api/procurement/dashboard/")
        rows = {row["currency"]: row
                for row in response.data["values_by_currency"]}
        self.assertEqual(set(rows), {"NPR", "USD"})
        self.assertEqual(rows["NPR"]["ordered_total"], "200.00")
        self.assertEqual(rows["USD"]["ordered_total"], "50.00")

    def test_zero_values_and_bounded_recent_lists(self):
        for _ in range(14):
            self.make_request()
        response = self.client_for(self.manager).get(
            "/api/procurement/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["purchase_orders"]["closed"], 0)
        self.assertLessEqual(len(response.data["recent_purchase_requests"]), 10)

    def test_date_filters(self):
        # Future-only window excludes everything seeded now.
        response = self.client_for(self.manager).get(
            "/api/procurement/dashboard/?date_from=2999-01-01")
        self.assertEqual(response.data["purchase_requests"]["draft"], 0)

    def test_department_filter(self):
        other = Department.objects.create(name="Finance", code="FIN")
        PurchaseRequest.objects.create(
            requester=self.support, department=other, reason="x",
            estimated_total=Decimal("10.00"))
        response = self.client_for(self.manager).get(
            f"/api/procurement/dashboard/?department={self.department.pk}")
        self.assertEqual(response.data["purchase_requests"]["draft"], 0)


class FilteringTests(ProcurementP21Base):
    def test_purchase_request_search_status_and_role_scope(self):
        own = self.make_request(status="draft")
        other = self.make_request(user=self.manager, status="approved")
        response = self.client_for(self.support).get(
            "/api/procurement/purchase-requests/?search=laptops")
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(own.pk, ids)
        self.assertNotIn(other.pk, ids)

        response = self.client_for(self.manager).get(
            "/api/procurement/purchase-requests/?status=approved")
        self.assertEqual({row["id"] for row in response.data["results"]},
                         {other.pk})

    def test_ordering_is_allowlisted(self):
        first = self.make_request(total="100.00")
        second = self.make_request(total="900.00")
        response = self.client_for(self.manager).get(
            "/api/procurement/purchase-requests/?ordering=estimated_total")
        self.assertEqual([row["id"] for row in response.data["results"]],
                         [first.pk, second.pk])

        # An injected / unknown ordering is ignored, not applied.
        response = self.client_for(self.manager).get(
            "/api/procurement/purchase-requests/?ordering=requester__password")
        self.assertEqual(response.status_code, 200)

    def test_pagination(self):
        for _ in range(25):
            self.make_request()
        response = self.client_for(self.manager).get(
            "/api/procurement/purchase-requests/?page_size=10")
        self.assertEqual(len(response.data["results"]), 10)
        self.assertIsNotNone(response.data["next"])

    def test_purchase_order_filters_and_search(self):
        npr, _ = self.make_order(currency="NPR")
        usd, _ = self.make_order(currency="USD")
        response = self.client_for(self.manager).get(
            "/api/procurement/purchase-orders/?vendor="
            f"{self.vendor.pk}&status=sent_to_vendor")
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {npr.pk, usd.pk})
        response = self.client_for(self.manager).get(
            f"/api/procurement/purchase-orders/?search={npr.po_number}")
        self.assertEqual({row["id"] for row in response.data["results"]},
                         {npr.pk})

    def test_goods_receipt_filters(self):
        po, line = self.make_order()
        receipt, _ = self.make_receipt(po, line, received=1, rejected=1)
        response = self.client_for(self.manager).get(
            "/api/procurement/goods-receipts/?discrepancy=yes")
        self.assertEqual({row["id"] for row in response.data["results"]},
                         {receipt.pk})
        response = self.client_for(self.manager).get(
            "/api/procurement/goods-receipts/?search=GR-")
        self.assertGreaterEqual(len(response.data["results"]), 1)


class AttachmentTests(ProcurementP21Base):
    def upload(self, pr, user=None, name="spec.pdf", content=b"%PDF-1.4 test"):
        upload = SimpleUploadedFile(name, content, content_type="application/pdf")
        return self.client_for(user or self.support).post(
            "/api/procurement/attachments/",
            {"purchase_request": pr.pk, "document_type": "specification",
             "description": "spec", "file": upload},
            format="multipart",
        )

    def test_upload_and_protected_download(self):
        pr = self.make_request()
        response = self.upload(pr)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data["checksum"]), 64)
        self.assertEqual(response.data["original_filename"], "spec.pdf")

        attachment = ProcurementAttachment.objects.get(pk=response.data["id"])
        download = self.client_for(self.support).get(
            f"/api/procurement/attachments/{attachment.pk}/download/")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment; filename=", download["Content-Disposition"])

    def test_executable_upload_is_rejected(self):
        pr = self.make_request()
        response = self.upload(pr, name="payload.exe", content=b"MZ")
        self.assertEqual(response.status_code, 400)

    def test_oversized_upload_is_rejected(self):
        pr = self.make_request()
        with override_settings(ATTACHMENT_MAX_SIZE_MB=0.0001):
            response = self.upload(pr, content=b"x" * 2048)
        self.assertEqual(response.status_code, 400)

    def test_cross_parent_access_is_denied(self):
        pr = self.make_request()
        created = self.upload(pr).data
        other_support = make_user("other@example.test", "it_support", "T-OTH")
        response = self.client_for(other_support).get(
            f"/api/procurement/attachments/{created['id']}/download/")
        self.assertEqual(response.status_code, 404)

    def test_employee_cannot_upload(self):
        pr = self.make_request()
        response = self.upload(pr, user=self.employee)
        self.assertEqual(response.status_code, 403)

    def test_archived_attachment_cannot_download(self):
        pr = self.make_request()
        created = self.upload(pr).data
        self.client_for(self.support).post(
            f"/api/procurement/attachments/{created['id']}/archive/")
        response = self.client_for(self.support).get(
            f"/api/procurement/attachments/{created['id']}/download/")
        self.assertEqual(response.status_code, 404)


class PurchaseOrderPDFTests(ProcurementP21Base):
    def test_pdf_content_type_filename_and_no_internal_notes(self):
        po, _ = self.make_order()
        po.notes = "INTERNAL SECRET NOTE"
        po.approval_reason = "INTERNAL REJECT REASON"
        po.save()
        response = self.client_for(self.manager).get(
            f"/api/procurement/purchase-orders/{po.pk}/pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(f'filename="{po.po_number}.pdf"',
                      response["Content-Disposition"])
        body = b"".join(response.streaming_content)
        self.assertIn(b"Grand total", body)
        self.assertNotIn(b"INTERNAL SECRET NOTE", body)
        self.assertNotIn(b"INTERNAL REJECT REASON", body)

    def test_employee_is_denied_and_missing_is_404(self):
        po, _ = self.make_order()
        self.assertIn(self.client_for(self.employee).get(
            f"/api/procurement/purchase-orders/{po.pk}/pdf/").status_code,
            (403, 404))
        self.assertEqual(self.client_for(self.manager).get(
            "/api/procurement/purchase-orders/99999/pdf/").status_code, 404)


class PurchaseRequestCancellationTests(ProcurementP21Base):
    def test_owner_cancels_with_reason_history_and_notification(self):
        pr = self.make_request()
        response = self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/cancel/",
            {"reason": "No longer needed", "version": pr.version},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "cancelled")
        pr.refresh_from_db()
        self.assertEqual(pr.cancellation_reason, "No longer needed")
        self.assertTrue(ProcurementHistory.objects.filter(
            purchase_request=pr, action="cancelled").exists())
        self.assertTrue(Notification.objects.filter(
            recipient=self.support).exists())

    def test_manager_can_cancel_someone_elses_request(self):
        pr = self.make_request()
        response = self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/cancel/",
            {"reason": "Budget cut"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_reason_is_required(self):
        pr = self.make_request()
        response = self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/cancel/",
            {}, format="json")
        self.assertEqual(response.status_code, 400)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "draft")

    def test_cannot_cancel_after_purchase_order(self):
        po, _ = self.make_order()
        pr = po.purchase_request
        response = self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/cancel/",
            {"reason": "too late"}, format="json")
        self.assertEqual(response.status_code, 400)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "po_generated")

    def test_stale_version_returns_409(self):
        pr = self.make_request()
        response = self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/cancel/",
            {"reason": "x", "version": pr.version + 5}, format="json")
        self.assertEqual(response.status_code, 409)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "draft")

    def test_unrelated_employee_cannot_cancel(self):
        pr = self.make_request()
        response = self.client_for(self.employee).post(
            f"/api/procurement/purchase-requests/{pr.pk}/cancel/",
            {"reason": "x"}, format="json")
        self.assertIn(response.status_code, (403, 404))


class PurchaseOrderCancellationAndClosureTests(ProcurementP21Base):
    def test_cancel_unreceived_order(self):
        po, _ = self.make_order(status="approved")
        response = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{po.pk}/cancel/",
            {"reason": "Vendor withdrawn", "version": po.version},
            format="json")
        self.assertEqual(response.status_code, 200, response.data)
        po.refresh_from_db()
        self.assertEqual(po.status, "cancelled")
        self.assertEqual(po.cancellation_reason, "Vendor withdrawn")

    def test_cancel_after_receipt_activity_is_blocked(self):
        po, line = self.make_order()
        self.make_receipt(po, line, received=1)
        response = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{po.pk}/cancel/",
            {"reason": "stop"}, format="json")
        self.assertEqual(response.status_code, 400)
        po.refresh_from_db()
        self.assertNotEqual(po.status, "cancelled")

    def test_close_fully_received(self):
        po, line = self.make_order(quantity=2)
        self.make_receipt(po, line, received=2)
        response = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{po.pk}/close/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        po.refresh_from_db()
        self.assertEqual(po.status, "closed")
        self.assertIsNotNone(po.closed_at)

    def test_short_close_requires_reason(self):
        po, line = self.make_order(quantity=4)
        self.make_receipt(po, line, received=1)
        missing = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{po.pk}/close/", {}, format="json")
        self.assertEqual(missing.status_code, 400)
        response = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{po.pk}/close/",
            {"reason": "Vendor cannot supply remainder"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        line.refresh_from_db()
        self.assertEqual(line.received_qty, 1)
        self.assertEqual(line.quantity, 4)

    def test_short_close_is_manager_only(self):
        po, line = self.make_order(quantity=4)
        self.make_receipt(po, line, received=1)
        response = self.client_for(self.support).post(
            f"/api/procurement/purchase-orders/{po.pk}/close/",
            {"reason": "x"}, format="json")
        self.assertIn(response.status_code, (403, 404))

    def test_receipt_after_close_is_denied(self):
        po, line = self.make_order(quantity=4)
        self.make_receipt(po, line, received=1)
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{po.pk}/close/",
            {"reason": "short close"}, format="json")
        response = self.client_for(self.support).post(
            "/api/procurement/goods-receipts/", {"purchase_order": po.pk},
            format="json")
        self.assertEqual(response.status_code, 400)

    def test_direct_purchase_order_create_is_a_readable_405(self):
        response = self.client_for(self.manager).post(
            "/api/procurement/purchase-orders/", {}, format="json")
        self.assertEqual(response.status_code, 405)
        self.assertIn("generated", response.data["detail"])


class ReceiptDiscrepancyTests(ProcurementP21Base):
    def test_structured_fields_and_accepted_only(self):
        stock = StockItem.objects.create(name="Toner", sku="TON-1", quantity=3)
        po, line = self.make_order(quantity=4, stock_item=stock)
        receipt, response = self.make_receipt(
            po, line, received=4, rejected=1, damaged=1)
        self.assertEqual(response.status_code, 201, response.data)
        arrival = GoodsReceiptItem.objects.get(pk=response.data["id"])
        self.assertEqual(arrival.accepted_quantity, 2)
        self.assertEqual(arrival.discrepancy_status, "mixed")
        self.assertEqual(arrival.inspection_status, "failed")
        self.assertTrue(arrival.rejection_reason)
        self.assertTrue(arrival.damage_notes)

        line.refresh_from_db()
        stock.refresh_from_db()
        self.assertEqual(line.received_qty, 2)
        self.assertEqual(line.rejected_qty, 1)
        self.assertEqual(line.damaged_qty, 1)
        self.assertEqual(stock.quantity, 5)
        self.assertTrue(StockMovement.objects.filter(
            stock_item=stock, movement_type="receive", quantity=2).exists())

    def test_total_equality_is_enforced(self):
        po, line = self.make_order()
        receipt = GoodsReceipt.objects.create(
            purchase_order=po, received_by=self.support)
        response = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {"goods_receipt": receipt.pk, "purchase_order_item": line.pk,
             "quantity_received": 1, "quantity_rejected": 2},
            format="json")
        self.assertEqual(response.status_code, 400)

    def test_receipt_result_creates_pending_asset_units(self):
        category = AssetCategory.objects.create(name="Laptop")
        po, line = self.make_order(quantity=3, serialized=True,
                                   category=category)
        receipt, response = self.make_receipt(po, line, received=3, rejected=1)
        self.assertEqual(response.status_code, 201, response.data)
        pending = ProcurementAssetReceiptItem.objects.filter(
            goods_receipt=receipt, status="pending_registration")
        self.assertEqual(pending.count(), 2)
        self.assertEqual(set(pending.values_list("sequence", flat=True)), {1, 2})
        for item in pending:
            self.assertEqual(item.purchase_order_id, po.pk)
            self.assertEqual(item.vendor_id, self.vendor.pk)
            self.assertEqual(item.asset_category_id, category.pk)
            self.assertEqual(item.purchase_cost, Decimal("250.00"))


class AssetRegistrationTests(ProcurementP21Base):
    def setUp(self):
        super().setUp()
        self.category = AssetCategory.objects.create(name="Laptop")
        self.po, self.line = self.make_order(
            quantity=2, serialized=True, category=self.category)
        self.receipt, _ = self.make_receipt(self.po, self.line, received=2)
        self.items = list(ProcurementAssetReceiptItem.objects.order_by("sequence"))

    def register(self, item, **overrides):
        payload = {
            "asset_tag": f"AT-{item.sequence}",
            "serial_number": f"SN-{item.sequence}",
            "name": "Laptop",
            "location": "HQ",
            "notes": "received",
        }
        payload.update(overrides)
        return self.client_for(self.support).post(
            f"/api/procurement/asset-receipt-items/{item.pk}/register-asset/",
            payload, format="json")

    def test_registration_links_asset_and_is_atomic(self):
        response = self.register(self.items[0])
        self.assertEqual(response.status_code, 200, response.data)
        item = ProcurementAssetReceiptItem.objects.get(pk=self.items[0].pk)
        self.assertEqual(item.status, "registered")
        self.assertIsNotNone(item.asset_id)
        self.assertEqual(item.asset.vendor_id, self.vendor.pk)
        self.assertEqual(item.asset.purchase_cost, Decimal("250.00"))
        self.assertEqual(item.registered_by, self.support)
        self.assertTrue(ProcurementHistory.objects.filter(
            purchase_order=self.po, action="asset_registered").exists())

    def test_duplicate_registration_is_denied(self):
        self.assertEqual(self.register(self.items[0]).status_code, 200)
        again = self.register(self.items[0], asset_tag="AT-DUP")
        self.assertEqual(again.status_code, 409)

    def test_duplicate_serial_and_asset_tag_are_rejected_without_losing_pending(self):
        self.assertEqual(self.register(self.items[0]).status_code, 200)
        duplicate_serial = self.register(
            self.items[1], asset_tag="AT-9", serial_number="SN-1")
        self.assertEqual(duplicate_serial.status_code, 400)
        duplicate_tag = self.register(self.items[1], asset_tag="AT-1")
        self.assertEqual(duplicate_tag.status_code, 400)
        item = ProcurementAssetReceiptItem.objects.get(pk=self.items[1].pk)
        self.assertEqual(item.status, "pending_registration")
        self.assertIsNone(item.asset_id)

    def test_employee_cannot_register(self):
        response = self.client_for(self.employee).post(
            f"/api/procurement/asset-receipt-items/{self.items[0].pk}/register-asset/",
            {"asset_tag": "X", "name": "X"}, format="json")
        self.assertIn(response.status_code, (403, 404))
        self.assertEqual(ProcurementAssetReceiptItem.objects.get(
            pk=self.items[0].pk).status, "pending_registration")

    def test_pending_list_is_paginated_and_scoped(self):
        response = self.client_for(self.support).get(
            "/api/procurement/asset-receipt-items/?status=pending_registration")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 2)
        other = make_user("other@example.test", "it_support", "T-OTH")
        response = self.client_for(other).get(
            "/api/procurement/asset-receipt-items/")
        self.assertEqual(response.data["results"], [])
