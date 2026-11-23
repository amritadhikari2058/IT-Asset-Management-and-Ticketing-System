import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import { PageHeader, DataTable, AccessDenied } from './components';
import api from './api';
import { licensingCapabilities } from './licensing-utils';

function MySoftwarePage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    setLoading(true); // eslint-disable-line react/set-state-in-effect
    api.get('/licensing/allocations/my-software/').then((r) => setItems(r.data.results || r.data || [])).catch((e) => setError(e.response?.data?.detail || 'Could not load.')).finally(() => setLoading(false));
  }, []);
  if (!caps.canViewMySoftware) return <AccessDenied />;
  const columns = [
    { key: 'product_name', label: 'Product' },
    { key: 'publisher', label: 'Publisher' },
    { key: 'edition', label: 'Edition' },
    { key: 'version', label: 'Version' },
    { key: 'allocation_type', label: 'Type' },
    { key: 'status', label: 'Status' },
    { key: 'assigned_at', label: 'Assigned' },
    { key: 'expected_release_date', label: 'Expiry' },
    { key: 'asset_tag', label: 'Asset' },
    { key: 'last_verified_at', label: 'Verified' },
  ];
  return (
    <div className="my-software-page">
      <PageHeader title="My Software" />
      {error && <div className="alert alert-danger">{error}</div>}
      <DataTable columns={columns} rows={items} keyOf={(r) => r.id} loading={loading} emptyTitle="No software allocated" />
    </div>
  );
}
export { MySoftwarePage };
export default MySoftwarePage;
