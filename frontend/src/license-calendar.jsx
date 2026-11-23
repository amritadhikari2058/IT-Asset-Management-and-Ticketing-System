import { useEffect, useState } from 'react';
import { PageHeader } from './components';
import api from './api';

function LicenseCalendarPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    setLoading(true); // eslint-disable-line react/set-state-in-effect
    api.get('/licensing/renewal-calendar/').then((r) => setData(r.data)).catch((e) => setError(e.response?.data?.detail || 'Could not load calendar.')).finally(() => setLoading(false));
  }, []);
  if (loading) return <div className="panel-pad">Loading calendar…</div>;
  if (error) return <div className="alert alert-danger">{error}</div>;
  const groups = data?.groups || data || {};
  return (
    <div className="license-calendar-page">
      <PageHeader title="License Renewal Calendar" />
      {Array.isArray(groups) ? groups.map((g, i) => (
        <div className="card mb-3" key={i}><div className="card-body">
          <h5>{g.label || `Group ${i + 1}`}</h5>
          <table className="table table-sm"><tbody>
            {(g.items || []).map((a) => <tr key={a.id}><td>{a.agreement_number}</td><td>{a.product_name}</td><td>{a.expiry_date}</td><td>{a.days_remaining}</td></tr>)}
          </tbody></table>
        </div></div>
      )) : <pre>{JSON.stringify(groups, null, 2)}</pre>}
    </div>
  );
}
export { LicenseCalendarPage };
export default LicenseCalendarPage;
