import api from '../api';
import { parseApiError } from '../api-utils';

export const PURCHASE_REQUEST_STATUS_LABELS = {
  draft: 'Draft',
  pending_approval: 'Pending approval',
  approved: 'Approved',
  rejected: 'Rejected',
  returned_for_correction: 'Returned for correction',
  po_generated: 'PO generated',
  cancelled: 'Cancelled',
  closed: 'Closed',
};

export const PURCHASE_ORDER_STATUS_LABELS = {
  draft: 'Draft',
  pending_approval: 'Pending approval',
  approved: 'Approved',
  rejected: 'Rejected',
  sent_to_vendor: 'Sent to vendor',
  partially_received: 'Partially received',
  received: 'Received',
  cancelled: 'Cancelled',
  closed: 'Closed',
};

export const GOODS_RECEIPT_STATUS_LABELS = { recorded: 'Recorded' };
export const APPROVAL_STATUS_LABELS = { '': 'No decision', pending: 'Pending', approved: 'Approved', rejected: 'Rejected', returned: 'Returned for correction' };
export const QUOTATION_STATUS_LABELS = { offered: 'Offered', selected: 'Selected' };
export const ITEM_TYPE_LABELS = { stock: 'Stock item', serialized: 'Serialized asset', other: 'Item' };
export const PROCUREMENT_ASSET_STATUS_LABELS = {
  pending_registration: 'Pending registration',
  registered: 'Registered',
  cancelled: 'Cancelled',
  exception: 'Exception',
  pending: 'Pending registration',
  created: 'Registered',
};

export const SUPPLIER_INVOICE_STATUS_LABELS = {
  draft: 'Draft', submitted: 'Submitted', matching: 'Matching', exception: 'Exception',
  matched: 'Matched', approved: 'Approved', rejected: 'Rejected', cancelled: 'Cancelled',
  payment_ready: 'Payment Ready', paid: 'Paid', closed: 'Closed',
};
export const PAYMENT_STATUS_LABELS = {
  not_ready: 'Not ready', on_hold: 'On hold', ready: 'Ready',
  partially_paid: 'Partially paid', paid: 'Paid', cancelled: 'Cancelled',
};
export const INVOICE_MATCH_STATUS_LABELS = {
  unmatched: 'Unmatched', matched: 'Matched', quantity_variance: 'Quantity variance',
  price_variance: 'Price variance', tax_variance: 'Tax variance', multiple_variances: 'Multiple variances',
  receipt_missing: 'Receipt missing', po_line_missing: 'PO line missing', over_invoiced: 'Over invoiced',
  exception_accepted: 'Exception accepted',
  matched_within_tolerance: 'Matched within tolerance', invalid: 'Invalid', receipt_incomplete: 'Receipt incomplete',
};
export const EXCEPTION_STATUS_LABELS = { open: 'Open', acknowledged: 'Acknowledged', accepted: 'Accepted', resolved: 'Resolved', rejected: 'Rejected', superseded: 'Superseded' };
export const VENDOR_RETURN_STATUS_LABELS = { draft: 'Draft', pending_approval: 'Pending Approval', approved: 'Approved', shipped: 'Shipped', partially_resolved: 'Partially Resolved', resolved: 'Resolved', rejected: 'Rejected', cancelled: 'Cancelled' };
export const CREDIT_NOTE_STATUS_LABELS = { draft: 'Draft', submitted: 'Submitted', approved: 'Approved', applied: 'Applied', rejected: 'Rejected', cancelled: 'Cancelled' };

