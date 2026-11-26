import { useCallback, useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import {
  safeResults, statusLabel, parseFieldErrors, procurementCapabilities,
  vendorReturnActionState, procurementErrorText, recordConflictText,
} from '../../shared/procurement-utils';

function Table({ columns, rows, empty = 'No records.' }) {
  if (!rows?.length) return <div className="empty-state"><div className="empty-title">{empty}</div></div>;
  return <div className="table-wrap"><table className="table"><thead><tr>{columns.map(c => <th key={c.key || c.label}>{c.label}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={row.id ?? i}>{columns.map(c => <td key={c.key || c.label}>{typeof c.render === 'function' ? c.render(row) : row[c.key]}</td>)}</tr>)}</tbody></table></div>;
}

function FormError({ error }) {
  if (!error) return null;
  const parsed = (error && ('global' in error || 'fields' in error)) ? error : parseFieldErrors(error);
  const fields = Object.entries(parsed?.fields || {});
  return (
    <div role="alert" className="error">
      {parsed?.global && <div>{parsed.global}</div>}
      {fields.length > 0 && <ul>{fields.map(([field, message]) => <li key={field}><strong>{field.replace(/_/g, ' ')}:</strong> {message}</li>)}</ul>}
    </div>
  );
}

export function ProcurementReturnsPage() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true); setError('');
    return api.get('/procurement/vendor-returns/?page_size=50')
      .then(r => setRows(safeResults(r.data)))
      .catch(e => setError(procurementErrorText(e, 'Failed to load returns.')))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  if (loading) return <p className="page-loading" role="status">Loading vendor returns…</p>;
  return (
    <div>
      <div className="page-header"><h1>Vendor Returns</h1><a className="btn" href="#/procurement/returns/new">New Return</a></div>
      {error && <div role="alert" className="error">{error} <button className="btn" onClick={load}>Retry</button></div>}
      <Table columns={[
        { label: 'Return Number', render: r => <a href={`#/procurement/returns/${r.id}`}>{r.return_number}</a> },
        { label: 'Vendor', render: r => r.vendor_name || r.vendor },
        { label: 'Purchase Order', render: r => r.po_number || r.purchase_order },
        { label: 'Goods Receipt', render: r => r.gr_number || r.goods_receipt || '—' },
        { label: 'Invoice', render: r => r.invoice_number || r.supplier_invoice || '—' },
        { label: 'Status', render: r => statusLabel(r.status) },
        { label: 'Reason', key: 'reason' },
        { label: 'Method', key: 'return_method' },
      ]} rows={rows} empty="No vendor returns." />
    </div>
  );
}

