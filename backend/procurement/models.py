import os
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import User, Department
from assets.models import Vendor, Asset, AssetCategory
from common.models import SoftDeleteModel
from inventory.models import StockItem
from services.models import ServiceRequest


class ProcurementSetting(models.Model):
    """Configurable procurement approval thresholds."""

    approval_threshold = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=100000.00,
        help_text="Amount in local currency above which System Admin approval is required (in addition to IT Manager).",
    )
    currency = models.CharField(max_length=10, default="NPR")
    organization_name = models.CharField(max_length=200, default="IT Service Desk")
    delivery_address = models.TextField(blank=True, default="")
    po_terms = models.TextField(blank=True, default="")
    authorized_signatory_name = models.CharField(max_length=200, blank=True, default="")
    authorized_signatory_title = models.CharField(max_length=200, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="procurement_settings_updated"
    )

    class Meta:
        verbose_name = "Procurement Setting"
        verbose_name_plural = "Procurement Settings"

    def __str__(self):
        return f"Procurement Settings (threshold {self.currency} {self.approval_threshold})"

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={})
        return obj


def procurement_attachment_upload_to(instance, filename):
    """Generate a safe, unguessable storage filename for an attachment."""
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    safe_ext = "".join(c for c in ext if c.isalnum())[:10]
    return f"procurement_attachments/{uuid.uuid4().hex}" + (
        f".{safe_ext}" if safe_ext else ""
    )


DOCUMENT_TYPE_CHOICES = [
    ("requisition", "Requisition"),
    ("specification", "Specification"),
    ("quotation", "Quotation"),
    ("comparison", "Comparison"),
    ("approval", "Approval"),
    ("purchase_order", "Purchase Order"),
    ("delivery_note", "Delivery Note"),
    ("invoice", "Invoice"),
    ("supplier_invoice", "Supplier Invoice"),
    ("tax_invoice", "Tax Invoice"),
    ("receipt", "Receipt"),
    ("inspection", "Inspection"),
    ("discrepancy", "Discrepancy"),
    ("warranty", "Warranty"),
    ("credit_note", "Credit Note"),
    ("return_authorization", "Return Authorization"),
    ("shipping_document", "Shipping Document"),
    ("replacement_document", "Replacement Document"),
    ("payment_evidence", "Payment Evidence"),
    ("other", "Other"),
]

ATTACHMENT_STATUS_CHOICES = [
    ("active", "Active"),
    ("superseded", "Superseded"),
    ("archived", "Archived"),
]


class PurchaseRequest(SoftDeleteModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending_approval", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("returned_for_correction", "Returned for Correction"),
        ("po_generated", "PO Generated"),
        ("cancelled", "Cancelled"),
        ("closed", "Closed"),
    ]

    pr_number = models.CharField(max_length=30, unique=True, db_index=True)
    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name="purchase_requests")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_requests")
    reason = models.TextField()
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft", db_index=True)
    estimated_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    requires_system_admin_approval = models.BooleanField(default=False)
    approver = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_purchase_requests")
    approval_decision = models.CharField(max_length=20, blank=True, default="")
    approval_reason = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["requester", "status"]),
        ]
        permissions = [
            ("approve_pr", "Can approve purchase requests"),
            ("reject_pr", "Can reject purchase requests"),
        ]
        constraints = [
            # Ensure pr_number is unique across non-deleted requests.
            # Soft-deleted rows may retain historical pr_numbers.
            models.UniqueConstraint(
                fields=["pr_number"],
                name="unique_pr_number_active",
                condition=models.Q(is_deleted=False),
            ),
        ]

    def __str__(self):
        return self.pr_number

    def save(self, *args, **kwargs):
        if not self.pr_number:
            today = timezone.now().strftime("%Y%m%d")
            count = PurchaseRequest.objects.count() + 1
            self.pr_number = f"PR-{timezone.now().year}-{count:05d}"
        super().save(*args, **kwargs)


