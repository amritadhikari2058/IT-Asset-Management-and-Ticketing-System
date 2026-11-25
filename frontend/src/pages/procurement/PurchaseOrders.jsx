import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import {
  ConfirmDialog, DataTable, ErrorSummary, Field, LoadingRows, Modal, PageHeader, Pager, PageSizeSelector,
} from '../../components';
import {
  PURCHASE_ORDER_STATUS_LABELS,
  actionAvailability,
  buildPurchaseOrderListUrl,
  formatDateTime,
  formatMoney,
  parseFieldErrors,
  procurementCapabilities,
  safeResults,
  statusBadgeVariant,
} from '../../shared/procurement-utils';

function StatusPill({ status }) {
  return (
    <span className={`badge badge-${statusBadgeVariant(status)}`}>
      {PURCHASE_ORDER_STATUS_LABELS[status] ?? status}
    </span>
  );
}

/** Purchase order list with server-side filters, search and pagination. */
export function PurchaseOrdersPage() {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const requestIdRef = useRef(0);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  const [orders, setOrders] = useState([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    q: '', status: '', createdFrom: '', createdTo: '', receiptStatus: '', ordering: '-created_at',
  });
  const [dialog, setDialog] = useState(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');

  // Page-size preference persisted in localStorage; fall back to DRF default 20.
  const [pageSize, setPageSize] = useState(() => {
    if (typeof window === 'undefined') return 20;
    try {
      const saved = window.localStorage.getItem('itdesk.pageSize');
      const n = Number(saved);
      return saved && Number.isFinite(n) && n > 0 ? n : 20;
    } catch {
      return 20;
    }
  });

  const load = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError('');
    try {
      const response = await api.get(buildPurchaseOrderListUrl({
        page,
        page_size: pageSize,
        search: filters.q,
        status: filters.status,
        created_from: filters.createdFrom,
        created_to: filters.createdTo,
        receipt_status: filters.receiptStatus,
        ordering: filters.ordering,
      }));
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setOrders(safeResults(response.data));
      setCount(Number(response.data?.count ?? safeResults(response.data).length));
    } catch (e) {
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setError(parseFieldErrors(e).global || 'Could not load purchase orders.');
    } finally {
      if (mountedRef.current && requestId === requestIdRef.current) setLoading(false);
    }
  }, [page, filters, pageSize]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  // Reset to page 1 when page size changes
  useEffect(() => {
    setPage(1); // eslint-disable-line react/set-state-in-effect
  }, [pageSize]);

  // Persist page-size preference without unnecessary writes
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      if (window.localStorage.getItem('itdesk.pageSize') !== String(pageSize)) {
        window.localStorage.setItem('itdesk.pageSize', String(pageSize));
      }
    } catch {
      // ignore storage failures
    }
  }, [pageSize]);

  const pageCount = Math.max(1, Math.ceil(count / pageSize));
  const currentPage = Math.min(page, pageCount);
  const update = (key, value) => { setFilters((f) => ({ ...f, [key]: value })); setPage(1); };

  const runAction = async (po, action) => {
    setBusy(true);
    setActionError('');
    try {
      const payload = { reason: reason.trim() };
      if (action === 'cancel') payload.version = po.version;
      await api.post(`/procurement/purchase-orders/${po.id}/${action}/`, payload);
      setDialog(null);
      setReason('');
      setNotice('Purchase order updated.');
      await load();
    } catch (e) {
      const status = e?.response?.status;
      const parsed = parseFieldErrors(e);
      if (status === 403) {
        setActionError('You do not have permission to perform this action.');
      } else if (status === 409) {
        await load();
        setActionError('This order changed while you were working. Reload and review before retrying.');
      } else {
        setActionError(parsed.global || Object.values(parsed.fields)[0] || 'Action failed.');
      }
    } finally {
      setBusy(false);
    }
  };

  if (!caps.canViewProcurement) {
    return <div className="empty-state"><div className="empty-title">Access restricted</div><div className="small">Procurement is available to IT staff only.</div></div>;
  }

  return (
    <div>
      <PageHeader
        title="Purchase orders"
        sub="Approval, issue and receipt for vendor orders."
        actions={<a className="btn-ghost" href="#/procurement">Overview</a>}
      />

      <div className="panel">
        <div className="panel-head"><h3>Filters</h3></div>
        <div className="panel-pad">
          <div className="row-gap">
            <Field label="Search">
              <input className="input" value={filters.q} onChange={(e) => update('q', e.target.value)} placeholder="PO number, vendor, request" />
            </Field>
            <Field label="Status">
              <select className="input" value={filters.status} onChange={(e) => update('status', e.target.value)}>
                <option value="">Any status</option>
                {Object.entries(PURCHASE_ORDER_STATUS_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </Field>
            <Field label="Receipt status">
              <select className="input" value={filters.receiptStatus} onChange={(e) => update('receiptStatus', e.target.value)}>
                <option value="">Any</option>
                <option value="unreceived">Not yet received</option>
                <option value="partially_received">Partially received</option>
                <option value="received">Fully received</option>
              </select>
            </Field>
            <Field label="Order by">
              <select className="input" value={filters.ordering} onChange={(e) => update('ordering', e.target.value)} aria-label="Order by">
                <option value="-created_at">Newest first</option>
                <option value="created_at">Oldest first</option>
                <option value="expected_delivery_date">Expected delivery</option>
                <option value="total">Total</option>
                <option value="po_number">PO number</option>
              </select>
            </Field>
            <Field label="Ordered from">
              <input type="date" className="input" value={filters.createdFrom} onChange={(e) => update('createdFrom', e.target.value)} />
            </Field>
            <Field label="Ordered to">
              <input type="date" className="input" value={filters.createdTo} onChange={(e) => update('createdTo', e.target.value)} />
            </Field>
          </div>
          <div className="row-gap" style={{ marginTop: 8 }}>
            <span className="small muted">{count} order(s)</span>
            <button type="button" className="btn-ghost btn-small" onClick={load} disabled={loading}>Refresh</button>
          </div>
        </div>
      </div>

      {notice ? <div className="success-summary" role="status">{notice}</div> : null}
      {actionError && !dialog ? <ErrorSummary parsed={{ global: actionError }} /> : null}

      {loading ? <LoadingRows /> : null}
      {error ? (
        <div>
          <div className="error-summary" role="alert">{error}</div>
          <button type="button" className="btn-primary" onClick={load}>Retry</button>
        </div>
      ) : null}

      {!loading && !error ? (
        <>
          <DataTable
            columns={[
              { key: 'po_number', label: 'PO', render: (r) => <a className="row-title" href={`#/procurement/orders/${r.id}`}>{r.po_number}</a> },
              {
                key: 'request',
                label: 'Request',
                render: (r) => (r.purchase_request
                  ? <a href={`#/procurement/requests/${r.purchase_request}`}>{r.purchase_request_number || `Request ${r.purchase_request}`}</a>
                  : '—'),
              },
              { key: 'vendor', label: 'Vendor', render: (r) => r.vendor_detail?.name ?? '—' },
              { key: 'status', label: 'Status', render: (r) => <StatusPill status={r.status} /> },
              { key: 'created_at', label: 'Order date', render: (r) => formatDateTime(r.created_at) },
              { key: 'expected_delivery_date', label: 'Expected delivery', render: (r) => r.expected_delivery_date || '—' },
              { key: 'total', label: 'Total', render: (r) => formatMoney(r.total, r.currency) },
              { key: 'currency', label: 'Currency', render: (r) => r.currency || '—' },
              {
                key: 'receipt',
                label: 'Receipt status',
                render: (r) => {
                  const lines = r.items || [];
                  const booked = lines.reduce((sum, line) => sum
                    + Number(line.received_qty || 0)
                    + Number(line.rejected_qty || 0)
                    + Number(line.damaged_qty || 0), 0);
                  if (!booked) return <span className="small muted">Nothing received</span>;
                  return <span className="small">{booked} of {lines.reduce((s, l) => s + Number(l.quantity || 0), 0)} units booked</span>;
                },
              },
              { key: 'updated_at', label: 'Updated', render: (r) => formatDateTime(r.updated_at) },
              {
                key: 'actions',
                label: 'Actions',
                render: (r) => {
                  const available = actionAvailability({ purchaseOrder: r, caps, userId: auth?.user?.id });
                  const booked = (r.items || []).some((line) => (
                    Number(line.received_qty || 0) + Number(line.rejected_qty || 0) + Number(line.damaged_qty || 0)) > 0);
                  return (
                    <div className="row-gap">
                      <a className="btn-ghost btn-small" href={`#/procurement/orders/${r.id}`}>View</a>
                      {available.approveOrder ? (
                        <button type="button" className="btn-small" onClick={() => { setReason(''); setActionError(''); setDialog({ kind: 'approve', po: r }); }}>Approve</button>
                      ) : null}
                      {available.rejectOrder ? (
                        <button type="button" className="btn-small" onClick={() => { setReason(''); setActionError(''); setDialog({ kind: 'reject', po: r }); }}>Reject</button>
                      ) : null}
                      {available.issueOrder ? (
                        <button type="button" className="btn-small" onClick={() => { setActionError(''); setDialog({ kind: 'issue', po: r }); }}>Issue to vendor</button>
                      ) : null}
                      {available.createReceipt ? (
                        <a className="btn-ghost btn-small" href={`#/procurement/receipts/new?po=${r.id}`}>Create receipt</a>
                      ) : null}
                      {caps.canApprovePurchaseOrder && !booked
                        && ['draft', 'pending_approval', 'approved', 'sent_to_vendor'].includes(r.status) ? (
                          <button type="button" className="btn-danger btn-small" onClick={() => { setReason(''); setActionError(''); setDialog({ kind: 'cancel', po: r }); }}>Cancel</button>
                        ) : null}
                    </div>
                  );
                },
              },
            ]}
            rows={orders}
            keyOf={(r) => `po-${r.id}`}
            emptyTitle="No purchase orders match these filters."
            emptyHint="Purchase orders are generated from an approved request with a selected vendor."
          />
          <PageSizeSelector value={pageSize} onChange={setPageSize} />
          <Pager
            count={count}
            hasPrev={currentPage > 1}
            hasNext={currentPage < pageCount}
            onPrev={() => setPage((p) => Math.max(1, p - 1))}
            onNext={() => setPage((p) => Math.min(pageCount, p + 1))}
            busy={loading}
            pageLabel={`Page ${currentPage} of ${pageCount}`}
          />
        </>
      ) : null}

      {dialog?.kind === 'issue' ? (
        <ConfirmDialog
          title={`Issue ${dialog.po.po_number} to the vendor`}
          message="The order is marked as sent to the vendor. Receipts can be booked after this step."
          confirmLabel="Issue to vendor"
          busy={busy}
          onCancel={() => setDialog(null)}
          onConfirm={() => runAction(dialog.po, 'send_to_vendor')}
        >
          {actionError ? <ErrorSummary parsed={{ global: actionError }} /> : null}
        </ConfirmDialog>
      ) : null}

      {dialog && ['approve', 'reject', 'cancel'].includes(dialog.kind) ? (
        <Modal
          title={`${dialog.kind === 'approve' ? 'Approve' : dialog.kind === 'reject' ? 'Reject' : 'Cancel'} ${dialog.po.po_number}`}
          onClose={() => { if (!busy) setDialog(null); }}
        >
          <Field label={dialog.kind === 'cancel' ? 'Cancellation reason' : 'Reason'} required={dialog.kind !== 'approve'}>
            <textarea
              className="input" rows={3} value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-label={dialog.kind === 'cancel' ? 'Cancellation reason' : 'Reason'}
            />
          </Field>
          {actionError ? <ErrorSummary parsed={{ global: actionError }} /> : null}
          <div className="row-end">
            <button type="button" className="btn-ghost" onClick={() => setDialog(null)} disabled={busy}>Cancel</button>
            <button
              type="button" className={dialog.kind === 'cancel' ? 'btn-danger' : 'btn-primary'}
              disabled={busy || (dialog.kind !== 'approve' && !reason.trim())}
              onClick={() => runAction(dialog.po, dialog.kind)}
            >
              {busy ? 'Working…' : 'Confirm'}
            </button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

