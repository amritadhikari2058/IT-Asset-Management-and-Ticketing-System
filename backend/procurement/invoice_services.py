"""Invoice workflow and calculation services for Procurement P3."""
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import (
    GoodsReceiptItem, ProcurementFinancialHistory, SupplierInvoice, SupplierInvoiceLine,
    normalize_invoice_number,
)

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def _money(v):
    if v is None:
        return ZERO
    return Decimal(str(v)).quantize(CENT, rounding=ROUND_HALF_UP)


def _q(v):
    if v is None:
        return Decimal("0.00")
    return Decimal(str(v))


def recalculate_invoice_totals(invoice):
    """Server-side recalculation of invoice header and line totals."""
    lines = list(invoice.lines.all())
    subtotal = ZERO
    tax = ZERO
    for line in lines:
        qty = _q(line.invoiced_quantity)
        unit = _money(line.unit_price)
        discount = _money(line.discount_amount)
        line_tax = _money(line.tax_amount)
        line_sub = _money((qty * unit) - discount)
        line_total = _money(line_sub + line_tax + _money(line.freight_allocation) + _money(line.other_charge_allocation))
        if line.line_subtotal != line_sub or line.line_total != line_total:
            line.line_subtotal = line_sub
            line.line_total = line_total
            line.save(update_fields=["line_subtotal", "line_total", "updated_at"])
        subtotal += line_sub
        tax += line_tax
    invoice.subtotal = _money(subtotal)
    invoice.tax_total = _money(tax)
    invoice.grand_total = _money(
        subtotal + _money(invoice.freight_total) + _money(invoice.other_charge_total) + tax - _money(invoice.discount_total)
    )
    invoice.save(update_fields=[
        "subtotal", "tax_total", "grand_total", "updated_at",
    ])
    return invoice


def find_duplicate_invoice(vendor_id, invoice_number, exclude_id=None):
    norm = normalize_invoice_number(invoice_number)
    qs = SupplierInvoice.objects.filter(vendor_id=vendor_id, normalized_invoice_number=norm, is_deleted=False)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


def validate_invoice_for_submit(invoice, actor=None):
    errors = {}
    if not invoice.invoice_number:
        errors["invoice_number"] = "Invoice number is required."
    if not invoice.vendor_id:
        errors["vendor"] = "Vendor is required."
    if not invoice.purchase_order_id:
        errors["purchase_order"] = "Purchase order is required."
    if not invoice.invoice_date:
        errors["invoice_date"] = "Invoice date is required."
    if not invoice.received_date:
        errors["received_date"] = "Received date is required."
    if invoice.due_date and invoice.invoice_date and invoice.due_date < invoice.invoice_date:
        errors["due_date"] = "Due date cannot precede invoice date."
    if invoice.purchase_order_id and invoice.vendor_id:
        if invoice.purchase_order.vendor_id != invoice.vendor_id:
            errors["vendor"] = "Vendor must match the purchase order vendor."
    if invoice.purchase_order_id and invoice.currency:
        if invoice.purchase_order.currency and invoice.currency != invoice.purchase_order.currency:
            # currency mismatch allowed only if explicit authorized exception exists (System Admin flow later)
            # At submit, block unless invoice has pre-authorized flag? spec says "unless an explicit authorized exception exists"
            if not is_system_admin(actor):
                errors["currency"] = "Invoice currency must match purchase order currency unless an authorized exception exists."
    if invoice.grand_total < ZERO:
        errors["grand_total"] = "Grand total cannot be negative."
    if not invoice.lines.exists():
        errors["lines"] = "At least one invoice line is required."

    # duplicate detection
    if invoice.vendor_id and invoice.invoice_number:
        if find_duplicate_invoice(invoice.vendor_id, invoice.invoice_number, exclude_id=invoice.pk):
            errors["invoice_number"] = "An invoice with this number already exists for the selected Vendor."

    # line validations
    for line in invoice.lines.select_related("purchase_order_item", "goods_receipt_item").all():
        if line.purchase_order_item.purchase_order_id != invoice.purchase_order_id:
            errors.setdefault("lines", "One or more lines reference a purchase order item outside this invoice.")
        if line.goods_receipt_item_id:
            if line.goods_receipt_item.goods_receipt.purchase_order_id != invoice.purchase_order_id:
                errors.setdefault("lines", "One or more lines reference a receipt from another purchase order.")
        if _q(line.invoiced_quantity) <= 0:
            errors.setdefault("lines", "Invoiced quantity must be positive.")
        if _money(line.unit_price) < 0:
            errors.setdefault("lines", "Unit price cannot be negative.")
        if _q(line.tax_rate) < 0 or _q(line.tax_rate) > Decimal("100"):
            errors.setdefault("lines", "Tax rate must be within the configured range.")
        # cumulative invoiced cannot exceed ordered unless authorized exception
        prev = SupplierInvoiceLine.objects.filter(
            purchase_order_item=line.purchase_order_item, invoice__is_deleted=False,
        ).exclude(invoice_id=invoice.pk).exclude(invoice__status__in=["cancelled", "rejected"]).aggregate(
            total=Sum("invoiced_quantity")
        ).get("total") or Decimal("0")
        if (_q(prev) + _q(line.invoiced_quantity)) > _q(line.purchase_order_item.quantity):
            if not is_system_admin(actor):
                errors.setdefault("lines", "Cumulative invoiced quantity cannot exceed ordered quantity without authorized exception.")

    return errors


def is_system_admin(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and (getattr(user, "role", "") == "system_admin" or getattr(user, "is_superuser", False))
    )


def is_manager_or_admin(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and (getattr(user, "role", "") in ("system_admin", "it_manager") or getattr(user, "is_superuser", False))
    )


def invoice_high_value_threshold():
    return _money(getattr(settings, "PROCUREMENT_INVOICE_SYSTEM_ADMIN_THRESHOLD", "100000.00"))


def invoice_variance_threshold():
    return _money(getattr(settings, "PROCUREMENT_INVOICE_VARIANCE_SYSTEM_ADMIN_THRESHOLD", "5000.00"))


def invoice_approval_currency():
    return getattr(settings, "PROCUREMENT_INVOICE_APPROVAL_CURRENCY", "NPR")


def requires_system_admin_approval(invoice):
    if invoice.currency != invoice_approval_currency():
        return True
    if abs(_money(invoice.grand_total)) >= invoice_high_value_threshold():
        return True
    # accepted critical variance or high variance amount
    if abs(_money(invoice.variance_total)) >= invoice_variance_threshold():
        return True
    from .models import InvoiceException
    if InvoiceException.objects.filter(
        invoice=invoice, status="accepted", severity="critical"
    ).exists():
        return True
    return False
