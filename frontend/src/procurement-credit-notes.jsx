import { useCallback, useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  safeResults, formatMoney, statusLabel, parseFieldErrors, procurementCapabilities,
  vendorCreditNoteActionState, procurementErrorText, recordConflictText,
} from './procurement-utils';

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

export function ProcurementCreditNotesPage() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true); setError('');
    return api.get('/procurement/credit-notes/?page_size=50')
      .then(r => setRows(safeResults(r.data)))
      .catch(e => setError(procurementErrorText(e, 'Failed to load credit notes.')))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (loading) return <p className="page-loading" role="status">Loading credit notes…</p>;
  return (
    <div>
      <div className="page-header"><h1>Credit Notes</h1><a className="btn" href="#/procurement/credit-notes/new">New Credit Note</a></div>
      {error && <div role="alert" className="error">{error} <button className="btn" onClick={load}>Retry</button></div>}
      <Table columns={[
        { label: 'Credit Note Number', render: r => <a href={`#/procurement/credit-notes/${r.id}`}>{r.credit_note_number}</a> },
        { label: 'Vendor', render: r => r.vendor_name || r.vendor },
        { label: 'Invoice', render: r => r.invoice_number || r.supplier_invoice },
        { label: 'Return', render: r => r.return_number || r.vendor_return || '—' },
        { label: 'Date', key: 'credit_date' },
        { label: 'Status', render: r => statusLabel(r.status) },
        { label: 'Total', render: r => formatMoney(r.total, r.currency) },
        { label: 'Currency', key: 'currency' },
        { label: 'Applied Amount', render: r => formatMoney(r.applied_amount, r.currency) },
      ]} rows={rows} empty="No credit notes." />
    </div>
  );
}

export function ProcurementCreditNoteForm() {
  const [form, setForm] = useState({ credit_note_number: '', vendor: '', supplier_invoice: '', vendor_return: '', credit_date: '', currency: 'NPR', subtotal: '0.00', tax_total: '0.00', total: '0.00', reason: '', external_reference: '' });
  const [error, setError] = useState(null); const [saving, setSaving] = useState(false);
  function set(k, v) { setForm(f => ({ ...f, [k]: v })); }
  async function save(e) {
    e.preventDefault(); if (saving) return;
    setSaving(true); setError(null);
    try {
      const r = await api.post('/procurement/credit-notes/', { ...form, vendor_return: form.vendor_return || null });
      if (!r.data?.id) { setError({ global: 'The server did not return the new credit note id.' }); return; }
      window.location.hash = `#/procurement/credit-notes/${r.data.id}`;
    } catch (err) {
      const p = parseFieldErrors(err);
      const status = err?.response?.status;
      const hasFields = Object.keys(p?.fields || {}).length > 0;
      setError(status === 403 || status === 404 || (!p?.global && !hasFields) ? { global: procurementErrorText(err, 'Failed to create credit note.') } : p);
    } finally { setSaving(false); }
  }
  return (
    <div>
      <h1>New Credit Note</h1>
      <FormError error={error} />
      <form onSubmit={save} className="form-grid">
        <label>Credit Note Number<input value={form.credit_note_number} onChange={e => set('credit_note_number', e.target.value)} required /></label>
        <label>Vendor ID<input value={form.vendor} onChange={e => set('vendor', e.target.value)} required /></label>
        <label>Supplier Invoice ID<input value={form.supplier_invoice} onChange={e => set('supplier_invoice', e.target.value)} required /></label>
        <label>Vendor Return ID<input value={form.vendor_return} onChange={e => set('vendor_return', e.target.value)} /></label>
        <label>Credit Date<input type="date" value={form.credit_date} onChange={e => set('credit_date', e.target.value)} required /></label>
        <label>Currency<input value={form.currency} onChange={e => set('currency', e.target.value)} required /></label>
        <label>Subtotal<input value={form.subtotal} onChange={e => set('subtotal', e.target.value)} /></label>
        <label>Tax Total<input value={form.tax_total} onChange={e => set('tax_total', e.target.value)} /></label>
        <label>Total<input value={form.total} onChange={e => set('total', e.target.value)} /></label>
        <label>Reason<textarea value={form.reason} onChange={e => set('reason', e.target.value)} /></label>
        <label>External Reference<input value={form.external_reference} onChange={e => set('external_reference', e.target.value)} /></label>
        <button className="btn primary" disabled={saving}>{saving ? 'Saving…' : 'Create'}</button>
      </form>
    </div>
  );
}

export function ProcurementCreditNoteDetail({ id }) {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const userId = auth?.user?.id;
  const [cn, setCn] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    try { const r = await api.get(`/procurement/credit-notes/${id}/`); setCn(r.data); }
    catch (e) { setLoadError(procurementErrorText(e, 'Failed to load.')); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  async function act(action, body = {}) {
    setBusy(action); setError('');
    try { await api.post(`/procurement/credit-notes/${id}/${action}/`, body); await load(); }
    catch (e) {
      if (e?.response?.status === 409) { setError(recordConflictText('credit note')); await load(); }
      else setError(procurementErrorText(e, 'Action failed.'));
    }
    finally { setBusy(''); }
  }

  if (!cn) return <p className="page-loading">{loadError ? <span role="alert">{loadError}</span> : 'Loading…'}</p>;
  const isSystemAdmin = !!(auth?.isSystemAdmin || auth?.role === 'system_admin' || auth?.isSuperuser);
  const actions = vendorCreditNoteActionState(cn, caps, userId, isSystemAdmin);
  return (
    <div>
      <h1>Credit Note {cn.credit_note_number}</h1>
      {error && <div role="alert" className="error">{error}</div>}
      <div className="button-row" style={{flexWrap:'wrap',gap:'8px'}}>
        {actions.canSubmit && <button disabled={!!busy} onClick={() => act('submit')}>Submit</button>}
        {actions.canApprove && <button disabled={!!busy} onClick={() => act('approve')}>Approve</button>}
        {actions.canReject && <button disabled={!!busy} onClick={() => { const r = prompt('Reason'); if (r) act('reject', { reason: r }); }}>Reject</button>}
        {actions.canApply && <button disabled={!!busy} onClick={() => act('apply')}>Apply</button>}
        {actions.canCancel && <button disabled={!!busy} onClick={() => { const r = prompt('Reason'); if (r) act('cancel', { reason: r }); }}>Cancel</button>}
      </div>
      <dl className="detail-grid">
        <dt>Status</dt><dd>{statusLabel(cn.status)}</dd>
        <dt>Vendor</dt><dd>{cn.vendor_name || cn.vendor}</dd>
        <dt>Invoice</dt><dd>{cn.invoice_number || cn.supplier_invoice}</dd>
        <dt>Return</dt><dd>{cn.return_number || cn.vendor_return || '—'}</dd>
        <dt>Currency</dt><dd>{cn.currency}</dd>
        <dt>Total</dt><dd>{formatMoney(cn.total, cn.currency)}</dd>
        <dt>Applied Amount</dt><dd>{formatMoney(cn.applied_amount, cn.currency)} — Credit applied to tracked Invoice balance.</dd>
      </dl>
      <h2>Lines</h2>
      <Table columns={[{ label: 'Description', key: 'description' }, { label: 'Quantity', key: 'quantity' }, { label: 'Amount', key: 'amount' }]} rows={cn.lines || []} empty="No lines." />
    </div>
  );
}

export default ProcurementCreditNotesPage;
