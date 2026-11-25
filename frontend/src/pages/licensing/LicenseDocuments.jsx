import { useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { PageHeader, Field, AccessDenied } from '../../components';
import { parseApiError } from '../../api-utils';
import api from '../../api';
import { licensingCapabilities } from '../../shared/licensing-utils';

const DOC_TYPES = ['agreement', 'invoice', 'quotation', 'purchase_order_copy', 'license_certificate', 'support_contract', 'maintenance_agreement', 'renewal_notice', 'deployment_guide', 'compliance_evidence'];

function LicenseDocumentsPage({ agreementId }) {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showUpload, setShowUpload] = useState(false);
  const [form, setForm] = useState({ document_type: 'agreement', description: '', file: null });
  const [saving, setSaving] = useState(false);
  const load = async () => {
    setLoading(true);
    try { const r = await api.get(`/licensing/documents/?agreement=${agreementId}`); setItems(r.data.results || r.data || []); } catch (e) { setError(e.response?.data?.detail || 'Could not load documents.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { if (agreementId) load(); }, [agreementId]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect
  if (!caps.canManageDocuments && !caps.canView) return <AccessDenied />;
  const upload = async (e) => {
    e.preventDefault(); setSaving(true); setError('');
    const fd = new FormData();
    fd.append('agreement', agreementId);
    fd.append('document_type', form.document_type);
    fd.append('description', form.description);
    if (form.file) fd.append('file', form.file);
    try { await api.post('/licensing/documents/', fd, { headers: { 'Content-Type': 'multipart/form-data' } }); setShowUpload(false); setForm({ document_type: 'agreement', description: '', file: null }); load(); }
    catch (e) { setError(parseApiError(e).global || 'Upload failed.'); }
    finally { setSaving(false); }
  };
  const download = async (doc) => {
    try {
      const r = await api.get(`/licensing/documents/${doc.id}/download/`, { responseType: 'blob' });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement('a'); a.href = url; a.download = doc.original_filename || 'document'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch { setError('Download failed.'); }
  };
  return (
    <div className="license-documents-page">
      <PageHeader title="License Documents" />
      {error && <div className="alert alert-danger">{error}</div>}
      {caps.canManageDocuments && <button className="btn btn-primary mb-3" onClick={() => setShowUpload(true)}>Upload Document</button>}
      {loading ? <div>Loading…</div> : (
        <table className="table table-sm"><thead><tr><th>Type</th><th>Filename</th><th>Size</th><th>Uploaded By</th><th>Date</th><th>Actions</th></tr></thead><tbody>
          {items.map((d) => (
            <tr key={d.id}><td>{d.document_type}</td><td>{d.original_filename}</td><td>{d.size}</td><td>{d.uploaded_by_email}</td><td>{d.created_at}</td><td><button className="btn btn-sm btn-outline" onClick={() => download(d)}>Download</button></td></tr>
          ))}
        </tbody></table>
      )}
      {showUpload && (
        <div className="modal-backdrop"><div className="modal">
          <h3>Upload Document</h3>
          <form onSubmit={upload}>
            <Field label="Type"><select className="input" value={form.document_type} onChange={(e) => setForm({ ...form, document_type: e.target.value })}>{DOC_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}</select></Field>
            <Field label="Description"><input className="input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
            <Field label="File"><input className="input" type="file" onChange={(e) => setForm({ ...form, file: e.target.files?.[0] })} required /></Field>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-outline" onClick={() => setShowUpload(false)}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Uploading…' : 'Upload'}</button>
            </div>
          </form>
        </div></div>
      )}
    </div>
  );
}
export { LicenseDocumentsPage };
export default LicenseDocumentsPage;