class PurchaseRequestItem(models.Model):
    purchase_request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name="items")
    item_name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    suggested_vendor = models.ForeignKey(Vendor, null=True, blank=True, on_delete=models.SET_NULL)
    estimated_unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    estimated_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.purchase_request.pr_number} - {self.item_name} x{self.quantity}"


class PurchaseQuotation(models.Model):
    purchase_request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name="quotations")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    quoted_amount = models.DecimalField(max_digits=14, decimal_places=2)
    delivery_days = models.PositiveIntegerField(null=True, blank=True)
    warranty = models.CharField(max_length=200, blank=True, default="")
    terms = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    is_selected = models.BooleanField(default=False)
    selected_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="selected_quotations")
    selected_at = models.DateTimeField(null=True, blank=True)
    selection_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-quoted_amount"]

    def __str__(self):
        return f"{self.purchase_request.pr_number} - {self.vendor.name} ({self.quoted_amount})"


class PurchaseOrder(SoftDeleteModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending_approval", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("sent_to_vendor", "Sent to Vendor"),
        ("partially_received", "Partially Received"),
        ("received", "Received"),
        ("cancelled", "Cancelled"),
        ("closed", "Closed"),
    ]

    po_number = models.CharField(max_length=30, unique=True, db_index=True)
    purchase_request = models.ForeignKey(PurchaseRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_orders")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_purchase_orders")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="draft", db_index=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    shipping = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="NPR")
    delivery_address = models.TextField(blank=True, default="")
    terms = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    requires_system_admin_approval = models.BooleanField(default=False)
    approver = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_purchase_orders")
    approval_decision = models.CharField(max_length=20, blank=True, default="")
    approval_reason = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_reason = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["vendor", "status"]),
        ]
        permissions = [
            ("approve_po", "Can approve purchase orders"),
            ("reject_po", "Can reject purchase orders"),
            ("generate_po_pdf", "Can generate purchase order PDF"),
            ("receive_goods", "Can receive goods"),
        ]
        constraints = [
            # Ensure po_number is unique across non-deleted orders.
            # Soft-deleted rows may retain historical po_numbers.
            models.UniqueConstraint(
                fields=["po_number"],
                name="unique_po_number_active",
                condition=models.Q(is_deleted=False),
            ),
        ]

    def __str__(self):
        return self.po_number

    def save(self, *args, **kwargs):
        if not self.po_number:
            count = PurchaseOrder.objects.count() + 1
            self.po_number = f"PO-{timezone.now().year}-{count:05d}"
        # Calculate total
        self.total = (self.subtotal or 0) + (self.tax or 0) + (self.shipping or 0) - (self.discount or 0)
        super().save(*args, **kwargs)


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="items")
    item_name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    received_qty = models.PositiveIntegerField(default=0)
    rejected_qty = models.PositiveIntegerField(default=0)
    damaged_qty = models.PositiveIntegerField(default=0)
    is_serialized = models.BooleanField(default=False)
    stock_item = models.ForeignKey(StockItem, null=True, blank=True, on_delete=models.SET_NULL)
    asset_category = models.ForeignKey(
        AssetCategory, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="procurement_order_lines",
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        self.total = (self.quantity * self.unit_price) + (self.tax or 0) - (self.discount or 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.purchase_order.po_number} - {self.item_name} x{self.quantity}"


class GoodsReceipt(SoftDeleteModel):
    gr_number = models.CharField(max_length=30, unique=True, db_index=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="goods_receipts")
    delivery_note_number = models.CharField(max_length=120, blank=True, default="")
    invoice_number = models.CharField(max_length=120, blank=True, default="")
    received_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="goods_receipts")
    received_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at"]
        permissions = [
            ("create_gr", "Can create goods receipts"),
        ]

    def save(self, *args, **kwargs):
        if not self.gr_number:
            count = GoodsReceipt.objects.count() + 1
            self.gr_number = f"GR-{timezone.now().year}-{count:05d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.gr_number