const STATUS_TONES = {
  draft: 'gray', pending_approval: 'amber', approved: 'green', rejected: 'red',
  returned_for_correction: 'purple', po_generated: 'blue', cancelled: 'gray', closed: 'gray',
  sent_to_vendor: 'blue', partially_received: 'amber', received: 'green', recorded: 'green',
  pending: 'amber', returned: 'purple', selected: 'green', offered: 'gray', created: 'green',
  submitted: 'blue', matching: 'amber', exception: 'red', matched: 'green', payment_ready: 'blue',
  paid: 'green', not_ready: 'gray', on_hold: 'red', ready: 'green', partially_paid: 'amber',
  open: 'red', acknowledged: 'amber', accepted: 'blue', resolved: 'green', superseded: 'gray',
  shipped: 'blue', partially_resolved: 'amber', applied: 'green',
  unmatched: 'gray', matched_within_tolerance: 'green', over_invoiced: 'red', receipt_missing: 'red',
  quantity_variance: 'amber', price_variance: 'amber', tax_variance: 'amber', multiple_variances: 'red',
  exception_accepted: 'blue', invalid: 'red', receipt_incomplete: 'amber',
  pending_registration: 'amber', registered: 'green',
};

export function statusBadgeVariant(status) {
  return STATUS_TONES[String(status ?? '')] ?? 'gray';
}

export function statusLabel(status) {
  const key = String(status ?? '');
  return PURCHASE_REQUEST_STATUS_LABELS[key]
    ?? PURCHASE_ORDER_STATUS_LABELS[key]
    ?? GOODS_RECEIPT_STATUS_LABELS[key]
    ?? SUPPLIER_INVOICE_STATUS_LABELS[key]
    ?? PAYMENT_STATUS_LABELS[key]
    ?? VENDOR_RETURN_STATUS_LABELS[key]
    ?? CREDIT_NOTE_STATUS_LABELS[key]
    ?? EXCEPTION_STATUS_LABELS[key]
    ?? INVOICE_MATCH_STATUS_LABELS[key]
    ?? APPROVAL_STATUS_LABELS[key]
    ?? PROCUREMENT_ASSET_STATUS_LABELS[key]
    ?? (key ? key.replace(/_/g, ' ') : '—');
}

export function itemTypeOf(line) {
  if (!line) return 'other';
  if (line.is_serialized) return 'serialized';
  if (line.stock_item) return 'stock';
  return 'other';
}

export function formatDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString();
}

export function formatDateTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString();
}

export function formatMoney(value, currency) {
  if (value === null || value === undefined || value === '') return '—';
  const raw = String(value).trim();
  const negative = raw.startsWith('-');
  const unsigned = negative ? raw.slice(1) : raw;
  const [whole, fraction = ''] = unsigned.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const decimals = fraction.padEnd(2, '0').slice(0, 2);
  const amount = `${negative ? '-' : ''}${grouped || '0'}.${decimals}`;
  return currency ? `${currency} ${amount}` : amount;
}

export function formatQuantity(value) {
  if (value === null || value === undefined || value === '') return '0';
  return String(value);
}

export function safeResults(data) {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  return Array.isArray(data.results) ? data.results : [];
}

export function normalizePageUrl(url) {
  if (!url) return '';
  return String(url).replace(/^https?:\/\/[^/]+\/api/, '');
}

export async function fetchAll(url, { maxPages = 10 } = {}) {
  const rows = [];
  let next = url;
  let pages = 0;
  while (next && pages < maxPages) {
    const r = await api.get(next);
    rows.push(...safeResults(r.data));
    next = normalizePageUrl(r.data?.next);
    pages += 1;
  }
  return rows;
}