export function ProcurementReturnForm() {
  const [form, setForm] = useState({ vendor: '', purchase_order: '', goods_receipt: '', supplier_invoice: '', reason: 'damaged', return_method: 'physical_return', authorization_reference: '', shipping_reference: '', expected_resolution: '', replacement_expected: false, replacement_due_date: '', return_date: '' });
  const [error, setError] = useState(null); const [saving, setSaving] = useState(false);
  function set(k, v) { setForm(f => ({ ...f, [k]: v })); }
  async function save(e) {
    e.preventDefault(); if (saving) return;
    setSaving(true); setError(null);
    try {
      const payload = {
        ...form,
        goods_receipt: form.goods_receipt || null,
        supplier_invoice: form.supplier_invoice || null,
        replacement_due_date: form.replacement_due_date || null,
        return_date: form.return_date || null,
      };
      const r = await api.post('/procurement/vendor-returns/', payload);
      if (!r.data?.id) { setError({ global: 'The server did not return the new return id.' }); return; }
      window.location.hash = `#/procurement/returns/${r.data.id}`;
    } catch (err) {
      const p = parseFieldErrors(err);
      const status = err?.response?.status;
      const hasFields = Object.keys(p?.fields || {}).length > 0;
      setError(status === 403 || status === 404 || (!p?.global && !hasFields) ? { global: procurementErrorText(err, 'Failed to create return.') } : p);
    } finally { setSaving(false); }
  }
  return (
    <div>
      <h1>New Vendor Return</h1>
      <FormError error={error} />
      <form onSubmit={save} className="form-grid">
        <label>Vendor ID<input value={form.vendor} onChange={e => set('vendor', e.target.value)} required /></label>
        <label>Purchase Order ID<input value={form.purchase_order} onChange={e => set('purchase_order', e.target.value)} required /></label>
        <label>Goods Receipt ID<input value={form.goods_receipt} onChange={e => set('goods_receipt', e.target.value)} /></label>
        <label>Supplier Invoice ID<input value={form.supplier_invoice} onChange={e => set('supplier_invoice', e.target.value)} /></label>
        <label>Return Date<input type="date" value={form.return_date} onChange={e => set('return_date', e.target.value)} /></label>
        <label>Reason<select value={form.reason} onChange={e => set('reason', e.target.value)}>{['damaged','rejected','incorrect_item','wrong_specification','excess_delivery','quality_failure','warranty','other'].map(v => <option key={v} value={v}>{v}</option>)}</select></label>
        <label>Return Method<select value={form.return_method} onChange={e => set('return_method', e.target.value)}>{['physical_return','vendor_pickup','onsite_disposal','replacement_without_return','credit_only','other'].map(v => <option key={v} value={v}>{v}</option>)}</select></label>
        <label>Authorization Reference<input value={form.authorization_reference} onChange={e => set('authorization_reference', e.target.value)} /></label>
        <label>Expected Resolution<textarea value={form.expected_resolution} onChange={e => set('expected_resolution', e.target.value)} /></label>
        <label><input type="checkbox" checked={form.replacement_expected} onChange={e => set('replacement_expected', e.target.checked)} /> Replacement Expected</label>
        <label>Replacement Due Date<input type="date" value={form.replacement_due_date} onChange={e => set('replacement_due_date', e.target.value)} /></label>
        <button className="btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Create Return'}</button>
      </form>
    </div>
  );
}

const EMPTY_RETURN_LINE = { goods_receipt_item: '', purchase_order_item: '', quantity: 1, disposition: 'pending_vendor_decision', condition: 'damaged', reason: '', notes: '' };

