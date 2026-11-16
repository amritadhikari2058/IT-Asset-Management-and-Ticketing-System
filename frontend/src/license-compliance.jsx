import { useEffect, useMemo, useState } from 'react';
import { useAuth } from './auth';
import { Badge, Field, EmptyState, DataTable, Pager, PageHeader } from './components';
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
  const [f, setF] = useState({ search: '', finding_type: '', severity: '', status: '' });
  const loadUrl = async (url) => {
    setLoading(true); setError('');
    try { const pg = await fetchPage(url); setItems(pg.items); setCount(pg.count); setNext(pg.next); setPrevious(pg.previous); } catch { setError('Could not load findings.'); }
    finally { setLoading(false); }
  };
  const builtUrl = useMemo(() => buildFindingListUrl(f, null, page), [f, page]);
  useEffect(() => { const t = setTimeout(() => loadUrl(builtUrl), 250); return () => clearTimeout(t); }, [builtUrl]);
  const doAction = async (id, action, body = {}) => {
    try { await api.post(`/licensing/findings/${id}/${action}/`, body); loadUrl(builtUrl); } catch (e) { setError(parseApiError(e).global || 'Action failed.'); }
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
    { key: 'actions', label: 'Actions', render: (v) => (
      <div style={{ display: 'flex', gap: 4 }}>
        <button className="btn btn-sm btn-outline" onClick={() => doAction(v.id, 'acknowledge')}>Acknowledge</button>
        <button className="btn btn-sm btn-outline" onClick={() => { const r = prompt('Resolution note:'); if (r) doAction(v.id, 'resolve', { resolution_note: r }); }}>Resolve</button>
        <button className="btn btn-sm btn-outline" onClick={() => { const r = prompt('Reason:'); if (r) doAction(v.id, 'false-positive', { resolution_note: r }); }}>False Positive</button>
      </div>
    ) },
  ];
  if (!caps.canManageCompliance && !caps.canView) return <div className="panel-pad">Access denied.</div>;
  return (
    <div className="license-compliance-page">
      <PageHeader title="License Compliance Findings" />
      <div className="page-toolbar" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <Field label="Type" required={false}><select className="input" value={f.finding_type} onChange={(e) => setF({ ...f, finding_type: e.target.value })}><option value="">All</option>{Object.entries(FINDING_TYPE_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Severity" required={false}><select className="input" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}><option value="">All</option>{Object.entries(FINDING_SEVERITY_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Status" required={false}><select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All</option>{Object.entries(FINDING_STATUS_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      </div>
      {error && <div className="alert alert-danger">{error}</div>}
      <DataTable columns={columns} rows={items} keyOf="id" loading={loading} emptyTitle="No findings found" />
      {count !== null && <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />}
    </div>
  );
}
export { LicenseCompliancePage };
export default LicenseCompliancePage;
