import { useEffect, useState } from 'react';
import api from '../../api';
import { safeResults, parseFieldErrors, procurementErrorText } from '../../shared/procurement-utils';

function ErrorList({ error }) {
  if (!error) return null;
  const parsed = (error && ('global' in error || 'fields' in error)) ? error : parseFieldErrors(error);
  const global = parsed?.global;
  const fields = Object.entries(parsed?.fields || {});
  if (!global && fields.length === 0) return null;
  return (
    <div role="alert" className="error">
      {global && <div>{global}</div>}
      {fields.length > 0 && (
        <ul>
          {fields.map(([field, message]) => (
            <li key={field}><strong>{field.replace(/_/g, ' ')}:</strong> {message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ProcurementInvoiceForm() {
  const [form, setForm] = useState({
    invoice_number: '', vendor: '', purchase_order: '', invoice_date: '',
    received_date: '', due_date: '', currency: 'NPR', freight_total: '0.00',
    other_charge_total: '0.00', discount_total: '0.00', notes: '',
  });
  const [pos, setPos] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get('/procurement/purchase-orders/?page_size=100').then(r => setPos(safeResults(r.data))).catch(() => {});
    api.get('/assets/vendors/?page_size=100').then(r => setVendors(safeResults(r.data))).catch(() => {});
  }, []);

  function set(k, v) { setForm(f => ({ ...f, [k]: v })); }

  const visiblePos = form.vendor
    ? pos.filter(p => String(p.vendor) === String(form.vendor) || String(p.vendor_detail?.id) === String(form.vendor))
    : pos;

  async function save(e) {
    e.preventDefault();
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      // Totals, status and the normalized invoice number stay backend-authoritative.
      const payload = { ...form, due_date: form.due_date || null };
      const r = await api.post('/procurement/supplier-invoices/', payload);
      if (!r.data?.id) {
        setError({ global: 'The server did not return the new invoice id. The invoice was not opened.' });
        return;
      }
      window.location.hash = `#/procurement/invoices/${r.data.id}`;
    } catch (err) {
      const p = parseFieldErrors(err);
      const status = err?.response?.status;
      const hasFieldErrors = Object.keys(p?.fields || {}).length > 0;
      if (status === 403 || status === 404 || (!p?.global && !hasFieldErrors)) {
        setError({ global: procurementErrorText(err, 'Failed to create invoice.') });
      } else {
        setError(p);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="page-header"><h1>New Supplier Invoice</h1></div>
      <ErrorList error={error} />
      <form onSubmit={save} className="form-grid">
        <label>Invoice Number<input value={form.invoice_number} onChange={e => set('invoice_number', e.target.value)} required /></label>
        <label>Vendor<select value={form.vendor} onChange={e => { set('vendor', e.target.value); set('purchase_order', ''); }} required><option value="">Select vendor</option>{vendors.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label>
        <label>Purchase Order<select value={form.purchase_order} onChange={e => set('purchase_order', e.target.value)} required><option value="">Select PO</option>{visiblePos.map(p => <option key={p.id} value={p.id}>{p.po_number} - {p.vendor_detail?.name || p.vendor}</option>)}</select></label>
        <label>Invoice Date<input type="date" value={form.invoice_date} onChange={e => set('invoice_date', e.target.value)} required /></label>
        <label>Received Date<input type="date" value={form.received_date} onChange={e => set('received_date', e.target.value)} required /></label>
        <label>Due Date<input type="date" value={form.due_date} onChange={e => set('due_date', e.target.value)} /></label>
        <label>Currency<input value={form.currency} onChange={e => set('currency', e.target.value)} required /></label>
        <label>Freight<input value={form.freight_total} onChange={e => set('freight_total', e.target.value)} /></label>
        <label>Other Charges<input value={form.other_charge_total} onChange={e => set('other_charge_total', e.target.value)} /></label>
        <label>Discount<input value={form.discount_total} onChange={e => set('discount_total', e.target.value)} /></label>
        <label>Notes<textarea value={form.notes} onChange={e => set('notes', e.target.value)} /></label>
        <div><button className="btn-primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Create Invoice'}</button></div>
      </form>
    </div>
  );
}

export default ProcurementInvoiceForm;

