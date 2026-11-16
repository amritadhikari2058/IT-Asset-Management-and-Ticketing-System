import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import { EmptyState, PageHeader, DataTable } from './components';
import { fetchPage } from './api-utils';
import api from './api';
import { licensingCapabilities } from './licensing-utils';

function LicenseUtilizationPage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    setLoading(true);
    api.get('/licensing/utilization-report/').then((r) => { setItems(Array.isArray(r.data) ? r.data : (r.data.results || [])); }).catch((e) => setError(e.response?.data?.detail || 'Could not load report.')).finally(() => setLoading(false));
  }, []);
  if (loading) return <div className="panel-pad">Loading utilization…</div>;
  if (error) return <div className="alert alert-danger">{error}</div>;
  const columns = [
    { key: 'agreement_number', label: 'Agreement' },
    { key: 'product_name', label: 'Product' },
    { key: 'license_model', label: 'Model' },
    { key: 'quantity_purchased', label: 'Purchased' },
    { key: 'quantity_reserved', label: 'Reserved' },
    { key: 'quantity_allocated', label: 'Allocated' },
    { key: 'quantity_available', label: 'Available' },
    { key: 'utilization_percent', label: 'Utilization' },
  ];
  return (
    <div className="license-utilization-page">
      <PageHeader title="License Utilization" />
      <DataTable columns={columns} rows={items} keyOf="id" loading={loading} emptyTitle="No data" />
    </div>
  );
}
export { LicenseUtilizationPage };
export default LicenseUtilizationPage;
