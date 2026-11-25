import { useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { PageHeader, Field, AccessDenied } from '../../components';
import { parseApiError } from '../../api-utils';
import api from '../../api';
import { licensingCapabilities } from '../../shared/licensing-utils';
import { PRODUCT_CATEGORY_LABELS, PLATFORM_LABELS, LICENSE_MODEL_LABELS, PRODUCT_APPROVAL_STATUS_LABELS, RISK_LEVEL_LABELS, SUPPORT_STATUS_LABELS } from '../../shared/licensing-utils';

function SoftwareProductForm({ vendorId, onSave, onClose, productId }) {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const id = productId || vendorId;
  const [form, setForm] = useState({ name: '', code: '', publisher: '', vendor: '', product_family: '', edition: '', version: '', category: 'other', description: '', website: '', platform: 'cross_platform', license_required: true, license_model: 'perpetual', approved_status: 'pending', risk_level: 'low', support_status: 'supported', support_end_date: '', end_of_life_date: '', is_active: true, notes: '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [vendors, setVendors] = useState([]);
  useEffect(() => { api.get('/assets/vendors/?is_deleted=false').then((r) => setVendors(r.data.results || r.data || [])).catch(() => {}); }, []);
  useEffect(() => {
    if (id) {
      api.get(`/licensing/products/${id}/`).then((r) => {
        const d = r.data;
        setForm({ name: d.name || '', code: d.code || '', publisher: d.publisher || '', vendor: d.vendor || '', product_family: d.product_family || '', edition: d.edition || '', version: d.version || '', category: d.category || 'other', description: d.description || '', website: d.website || '', platform: d.platform || 'cross_platform', license_required: d.license_required !== false, license_model: d.license_model || 'perpetual', approved_status: d.approved_status || 'pending', risk_level: d.risk_level || 'low', support_status: d.support_status || 'supported', support_end_date: d.support_end_date || '', end_of_life_date: d.end_of_life_date || '', is_active: d.is_active !== false, notes: d.notes || '' });
      }).catch((e) => setError(parseApiError(e).global || 'Could not load product.'));
    }
  }, [id]);
  if (!caps.canManageProducts) return <AccessDenied reason="manager" />;
  const submit = async (e) => {
    e.preventDefault(); setSaving(true); setError('');
    try {
      if (id) await api.patch(`/licensing/products/${id}/`, form); else await api.post('/licensing/products/', form);
      setSaving(false);
      if (onSave) onSave(); else window.location.hash = '#/software/products';
    } catch (e) {
      setSaving(false);
      const pe = parseApiError(e);
      setError(pe.global || 'Save failed.');
    }
  };
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  return (
    <form onSubmit={submit} noValidate>
      <PageHeader title={id ? 'Edit Software Product' : 'New Software Product'} />
      {error && <div className="alert alert-danger">{error}</div>}
      <Field label="Name*"><input className="input" name="name" value={form.name} onChange={set('name')} required /></Field>
      <Field label="Code*"><input className="input" name="code" value={form.code} onChange={set('code')} required /></Field>
      <Field label="Publisher"><input className="input" name="publisher" value={form.publisher} onChange={set('publisher')} /></Field>
      <Field label="Vendor"><select className="input" name="vendor" value={form.vendor} onChange={set('vendor')}><option value="">—</option>{vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</select></Field>
      <Field label="Category"><select className="input" name="category" value={form.category} onChange={set('category')}>{Object.entries(PRODUCT_CATEGORY_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="Platform"><select className="input" name="platform" value={form.platform} onChange={set('platform')}>{Object.entries(PLATFORM_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="License Model"><select className="input" name="license_model" value={form.license_model} onChange={set('license_model')}>{Object.entries(LICENSE_MODEL_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="Approval Status"><select className="input" name="approved_status" value={form.approved_status} onChange={set('approved_status')}>{Object.entries(PRODUCT_APPROVAL_STATUS_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="Risk Level"><select className="input" name="risk_level" value={form.risk_level} onChange={set('risk_level')}>{Object.entries(RISK_LEVEL_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="Support Status"><select className="input" name="support_status" value={form.support_status} onChange={set('support_status')}>{Object.entries(SUPPORT_STATUS_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="Version"><input className="input" name="version" value={form.version} onChange={set('version')} /></Field>
      <Field label="Edition"><input className="input" name="edition" value={form.edition} onChange={set('edition')} /></Field>
      <Field label="Description"><textarea className="input" name="description" value={form.description} onChange={set('description')} /></Field>
      <Field label="Website"><input className="input" name="website" value={form.website} onChange={set('website')} /></Field>
      <Field label="Support End Date"><input className="input" type="date" name="support_end_date" value={form.support_end_date} onChange={set('support_end_date')} /></Field>
      <Field label="End of Life Date"><input className="input" type="date" name="end_of_life_date" value={form.end_of_life_date} onChange={set('end_of_life_date')} /></Field>
      <Field label="Notes"><textarea className="input" name="notes" value={form.notes} onChange={set('notes')} /></Field>
      <Field label="Active"><input type="checkbox" name="is_active" checked={form.is_active} onChange={set('is_active')} /></Field>
      <Field label="License Required"><input type="checkbox" name="license_required" checked={form.license_required} onChange={set('license_required')} /></Field>
      <div className="modal-foot" style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button type="button" className="btn btn-outline" onClick={() => { if (onClose) onClose(); else window.location.hash = '#/software/products'; }}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
    </form>
  );
}

export { SoftwareProductForm };
export default SoftwareProductForm;

