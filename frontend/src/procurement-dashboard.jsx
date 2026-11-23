import { useCallback, useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  DataTable, EmptyState, Field, LoadingRows, PageHeader,
} from './components';
import {
  PURCHASE_ORDER_STATUS_LABELS,
  PURCHASE_REQUEST_STATUS_LABELS,
  buildDashboardUrl,
  buildGoodsReceiptListUrl,
  buildPurchaseOrderListUrl,
  buildPurchaseRequestListUrl,
  fetchAll,
  formatDate,
  formatDateTime,
  formatMoney,
  formatQuantity,
  parseFieldErrors,
  procurementCapabilities,
  procurementOverview,
  statusBadgeVariant,
} from './procurement-utils';

function Kpi({ label, value, hint }) {
  return (
    <div className="panel" style={{ minWidth: 170, flex: '1 1 170px' }}>
      <div className="panel-pad">
        <div className="small muted">{label}</div>
        <div style={{ fontSize: 26, fontWeight: 600 }}>{value}</div>
        {hint ? <div className="small muted">{hint}</div> : null}
      </div>
    </div>
  );
}

/** Legacy list aggregation, used only if the aggregate endpoint is missing
 *  during a rolling deployment. Never a permanent code path. */
async function loadLegacyDashboard() {
  const [requests, orders, receipts] = await Promise.all([
    fetchAll(buildPurchaseRequestListUrl()),
    fetchAll(buildPurchaseOrderListUrl()),
    fetchAll(buildGoodsReceiptListUrl()),
  ]);
  const overview = procurementOverview({ requests, orders, receipts });
  return {
    purchase_requests: {
      draft: overview.draftRequests,
      pending_manager_approval: overview.pendingRequestApprovals,
      pending_system_admin_approval: requests.filter(
        (r) => r.status === 'pending_approval' && r.requires_system_admin_approval).length,
      approved: requests.filter((r) => r.status === 'approved').length,
      rejected: requests.filter((r) => r.status === 'rejected').length,
      returned_for_correction: requests.filter(
        (r) => r.status === 'returned_for_correction').length,
    },
    quotations: {
      awaiting_collection: overview.approvedAwaitingQuotations,
      awaiting_selection: overview.quotationsAwaitingSelection,
      selected: requests.filter((r) => (r.quotations || []).some((q) => q.is_selected)).length,
    },
    purchase_orders: {
      pending_approval: overview.pendingOrderApprovals,
      sent_to_vendor: orders.filter((o) => o.status === 'sent_to_vendor').length,
      partially_received: overview.partiallyReceived,
      overdue_delivery: 0,
      closed: orders.filter((o) => o.status === 'closed').length,
      cancelled: orders.filter((o) => o.status === 'cancelled').length,
    },
    goods_receipts: {
      recent: receipts.length,
      with_rejections: overview.discrepancies,
      with_damage: 0,
      with_short_delivery: 0,
    },
    asset_registration: { pending: overview.pendingAssets, completed: 0 },
    values_by_currency: overview.orderValueByCurrency.map((row) => ({
      currency: row.currency,
      ordered_total: row.amount,
      received_total: '0.00',
      outstanding_total: row.amount,
    })),
    recent_purchase_requests: requests.slice(0, 10),
    recent_purchase_orders: orders.slice(0, 10),
    recent_receipts: receipts.slice(0, 10),
    upcoming_deliveries: [],
    overdue_deliveries: [],
    pending_asset_registration: overview.pendingAssetDetail.slice(0, 10),
    receipt_discrepancies: overview.discrepanciesDetail.slice(0, 10).map(({ receipt, line }) => ({
      id: line.id,
      goods_receipt: receipt.id,
      gr_number: receipt.gr_number,
      item_name: `Line ${line.purchase_order_item}`,
      quantity_rejected: line.quantity_rejected,
      quantity_damaged: line.quantity_damaged,
      rejection_reason: line.rejection_reason,
      damage_notes: line.damage_notes,
    })),
    _legacy: true,
  };
}

