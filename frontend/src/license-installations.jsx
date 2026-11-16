import { useEffect, useMemo, useState } from 'react';
import { useAuth } from './auth';
import { Badge, Field, EmptyState, DataTable, Pager, PageHeader } from './components';
import { fetchPage } from './api-utils';
import api from './api';
import { licensingCapabilities } from './licensing-utils';
import { INSTALLATION_STATUS_LABELS, COMPLIANCE_STATUS_LABELS } from './licensing-utils';

function LicenseInstallationsPage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [f, setF] = useState({ search: '' });
  const loadUrl = async (url) => {
    setLoading(true); setError('');
    try { const pg = await fetchPage(url); setItems(pg.items); setCount(pg.count); setNext(pg.next); setPrevious(pg.previous); } catch { setError('Could not load installations.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { loadUrl(`/licensing/installations/?page=${page}`); }, [page]);
  const columns = [
    { key: 'product_name', label: 'Product' },
    { key: 'asset_tag', label: 'Asset' },
    { key: 'installed_version', label: 'Version' },
    { key: 'install_date', label: 'Install Date' },
    { key: 'source', label: 'Source' },
    { key: 'status', label: 'Status', render: (v) => INSTALLATION_STATUS_LABELS[v.status] || v.status },
    { key: 'is_authorized', label: 'Authorized', render: (v) => v.is_authorized ? 'Yes' : 'No' },
    { key: 'compliance_status', label: 'Compliance', render: (v) => COMPLIANCE_STATUS_LABELS[v.compliance_status] || v.compliance_status },
    { key: 'last_seen_at', label: 'Last Seen' },
  ];
  if (!caps.canManageInstallations && !caps.canView) return <div className="panel-pad">Access denied.</div>;
  return (
    <div className="license-installations-page">
      <PageHeader title="Software Installations" />
      {error && <div className="alert alert-danger">{error}</div>}
      <DataTable columns={columns} rows={items} keyOf="id" loading={loading} emptyTitle="No installations found" />
      {count !== null && <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />}
    </div>
  );
}
export { LicenseInstallationsPage };
export default LicenseInstallationsPage;
