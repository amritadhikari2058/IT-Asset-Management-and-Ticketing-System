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
    ("receipt", "Receipt"),
    ("inspection", "Inspection"),
    ("discrepancy", "Discrepancy"),
    ("warranty", "Warranty"),
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
            models.Index(fields=["purchase_request", "status"],
                         name="proc_attach_pr_idx"),
            models.Index(fields=["purchase_order", "status"],
                         name="proc_attach_po_idx"),
        ]

    @property
    def parent(self):
        return (self.purchase_request or self.quotation
                or self.purchase_order or self.goods_receipt)

    def clean(self):
        super().clean()
        parents = [
            self.purchase_request_id, self.quotation_id,
            self.purchase_order_id, self.goods_receipt_id,
        ]
        if sum(1 for p in parents if p) != 1:
            from django.core.exceptions import ValidationError
            raise ValidationError(
                "Exactly one of purchase request, quotation, purchase order, "
                "or goods receipt must be set for an attachment.")

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
