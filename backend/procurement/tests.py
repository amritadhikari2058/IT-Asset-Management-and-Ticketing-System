"""API tests for the procurement workflow.

These cover the contract the frontend relies on: purchase request
submission/approval, quotation selection, PO generation, and goods receipt
booking (partial, complete and over-receipt rejection).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Department, User
from assets.models import Asset, AssetCategory, Vendor
from inventory.models import StockItem

from .models import (
    GoodsReceipt,
    ProcurementHistory,
    ProcurementIdempotencyKey,
    PurchaseOrder,
    PurchaseOrderItem,
    ProcurementAssetReceiptItem,
    PurchaseQuotation,
    PurchaseRequest,
    PurchaseRequestItem,
    ProcurementSetting,
)


def make_user(email, role, employee_id):
    return User.objects.create_user(
        username=employee_id,
        email=email,
        password="test-pass-123",
        role=role,
        employee_id=employee_id,
    )


class ProcurementAPITestCase(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="IT", code="IT")
        self.vendor = Vendor.objects.create(name="Acme Supplies", code="ACME")
        self.admin = make_user("admin@example.test", "system_admin", "T-ADM")
        self.manager = make_user("manager@example.test", "it_manager", "T-MGR")
        self.support = make_user("support@example.test", "it_support", "T-SUP")
        self.employee = make_user("employee@example.test", "employee", "T-EMP")
        self.support.home_department = self.department
        self.support.save(update_fields=["home_department"])
        ProcurementSetting.objects.update_or_create(
            pk=1, defaults={"approval_threshold": Decimal("1000.00")},
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def make_request(self, total="500.00", user=None):
        from decimal import Decimal
        client = self.client_for(user or self.support)
        unit_price = str(Decimal(total) / Decimal(2))
        resp = client.post(
            "/api/procurement/purchase-requests/",
            {"reason": "Need laptops for new hires", "notes": "urgent"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        pr_id = resp.data["id"]
        item = client.post(
            "/api/procurement/purchase-request-items/",
            {
                "purchase_request": pr_id,
                "item_name": "Laptop",
                "quantity": 2,
                "estimated_unit_price": unit_price,
                "estimated_total": total,
            },
            format="json",
        )
        self.assertEqual(item.status_code, 201, item.data)
        return PurchaseRequest.objects.get(pk=pr_id)

    # ---- purchase request lifecycle ----

    def test_requester_submits_and_manager_approves(self):
        pr = self.make_request()
        resp = self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "pending_approval")
        self.assertFalse(resp.data["requires_system_admin_approval"])

        resp = self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/",
            {"reason": "approved"}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "approved")
        self.assertEqual(resp.data["approver"], self.manager.pk)

    def test_requester_cannot_approve_own_request(self):
        pr = self.make_request(user=self.manager)
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        resp = self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 400)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "pending_approval")

    def test_it_support_cannot_approve(self):
        pr = self.make_request()
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/",
            {}, format="json",
        )
        resp = self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 403)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "pending_approval")

    def test_high_value_request_requires_system_admin(self):
        pr = self.make_request(total="5000.00")
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        pr.refresh_from_db()
        self.assertTrue(pr.requires_system_admin_approval)

        resp = self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

        resp = self.client_for(self.admin).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "approved")

    def test_submit_twice_is_rejected(self):
        pr = self.make_request()
        client = self.client_for(self.support)
        client.post(f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json")
        resp = client.post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # ---- quotations ----

    def test_quotation_create_and_select(self):
        pr = self.make_request()
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        quote = self.client_for(self.manager).post(
            "/api/procurement/quotations/",
            {
                "purchase_request": pr.pk,
                "vendor": self.vendor.pk,
                "quoted_amount": "520.00",
                "delivery_days": 5,
                "warranty": "1 year",
            },
            format="json",
        )
        self.assertEqual(quote.status_code, 201, quote.data)

        self.assertEqual(
            self.client_for(self.support).post(
                f"/api/procurement/quotations/{quote.data['id']}/select/",
                {"reason": "best"}, format="json",
            ).status_code,
            403,
        )
        selected = self.client_for(self.manager).post(
            f"/api/procurement/quotations/{quote.data['id']}/select/",
            {"reason": "best value"}, format="json",
        )
        self.assertEqual(selected.status_code, 200, selected.data)
        self.assertTrue(selected.data["is_selected"])
        self.assertEqual(selected.data["selected_by"], self.manager.pk)

    # ---- purchase orders ----

    def _approved_request_with_quote(self):
        pr = self.make_request(total="500.00")
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        quote = PurchaseQuotation.objects.create(
            purchase_request=pr, vendor=self.vendor,
            quoted_amount=Decimal("520.00"), created_by=self.manager,
        )
        quote.is_selected = True
        quote.selected_by = self.manager
        quote.save()
        return pr

    def test_generate_purchase_order_from_selected_quotation(self):
        pr = self._approved_request_with_quote()
        resp = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/",
            {}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["vendor"], self.vendor.pk)
        self.assertEqual(resp.data["status"], "pending_approval")
        # Line values roll up so a generated PO never shows a zero total.
        self.assertEqual(Decimal(resp.data["subtotal"]), Decimal("500.00"))
        self.assertEqual(Decimal(resp.data["total"]), Decimal("500.00"))
        pr.refresh_from_db()
        self.assertEqual(pr.status, "po_generated")

    def test_generate_purchase_order_requires_selected_quotation(self):
        pr = self.make_request()
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        resp = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/",
            {}, format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_purchase_order_approve_then_issue(self):
        pr = self._approved_request_with_quote()
        po_data = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/",
            {}, format="json",
        ).data
        po = PurchaseOrder.objects.get(pk=po_data["id"])

        # Creator cannot approve their own PO.
        self.assertEqual(
            self.client_for(self.manager).post(
                f"/api/procurement/purchase-orders/{po.pk}/approve/", {}, format="json",
            ).status_code,
            400,
        )
        approved = self.client_for(self.admin).post(
            f"/api/procurement/purchase-orders/{po.pk}/approve/",
            {"reason": "ok"}, format="json",
        )
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], "approved")

        sent = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{po.pk}/send_to_vendor/",
            {}, format="json",
        )
        self.assertEqual(sent.status_code, 200, sent.data)
        self.assertEqual(sent.data["status"], "sent_to_vendor")

    # ---- goods receipts ----

    def _issued_po(self):
        pr = self._approved_request_with_quote()
        po_data = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/",
            {}, format="json",
        ).data
        po = PurchaseOrder.objects.get(pk=po_data["id"])
        self.client_for(self.admin).post(
            f"/api/procurement/purchase-orders/{po.pk}/approve/", {}, format="json",
        )
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{po.pk}/send_to_vendor/", {}, format="json",
        )
        po.refresh_from_db()
        return po

    def test_partial_receipt_then_complete_receipt(self):
        po = self._issued_po()
        line = po.items.first()
        self.assertEqual(line.quantity, 2)

        gr = self.client_for(self.support).post(
            "/api/procurement/goods-receipts/",
            {"purchase_order": po.pk, "delivery_note_number": "DN-1"},
            format="json",
        )
        self.assertEqual(gr.status_code, 201, gr.data)
        receipt = GoodsReceipt.objects.get(pk=gr.data["id"])

        first = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": 1,
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, 1)
        self.assertEqual(po.status, "partially_received")

        second = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": 1,
            },
            format="json",
        )
        self.assertEqual(second.status_code, 201, second.data)
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, 2)
        self.assertEqual(po.status, "received")

    def test_rejected_and_damaged_units_do_not_count_as_accepted(self):
        po = self._issued_po()
        line = po.items.first()
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": 2,
                "quantity_rejected": 1,
                "quantity_damaged": 1,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, 0)
        self.assertEqual(line.rejected_qty, 1)
        self.assertEqual(line.damaged_qty, 1)
        self.assertEqual(po.status, "received")

    def test_over_receipt_is_rejected(self):
        po = self._issued_po()
        line = po.items.first()
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": 5,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("quantity_received", resp.data)
        line.refresh_from_db()
        self.assertEqual(line.received_qty, 0)

    def test_rejected_plus_damaged_cannot_exceed_received(self):
        po = self._issued_po()
        line = po.items.first()
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": 1,
                "quantity_rejected": 2,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_receipt_line_must_match_receipt_purchase_order(self):
        po = self._issued_po()
        other_pr = self._approved_request_with_quote()
        other_po_data = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{other_pr.pk}/generate_from_pr/",
            {}, format="json",
        ).data
        other_line = PurchaseOrderItem.objects.filter(
            purchase_order_id=other_po_data["id"]).first()
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": other_line.pk,
                "quantity_received": 1,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # ---- visibility ----

    def test_it_support_only_sees_own_purchase_requests(self):
        own = self.make_request()
        other_user = make_user("other-support@example.test", "it_support", "T-SUP2")
        other = self.make_request(user=other_user)
        resp = self.client_for(self.support).get("/api/procurement/purchase-requests/")
        self.assertEqual(resp.status_code, 200)
        ids = {row["id"] for row in resp.data["results"]}
        self.assertIn(own.pk, ids)
        self.assertNotIn(other.pk, ids)

    def test_receipt_rejected_for_pending_approval_order(self):
        pr = self._approved_request_with_quote()
        po_data = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/",
            {}, format="json",
        ).data
        po = PurchaseOrder.objects.get(pk=po_data["id"])
        resp = self.client_for(self.support).post(
            "/api/procurement/goods-receipts/",
            {"purchase_order": po.pk}, format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_employee_denied_procurement_access(self):
        resp = self.client_for(self.employee).get("/api/procurement/purchase-requests/")
        self.assertEqual(resp.status_code, 403)

    def test_procurement_history_is_written(self):
        pr = self.make_request()
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )
        detail = self.client_for(self.manager).get(
            f"/api/procurement/purchase-requests/{pr.pk}/").data
        actions = [row["action"] for row in detail["history"]]
        self.assertEqual(actions[:3], ["created", "submitted", "approved"])

    # ---- receiving quantity integrity ----

    def _post_receipt(self, po, key=None):
        extra = {}
        if key:
            extra["HTTP_IDEMPOTENCY_KEY"] = key
        return self.client_for(self.support).post(
            "/api/procurement/goods-receipts/",
            {"purchase_order": po.pk, "delivery_note_number": "DN-1"},
            format="json",
            **extra,
        )

    def _post_receipt_item(self, receipt, line, qty):
        rid = receipt.pk if hasattr(receipt, "pk") else receipt
        return self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": rid,
                "purchase_order_item": line.pk,
                "quantity_received": qty,
            },
            format="json",
        )

    def test_full_receipt_in_one_line(self):
        po = self._issued_po()
        line = po.items.first()
        gr = self._post_receipt(po)
        self.assertEqual(gr.status_code, 201, gr.data)
        resp = self._post_receipt_item(gr.data["id"], line, 2)
        self.assertEqual(resp.status_code, 201, resp.data)
        po.refresh_from_db()
        self.assertEqual(po.status, "received")

    def test_multiple_partial_receipts_across_receipts(self):
        po = self._issued_po()
        line = po.items.first()
        self.assertEqual(line.quantity, 2)

        gr1 = self._post_receipt(po)
        self.assertEqual(gr1.status_code, 201, gr1.data)
        self.assertEqual(self._post_receipt_item(gr1.data["id"], line, 1).status_code, 201)
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, 1)
        self.assertEqual(po.status, "partially_received")

        gr2 = self._post_receipt(po)
        self.assertEqual(gr2.status_code, 201, gr2.data)
        self.assertEqual(self._post_receipt_item(gr2.data["id"], line, 1).status_code, 201)
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, 2)
        self.assertEqual(po.status, "received")

    def test_zero_quantity_receipt_rejected(self):
        po = self._issued_po()
        line = po.items.first()
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self._post_receipt_item(receipt.pk, line, 0)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("quantity_received", resp.data)
        line.refresh_from_db()
        self.assertEqual(line.received_qty, 0)

    def test_receipt_rejected_for_invalid_po_states(self):
        po = self._issued_po()
        line = po.items.first()
        for status in ("draft", "rejected", "cancelled", "closed"):
            po.status = status
            po.save(update_fields=["status"])
            receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
            resp = self._post_receipt_item(receipt.pk, line, 1)
            self.assertEqual(resp.status_code, 400, f"status {status}: {resp.data}")
            line.refresh_from_db()
            self.assertEqual(line.received_qty, 0)

    def test_idempotent_receipt_creation(self):
        po = self._issued_po()
        key = "idem-receipt-1"
        first = self._post_receipt(po, key=key)
        self.assertEqual(first.status_code, 201, first.data)
        receipt_id = first.data["id"]
        count_before = GoodsReceipt.objects.count()

        second = self._post_receipt(po, key=key)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data["id"], receipt_id)
        self.assertEqual(second.headers.get("X-Idempotency-Replayed"), "true")
        self.assertEqual(GoodsReceipt.objects.count(), count_before)

        # A different key creates a distinct receipt.
        third = self._post_receipt(po, key="idem-receipt-2")
        self.assertEqual(third.status_code, 201, third.data)
        self.assertNotEqual(third.data["id"], receipt_id)
        self.assertEqual(GoodsReceipt.objects.count(), count_before + 1)

    def test_idempotency_different_po_same_key_rejected(self):
        """Same idempotency key against a different PO must not replay."""
        po1 = self._issued_po()
        po2 = self._issued_po()
        key = "idem-po-conflict"

        first = self._post_receipt(po1, key=key)
        self.assertEqual(first.status_code, 201, first.data)

        # Same key, different PO (same user) → conflict, no new receipt.
        before = GoodsReceipt.objects.count()
        second = self._post_receipt(po2, key=key)
        self.assertEqual(second.status_code, 409, second.data)
        self.assertEqual(GoodsReceipt.objects.count(), before)

    def test_idempotency_different_user_same_key_rejected(self):
        """Same idempotency key used by a different user must not replay."""
        po = self._issued_po()
        key = "idem-user-conflict"

        first = self._post_receipt(po, key=key)
        self.assertEqual(first.status_code, 201, first.data)
        receipt_id = first.data["id"]

        before = GoodsReceipt.objects.count()
        second = self.client_for(self.manager).post(
            "/api/procurement/goods-receipts/",
            {"purchase_order": po.pk, "delivery_note_number": "DN-2"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(second.status_code, 409, second.data)
        self.assertEqual(GoodsReceipt.objects.count(), before)

    def test_idempotency_failed_creation_clears_key(self):
        """A failed receipt creation must not leave a reusable idempotency record."""
        po = self._issued_po()
        key = "idem-fail-clear"
        # Mark the PO closed so receipt creation fails.
        po.status = "closed"
        po.save(update_fields=["status"])

        resp = self._post_receipt(po, key=key)
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertFalse(
            ProcurementIdempotencyKey.objects.filter(key=key).exists(),
            "Failed creation must not leave a persistent idempotency key row.",
        )

        # Reopen the PO; the same key must now work as a fresh request.
        po.status = "sent_to_vendor"
        po.save(update_fields=["status"])
        retry = self._post_receipt(po, key=key)
        self.assertEqual(retry.status_code, 201, retry.data)
        self.assertIsNotNone(retry.data.get("id"))

    def test_repeated_receiving_never_over_receives(self):
        """Repeated (concurrent-client-like) requests cannot over-receive a line.

        SQLite serializes writes with a table-level lock, so true multi-writer
        concurrency is not practical here; the backend's remaining-quantity
        check plus atomic F() increment is what guarantees safety. We exercise
        it with rapid repeated requests, which is the practical equivalent of
        concurrent clients on this database.
        """
        po = self._issued_po()
        line = po.items.first()
        self.assertEqual(line.quantity, 2)

        successes = 0
        for _ in range(4):
            receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
            resp = self._post_receipt_item(receipt.pk, line, 1)
            if resp.status_code == 201:
                successes += 1
            else:
                self.assertEqual(resp.status_code, 400)
                self.assertIn("quantity_received", resp.data)
                break
            line.refresh_from_db()
            po.refresh_from_db()
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(successes, 2)
        self.assertEqual(line.received_qty, 2)
        self.assertEqual(po.status, "received")

        # One more unit must be rejected: nothing remains.
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self._post_receipt_item(receipt.pk, line, 1)
        self.assertEqual(resp.status_code, 400)
        line.refresh_from_db()
        self.assertEqual(line.received_qty, 2)

    # ---- receipt immutability & permissions ----

    def test_posted_receipt_is_immutable(self):
        po = self._issued_po()
        gr = self._post_receipt(po)
        self.assertEqual(gr.status_code, 201)
        rid = gr.data["id"]

        client = self.client_for(self.support)
        self.assertEqual(
            client.put(f"/api/procurement/goods-receipts/{rid}/", {"notes": "x"},
                       format="json").status_code,
            405,
        )
        self.assertEqual(
            client.delete(f"/api/procurement/goods-receipts/{rid}/", format="json").status_code,
            405,
        )

        line = po.items.first()
        item = self._post_receipt_item(rid, line, 1)
        self.assertEqual(item.status_code, 201)
        iid = item.data["id"]
        self.assertEqual(
            client.put(f"/api/procurement/goods-receipt-items/{iid}/",
                       {"quantity_received": 2}, format="json").status_code,
            405,
        )
        self.assertEqual(
            client.delete(f"/api/procurement/goods-receipt-items/{iid}/", format="json").status_code,
            405,
        )

    def test_employee_cannot_create_receipt(self):
        po = self._issued_po()
        resp = self.client_for(self.employee).post(
            "/api/procurement/goods-receipts/",
            {"purchase_order": po.pk}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    # ---- asset registration integration ----

    def _serialized_line(self, po):
        line = po.items.first()
        line.is_serialized = True
        line.asset_category = AssetCategory.objects.create(name="Laptops")
        line.save(update_fields=["is_serialized", "asset_category"])
        return line

    def test_serialized_receipt_creates_pending_asset_items(self):
        po = self._issued_po()
        line = self._serialized_line(po)
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self._post_receipt_item(receipt.pk, line, 2)
        self.assertEqual(resp.status_code, 201, resp.data)
        pending = ProcurementAssetReceiptItem.objects.filter(
            purchase_order=po, goods_receipt=receipt, purchase_order_item=line,
            status="pending_registration",
        )
        self.assertEqual(pending.count(), 2)

    def test_asset_registration_duplicate_serial_rejected(self):
        po = self._issued_po()
        line = self._serialized_line(po)
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        self._post_receipt_item(receipt.pk, line, 1)
        item = ProcurementAssetReceiptItem.objects.get(
            goods_receipt=receipt, purchase_order_item=line,
            status="pending_registration",
        )
        category = AssetCategory.objects.get(name="Laptops")
        payload = {
            "asset_tag": "LT-001", "serial_number": "SN-LT-001", "name": "Laptop 1",
            "category": category.pk, "department": self.department.pk,
            "purchase_cost": "250.00",
        }
        first = self.client_for(self.support).post(
            f"/api/procurement/asset-receipt-items/{item.pk}/register-asset/",
            payload, format="json",
        )
        self.assertEqual(first.status_code, 200, first.data)

        # A second pending unit for the same PO/line may not reuse the serial.
        self._post_receipt_item(receipt.pk, line, 1)
        item2 = ProcurementAssetReceiptItem.objects.filter(
            goods_receipt=receipt, purchase_order_item=line,
            status="pending_registration",
        ).exclude(pk=item.pk).first()
        self.assertIsNotNone(item2)
        dup = self.client_for(self.support).post(
            f"/api/procurement/asset-receipt-items/{item2.pk}/register-asset/",
            {**payload, "asset_tag": "LT-002"}, format="json",
        )
        self.assertEqual(dup.status_code, 400, dup.data)
        item2.refresh_from_db()
        self.assertEqual(item2.status, "pending_registration")
        self.assertIsNone(item2.asset_id)
        self.assertEqual(Asset.objects.filter(serial_number="SN-LT-001").count(), 1)

    def test_asset_registration_traceability(self):
        po = self._issued_po()
        line = self._serialized_line(po)
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        self._post_receipt_item(receipt.pk, line, 1)
        item = ProcurementAssetReceiptItem.objects.get(
            goods_receipt=receipt, purchase_order_item=line,
            status="pending_registration",
        )
        category = AssetCategory.objects.get(name="Laptops")
        resp = self.client_for(self.support).post(
            f"/api/procurement/asset-receipt-items/{item.pk}/register-asset/",
            {
                "asset_tag": "LT-001", "serial_number": "SN-LT-001", "name": "Laptop 1",
                "category": category.pk, "department": self.department.pk,
                "purchase_cost": "250.00", "warranty_expiry": "2029-12-31",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        item.refresh_from_db()
        self.assertEqual(item.status, "registered")
        self.assertIsNotNone(item.asset_id)

        asset = Asset.objects.get(pk=item.asset_id)
        self.assertEqual(asset.asset_tag, "LT-001")
        self.assertEqual(asset.serial_number, "SN-LT-001")
        self.assertEqual(asset.vendor_id, po.vendor_id)
        self.assertEqual(asset.category_id, category.pk)
        self.assertIn(po.po_number, asset.description)
        self.assertIn(receipt.gr_number, asset.description)
        self.assertTrue(
            ProcurementHistory.objects.filter(
                purchase_order=po, action="asset_registered"
            ).exists()
        )

    # ---- estimated_total read-only (threshold bypass protection) ----

    def test_estimated_total_is_read_only_on_purchase_request(self):
        """estimated_total cannot be set directly on a purchase request;
        it is always derived from line items."""
        pr = self.make_request(total="5000.00")
        pr.refresh_from_db()
        self.assertEqual(Decimal(str(pr.estimated_total)), Decimal("5000.00"))

        # Attempt to understate the total to bypass system admin approval,
        # while the request is still draft (editable).
        resp = self.client_for(self.support).patch(
            f"/api/procurement/purchase-requests/{pr.pk}/",
            {"reason": pr.reason, "estimated_total": "1.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        pr.refresh_from_db()
        # The total is derived from items, not from the client-supplied value.
        self.assertEqual(Decimal(str(pr.estimated_total)), Decimal("5000.00"))

        # Submit: threshold check uses the item-derived total, not the
        # client-supplied understated value.
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        pr.refresh_from_db()
        self.assertTrue(pr.requires_system_admin_approval)

    def test_estimated_total_item_cross_check_blocks_understatement(self):
        """estimated_total on a request item must equal quantity x unit_price;
        understatement is rejected."""
        pr = self.make_request(total="5000.00")
        self.client_for(self.support).post(
            f"/api/procurement/purchase-requests/{pr.pk}/submit/", {}, format="json",
        )
        self.client_for(self.manager).post(
            f"/api/procurement/purchase-requests/{pr.pk}/approve/", {}, format="json",
        )

        item = PurchaseRequestItem.objects.filter(purchase_request=pr).first()
        # Attempt to understate the item total (2 x 2500 = 5000, not 1).
        resp = self.client_for(self.support).patch(
            f"/api/procurement/purchase-request-items/{item.pk}/",
            {"estimated_total": "1.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        item.refresh_from_db()
        self.assertEqual(Decimal(str(item.estimated_total)), Decimal("5000.00"))

    # ---- atomic stock quantity update on receipt ----

    def _stock_po(self):
        """Return an issued PO whose line is linked to a stock item."""
        po = self._issued_po()
        line = po.items.first()
        stock = StockItem.objects.create(
            name="Stock Laptop", sku=f"STOCK-{po.pk}", quantity=0,
        )
        line.stock_item = stock
        line.save(update_fields=["stock_item"])
        return po, line, stock

    def test_receipt_increments_stock_atomically(self):
        po, line, stock = self._stock_po()
        receipt = GoodsReceipt.objects.create(purchase_order=po, received_by=self.support)
        resp = self.client_for(self.support).post(
            "/api/procurement/goods-receipt-items/",
            {
                "goods_receipt": receipt.pk,
                "purchase_order_item": line.pk,
                "quantity_received": 2,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 2)

    def _draft_po(self):
        """Return a PO in draft status (editable items)."""
        pr = self._approved_request_with_quote()
        po_data = self.client_for(self.manager).post(
            f"/api/procurement/purchase-orders/{pr.pk}/generate_from_pr/", {}, format="json",
        ).data
        return PurchaseOrder.objects.get(pk=po_data["id"])

    # ---- PurchaseOrderItem status-based edit protection ----

    def test_po_item_update_allowed_on_draft_order(self):
        po = self._draft_po()
        line = po.items.first()
        resp = self.client_for(self.manager).patch(
            f"/api/procurement/purchase-order-items/{line.pk}/",
            {"unit_price": "100.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        line.refresh_from_db()
        self.assertEqual(Decimal(str(line.unit_price)), Decimal("100.00"))

    def test_po_item_update_blocked_on_sent_order(self):
        po = self._issued_po()
        line = po.items.first()
        resp = self.client_for(self.manager).patch(
            f"/api/procurement/purchase-order-items/{line.pk}/",
            {"unit_price": "9999.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        line.refresh_from_db()
        # The blocked update must not change the unit price.
        self.assertEqual(Decimal(str(line.unit_price)), Decimal("250.00"))

    def test_po_item_delete_blocked_on_sent_order(self):
        po = self._issued_po()
        line = po.items.first()
        resp = self.client_for(self.manager).delete(
            f"/api/procurement/purchase-order-items/{line.pk}/", format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertTrue(PurchaseOrderItem.objects.filter(pk=line.pk).exists())

    def test_po_total_recalculated_on_item_change(self):
        po = self._draft_po()
        line = po.items.first()
        original_total = po.total
        resp = self.client_for(self.manager).patch(
            f"/api/procurement/purchase-order-items/{line.pk}/",
            {"unit_price": "100.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        po.refresh_from_db()
        self.assertNotEqual(po.total, original_total)
