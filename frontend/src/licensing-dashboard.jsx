import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import { PageHeader, EmptyState, Field } from './components';
import api from './api';
import {
  formatMoney,
  formatPercent,
  formatQuantity,
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

export function LicensingDashboard() {
  const { canViewLicenseReports } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filters, setFilters] = useState({ status: '', vendor: '', license_type: '', expiry: '' });

  const load = async () => {
    setLoading(true); setError('');
    try {
      const params = {};
      Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
      const r = await api.get('/licensing/dashboard/', { params });
      setData(r.data);
    } catch (e) { setError(e.response?.data?.detail || 'Could not load dashboard.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [filters.status, filters.vendor, filters.license_type, filters.expiry]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect

  const setFilter = (key, value) => setFilters((prev) => ({ ...prev, [key]: value }));
  const clearFilters = () => setFilters({ status: '', vendor: '', license_type: '', expiry: '' });
  const hasFilters = Object.values(filters).some(Boolean);

  if (loading) return <div className="panel-pad">Loading licensing dashboard…</div>;
  if (error) return <div className="alert alert-danger">{error} <button className="btn btn-sm" onClick={load}>Retry</button></div>;
  if (!data) return <EmptyState title="No data" />;

  const kpis = [
    ['Active Products', data.active_products],
    ['Total Agreements', data.total_agreements],
    ['Active Agreements', data.active_agreements],
    ['Expired Agreements', data.expired ?? data.expired_agreements],
    ['Approaching Expiry', data.approaching_expiry_agreements],
    ['Total Entitlement', formatQuantity(data.total_entitlement_quantity)],
    ['Active Usage', data.active_usage ?? data.allocated_seats],
    ['Available Entitlement', formatQuantity(data.available_entitlements)],
    ['Overallocated Agreements', data.overallocated_agreements],
    ['Pending Renewals', data.pending_renewals],
    ['Open Compliance Findings', data.open_compliance_findings],
    ['Agreements Requiring Attention', data.agreements_requiring_attention],
    ['Utilization', data.utilization_calculable === false ? 'Not calculable' : formatPercent(data.utilization_percent)],
  ];

  return (
    <div className="licensing-dashboard">
      <PageHeader title="Software Licensing Dashboard" />

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
        {hasFilters && <div style={{ alignSelf: 'flex-end' }}><button className="btn btn-sm btn-outline" onClick={clearFilters}>Clear filters</button></div>}
      </div>

      {Number(data.overallocated_agreements) > 0 && (
        <div className="alert alert-danger" role="alert">
          {data.overallocated_agreements} agreement(s) exceed purchased entitlement by {formatQuantity(data.overallocated_quantity)} allocation(s).{' '}
          <a href="#/license-compliance">Review compliance findings</a>.
        </div>
      )}

      <div className="row g-3 mb-3">
        {kpis.map(([label, val]) => (
          <div className="col-md-3 col-sm-6" key={label}>
            <div className="card"><div className="card-body">
              <div className="text-muted small">{label}</div>
              <div className="fs-4 fw-bold">{val ?? '—'}</div>
            </div></div>
          </div>
        ))}
      </div>

      <div className="mb-3" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <a className="btn btn-sm btn-outline" href="#/license-utilization">Entitlement utilization report</a>
        <a className="btn btn-sm btn-outline" href="#/license-compliance">Compliance findings</a>
        <a className="btn btn-sm btn-outline" href="#/license-renewals">Renewals</a>
      </div>

      {canViewLicenseReports && (data.annual_recurring_cost_by_currency || data.annual_cost_by_currency) && (
        <div className="card mb-3"><div className="card-body">
          <h5>Annual Recurring Cost by Currency</h5>
          <ul className="list-unstyled mb-0">
            {Object.entries(data.annual_recurring_cost_by_currency || data.annual_cost_by_currency).map(([c, v]) => (
              <li key={c}>{c}: {formatMoney(v, c)}</li>
            ))}
          </ul>
        </div></div>
      )}

      <div className="row g-3">
        <div className="col-md-6">
          <div className="card"><div className="card-body">
            <h5>Expiring Agreements</h5>
            {(data.expiring_agreements || []).length === 0 ? <p className="text-muted">None</p> : (
              <table className="table table-sm"><tbody>
                {(data.expiring_agreements || []).map((a) => (
                  <tr key={a.id}>
                    <td><a href={`#/licenses/${a.id}`}>{a.agreement_number}</a></td>
                    <td>{a.product_name}</td>
                    <td>{a.expiry_date}</td>
                  </tr>
                ))}
              </tbody></table>
            )}
          </div></div>
        </div>
        <div className="col-md-6">
          <div className="card"><div className="card-body">
            <h5>Pending Renewals</h5>
            {(data.pending_renewals_list || []).length === 0 ? <p className="text-muted">None</p> : (
              <table className="table table-sm"><tbody>
                {(data.pending_renewals_list || []).map((r) => <tr key={r.id}><td>{r.agreement_number}</td><td>{r.status}</td></tr>)}
              </tbody></table>
            )}
          </div></div>
        </div>
      </div>
    </div>
  );
}