INSPECTION_STATUS_CHOICES = [
    ("pending", "Pending inspection"),
    ("passed", "Passed"),
    ("failed", "Failed"),
]

DISCREPANCY_STATUS_CHOICES = [
    ("none", "No discrepancy"),
    ("rejected", "Rejected units"),
    ("damaged", "Damaged units"),
    ("mixed", "Rejected and damaged units"),
]


class GoodsReceiptItem(models.Model):
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="items")
    purchase_order_item = models.ForeignKey(PurchaseOrderItem, on_delete=models.PROTECT)
    quantity_received = models.PositiveIntegerField(default=0)
    quantity_rejected = models.PositiveIntegerField(default=0)
    quantity_damaged = models.PositiveIntegerField(default=0)
    #: Explicit accepted count. Always equals received - rejected - damaged;
    #: stored so downstream reporting never has to re-derive it.
    accepted_quantity = models.PositiveIntegerField(default=0)
    rejection_reason = models.TextField(blank=True, default="")
    damage_notes = models.TextField(blank=True, default="")
    inspection_status = models.CharField(
        max_length=20, choices=INSPECTION_STATUS_CHOICES, default="pending")
    discrepancy_status = models.CharField(
        max_length=20, choices=DISCREPANCY_STATUS_CHOICES, default="none")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.goods_receipt.gr_number} - {self.purchase_order_item.item_name}"


def derive_discrepancy_status(rejected, damaged):
    if rejected and damaged:
        return "mixed"
    if rejected:
        return "rejected"
    if damaged:
        return "damaged"
    return "none"


PROCUREMENT_ASSET_STATUS_CHOICES = [
    ("pending_registration", "Pending registration"),
    ("registered", "Registered"),
    ("cancelled", "Cancelled"),
    ("exception", "Exception"),
]


class ProcurementAssetReceiptItem(models.Model):
    """One pending/registered Asset per accepted serialized receipt unit.

    Created transactionally when a goods receipt line for a serialized PO
    line is posted. It records where the unit came from so registration is
    traceable instead of encoding receipt identity into free-text fields on
    a generic `/assets/` create.
    """

    goods_receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.PROTECT, related_name="asset_items")
    goods_receipt_item = models.ForeignKey(
        GoodsReceiptItem, on_delete=models.PROTECT, related_name="asset_items")
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, related_name="asset_receipt_items")
    purchase_order_item = models.ForeignKey(
        PurchaseOrderItem, on_delete=models.PROTECT, related_name="asset_receipt_items")
    vendor = models.ForeignKey(
        Vendor, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="procurement_asset_items")
    asset_category = models.ForeignKey(
        AssetCategory, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="procurement_asset_items")
    sequence = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=30, choices=PROCUREMENT_ASSET_STATUS_CHOICES,
        default="pending_registration", db_index=True)
    asset = models.OneToOneField(
        Asset, null=True, blank=True, on_delete=models.PROTECT,
        related_name="procurement_receipt_item")
    expected_purchase_date = models.DateField(null=True, blank=True)
    purchase_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True)
    warranty_expiry = models.DateField(null=True, blank=True)
    registered_at = models.DateTimeField(null=True, blank=True)
    registered_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="registered_procurement_assets")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["goods_receipt", "purchase_order_item", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["goods_receipt_item", "sequence"],
                name="proc_asset_item_unique_receipt_line_sequence",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"],
                         name="proc_asset_item_status_idx"),
            models.Index(fields=["purchase_order"],
                         name="proc_asset_item_po_idx"),
        ]

    def __str__(self):
        return (f"{self.purchase_order.po_number} "
                f"{self.purchase_order_item.item_name} #{self.sequence} "
                f"[{self.status}]")


