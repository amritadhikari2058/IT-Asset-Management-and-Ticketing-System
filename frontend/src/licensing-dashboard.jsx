import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import { PageHeader, EmptyState } from './components';
import api from './api';
import { formatMoney } from './licensing-utils';

export function LicensingDashboard() {
  const { canViewLicenseReports } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = async () => {
    setLoading(true); setError('');
    try {
      const r = await api.get('/licensing/dashboard/');
      setData(r.data);
    } catch (e) { setError(e.response?.data?.detail || 'Could not load dashboard.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);
  if (loading) return <div className="panel-pad">Loading licensing dashboard…</div>;
  if (error) return <div className="alert alert-danger">{error} <button className="btn btn-sm" onClick={load}>Retry</button></div>;
  if (!data) return <EmptyState title="No data" />;
  const kpis = [
    ['Active Products', data.active_products],
    ['Active Agreements', data.active_agreements],
    ['Purchased Seats', data.purchased_seats],
    ['Allocated Seats', data.allocated_seats],
    ['Available Seats', data.available_seats],
    ['Utilization', data.utilization_percent != null ? `${data.utilization_percent}%` : '—'],
    ['Expiring 30d', data.expiring_30],
    ['Expiring 60d', data.expiring_60],
    ['Expiring 90d', data.expiring_90],
    ['Expired', data.expired],
    ['Pending Renewals', data.pending_renewals],
    ['Unused Findings', data.unused_findings],
    ['Unlicensed Installations', data.unlicensed_installations],
    ['Prohibited Findings', data.prohibited_findings],
  ];
  return (
    <div className="licensing-dashboard">
      <PageHeader title="Software Licensing Dashboard" />
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
      {canViewLicenseReports && data.annual_recurring_cost_by_currency && (
        <div className="card mb-3"><div className="card-body">
          <h5>Annual Recurring Cost by Currency</h5>
          <ul className="list-unstyled mb-0">
            {Object.entries(data.annual_recurring_cost_by_currency).map(([c, v]) => (
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
                {(data.expiring_agreements || []).map((a) => <tr key={a.id}><td>{a.agreement_number}</td><td>{a.product_name}</td><td>{a.expiry_date}</td></tr>)}
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
