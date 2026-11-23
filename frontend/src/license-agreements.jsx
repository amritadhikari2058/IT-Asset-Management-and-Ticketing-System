import { useEffect, useMemo, useState } from 'react';
import { useAuth } from './auth';
import { Badge, Field, DataTable, Pager, PageHeader } from './components';
import { fetchPage } from './api-utils';
import { licensingCapabilities, buildAgreementListUrl } from './licensing-utils';
import { AGREEMENT_TYPE_LABELS, AGREEMENT_STATUS_LABELS } from './licensing-utils';

function LicenseAgreementsPage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [page] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [f, setF] = useState({ search: '', status: '', agreement_type: '', license_model: '' });
  const loadUrl = async (url) => {
    setLoading(true); setError('');
    try { const pg = await fetchPage(url); setItems(pg.items); setCount(pg.count); setNext(pg.next); setPrevious(pg.previous); setLastUrl(url); } catch { setError('Could not load agreements.'); }
    finally { setLoading(false); }
  };
  const builtUrl = useMemo(() => buildAgreementListUrl(f, null, page), [f, page]);
  useEffect(() => { const t = setTimeout(() => loadUrl(builtUrl), 250); return () => clearTimeout(t); }, [builtUrl]);
  const columns = [
    { key: 'agreement_number', label: 'Agreement #' },
    { key: 'product_name', label: 'Product' },
    { key: 'vendor_name', label: 'Vendor' },
    { key: 'agreement_type', label: 'Type', render: (v) => AGREEMENT_TYPE_LABELS[v.agreement_type] || v.agreement_type },
    { key: 'status', label: 'Status', render: (v) => <Badge kind="status" value={AGREEMENT_STATUS_LABELS[v.status] || v.status} /> },
    { key: 'start_date', label: 'Start', render: (v) => v.start_date },
    { key: 'expiry_date', label: 'Expiry', render: (v) => v.expiry_date },
    { key: 'quantity_purchased', label: 'Purchased' },
    { key: 'quantity_allocated', label: 'Allocated' },
    { key: 'quantity_available', label: 'Available', render: (v) => v.is_unlimited ? 'Unlimited' : v.quantity_available },
    { key: 'total_cost', label: 'Total Cost', render: (v) => caps.canViewCosts ? `${v.currency} ${v.total_cost}` : '—' },
  ];
  if (caps.canManageAgreements) columns.push({ key: 'actions', label: 'Actions', render: (v) => (<div style={{ display: 'flex', gap: 4 }}><a className="btn btn-sm btn-outline" href={`#/licenses/${v.id}`}>View</a><a className="btn btn-sm btn-outline" href={`#/licenses/${v.id}/edit`}>Edit</a></div>) });
  if (!caps.canView) return <div className="panel-pad">Access denied.</div>;
  return (
    <div className="license-agreements-page">
      <PageHeader title="License Agreements" />
      <div className="page-toolbar" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <Field label="Search" required={false}><input className="input" value={f.search} onChange={(e) => setF({ ...f, search: e.target.value })} /></Field>
        <Field label="Status" required={false}><select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All</option>{Object.entries(AGREEMENT_STATUS_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Type" required={false}><select className="input" value={f.agreement_type} onChange={(e) => setF({ ...f, agreement_type: e.target.value })}><option value="">All</option>{Object.entries(AGREEMENT_TYPE_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        {caps.canManageAgreements && <a className="btn btn-primary" href="#/licenses/new">New Agreement</a>}
      </div>
      {error && <div className="alert alert-danger">{error}</div>}
      <DataTable columns={columns} rows={items} keyOf={(r) => r.id} loading={loading} emptyTitle="No agreements found" />
      {count !== null && <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />}
    </div>
  );
}
export { LicenseAgreementsPage };
export default LicenseAgreementsPage;