class ProcurementAttachment(SoftDeleteModel):
    """Protected file attached to exactly one procurement record.

    A restricted set of nullable parents is used on purpose: no generic
    foreign key, so cross-parent IDOR is easy to deny. Exactly one parent
    must be set (validated in ``clean`` and in the serializer).
    """

    purchase_request = models.ForeignKey(
        PurchaseRequest, null=True, blank=True, on_delete=models.CASCADE,
        related_name="attachments")
    quotation = models.ForeignKey(
        PurchaseQuotation, null=True, blank=True, on_delete=models.CASCADE,
        related_name="attachments")
    purchase_order = models.ForeignKey(
        PurchaseOrder, null=True, blank=True, on_delete=models.CASCADE,
        related_name="attachments")
    goods_receipt = models.ForeignKey(
        GoodsReceipt, null=True, blank=True, on_delete=models.CASCADE,
        related_name="attachments")
    supplier_invoice = models.ForeignKey(
        "SupplierInvoice", null=True, blank=True, on_delete=models.CASCADE,
        related_name="attachments")
    vendor_return = models.ForeignKey(
        "VendorReturn", null=True, blank=True, on_delete=models.CASCADE,
        related_name="attachments")
    credit_note = models.ForeignKey(
        "VendorCreditNote", null=True, blank=True, on_delete=models.CASCADE,
        related_name="attachments")
    document_type = models.CharField(
        max_length=30, choices=DOCUMENT_TYPE_CHOICES, default="other")
    uploaded_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="uploaded_procurement_attachments")
    original_filename = models.CharField(max_length=255)
    file = models.FileField(upload_to=procurement_attachment_upload_to)
    content_type = models.CharField(max_length=100, blank=True, default="")
    size = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True, default="")
    checksum = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=20, choices=ATTACHMENT_STATUS_CHOICES,
        default="active", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["purchase_request", "status"], name="proc_attach_pr_idx"),
            models.Index(fields=["purchase_order", "status"], name="proc_attach_po_idx"),
            models.Index(fields=["supplier_invoice", "status"], name="proc_attach_inv_idx"),
            models.Index(fields=["vendor_return", "status"], name="proc_attach_ret_idx"),
            models.Index(fields=["credit_note", "status"], name="proc_attach_cn_idx"),
        ]

    @property
    def parent(self):
        return (
            self.purchase_request or self.quotation or self.purchase_order
            or self.goods_receipt or self.supplier_invoice or self.vendor_return
            or self.credit_note
        )

    def clean(self):
        super().clean()
        parents = [
            self.purchase_request_id, self.quotation_id, self.purchase_order_id,
            self.goods_receipt_id, self.supplier_invoice_id, self.vendor_return_id,
            self.credit_note_id,
        ]
        if sum(1 for p in parents if p) != 1:
            from django.core.exceptions import ValidationError
            raise ValidationError("Exactly one parent procurement record must be set for an attachment.")

    def __str__(self):
        return f"{self.original_filename} ({self.get_document_type_display()})"


