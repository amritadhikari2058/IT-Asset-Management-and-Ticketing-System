import { useEffect, useMemo, useState } from 'react';
import { useAuth } from './auth';
import { Badge, Field, EmptyState, DataTable, Pager, PageHeader, Modal, ConfirmDialog } from './components';
import { fetchPage } from './api-utils';
import { parseApiError } from './api-utils';
import api from './api';
import { licensingCapabilities, buildAllocationListUrl, ALLOCATION_TYPE_LABELS, ALLOCATION_STATUS_LABELS, allocationStatusBadgeVariant } from './licensing-utils';

function LicenseAllocationsPage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [f, setF] = useState({ search: '', status: '', allocation_type: '', agreement: '' });
  const loadUrl = async (url) => {
    setLoading(true); setError('');
    try { const pg = await fetchPage(url); setItems(pg.items); setCount(pg.count); setNext(pg.next); setPrevious(pg.previous); } catch { setError('Could not load allocations.'); }
    finally { setLoading(false); }
  };
  const builtUrl = useMemo(() => buildAllocationListUrl(f, null, page), [f, page]);
  useEffect(() => { const t = setTimeout(() => loadUrl(builtUrl), 250); return () => clearTimeout(t); }, [builtUrl]);
  const doAction = async (id, action, body = {}) => {
    try { await api.post(`/licensing/allocations/${id}/${action}/`, body); loadUrl(builtUrl); } catch (e) { setError(parseApiError(e).global || 'Action failed.'); }
  };
  const columns = [
    { key: 'product_name', label: 'Product' },
    { key: 'agreement_number', label: 'Agreement' },
    { key: 'allocation_type', label: 'Type', render: (v) => ALLOCATION_TYPE_LABELS[v.allocation_type] || v.allocation_type },
    { key: 'user_email', label: 'User' },
    { key: 'asset_tag', label: 'Asset' },
    { key: 'status', label: 'Status', render: (v) => <Badge kind="status" value={ALLOCATION_STATUS_LABELS[v.status] || v.status} /> },
    { key: 'assigned_at', label: 'Assigned' },
    { key: 'last_verified_at', label: 'Verified' },
    { key: 'actions', label: 'Actions', render: (v) => (
      <div style={{ display: 'flex', gap: 4 }}>
        {v.status !== 'active' && <button className="btn btn-sm btn-outline" onClick={() => doAction(v.id, 'activate')}>Activate</button>}
        <button className="btn btn-sm btn-outline" onClick={() => doAction(v.id, 'verify')}>Verify</button>
        <button className="btn btn-sm btn-outline danger" onClick={() => { const r = prompt('Revocation reason:'); if (r) doAction(v.id, 'revoke', { reason: r }); }}>Revoke</button>
      </div>
    ) },
  ];
  if (!caps.canManageAllocations) return <div className="panel-pad">Access denied.</div>;
  return (
    <div className="license-allocations-page">
      <PageHeader title="License Allocations" />
      <div className="page-toolbar" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <Field label="Search" required={false}><input className="input" value={f.search} onChange={(e) => setF({ ...f, search: e.target.value })} /></Field>
        <Field label="Status" required={false}><select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All</option>{Object.entries(ALLOCATION_STATUS_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Type" required={false}><select className="input" value={f.allocation_type} onChange={(e) => setF({ ...f, allocation_type: e.target.value })}><option value="">All</option>{Object.entries(ALLOCATION_TYPE_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      </div>
      {error && <div className="alert alert-danger">{error}</div>}
      <DataTable columns={columns} rows={items} keyOf="id" loading={loading} emptyTitle="No allocations found" />
      {count !== null && <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />}
    </div>
  );
}
export { LicenseAllocationsPage };
export default LicenseAllocationsPage;
