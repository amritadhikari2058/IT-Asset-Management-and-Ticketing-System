import { useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { PageHeader, Field, AccessDenied } from '../../components';
import { parseApiError } from '../../api-utils';
import api from '../../api';
import { licensingCapabilities } from '../../shared/licensing-utils';
import { SECRET_TYPE_LABELS, SECRET_STATUS_LABELS } from '../../shared/licensing-utils';

function LicenseSecretsPage({ agreementId }) {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ secret_type: 'license_key', label: '', plaintext_value: '' });
  const [saving, setSaving] = useState(false);
  const [revealed, setRevealed] = useState(null);
  const load = async () => {
    setLoading(true);
    try { const r = await api.get(`/licensing/secrets/?agreement=${agreementId}`); setItems(r.data.results || r.data || []); } catch (e) { setError(e.response?.data?.detail || 'Could not load secrets.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { if (agreementId) load(); }, [agreementId]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect
  if (!caps.canViewSecrets) return <AccessDenied />;
  const create = async (e) => {
    e.preventDefault(); setSaving(true); setError('');
    try {
      await api.post('/licensing/secrets/', { agreement: agreementId, secret_type: form.secret_type, label: form.label, plaintext_value: form.plaintext_value });
      setShowCreate(false); setForm({ secret_type: 'license_key', label: '', plaintext_value: '' });
      load();
    } catch (e) { setError(parseApiError(e).global || 'Create failed.'); }
    finally { setSaving(false); }
  };
  const reveal = async (id) => {
    if (!window.confirm('You are about to reveal a protected license secret. This action is audited.')) return;
    try {
      const r = await api.post(`/licensing/secrets/${id}/reveal/`);
      setRevealed(r.data.revealed_value);
      setTimeout(() => setRevealed(null), 30000);
    } catch (e) { setError(e.response?.status === 403 ? 'You do not have permission to reveal this secret.' : (e.response?.data?.detail || 'Reveal failed.')); }
  };
  const revoke = async (id) => {
    if (!window.confirm('Revoke this secret?')) return;
    try { await api.post(`/licensing/secrets/${id}/revoke/`); load(); } catch (e) { setError(e.response?.data?.detail || 'Revoke failed.'); }
  };
  return (
    <div className="license-secrets-page">
      <PageHeader title="License Secrets" />
      {error && <div className="alert alert-danger">{error}</div>}
      {caps.canViewSecrets && <button className="btn btn-primary mb-3" onClick={() => setShowCreate(true)}>New Secret</button>}
      {loading ? <div>Loading…</div> : (
        <table className="table table-sm"><thead><tr><th>Type</th><th>Label</th><th>Last 4</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead><tbody>
          {items.map((s) => (
            <tr key={s.id}>
              <td>{SECRET_TYPE_LABELS[s.secret_type] || s.secret_type}</td>
              <td>{s.label}</td>
              <td>{s.last_four}</td>
              <td>{SECRET_STATUS_LABELS[s.status] || s.status}</td>
              <td>{s.created_at}</td>
              <td>
                {caps.canRevealSecrets && <button className="btn-small btn-secondary" onClick={() => reveal(s.id)}>Reveal</button>}{' '}
                <button className="btn-small btn-danger" onClick={() => revoke(s.id)}>Revoke</button>
              </td>
            </tr>
          ))}
        </tbody></table>
      )}
      {revealed && <div className="alert alert-warning">Revealed value (temporary): <code>{revealed}</code></div>}
      {showCreate && (
        <div className="modal-backdrop"><div className="modal">
          <h3>New Secret</h3>
          <form onSubmit={create}>
            <Field label="Type"><select className="input" value={form.secret_type} onChange={(e) => setForm({ ...form, secret_type: e.target.value })}>{Object.entries(SECRET_TYPE_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
            <Field label="Label"><input className="input" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} required /></Field>
            <Field label="Plaintext Value"><input className="input" type="password" value={form.plaintext_value} onChange={(e) => setForm({ ...form, plaintext_value: e.target.value })} required /></Field>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" className="btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Create'}</button>
            </div>
          </form>
        </div></div>
      )}
    </div>
  );
}
export { LicenseSecretsPage };
export default LicenseSecretsPage;