export function ProcurementReturnDetail({ id }) {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const userId = auth?.user?.id;
  const [vr, setVr] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [line, setLine] = useState(EMPTY_RETURN_LINE);

  const load = useCallback(async () => {
    try { const r = await api.get(`/procurement/vendor-returns/${id}/`); setVr(r.data); }
    catch (e) { setLoadError(procurementErrorText(e, 'Failed to load return.')); }
  }, [id]);
  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  async function act(action, body = {}) {
    setBusy(action); setError('');
    try { await api.post(`/procurement/vendor-returns/${id}/${action}/`, body); await load(); }
    catch (e) {
      if (e?.response?.status === 409) { setError(recordConflictText('return')); await load(); }
      else setError(procurementErrorText(e, 'Action failed.'));
    }
    finally { setBusy(''); }
  }
  async function addLine(e) {
    e.preventDefault(); setBusy('line'); setError('');
    try {
      await api.post('/procurement/vendor-return-lines/', { ...line, vendor_return: id });
      setLine(EMPTY_RETURN_LINE);
      await load();
    } catch (err) { setError(procurementErrorText(err, 'Failed to add line.')); }
    finally { setBusy(''); }
  }

  if (!vr) return <p className="page-loading">{loadError ? <span role="alert">{loadError}</span> : 'Loading…'}</p>;
  const isSystemAdmin = !!(auth?.isSystemAdmin || auth?.role === 'system_admin' || auth?.isSuperuser);
  const actions = vendorReturnActionState(vr, caps, userId, isSystemAdmin);
  return (
    <div>
      <h1>Return {vr.return_number}</h1>
      {error && <div role="alert" className="error">{error}</div>}
      <div className="button-row" style={{flexWrap:'wrap',gap:'8px'}}>
        {actions.canSubmit && <button disabled={!!busy} onClick={() => act('submit')}>Submit</button>}
        {actions.canApprove && <button disabled={!!busy} onClick={() => act('approve', { authorization_reference: prompt('Authorization reference') || vr.authorization_reference || '' })}>Approve</button>}
        {actions.canReject && <button disabled={!!busy} onClick={() => { const r = prompt('Reason'); if (r) act('reject', { reason: r }); }}>Reject</button>}
        {actions.canShip && <button disabled={!!busy} onClick={() => act('ship', { shipping_reference: prompt('Shipping reference') || '' })}>Ship</button>}
        {actions.canRecordReplacement && <button disabled={!!busy} onClick={() => act('record-replacement')}>Record Replacement</button>}
        {actions.canComplete && <button disabled={!!busy} onClick={() => act('complete')}>Complete</button>}
        {actions.canCancel && <button disabled={!!busy} onClick={() => { const r = prompt('Reason'); if (r) act('cancel', { reason: r }); }}>Cancel</button>}
      </div>
      <dl className="detail-grid"><dt>Status</dt><dd>{statusLabel(vr.status)}</dd><dt>Vendor</dt><dd>{vr.vendor_name || vr.vendor}</dd><dt>PO</dt><dd>{vr.po_number || vr.purchase_order}</dd><dt>Receipt</dt><dd>{vr.gr_number || vr.goods_receipt || '—'}</dd><dt>Invoice</dt><dd>{vr.invoice_number || vr.supplier_invoice || '—'}</dd><dt>Reason</dt><dd>{vr.reason}</dd><dt>Method</dt><dd>{vr.return_method}</dd></dl>
      <p className="small">Inventory reversal and asset consequences are processed by the backend according to item disposition and receipt status. Returning goods does not automatically create a refund; credit notes are tracked separately.</p>
      <h2>Return Lines</h2>
      <Table columns={[{ label: 'GR Item', key: 'goods_receipt_item' }, { label: 'PO Item', key: 'purchase_order_item' }, { label: 'Asset Receipt Item', render: r => r.asset_receipt_item || '—' }, { label: 'Asset', render: r => r.asset_tag || r.asset || '—' }, { label: 'Qty', key: 'quantity' }, { label: 'Disposition', key: 'disposition' }, { label: 'Condition', key: 'condition' }, { label: 'Reason', key: 'reason' }]} rows={vr.lines || []} empty="No return lines." />
      {actions.canAddLine && (
        <form onSubmit={addLine} className="form-grid">
          <h3>Add Return Line</h3>
          <label>Goods Receipt Item ID<input value={line.goods_receipt_item} onChange={e => setLine(l => ({ ...l, goods_receipt_item: e.target.value }))} required /></label>
          <label>Purchase Order Item ID<input value={line.purchase_order_item} onChange={e => setLine(l => ({ ...l, purchase_order_item: e.target.value }))} required /></label>
          <label>Quantity<input type="number" value={line.quantity} onChange={e => setLine(l => ({ ...l, quantity: e.target.value }))} required /></label>
          <label>Condition<select value={line.condition} onChange={e => setLine(l => ({ ...l, condition: e.target.value }))}>{['rejected','damaged','defective','incorrect','excess','other'].map(v => <option key={v} value={v}>{v}</option>)}</select></label>
          <label>Disposition<select value={line.disposition} onChange={e => setLine(l => ({ ...l, disposition: e.target.value }))}>{['refund','credit_note','replacement','repair','exchange','write_off','pending_vendor_decision'].map(v => <option key={v} value={v}>{v}</option>)}</select></label>
          <label>Reason<input value={line.reason} onChange={e => setLine(l => ({ ...l, reason: e.target.value }))} /></label>
          <label>Notes<textarea value={line.notes} onChange={e => setLine(l => ({ ...l, notes: e.target.value }))} /></label>
          <button className="btn" disabled={busy === 'line'}>Add Line</button>
        </form>
      )}
    </div>
  );
}

export default ProcurementReturnsPage;

