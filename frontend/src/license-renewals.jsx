import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import { Field, DataTable, Pager, PageHeader } from './components';
import { fetchPage, parseApiError } from './api-utils';
import { RENEWAL_STATUS_LABELS, AGREEMENT_STATUS_LABELS } from './licensing-utils';

function LicenseRenewalsPage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [page] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [f, setF] = useState({ search: '', status: '' });
  const loadUrl = async (url) => {
    setLoading(true); setError('');
    try { const pg = await fetchPage(url); setItems(pg.items); setCount(pg.count); setNext(pg.next); setPrevious(pg.previous); } catch { setError('Could not load renewals.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { loadUrl(`/licensing/renewals/?page=${page}${f.status ? '&status=' + f.status : ''}`); }, [page, f.status]); // eslint-disable-line react/set-state-in-effect
  const [busyId, setBusyId] = useState(null);
  const doAction = async (id, action, body = {}) => {
    if (busyId) return;
    setBusyId(id); setError('');
    try { await api.post(`/licensing/renewals/${id}/${action}/`, body); await loadUrl(`/licensing/renewals/?page=${page}`); } catch (e) { setError(parseApiError(e).global || 'Action failed.'); }
    finally { setBusyId(null); }
  };
  const columns = [
    { key: 'agreement_number', label: 'Agreement' },
    { key: 'product_name', label: 'Product' },
    { key: 'agreement_status', label: 'Agreement Status', render: (v) => AGREEMENT_STATUS_LABELS[v.agreement_status] || v.agreement_status || '—' },
    { key: 'previous_expiry_date', label: 'Current Expiry' },
    { key: 'proposed_expiry_date', label: 'Proposed Expiry' },
    { key: 'proposed_quantity', label: 'Qty' },
    { key: 'proposed_total_cost', label: 'Cost' },
    { key: 'currency', label: 'Currency' },
    { key: 'status', label: 'Status', render: (v) => RENEWAL_STATUS_LABELS[v.status] || v.status },
    { key: 'requested_by_email', label: 'Requested By' },
    { key: 'actions', label: 'Actions', render: (v) => (
      <div style={{ display: 'flex', gap: 4 }}>
        {v.status === 'draft' && <button className="btn btn-sm btn-outline" disabled={busyId === v.id} onClick={() => doAction(v.id, 'submit')}>Submit</button>}
        {v.status === 'submitted' && caps.canApproveRenewals && <>
          <button className="btn btn-sm btn-outline" disabled={busyId === v.id} onClick={() => doAction(v.id, 'approve', { decision: 'approved' })}>Approve</button>
          <button className="btn btn-sm btn-outline danger" disabled={busyId === v.id} onClick={() => doAction(v.id, 'reject', { decision: 'rejected', review_reason: 'rejected' })}>Reject</button>
        </>}
        {v.status === 'approved' && (
          <button
            className="btn btn-sm btn-outline"
            disabled={busyId === v.id || ['draft', 'terminated', 'retired'].includes(v.agreement_status)}
            title={['draft', 'terminated', 'retired'].includes(v.agreement_status) ? 'Agreement is not eligible for renewal application' : ''}
            onClick={() => doAction(v.id, 'apply')}
          >
            Apply
          </button>
        )}
        <button className="btn btn-sm btn-outline" disabled={busyId === v.id} onClick={() => doAction(v.id, 'cancel')}>Cancel</button>
      </div>
    ) },
  ];
  if (!caps.canManageRenewals && !caps.canView) return <div className="panel-pad">Access denied.</div>;
  return (
    <div className="license-renewals-page">
      <PageHeader title="License Renewals" />
      <div className="page-toolbar" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <Field label="Status" required={false}><select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All</option>{Object.entries(RENEWAL_STATUS_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      </div>
      {error && <div className="alert alert-danger">{error}</div>}
      <DataTable columns={columns} rows={items} keyOf={(r) => r.id} loading={loading} emptyTitle="No renewals found" />
      {count !== null && <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />}
    </div>
  );
}
export { LicenseRenewalsPage };
export default LicenseRenewalsPage;