class ProcurementHistory(models.Model):
    ACTION_CHOICES = [
        ("created", "Created"),
        ("updated", "Updated"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("returned", "Returned for Correction"),
        ("po_generated", "PO Generated"),
        ("sent", "Sent to Vendor"),
        ("received", "Goods Received"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("closed", "Closed"),
        ("asset_registered", "Asset Registered"),
    ]

    purchase_request = models.ForeignKey(PurchaseRequest, null=True, blank=True, on_delete=models.CASCADE, related_name="history")
    purchase_order = models.ForeignKey(PurchaseOrder, null=True, blank=True, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class ProcurementIdempotencyKey(models.Model):
    """Idempotency tokens for procurement write operations.

    A client sends an ``Idempotency-Key`` header with a mutating request. The
    first successful response is recorded under the key; repeat submissions
    with the same key replay that response instead of re-executing the write,
    so network retries and double-posts cannot create duplicate receipts or
    other side effects.
    """

    key = models.CharField(max_length=128, unique=True, db_index=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder, null=True, blank=True, on_delete=models.CASCADE,
        related_name="idempotency_keys")
    received_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="procurement_idempotency_keys")
    response_status = models.PositiveIntegerField(default=200)
    response_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# ---------------------------------------------------------------------------
# P3: Supplier invoicing, matching, returns, credit notes, financial control
# ---------------------------------------------------------------------------

SUPPLIER_INVOICE_STATUS_CHOICES = [
    ("draft", "Draft"), ("submitted", "Submitted"), ("matching", "Matching"),
    ("exception", "Exception"), ("matched", "Matched"), ("approved", "Approved"),
    ("rejected", "Rejected"), ("cancelled", "Cancelled"), ("payment_ready", "Payment Ready"),
    ("paid", "Paid"), ("closed", "Closed"),
]
PAYMENT_STATUS_CHOICES = [
    ("not_ready", "Not ready"), ("on_hold", "On hold"), ("ready", "Ready"),
    ("partially_paid", "Partially paid"), ("paid", "Paid"), ("cancelled", "Cancelled"),
]


def normalize_invoice_number(value):
    import re
    s = str(value or "").strip().upper()
    s = re.sub(r"\s+", " ", s)
    return s


class SupplierInvoice(SoftDeleteModel):
    invoice_number = models.CharField(max_length=120)
    normalized_invoice_number = models.CharField(max_length=120, db_index=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="supplier_invoices")
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="supplier_invoices")
    invoice_date = models.DateField()
    received_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=10)
    status = models.CharField(max_length=30, choices=SUPPLIER_INVOICE_STATUS_CHOICES, default="draft", db_index=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default="not_ready", db_index=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    freight_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    other_charge_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    matched_subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    variance_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payment_hold = models.BooleanField(default=False)
    payment_hold_reason = models.TextField(blank=True, default="")
    external_accounting_reference = models.CharField(max_length=120, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_supplier_invoices")
    submitted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="submitted_supplier_invoices")
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_supplier_invoices")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_supplier_invoices")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    payment_ready_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["vendor", "normalized_invoice_number"], name="inv_vendor_norm_idx"),
            models.Index(fields=["purchase_order", "status"], name="inv_po_status_idx"),
            models.Index(fields=["status", "payment_status"], name="inv_status_pay_idx"),
        ]
        constraints = [
            # Ensure invoice_number is unique across non-deleted invoices.
            # Soft-deleted rows may retain historical invoice_numbers.
            models.UniqueConstraint(
                fields=["invoice_number"],
                name="unique_invoice_number_active",
                condition=models.Q(is_deleted=False),
            ),
        ]

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        if self.due_date and self.invoice_date and self.due_date < self.invoice_date:
            raise ValidationError({"due_date": "Due date cannot precede invoice date."})
        self.normalized_invoice_number = normalize_invoice_number(self.invoice_number)

    def save(self, *args, **kwargs):
        self.normalized_invoice_number = normalize_invoice_number(self.invoice_number)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice_number} ({self.vendor})"


INVOICE_LINE_MATCH_STATUS_CHOICES = [
    ("unmatched", "Unmatched"), ("matched", "Matched"), ("quantity_variance", "Quantity variance"),
    ("price_variance", "Price variance"), ("tax_variance", "Tax variance"),
    ("multiple_variances", "Multiple variances"), ("receipt_missing", "Receipt missing"),
    ("po_line_missing", "PO line missing"), ("over_invoiced", "Over invoiced"),
    ("exception_accepted", "Exception accepted"),
]


