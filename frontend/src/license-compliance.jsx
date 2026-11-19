import { useEffect, useMemo, useState } from 'react';
import { useAuth } from './auth';
import { Badge, Field, EmptyState, DataTable, Pager, PageHeader, Modal } from './components';
import { fetchPage } from './api-utils';
import { parseApiError } from './api-utils';
import api from './api';
import { licensingCapabilities, buildFindingListUrl } from './licensing-utils';
import { FINDING_TYPE_LABELS, FINDING_SEVERITY_LABELS, FINDING_STATUS_LABELS, findingSeverityBadgeVariant, findingStatusBadgeVariant } from './licensing-utils';

function LicenseCompliancePage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [f, setF] = useState({ search: '', finding_type: '', severity: '', status: '' });

  // Remediation state
  const [remediateTarget, setRemediateTarget] = useState(null);
  const [remediateNote, setRemediateNote] = useState('');
  const [remediateReevaluate, setRemediateReevaluate] = useState(false);
  const [remediateBusy, setRemediateBusy] = useState(false);
  const [remediateError, setRemediateError] = useState('');

  const loadUrl = async (url) => {
    setLoading(true); setError('');
    try { const pg = await fetchPage(url); setItems(pg.items); setCount(pg.count); setNext(pg.next); setPrevious(pg.previous); } catch { setError('Could not load findings.'); }
    finally { setLoading(false); }
  };
  const builtUrl = useMemo(() => buildFindingListUrl(f, null, page), [f, page]);
  useEffect(() => { const t = setTimeout(() => loadUrl(builtUrl), 250); return () => clearTimeout(t); }, [builtUrl]);
  const doAction = async (id, action, body = {}) => {
    try { await api.post(`/licensing/findings/${id}/${action}/`, body); setMessage('Action completed.'); loadUrl(builtUrl); } catch (e) { setError(parseApiError(e).global || 'Action failed.'); }
  };

  const openRemediate = (row) => {
    setRemediateTarget(row);
    setRemediateNote('');
    setRemediateReevaluate(false);
    setRemediateError('');
  };
  const closeRemediate = () => { if (!remediateBusy) { setRemediateTarget(null); setRemediateNote(''); setRemediateError(''); } };
  const submitRemediate = async () => {
    if (!remediateTarget || remediateBusy) return;
    setRemediateBusy(true); setRemediateError('');
    try {
      await api.post(`/licensing/findings/${remediateTarget.id}/remediate/`, {
        remediation_note: remediateNote.trim(),
        reevaluate: remediateReevaluate,
      });
      setMessage('Remediation recorded.');
      setRemediateTarget(null);
      setRemediateNote('');
      await loadUrl(builtUrl);
    } catch (e) {
      setRemediateError(parseApiError(e).global || 'Remediation failed.');
    } finally {
      setRemediateBusy(false);
    }
  };

  const columns = [
    { key: 'title', label: 'Title' },
    { key: 'finding_type', label: 'Type', render: (v) => FINDING_TYPE_LABELS[v.finding_type] || v.finding_type },
    { key: 'severity', label: 'Severity', render: (v) => <Badge kind="status" value={FINDING_SEVERITY_LABELS[v.severity] || v.severity} /> },
    { key: 'product_name', label: 'Product' },
    { key: 'agreement_number', label: 'Agreement' },
    { key: 'user_email', label: 'User' },
    { key: 'asset_tag', label: 'Asset' },
    { key: 'status', label: 'Status', render: (v) => FINDING_STATUS_LABELS[v.status] || v.status },
    { key: 'detected_at', label: 'Detected' },
    { key: 'resolved_at', label: 'Resolved At' },
    { key: 'actions', label: 'Actions', render: (v) => (
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        <button className="btn btn-sm btn-outline" onClick={() => doAction(v.id, 'acknowledge')}>Acknowledge</button>
        <button className="btn btn-sm btn-outline" onClick={() => openRemediate(v)}>Remediate</button>
        <button className="btn btn-sm btn-outline" onClick={() => { const r = window.prompt('Resolution note:'); if (r) doAction(v.id, 'resolve', { resolution_note: r }); }}>Resolve</button>
        <button className="btn btn-sm btn-outline" onClick={() => { const r = window.prompt('Reason:'); if (r) doAction(v.id, 'false-positive', { resolution_note: r }); }}>False Positive</button>
      </div>
    ) },
  ];
  if (!caps.canManageCompliance && !caps.canView) return <div className="panel-pad">Access denied.</div>;
  return (
    <div className="license-compliance-page">
      <PageHeader title="License Compliance Findings" />
      {message && <div className="alert alert-success">{message}</div>}
      {error && <div className="alert alert-danger">{error}</div>}
      <div className="page-toolbar" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <Field label="Type" required={false}><select className="input" value={f.finding_type} onChange={(e) => setF({ ...f, finding_type: e.target.value })}><option value="">All</option>{Object.entries(FINDING_TYPE_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Severity" required={false}><select className="input" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}><option value="">All</option>{Object.entries(FINDING_SEVERITY_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Status" required={false}><select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All</option>{Object.entries(FINDING_STATUS_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      </div>
      <DataTable columns={columns} rows={items} keyOf="id" loading={loading} emptyTitle="No findings found" />
      {count !== null && <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />}

      {remediateTarget && (
        <Modal title={`Remediate Finding ${remediateTarget.id}`} onClose={closeRemediate}>
          <p>{remediateTarget.title}</p>
          <p className="text-muted">{remediateTarget.description}</p>
          <Field label="Remediation notes" error={remediateError}>
            <textarea className="input" rows={4} value={remediateNote} onChange={(e) => setRemediateNote(e.target.value)} />
          </Field>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 8 }}>
            <input type="checkbox" checked={remediateReevaluate} onChange={(e) => setRemediateReevaluate(e.target.checked)} />
            Re-evaluate compliance after remediation
          </label>
          {remediateError && <div className="alert alert-danger">{remediateError}</div>}
          <div className="row-end" style={{ marginTop: 12 }}>
            <button type="button" className="btn-ghost" onClick={closeRemediate} disabled={remediateBusy}>Cancel</button>
            <button type="button" className="btn-primary" onClick={submitRemediate} disabled={remediateBusy || !remediateNote.trim()}>
              {remediateBusy ? 'Working…' : 'Record Remediation'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
export { LicenseCompliancePage };
export default LicenseCompliancePage;