export function queryString(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

export function buildPurchaseRequestListUrl(params = { page_size: 100 }) { return `/procurement/purchase-requests/${queryString(params)}`; }
export function buildPurchaseOrderListUrl(params = { page_size: 100 }) { return `/procurement/purchase-orders/${queryString(params)}`; }
export function buildGoodsReceiptListUrl(params = { page_size: 100 }) { return `/procurement/goods-receipts/${queryString(params)}`; }
export function buildQuotationListUrl(purchaseRequestId) { return `/procurement/quotations/${queryString({ page_size: 100, purchase_request: purchaseRequestId })}`; }
export function buildDashboardUrl(filters = {}) { return `/procurement/dashboard/${queryString(filters)}`; }
export function buildFinancialDashboardUrl(filters = {}) { return `/procurement/financial-dashboard/${queryString(filters)}`; }
export function buildAssetReceiptItemsUrl(params = {}) { return `/procurement/asset-receipt-items/${queryString(params)}`; }
export function buildAttachmentListUrl(parentType, parentId) { return `/procurement/attachments/${queryString({ page_size: 100, [parentType]: parentId })}`; }
export function buildSupplierInvoiceListUrl(params = { page_size: 100 }) { return `/procurement/supplier-invoices/${queryString(params)}`; }
export function buildInvoiceExceptionListUrl(params = { page_size: 100 }) { return `/procurement/invoice-exceptions/${queryString(params)}`; }
export function buildVendorReturnListUrl(params = { page_size: 100 }) { return `/procurement/vendor-returns/${queryString(params)}`; }
export function buildCreditNoteListUrl(params = { page_size: 100 }) { return `/procurement/credit-notes/${queryString(params)}`; }

export const ATTACHMENT_DOCUMENT_TYPES = [
  'requisition', 'specification', 'quotation', 'comparison', 'approval',
  'purchase_order', 'delivery_note', 'invoice', 'supplier_invoice', 'tax_invoice',
  'receipt', 'inspection', 'discrepancy', 'warranty', 'credit_note',
  'return_authorization', 'shipping_document', 'replacement_document', 'payment_evidence', 'other',
];

export function filenameFromContentDisposition(header, fallback = 'download') {
  if (!header) return fallback;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(String(header));
  if (!match) return fallback;
  try { return decodeURIComponent(match[1].trim()); } catch { return match[1].trim() || fallback; }
}

export function parseFieldErrors(error) { return parseApiError(error); }

function dec(value) { const n = Number(value); return Number.isFinite(n) ? n : 0; }
function money(value) { return value.toFixed(2); }
export function calculateDisplaySubtotal(lines, unitKey = 'estimated_unit_price') { return money((lines || []).reduce((sum, line) => sum + dec(line.quantity) * dec(line[unitKey]), 0)); }
export function calculateDisplayTax(lines) { return money((lines || []).reduce((sum, line) => sum + dec(line.tax), 0)); }
export function calculateDisplayDiscount(lines) { return money((lines || []).reduce((sum, line) => sum + dec(line.discount), 0)); }
export function calculateDisplayTotal(lines) { return money(dec(calculateDisplaySubtotal(lines)) + dec(calculateDisplayTax(lines)) - dec(calculateDisplayDiscount(lines))); }
export function estimateRequestTotal(items) { const total = (items || []).reduce((sum, line) => { const lineTotal = dec(line.estimated_total) || (dec(line.quantity) * dec(line.estimated_unit_price)); return sum + lineTotal; }, 0); return total.toFixed(2); }
export function remainingQuantity(line) { if (!line) return 0; const booked = dec(line.received_qty) + dec(line.rejected_qty) + dec(line.damaged_qty); return Math.max(0, dec(line.quantity) - booked); }
export function acceptedQuantity(line) { if (!line) return 0; return Math.max(0, dec(line.quantity_received) - dec(line.quantity_rejected) - dec(line.quantity_damaged)); }
export function receiptSummary(receipt) { const items = receipt?.items || []; return items.reduce((acc, line) => ({ received: acc.received + dec(line.quantity_received), accepted: acc.accepted + acceptedQuantity(line), rejected: acc.rejected + dec(line.quantity_rejected), damaged: acc.damaged + dec(line.quantity_damaged) }), { received: 0, accepted: 0, rejected: 0, damaged: 0 }); }
export function totalsByCurrency(rows, amountKey = 'total', currencyKey = 'currency') { const groups = new Map(); for (const row of rows || []) { const currency = row?.[currencyKey] || '—'; const current = groups.get(currency) || 0; groups.set(currency, current + dec(row?.[amountKey])); } return [...groups.entries()].map(([currency, amount]) => ({ currency, amount: amount.toFixed(2) })); }
export function moneyFor(row, key = 'total') { return formatMoney(row?.[key], row?.currency); }

export function actionAvailability({ request, purchaseOrder, caps, userId } = {}) {
  const c = caps || {};
  const isRequester = !!request && !!userId && request.requester === userId;
  const prStatus = request?.status;
  const poStatus = purchaseOrder?.status;
  const isPoCreator = !!purchaseOrder && !!userId && purchaseOrder.created_by === userId;
  return {
    submitRequest: !!c.canCreatePurchaseRequest && (isRequester || !!c.canApprovePurchaseRequest) && (prStatus === 'draft' || prStatus === 'returned_for_correction'),
    approveRequest: !!c.canApprovePurchaseRequest && prStatus === 'pending_approval' && !isRequester,
    rejectRequest: !!c.canApprovePurchaseRequest && prStatus === 'pending_approval' && !isRequester,
    returnRequest: !!c.canApprovePurchaseRequest && prStatus === 'pending_approval',
    editRequest: !!c.canCreatePurchaseRequest && (prStatus === 'draft' || prStatus === 'returned_for_correction'),
    manageQuotations: !!c.canManageQuotations && prStatus === 'approved',
    selectVendor: !!c.canSelectProcurementVendor && prStatus === 'approved',
    generateOrder: !!c.canCreatePurchaseOrder && prStatus === 'approved',
    approveOrder: !!c.canApprovePurchaseOrder && poStatus === 'pending_approval' && !isPoCreator,
    rejectOrder: !!c.canApprovePurchaseOrder && poStatus === 'pending_approval' && !isPoCreator,
    issueOrder: !!c.canIssuePurchaseOrder && poStatus === 'approved',
    createReceipt: !!c.canCreateGoodsReceipt && ['sent_to_vendor', 'partially_received', 'approved'].includes(poStatus),
  };
}

export function procurementCapabilities(auth) {
  const role = auth?.role;
  // Inactive accounts fail closed when the auth payload exposes active state.
  const inactive = auth?.user?.is_active === false;
  const isSystemAdmin = !inactive && (!!auth?.isSystemAdmin || role === 'system_admin' || !!auth?.isSuperuser);
  const isManager = !inactive && (!!auth?.isITManager || role === 'it_manager');
  const isSupport = !inactive && (!!auth?.isITSupport || role === 'it_support');
  const isKnownStaff = !inactive && (isSystemAdmin || isManager || isSupport);
  const financialControls = isSystemAdmin || isManager;
  return {
    canViewProcurement: isKnownStaff,
    canCreatePurchaseRequest: isKnownStaff,
    canApprovePurchaseRequest: financialControls,
    canManageQuotations: isKnownStaff,
    canSelectProcurementVendor: financialControls,
    canCreatePurchaseOrder: financialControls,
    canApprovePurchaseOrder: financialControls,
    canIssuePurchaseOrder: financialControls,
    canCreateGoodsReceipt: isKnownStaff,
    canPostGoodsReceipt: isKnownStaff,
    canRegisterProcurementAssets: isKnownStaff,
    canViewProcurementReports: financialControls,
    canManageProcurementFinance: financialControls,
    canApproveSupplierInvoice: financialControls,
    canMarkSupplierInvoicePaymentReady: financialControls,
    canRecordSupplierInvoicePayment: financialControls,
    canRecordPayment: financialControls,
    canApproveVendorReturn: financialControls,
    canApproveVendorCreditNote: financialControls,
    canAcceptInvoiceException: financialControls,
    canManageFinancialControls: financialControls,
  };
}

const FINANCIAL_TERMINAL = ['paid', 'closed', 'cancelled'];

/** Action availability mirrored from the backend P3 viewsets. UX only. */
export function invoiceActionState(invoice, caps = {}, userId) {
  const c = caps || {};
  const status = invoice?.status;
  const isCreator = !!invoice && userId !== undefined && invoice.created_by === userId;
  const financial = !!c.canManageProcurementFinance;
  const settled = FINANCIAL_TERMINAL.includes(status);
  return {
    canSubmit: status === 'draft',
    canMatch: !!c.canViewProcurement && !['paid', 'closed', 'cancelled', 'rejected'].includes(status),
    canApprove: financial && !isCreator && ['matched', 'exception'].includes(status),
    canReject: financial && !settled,
    canReturnForCorrection: financial && !settled,
    canPlaceHold: financial && !settled,
    canReleaseHold: financial && !!invoice?.payment_hold,
    canMarkPaymentReady: financial && status === 'approved',
    canRecordPayment: financial && status === 'payment_ready' && invoice?.payment_status === 'ready',
    canCancel: financial && !['paid', 'closed'].includes(status),
    canClose: financial && status === 'paid',
    canAddLine: status === 'draft',
    isCreator,
  };
}

export function vendorReturnActionState(vendorReturn, caps = {}, userId, isSystemAdmin = false) {
  const c = caps || {};
  const status = vendorReturn?.status;
  const isCreator = !!vendorReturn && userId !== undefined && vendorReturn.created_by === userId;
  const financial = !!c.canApproveVendorReturn;
  return {
    canSubmit: status === 'draft',
    canApprove: financial && status === 'pending_approval' && (!isCreator || !!isSystemAdmin),
    canReject: financial && ['pending_approval', 'approved'].includes(status),
    canShip: financial && status === 'approved',
    canRecordReplacement: financial && ['shipped', 'partially_resolved'].includes(status),
    canComplete: financial && ['approved', 'shipped', 'partially_resolved'].includes(status),
    canCancel: financial && !['resolved', 'shipped'].includes(status),
    canAddLine: status === 'draft',
    isCreator,
  };
}

export function vendorCreditNoteActionState(creditNote, caps = {}, userId, isSystemAdmin = false) {
  const c = caps || {};
  const status = creditNote?.status;
  const isCreator = !!creditNote && userId !== undefined && creditNote.created_by === userId;
  const financial = !!c.canApproveVendorCreditNote;
  return {
    canSubmit: status === 'draft',
    canApprove: financial && status === 'submitted' && (!isCreator || !!isSystemAdmin),
    canReject: financial && !['applied', 'cancelled'].includes(status),
    canApply: financial && status === 'approved',
    canCancel: financial && status !== 'applied',
    isCreator,
  };
}

const PERMISSION_DENIED = 'You do not have permission to perform this action.';
const RECORD_UNAVAILABLE = 'This Procurement record is unavailable or you no longer have access.';

export function procurementErrorText(error, fallback = 'Request failed.') {
  const status = error?.response?.status;
  if (status === 403) return PERMISSION_DENIED;
  if (status === 404) return RECORD_UNAVAILABLE;
  const parsed = parseFieldErrors(error);
  if (parsed?.global) return parsed.global;
  const fieldMessages = Object.entries(parsed?.fields || {}).map(([field, msg]) => `${field.replace(/_/g, ' ')}: ${msg}`);
  return fieldMessages.length ? fieldMessages.join(' ') : fallback;
}

export function recordConflictText(recordType) {
  return `This ${recordType} changed while you were working. The latest version has been loaded.`;
}

export function procurementOverview({ requests = [], orders = [], receipts = [] } = {}) {
  const discrepancies = [];
  for (const receipt of receipts) {
    for (const line of receipt.items || []) {
      if (dec(line.quantity_rejected) > 0 || dec(line.quantity_damaged) > 0) discrepancies.push({ receipt, line });
    }
  }
  const units = (rows, key) => rows.reduce((sum, row) => sum + dec(row[key]), 0);
  return {
    draftRequests: requests.filter((r) => r.status === 'draft').length,
    pendingRequestApprovals: requests.filter((r) => r.status === 'pending_approval').length,
    pendingOrderApprovals: orders.filter((o) => o.status === 'pending_approval').length,
    issuedOrders: orders.filter((o) => ['sent_to_vendor', 'partially_received'].includes(o.status)).length,
    partiallyReceived: orders.filter((o) => o.status === 'partially_received').length,
    discrepancies: discrepancies.length,
    requests: requests.length,
    orders: orders.length,
    receipts: receipts.length,
    orderedUnits: units(orders.flatMap((o) => o.items || []), 'quantity'),
    acceptedUnits: units(receipts.flatMap((r) => r.items || []), 'quantity_received'),
  };
}