class SupplierInvoiceLine(models.Model):
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name="lines")
    purchase_order_item = models.ForeignKey(PurchaseOrderItem, on_delete=models.PROTECT, related_name="invoice_lines")
    goods_receipt_item = models.ForeignKey(GoodsReceiptItem, null=True, blank=True, on_delete=models.PROTECT, related_name="invoice_lines")
    description = models.TextField(blank=True, default="")
    invoiced_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    accepted_quantity_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    freight_allocation = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_charge_allocation = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    matched_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity_variance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    price_variance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_variance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_variance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    match_status = models.CharField(max_length=30, choices=INVOICE_LINE_MATCH_STATUS_CHOICES, default="unmatched", db_index=True)
    exception_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["invoice", "match_status"], name="invline_invoice_status_idx")]


MATCH_OVERALL_STATUS_CHOICES = [
    ("matched", "Matched"), ("matched_within_tolerance", "Matched within tolerance"),
    ("exception", "Exception"), ("receipt_incomplete", "Receipt incomplete"),
    ("over_invoiced", "Over invoiced"), ("unmatched", "Unmatched"), ("invalid", "Invalid"),
]


class InvoiceMatchResult(models.Model):
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name="match_results")
    match_version = models.PositiveIntegerField(default=1)
    overall_status = models.CharField(max_length=30, choices=MATCH_OVERALL_STATUS_CHOICES, default="unmatched")
    po_total_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    accepted_receipt_total_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    invoice_total_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    quantity_variance_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    price_variance_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_variance_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_variance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tolerance_snapshot = models.JSONField(default=dict, blank=True)
    matched_at = models.DateTimeField(auto_now_add=True)
    matched_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoice_match_results")
    detail = models.JSONField(default=dict, blank=True)
    checksum = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-match_version", "-created_at"]
        constraints = [models.UniqueConstraint(fields=["invoice", "match_version"], name="uniq_invoice_match_version")]


INVOICE_EXCEPTION_TYPE_CHOICES = [
    ("quantity_variance", "Quantity variance"), ("price_variance", "Price variance"),
    ("tax_variance", "Tax variance"), ("over_invoiced", "Over invoiced"),
    ("receipt_missing", "Receipt missing"), ("po_line_missing", "PO line missing"),
    ("currency_mismatch", "Currency mismatch"), ("duplicate_invoice", "Duplicate invoice"),
    ("rejected_goods_invoiced", "Rejected goods invoiced"), ("damaged_goods_invoiced", "Damaged goods invoiced"),
    ("invalid_total", "Invalid total"), ("other", "Other"),
]
EXCEPTION_SEVERITY_CHOICES = [("info", "Info"), ("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")]
EXCEPTION_STATUS_CHOICES = [("open", "Open"), ("acknowledged", "Acknowledged"), ("accepted", "Accepted"), ("resolved", "Resolved"), ("rejected", "Rejected"), ("superseded", "Superseded")]
EXCEPTION_RESOLUTION_CHOICES = [
    ("corrected_invoice", "Corrected invoice"), ("additional_receipt", "Additional receipt"),
    ("credit_note", "Credit note"), ("vendor_return", "Vendor return"),
    ("authorized_variance", "Authorized variance"), ("duplicate_cancelled", "Duplicate cancelled"),
    ("rejected", "Rejected"), ("other", "Other"),
]


class InvoiceException(models.Model):
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name="exceptions")
    invoice_line = models.ForeignKey(SupplierInvoiceLine, null=True, blank=True, on_delete=models.CASCADE, related_name="exceptions")
    exception_type = models.CharField(max_length=40, choices=INVOICE_EXCEPTION_TYPE_CHOICES)
    severity = models.CharField(max_length=20, choices=EXCEPTION_SEVERITY_CHOICES, default="medium")
    status = models.CharField(max_length=20, choices=EXCEPTION_STATUS_CHOICES, default="open", db_index=True)
    expected_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    actual_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    variance = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    variance_percent = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    assigned_to = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_invoice_exceptions")
    detected_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="acknowledged_invoice_exceptions")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="resolved_invoice_exceptions")
    resolution = models.CharField(max_length=40, choices=EXCEPTION_RESOLUTION_CHOICES, blank=True, default="")
    resolution_note = models.TextField(blank=True, default="")
    fingerprint = models.CharField(max_length=64, db_index=True, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["invoice", "status"], name="invexc_invoice_status_idx"),
            models.Index(fields=["fingerprint", "status"], name="invexc_fp_status_idx"),
        ]


