import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import {
  Badge, ConfirmDialog, DataTable, ErrorSummary, Field, LoadingRows, Modal, PageHeader, Pager, PageSizeSelector,
} from '../../components';
import {
  PURCHASE_REQUEST_STATUS_LABELS,
  actionAvailability,
  buildPurchaseRequestListUrl,
  formatDateTime,
  formatMoney,
  parseFieldErrors,
  procurementCapabilities,
  safeResults,
  statusBadgeVariant,
} from '../../shared/procurement-utils';

// Page-size preference persisted in localStorage; fall back to DRF default 20.

function StatusPill({ status }) {
  return (
    <span className={`badge badge-${statusBadgeVariant(status)}`}>
      {PURCHASE_REQUEST_STATUS_LABELS[status] ?? status}
    </span>
  );
}

const STATUS_OPTIONS = Object.entries(PURCHASE_REQUEST_STATUS_LABELS);

/** Purchase request list: server-side search, filters, ordering, pagination. */
export function PurchaseRequestsPage() {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const requestIdRef = useRef(0);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  const [requests, setRequests] = useState([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    q: '', status: '', approval: '', hasPo: '', createdFrom: '', createdTo: '', ordering: '-created_at',
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
      return saved && Number.isFinite(n) && n > 0 && n <= 100 ? n : 20;
    } catch {
      return 20;
    }
  });

  const load = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError('');
    try {
      const response = await api.get(buildPurchaseRequestListUrl({
        page,
        page_size: pageSize,
        search: filters.q,
        status: filters.status,
        approval: filters.approval,
        has_po: filters.hasPo === 'yes' ? 'true' : filters.hasPo === 'no' ? 'false' : '',
        created_from: filters.createdFrom,
        created_to: filters.createdTo,
        ordering: filters.ordering,
      }));
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setRequests(safeResults(response.data));
      setCount(Number(response.data?.count ?? safeResults(response.data).length));
    } catch (e) {
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setError(parseFieldErrors(e).global || 'Could not load purchase requests.');
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

  const update = (key, value) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
  };

  const runAction = async (request, action) => {
    setBusy(true);
    setActionError('');
    try {
      const payload = { reason: reason.trim() };
      if (action === 'cancel') payload.version = request.version;
      await api.post(`/procurement/purchase-requests/${request.id}/${action}/`, payload);
      setDialog(null);
      setReason('');
      setNotice('Purchase request updated.');
      await load();
    } catch (e) {
      const status = e?.response?.status;
      const parsed = parseFieldErrors(e);
      if (status === 409) {
        await load();
        setActionError('This request changed while you were working. Reload and review before retrying.');
      } else if (status === 403) {
        setActionError('You do not have permission to perform this action.');
      } else {
        setActionError(parsed.global || Object.values(parsed.fields)[0] || 'Action failed.');
      }
    } finally {
      setBusy(false);
    }
  };

  const generateOrder = async (request) => {
    setBusy(true);
    setActionError('');
    try {
      const r = await api.post(`/procurement/purchase-orders/${request.id}/generate_from_pr/`, {});
      setDialog(null);
      setNotice(`Purchase order ${r.data.po_number} created.`);
      await load();
    } catch (e) {
      setActionError(parseFieldErrors(e).global || 'Could not create the purchase order.');
    } finally {
      setBusy(false);
    }
  };

  const canCancel = (request) => !request.purchase_order_ref
    && ['draft', 'pending_approval', 'returned_for_correction', 'rejected', 'approved'].includes(request.status)
    && (request.requester === auth?.user?.id || caps.canApprovePurchaseRequest);

  const columns = [
    {
      key: 'pr_number',
      label: 'Request',
      render: (r) => <a className="row-title" href={`#/procurement/requests/${r.id}`}>{r.pr_number}</a>,
    },
    {
      key: 'reason',
      label: 'Business justification',
      render: (r) => <span title={r.reason}>{(r.reason || '').slice(0, 60)}{(r.reason || '').length > 60 ? '…' : ''}</span>,
    },
    { key: 'requester_name', label: 'Requester', render: (r) => r.requester_name || '—' },
    { key: 'status', label: 'Status', render: (r) => <StatusPill status={r.status} /> },
    { key: 'estimated_total', label: 'Estimated total', render: (r) => formatMoney(r.estimated_total) },
    {
      key: 'approval',
      label: 'Approval',
      render: (r) => (
        <span>
          {r.approval_decision ? <Badge kind="status" value={r.approval_decision} /> : 'Not decided'}
          {r.requires_system_admin_approval
            ? <span className="small"> · System Admin required</span> : null}
        </span>
      ),
    },
    {
      key: 'vendor',
      label: 'Selected vendor',
      render: (r) => (r.quotations || []).find((q) => q.is_selected)?.vendor_detail?.name ?? '—',
    },
    {
      key: 'po',
      label: 'Purchase order',
      render: (r) => (r.purchase_order_ref
        ? <a href={`#/procurement/orders/${r.purchase_order_ref.id}`}>{r.purchase_order_ref.po_number}</a>
        : '—'),
    },
    { key: 'updated_at', label: 'Updated', render: (r) => formatDateTime(r.updated_at) },
    {
      key: 'actions',
      label: 'Actions',
      render: (r) => {
        const available = actionAvailability({ request: r, caps, userId: auth?.user?.id });
        const selected = (r.quotations || []).some((q) => q.is_selected);
        return (
          <div className="row-gap">
            <a className="btn-ghost btn-small" href={`#/procurement/requests/${r.id}`}>View</a>
            {available.editRequest ? (
              <a className="btn-ghost btn-small" href={`#/procurement/requests/${r.id}/edit`}>Edit</a>
            ) : null}
            {available.submitRequest ? (
              <button type="button" className="btn-small" onClick={() => { setReason(''); setActionError(''); setDialog({ kind: 'submit', request: r }); }}>
                Submit
              </button>
            ) : null}
            {available.approveRequest ? (
              <button type="button" className="btn-small" onClick={() => { setReason(''); setActionError(''); setDialog({ kind: 'approve', request: r }); }}>
                Approve
              </button>
            ) : null}
            {available.rejectRequest ? (
              <button type="button" className="btn-small" onClick={() => { setReason(''); setActionError(''); setDialog({ kind: 'reject', request: r }); }}>
                Reject
              </button>
            ) : null}
            {available.returnRequest ? (
              <button type="button" className="btn-small" onClick={() => { setReason(''); setActionError(''); setDialog({ kind: 'return', request: r }); }}>
                Return
              </button>
            ) : null}
            {caps.canManageQuotations && r.status === 'approved' ? (
              <a className="btn-ghost btn-small" href={`#/procurement/requests/${r.id}/quotations`}>Quotations</a>
            ) : null}
            {available.generateOrder && selected ? (
              <button type="button" className="btn-small" onClick={() => { setActionError(''); setDialog({ kind: 'generate', request: r }); }}>
                Create PO
              </button>
            ) : null}
            {canCancel(r) ? (
              <button type="button" className="btn-danger btn-small" onClick={() => { setReason(''); setActionError(''); setDialog({ kind: 'cancel', request: r }); }}>
                Cancel
              </button>
            ) : null}
          </div>
        );
      },
    },
  ];

  if (!caps.canViewProcurement) {
    return (
      <div>
        <PageHeader title="Purchase requests" />
        <div className="empty-state">
          <div className="empty-title">Access restricted</div>
          <div className="small">Procurement is available to IT staff only.</div>
        </div>
      </div>
    );
  }

  const reasonRequired = dialog && dialog.kind !== 'approve';

  return (
    <div>
      <PageHeader
        title="Purchase requests"
        sub="Requests, approvals and the route to a purchase order."
        actions={(
          <div className="row-gap">
            <a className="btn-ghost" href="#/procurement">Overview</a>
            {caps.canCreatePurchaseRequest ? <a className="btn-primary" href="#/procurement/requests/new">New request</a> : null}
          </div>
        )}
      />

      <div className="panel">
        <div className="panel-head"><h3>Filters</h3></div>
        <div className="panel-pad">
          <div className="row-gap">
            <Field label="Search">
              <input
                className="input" value={filters.q} placeholder="Number, justification, requester"
                onChange={(e) => update('q', e.target.value)}
              />
            </Field>
            <Field label="Status">
              <select className="input" value={filters.status} onChange={(e) => update('status', e.target.value)}>
                <option value="">Any status</option>
                {STATUS_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </Field>
            <Field label="Approval state">
              <select className="input" value={filters.approval} onChange={(e) => update('approval', e.target.value)}>
                <option value="">Any</option>
                <option value="approved">Approved</option>
                <option value="rejected">Rejected</option>
                <option value="returned">Returned</option>
              </select>
            </Field>
            <Field label="Purchase order">
              <select className="input" value={filters.hasPo} onChange={(e) => update('hasPo', e.target.value)}>
                <option value="">Any</option>
                <option value="yes">Has purchase order</option>
                <option value="no">No purchase order</option>
              </select>
            </Field>
            <Field label="Order by">
              <select className="input" value={filters.ordering} onChange={(e) => update('ordering', e.target.value)} aria-label="Order by">
                <option value="-created_at">Newest first</option>
                <option value="created_at">Oldest first</option>
                <option value="estimated_total">Estimated total</option>
                <option value="pr_number">Request number</option>
                <option value="updated_at">Last updated</option>
              </select>
            </Field>
            <Field label="Created from">
              <input type="date" className="input" value={filters.createdFrom} onChange={(e) => update('createdFrom', e.target.value)} />
            </Field>
            <Field label="Created to">
              <input type="date" className="input" value={filters.createdTo} onChange={(e) => update('createdTo', e.target.value)} />
            </Field>
          </div>
          <div className="row-gap" style={{ marginTop: 8 }}>
            <span className="small muted">{count} request(s)</span>
            <button type="button" className="btn-ghost btn-small" onClick={load} disabled={loading}>Refresh</button>
          </div>
        </div>
      </div>

      {notice ? <div className="success-summary" role="status">{notice}</div> : null}
      {actionError && !dialog ? <div className="field-error" role="alert">{actionError}</div> : null}

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
            columns={columns}
            rows={requests}
            keyOf={(r) => `request-${r.id}`}
            emptyTitle="No purchase requests match these filters."
            emptyHint="Adjust the filters or create a new request."
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

      {dialog?.kind === 'submit' ? (
        <ConfirmDialog
          title={`Submit ${dialog.request.pr_number}`}
          message="This sends the request for approval. It can no longer be edited while pending."
          confirmLabel="Submit for approval"
          busy={busy}
          onCancel={() => setDialog(null)}
          onConfirm={() => runAction(dialog.request, 'submit')}
        />
      ) : null}

      {dialog && ['approve', 'reject', 'return', 'cancel'].includes(dialog.kind) ? (
        <Modal
          title={`${dialog.kind === 'approve' ? 'Approve' : dialog.kind === 'reject' ? 'Reject' : dialog.kind === 'cancel' ? 'Cancel' : 'Return for correction'} ${dialog.request.pr_number}`}
          onClose={() => { if (!busy) setDialog(null); }}
        >
          <p style={{ marginTop: 0 }}>
            {dialog.kind === 'approve'
              ? 'Approval is recorded against your account and cannot be undone from this screen.'
              : dialog.kind === 'cancel'
                ? 'Cancelling keeps the request and its history. It cannot be undone.'
                : 'The requester will see this reason in the request history.'}
          </p>
          <Field
            label={dialog.kind === 'cancel' ? 'Cancellation reason' : 'Reason'}
            required={reasonRequired}
            error={reasonRequired && actionError ? actionError : ''}
          >
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
              disabled={busy || (reasonRequired && !reason.trim())}
              onClick={() => runAction(dialog.request, dialog.kind === 'return' ? 'return_for_correction' : dialog.kind)}
            >
              {busy ? 'Working…' : dialog.kind === 'cancel' ? 'Cancel request' : 'Confirm'}
            </button>
          </div>
        </Modal>
      ) : null}

      {dialog?.kind === 'generate' ? (
        <ConfirmDialog
          title={`Create purchase order for ${dialog.request.pr_number}`}
          message="The selected quotation's vendor is used and the order is created pending approval."
          confirmLabel="Create purchase order"
          busy={busy}
          onCancel={() => setDialog(null)}
          onConfirm={() => generateOrder(dialog.request)}
        >
          {actionError ? <div className="field-error" role="alert">{actionError}</div> : null}
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

