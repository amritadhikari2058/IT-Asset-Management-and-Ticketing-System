import { useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { PageHeader } from '../../components';
import api from '../../api';
import { HistoryList } from './LicenseHistory';
import {
  licensingCapabilities,
  formatQuantity,
  formatPercent,
  AGREEMENT_STATUS_LABELS,
  LICENSE_MODEL_LABELS,
} from '../../shared/licensing-utils';

function LicenseAgreementDetail({ id, agreementId }) {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const aid = id || agreementId;
  const [agreement, setAgreement] = useState(null);
  const [utilization, setUtilization] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [historyItems, setHistoryItems] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState('');
  const load = async () => {
    setLoading(true); setError('');
    try {
      const [agreementResponse, utilizationResponse] = await Promise.all([
        api.get(`/licensing/agreements/${aid}/`),
        api.get(`/licensing/agreements/${aid}/utilization/`).catch(() => null),
      ]);
      setAgreement(agreementResponse.data);
      setUtilization(utilizationResponse?.data || null);
    } catch (e) { setError(e.response?.data?.detail || 'Could not load agreement.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { if (aid) load(); }, [aid]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect
  useEffect(() => {
    let cancelled = false;
    if (!aid) return undefined;
    setHistoryLoading(true); // eslint-disable-line react/set-state-in-effect
    setHistoryError(''); // eslint-disable-line react/set-state-in-effect
    api.get(`/licensing/agreements/${aid}/history/`)
      .then((r) => {
        if (cancelled) return;
        setHistoryItems(Array.isArray(r.data) ? r.data : (r.data?.results || []));
      })
      .catch((e) => {
        if (cancelled) return;
        setHistoryError(e?.response?.status === 403
          ? 'You do not have permission to view this agreement history.'
          : (e?.response?.data?.detail || 'Could not load agreement history.'));
      })
      .finally(() => { if (!cancelled) setHistoryLoading(false); });
    return () => { cancelled = true; };
  }, [aid]);
  const doAction = async (action, body = {}) => {
    try { await api.post(`/licensing/agreements/${aid}/${action}/`, body); await load(); } catch (e) { setError(e.response?.data?.detail || 'Action failed.'); }
  };
  if (loading) return <div className="panel-pad">Loading agreement…</div>;
  if (error) return <div className="alert alert-danger">{error}</div>;
  if (!agreement) return null;
  return (
    <div className="license-agreement-detail">
      <PageHeader title={agreement.agreement_number} />
      <div className="card mb-3"><div className="card-body">
        <div><strong>Product:</strong> {agreement.product_name}</div>
        <div><strong>Status:</strong> {AGREEMENT_STATUS_LABELS[agreement.status]}</div>
        <div><strong>Capacity:</strong> {agreement.is_unlimited ? 'Unlimited' : `${agreement.quantity_allocated}/${agreement.quantity_purchased} (avail ${agreement.quantity_available})`}</div>
        <div><strong>Utilization:</strong> {utilization?.utilization_calculable === false ? (utilization.utilization_note || 'Not calculable') : formatPercent(utilization?.reconciled_utilization_percent ?? agreement.utilization_percent)}</div>
        {caps.canViewCosts && <div><strong>Cost:</strong> {agreement.currency} {agreement.total_cost}</div>}
        <div><strong>Expiry:</strong> {agreement.expiry_date}</div>
        <div><strong>Renewal:</strong> {agreement.renewal_date}</div>
      </div></div>

      {utilization && (
        <div className="card mb-3"><div className="card-body">
          <h5>Entitlement reconciliation</h5>
          {utilization.overallocated_quantity > 0 && (
            <div className="alert alert-danger" role="alert">
              Overallocated by {formatQuantity(utilization.overallocated_quantity)} allocation(s): usage exceeds purchased entitlement.
            </div>
          )}
          <div className="row g-2">
            {[
              ['Metric', LICENSE_MODEL_LABELS[utilization.license_model] || utilization.license_model],
              ['Purchased entitlement', utilization.is_unlimited ? 'Unlimited' : formatQuantity(utilization.purchased_entitlement_quantity)],
              ['Active allocated', utilization.active_allocated_quantity],
              ['Reserved', utilization.consuming_quantity - utilization.active_allocated_quantity],
              ['Available', utilization.is_unlimited ? '—' : formatQuantity(utilization.available_entitlement_quantity)],
              ['Suspended', utilization.suspended_allocation_quantity],
              ['Released/revoked', utilization.released_allocation_quantity],
              ['Expired allocations', utilization.expired_allocation_quantity],
              ['Open findings', utilization.open_findings],
            ].map(([label, value]) => (
              <div className="col-md-4 col-sm-6" key={label}>
                <div className="text-muted small">{label}</div>
                <div className="fw-bold">{value ?? '—'}</div>
              </div>
            ))}
          </div>
          {utilization.utilization_note && <p className="text-muted small mt-2 mb-0">{utilization.utilization_note}</p>}
          <div className="mt-2">
            <a className="btn-small btn-secondary" href="#/license-compliance">View compliance findings</a>{' '}
            <a className="btn-small btn-secondary" href={`#/licenses/${aid}/allocations`}>View allocations</a>
          </div>
        </div></div>
      )}
      {caps.canManageAgreements && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <a className="btn-secondary" href={`#/licenses/${aid}/edit`}>Edit</a>
          <button className="btn-secondary" onClick={() => doAction('activate')}>Activate</button>
          <button className="btn-secondary" onClick={() => doAction('suspend', { reason: 'suspended' })}>Suspend</button>
          <button className="btn-secondary" onClick={() => doAction('resume')}>Resume</button>
          <button className="btn-secondary" onClick={() => doAction('recalculate')}>Recalculate</button>
          <button className="btn btn-outline danger" onClick={() => doAction('terminate', { reason: 'terminated' })}>Terminate</button>
        </div>
      )}
      <div className="card mt-3" id="history"><div className="card-body">
        <h5>History</h5>
        <p className="text-muted small">Latest 100 agreement, allocation, and secret lifecycle events.</p>
        <HistoryList
          items={historyItems}
          loading={historyLoading}
          error={historyError}
          emptyText="No history recorded for this agreement."
        />
      </div></div>
      <div className="mt-3">
        <a className="btn-small btn-secondary" href={`#/licenses/${aid}/allocations`}>Allocations</a>{' '}
        <a className="btn-small btn-secondary" href={`#/licenses/${aid}/installations`}>Installations</a>{' '}
        <a className="btn-small btn-secondary" href={`#/licenses/${aid}/documents`}>Documents</a>{' '}
        <a className="btn-small btn-secondary" href={`#/licenses/${aid}/history`}>History</a>{' '}
        <a className="btn-small btn-secondary" href={`#/licenses/${aid}/renewal`}>Renewal</a>
      </div>
    </div>
  );
}
export { LicenseAgreementDetail };
export default LicenseAgreementDetail;

