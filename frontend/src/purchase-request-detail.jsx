import { useCallback, useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, ConfirmDialog, DataTable, EmptyState, ErrorSummary, Field, LoadingRows, Modal, PageHeader,
} from './components';
import { ProcurementAttachments } from './procurement-attachments';
import {
  APPROVAL_STATUS_LABELS,
  PURCHASE_REQUEST_STATUS_LABELS,
  actionAvailability,
  buildGoodsReceiptListUrl,
  buildPurchaseOrderListUrl,
  fetchAll,
  formatDate,
  formatDateTime,
  formatMoney,
  parseFieldErrors,
  procurementCapabilities,
  receiptSummary,
  statusBadgeVariant,
} from './procurement-utils';

function Row({ label, children }) {
  return (
    <div className="field">
      <span className="form-label">{label}</span>
      <div className="small">{children ?? '—'}</div>
    </div>
  );
}

/** Purchase request detail: overview, lines, approval trail, quotations,
 *  resulting purchase order and receipts. */
export function PurchaseRequestDetail({ id }) {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const [request, setRequest] = useState(null);
  const [orders, setOrders] = useState([]);
  const [receipts, setReceipts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [secondaryError, setSecondaryError] = useState('');
  const [dialog, setDialog] = useState(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [refreshAt, setRefreshAt] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    setSecondaryError('');
    try {
      const res = await api.get(`/procurement/purchase-requests/${id}/`);
      setRequest(res.data);
      setRefreshAt(new Date());
    } catch (e) {
      const parsed = parseFieldErrors(e);
      setError(parsed.global || 'This purchase request is unavailable.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  const loadSecondary = useCallback(async () => {
    try {
      const [poRows, grRows] = await Promise.all([
        fetchAll(buildPurchaseOrderListUrl({ purchase_request: id, page_size: 100 })),
        fetchAll(buildGoodsReceiptListUrl({ purchase_request: id, page_size: 100 })),
      ]);
      setOrders(poRows);
      setReceipts(grRows);
    } catch {
      setSecondaryError('Purchase orders and receipts could not be loaded.');
    }
  }, [id]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect
  useEffect(() => { loadSecondary(); }, [loadSecondary]); // eslint-disable-line react/set-state-in-effect

  const runAction = async (action) => {
    setBusy(true);
    setActionError('');
    try {
      const payload = { reason: reason.trim() };
      if (action === 'cancel') payload.version = request?.version;
      await api.post(`/procurement/purchase-requests/${id}/${action}/`, payload);
      setDialog(null);
      setReason('');
      setNotice('Purchase request updated.');
      await load();
    } catch (e) {
      const parsed = parseFieldErrors(e);
      const status = e?.response?.status;
      if (status === 409) {
        await load();
        setActionError('This request changed while you were working. The latest data is shown; review before retrying.');
      } else if (status === 403) {
        setActionError('You do not have permission to perform this action.');
      } else if (status === 404) {
        setActionError('This procurement record is unavailable or you no longer have access.');
      } else {
        setActionError(parsed.global || Object.values(parsed.fields)[0] || 'Action failed.');
      }
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingRows />;

  if (error) {
    return (
      <div>
        <PageHeader title="Purchase request" />
        <div className="error-summary" role="alert">{error}</div>
        <div className="row-gap">
          <button type="button" className="btn-primary" onClick={load}>Retry</button>
          <a className="btn-ghost" href="#/procurement/requests">Back to requests</a>
        </div>
      </div>
    );
  }

  if (!request) return null;

  const available = actionAvailability({ request, caps, userId: auth?.user?.id });
  const canCancel = !request.purchase_order_ref
    && ['draft', 'pending_approval', 'returned_for_correction', 'rejected', 'approved'].includes(request.status)
    && (request.requester === auth?.user?.id || caps.canApprovePurchaseRequest);
  const requestOrders = orders.filter((po) => po.purchase_request === request.id);
  const requestReceipts = receipts.filter((gr) => requestOrders.some((po) => po.id === gr.purchase_order));
  const selectedQuotation = (request.quotations || []).find((q) => q.is_selected);
  const history = request.history || [];

  return (
    <div>
      <PageHeader
        title={request.pr_number}
        sub={request.reason}
        actions={(
          <div className="row-gap">
            <a className="btn-ghost" href="#/procurement/requests">All requests</a>
            {available.editRequest ? (
              <a className="btn-ghost" href={`#/procurement/requests/${request.id}/edit`}>Edit draft</a>
            ) : null}
            {caps.canManageQuotations ? (
              <a className="btn-ghost" href={`#/procurement/requests/${request.id}/quotations`}>Quotations</a>
            ) : null}
          </div>
        )}
      />

      <div className="row-gap" aria-label="Request status">
        <span className={`badge badge-${statusBadgeVariant(request.status)}`}>
          {PURCHASE_REQUEST_STATUS_LABELS[request.status] ?? request.status}
        </span>
        {request.requires_system_admin_approval
          ? <span className="badge badge-amber">System Admin approval required</span> : null}
      </div>

      {notice ? <div className="success-summary" role="status">{notice}</div> : null}

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><h3>Overview</h3></div>
        <div className="panel-pad">
          <Row label="Requester">{request.requester_name || request.requester}</Row>
          <Row label="Department">{request.department ?? '—'}</Row>
          <Row label="Estimated total">{formatMoney(request.estimated_total)}</Row>
          <Row label="Approval state">
            {request.approver_name
              ? `${APPROVAL_STATUS_LABELS[request.approval_decision] ?? request.approval_decision} by ${request.approver_name}`
              : (APPROVAL_STATUS_LABELS[request.approval_decision] ?? 'Not decided')}
          </Row>
          <Row label="Approval note">{request.approval_reason || '—'}</Row>
          <Row label="Approved at">{formatDateTime(request.approved_at)}</Row>
          <Row label="Created">{formatDateTime(request.created_at)}</Row>
          <Row label="Last updated">{formatDateTime(request.updated_at)}</Row>
          <Row label="Data as of">{formatDateTime(refreshAt)}</Row>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><h3>Business justification</h3></div>
        <div className="panel-pad">
          <p style={{ whiteSpace: 'pre-wrap', marginTop: 0 }}>{request.reason || '—'}</p>
          {request.notes ? <p className="small muted" style={{ whiteSpace: 'pre-wrap' }}>{request.notes}</p> : null}
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <h3>Line items</h3>
        <DataTable
          columns={[
            { key: 'item_name', label: 'Item' },
            { key: 'description', label: 'Description', render: (r) => r.description || '—' },
            { key: 'quantity', label: 'Quantity' },
            { key: 'estimated_unit_price', label: 'Unit estimate', render: (r) => formatMoney(r.estimated_unit_price) },
            { key: 'estimated_total', label: 'Line estimate', render: (r) => formatMoney(r.estimated_total) },
            { key: 'suggested_vendor', label: 'Suggested vendor', render: (r) => r.suggested_vendor ?? '—' },
          ]}
          rows={request.items || []}
          keyOf={(r) => `item-${r.id}`}
          emptyTitle="No line items recorded."
          emptyHint="A request needs at least one line before it can be approved."
        />
      </div>

      <div style={{ marginTop: 24 }}>
        <h3>Quotations and vendor selection</h3>
        {secondaryError ? <div className="field-error" role="alert">{secondaryError}</div> : null}
        {(request.quotations || []).length === 0 ? (
          <EmptyState
            title="No quotations recorded."
            hint={request.status === 'approved'
              ? 'Add vendor quotations, then select the winning offer.'
              : 'Quotations can be collected once the request is approved.'}
            action={caps.canManageQuotations && request.status === 'approved'
              ? <a className="btn-primary" href={`#/procurement/requests/${request.id}/quotations`}>Manage quotations</a>
              : null}
          />
        ) : (
          <DataTable
            columns={[
              { key: 'vendor', label: 'Vendor', render: (r) => r.vendor_detail?.name ?? '—' },
              { key: 'quoted_amount', label: 'Quoted amount', render: (r) => formatMoney(r.quoted_amount) },
              { key: 'delivery_days', label: 'Delivery days', render: (r) => r.delivery_days ?? '—' },
              { key: 'warranty', label: 'Warranty', render: (r) => r.warranty || '—' },
              {
                key: 'selection',
                label: 'Selection',
                render: (r) => (r.is_selected
                  ? <Badge kind="status" value="approved" label="Selected" />
                  : <span className="small muted">Not selected</span>),
              },
            ]}
            rows={request.quotations}
            keyOf={(r) => `quotation-${r.id}`}
            emptyTitle="No quotations."
            emptyHint=""
          />
        )}
        {selectedQuotation ? (
          <p className="small">
            Selected vendor: <strong>{selectedQuotation.vendor_detail?.name}</strong>
            {selectedQuotation.selection_reason ? ` — ${selectedQuotation.selection_reason}` : ''}
          </p>
        ) : null}
      </div>

      <div style={{ marginTop: 24 }}>
        <h3>Purchase order</h3>
        {requestOrders.length === 0 ? (
          <EmptyState
            title="No purchase order yet."
            hint="An order is generated from an approved request with a selected vendor quotation."
          />
        ) : (
          <DataTable
            columns={[
              { key: 'po_number', label: 'PO', render: (r) => <a className="row-title" href={`#/procurement/orders/${r.id}`}>{r.po_number}</a> },
              { key: 'vendor', label: 'Vendor', render: (r) => r.vendor_detail?.name ?? '—' },
              { key: 'status', label: 'Status', render: (r) => r.status },
              { key: 'total', label: 'Total', render: (r) => formatMoney(r.total, r.currency) },
            ]}
            rows={requestOrders}
            keyOf={(r) => `po-${r.id}`}
            emptyTitle="No purchase order."
            emptyHint=""
          />
        )}
      </div>

      <div style={{ marginTop: 24 }}>
        <h3>Goods receipts</h3>
        {requestReceipts.length === 0 ? (
          <EmptyState title="No goods receipts yet." hint="Receipts appear here once deliveries are booked against the purchase order." />
        ) : (
          <DataTable
            columns={[
              { key: 'gr_number', label: 'Receipt', render: (r) => <a className="row-title" href={`#/procurement/receipts/${r.id}`}>{r.gr_number}</a> },
              { key: 'received_at', label: 'Received', render: (r) => formatDate(r.received_at) },
              { key: 'received_by_name', label: 'Received by', render: (r) => r.received_by_name || '—' },
              { key: 'accepted', label: 'Accepted', render: (r) => receiptSummary(r).accepted },
              { key: 'rejected', label: 'Rejected', render: (r) => receiptSummary(r).rejected },
              { key: 'damaged', label: 'Damaged', render: (r) => receiptSummary(r).damaged },
            ]}
            rows={requestReceipts}
            keyOf={(r) => `gr-${r.id}`}
            emptyTitle="No receipts."
            emptyHint=""
          />
        )}
      </div>

      <div style={{ marginTop: 24 }}>
        <h3>History</h3>
        {history.length === 0 ? (
          <EmptyState title="No history recorded." hint="Actions on this request will be listed here." />
        ) : (
          <DataTable
            columns={[
              { key: 'created_at', label: 'When', render: (r) => formatDateTime(r.created_at) },
              { key: 'action', label: 'Event', render: (r) => r.action },
              { key: 'actor_name', label: 'Actor', render: (r) => r.actor_name || '—' },
              { key: 'detail', label: 'Detail', render: (r) => r.detail || '—' },
            ]}
            rows={history}
            keyOf={(r) => `history-${r.id}`}
            emptyTitle="No history."
            emptyHint=""
          />
        )}
        <p className="small muted">History is read-only and cannot be edited from the interface.</p>
      </div>

      <div className="row-gap" style={{ marginTop: 16 }}>
        {available.submitRequest ? (
          <button type="button" className="btn-primary" onClick={() => { setReason(''); setActionError(''); setDialog('submit'); }}>
            Submit for approval
          </button>
        ) : null}
        {available.approveRequest ? (
          <button type="button" className="btn-primary" onClick={() => { setReason(''); setActionError(''); setDialog('approve'); }}>
            Approve
          </button>
        ) : null}
        {available.rejectRequest ? (
          <button type="button" className="btn-danger" onClick={() => { setReason(''); setActionError(''); setDialog('reject'); }}>
            Reject
          </button>
        ) : null}
        {available.returnRequest ? (
          <button type="button" className="btn-ghost" onClick={() => { setReason(''); setActionError(''); setDialog('return'); }}>
            Return for correction
          </button>
        ) : null}
        {canCancel ? (
          <button type="button" className="btn-danger" onClick={() => { setReason(''); setActionError(''); setDialog('cancel'); }}>
            Cancel request
          </button>
        ) : null}
      </div>

      <ProcurementAttachments
        parentType="purchase_request"
        parentId={request.id}
        canUpload={caps.canViewProcurement}
        title="Request attachments"
      />

      {dialog === 'submit' ? (
        <ConfirmDialog
          title={`Submit ${request.pr_number}`}
          message="This sends the request for approval. It cannot be edited while pending."
          confirmLabel="Submit"
          busy={busy}
          onCancel={() => setDialog(null)}
          onConfirm={() => runAction('submit')}
        >
          {actionError ? <ErrorSummary parsed={{ global: actionError }} /> : null}
        </ConfirmDialog>
      ) : null}

      {dialog === 'cancel' ? (
        <Modal
          title={`Cancel ${request.pr_number}`}
          onClose={() => { if (!busy) setDialog(null); }}
        >
          <p style={{ marginTop: 0 }}>
            Cancelling keeps the request and its history. It cannot be undone.
          </p>
          <Field label="Cancellation reason" required>
            <textarea
              className="input" rows={3} value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-label="Cancellation reason"
            />
          </Field>
          {actionError ? <ErrorSummary parsed={{ global: actionError }} /> : null}
          <div className="row-end">
            <button type="button" className="btn-ghost" onClick={() => setDialog(null)} disabled={busy}>Keep request</button>
            <button
              type="button" className="btn-danger"
              disabled={busy || !reason.trim()}
              onClick={() => runAction('cancel')}
            >
              {busy ? 'Working…' : 'Cancel request'}
            </button>
          </div>
        </Modal>
      ) : null}

      {dialog && dialog !== 'submit' && dialog !== 'cancel' ? (
        <Modal
          title={`${dialog === 'approve' ? 'Approve' : dialog === 'reject' ? 'Reject' : 'Return for correction'} ${request.pr_number}`}
          onClose={() => { if (!busy) setDialog(null); }}
        >
          <Field label="Reason" required={dialog !== 'approve'}>
            <textarea
              className="input" rows={3} value={reason}
              onChange={(e) => setReason(e.target.value)} aria-label="Reason"
            />
          </Field>
          {actionError ? <ErrorSummary parsed={{ global: actionError }} /> : null}
          <div className="row-end">
            <button type="button" className="btn-ghost" onClick={() => setDialog(null)} disabled={busy}>Cancel</button>
            <button
              type="button" className="btn-primary"
              disabled={busy || (dialog !== 'approve' && !reason.trim())}
              onClick={() => runAction(dialog === 'return' ? 'return_for_correction' : dialog)}
            >
              {busy ? 'Working…' : 'Confirm'}
            </button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