function useDashboard(filters, enabled) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(!!enabled);
  const [error, setError] = useState('');
  const [refreshedAt, setRefreshedAt] = useState(null);
  const [legacy, setLegacy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await api.get(buildDashboardUrl(filters));
      setData(response.data);
      setLegacy(false);
      setRefreshedAt(new Date());
    } catch (e) {
      const status = e?.response?.status;
      // Only an unavailable endpoint during a rolling deploy triggers the
      // fallback; auth/permission/server errors are surfaced honestly.
      if (!status || status === 404) {
        try {
          setData(await loadLegacyDashboard());
          setLegacy(true);
          setRefreshedAt(new Date());
        } catch (fallbackError) {
          setError(parseFieldErrors(fallbackError).global || 'Could not load procurement data.');
        }
      } else if (status === 403) {
        setError('You do not have access to the procurement dashboard.');
      } else {
        setError(parseFieldErrors(e).global || 'Could not load procurement data.');
      }
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    if (enabled) load(); // eslint-disable-line react/set-state-in-effect
  }, [enabled, load]);

  return { data, loading, error, refreshedAt, legacy, load };
}

/** Procurement overview from the server aggregate endpoint. */
export function ProcurementDashboard() {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const [filters, setFilters] = useState({
    date_from: '', date_to: '', department: '', vendor: '', currency: '',
  });
  const queryFilters = useMemo(() => ({ ...filters }), [filters]);
  const {
    data, loading, error, refreshedAt, legacy, load,
  } = useDashboard(queryFilters, caps.canViewProcurement);

  if (!caps.canViewProcurement) {
    return (
      <div>
        <PageHeader title="Procurement" />
        <EmptyState
          title="Procurement is not available to your role"
          hint="Procurement is administered by IT Support, IT Manager and System Admin users."
        />
      </div>
    );
  }

  const requests = data?.purchase_requests || {};
  const quotations = data?.quotations || {};
  const orders = data?.purchase_orders || {};
  const receipts = data?.goods_receipts || {};
  const assets = data?.asset_registration || {};
  const currencies = data?.values_by_currency || [];
  const recentRequests = data?.recent_purchase_requests || [];
  const recentOrders = data?.recent_purchase_orders || [];
  const recentReceipts = data?.recent_receipts || [];
  const pendingAssets = data?.pending_asset_registration || [];
  const discrepancies = data?.receipt_discrepancies || [];
  const vendors = new Map();
  for (const order of [...recentOrders, ...(data?.upcoming_deliveries || [])]) {
    if (order.vendor) vendors.set(String(order.vendor), order.vendor_detail?.name ?? `Vendor ${order.vendor}`);
  }
  const pendingApprovalRequests = recentRequests.filter(
    (r) => r.status === 'pending_approval').slice(0, 6);
  const setFilter = (key, value) => setFilters((f) => ({ ...f, [key]: value }));

  return (
    <div>
      <PageHeader
        title="Procurement"
        sub="Purchase requests, vendor quotations, orders and deliveries."
        actions={(
          <div className="row-gap">
            <button type="button" className="btn-ghost" onClick={load} disabled={loading}>Refresh</button>
            <a className="btn-ghost" href="#/procurement/requests">Purchase requests</a>
            <a className="btn-ghost" href="#/procurement/orders">Purchase orders</a>
            <a className="btn-ghost" href="#/procurement/receipts">Goods receipts</a>
          </div>
        )}
      />

      <div className="panel">
        <div className="panel-head"><h3>Filters</h3></div>
        <div className="panel-pad">
          <div className="row-gap">
            <Field label="Created from">
              <input type="date" className="input" value={filters.date_from} onChange={(e) => setFilter('date_from', e.target.value)} aria-label="Created from" />
            </Field>
            <Field label="Created to">
              <input type="date" className="input" value={filters.date_to} onChange={(e) => setFilter('date_to', e.target.value)} aria-label="Created to" />
            </Field>
            <Field label="Department ID">
              <input type="number" min="1" className="input" value={filters.department} onChange={(e) => setFilter('department', e.target.value)} aria-label="Department ID" />
            </Field>
            <Field label="Currency">
              <select className="input" value={filters.currency} onChange={(e) => setFilter('currency', e.target.value)} aria-label="Currency">
                <option value="">All currencies</option>
                {currencies.map((row) => <option key={row.currency} value={row.currency}>{row.currency}</option>)}
              </select>
            </Field>
            <Field label="Vendor">
              <select className="input" value={filters.vendor} onChange={(e) => setFilter('vendor', e.target.value)} aria-label="Vendor">
                <option value="">All vendors</option>
                {[...vendors.entries()].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </Field>
          </div>
          <p className="small muted" style={{ marginBottom: 0 }}>
            Last refreshed {refreshedAt ? formatDateTime(refreshedAt) : '—'} ·{' '}
            {legacy
              ? 'aggregate endpoint unavailable, showing a bounded client summary'
              : 'server aggregates'}
          </p>
        </div>
      </div>

      {loading ? <LoadingRows /> : null}
      {error ? (
        <div>
          <div className="error-summary" role="alert">{error}</div>
          <button type="button" className="btn-primary" onClick={load}>Retry</button>
        </div>
      ) : null}

      {!loading && !error && data ? (
        <>
          <div className="row-gap" style={{ marginTop: 16, alignItems: 'stretch' }}>
            <Kpi label="Draft purchase requests" value={requests.draft ?? 0} />
            <Kpi
              label="Pending request approval"
              value={requests.pending_manager_approval ?? 0}
              hint={`${requests.pending_system_admin_approval ?? 0} need System Admin`}
            />
            <Kpi label="Awaiting quotations" value={quotations.awaiting_collection ?? 0} />
            <Kpi label="Quotations awaiting selection" value={quotations.awaiting_selection ?? 0} />
            <Kpi label="Orders pending approval" value={orders.pending_approval ?? 0} />
            <Kpi label="Issued orders" value={(orders.sent_to_vendor ?? 0) + (orders.partially_received ?? 0)} />
            <Kpi label="Partially received" value={orders.partially_received ?? 0} />
            <Kpi label="Overdue deliveries" value={orders.overdue_delivery ?? 0} />
            <Kpi label="Receipt discrepancies" value={(receipts.with_rejections ?? 0) + (receipts.with_damage ?? 0)} hint="receipts with rejected or damaged units" />
            <Kpi label="Awaiting asset registration" value={assets.pending ?? 0} hint="accepted serialized units" />
          </div>

          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h3>Ordered value by currency</h3></div>
            <div className="panel-pad">
              {currencies.length === 0 ? (
                <p className="small">No purchase orders yet.</p>
              ) : (
                <DataTable
                  columns={[
                    { key: 'currency', label: 'Currency' },
                    { key: 'ordered_total', label: 'Ordered', render: (r) => formatMoney(r.ordered_total, r.currency) },
                    { key: 'received_total', label: 'Received', render: (r) => formatMoney(r.received_total, r.currency) },
                    { key: 'outstanding_total', label: 'Outstanding', render: (r) => formatMoney(r.outstanding_total, r.currency) },
                  ]}
                  rows={currencies}
                  keyOf={(r) => `currency-${r.currency}`}
                  emptyTitle="No orders."
                  emptyHint=""
                />
              )}
              <p className="small muted">
                Currencies are never combined into a single total. Values are server-calculated
                order totals, received line values and the outstanding balance.
              </p>
            </div>
          </div>

          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h3>Purchase requests needing action</h3></div>
            <div className="panel-pad">
              {pendingApprovalRequests.length === 0 ? (
                <p className="small">Nothing is waiting for approval.</p>
              ) : (
                <DataTable
                  columns={[
                    { key: 'pr_number', label: 'Request', render: (r) => <a className="row-title" href={`#/procurement/requests/${r.id}`}>{r.pr_number}</a> },
                    { key: 'requester_name', label: 'Requester', render: (r) => r.requester_name || '—' },
                    { key: 'status', label: 'Status', render: (r) => <span className={`badge badge-${statusBadgeVariant(r.status)}`}>{PURCHASE_REQUEST_STATUS_LABELS[r.status] ?? r.status}</span> },
                    { key: 'estimated_total', label: 'Estimated total', render: (r) => formatMoney(r.estimated_total) },
                    { key: 'created_at', label: 'Created', render: (r) => formatDate(r.created_at) },
                  ]}
                  rows={pendingApprovalRequests}
                  keyOf={(r) => `pending-${r.id}`}
                  emptyTitle="Nothing pending."
                  emptyHint=""
                />
              )}
            </div>
          </div>

          <div className="row-gap" style={{ marginTop: 16, alignItems: 'flex-start' }}>
            <div className="panel" style={{ flex: '1 1 420px' }}>
              <div className="panel-head"><h3>Recent purchase requests</h3></div>
              <div className="panel-pad">
                {recentRequests.length === 0 ? <p className="small">No purchase requests.</p> : (
                  <ul className="small">
                    {recentRequests.slice(0, 6).map((request) => (
                      <li key={request.id}>
                        <a href={`#/procurement/requests/${request.id}`}>{request.pr_number}</a>
                        {' · '}{PURCHASE_REQUEST_STATUS_LABELS[request.status] ?? request.status}
                        {' · '}{formatMoney(request.estimated_total)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
            <div className="panel" style={{ flex: '1 1 420px' }}>
              <div className="panel-head"><h3>Recent purchase orders</h3></div>
              <div className="panel-pad">
                {recentOrders.length === 0 ? <p className="small">No purchase orders.</p> : (
                  <ul className="small">
                    {recentOrders.slice(0, 6).map((order) => (
                      <li key={order.id}>
                        <a href={`#/procurement/orders/${order.id}`}>{order.po_number}</a>
                        {' · '}{order.vendor_detail?.name ?? '—'}
                        {' · '}{PURCHASE_ORDER_STATUS_LABELS[order.status] ?? order.status}
                        {' · '}{formatMoney(order.total, order.currency)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>

          <div className="row-gap" style={{ marginTop: 16, alignItems: 'flex-start' }}>
            <div className="panel" style={{ flex: '1 1 420px' }}>
              <div className="panel-head"><h3>Recent goods receipts</h3></div>
              <div className="panel-pad">
                {recentReceipts.length === 0 ? <p className="small">No goods receipts.</p> : (
                  <ul className="small">
                    {recentReceipts.slice(0, 6).map((receipt) => (
                      <li key={receipt.id}>
                        <a href={`#/procurement/receipts/${receipt.id}`}>{receipt.gr_number}</a>
                        {' · '}{formatDate(receipt.received_at)}
                        {' · '}{formatQuantity((receipt.items || []).length)} line(s)
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
            <div className="panel" style={{ flex: '1 1 420px' }}>
              <div className="panel-head"><h3>Receipt discrepancies</h3></div>
              <div className="panel-pad">
                {discrepancies.length === 0 ? (
                  <p className="small">No rejected or damaged units recorded.</p>
                ) : (
                  <ul className="small">
                    {discrepancies.slice(0, 6).map((line) => (
                      <li key={`disc-${line.id}`}>
                        <a href={`#/procurement/receipts/${line.goods_receipt}`}>{line.gr_number}</a>
                        {' · '}{line.item_name}
                        {' · '}{formatQuantity(line.quantity_rejected)} rejected,{' '}
                        {formatQuantity(line.quantity_damaged)} damaged
                      </li>
                    ))}
                  </ul>
                )}
                <p className="small muted">
                  Discrepancy recorded for follow-up. Vendor return processing is not included in this release.
                </p>
              </div>
            </div>
          </div>

          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h3>Pending asset registration</h3></div>
            <div className="panel-pad">
              {pendingAssets.length === 0 ? (
                <p className="small">No accepted serialized units are awaiting registration.</p>
              ) : (
                <ul className="small">
                  {pendingAssets.slice(0, 8).map((item) => (
                    <li key={`asset-${item.id}`}>
                      {item.item_name} · unit {item.sequence} ·{' '}
                      <a href={`#/procurement/receipts/${item.goods_receipt}`}>{item.gr_number}</a>
                    </li>
                  ))}
                </ul>
              )}
              <a className="btn-ghost btn-small" href="#/procurement/assets">Open asset registration</a>
            </div>
          </div>

          {caps.canViewProcurementReports ? (
            <p className="small" style={{ marginTop: 16 }}>
              <a href="#/procurement/reports">Open procurement reports →</a>
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function useProcurementData(enabled) {
  const [requests, setRequests] = useState([]);
  const [orders, setOrders] = useState([]);
  const [receipts, setReceipts] = useState([]);
  const [loading, setLoading] = useState(!!enabled);
  const [error, setError] = useState('');
  const [refreshedAt, setRefreshedAt] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [requestRows, orderRows, receiptRows] = await Promise.all([
        fetchAll(buildPurchaseRequestListUrl()),
        fetchAll(buildPurchaseOrderListUrl()),
        fetchAll(buildGoodsReceiptListUrl()),
      ]);
      setRequests(requestRows);
      setOrders(orderRows);
      setReceipts(receiptRows);
      setRefreshedAt(new Date());
    } catch (e) {
      setError(parseFieldErrors(e).global || 'Could not load procurement data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (enabled) load(); // eslint-disable-line react/set-state-in-effect
  }, [enabled, load]);

  return {
    requests, orders, receipts, loading, error, refreshedAt, load,
  };
}

/** Reporting view aggregated from the same real list endpoints. */
export function ProcurementReports() {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const {
    requests, orders, receipts, loading, error, refreshedAt, load,
  } = useProcurementData(caps.canViewProcurementReports);

  const overview = useMemo(
    () => procurementOverview({ requests, orders, receipts }),
    [requests, orders, receipts],
  );

  const statusRows = useMemo(() => Object.entries(PURCHASE_ORDER_STATUS_LABELS)
    .map(([status, label]) => ({
      status,
      label,
      count: orders.filter((order) => order.status === status).length,
      value: orders.filter((order) => order.status === status)
        .reduce((sum, order) => sum + Number(order.total || 0), 0),
    }))
    .filter((row) => row.count > 0), [orders]);

  const requestStatusRows = useMemo(() => Object.entries(PURCHASE_REQUEST_STATUS_LABELS)
    .map(([status, label]) => ({
      status,
      label,
      count: requests.filter((request) => request.status === status).length,
      value: requests.filter((request) => request.status === status)
        .reduce((sum, request) => sum + Number(request.estimated_total || 0), 0),
    }))
    .filter((row) => row.count > 0), [requests]);

  if (!caps.canViewProcurementReports) {
    return (
      <div>
        <PageHeader title="Procurement reports" />
        <EmptyState
          title="Reports are restricted"
          hint="Procurement reports are available to IT Manager and System Admin users."
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Procurement reports"
        sub="Aggregated from the live procurement records."
        actions={(
          <div className="row-gap">
            <button type="button" className="btn-ghost" onClick={load} disabled={loading}>Refresh</button>
            <a className="btn-ghost" href="#/procurement">Overview</a>
          </div>
        )}
      />

      {loading ? <LoadingRows /> : null}
      {error ? (
        <div>
          <div className="error-summary" role="alert">{error}</div>
          <button type="button" className="btn-primary" onClick={load}>Retry</button>
        </div>
      ) : null}

      {!loading && !error ? (
        <>
          <p className="small muted">Data as of {formatDateTime(refreshedAt)}.</p>

          <div className="panel">
            <div className="panel-head"><h3>Value by currency</h3></div>
            <div className="panel-pad">
              {overview.orderValueByCurrency.length === 0 ? <p className="small">No orders.</p> : (
                <DataTable
                  columns={[
                    { key: 'currency', label: 'Currency' },
                    { key: 'amount', label: 'Ordered value', render: (r) => formatMoney(r.amount, r.currency) },
                  ]}
                  rows={overview.orderValueByCurrency}
                  keyOf={(r) => r.currency}
                  emptyTitle="No orders."
                  emptyHint=""
                />
              )}
            </div>
          </div>

          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h3>Value by vendor</h3></div>
            <div className="panel-pad">
              {overview.orderValueByVendor.length === 0 ? <p className="small">No vendor spend yet.</p> : (
                <DataTable
                  columns={[
                    { key: 'vendor', label: 'Vendor' },
                    { key: 'currency', label: 'Currency' },
                    { key: 'amount', label: 'Ordered value', render: (r) => formatMoney(r.amount, r.currency) },
                  ]}
                  rows={overview.orderValueByVendor}
                  keyOf={(r) => `${r.vendor}-${r.currency}`}
                  emptyTitle="No vendors."
                  emptyHint=""
                />
              )}
              <p className="small muted">
                Vendor totals are grouped per currency so different currencies are never added together.
              </p>
            </div>
          </div>

          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h3>Purchase order status</h3></div>
            <div className="panel-pad">
              <DataTable
                columns={[
                  { key: 'label', label: 'Status' },
                  { key: 'count', label: 'Orders' },
                  { key: 'value', label: 'Value (mixed currencies)', render: (r) => r.value.toFixed(2) },
                ]}
                rows={statusRows}
                keyOf={(r) => r.status}
                emptyTitle="No purchase orders."
                emptyHint=""
              />
              <p className="small muted">
                Status rows list order counts; the value column only groups same-currency totals
                when a single currency is in use.
              </p>
            </div>
          </div>

          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h3>Purchase request status</h3></div>
            <div className="panel-pad">
              <DataTable
                columns={[
                  { key: 'label', label: 'Status' },
                  { key: 'count', label: 'Requests' },
                  { key: 'value', label: 'Estimated value', render: (r) => r.value.toFixed(2) },
                ]}
                rows={requestStatusRows}
                keyOf={(r) => r.status}
                emptyTitle="No purchase requests."
                emptyHint=""
              />
            </div>
          </div>

          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head"><h3>Receipts and discrepancies</h3></div>
            <div className="panel-pad">
              <ul className="small">
                <li>Receipts recorded: {overview.receipts}</li>
                <li>Accepted units booked: {formatQuantity(overview.acceptedUnits)}</li>
                <li>Rejected or damaged lines: {overview.discrepancies}</li>
                <li>Awaiting asset registration: {overview.pendingAssets}</li>
              </ul>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
