"""Three-way matching and payment-readiness services for Procurement P3."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db.models import Q, Sum
from django.utils import timezone

from .models import (
    GoodsReceiptItem, InvoiceException, InvoiceMatchResult, ProcurementFinancialHistory,
    PurchaseOrderItem, SupplierInvoice, SupplierInvoiceLine, VendorCreditNote,
    VendorReturn, VendorReturnLine, normalize_invoice_number,
)

ZERO = Decimal("0.00")
QTY_ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def _d(value):
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q(value):
    if value is None:
        return QTY_ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _money(value):
    return _d(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _pct(part, whole):
    if not whole:
        return None
    try:
        return (_d(part) / _d(whole)) * Decimal("100")
    except Exception:
        return None


def _setting(name, default):
    return getattr(settings, name, default)


def tolerance_snapshot():
    return {
        "price_variance_percent": str(_d(_setting("PROCUREMENT_PRICE_VARIANCE_PERCENT", "2.00"))),
        "quantity_variance_percent": str(_d(_setting("PROCUREMENT_QUANTITY_VARIANCE_PERCENT", "0.00"))),
        "total_variance_percent": str(_d(_setting("PROCUREMENT_TOTAL_VARIANCE_PERCENT", "2.00"))),
        "absolute_variance_amount": str(_d(_setting("PROCUREMENT_ABSOLUTE_VARIANCE_AMOUNT", "0.00"))),
    }


def _within_tolerance(variance, base, percent_key, absolute_key="PROCUREMENT_ABSOLUTE_VARIANCE_AMOUNT"):
    tol_pct = _d(_setting(percent_key, "0.00"))
    tol_abs = _d(_setting(absolute_key, "0.00"))
    abs_var = abs(_d(variance))
    if abs_var <= tol_abs:
        return True
    if base:
        try:
            if (abs_var / abs(_d(base))) * Decimal("100") <= tol_pct:
                return True
        except Exception:
            pass
    return abs_var == ZERO


def _exception_fingerprint(invoice, line, exc_type):
    base = f"{invoice.pk}:{getattr(line,'pk',0) or 0}:{exc_type}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _open_blocking_severity(exception_type, outside_tolerance):
    # high/critical require elevated acceptance; treat outside-tolerance variances as high
    if exception_type in ("over_invoiced", "receipt_missing", "duplicate_invoice",
                          "rejected_goods_invoiced", "damaged_goods_invoiced",
                          "invalid_total", "currency_mismatch", "po_line_missing"):
        return "critical" if exception_type in ("duplicate_invoice", "invalid_total", "currency_mismatch") else "high"
    if outside_tolerance:
        return "high"
    return "medium"


def supersede_open_exceptions(invoice):
    InvoiceException.objects.filter(
        invoice=invoice, status__in=["open", "acknowledged"]
    ).update(status="superseded", updated_at=timezone.now())


def _ensure_exception(invoice, line, exc_type, severity, expected, actual, variance, variance_pct, reason):
    fp = _exception_fingerprint(invoice, line, exc_type)
    existing = InvoiceException.objects.filter(
        invoice=invoice, fingerprint=fp, status__in=["open", "acknowledged", "accepted"]
    ).first()
    if existing:
        # update values if still open/ack; keep accepted as-is but refresh numbers
        if existing.status in ("open", "acknowledged"):
            existing.severity = severity
            existing.expected_value = _money(expected) if expected is not None else None
            existing.actual_value = _money(actual) if actual is not None else None
            existing.variance = _money(variance) if variance is not None else None
            existing.variance_percent = _d(variance_pct).quantize(Decimal("0.0001")) if variance_pct is not None else None
            existing.reason = reason or existing.reason
            existing.save()
        return existing, False
    exc = InvoiceException.objects.create(
        invoice=invoice,
        invoice_line=line,
        exception_type=exc_type,
        severity=severity,
        status="open",
        expected_value=_money(expected) if expected is not None else None,
        actual_value=_money(actual) if actual is not None else None,
        variance=_money(variance) if variance is not None else None,
        variance_percent=_d(variance_pct).quantize(Decimal("0.0001")) if variance_pct is not None else None,
        reason=reason or "",
        fingerprint=fp,
    )
    return exc, True


def _accepted_received_for_po_line(po_line, exclude_goods_receipt_item_ids=None):
    qs = GoodsReceiptItem.objects.filter(
        purchase_order_item=po_line, goods_receipt__is_deleted=False
    )
    if exclude_goods_receipt_item_ids:
        qs = qs.exclude(pk__in=exclude_goods_receipt_item_ids)
    totals = qs.aggregate(
        accepted=Sum("accepted_quantity"),
        rejected=Sum("quantity_rejected"),
        damaged=Sum("quantity_damaged"),
    )
    return {
        "accepted": _q(totals.get("accepted") or 0),
        "rejected": _q(totals.get("rejected") or 0),
        "damaged": _q(totals.get("damaged") or 0),
    }


def _previous_invoiced_for_po_line(po_line, exclude_invoice_id=None, exclude_line_id=None):
    qs = SupplierInvoiceLine.objects.filter(
        purchase_order_item=po_line,
        invoice__is_deleted=False,
    ).exclude(invoice__status__in=["cancelled", "rejected"])
    if exclude_invoice_id:
        qs = qs.exclude(invoice_id=exclude_invoice_id)
    if exclude_line_id:
        qs = qs.exclude(pk=exclude_line_id)
    return _q(qs.aggregate(total=Sum("invoiced_quantity")).get("total") or 0)


def evaluate_invoice_match(invoice, actor=None):
    """Deterministic three-way match. Creates immutable snapshot and exceptions."""
    invoice = SupplierInvoice.objects.select_related("purchase_order", "vendor").get(pk=invoice.pk)
    lines = list(
        invoice.lines.select_related(
            "purchase_order_item", "goods_receipt_item", "goods_receipt_item__goods_receipt"
        ).all()
    )
    po = invoice.purchase_order
    tol = tolerance_snapshot()

    # supersede previous open/ack exceptions (accepted retained via fingerprint logic below)
    InvoiceException.objects.filter(invoice=invoice, status__in=["open", "acknowledged"]).update(
        status="superseded", updated_at=timezone.now()
    )

    line_details = []
    overall = "matched"
    totals = {
        "po_total": ZERO, "accepted_receipt_total": ZERO, "invoice_total": ZERO,
        "qty_var": ZERO, "price_var": ZERO, "tax_var": ZERO, "total_var": ZERO,
    }
    has_exception = False
    receipt_incomplete = False
    over_invoiced = False

    for line in lines:
        po_item = line.purchase_order_item
        ordered_qty = _q(po_item.quantity)
        po_unit = _money(po_item.unit_price)
        po_tax = _money(po_item.tax)
        invoiced_qty = _q(line.invoiced_quantity)
        inv_unit = _money(line.unit_price)
        inv_tax = _money(line.tax_amount)
        prev_invoiced = _previous_invoiced_for_po_line(po_item, exclude_invoice_id=invoice.pk, exclude_line_id=line.pk)
        remaining_to_invoice = ordered_qty - prev_invoiced

        recv = _accepted_received_for_po_line(po_item)
        accepted_qty = recv["accepted"]
        remaining_unreceived = max(QTY_ZERO, ordered_qty - accepted_qty)
        remaining_uninvoiced = max(QTY_ZERO, remaining_to_invoice)

        # snapshot accepted qty for traceability
        line.accepted_quantity_snapshot = accepted_qty

        qty_var = invoiced_qty - min(invoiced_qty, accepted_qty)
        # quantity variance relative to accepted received for this invoice context
        qty_variance_amount = _q(invoiced_qty - accepted_qty)
        price_var = _money((inv_unit - po_unit) * invoiced_qty)
        tax_var = _money(inv_tax - po_tax) if inv_tax or po_tax else ZERO
        # line expected = po_unit*invoiced_qty + po_tax proportion? simpler: compare line totals
        expected_line_total = _money((po_unit * invoiced_qty) + po_tax - _money(line.discount_amount))
        total_var = _money(line.line_total - expected_line_total)

        line.quantity_variance = qty_variance_amount
        line.price_variance = price_var
        line.tax_variance = tax_var
        line.total_variance = total_var

        variances = []
        line_status = "matched"
        outside = False

        # receipt missing/incomplete
        if accepted_qty <= QTY_ZERO and invoiced_qty > QTY_ZERO:
            variances.append("receipt_missing")
            exc, created = _ensure_exception(
                invoice, line, "receipt_missing", "high",
                accepted_qty, invoiced_qty, invoiced_qty, None,
                "No accepted receipt quantity available for this line."
            )
            if created:
                has_exception = True
            line_status = "receipt_missing"
            receipt_incomplete = True
            outside = True
        else:
            # over-invoiced vs ordered (cumulative)
            if (prev_invoiced + invoiced_qty) > ordered_qty:
                variances.append("over_invoiced")
                exc, _ = _ensure_exception(
                    invoice, line, "over_invoiced", "high",
                    ordered_qty, prev_invoiced + invoiced_qty,
                    (prev_invoiced + invoiced_qty) - ordered_qty,
                    _pct((prev_invoiced + invoiced_qty) - ordered_qty, ordered_qty),
                    "Cumulative invoiced quantity exceeds ordered quantity."
                )
                has_exception = True
                over_invoiced = True
                outside = True
            # qty variance vs accepted
            if invoiced_qty > accepted_qty and "over_invoiced" not in variances and "receipt_missing" not in variances:
                variances.append("quantity_variance")
                outside_q = not _within_tolerance(invoiced_qty - accepted_qty, accepted_qty or ordered_qty, "PROCUREMENT_QUANTITY_VARIANCE_PERCENT")
                exc, _ = _ensure_exception(
                    invoice, line, "quantity_variance",
                    _open_blocking_severity("quantity_variance", outside_q),
                    accepted_qty, invoiced_qty, invoiced_qty - accepted_qty,
                    _pct(invoiced_qty - accepted_qty, accepted_qty or ordered_qty),
                    "Invoiced quantity differs from accepted receipt quantity."
                )
                has_exception = True
                if outside_q:
                    outside = True
            # price variance
            if price_var != ZERO:
                variances.append("price_variance")
                outside_p = not _within_tolerance(price_var, (po_unit * invoiced_qty) or po_unit or ZERO, "PROCUREMENT_PRICE_VARIANCE_PERCENT")
                exc, _ = _ensure_exception(
                    invoice, line, "price_variance",
                    _open_blocking_severity("price_variance", outside_p),
                    po_unit, inv_unit, inv_unit - po_unit,
                    _pct(inv_unit - po_unit, po_unit) if po_unit else None,
                    "Invoice unit price differs from purchase order unit price."
                )
                has_exception = True
                if outside_p:
                    outside = True
            # tax variance
            if tax_var != ZERO:
                variances.append("tax_variance")
                outside_t = not _within_tolerance(tax_var, po_tax or inv_tax or ZERO, "PROCUREMENT_TOTAL_VARIANCE_PERCENT")
                exc, _ = _ensure_exception(
                    invoice, line, "tax_variance",
                    _open_blocking_severity("tax_variance", outside_t),
                    po_tax, inv_tax, tax_var,
                    _pct(tax_var, po_tax) if po_tax else None,
                    "Invoice tax differs from purchase order tax."
                )
                has_exception = True
                if outside_t:
                    outside = True
            # rejected/damaged invoiced check: if invoicing against specific receipt item with rejected/damaged
            if line.goods_receipt_item_id:
                gri = line.goods_receipt_item
                rej = _q(gri.quantity_rejected)
                dmg = _q(gri.quantity_damaged)
                if rej > 0 and invoiced_qty > _q(gri.accepted_quantity):
                    exc, _ = _ensure_exception(
                        invoice, line, "rejected_goods_invoiced", "high",
                        _q(gri.accepted_quantity), invoiced_qty, invoiced_qty - _q(gri.accepted_quantity),
                        None, "Rejected goods are not payable by default."
                    )
                    has_exception = True
                    outside = True
                if dmg > 0 and invoiced_qty > _q(gri.accepted_quantity):
                    exc, _ = _ensure_exception(
                        invoice, line, "damaged_goods_invoiced", "high",
                        _q(gri.accepted_quantity), invoiced_qty, invoiced_qty - _q(gri.accepted_quantity),
                        None, "Damaged goods are not payable by default."
                    )
                    has_exception = True
                    outside = True

            if "over_invoiced" in variances:
                line_status = "over_invoiced"
            elif not variances:
                # check tolerance on total
                outside_total = not _within_tolerance(total_var, expected_line_total or line.line_total or ZERO, "PROCUREMENT_TOTAL_VARIANCE_PERCENT")
                if total_var != ZERO and outside_total:
                    variances.append("price_variance")
                    exc, _ = _ensure_exception(
                        invoice, line, "price_variance", "high",
                        expected_line_total, line.line_total, total_var,
                        _pct(total_var, expected_line_total) if expected_line_total else None,
                        "Line total differs outside tolerance."
                    )
                    has_exception = True
                    outside = True
                    line_status = "price_variance"
                elif total_var != ZERO and not outside_total:
                    line_status = "matched"
                else:
                    line_status = "matched"
            elif len(variances) > 1:
                line_status = "multiple_variances"
            else:
                line_status = variances[0] if variances[0] in dict(SupplierInvoiceLine._meta.get_field("match_status").choices) else "unmatched"

        # if any accepted exception exists for this fingerprint set, allow exception_accepted display
        # (kept as match_status exception_accepted only when all open resolved/accepted)
        line.match_status = line_status
        line.matched_quantity = min(invoiced_qty, accepted_qty)
        line.save()

        totals["po_total"] += _money(po_unit * ordered_qty)
        totals["accepted_receipt_total"] += _money(po_unit * accepted_qty)
        totals["invoice_total"] += _money(line.line_total)
        totals["qty_var"] += _money(qty_variance_amount)
        totals["price_var"] += _money(price_var)
        totals["tax_var"] += _money(tax_var)
        totals["total_var"] += _money(total_var)

        line_details.append({
            "invoice_line_id": line.pk,
            "purchase_order_item_id": po_item.pk,
            "ordered_quantity": str(ordered_qty),
            "accepted_received_quantity": str(accepted_qty),
            "previously_invoiced_quantity": str(prev_invoiced),
            "current_invoiced_quantity": str(invoiced_qty),
            "remaining_uninvoiced_quantity": str(remaining_uninvoiced),
            "remaining_unreceived_quantity": str(remaining_unreceived),
            "po_unit_price": str(po_unit),
            "invoice_unit_price": str(inv_unit),
            "po_tax": str(po_tax),
            "invoice_tax": str(inv_tax),
            "quantity_variance": str(qty_variance_amount),
            "price_variance": str(price_var),
            "tax_variance": str(tax_var),
            "total_variance": str(total_var),
            "match_status": line.match_status,
            "variances": variances,
            "within_tolerance": not outside,
        })

    # determine overall status
    if over_invoiced:
        overall = "over_invoiced"
    elif receipt_incomplete:
        overall = "receipt_incomplete"
    elif has_exception:
        # if any exception outside tolerance -> exception; else matched_within_tolerance
        any_blocking_open = InvoiceException.objects.filter(
            invoice=invoice, status="open"
        ).exclude(severity="info").exists()
        overall = "exception" if any_blocking_open else "matched_within_tolerance"
    else:
        overall = "matched"

    # handle currency mismatch exception at invoice level
    if po.currency and invoice.currency and po.currency != invoice.currency:
        _ensure_exception(
            invoice, None, "currency_mismatch", "critical",
            None, None, None, None,
            f"Invoice currency {invoice.currency} does not match PO currency {po.currency}."
        )
        overall = "exception"

    # invalid total
    calc_subtotal = sum((_money(l.line_subtotal) for l in lines), ZERO)
    calc_tax = sum((_money(l.tax_amount) for l in lines), ZERO)
    calc_grand = _money(calc_subtotal + _money(invoice.freight_total) + _money(invoice.other_charge_total) + calc_tax - _money(invoice.discount_total))
    if abs(_money(invoice.grand_total) - calc_grand) > CENT:
        _ensure_exception(
            invoice, None, "invalid_total", "critical",
            calc_grand, invoice.grand_total, _money(invoice.grand_total - calc_grand), None,
            "Invoice grand total does not match calculated line totals."
        )
        overall = "exception"

    prev = invoice.match_results.order_by("-match_version").first()
    version = (prev.match_version + 1) if prev else 1
    detail = {
        "lines": line_details,
        "tolerance": tol,
        "overall_status": overall,
    }
    checksum = hashlib.sha256(
        json.dumps(detail, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    result = InvoiceMatchResult.objects.create(
        invoice=invoice,
        match_version=version,
        overall_status=overall,
        po_total_snapshot=_money(totals["po_total"]),
        accepted_receipt_total_snapshot=_money(totals["accepted_receipt_total"]),
        invoice_total_snapshot=_money(totals["invoice_total"]),
        quantity_variance_total=_money(totals["qty_var"]),
        price_variance_total=_money(totals["price_var"]),
        tax_variance_total=_money(totals["tax_var"]),
        total_variance=_money(totals["total_var"]),
        tolerance_snapshot=tol,
        matched_by=actor if getattr(actor, "pk", None) else None,
        detail={"line_count": len(line_details), "overall_status": overall},
        checksum=checksum,
    )
    # store full line detail in JSON? detail field bounded - keep summary; full in snapshot already bounded enough
    result.detail = detail
    result.save(update_fields=["detail"])

    # update invoice aggregates
    invoice.matched_subtotal = _money(sum((_money(l.matched_quantity) * _money(l.unit_price) for l in lines), ZERO))
    invoice.variance_total = _money(totals["total_var"])
    # status transition based on result
    if overall in ("matched", "matched_within_tolerance"):
        invoice.status = "matched"
    else:
        invoice.status = "exception"
    invoice.version = (invoice.version or 1) + 1
    invoice.save()

    # history
    ProcurementFinancialHistory.objects.create(
        invoice=invoice, actor=actor if getattr(actor, "pk", None) else None,
        event_type="invoice_matched",
        previous_status="", new_status=invoice.status,
        detail={"overall_status": overall, "match_version": version},
    )
    # log created exceptions as events (summary)
    new_exc_count = InvoiceException.objects.filter(invoice=invoice, status="open").count()
    if new_exc_count:
        ProcurementFinancialHistory.objects.create(
            invoice=invoice, actor=actor if getattr(actor, "pk", None) else None,
            event_type="match_exception_created",
            previous_status="", new_status=invoice.status,
            detail={"open_exceptions": new_exc_count},
        )

    return result


def evaluate_payment_readiness(invoice):
    """Return blockers for payment readiness (backend authoritative)."""
    invoice = SupplierInvoice.objects.select_related("purchase_order", "vendor").get(pk=invoice.pk)
    blockers = []

    def add(code, message, severity="high"):
        blockers.append({"code": code, "message": message, "severity": severity})

    if invoice.status == "cancelled":
        add("CANCELLED", "Invoice is cancelled.", "critical")
    if invoice.status not in ("approved", "payment_ready", "paid", "closed"):
        if invoice.status in ("draft", "submitted", "matching"):
            add("NOT_MATCHED", "Invoice has not been matched.", "high")
        if invoice.status == "exception":
            add("UNRESOLVED_EXCEPTION", "Invoice has match exceptions.", "high")
        if invoice.status == "rejected":
            add("REJECTED", "Invoice is rejected.", "critical")
    if invoice.payment_hold:
        add("PAYMENT_HOLD", "Invoice is on payment hold.", "high")
    if invoice.approved_by_id is None and invoice.status not in ("paid", "closed", "cancelled"):
        add("APPROVAL_PENDING", "Invoice approval is pending.", "high")

    # currency mismatch
    if invoice.purchase_order_id and invoice.currency != invoice.purchase_order.currency:
        add("CURRENCY_MISMATCH", "Invoice currency does not match purchase order currency.", "critical")

    # latest match
    latest = invoice.match_results.order_by("-match_version").first()
    if not latest:
        if not any(b["code"] == "NOT_MATCHED" for b in blockers):
            add("NOT_MATCHED", "No match result exists.", "high")
    else:
        if latest.overall_status in ("exception", "over_invoiced", "receipt_incomplete", "invalid", "unmatched"):
            if not any(b["code"] in ("UNRESOLVED_EXCEPTION", "NOT_MATCHED") for b in blockers):
                add("MATCH_EXCEPTION", f"Latest match status: {latest.overall_status}.", "high")

    # open blocking exceptions
    open_excs = InvoiceException.objects.filter(invoice=invoice, status="open")
    for exc in open_excs:
        code_map = {
            "quantity_variance": "UNRESOLVED_QUANTITY_VARIANCE",
            "price_variance": "UNRESOLVED_PRICE_VARIANCE",
            "tax_variance": "UNRESOLVED_TAX_VARIANCE",
            "over_invoiced": "OVER_INVOICED",
            "receipt_missing": "MISSING_GOODS_RECEIPT",
            "duplicate_invoice": "DUPLICATE_RISK",
            "rejected_goods_invoiced": "REJECTED_GOODS_INVOICED",
            "damaged_goods_invoiced": "DAMAGED_GOODS_INVOICED",
            "currency_mismatch": "CURRENCY_MISMATCH",
            "invalid_total": "INVALID_TOTAL",
        }
        code = code_map.get(exc.exception_type, "UNRESOLVED_EXCEPTION")
        if not any(b["code"] == code for b in blockers):
            add(code, exc.reason or exc.get_exception_type_display(), exc.severity)

    # missing receipt (any line with no accepted receipt)
    for line in invoice.lines.select_related("goods_receipt_item", "purchase_order_item").all():
        if not line.goods_receipt_item_id and _q(line.invoiced_quantity) > 0:
            # check if PO line has accepted receipts at all
            accepted = _accepted_received_for_po_line(line.purchase_order_item)["accepted"]
            if accepted <= QTY_ZERO:
                if not any(b["code"] == "MISSING_GOODS_RECEIPT" for b in blockers):
                    add("MISSING_GOODS_RECEIPT", "One or more invoice lines have no accepted receipt.", "high")
                break
        # incomplete receipt: accepted < ordered for referenced line and invoiced expects more?
        po_item = line.purchase_order_item
        recv = _accepted_received_for_po_line(po_item)
        if recv["accepted"] < _q(po_item.quantity):
            # not necessarily blocking if invoiced within accepted, but spec lists "incomplete receipt"
            if _q(line.invoiced_quantity) > recv["accepted"]:
                if not any(b["code"] == "INCOMPLETE_RECEIPT" for b in blockers):
                    add("INCOMPLETE_RECEIPT", "Receipt is incomplete for invoiced quantity.", "medium")

    # vendor return / credit pending
    pending_returns = VendorReturn.objects.filter(
        supplier_invoice=invoice, status__in=["draft", "pending_approval", "approved", "shipped"]
    ).exists()
    if pending_returns:
        add("VENDOR_RETURN_PENDING", "A related vendor return is pending resolution.", "high")
    pending_credits = VendorCreditNote.objects.filter(
        supplier_invoice=invoice, status__in=["draft", "submitted"]
    ).exists()
    if pending_credits:
        add("CREDIT_NOTE_PENDING", "A related credit note is pending.", "medium")

    # dedupe by code keeping first
    seen = set()
    unique = []
    for b in blockers:
        if b["code"] in seen:
            continue
        seen.add(b["code"])
        unique.append(b)
    return {"ready": len(unique) == 0, "blockers": unique}


def record_financial_event(*, invoice=None, vendor_return=None, credit_note=None,
                           actor=None, event_type, previous_status="", new_status="", detail=None):
    safe_detail = detail or {}
    # ensure no secrets
    for k in list(safe_detail.keys()):
        lk = str(k).lower()
        if any(s in lk for s in ("password", "token", "secret", "bank", "card", "credential")):
            safe_detail[k] = "[redacted]"
    return ProcurementFinancialHistory.objects.create(
        invoice=invoice, vendor_return=vendor_return, credit_note=credit_note,
        actor=actor if getattr(actor, "pk", None) else None,
        event_type=event_type,
        previous_status=previous_status or "",
        new_status=new_status or "",
        detail=safe_detail,
    )


def run_three_way_match(invoice, actor=None, expected_version=None):
    """Public orchestration wrapper expected by views/tests."""
    # expected_version is validated/handled by caller when needed.
    return evaluate_invoice_match(invoice, actor=actor)


compute_payment_readiness = evaluate_payment_readiness
