import { useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { PageHeader, Field, AccessDenied } from '../../components';
import { parseApiError } from '../../api-utils';
import api from '../../api';
import { licensingCapabilities } from '../../shared/licensing-utils';
import { AGREEMENT_TYPE_LABELS, LICENSE_MODEL_LABELS, BILLING_FREQUENCY_LABELS } from '../../shared/licensing-utils';

function LicenseAgreementForm({ id, agreementId, onSave, onClose }) {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const aid = id || agreementId;
  const [form, setForm] = useState({ software_product: '', vendor: '', agreement_type: 'purchase', license_model: 'perpetual', purchase_date: '', start_date: '', expiry_date: '', renewal_date: '', grace_period_days: 0, auto_renew: false, renewal_notice_days: 30, currency: 'USD', unit_cost: '', total_cost: '', quantity_purchased: 1, concurrent_limit: '', maintenance_included: false, support_included: false, support_expiry_date: '', contract_reference: '', invoice_reference: '', external_subscription_id: '', billing_frequency: 'annual', department: '', cost_center: '', owner: '', contract_manager: '', terms_summary: '', internal_notes: '', procurement_purchase_order: '', procurement_purchase_order_line: '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [products, setProducts] = useState([]);
  const [vendors, setVendors] = useState([]);
  useEffect(() => { api.get('/licensing/products/').then((r) => setProducts(r.data.results || r.data || [])).catch(() => {}); api.get('/assets/vendors/?is_deleted=false').then((r) => setVendors(r.data.results || r.data || [])).catch(() => {}); }, []);
  useEffect(() => {
    if (aid) {
      api.get(`/licensing/agreements/${aid}/`).then((r) => {
        const d = r.data;
        setForm({ ...form, ...d, software_product: d.software_product || '', vendor: d.vendor || '', department: d.department || '', owner: d.owner || '', contract_manager: d.contract_manager || '' });
      }).catch((e) => setError(parseApiError(e).global || 'Could not load agreement.'));
    }
  }, [aid]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!caps.canManageAgreements) return <AccessDenied reason="manager" />;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault(); setSaving(true); setError('');
    try {
      if (aid) await api.patch(`/licensing/agreements/${aid}/`, form); else await api.post('/licensing/agreements/', form);
      setSaving(false);
      if (onSave) onSave(); else window.location.hash = aid ? `#/licenses/${aid}` : '#/licenses';
    } catch (e) { setSaving(false); setError(parseApiError(e).global || 'Save failed.'); }
  };
  return (
    <form onSubmit={submit} noValidate>
      <PageHeader title={aid ? 'Edit License Agreement' : 'New License Agreement'} />
      {error && <div className="alert alert-danger">{error}</div>}
      <Field label="Software Product*"><select className="input" value={form.software_product} onChange={set('software_product')} required><option value="">—</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
      <Field label="Vendor"><select className="input" value={form.vendor} onChange={set('vendor')}><option value="">—</option>{vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</select></Field>
      <Field label="Agreement Type"><select className="input" value={form.agreement_type} onChange={set('agreement_type')}>{Object.entries(AGREEMENT_TYPE_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="License Model"><select className="input" value={form.license_model} onChange={set('license_model')}>{Object.entries(LICENSE_MODEL_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="Purchase Date"><input className="input" type="date" value={form.purchase_date} onChange={set('purchase_date')} /></Field>
      <Field label="Start Date*"><input className="input" type="date" value={form.start_date} onChange={set('start_date')} required /></Field>
      <Field label="Expiry Date"><input className="input" type="date" value={form.expiry_date} onChange={set('expiry_date')} /></Field>
      <Field label="Renewal Date"><input className="input" type="date" value={form.renewal_date} onChange={set('renewal_date')} /></Field>
      <Field label="Currency"><input className="input" value={form.currency} onChange={set('currency')} /></Field>
      <Field label="Unit Cost"><input className="input" type="number" step="0.01" value={form.unit_cost} onChange={set('unit_cost')} /></Field>
      <Field label="Total Cost"><input className="input" type="number" step="0.01" value={form.total_cost} onChange={set('total_cost')} /></Field>
      <Field label="Quantity Purchased"><input className="input" type="number" value={form.quantity_purchased} onChange={set('quantity_purchased')} /></Field>
      <Field label="Concurrent Limit"><input className="input" type="number" value={form.concurrent_limit} onChange={set('concurrent_limit')} /></Field>
      <Field label="Billing Frequency"><select className="input" value={form.billing_frequency} onChange={set('billing_frequency')}>{Object.entries(BILLING_FREQUENCY_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="Contract Reference"><input className="input" value={form.contract_reference} onChange={set('contract_reference')} /></Field>
      <Field label="Invoice Reference"><input className="input" value={form.invoice_reference} onChange={set('invoice_reference')} /></Field>
      <Field label="Terms Summary"><textarea className="input" value={form.terms_summary} onChange={set('terms_summary')} /></Field>
      <Field label="Internal Notes"><textarea className="input" value={form.internal_notes} onChange={set('internal_notes')} /></Field>
      <Field label="Auto Renew"><input type="checkbox" checked={form.auto_renew} onChange={set('auto_renew')} /></Field>
      <Field label="Maintenance Included"><input type="checkbox" checked={form.maintenance_included} onChange={set('maintenance_included')} /></Field>
      <Field label="Support Included"><input type="checkbox" checked={form.support_included} onChange={set('support_included')} /></Field>
      <div className="modal-foot" style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button type="button" className="btn-secondary" onClick={() => { if (onClose) onClose(); else window.location.hash = '#/licenses'; }}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
    </form>
  );
}
export { LicenseAgreementForm };
export default LicenseAgreementForm;

