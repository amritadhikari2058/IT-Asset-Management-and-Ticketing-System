import { useEffect, useMemo, useState } from 'react';
import { useAuth } from './auth';
import { EmptyState, PageHeader, DataTable, Field } from './components';
import api from './api';
import {
  licensingCapabilities,
  formatQuantity,
  formatPercent,
  formatUtilization,
  AGREEMENT_STATUS_LABELS,
  LICENSE_MODEL_LABELS,
} from './licensing-utils';

const EXPIRY_OPTIONS = [
  ['', 'Any expiry'],
  ['30', 'Expiring in 30 days'],
  ['60', 'Expiring in 60 days'],
  ['90', 'Expiring in 90 days'],
  ['expired', 'Already expired'],
  ['none', 'No expiry date'],
];

function LicenseUtilizationPage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filters, setFilters] = useState({ status: '', vendor: '', license_type: '', expiry: '', overallocated: '' });

  const params = useMemo(() => {
    const out = {};
    Object.entries(filters).forEach(([k, v]) => { if (v) out[k] = v; });
    return out;
  }, [filters]);

  useEffect(() => {
    setLoading(true); setError('');
    api.get('/licensing/utilization-report/', { params })
      .then((r) => {
        setItems(Array.isArray(r.data) ? r.data : (r.data.results || []));
        setSummary(r.data?.summary || null);
      })
      .catch((e) => setError(e.response?.data?.detail || 'Could not load report.'))
      .finally(() => setLoading(false));
  }, [params]);

  const setFilter = (key, value) => setFilters((prev) => ({ ...prev, [key]: value }));
  const clearFilters = () => setFilters({ status: '', vendor: '', license_type: '', expiry: '', overallocated: '' });
  const hasFilters = Object.values(filters).some(Boolean);

  if (loading) return <div className="panel-pad">Loading utilization…</div>;
  if (error) return <div className="alert alert-danger">{error}</div>;

  const columns = [
    { key: 'agreement_name', label: 'Agreement', render: (v) => <a href={`#/licenses/${v.id}`}>{v.agreement_name}</a> },
    { key: 'product_name', label: 'Product' },
    { key: 'vendor', label: 'Vendor' },
    { key: 'license_metric', label: 'Metric', render: (v) => LICENSE_MODEL_LABELS[v.license_metric] || v.license_metric },
    { key: 'purchased_entitlement', label: 'Purchased', render: (v) => (v.is_unlimited ? 'Unlimited' : formatQuantity(v.purchased_entitlement)) },
    { key: 'current_usage', label: 'Current usage' },
    { key: 'available_entitlement', label: 'Available', render: (v) => (v.is_unlimited ? '—' : formatQuantity(v.available_entitlement)) },
    {
      key: 'utilization_percent',
      label: 'Utilization',
      render: (v) => (
        <span title={v.utilization_note || undefined}>
          {formatUtilization(v)}
          {v.is_overallocated && <span className="badge bg-danger ms-1">Over</span>}
        </span>
      ),
    },
    { key: 'expiry_date', label: 'Expiry' },
    {
      key: 'open_findings',
      label: 'Open findings',
      render: (v) => (v.open_findings ? <a href="#/license-compliance">{v.open_findings}</a> : '0'),
    },
  ];

  return (
    <div className="license-utilization-page">
      <PageHeader title="License Utilization" />

      <div className="page-toolbar" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <Field label="Agreement status" required={false}>
          <select className="input" value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
            <option value="">All statuses</option>
            {Object.entries(AGREEMENT_STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Vendor" required={false}>
          <input className="input" placeholder="Vendor name" value={filters.vendor} onChange={(e) => setFilter('vendor', e.target.value)} />
        </Field>
        <Field label="License metric" required={false}>
          <select className="input" value={filters.license_type} onChange={(e) => setFilter('license_type', e.target.value)}>
            <option value="">All metrics</option>
            {Object.entries(LICENSE_MODEL_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Expiry period" required={false}>
          <select className="input" value={filters.expiry} onChange={(e) => setFilter('expiry', e.target.value)}>
            {EXPIRY_OPTIONS.map(([k, v]) => <option key={k || 'any'} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Over-allocation" required={false}>
          <select className="input" value={filters.overallocated} onChange={(e) => setFilter('overallocated', e.target.value)}>
            <option value="">All agreements</option>
            <option value="true">Only overallocated</option>
          </select>
        </Field>
        {hasFilters && <div style={{ alignSelf: 'flex-end' }}><button className="btn btn-sm btn-outline" onClick={clearFilters}>Clear filters</button></div>}
      </div>

      {summary && (
        <div className="row g-3 mb-3">
          {[
            ['Purchased entitlement', formatQuantity(summary.total_entitlement_quantity)],
            ['Current usage', summary.current_usage],
            ['Available', formatQuantity(summary.available_entitlement)],
            ['Overallocated agreements', summary.overallocated_agreements],
            ['Overall utilization', summary.utilization_percent == null ? 'Not calculable' : formatPercent(summary.utilization_percent)],
          ].map(([label, value]) => (
            <div className="col-md-3 col-sm-6" key={label}>
              <div className="card"><div className="card-body">
                <div className="text-muted small">{label}</div>
                <div className="fs-5 fw-bold">{value ?? '—'}</div>
              </div></div>
            </div>
          ))}
        </div>
      )}

      {items.length === 0
        ? <EmptyState title="No agreements match these filters" />
        : <DataTable columns={columns} rows={items} keyOf={(r) => r.id} loading={loading} emptyTitle="No data" />}
    </div>
  );
}
export { LicenseUtilizationPage };
export default LicenseUtilizationPage;
