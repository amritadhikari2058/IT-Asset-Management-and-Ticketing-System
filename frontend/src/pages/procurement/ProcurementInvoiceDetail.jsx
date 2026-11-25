import { useCallback, useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import {
  safeResults, formatMoney, statusLabel, parseFieldErrors,
  procurementCapabilities, invoiceActionState, procurementErrorText, recordConflictText,
} from '../../shared/procurement-utils';

function Table({ columns, rows, empty = 'No records.' }) {
  if (!rows?.length) return <div className="empty-state"><div className="empty-title">{empty}</div></div>;
  return <div className="table-wrap"><table className="table"><thead><tr>{columns.map(c => <th key={c.key || c.label}>{c.label}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={row.id ?? i}>{columns.map(c => <td key={c.key || c.label}>{typeof c.render === 'function' ? c.render(row) : row[c.key]}</td>)}</tr>)}</tbody></table></div>;
}

function ActionError({ error }) {
  if (!error) return null;
  return (
    <div role="alert" className="error">
      {error.global && <div>{error.global}</div>}
      {Object.keys(error.fields || {}).length > 0 && (
        <ul>
          {Object.entries(error.fields).map(([field, message]) => (
            <li key={field}><strong>{field.replace(/_/g, ' ')}:</strong> {message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

const EMPTY_LINE = { purchase_order_item: '', goods_receipt_item: '', description: '', invoiced_quantity: '1', unit_price: '0.00', discount_amount: '0.00', tax_rate: '0', tax_amount: '0.00' };

export function ProcurementInvoiceDetail({ id }) {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const userId = auth?.user?.id;
  const [inv, setInv] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState('');
  const [line, setLine] = useState(EMPTY_LINE);
  const [poItems, setPoItems] = useState([]);
  const [grItems, setGrItems] = useState([]);

  const load = useCallback(async () => {
    try {
      const r = await api.get(`/procurement/supplier-invoices/${id}/`);
      setInv(r.data);
      const rd = await api.get(`/procurement/supplier-invoices/${id}/readiness/`);
      setReadiness(rd.data);
      return r.data;
    } catch (e) {
      setLoadError(procurementErrorText(e, 'Failed to load invoice.'));
      return null;
    }
  }, [id]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect
  useEffect(() => {
    if (!inv?.purchase_order) return;
    api.get(`/procurement/purchase-order-items/?purchase_order=${inv.purchase_order}`).then(r => setPoItems(safeResults(r.data))).catch(() => {});
    api.get('/procurement/goods-receipt-items/?page_size=200').then(r => setGrItems(safeResults(r.data))).catch(() => {});
  }, [inv?.purchase_order]);

  function errorFrom(e) {
    const parsed = parseFieldErrors(e);
    const status = e?.response?.status;
    if (status === 403 || status === 404 || (!parsed?.global && !Object.keys(parsed?.fields || {}).length)) {
      return { global: procurementErrorText(e, 'Action failed.') };
    }
    return parsed;
  }

  async function act(action, body = {}) {
    setBusy(action); setError(null);
    try {
      await api.post(`/procurement/supplier-invoices/${id}/${action}/`, body);
      await load();
    } catch (e) {
      if (e?.response?.status === 409) {
        setError({ global: recordConflictText('invoice') });
        await load();
      } else {
        setError(errorFrom(e));
      }
    } finally { setBusy(''); }
  }

  async function addLine(e) {
    e.preventDefault(); setBusy('line'); setError(null);
    try {
      await api.post('/procurement/supplier-invoice-lines/', { ...line, invoice: id, goods_receipt_item: line.goods_receipt_item || null });
      setLine(EMPTY_LINE);
      await load();
    } catch (e2) {
      setError(errorFrom(e2));
    } finally { setBusy(''); }
  }

  if (!inv) return <p className="page-loading">{loadError ? <span role="alert">{loadError}</span> : 'Loading invoice…'}</p>;
  const actions = invoiceActionState(inv, caps, userId);
  const isSystemAdmin = !!(auth?.isSystemAdmin || auth?.role === 'system_admin' || auth?.isSuperuser);
  const systemAdminRequired = !!inv.requires_system_admin_approval && !isSystemAdmin;
  return (
    <div>
      <div className="page-header"><h1>Invoice {inv.invoice_number}</h1><div className="small">Status: {statusLabel(inv.status)} | Match: {statusLabel(inv.latest_match?.overall_status || 'unmatched')} | Payment: {statusLabel(inv.payment_status)}</div></div>
      <ActionError error={error} />
      {systemAdminRequired && <div className="small" role="note">This invoice requires System Admin approval (high value, currency, or variance threshold).</div>}
      <div className="button-row" style={{flexWrap:'wrap',gap:'8px'}}>
        {actions.canSubmit && <button disabled={!!busy} onClick={() => act('submit')}>Submit</button>}
        {actions.canMatch && <button disabled={!!busy} onClick={() => act('match')}>Run Match</button>}
        {actions.canApprove && <button disabled={!!busy} onClick={() => act('approve')}>Approve</button>}
        {actions.canReject && <button disabled={!!busy} onClick={() => { const r = prompt('Rejection reason'); if (r) act('reject', { reason: r }); }}>Reject</button>}
        {actions.canReturnForCorrection && <button disabled={!!busy} onClick={() => { const r = prompt('Correction reason'); if (r) act('return-for-correction', { reason: r }); }}>Return for Correction</button>}
        {actions.canPlaceHold && <button disabled={!!busy} onClick={() => { const r = prompt('Hold reason'); if (r) act('place-hold', { reason: r }); }}>Place Hold</button>}
        {actions.canReleaseHold && <button disabled={!!busy} onClick={() => act('release-hold')}>Release Hold</button>}
        {actions.canMarkPaymentReady && (
          <button disabled={!!busy || !readiness?.ready} title={readiness?.ready ? undefined : 'Backend payment readiness is false; resolve the blockers first.'} onClick={() => act('mark-payment-ready')}>Mark Payment Ready</button>
        )}
        {actions.canRecordPayment && <button disabled={!!busy} onClick={() => { const ref = prompt('Payment reference'); if (!ref) return; const dt = prompt('Payment date (YYYY-MM-DD)'); if (dt) act('mark-paid', { payment_reference: ref, payment_date: dt }); }}>Mark Paid</button>}
        {actions.canCancel && <button disabled={!!busy} onClick={() => { const r = prompt('Cancel reason'); if (r) act('cancel', { reason: r, version: inv.version }); }}>Cancel</button>}
        {actions.canClose && <button disabled={!!busy} onClick={() => act('close')}>Close</button>}
        <a className="btn" href={`#/procurement/invoices/${id}/match`}>Matching View</a>
      </div>
      <dl className="detail-grid">
        <dt>Vendor</dt><dd>{inv.vendor_name || inv.vendor}</dd>
        <dt>Purchase Order</dt><dd>{inv.po_number || inv.purchase_order}</dd>
        <dt>Invoice Date</dt><dd>{inv.invoice_date}</dd>
        <dt>Due Date</dt><dd>{inv.due_date || '—'}</dd>
        <dt>Currency</dt><dd>{inv.currency}</dd>
        <dt>Subtotal</dt><dd>{formatMoney(inv.subtotal, inv.currency)}</dd>
        <dt>Grand Total</dt><dd>{formatMoney(inv.grand_total, inv.currency)}</dd>
        <dt>Variance Total</dt><dd>{formatMoney(inv.variance_total, inv.currency)}</dd>
        <dt>Payment Hold</dt><dd>{inv.payment_hold ? `Yes: ${inv.payment_hold_reason}` : 'No'}</dd>
      </dl>
      <h2>Payment Readiness</h2>
      {readiness && (readiness.ready
        ? <div className="badge green">Ready for payment tracking</div>
        : <div><strong>Not ready</strong><ul>{(readiness.blockers || []).map((b, i) => <li key={i}><strong>{b.code}:</strong> {b.message} ({b.severity})</li>)}</ul></div>)}
      <h2>Invoice Lines</h2>
      <Table
        columns={[
          { label: 'PO Line', render: r => r.po_item_name || r.purchase_order_item },
          { label: 'Receipt Line', render: r => r.goods_receipt_number || r.goods_receipt_item || '—' },
          { label: 'Description', key: 'description' },
          { label: 'Invoiced Qty', key: 'invoiced_quantity' },
          { label: 'Unit Price', key: 'unit_price' },
          { label: 'Tax', key: 'tax_amount' },
          { label: 'Line Total', key: 'line_total' },
          { label: 'Match Status', render: r => statusLabel(r.match_status) },
        ]}
        rows={inv.lines || []}
        empty="No invoice lines."
      />
      {actions.canAddLine && (
        <form onSubmit={addLine} className="form-grid">
          <h3>Add Invoice Line</h3>
          <label>PO Item<select value={line.purchase_order_item} onChange={e => setLine(l => ({ ...l, purchase_order_item: e.target.value }))} required><option value="">Select</option>{poItems.map(i => <option key={i.id} value={i.id}>{i.item_name} (ordered {i.quantity}, received {i.received_qty}, rejected {i.rejected_qty}, damaged {i.damaged_qty})</option>)}</select></label>
          <label>Goods Receipt Item<select value={line.goods_receipt_item} onChange={e => setLine(l => ({ ...l, goods_receipt_item: e.target.value }))}><option value="">None</option>{grItems.map(i => <option key={i.id} value={i.id}>GR Item {i.id} - PO line {i.purchase_order_item} (accepted {i.accepted_quantity})</option>)}</select></label>
          <label>Description<input value={line.description} onChange={e => setLine(l => ({ ...l, description: e.target.value }))} /></label>
          <label>Invoiced Quantity<input value={line.invoiced_quantity} onChange={e => setLine(l => ({ ...l, invoiced_quantity: e.target.value }))} required /></label>
          <label>Unit Price<input value={line.unit_price} onChange={e => setLine(l => ({ ...l, unit_price: e.target.value }))} required /></label>
          <label>Discount Amount<input value={line.discount_amount} onChange={e => setLine(l => ({ ...l, discount_amount: e.target.value }))} /></label>
          <label>Tax Rate<input value={line.tax_rate} onChange={e => setLine(l => ({ ...l, tax_rate: e.target.value }))} /></label>
          <label>Tax Amount<input value={line.tax_amount} onChange={e => setLine(l => ({ ...l, tax_amount: e.target.value }))} /></label>
          <button className="btn" type="submit" disabled={busy === 'line'}>Add Line</button>
        </form>
      )}
    </div>
  );
}

export default ProcurementInvoiceDetail;