VENDOR_RETURN_STATUS_CHOICES = [
    ("draft", "Draft"), ("pending_approval", "Pending Approval"), ("approved", "Approved"),
    ("shipped", "Shipped"), ("partially_resolved", "Partially Resolved"), ("resolved", "Resolved"),
    ("rejected", "Rejected"), ("cancelled", "Cancelled"),
]
VENDOR_RETURN_REASON_CHOICES = [
    ("damaged", "Damaged"), ("rejected", "Rejected"), ("incorrect_item", "Incorrect item"),
    ("wrong_specification", "Wrong specification"), ("excess_delivery", "Excess delivery"),
    ("quality_failure", "Quality failure"), ("warranty", "Warranty"), ("other", "Other"),
]
VENDOR_RETURN_METHOD_CHOICES = [
    ("physical_return", "Physical return"), ("vendor_pickup", "Vendor pickup"),
    ("onsite_disposal", "Onsite disposal"), ("replacement_without_return", "Replacement without return"),
    ("credit_only", "Credit only"), ("other", "Other"),
]


class VendorReturn(SoftDeleteModel):
    return_number = models.CharField(max_length=30, unique=True, db_index=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="vendor_returns")
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="vendor_returns")
    goods_receipt = models.ForeignKey(GoodsReceipt, null=True, blank=True, on_delete=models.PROTECT, related_name="vendor_returns")
    supplier_invoice = models.ForeignKey(SupplierInvoice, null=True, blank=True, on_delete=models.SET_NULL, related_name="vendor_returns")
    status = models.CharField(max_length=30, choices=VENDOR_RETURN_STATUS_CHOICES, default="draft", db_index=True)
    return_date = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=40, choices=VENDOR_RETURN_REASON_CHOICES)
    return_method = models.CharField(max_length=40, choices=VENDOR_RETURN_METHOD_CHOICES)
    authorization_reference = models.CharField(max_length=120, blank=True, default="")
    shipping_reference = models.CharField(max_length=120, blank=True, default="")
    expected_resolution = models.TextField(blank=True, default="")
    replacement_expected = models.BooleanField(default=False)
    replacement_due_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_vendor_returns")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_vendor_returns")
    shipped_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="shipped_vendor_returns")
    completed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="completed_vendor_returns")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.return_number:
            count = VendorReturn.objects.count() + 1
            self.return_number = f"VR-{timezone.now().year}-{count:05d}"
        super().save(*args, **kwargs)


RETURN_DISPOSITION_CHOICES = [
    ("refund", "Refund"), ("credit_note", "Credit note"), ("replacement", "Replacement"),
    ("repair", "Repair"), ("exchange", "Exchange"), ("write_off", "Write off"),
    ("pending_vendor_decision", "Pending vendor decision"),
]
RETURN_CONDITION_CHOICES = [
    ("rejected", "Rejected"), ("damaged", "Damaged"), ("defective", "Defective"),
    ("incorrect", "Incorrect"), ("excess", "Excess"), ("other", "Other"),
]


class VendorReturnLine(models.Model):
    vendor_return = models.ForeignKey(VendorReturn, on_delete=models.CASCADE, related_name="lines")
    goods_receipt_item = models.ForeignKey(GoodsReceiptItem, on_delete=models.PROTECT, related_name="return_lines")
    purchase_order_item = models.ForeignKey(PurchaseOrderItem, on_delete=models.PROTECT, related_name="return_lines")
    asset_receipt_item = models.ForeignKey(ProcurementAssetReceiptItem, null=True, blank=True, on_delete=models.SET_NULL, related_name="return_lines")
    asset = models.ForeignKey(Asset, null=True, blank=True, on_delete=models.SET_NULL, related_name="procurement_return_lines")
    quantity = models.PositiveIntegerField(default=1)
    disposition = models.CharField(max_length=40, choices=RETURN_DISPOSITION_CHOICES, default="pending_vendor_decision")
    condition = models.CharField(max_length=20, choices=RETURN_CONDITION_CHOICES)
    reason = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    inventory_reversed = models.BooleanField(default=False)
    inventory_reversed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]


