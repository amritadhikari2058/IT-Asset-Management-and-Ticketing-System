from django.db import models
from django.utils import timezone
from django.conf import settings
from accounts.models import User, Department
from assets.models import Vendor


class StockItem(models.Model):
    UNIT_CHOICES = [
        ("pcs", "Pieces"),
        ("box", "Box"),
        ("set", "Set"),
        ("unit", "Unit"),
        ("meter", "Meter"),
        ("other", "Other"),
    ]
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    sku = models.CharField(max_length=80, unique=True, db_index=True)
    category = models.CharField(max_length=80, blank=True, default="")
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default="pcs")
    quantity = models.IntegerField(default=0)
    reserved = models.IntegerField(default=0)
    reorder_threshold = models.IntegerField(default=0)
    preferred_vendor = models.ForeignKey(Vendor, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_items")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_items_deleted")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["is_active", "is_deleted"]), models.Index(fields=["category"])]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    @property
    def available(self):
        return self.quantity - self.reserved

    def soft_delete(self, by_user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = by_user
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])


class StockMovement(models.Model):
    TYPE_CHOICES = [
        ("receive", "Receive"),
        ("issue", "Issue"),
        ("return", "Return"),
        ("adjustment", "Adjustment"),
        ("damage", "Damaged"),
        ("lost", "Lost"),
        ("correction", "Correction"),
        ("reservation", "Reservation"),
        ("release", "Reservation Release"),
    ]
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_index=True)
    quantity = models.IntegerField()
    previous_balance = models.IntegerField()
    new_balance = models.IntegerField()
    employee = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_movements")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_movements")
    reference = models.CharField(max_length=120, blank=True, default="")
    source_request = models.ForeignKey("services.ServiceRequest", null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_movements")
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="recorded_stock_movements")
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["stock_item", "created_at"]), models.Index(fields=["movement_type", "created_at"])]


class StockReservation(models.Model):
    STATUS_CHOICES = [("active", "Active"), ("released", "Released"), ("fulfilled", "Fulfilled")]
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="reservations")
    quantity = models.PositiveIntegerField()
    service_request = models.ForeignKey("services.ServiceRequest", on_delete=models.CASCADE, related_name="stock_reservations")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active", db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_stock_reservations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class PurchaseReceipt(models.Model):
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="purchase_receipts")
    purchase_reference = models.CharField(max_length=120, blank=True, default="")
    invoice_number = models.CharField(max_length=120, blank=True, default="")
    purchase_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    received_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="received_purchases")
    notes = models.TextField(blank=True, default="")
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class PurchaseReceiptLine(models.Model):
    receipt = models.ForeignKey(PurchaseReceipt, on_delete=models.CASCADE, related_name="lines")
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="receipt_lines")
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
