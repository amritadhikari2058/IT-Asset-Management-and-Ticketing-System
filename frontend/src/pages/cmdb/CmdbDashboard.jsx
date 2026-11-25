import { useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import {
  PageHeader, LoadingRows,
} from '../../components';
import {
  formatDateTime, ciStatusBadgeVariant, criticalityBadgeVariant, driftStatusBadgeVariant,
  formatVerificationAge,
} from '../../shared/cmdb-utils';

// ── KPI card components ──────────────────────────────────────────────

function Kpi({ label, value, sub, href }) {
  const body = (
    <>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub ? <div className="kpi-sub">{sub}</div> : null}
    </>
  );
  return href
    ? <a className="kpi kpi-link" href={href}>{body}</a>
    : <div className="kpi">{body}</div>;
}

// ── Main Dashboard component ───────────────────────────────────────────

export default function Dashboard() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    // Employees are denied CMDB dashboard access
    if (role === 'employee') {
      setLoading(false); // eslint-disable-line react/set-state-in-effect
      return;
    }

    setLoading(true); // eslint-disable-line react/set-state-in-effect
    setError('');
    api.get('/cmdb/dashboard')
      .then((r) => { if (!cancelled) setData(r.data); })
      .catch(() => { if (!cancelled) setError('Could not load dashboard metrics.'); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [role]);

  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Only IT staff can view the CMDB dashboard.
      </div>
    );
  }

  if (loading && !data) return (
    <div className="panel panel-pad">
      <LoadingRows n={8} />
    </div>
  );
  if (error && !data) return (
    <div className="error-summary" role="alert">{error}</div>
  );

  const d = data || {};

  return (
    <div>
      <PageHeader
        title="CMDB Dashboard"
        sub={`Configuration and relationship overview${d.generated_at ? ` · Updated ${formatDateTime(d.generated_at)}` : ''}`}
        actions={(
          <>
            <a className="btn-primary" href="#/cmdb/items">Configuration Items</a>
            <a className="btn-small" href="#/cmdb/types">CI Types</a>
            <a className="btn-small" href="#/cmdb/baselines">Baselines</a>
            <a className="btn-small" href="#/cmdb/drift">Drift</a>
            <a className="btn-small" href="#/cmdb/verification">Verification</a>
            <a className="btn-small" href="#/cmdb/reports">Reports</a>
          </>
        )}
      />

      <div className="kpi-grid">
        <Kpi
          label="Total CIs"
          value={d.total_cis != null ? d.total_cis.toString() : '—'}
          sub={`${d.active_cis || 0} active · ${d.unverified_cis || 0} unverified`}
          href="#/cmdb/items"
        />
        <Kpi
          label="Active CIs"
          value={d.active_cis != null ? d.active_cis.toString() : '—'}
          sub={ciStatusBadgeVariant(d.active_cis !== undefined ? undefined : undefined)}
          href="#/cmdb/items"
        />
        <Kpi
          label="Critical CIs"
          value={d.critical_cis != null ? d.critical_cis.toString() : '—'}
          sub={criticalityBadgeVariant('critical')}
          href="#/cmdb/items"
        />
        <Kpi
          label="Unverified CIs"
          value={(d.unverified_cis != null ? d.unverified_cis : 0).toString()}
          sub={formatVerificationAge(d.most_recent_unverified)}
          href="#/cmdb/verification"
        />
        <Kpi
          label="Open Drift Findings"
          value={(d.open_drift_findings != null ? d.open_drift_findings : 0).toString()}
          sub={driftStatusBadgeVariant('open')}
          href="#/cmdb/drift"
        />
      </div>

      <div className="split-grid split-2">
        <div className="panel panel-pad">
          <div className="panel-head">
            <h2>Recent CI Updates</h2>
          </div>
          <p className="muted">Use the CI list and item history views to review recent configuration changes. <a href="#/cmdb/items">Browse configuration items</a>.</p>
        </div>
        <div className="panel panel-pad">
          <div className="panel-head">
            <h2>Verification Queue</h2>
          </div>
          <p className="muted">
            {d.unverified_cis || 0} CIs require verification
          </p>
        </div>
      </div>

      <div className="split-grid split-2">
        <div className="panel panel-pad">
          <div className="panel-head">
            <h2>Recent Drift Findings</h2>
          </div>
          <p className="muted">
            {d.open_drift_findings || 0} open drift findings
          </p>
        </div>
        <div className="panel panel-pad">
          <div className="panel-head">
            <h2>Critical Dependencies</h2>
          </div>
          <p className="muted">
            {d.critical_cis || 0} critical CIs identified
          </p>
        </div>
      </div>

      <p className="page-footnote">
        Dashboard metrics are aggregated from the CMDB backend. Individual CI detail,
        verification, drift, and reports are accessible via the navigation menu.
      </p>
    </div>
  );
}
