import { useCallback, useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { ProcurementAttachments } from './procurement-attachments';
import {
  ConfirmDialog, DataTable, EmptyState, ErrorSummary, Field, LoadingRows, PageHeader,
} from './components';
import {
  buildAssetReceiptItemsUrl,
  buildPurchaseOrderListUrl,
  fetchAll,
  formatDate,
  formatDateTime,
  formatMoney,
  formatQuantity,
  parseFieldErrors,
  procurementCapabilities,
  receiptSummary,
  remainingQuantity,
} from './procurement-utils';

const RECEIVABLE_STATUSES = ['approved', 'sent_to_vendor', 'partially_received'];
const QUANTITY_FIELDS = ['received', 'rejected', 'damaged'];

function blankLine(line) {
  return {
    id: line.id,
    item_name: line.item_name,
    description: line.description,
    ordered: Number(line.quantity || 0),
    alreadyAccepted: Number(line.received_qty || 0),
    alreadyRejected: Number(line.rejected_qty || 0),
    alreadyDamaged: Number(line.damaged_qty || 0),
    remaining: remainingQuantity(line),
    stock_item: line.stock_item,
    is_serialized: !!line.is_serialized,
    received: '',
    rejected: '',
    damaged: '',
    rejection_reason: '',
    damage_notes: '',
  };
}

function validateLine(line) {
  const errors = {};
  const received = line.received === '' ? 0 : Number(line.received);
  const rejected = line.rejected === '' ? 0 : Number(line.rejected);
  const damaged = line.damaged === '' ? 0 : Number(line.damaged);
  for (const [field, value] of [['received', received], ['rejected', rejected], ['damaged', damaged]]) {
    if (!Number.isInteger(value) || value < 0) errors[field] = 'Enter a whole number of zero or more.';
  }
  if (rejected + damaged > received) {
    errors.rejected = 'Rejected plus damaged cannot exceed the quantity received.';
  }
  if (received > line.remaining) {
    errors.received = `Only ${line.remaining} unit(s) remain to be received on this line.`;
  }
  if (rejected > 0 && !line.rejection_reason.trim()) {
    errors.rejection_reason = 'A reason is required for rejected units.';
  }
  if (damaged > 0 && !line.damage_notes.trim()) {
    errors.damage_notes = 'Describe the damage for damaged units.';
  }
  return errors;
}

/** Goods receipt form: choose an issued order, enter arrivals, then post. */
export function GoodsReceiptForm({ id, poId }) {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const isView = !!id;
  const [orders, setOrders] = useState([]);
  const [orderId, setOrderId] = useState(poId ? String(poId) : '');
  const [order, setOrder] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [assetItems, setAssetItems] = useState([]);
  const [lines, setLines] = useState([]);
  const [meta, setMeta] = useState({ delivery_note_number: '', invoice_number: '', notes: '' });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lineErrors, setLineErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submittedReceipt, setSubmittedReceipt] = useState(null);

  const loadOrders = useCallback(async () => {
    try {
      const rows = await fetchAll(buildPurchaseOrderListUrl());
      setOrders(rows.filter((po) => RECEIVABLE_STATUSES.includes(po.status)));
    } catch {
      setOrders([]);
    }
  }, []);

  const loadOrder = useCallback(async (selectedId) => {
    if (!selectedId) { setOrder(null); setLines([]); return; }
    try {
      const res = await api.get(`/procurement/purchase-orders/${selectedId}/`);
      setOrder(res.data);
      setLines((res.data.items || []).map(blankLine));
      setLineErrors({});
    } catch (e) {
      setGlobalError(parseFieldErrors(e).global || 'Could not load the purchase order.');
    }
  }, []);

  const loadReceipt = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get(`/procurement/goods-receipts/${id}/`);
      setReceipt(res.data);
      const [poRes, assetRes] = await Promise.all([
        api.get(`/procurement/purchase-orders/${res.data.purchase_order}/`),
        api.get(buildAssetReceiptItemsUrl({ goods_receipt: id, page_size: 100 }))
          .catch(() => ({ data: { results: [] } })),
      ]);
      setOrder(poRes.data);
      setAssetItems(assetRes.data?.results ?? assetRes.data ?? []);
    } catch (e) {
      setError(parseFieldErrors(e).global || 'This goods receipt is unavailable.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    if (isView) { loadReceipt(); return; }
    setLoading(true);
    (async () => {
      await loadOrders();
      if (poId) await loadOrder(poId);
      setLoading(false);
    })();
  }, [isView, loadReceipt, loadOrders, loadOrder, poId]);

  const setLine = (lineId, field, value) => {
    setLines((rows) => rows.map((row) => (row.id === lineId ? { ...row, [field]: value } : row)));
  };

  const planned = useMemo(() => lines
    .map((line) => {
      const received = line.received === '' ? 0 : Number(line.received);
      const rejected = line.rejected === '' ? 0 : Number(line.rejected);
      const damaged = line.damaged === '' ? 0 : Number(line.damaged);
      return { ...line, received, rejected, damaged, accepted: Math.max(0, received - rejected - damaged) };
    })
    .filter((line) => line.received > 0), [lines]);

  const anyPlanned = planned.length > 0;

  /** Validate every line, then open the confirmation for a clean receipt. */
  const review = () => {
    const errors = {};
    for (const line of lines) {
      const problems = validateLine(line);
      if (Object.keys(problems).length) errors[line.id] = problems;
    }
    setLineErrors(errors);
    if (Object.keys(errors).length) {
      setGlobalError('Fix the highlighted receipt lines before posting.');
      return;
    }
    if (!anyPlanned) {
      setGlobalError('Enter the quantity received for at least one line.');
      return;
    }
    setGlobalError('');
    setConfirming(true);
  };

  const post = async () => {
    if (busy) return;
    setBusy(true);
    setGlobalError('');
    let created = null;
    try {
      const grRes = await api.post('/procurement/goods-receipts/', {
        purchase_order: Number(orderId),
        delivery_note_number: meta.delivery_note_number.trim(),
        invoice_number: meta.invoice_number.trim(),
        notes: meta.notes.trim(),
      });
      created = grRes.data;
      for (const line of planned) {
        const noteParts = [];
        if (line.rejection_reason.trim()) noteParts.push(`Rejection reason: ${line.rejection_reason.trim()}`);
        if (line.damage_notes.trim()) noteParts.push(`Damage: ${line.damage_notes.trim()}`);
        await api.post('/procurement/goods-receipt-items/', {
          goods_receipt: created.id,
          purchase_order_item: line.id,
          quantity_received: line.received,
          quantity_rejected: line.rejected,
          quantity_damaged: line.damaged,
          accepted_quantity: line.accepted,
          rejection_reason: line.rejection_reason.trim(),
          damage_notes: line.damage_notes.trim(),
          notes: noteParts.join(' · '),
        });
      }
      setConfirming(false);
      setSubmitted(true);
      setSubmittedReceipt(created);
      window.location.hash = `#/procurement/receipts/${created.id}`;
    } catch (e) {
      const status = e?.response?.status;
      const parsed = parseFieldErrors(e);
      if (status === 409) {
        await loadOrder(orderId);
        setGlobalError('This order changed while you were working. Balances were reloaded — review the quantities before posting again.');
      } else if (status === 403) {
        setGlobalError('You do not have permission to perform this action.');
      } else if (created) {
        setGlobalError(`Receipt ${created.gr_number} was created but some lines could not be booked: ${parsed.global || Object.values(parsed.fields)[0] || 'unknown error'}. Open the receipt to review it.`);
      } else {
        setGlobalError(parsed.global || Object.values(parsed.fields)[0] || 'Could not record the goods receipt.');
      }
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  };

  if (!caps.canViewProcurement) {
    return <EmptyState title="Access restricted" hint="Procurement is available to IT staff only." />;
  }

  if (loading) return <LoadingRows />;

  if (error) {
    return (
      <div>
        <PageHeader title="Goods receipt" />
        <div className="error-summary" role="alert">{error}</div>
        <div className="row-gap">
          <button type="button" className="btn-primary" onClick={loadReceipt}>Retry</button>
          <a className="btn-ghost" href="#/procurement/receipts">Back to receipts</a>
        </div>
      </div>
    );
  }

  if (isView) {
    if (!receipt) return null;
    const summary = receiptSummary(receipt);
    const discrepancyLines = (receipt.items || []).filter(
      (line) => Number(line.quantity_rejected) > 0 || Number(line.quantity_damaged) > 0,
    );
    return (
      <div>
        <PageHeader
          title={receipt.gr_number}
          sub={order ? `Purchase order ${order.po_number}` : undefined}
          actions={(
            <div className="row-gap">
              <a className="btn-ghost" href="#/procurement/receipts">All receipts</a>
              {order ? <a className="btn-ghost" href={`#/procurement/orders/${order.id}`}>Purchase order</a> : null}
            </div>
          )}
        />

        <div className="panel">
          <div className="panel-head"><h3>Receipt details</h3></div>
          <div className="panel-pad">
            <div className="field"><span className="form-label">Received</span><div className="small">{formatDateTime(receipt.received_at)}</div></div>
            <div className="field"><span className="form-label">Received by</span><div className="small">{receipt.received_by_name || '—'}</div></div>
            <div className="field"><span className="form-label">Delivery note</span><div className="small">{receipt.delivery_note_number || '—'}</div></div>
            <div className="field"><span className="form-label">Invoice</span><div className="small">{receipt.invoice_number || '—'}</div></div>
            <div className="field"><span className="form-label">Notes</span><div className="small">{receipt.notes || '—'}</div></div>
            <div className="field">
              <span className="form-label">Quantities</span>
              <div className="small">
                {summary.accepted} accepted · {summary.rejected} rejected · {summary.damaged} damaged
              </div>
            </div>
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          <h3>Receipt lines</h3>
          <DataTable
            columns={[
              {
                key: 'line',
                label: 'Purchase order line',
                render: (r) => order?.items?.find((line) => line.id === r.purchase_order_item)?.item_name
                  ?? `Line ${r.purchase_order_item}`,
              },
              { key: 'quantity_received', label: 'Received', render: (r) => formatQuantity(r.quantity_received) },
              {
                key: 'accepted',
                label: 'Accepted',
                render: (r) => formatQuantity(
                  r.accepted_quantity
                  ?? Math.max(0, Number(r.quantity_received) - Number(r.quantity_rejected) - Number(r.quantity_damaged)),
                ),
              },
              { key: 'quantity_rejected', label: 'Rejected', render: (r) => formatQuantity(r.quantity_rejected) },
              { key: 'quantity_damaged', label: 'Damaged', render: (r) => formatQuantity(r.quantity_damaged) },
              { key: 'discrepancy_status', label: 'Discrepancy', render: (r) => (r.discrepancy_status || 'none').replace(/_/g, ' ') },
              { key: 'inspection_status', label: 'Inspection', render: (r) => (r.inspection_status || '—').replace(/_/g, ' ') },
              { key: 'notes', label: 'Legacy notes', render: (r) => r.notes || '—' },
            ]}
            rows={receipt.items || []}
            keyOf={(r) => `gr-line-${r.id}`}
            emptyTitle="No receipt lines."
            emptyHint=""
          />
        </div>

        <div style={{ marginTop: 24 }}>
          <h3>Discrepancies</h3>
          {discrepancyLines.length === 0 ? (
            <EmptyState title="No discrepancies recorded." hint="Every line was accepted in full." />
          ) : (
            <>
              <DataTable
                columns={[
                  {
                    key: 'item',
                    label: 'PO line',
                    render: (r) => order?.items?.find((line) => line.id === r.purchase_order_item)?.item_name
                      ?? `Line ${r.purchase_order_item}`,
                  },
                  { key: 'quantity_rejected', label: 'Rejected', render: (r) => formatQuantity(r.quantity_rejected) },
                  { key: 'quantity_damaged', label: 'Damaged', render: (r) => formatQuantity(r.quantity_damaged) },
                  { key: 'rejection_reason', label: 'Rejection reason', render: (r) => r.rejection_reason || '—' },
                  { key: 'damage_notes', label: 'Damage notes', render: (r) => r.damage_notes || '—' },
                  { key: 'notes', label: 'Legacy notes', render: (r) => r.notes || '—' },
                  { key: 'vendor', label: 'Vendor', render: () => order?.vendor_detail?.name ?? '—' },
                ]}
                rows={discrepancyLines}
                keyOf={(r) => `disc-${r.id}`}
                emptyTitle="No discrepancies."
                emptyHint=""
              />
              <p className="small muted">
                Discrepancy recorded for follow-up. Vendor return processing is not included in this release.
              </p>
            </>
          )}
        </div>

        <div style={{ marginTop: 24 }}>
          <h3>Inventory and asset results</h3>
          <DataTable
            columns={[
              {
                key: 'item',
                label: 'PO line',
                render: (r) => order?.items?.find((line) => line.id === r.purchase_order_item)?.item_name
                  ?? `Line ${r.purchase_order_item}`,
              },
              {
                key: 'type',
                label: 'Item type',
                render: (r) => {
                  const poLine = order?.items?.find((line) => line.id === r.purchase_order_item);
                  return poLine ? (poLine.is_serialized ? 'Serialized asset' : 'Item') : '—';
                },
              },
              {
                key: 'accepted',
                label: 'Accepted quantity',
                render: (r) => Math.max(0, Number(r.quantity_received) - Number(r.quantity_rejected) - Number(r.quantity_damaged)),
              },
              {
                key: 'stock',
                label: 'Linked stock item',
                render: (r) => {
                  const poLine = order?.items?.find((line) => line.id === r.purchase_order_item);
                  return poLine?.stock_item
                    ? <a href={`#/inventory/items/${poLine.stock_item}`}>Stock item #{poLine.stock_item}</a>
                    : 'Not linked';
                },
              },
            ]}
            rows={receipt.items || []}
            keyOf={(r) => `inv-${r.id}`}
            emptyTitle="No lines."
            emptyHint=""
          />
          <p className="small muted">
            Only accepted quantities enter normal inventory. Rejected and damaged units never
            enter available stock, and accepted serialized units create pending asset
            registration records.
          </p>
        </div>

        <div style={{ marginTop: 24 }}>
          <h3>Pending asset registration</h3>
          {assetItems.length === 0 ? (
            <EmptyState
              title="No pending asset units from this receipt."
              hint="Pending rows appear for accepted serialized units only."
            />
          ) : (
            <DataTable
              columns={[
                { key: 'item_name', label: 'Item' },
                { key: 'sequence', label: 'Unit' },
                { key: 'status', label: 'Status', render: (r) => (r.status || '').replace(/_/g, ' ') },
                { key: 'purchase_cost', label: 'Unit cost', render: (r) => formatMoney(r.purchase_cost, order?.currency) },
                {
                  key: 'asset',
                  label: 'Registered asset',
                  render: (r) => (r.asset
                    ? <a href={`#/assets/${r.asset}`}>{r.asset_tag || `Asset ${r.asset}`}</a>
                    : '—'),
                },
              ]}
              rows={assetItems}
              keyOf={(r) => `asset-item-${r.id}`}
              emptyTitle="No pending units."
              emptyHint=""
            />
          )}
          <p className="small muted">
            <a href="#/procurement/assets">Open asset registration →</a>
            {' '}to register one asset per accepted serialized unit.
          </p>
        </div>

        <ProcurementAttachments
          parentType="goods_receipt"
          parentId={receipt.id}
          canUpload={caps.canViewProcurement}
          title="Receipt attachments"
        />
      </div>
    );
  }

  const selectableOrders = orders;

  return (
    <div>
      <PageHeader
        title="Record goods receipt"
        sub="Book what actually arrived against an issued purchase order."
        actions={<a className="btn-ghost" href="#/procurement/receipts">Cancel</a>}
      />

      {globalError ? <ErrorSummary parsed={{ global: globalError }} /> : null}

      {submitted && submittedReceipt ? (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="panel-head"><h3>Receipt recorded</h3></div>
          <div className="panel-pad">
            <p className="small">
              Goods receipt <strong>{submittedReceipt.gr_number}</strong> was recorded against{' '}
              <strong>{order?.po_number}</strong>. The receipt is now read-only.
            </p>
            <div className="row-gap" style={{ marginTop: 12 }}>
              <a className="btn-primary" href={`#/procurement/receipts/${submittedReceipt.id}`}>View receipt</a>
              <a className="btn-ghost" href="#/procurement/receipts">All receipts</a>
              <button type="button" className="btn-ghost" onClick={() => { setSubmitted(false); setSubmittedReceipt(null); setGlobalError(''); }}>Record another receipt</button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="panel">
        <div className="panel-head"><h3>Receipt details</h3></div>
        <div className="panel-pad">
          <Field label="Purchase order" required>
            <select
              className="input" value={orderId}
              onChange={(e) => { setOrderId(e.target.value); loadOrder(e.target.value); }}
              aria-label="Purchase order"
            >
              <option value="">Select a purchase order…</option>
              {selectableOrders.map((po) => (
                <option key={po.id} value={po.id}>
                  {po.po_number} — {po.vendor_detail?.name} ({po.status.replace(/_/g, ' ')})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Delivery note number">
            <input
              className="input" value={meta.delivery_note_number}
              onChange={(e) => setMeta((m) => ({ ...m, delivery_note_number: e.target.value }))}
              aria-label="Delivery note number"
            />
          </Field>
          <Field label="Invoice number">
            <input
              className="input" value={meta.invoice_number}
              onChange={(e) => setMeta((m) => ({ ...m, invoice_number: e.target.value }))}
              aria-label="Invoice number"
            />
          </Field>
          <Field label="Notes">
            <textarea
              className="input" rows={2} value={meta.notes}
              onChange={(e) => setMeta((m) => ({ ...m, notes: e.target.value }))}
              aria-label="Receipt notes"
            />
          </Field>
        </div>
      </div>

      {!order ? (
        <EmptyState
          title="Select a purchase order."
          hint="Only approved, issued or partially received orders can accept a new receipt."
        />
      ) : (
        <div style={{ marginTop: 16 }}>
          <h3>Lines on {order.po_number}</h3>
          <p className="small muted">
            Vendor {order.vendor_detail?.name} · total {formatMoney(order.total, order.currency)} · ordered{' '}
            {formatDate(order.created_at)}
          </p>
          {lines.length === 0 ? (
            <EmptyState title="This order has no lines." hint="A receipt needs at least one order line." />
          ) : (
            lines.map((line) => {
              const problems = lineErrors[line.id] || {};
              return (
                <div key={line.id} className="panel" style={{ marginBottom: 12 }}>
                  <div className="panel-head">
                    <h4>{line.item_name}</h4>
                  </div>
                  <div className="panel-pad">
                    <p className="small" style={{ marginTop: 0 }}>
                      Ordered {formatQuantity(line.ordered)} · previously accepted {formatQuantity(line.alreadyAccepted)}
                      {' · previously rejected '}{formatQuantity(line.alreadyRejected)}
                      {' · previously damaged '}{formatQuantity(line.alreadyDamaged)}
                      {' · remaining '}{formatQuantity(line.remaining)}
                      {line.stock_item ? <> · <a href={`#/inventory/items/${line.stock_item}`}>linked stock item</a></> : null}
                    </p>
                    <div className="row-gap">
                      {QUANTITY_FIELDS.map((field) => (
                        <Field
                          key={field}
                          label={field === 'received' ? 'Quantity received' : field === 'rejected' ? 'Rejected' : 'Damaged'}
                          error={problems[field]}
                        >
                          <input
                            type="number" min="0" step="1" className="input"
                            value={line[field]}
                            onChange={(e) => setLine(line.id, field, e.target.value)}
                            aria-label={`${field} quantity for ${line.item_name}`}
                            disabled={line.remaining === 0}
                          />
                        </Field>
                      ))}
                    </div>
                    {Number(line.rejected) > 0 ? (
                      <Field label="Rejection reason" required error={problems.rejection_reason}>
                        <input
                          className="input" value={line.rejection_reason}
                          onChange={(e) => setLine(line.id, 'rejection_reason', e.target.value)}
                          aria-label={`Rejection reason for ${line.item_name}`}
                        />
                      </Field>
                    ) : null}
                    {Number(line.damaged) > 0 ? (
                      <Field label="Damage notes" required error={problems.damage_notes}>
                        <input
                          className="input" value={line.damage_notes}
                          onChange={(e) => setLine(line.id, 'damage_notes', e.target.value)}
                          aria-label={`Damage notes for ${line.item_name}`}
                        />
                      </Field>
                    ) : null}
                  </div>
                </div>
              );
            })
          )}
          <div className="row-gap">
            <button
              type="button" className="btn-primary"
              onClick={review}
              disabled={busy || submitted || lines.length === 0 || !anyPlanned}
            >
              Review and record receipt
            </button>
            <span className="small muted">The procurement API records the receipt immediately — there is no draft receipt.</span>
          </div>
        </div>
      )}

      {confirming ? (
        <ConfirmDialog
          title="Record this goods receipt?"
          message="Review the arrivals below. Recording books the receipt against the purchase order and updates the outstanding balances."
          confirmLabel={busy ? 'Recording…' : 'Record receipt'}
          busy={busy}
          onCancel={() => setConfirming(false)}
          onConfirm={post}
        >
          <ul className="small">
            {planned.map((line) => (
              <li key={`planned-${line.id}`}>
                {line.item_name}: {line.accepted} accepted, {line.rejected} rejected, {line.damaged} damaged
                {line.stock_item ? ' (linked stock item will keep its own balance)' : ''}
                {line.is_serialized ? ' — serialized item ready for asset registration' : ''}
              </li>
            ))}
          </ul>
          <p className="small muted">
            Rejected and damaged quantities are recorded as discrepancies and are not accepted.
            Recording this receipt updates accepted Inventory and creates pending Asset
            registration records. The receipt becomes read-only once posted.
          </p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