CREDIT_NOTE_STATUS_CHOICES = [
    ("draft", "Draft"), ("submitted", "Submitted"), ("approved", "Approved"),
    ("applied", "Applied"), ("rejected", "Rejected"), ("cancelled", "Cancelled"),
]


class VendorCreditNote(SoftDeleteModel):
    credit_note_number = models.CharField(max_length=120)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="credit_notes")
    supplier_invoice = models.ForeignKey(SupplierInvoice, on_delete=models.PROTECT, related_name="credit_notes")
    vendor_return = models.ForeignKey(VendorReturn, null=True, blank=True, on_delete=models.SET_NULL, related_name="credit_notes")
    credit_date = models.DateField()
    currency = models.CharField(max_length=10)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    applied_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=CREDIT_NOTE_STATUS_CHOICES, default="draft", db_index=True)
    reason = models.TextField(blank=True, default="")
    external_reference = models.CharField(max_length=120, blank=True, default="")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_credit_notes")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_credit_notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["supplier_invoice", "status"], name="cn_invoice_status_idx")]


class VendorCreditNoteLine(models.Model):
    credit_note = models.ForeignKey(VendorCreditNote, on_delete=models.CASCADE, related_name="lines")
    supplier_invoice_line = models.ForeignKey(SupplierInvoiceLine, null=True, blank=True, on_delete=models.PROTECT, related_name="credit_note_lines")
    description = models.TextField(blank=True, default="")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


FINANCIAL_EVENT_CHOICES = [
    ("invoice_created", "Invoice created"), ("invoice_submitted", "Invoice submitted"),
    ("invoice_matched", "Invoice matched"), ("match_exception_created", "Match exception created"),
    ("match_exception_accepted", "Match exception accepted"), ("invoice_approved", "Invoice approved"),
    ("invoice_rejected", "Invoice rejected"), ("invoice_returned", "Invoice returned"),
    ("payment_hold_added", "Payment hold added"), ("payment_hold_released", "Payment hold released"),
    ("payment_ready", "Payment ready"), ("payment_recorded", "Payment recorded"),
    ("invoice_cancelled", "Invoice cancelled"), ("invoice_closed", "Invoice closed"),
    ("return_created", "Return created"), ("return_approved", "Return approved"),
    ("return_shipped", "Return shipped"), ("replacement_received", "Replacement received"),
    ("return_completed", "Return completed"), ("credit_created", "Credit created"),
    ("credit_approved", "Credit approved"), ("credit_applied", "Credit applied"),
]


class ProcurementFinancialHistory(models.Model):
    invoice = models.ForeignKey(SupplierInvoice, null=True, blank=True, on_delete=models.CASCADE, related_name="financial_history")
    vendor_return = models.ForeignKey(VendorReturn, null=True, blank=True, on_delete=models.CASCADE, related_name="financial_history")
    credit_note = models.ForeignKey(VendorCreditNote, null=True, blank=True, on_delete=models.CASCADE, related_name="financial_history")
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=40, choices=FINANCIAL_EVENT_CHOICES)
    previous_status = models.CharField(max_length=40, blank=True, default="")
    new_status = models.CharField(max_length=40, blank=True, default="")
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["invoice", "created_at"], name="finhist_inv_idx"),
            models.Index(fields=["vendor_return", "created_at"], name="finhist_ret_idx"),
            models.Index(fields=["credit_note", "created_at"], name="finhist_cn_idx"),
        ]
