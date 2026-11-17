import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, PageHeader, LoadingRows,
} from './components';
import {
  formatDate, formatDateTime, formatPercent, ciStatusBadgeVariant,
  criticalityBadgeVariant, driftStatusBadgeVariant, baselineStatusBadgeVariant,
  safeResults, formatVerificationAge,
} from './cmdb-utils';

const ASSET_STATUS_ORDER = ['available', 'assigned', 'in_repair', 'retired', 'lost', 'disposed'];
const TICKET_STATUS_ORDER = ['open', 'in_progress', 'reopened', 'resolved', 'closed', 'archived'];
const TICKET_PRIORITY_ORDER = ['low', 'medium', 'high', 'critical'];

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

// ── Distribution bar component ─────────────────────────────────────────
function Distribution({ title, data, order, href }) {
  const entries = order.filter((k) => k in (data || {}));
  const max = Math.max(1, ...entries.map((k) => data[k] || 0));
  const total = entries.reduce((sum, k) => sum + (data[k] || 0), 0);
  return (
    <div className="panel panel-pad">
      <div className="panel-head">
        <h2>{title}</h2>
        {href ? <a className="link-small" href={href}>View all</a> : null}
      </div>
      {!total ? <p className="muted">No data yet.</p> : entries.map((k) => (
        <div className="dist-row" key={k}>
          <span className="dist-label">{prettyLabel(k)}</span>
          <span className="dist-bar" aria-hidden="true">
            <span className="dist-fill"
              style={{ width: `${Math.round(((data[k] || 0) / max) * 100)}%` }} />
          </span>
          <span className="dist-value">{data[k] || 0}</span>
        </div>
      ))}
    </div>
  );
}

function prettyLabel(value) {
  // Use actual label maps for known values; fall back to human-readable
  if (value === 'active' || value === 'planned' || value === 'inactive'
    || value === 'maintenance' || value === 'degraded' || value === 'failed'
    || value === 'retired' || value === 'disposed') return ciStatusBadgeVariant(value)?.toString() ?? String(value).replace(/_/g, ' ');
  if (value === 'critical' || value === 'high' || value === 'medium' || value === 'low')
    return criticalityBadgeVariant(value)?.toString() ?? String(value).replace(/_/g, ' ');
  if (value === 'open' || value === 'acknowledged' || value === 'resolved'
    || value === 'accepted' || value === 'false_positive') return driftStatusBadgeVariant(value)?.toString() ?? String(value).replace(/_/g, ' ');
  if (value === 'approved' || value === 'pending_approval' || value === 'draft'
    || value === 'superseded' || value === 'retired') return baselineStatusBadgeVariant(value)?.toString() ?? String(value).replace(/_/g, ' ');
  return String(value).replace(/_/g, ' ');
}

// ── Main Dashboard component ───────────────────────────────────────────

export function Dashboard() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    // Employees are denied CMDB dashboard access
    if (role === 'employee') {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError('');
    api.get('/cmdb/dashboard')
      .then((r) => { if (!cancelled) setData(r.data); })
      .catch((e) => { if (!cancelled) setError('Could not load dashboard metrics.'); })
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
        sub={`Updated ${formatDateTime(d.generated_at)}`}
        actions={[]}
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
          href="#/cmdb/items/:id"
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
          <p className="muted">No recent CI updates loaded. <a href="#/cmdb/items/history">View CI history</a>.</p>
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