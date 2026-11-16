import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import { PageHeader, Badge, AccessDenied } from './components';
import api from './api';
import { licensingCapabilities } from './licensing-utils';
import { AGREEMENT_STATUS_LABELS } from './licensing-utils';

function LicenseAgreementDetail({ id, agreementId }) {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const aid = id || agreementId;
  const [agreement, setAgreement] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = async () => {
    setLoading(true); setError('');
    try { const r = await api.get(`/licensing/agreements/${aid}/`); setAgreement(r.data); } catch (e) { setError(e.response?.data?.detail || 'Could not load agreement.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { if (aid) load(); }, [aid]);
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
        <div><strong>Utilization:</strong> {agreement.utilization_percent}%</div>
        {caps.canViewCosts && <div><strong>Cost:</strong> {agreement.currency} {agreement.total_cost}</div>}
        <div><strong>Expiry:</strong> {agreement.expiry_date}</div>
        <div><strong>Renewal:</strong> {agreement.renewal_date}</div>
      </div></div>
      {caps.canManageAgreements && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <a className="btn btn-outline" href={`#/licenses/${aid}/edit`}>Edit</a>
          <button className="btn btn-outline" onClick={() => doAction('activate')}>Activate</button>
          <button className="btn btn-outline" onClick={() => doAction('suspend', { reason: 'suspended' })}>Suspend</button>
          <button className="btn btn-outline" onClick={() => doAction('resume')}>Resume</button>
          <button className="btn btn-outline" onClick={() => doAction('recalculate')}>Recalculate</button>
          <button className="btn btn-outline danger" onClick={() => doAction('terminate', { reason: 'terminated' })}>Terminate</button>
        </div>
      )}
      <div className="mt-3">
        <a className="btn btn-sm btn-outline" href={`#/licenses/${aid}/allocations`}>Allocations</a>{' '}
        <a className="btn btn-sm btn-outline" href={`#/licenses/${aid}/installations`}>Installations</a>{' '}
        <a className="btn btn-sm btn-outline" href={`#/licenses/${aid}/documents`}>Documents</a>{' '}
        <a className="btn btn-sm btn-outline" href={`#/licenses/${aid}/history`}>History</a>{' '}
        <a className="btn btn-sm btn-outline" href={`#/licenses/${aid}/renewal`}>Renewal</a>
      </div>
    </div>
  );
}
export { LicenseAgreementDetail };
export default LicenseAgreementDetail;
