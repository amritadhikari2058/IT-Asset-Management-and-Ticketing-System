import { useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, ExportDialog, LoadingRows, PageHeader,
} from './components';

const ASSET_STATUS_ORDER = ['available', 'assigned', 'in_repair', 'retired', 'lost', 'disposed'];
const TICKET_STATUS_ORDER = ['open', 'in_progress', 'reopened', 'resolved', 'closed', 'archived'];
const TICKET_PRIORITY_ORDER = ['low', 'medium', 'high', 'critical'];

const STATUS_LABELS = {
  available: 'Available', assigned: 'Assigned', in_repair: 'In repair',
  retired: 'Retired', lost: 'Lost', disposed: 'Disposed',
  open: 'Open', in_progress: 'In progress', reopened: 'Reopened',
  resolved: 'Resolved', closed: 'Closed', archived: 'Archived',
  low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical',
  scheduled: 'Scheduled', completed: 'Completed', cancelled: 'Cancelled',
  pending: 'Pending approval', approved: 'Approved', rejected: 'Rejected',
};

const pretty = (v) => STATUS_LABELS[v] ?? String(v ?? '').replace(/_/g, ' ');

const fmtDateTime = (v) => (v ? new Date(v).toLocaleString() : '—');
const fmtHours = (v) => (v == null ? '—' : `${Number(v).toFixed(1)} h`);

function Compliance({ pct }) {
  if (pct == null) return <span className="cell-muted">—</span>;
  const tone = pct >= 95 ? 'green' : pct >= 80 ? 'amber' : 'red';
  return <span className={`badge badge-${tone}`}>{pct}%</span>;
}

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
          <span className="dist-label">{pretty(k)}</span>
          <span className="dist-bar" aria-hidden="true">
            <span className="dist-fill" style={{ width: `${Math.round(((data[k] || 0) / max) * 100)}%` }} />
          </span>
          <span className="dist-value">{data[k] || 0}</span>
        </div>
      ))}
    </div>
  );
}

function DateRange({ from, to, onFrom, onTo }) {
  return (
    <div className="date-range">
      <label className="small muted" htmlFor="dash-from">From</label>
      <input id="dash-from" className="input" type="date" value={from} onChange={(e) => onFrom(e.target.value)} />
      <label className="small muted" htmlFor="dash-to">To</label>
      <input id="dash-to" className="input" type="date" value={to} onChange={(e) => onTo(e.target.value)} />
    </div>
  );
}

