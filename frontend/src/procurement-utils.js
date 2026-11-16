import api from './api';
import { parseApiError } from './api-utils';

/**
 * Procurement value maps and helpers.
 *
 * Every label/status here mirrors what `backend/procurement/models.py`
 * actually stores. Values are kept as a single source of truth so a status
 * added on the backend is labelled consistently across every page.
 */

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

/** Goods receipts are recorded on creation — there is no separate status
 *  column on the model, so the UI states the single real state. */
export const GOODS_RECEIPT_STATUS_LABELS = {
  recorded: 'Recorded',
};

export const APPROVAL_STATUS_LABELS = {
  '': 'No decision',
  pending: 'Pending',
  approved: 'Approved',
  rejected: 'Rejected',
  returned: 'Returned for correction',
};

export const QUOTATION_STATUS_LABELS = {
  offered: 'Offered',
  selected: 'Selected',
};

/** PO lines are typed by the two structural flags the backend stores. */
export const ITEM_TYPE_LABELS = {
  stock: 'Stock item',
  serialized: 'Serialized asset',
  other: 'Item',
};

export const ASSET_RECEIPT_STATUS_LABELS = {
  pending: 'Pending registration',
  created: 'Registered',
};

const STATUS_TONES = {
  draft: 'gray',
  pending_approval: 'amber',
  approved: 'green',
  rejected: 'red',
  returned_for_correction: 'purple',
  po_generated: 'blue',
  cancelled: 'gray',
  closed: 'gray',
  sent_to_vendor: 'blue',
  partially_received: 'amber',
  received: 'green',
  recorded: 'green',
  pending: 'amber',
  returned: 'purple',
  selected: 'green',
  offered: 'gray',
  created: 'green',
};

export function statusBadgeVariant(status) {
  return STATUS_TONES[String(status ?? '')] ?? 'gray';
}

/** Human label for any procurement status value. */
export function statusLabel(status) {
  const key = String(status ?? '');
  return PURCHASE_REQUEST_STATUS_LABELS[key]
    ?? PURCHASE_ORDER_STATUS_LABELS[key]
    ?? GOODS_RECEIPT_STATUS_LABELS[key]
    ?? APPROVAL_STATUS_LABELS[key]
    ?? (key ? key.replace(/_/g, ' ') : '—');
}

/** Item type is derived from the PO line flags, never invented. */
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

/**
 * Format a backend decimal string with thousands separators.
 *
 * Digits are grouped as text so a 14-digit amount never passes through a
 * float: the value the backend returned is what the user sees.
 */
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

/** DRF returns either a bare array or a paginated envelope. */
export function safeResults(data) {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  return Array.isArray(data.results) ? data.results : [];
}

/** Strip the API origin so `next` links can be passed back to axios. */
export function normalizePageUrl(url) {
  if (!url) return '';
  return String(url).replace(/^https?:\/\/[^/]+\/api/, '');
}

/**
 * Load rows across pages, bounded so a misbehaving `next` link can never
 * spin forever. The procurement API paginates but does not implement
 * filtering, so list pages filter the bounded result set in the browser.
 */
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

