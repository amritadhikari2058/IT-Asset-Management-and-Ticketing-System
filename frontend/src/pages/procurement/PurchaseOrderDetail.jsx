import { useCallback, useEffect, useState } from 'react';
import api from '../../api';
import { ProcurementAttachments } from './ProcurementAttachments';
import { useAuth } from '../../auth';
import {
  ConfirmDialog, DataTable, EmptyState, ErrorSummary, Field, LoadingRows, Modal, PageHeader,
} from '../../components';
import {
  APPROVAL_STATUS_LABELS,
  ITEM_TYPE_LABELS,
  PURCHASE_ORDER_STATUS_LABELS,
  actionAvailability,
  filenameFromContentDisposition,
  formatDate,
  formatDateTime,
  formatMoney,
  formatQuantity,
  itemTypeOf,
  parseFieldErrors,
  procurementCapabilities,
  receiptSummary,
  remainingQuantity,
  statusBadgeVariant,
} from '../../shared/procurement-utils';

function Info({ label, children }) {
  return (
    <div className="field">
      <span className="form-label">{label}</span>
      <div className="small">{children ?? '—'}</div>
    </div>
  );
}

/** Purchase order detail: terms, lines, delivery progress, receipts and
 *  approval trail. */
export function PurchaseOrderDetail({ id }) {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [dialog, setDialog] = useState(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [downloading, setDownloading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get(`/procurement/purchase-orders/${id}/`);
      setOrder(res.data);
    } catch (e) {
      const parsed = parseFieldErrors(e);
      setError(parsed.global || 'This purchase order is unavailable.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const runAction = async (action) => {
    setBusy(true);
    setActionError('');
    try {
      const payload = { reason: reason.trim() };
      if (action === 'cancel' || action === 'close') payload.version = order?.version;
      await api.post(`/procurement/purchase-orders/${id}/${action}/`, payload);
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
        setActionError('This order changed while you were working. The latest data is loaded; review before retrying.');
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
        <PageHeader title="Purchase order" />
        <div className="error-summary" role="alert">{error}</div>
        <div className="row-gap">
          <button type="button" className="btn-primary" onClick={load}>Retry</button>
          <a className="btn-ghost" href="#/procurement/orders">Back to orders</a>
        </div>
      </div>
    );
  }

  if (!order) return null;

  const manager = !!caps.canApprovePurchaseOrder;
  const available = actionAvailability({ purchaseOrder: order, caps, userId: auth?.user?.id });
  const lines = order.items || [];
  const orderedUnits = lines.reduce((sum, l) => sum + Number(l.quantity || 0), 0);
  const acceptedUnits = lines.reduce((sum, l) => sum + Number(l.received_qty || 0), 0);
  const rejectedUnits = lines.reduce((sum, l) => sum + Number(l.rejected_qty || 0), 0);
  const damagedUnits = lines.reduce((sum, l) => sum + Number(l.damaged_qty || 0), 0);
  const bookedUnits = acceptedUnits + rejectedUnits + damagedUnits;
  const cancelBlocked = bookedUnits > 0;
  const canCancel = manager && !cancelBlocked
    && ['draft', 'pending_approval', 'approved', 'sent_to_vendor'].includes(order.status);
  const canClose = manager
    && ['approved', 'sent_to_vendor', 'partially_received', 'received'].includes(order.status);

  const downloadPdf = async () => {
    setDownloading(true);
    setActionError('');
    try {
      const response = await api.get(
        `/procurement/purchase-orders/${id}/pdf/`, { responseType: 'blob' },
      );
      const filename = filenameFromContentDisposition(
        response.headers?.['content-disposition'], `PO-${order.po_number}.pdf`,
      );
      const url = window.URL.createObjectURL(response.data);
      try {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        window.URL.revokeObjectURL(url);
      }
    } catch (e) {
      const status = e?.response?.status;
      setActionError(status === 403
        ? 'You do not have permission to download this purchase order.'
        : 'Could not download the purchase order PDF.');
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div>
      <PageHeader
        title={order.po_number}
        sub={order.vendor_detail?.name ? `Vendor: ${order.vendor_detail.name}` : undefined}
        actions={(
          <div className="row-gap">
            <a className="btn-ghost" href="#/procurement/orders">All orders</a>
            {order.purchase_request ? (
              <a className="btn-ghost" href={`#/procurement/requests/${order.purchase_request}`}>View request</a>
            ) : null}
            <button type="button" className="btn-ghost" onClick={downloadPdf} disabled={downloading}>
              {downloading ? 'Preparing PDF…' : 'Download PDF'}
            </button>
            {available.createReceipt ? (
              <a className="btn-primary" href={`#/procurement/receipts/new?po=${order.id}`}>Create goods receipt</a>
            ) : null}
          </div>
        )}
      />

      <div className="row-gap">
        <span className={`badge badge-${statusBadgeVariant(order.status)}`}>
          {PURCHASE_ORDER_STATUS_LABELS[order.status] ?? order.status}
        </span>
        {order.requires_system_admin_approval
          ? <span className="badge badge-amber">System Admin approval required</span> : null}
      </div>

      {notice ? <div className="success-summary" role="status">{notice}</div> : null}

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><h3>Order</h3></div>
        <div className="panel-pad">
          <Info label="Vendor">{order.vendor_detail?.name}</Info>
          <Info label="Delivery address">{order.delivery_address || '—'}</Info>
          <Info label="Currency">{order.currency}</Info>
          <Info label="Subtotal">{formatMoney(order.subtotal, order.currency)}</Info>
          <Info label="Tax">{formatMoney(order.tax, order.currency)}</Info>
          <Info label="Discount">{formatMoney(order.discount, order.currency)}</Info>
          <Info label="Shipping">{formatMoney(order.shipping, order.currency)}</Info>
          <Info label="Total">{formatMoney(order.total, order.currency)}</Info>
          <Info label="Terms">{order.terms || '—'}</Info>
          <Info label="Notes">{order.notes || '—'}</Info>
          <Info label="Created by">{order.created_by_name || order.created_by}</Info>
          <Info label="Order date">{formatDateTime(order.created_at)}</Info>
          <Info label="Expected delivery">{formatDate(order.expected_delivery_date)}</Info>
          <Info label="Sent to vendor">{formatDateTime(order.sent_at)}</Info>
          <Info label="Closed at">{formatDateTime(order.closed_at)}</Info>
          <Info label="Closure reason">{order.closure_reason || '—'}</Info>
          <Info label="Cancellation reason">{order.cancellation_reason || '—'}</Info>
          <Info label="Last updated">{formatDateTime(order.updated_at)}</Info>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><h3>Approval</h3></div>
        <div className="panel-pad">
          <Info label="Decision">
            {order.approval_decision
              ? (APPROVAL_STATUS_LABELS[order.approval_decision] ?? order.approval_decision)
              : 'Not decided'}
          </Info>
          <Info label="Approver">{order.approver_name || '—'}</Info>
          <Info label="Reason">{order.approval_reason || '—'}</Info>
          <Info label="Approved at">{formatDateTime(order.approved_at)}</Info>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><h3>Delivery progress</h3></div>
        <div className="panel-pad">
          <p className="small" style={{ marginTop: 0 }}>
            {formatQuantity(acceptedUnits)} accepted · {formatQuantity(rejectedUnits)} rejected ·{' '}
            {formatQuantity(damagedUnits)} damaged · {formatQuantity(orderedUnits)} ordered
          </p>
          <div
            role="img"
            aria-label={`${bookedUnits} of ${orderedUnits} ordered units booked`}
            style={{ background: 'var(--neutral-bg, #eee)', height: 12, borderRadius: 6 }}
          >
            <div style={{
              width: `${orderedUnits ? Math.min(100, Math.round((bookedUnits / orderedUnits) * 100)) : 0}%`,
              background: 'var(--success, #16a34a)',
              height: 12,
              borderRadius: 6,
            }}
            />
          </div>
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <h3>Line items</h3>
        <DataTable
          columns={[
            { key: 'item_name', label: 'Item', render: (r) => <span className="row-title">{r.item_name}</span> },
            { key: 'type', label: 'Item type', render: (r) => ITEM_TYPE_LABELS[itemTypeOf(r)] },
            { key: 'quantity', label: 'Ordered', render: (r) => formatQuantity(r.quantity) },
            { key: 'received_qty', label: 'Received (accepted)', render: (r) => formatQuantity(r.received_qty) },
            { key: 'rejected_qty', label: 'Rejected', render: (r) => formatQuantity(r.rejected_qty) },
            { key: 'damaged_qty', label: 'Damaged', render: (r) => formatQuantity(r.damaged_qty) },
            { key: 'remaining', label: 'Remaining', render: (r) => formatQuantity(remainingQuantity(r)) },
            { key: 'unit_price', label: 'Unit price', render: (r) => formatMoney(r.unit_price, order.currency) },
            { key: 'tax', label: 'Tax', render: (r) => formatMoney(r.tax, order.currency) },
            { key: 'discount', label: 'Discount', render: (r) => formatMoney(r.discount, order.currency) },
            { key: 'total', label: 'Line total', render: (r) => formatMoney(r.total, order.currency) },
            { key: 'description', label: 'Description', render: (r) => r.description || '—' },
          ]}
          rows={lines}
          keyOf={(r) => `line-${r.id}`}
          emptyTitle="No line items."
          emptyHint="A purchase order line is created from the request's items."
        />
      </div>

      <div style={{ marginTop: 24 }}>
        <h3>Goods receipts</h3>
        {(order.goods_receipts || []).length === 0 ? (
          <EmptyState
            title="Nothing received yet."
            hint="Create a goods receipt when the vendor delivers."
            action={available.createReceipt
              ? <a className="btn-primary" href={`#/procurement/receipts/new?po=${order.id}`}>Create goods receipt</a>
              : null}
          />
        ) : (
          <DataTable
            columns={[
              { key: 'gr_number', label: 'Receipt', render: (r) => <a className="row-title" href={`#/procurement/receipts/${r.id}`}>{r.gr_number}</a> },
              { key: 'received_at', label: 'Received', render: (r) => formatDate(r.received_at) },
              { key: 'received_by_name', label: 'Received by', render: (r) => r.received_by_name || '—' },
              { key: 'delivery_note_number', label: 'Delivery note', render: (r) => r.delivery_note_number || '—' },
              { key: 'invoice_number', label: 'Invoice', render: (r) => r.invoice_number || '—' },
              { key: 'accepted', label: 'Accepted', render: (r) => receiptSummary(r).accepted },
              { key: 'rejected', label: 'Rejected', render: (r) => receiptSummary(r).rejected },
              { key: 'damaged', label: 'Damaged', render: (r) => receiptSummary(r).damaged },
            ]}
            rows={order.goods_receipts}
            keyOf={(r) => `receipt-${r.id}`}
            emptyTitle="No receipts."
            emptyHint=""
          />
        )}
      </div>

      <div style={{ marginTop: 24 }}>
        <h3>History</h3>
        {(order.history || []).length === 0 ? (
          <EmptyState title="No history recorded." hint="Approval and delivery events will appear here." />
        ) : (
          <DataTable
            columns={[
              { key: 'created_at', label: 'When', render: (r) => formatDateTime(r.created_at) },
              { key: 'action', label: 'Event' },
              { key: 'actor_name', label: 'Actor', render: (r) => r.actor_name || '—' },
              { key: 'detail', label: 'Detail', render: (r) => r.detail || '—' },
            ]}
            rows={order.history}
            keyOf={(r) => `history-${r.id}`}
            emptyTitle="No history."
            emptyHint=""
          />
        )}
      </div>

      <div className="row-gap" style={{ marginTop: 16 }}>
        {available.approveOrder ? (
          <button type="button" className="btn-primary" onClick={() => { setReason(''); setActionError(''); setDialog('approve'); }}>Approve</button>
        ) : null}
        {available.rejectOrder ? (
          <button type="button" className="btn-danger" onClick={() => { setReason(''); setActionError(''); setDialog('reject'); }}>Reject</button>
        ) : null}
        {available.issueOrder ? (
          <button type="button" className="btn-primary" onClick={() => { setActionError(''); setDialog('issue'); }}>Issue to vendor</button>
        ) : null}
        {canCancel ? (
          <button type="button" className="btn-danger" onClick={() => { setReason(''); setActionError(''); setDialog('cancel'); }}>Cancel order</button>
        ) : null}
        {canClose ? (
          <button type="button" className="btn-ghost" onClick={() => { setReason(''); setActionError(''); setDialog('close'); }}>Close order</button>
        ) : null}
      </div>

      {cancelBlocked && ['draft', 'pending_approval', 'approved', 'sent_to_vendor', 'partially_received'].includes(order.status) ? (
        <p className="small muted">
          This order already has receipt activity, so it cannot be cancelled.
          Close the remaining balance instead.
        </p>
      ) : null}

      <ProcurementAttachments
        parentType="purchase_order"
        parentId={order.id}
        canUpload={caps.canViewProcurement}
        title="Order attachments"
      />

      {dialog === 'cancel' || dialog === 'close' ? (
        <Modal
          title={`${dialog === 'cancel' ? 'Cancel' : 'Close'} ${order.po_number}`}
          onClose={() => { if (!busy) setDialog(null); }}
        >
          <p style={{ marginTop: 0 }}>
            {dialog === 'cancel'
              ? 'Cancelling keeps the order and every line. It cannot be undone and no further receipts are accepted.'
              : 'Closing stops further receipts. Ordered, received, rejected, damaged and outstanding quantities stay as they are.'}
          </p>
          <Field label={dialog === 'cancel' ? 'Cancellation reason' : 'Closure reason'} required={dialog === 'close' ? bookedUnits < orderedUnits : true}>
            <textarea
              className="input" rows={3} value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-label={dialog === 'cancel' ? 'Cancellation reason' : 'Closure reason'}
            />
          </Field>
          {actionError ? <ErrorSummary parsed={{ global: actionError }} /> : null}
          <div className="row-end">
            <button type="button" className="btn-ghost" onClick={() => setDialog(null)} disabled={busy}>Keep order</button>
            <button
              type="button" className={dialog === 'cancel' ? 'btn-danger' : 'btn-primary'}
              disabled={busy || !reason.trim()}
              onClick={() => runAction(dialog)}
            >
              {busy ? 'Working…' : dialog === 'cancel' ? 'Cancel order' : 'Close order'}
            </button>
          </div>
        </Modal>
      ) : null}

      {dialog === 'issue' ? (
        <ConfirmDialog
          title={`Issue ${order.po_number}`}
          message="The order is marked as sent to the vendor. Goods receipts can be booked after this step."
          confirmLabel="Issue to vendor"
          busy={busy}
          onCancel={() => setDialog(null)}
          onConfirm={() => runAction('send_to_vendor')}
        >
          {actionError ? <ErrorSummary parsed={{ global: actionError }} /> : null}
        </ConfirmDialog>
      ) : null}

      {dialog && dialog !== 'issue' && dialog !== 'cancel' && dialog !== 'close' ? (
        <Modal
          title={`${dialog === 'approve' ? 'Approve' : 'Reject'} ${order.po_number}`}
          onClose={() => { if (!busy) setDialog(null); }}
        >
          <Field label="Reason" required={dialog === 'reject'}>
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
              disabled={busy || (dialog === 'reject' && !reason.trim())}
              onClick={() => runAction(dialog)}
            >
              {busy ? 'Working…' : 'Confirm'}
            </button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