export function Dashboard() {
  const { isStaff } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [range, setRange] = useState({ from: '', to: '' });

  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (range.from) p.set('date_from', range.from);
    if (range.to) p.set('date_to', range.to);
    const s = p.toString();
    return s ? `?${s}` : '';
  }, [range]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    api.get(`/common/dashboard/${query}`)
      .then((r) => { if (!cancelled) setData(r.data); })
      .catch(() => { if (!cancelled) setError('Could not load dashboard metrics.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [query]);

  if (!isStaff) {
    return <div className="error-summary" role="alert">Only IT staff can view the management dashboard.</div>;
  }

  if (loading && !data) return <div className="panel panel-pad"><LoadingRows n={8} /></div>;
  if (error && !data) return <div className="error-summary" role="alert">{error}</div>;

  const e = data.employees;
  const a = data.assets;
  const t = data.tickets;
  const m = data.maintenance;
  const d = data.disposals;

  return (
    <div>
      <PageHeader
        title="Dashboard"
        sub={`Updated ${fmtDateTime(data.generated_at)}`}
        actions={
          <DateRange
            from={range.from} to={range.to}
            onFrom={(v) => setRange((r) => ({ ...r, from: v }))}
            onTo={(v) => setRange((r) => ({ ...r, to: v }))}
          />
        }
      />
      {error && <div className="error-summary" role="alert">{error}</div>}
      <div className="kpi-grid">
        <Kpi label="Employees" value={e.active} sub={`${e.total} total · ${e.departments} departments`} href="#/users" />
        <Kpi label="Assets" value={a.total} sub={`${a.under_maintenance} in repair · ${a.with_open_maintenance} with open maintenance`} href="#/assets" />
        <Kpi label="Open tickets" value={t.open} sub={`${t.total} total · ${t.overdue} overdue`} href="#/tickets" />
        <Kpi label="SLA compliance" value={t.sla.compliance_pct == null ? '—' : `${t.sla.compliance_pct}%`}
          sub={`${t.sla.resolved_on_time}/${t.sla.resolved_with_sla} resolved on time`} href="#/reports/sla" />
        <Kpi label="Open maintenance" value={m.open} sub={`${m.overdue} overdue`} href="#/maintenance" />
        <Kpi label="Pending disposals" value={d.pending_approval} sub={`${d.approved_not_completed} approved, awaiting completion`} href="#/disposals" />
      </div>
      <div className="split-grid">
        <Distribution title="Assets by status" data={a.by_status} order={ASSET_STATUS_ORDER} href="#/assets" />
        <Distribution title="Tickets by status" data={t.by_status} order={TICKET_STATUS_ORDER} href="#/tickets" />
        <Distribution title="Tickets by priority" data={t.by_priority} order={TICKET_PRIORITY_ORDER} href="#/tickets" />
      </div>
      <div className="split-grid split-2">
        <div className="panel panel-pad">
          <div className="panel-head">
            <h2>Upcoming maintenance</h2>
            <a className="link-small" href="#/maintenance">View all</a>
          </div>
          {m.upcoming.length ? (
            <ul className="mini-list">
              {m.upcoming.map((row) => (
                <li key={row.id} className="mini-item">
                  <a className="row-title" href={`#/assets/${row.asset_id}`}>{row.asset_tag}</a>
                  <span className="mini-title">{row.title}</span>
                  <span className="muted small">{fmtDateTime(row.scheduled_date)}</span>
                  <Badge kind="status" value={row.status} />
                </li>
              ))}
            </ul>
          ) : <p className="muted">No upcoming maintenance scheduled.</p>}
        </div>
        <div className="panel panel-pad">
          <div className="panel-head">
            <h2>Recent disposal requests</h2>
            <a className="link-small" href="#/disposals">View all</a>
          </div>
          {d.recent.length ? (
            <ul className="mini-list">
              {d.recent.map((row) => (
                <li key={row.id} className="mini-item">
                  <a className="row-title" href={`#/assets/${row.asset_id}`}>{row.asset_tag}</a>
                  <span className="mini-title">{pretty(row.approval_status)}</span>
                  <span className="muted small">{fmtDateTime(row.created_at)}</span>
                </li>
              ))}
            </ul>
          ) : <p className="muted">No disposal requests yet.</p>}
        </div>
      </div>
      <p className="page-footnote">
        Ticket metrics respect the date range; asset, employee, maintenance, and disposal counts are current totals.
        Average resolution time: {fmtHours(t.avg_resolution_hours)}.
      </p>
    </div>
  );
}

function compactCounts(data, order) {
  return order
    .filter((k) => (data?.[k] || 0) > 0)
    .map((k) => `${pretty(k)} ${data[k]}`)
    .join(' · ') || '—';
}

export function DepartmentReports() {
  const { isStaff } = useAuth();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [exportOpen, setExportOpen] = useState(false);
  const [range, setRange] = useState({ from: '', to: '' });
  const [generatedAt, setGeneratedAt] = useState(null);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (range.from) p.set('date_from', range.from);
    if (range.to) p.set('date_to', range.to);
    const s = p.toString();
    return s ? `?${s}` : '';
  }, [range]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    api.get(`/common/reports/departments/${query}`)
      .then((r) => {
        if (cancelled) return;
        setRows(r.data.results || []);
        setGeneratedAt(r.data.generated_at);
      })
      .catch(() => { if (!cancelled) setError('Could not load the department report.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [query]);

  if (!isStaff) {
    return <div className="error-summary" role="alert">Only IT staff can view department reports.</div>;
  }

  const totals = rows.reduce((acc, r) => ({
    employees: acc.employees + r.employees_total,
    assets: acc.assets + r.assets_total,
    tickets: acc.tickets + r.tickets_total,
    open: acc.open + r.tickets_open,
    overdue: acc.overdue + r.sla_overdue,
  }), { employees: 0, assets: 0, tickets: 0, open: 0, overdue: 0 });

  const columns = [
    { key: 'name', label: 'Department', render: (r) => (
      <span>
        <span className="row-title">{r.name}</span>
        {r.code ? <span className="muted small"> · {r.code}</span> : null}
      </span>
    ) },
    { key: 'employees', label: 'Employees', render: (r) => (
      <span>{r.employees_active}<span className="cell-muted"> / {r.employees_total}</span></span>
    ) },
    { key: 'assets', label: 'Assets', render: (r) => (
      <span>
        <strong>{r.assets_total}</strong>
        <br />
        <span className="muted small">{compactCounts(r.assets_by_status, ASSET_STATUS_ORDER)}</span>
      </span>
    ) },
    { key: 'tickets', label: 'Tickets', render: (r) => (
      <span>
        <strong>{r.tickets_total}</strong>
        <br />
        <span className="muted small">{r.tickets_open} open</span>
      </span>
    ) },
    { key: 'ticket_status', label: 'Ticket status', render: (r) => (
      <span className="muted small">{compactCounts(r.tickets_by_status, TICKET_STATUS_ORDER)}</span>
    ) },
    { key: 'ticket_priority', label: 'Priority', render: (r) => (
      <span className="muted small">{compactCounts(r.tickets_by_priority, TICKET_PRIORITY_ORDER)}</span>
    ) },
    { key: 'sla', label: 'SLA', render: (r) => (
      <span>
        <Compliance pct={r.sla_compliance_pct} />
        <br />
        <span className="muted small">{r.sla_overdue} overdue · {r.sla_breached} breached</span>
      </span>
    ) },
    { key: 'avg_resolution', label: 'Avg resolution', render: (r) => fmtHours(r.avg_resolution_hours) },
  ];

  return (
    <div>
      <PageHeader
        title="Department reports"
        sub={generatedAt ? `Generated ${fmtDateTime(generatedAt)}` : undefined}
        actions={<>
          <DateRange
            from={range.from} to={range.to}
            onFrom={(v) => setRange((r) => ({ ...r, from: v }))}
            onTo={(v) => setRange((r) => ({ ...r, to: v }))}
          />
          <button type="button" className="btn-secondary" onClick={() => setExportOpen(true)}>Export…</button>
        </>}
      />
      {exportOpen && (
        <ExportDialog
          dataset="department_report" open={exportOpen}
          filterParams={{ date_from: range.from, date_to: range.to }}
          onClose={() => setExportOpen(false)}
        />
      )}
      {error && <div className="error-summary" role="alert">{error}</div>}
      <div className="kpi-grid kpi-grid-compact">
        <Kpi label="Departments" value={rows.length} />
        <Kpi label="Employees" value={totals.employees} />
        <Kpi label="Assets" value={totals.assets} />
        <Kpi label="Tickets" value={totals.tickets} sub={`${totals.open} open`} />
        <Kpi label="SLA overdue" value={totals.overdue} />
      </div>
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={6} /></div>
          : (
            <DataTable
              columns={columns} rows={rows} keyOf={(r) => r.id ?? 'unassigned'}
              emptyTitle="No departments to report on."
              emptyHint="Add departments and assign employees, assets, and tickets."
            />
          )}
      </div>
      <p className="page-footnote">
        Counts reflect current employees, assets, and tickets; ticket workload, SLA, and resolution
        metrics respect the date range. Departments with no activity are included.
      </p>
    </div>
  );
}