/** Build a query string, dropping empty values. */
export function queryString(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

export function buildPurchaseRequestListUrl(params = { page_size: 100 }) {
  return `/procurement/purchase-requests/${queryString(params)}`;
}

export function buildPurchaseOrderListUrl(params = { page_size: 100 }) {
  return `/procurement/purchase-orders/${queryString(params)}`;
}

export function buildGoodsReceiptListUrl(params = { page_size: 100 }) {
  return `/procurement/goods-receipts/${queryString(params)}`;
}

export function buildQuotationListUrl(purchaseRequestId) {
  return `/procurement/quotations/${queryString({
    page_size: 100, purchase_request: purchaseRequestId,
  })}`;
}

export function buildDashboardUrl(filters = {}) {
  return `/procurement/dashboard/${queryString(filters)}`;
}

export function buildAssetReceiptItemsUrl(params = {}) {
  return `/procurement/asset-receipt-items/${queryString(params)}`;
}

export function buildAttachmentListUrl(parentType, parentId) {
  return `/procurement/attachments/${queryString({
    page_size: 100, [parentType]: parentId,
  })}`;
}

export const ATTACHMENT_DOCUMENT_TYPES = [
  'requisition', 'specification', 'quotation', 'comparison', 'approval',
  'purchase_order', 'delivery_note', 'invoice', 'receipt', 'inspection',
  'discrepancy', 'warranty', 'other',
];

export const PROCUREMENT_ASSET_STATUS_LABELS = {
  pending_registration: 'Pending registration',
  registered: 'Registered',
  cancelled: 'Cancelled',
  exception: 'Exception',
};

/** Extract a safe filename from a Content-Disposition header. */
export function filenameFromContentDisposition(header, fallback = 'download') {
  if (!header) return fallback;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(String(header));
  if (!match) return fallback;
  try {
    return decodeURIComponent(match[1].trim());
  } catch {
    return match[1].trim() || fallback;
  }
}

export function parseFieldErrors(error) {
  return parseApiError(error);
}

function dec(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function money(value) {
  return value.toFixed(2);
}

/** Informational only — the backend total stays authoritative. */
export function calculateDisplaySubtotal(lines, unitKey = 'estimated_unit_price') {
  return money((lines || []).reduce(
    (sum, line) => sum + dec(line.quantity) * dec(line[unitKey]), 0,
  ));
}

export function calculateDisplayTax(lines) {
  return money((lines || []).reduce((sum, line) => sum + dec(line.tax), 0));
}

export function calculateDisplayDiscount(lines) {
  return money((lines || []).reduce((sum, line) => sum + dec(line.discount), 0));
}

export function calculateDisplayTotal(lines) {
  return money(dec(calculateDisplaySubtotal(lines)) + dec(calculateDisplayTax(lines))
    - dec(calculateDisplayDiscount(lines)));
}

/** Request-level estimate from its line items (informational). */
export function estimateRequestTotal(items) {
  const total = (items || []).reduce((sum, line) => {
    const lineTotal = dec(line.estimated_total) || (dec(line.quantity) * dec(line.estimated_unit_price));
    return sum + lineTotal;
  }, 0);
  return total.toFixed(2);
}

export function remainingQuantity(line) {
  if (!line) return 0;
  const booked = dec(line.received_qty) + dec(line.rejected_qty) + dec(line.damaged_qty);
  return Math.max(0, dec(line.quantity) - booked);
}

/** Accepted (usable) units on a receipt line. */
export function acceptedQuantity(line) {
  if (!line) return 0;
  return Math.max(
    0,
    dec(line.quantity_received) - dec(line.quantity_rejected) - dec(line.quantity_damaged),
  );
}

export function receiptSummary(receipt) {
  const items = receipt?.items || [];
  return items.reduce((acc, line) => ({
    received: acc.received + dec(line.quantity_received),
    accepted: acc.accepted + acceptedQuantity(line),
    rejected: acc.rejected + dec(line.quantity_rejected),
    damaged: acc.damaged + dec(line.quantity_damaged),
  }), { received: 0, accepted: 0, rejected: 0, damaged: 0 });
}

/** Group backend amounts per currency — currencies are never summed. */
export function totalsByCurrency(rows, amountKey = 'total', currencyKey = 'currency') {
  const groups = new Map();
  for (const row of rows || []) {
    const currency = row?.[currencyKey] || '—';
    const current = groups.get(currency) || 0;
    groups.set(currency, current + dec(row?.[amountKey]));
  }
  return [...groups.entries()].map(([currency, amount]) => ({
    currency,
    amount: amount.toFixed(2),
  }));
}

/**
 * What the current user may do, from the capabilities the backend grants.
 * Hiding a control is presentation only — the API stays authoritative.
 */
export function actionAvailability({ request, purchaseOrder, caps, userId } = {}) {
  const c = caps || {};
  const isRequester = !!request && !!userId && request.requester === userId;
  const prStatus = request?.status;
  const poStatus = purchaseOrder?.status;
  const isPoCreator = !!purchaseOrder && !!userId
    && purchaseOrder.created_by === userId;
  return {
    submitRequest: !!c.canCreatePurchaseRequest
      && (isRequester || !!c.canApprovePurchaseRequest)
      && (prStatus === 'draft' || prStatus === 'returned_for_correction'),
    approveRequest: !!c.canApprovePurchaseRequest
      && prStatus === 'pending_approval'
      && !isRequester,
    rejectRequest: !!c.canApprovePurchaseRequest
      && prStatus === 'pending_approval'
      && !isRequester,
    returnRequest: !!c.canApprovePurchaseRequest && prStatus === 'pending_approval',
    editRequest: !!c.canCreatePurchaseRequest
      && (prStatus === 'draft' || prStatus === 'returned_for_correction'),
    manageQuotations: !!c.canManageQuotations && prStatus === 'approved',
    selectVendor: !!c.canSelectProcurementVendor && prStatus === 'approved',
    generateOrder: !!c.canCreatePurchaseOrder && prStatus === 'approved',
    approveOrder: !!c.canApprovePurchaseOrder
      && poStatus === 'pending_approval'
      && !isPoCreator,
    rejectOrder: !!c.canApprovePurchaseOrder
      && poStatus === 'pending_approval'
      && !isPoCreator,
    issueOrder: !!c.canIssuePurchaseOrder && poStatus === 'approved',
    createReceipt: !!c.canCreateGoodsReceipt
      && ['sent_to_vendor', 'partially_received', 'approved'].includes(poStatus),
  };
}

/** Client-side capability view used by every procurement page. */
export function procurementCapabilities(auth) {
  const role = auth?.role;
  const isSystemAdmin = !!auth?.isSystemAdmin || role === 'system_admin';
  const isManager = !!auth?.isITManager || role === 'it_manager';
  const isSupport = !!auth?.isITSupport || role === 'it_support';
  const isKnownStaff = isSystemAdmin || isManager || isSupport;
  return {
    canViewProcurement: isKnownStaff,
    canCreatePurchaseRequest: isKnownStaff,
    canApprovePurchaseRequest: isSystemAdmin || isManager,
    canManageQuotations: isKnownStaff,
    canSelectProcurementVendor: isSystemAdmin || isManager,
    canCreatePurchaseOrder: isSystemAdmin || isManager,
    canApprovePurchaseOrder: isSystemAdmin || isManager,
    canIssuePurchaseOrder: isSystemAdmin || isManager,
    canCreateGoodsReceipt: isKnownStaff,
    canPostGoodsReceipt: isKnownStaff,
    canRegisterProcurementAssets: isKnownStaff,
    canViewProcurementReports: isSystemAdmin || isManager,
  };
}

/**
 * Procurement overview counters computed from the real list endpoints.
 * The backend exposes no dashboard endpoint, so every number here is a
 * count over rows that were actually returned — never a made-up metric.
 */
export function procurementOverview({ requests = [], orders = [], receipts = [] } = {}) {
  // Retained for reporting views that still read the list endpoints.

  const approvedAwaitingQuotations = requests.filter(
    (request) => request.status === 'approved' && (request.quotations || []).length === 0,
  );
  const quotationsAwaitingSelection = requests.filter(
    (request) => request.status === 'approved'
      && (request.quotations || []).length > 0
      && !(request.quotations || []).some((quotation) => quotation.is_selected),
  );
  const discrepancies = [];
  for (const receipt of receipts) {
    for (const line of receipt.items || []) {
      if (dec(line.quantity_rejected) > 0 || dec(line.quantity_damaged) > 0) {
        discrepancies.push({ receipt, line });
      }
    }
  }
  const orderById = new Map(orders.map((order) => [order.id, order]));
  const pendingAssets = [];
  for (const receipt of receipts) {
    const order = orderById.get(receipt.purchase_order);
    for (const line of receipt.items || []) {
      const poLine = (order?.items || []).find((item) => item.id === line.purchase_order_item);
      if (!poLine?.is_serialized) continue;
      const accepted = acceptedQuantity(line);
      if (accepted > 0) pendingAssets.push({ receipt, line, poLine, accepted });
    }
  }
  const units = (rows, key) => rows.reduce((sum, row) => sum + dec(row[key]), 0);
  return {
    draftRequests: requests.filter((r) => r.status === 'draft').length,
    pendingRequestApprovals: requests.filter((r) => r.status === 'pending_approval').length,
    approvedAwaitingQuotations: approvedAwaitingQuotations.length,
    quotationsAwaitingSelection: quotationsAwaitingSelection.length,
    pendingOrderApprovals: orders.filter((o) => o.status === 'pending_approval').length,
    issuedOrders: orders.filter((o) => ['sent_to_vendor', 'partially_received'].includes(o.status)).length,
    partiallyReceived: orders.filter((o) => o.status === 'partially_received').length,
    discrepancies: discrepancies.length,
    pendingAssets: pendingAssets.length,
    requests: requests.length,
    orders: orders.length,
    receipts: receipts.length,
    orderedUnits: units(orders.flatMap((o) => o.items || []), 'quantity'),
    acceptedUnits: units(receipts.flatMap((r) => r.items || []), 'quantity_received'),
    orderValueByCurrency: totalsByCurrency(
      orders.filter((o) => o.status !== 'cancelled' && o.status !== 'rejected'),
    ),
    orderValueByVendor: [...orders.reduce((map, order) => {
      const key = order.vendor_detail?.name || `Vendor ${order.vendor}`;
      const group = map.get(key) || { vendor: key, currency: order.currency || '—', amount: 0 };
      group.amount += dec(order.total);
      map.set(key, group);
      return map;
    }, new Map()).values()]
      .map((row) => ({ ...row, amount: row.amount.toFixed(2) }))
      .sort((a, b) => Number(b.amount) - Number(a.amount)),
    discrepanciesDetail: discrepancies,
    pendingAssetDetail: pendingAssets,
  };
}

/** Small helper for currency-aware amounts with a per-row currency. */
export function moneyFor(row, key = 'total') {
  return formatMoney(row?.[key], row?.currency);
}
