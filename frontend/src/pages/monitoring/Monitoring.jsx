import { useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import { Badge, DataTable, Field, Modal, PageHeader } from '../../components';
import { fetchPage, parseApiError } from '../../api-utils';
import { canAccessMonitoring, canAdministerMonitoring } from '../../components/monitoring/access';
import { MonitoringOverview } from '../../features/monitoring/MonitoringOverview';
import { AlertList } from '../../features/monitoring/AlertList';
import { AlertDetail } from '../../features/monitoring/AlertDetail';
import { SourceManagement } from '../../features/monitoring/SourceManagement';
import { PolicyManagement } from '../../features/monitoring/PolicyManagement';

const STATE_TONE = {
  healthy: 'green', degraded: 'amber', unavailable: 'red',
  unknown: 'gray', 'not_configured': 'gray',
};
const STATE_LABEL = {
  healthy: 'Healthy', degraded: 'Degraded', unavailable: 'Unavailable',
  unknown: 'Unknown', 'not_configured': 'Not configured',
};
const SAFE_RETRY_TASKS = new Set([
  'common.tasks.process_inbound_mailbox',
  'common.tasks.process_inbound_email_task',
  'common.tasks.run_scheduled_reports',
  'common.tasks.evaluate_retention_policies',
  'common.tasks.execute_retention_policy',
]);
/** Phase 26 — operational monitoring dashboard (System Admin / IT staff).
 *
 * Hash-based sub-views:
 *   #/monitoring                health dashboard
 *   #/monitoring/tasks          background task history + safe retry
 *   #/monitoring/errors         application errors
 *   #/monitoring/alerts         common operational alerts + ack/resolve
 *   #/monitoring/alerts/list    monitoring alert list unavailable state
 *   #/monitoring/alerts/:id     monitoring alert detail + supported actions
 *   #/monitoring/incidents      operational incidents
 *   #/monitoring/performance    API performance summary
 *   #/monitoring/email-storage  email & storage health
 */
export function Monitoring() {
  const auth = useAuth();
  if (!canAccessMonitoring(auth)) {
    return (
      <div>
        <div className="page-head"><h1>Operational Monitoring</h1></div>
        <div className="empty-state">
          <div className="empty-title">Access restricted</div>
          <div className="small">Operational monitoring is IT staff only.</div>
        </div>
      </div>
    );
  }

  const hash = location.hash.split('?')[0];
  const alertDetail = hash.match(/^#\/monitoring\/alerts\/([^/]+)$/);
  if (alertDetail && alertDetail[1] !== 'list') return <AlertDetail alertId={decodeURIComponent(alertDetail[1])} />;
  if (hash === '#/monitoring/alerts') return <AlertMonitor />;
  if (hash === '#/monitoring/alerts/list') return <AlertList />;
  if (hash === '#/monitoring/tasks') return <TaskMonitor />;
  if (hash === '#/monitoring/errors') return <ErrorMonitor />;
  if (hash === '#/monitoring/incidents') return <IncidentMonitor />;
  if (hash === '#/monitoring/performance') return <PerfMonitor />;
  if (hash === '#/monitoring/email-storage') return <EmailStorageMonitor />;
  if (hash === '#/monitoring/notification-outbox') return <NotificationOutbox />;
  if (hash === '#/monitoring/health') return <HealthMonitor />;
  if (hash === '#/monitoring/overview') return <MonitoringOverview />;
  if (hash === '#/monitoring/sources') return <SourceManagement />;
  if (hash === '#/monitoring/policies') return <PolicyManagement />;
  return <HealthDashboard />;
}

/* ---------------- Health dashboard ---------------- */

function HealthDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const r = await api.get('/common/health/');
        if (!cancelled) setData(r.data);
      } catch (e) {
        if (!cancelled) setError(parseApiError(e).global || 'Health check failed.');
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) return (
    <>
      <div className="page-head"><h1>System Health</h1></div>
      <div className="panel panel-pad" role="status" aria-label="Loading">
        <span className="spinner" aria-hidden="true" /> Loading…
      </div>
    </>
  );

  const comps = data ? data.components : {};
  const overallLabel = STATE_LABEL[data?.overall ?? 'unknown'] ?? 'Unknown';
  const lastEvaluated = data?.components?.backend?.evaluated_at;

  return (
    <div>
      <PageHeader title="System Health" sub="Centralized operational health dashboard."
        actions={(
          <div className="row-gap">
            <button type="button" className="btn-secondary" onClick={() => window.location.reload()}>Refresh</button>
            <a href="#/monitoring/health" className="btn-primary">View all checks</a>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <div className="panel">
        <div className="panel-head"><h3>Overall status</h3></div>
        <div className="panel-pad">
          <div className="kpi-card" style={{ display: 'inline-block', minWidth: 200 }}>
            <div className="kpi-value" style={{ color: STATE_TONE[data?.overall ?? 'unknown'] ?? '#666' }}>
              {overallLabel}
            </div>
            <div className="kpi-label">System overall</div>
          </div>
          {data && (
            <div className="small muted">
              Last evaluated: {lastEvaluated ? new Date(lastEvaluated).toLocaleString() : '—'}
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h3>Component health</h3></div>
        <div className="panel-pad">
          <table className="grid">
            <thead>
              <tr><th>Component</th><th>Status</th><th>Diagnostic</th><th>Last evaluated</th></tr>
            </thead>
            <tbody>
              {Object.entries(comps).map(([key, c]) => (
                <tr key={key}>
                  <td>{key.replace(/_/g, ' ')}</td>
                  <td>
                    <Badge kind="status" value={c.state}
                           label={STATE_LABEL[c.state] ?? c.state} />
                  </td>
                  <td className="cell-muted small">{c.diagnostic || '—'}</td>
                  <td className="cell-muted small">
                    {c.evaluated_at ? new Date(c.evaluated_at).toLocaleString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h3>Quick links</h3></div>
        <div className="panel-pad" style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <a href="#/monitoring/tasks" className="btn-secondary">Background tasks</a>
          <a href="#/monitoring/errors" className="btn-secondary">Application errors</a>
          <a href="#/monitoring/alerts" className="btn-secondary">Alerts</a>
          <a href="#/monitoring/incidents" className="btn-secondary">Incidents</a>
          <a href="#/monitoring/performance" className="btn-secondary">API performance</a>
          <a href="#/monitoring/email-storage" className="btn-secondary">Email &amp; storage</a>
          <a href="#/monitoring/notification-outbox" className="btn-secondary">Notification outbox</a>
        </div>
      </div>
    </div>
  );
}

function NotificationOutbox() {
  const auth = useAuth();
  const isAdmin = canAdministerMonitoring(auth);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [eventType, setEventType] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const [inspectEvent, setInspectEvent] = useState(null);
  const [cancelEvent, setCancelEvent] = useState(null);
  const [cancelReason, setCancelReason] = useState('');
  const [actionBusy, setActionBusy] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError('');
      try {
        const params = { limit: 50 };
        if (status) params.status = status;
        if (eventType.trim()) params.event_type = eventType.trim();

        const response = await api.get('/common/notification-outbox/', { params });
        if (!cancelled) setData(response.data);
      } catch (e) {
        if (!cancelled) setError(parseApiError(e).global || 'Failed to load notification outbox.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [status, eventType, refreshKey]);

  const stats = data?.stats || {};
  const events = Array.isArray(data?.events) ? data.events : [];

  async function inspect(id) {
    setError('');
    setMessage('');
    try {
      const response = await api.get(`/common/notification-outbox/${id}/inspect/`);
      setInspectEvent(response.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Unable to inspect this event.');
    }
  }

  async function retry(id) {
    if (actionBusy) return;
    setActionBusy(true);
    setError('');
    setMessage('');
    try {
      await api.post(`/common/notification-outbox/${id}/retry/`);
      setMessage('Retry queued successfully.');
      setRefreshKey((value) => value + 1);
    } catch (e) {
      setError(parseApiError(e).global || 'Unable to retry this event.');
    } finally {
      setActionBusy(false);
    }
  }

  async function cancel() {
    if (!cancelEvent || !cancelReason.trim() || actionBusy) return;
    setActionBusy(true);
    setError('');
    setMessage('');
    try {
      await api.post(`/common/notification-outbox/${cancelEvent.id}/cancel/`, {
        reason: cancelReason.trim(),
      });
      setMessage('Notification event cancelled.');
      setCancelEvent(null);
      setCancelReason('');
      setRefreshKey((value) => value + 1);
    } catch (e) {
      setError(parseApiError(e).global || 'Unable to cancel this event.');
    } finally {
      setActionBusy(false);
    }
  }

  const statItems = [
    ['Total', stats.total],
    ['Pending', stats.pending],
    ['Retry', stats.retry],
    ['Processing', stats.processing],
    ['Delivered', stats.delivered],
    ['Failed', stats.failed],
    ['Cancelled', stats.cancelled],
    ['Expired claims', stats.expired_claims],
    ['Delivered · 24h', stats.delivered_last_24h],
    ['Failed · 24h', stats.failed_last_24h],
    ['Oldest pending age', stats.oldest_pending_age_seconds == null
      ? '—'
      : `${Math.floor(stats.oldest_pending_age_seconds / 60)} min`],
  ];

  return (
    <div>
      <PageHeader
        title="Notification Outbox"
        sub="Monitor queued notification delivery and review failed or delayed events."
        actions={(
          <div className="row-gap">
            <button type="button" className="btn-secondary"
              onClick={() => setRefreshKey((value) => value + 1)}>
              Refresh
            </button>
            <a href="#/monitoring" className="btn-ghost">&larr; Monitoring</a>
          </div>
        )}
      />

      {error ? <div className="field-error" role="alert">{error}</div> : null}
      {message ? <div className="small" role="status">{message}</div> : null}

      <div className="panel">
        <div className="panel-head"><h3>Delivery statistics</h3></div>
        <div className="panel-pad">
          {loading && !data ? (
            <div role="status"><span className="spinner" aria-hidden="true" /> Loading statistics…</div>
          ) : (
            <div className="grid" style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))',
              gap: 12,
            }}>
              {statItems.map(([label, value]) => (
                <div className="kpi-card" key={label}>
                  <div className="kpi-value">{value ?? '—'}</div>
                  <div className="kpi-label">{label}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head"><h3>Notification events</h3></div>
        <div className="panel-pad">
          <div className="row-gap" style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
            <label className="field">
              <span className="form-label">Status</span>
              <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">All statuses</option>
                {['pending', 'retry', 'processing', 'delivered', 'failed', 'cancelled'].map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="form-label">Event type</span>
              <input className="input" value={eventType}
                onChange={(e) => setEventType(e.target.value)}
                placeholder="Filter by event type" />
            </label>
          </div>

          {loading ? (
            <div role="status"><span className="spinner" aria-hidden="true" /> Loading events…</div>
          ) : events.length === 0 ? (
            <div className="empty-state">
              <div className="empty-title">No notification events found</div>
              <div className="small">Try changing the filters or check again after notifications are queued.</div>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="grid">
                <thead>
                  <tr>
                    <th>Created</th>
                    <th>Event type</th>
                    <th>Channel</th>
                    <th>Recipient</th>
                    <th>Status</th>
                    <th>Attempts</th>
                    <th>Last error</th>
                    {isAdmin ? <th>Actions</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr key={event.id}>
                      <td className="small">{event.created_at ? new Date(event.created_at).toLocaleString() : '—'}</td>
                      <td>{event.event_type || '—'}</td>
                      <td>{event.channel || '—'}</td>
                      <td>{event.recipient_email || event.recipient || '—'}</td>
                      <td><Badge kind="status" value={event.status} label={event.status} /></td>
                      <td>{event.attempts ?? 0} / {event.max_attempts ?? '—'}</td>
                      <td className="small cell-muted">{event.last_error || '—'}</td>
                      {isAdmin ? (
                        <td>
                          <div className="cell-actions">
                            <button type="button" className="btn-ghost"
                              onClick={() => inspect(event.id)}>Inspect</button>
                            {['failed', 'cancelled'].includes(event.status) ? (
                              <button type="button" className="btn-secondary"
                                disabled={actionBusy} onClick={() => retry(event.id)}>Retry</button>
                            ) : null}
                            {['pending', 'retry', 'processing'].includes(event.status) ? (
                              <button type="button" className="btn-ghost"
                                disabled={actionBusy}
                                onClick={() => { setCancelEvent(event); setCancelReason(''); }}>
                                Cancel
                              </button>
                            ) : null}
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="small muted" style={{ marginTop: 12 }}>
            Showing up to 50 events. Notification payloads are not included in this list.
          </div>
        </div>
      </div>

      {inspectEvent ? (
        <Modal title="Notification event inspection" onClose={() => setInspectEvent(null)} size="large">
          <div className="panel-pad">
            <dl className="grid" style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: 12,
            }}>
              {['id', 'event_type', 'channel', 'recipient_email', 'status', 'attempts',
                'max_attempts', 'next_attempt_at', 'last_attempt_at', 'delivered_at',
                'claimed_by', 'last_error', 'cancel_reason'].map((key) => (
                <div key={key}>
                  <dt className="form-label">{key.replace(/_/g, ' ')}</dt>
                  <dd className="small" style={{ margin: 0, overflowWrap: 'anywhere' }}>
                    {inspectEvent[key] == null || inspectEvent[key] === '' ? '—' : String(inspectEvent[key])}
                  </dd>
                </div>
              ))}
            </dl>
            <h4>Payload</h4>
            <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
              {JSON.stringify(inspectEvent.payload ?? {}, null, 2)}
            </pre>
          </div>
        </Modal>
      ) : null}

      {cancelEvent ? (
        <Modal title="Cancel notification event" onClose={() => {
          if (!actionBusy) {
            setCancelEvent(null);
            setCancelReason('');
          }
        }}>
          <div className="panel-pad">
            <p>Cancel this notification event? This action cannot be used to stop an event that has already been delivered.</p>
            <label className="field">
              <span className="form-label">Reason</span>
              <textarea className="input" rows={3} maxLength={255}
                value={cancelReason}
                onChange={(e) => setCancelReason(e.target.value)}
                placeholder="Explain why this notification is being cancelled." />
            </label>
            <div className="row-end" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button type="button" className="btn-secondary" disabled={actionBusy}
                onClick={() => { setCancelEvent(null); setCancelReason(''); }}>
                Keep event
              </button>
              <button type="button" className="btn-primary"
                disabled={actionBusy || !cancelReason.trim()}
                onClick={cancel}>
                {actionBusy ? 'Cancelling…' : 'Confirm cancellation'}
              </button>
            </div>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
function HealthMonitor() {
  const [data, setData] = useState(null);
  const [, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const r = await api.get('/common/health/results/');
        if (!cancelled) setData(r.data);
      } catch (e) {
        if (!cancelled) setError(parseApiError(e).global || 'Failed to load health history.');
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, []);

  const rows = data || [];
  return (
    <div>
      <PageHeader title="Component health history" sub="Recent health check results."
        actions={(
          <div className="row-gap">
            <button type="button" className="btn-secondary" onClick={() => window.location.reload()}>Refresh</button>
            <a href="#/monitoring" className="btn-ghost">&larr; Back to dashboard</a>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <DataTable columns={[
        { key: 'component', label: 'Component', render: (r) => r.component.replace(/_/g, ' ') },
        { key: 'state', label: 'Status', render: (r) => <Badge kind="status" value={r.state} label={STATE_LABEL[r.state] ?? r.state} /> },
        { key: 'evaluated_at', label: 'Evaluated', render: (r) => r.evaluated_at ? new Date(r.evaluated_at).toLocaleString() : '—' },
        { key: 'last_success', label: 'Last success', render: (r) => r.last_successful_at ? new Date(r.last_successful_at).toLocaleString() : <span className="cell-muted">—</span> },
        { key: 'last_failure', label: 'Last failure', render: (r) => r.last_failure_at ? new Date(r.last_failure_at).toLocaleString() : <span className="cell-muted">—</span> },
        { key: 'diagnostic', label: 'Diagnostic', render: (r) => <span className="cell-muted small">{r.diagnostic || '—'}</span> },
      ]} rows={rows} keyOf={(r)=>String(r.id)+r.component+(r.evaluated_at||'')}
        emptyTitle="No health check history." emptyHint="Run a health check to populate history." />
    </div>
  );
}

/* ---------------- Background task monitor ---------------- */

function TaskMonitor() {
  const [items, setItems] = useState([]);
  const [, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [f, setF] = useState({ task_name: '', status: '' });
  const [retryBusy, setRetryBusy] = useState(null);

  const load = async () => {
    setLoading(true); setError('');
    try {
      const p = new URLSearchParams();
      if (f.task_name) p.set('task_name', f.task_name);
      if (f.status) p.set('status', f.status);
      p.set('limit', '100');
      const r = await api.get(`/common/tasks/?${p.toString()}`);
      setItems(r.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load tasks.');
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [f.task_name, f.status]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect

  const retry = async (taskName) => {
    setRetryBusy(taskName);
    try {
      const r = await api.post('/common/tasks/retry_task/', { task_name: taskName });
      if (r.data.retried) {
        setError('');
        load();
      } else {
        setError(r.data.detail || 'Retry failed.');
      }
    } catch (e) {
      setError(parseApiError(e).global || 'Retry failed.');
    } finally { setRetryBusy(null); }
  };

  return (
    <div>
      <PageHeader title="Background tasks" sub="Celery task execution history and authorized retry."
        actions={(
          <div className="row-gap">
            <button type="button" className="btn-secondary" onClick={load}>Refresh</button>
            <a href="#/monitoring" className="btn-ghost">&larr; Back to dashboard</a>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-pad" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'end' }}>
          <Field label="Task"><input className="input input-auto" value={f.task_name} onChange={(e)=>setF({...f, task_name:e.target.value})} placeholder="e.g. common.tasks.run_scheduled_reports" /></Field>
          <Field label="Status"><select className="input" value={f.status} onChange={(e)=>setF({...f, status:e.target.value})}>
            <option value="">All</option>
            <option value="running">Running</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
            <option value="skipped">Skipped</option>
          </select></Field>
          <button type="button" className="btn-primary" onClick={load}>Filter</button>
        </div>
      </div>
      <DataTable columns={[
        { key: 'task_name', label: 'Task', render: (r) => r.task_name },
        { key: 'status', label: 'Status', render: (r) => <Badge kind="status" value={r.status} label={r.status} /> },
        { key: 'started_at', label: 'Started', render: (r) => r.started_at ? new Date(r.started_at).toLocaleString() : '—' },
        { key: 'finished_at', label: 'Finished', render: (r) => r.finished_at ? new Date(r.finished_at).toLocaleString() : <span className="cell-muted">—</span> },
        { key: 'success', label: 'Success', render: (r) => r.success ? <span className="badge badge-green">Yes</span> : <span className="badge badge-red">No</span> },
        { key: 'error', label: 'Error', render: (r) => <span className="cell-muted small">{r.error_summary || '—'}</span> },
        { key: 'actions', label: 'Actions', thClass: 'cell-actions', render: (r) => (
          <div className="cell-actions">
            {r.status === 'failed' && SAFE_RETRY_TASKS.has(r.task_name) && (
              <button type="button" className="btn-small btn-primary"
                onClick={() => retry(r.task_name)}
                disabled={retryBusy === r.task_name}>
                {retryBusy === r.task_name ? '…' : 'Retry'}
              </button>
            )}
            {r.status === 'failed' && !SAFE_RETRY_TASKS.has(r.task_name) && (
              <span className="cell-muted small">Retry not available for this task</span>
            )}
          </div>
        )},
      ]} rows={items} keyOf={(r)=>String(r.id)}
        emptyTitle="No background tasks." emptyHint="Task runs appear here after Celery executes them." />
    </div>
  );
}

/* ---------------- Application errors ---------------- */

function ErrorMonitor() {
  const [items, setItems] = useState([]);
  const [, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [f, setF] = useState({ component: '', resolved: '' });

  const load = async () => {
    setLoading(true); setError('');
    try {
      const p = new URLSearchParams();
      if (f.component) p.set('component', f.component);
      if (f.resolved) p.set('resolved', f.resolved);
      const r = await fetchPage(`/common/errors/?${p.toString()}`);
      setItems(r.items);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load errors.');
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [f.component, f.resolved]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect

  const resolve = async (id) => {
    try {
      await api.post(`/common/errors/${id}/resolve/`);
      load();
    } catch (e) {
      setError(parseApiError(e).global || 'Resolve failed.');
    }
  };

  return (
    <div>
      <PageHeader title="Application errors" sub="Sanitized, deduplicated operational errors."
        actions={(
          <div className="row-gap">
            <button type="button" className="btn-secondary" onClick={load}>Refresh</button>
            <a href="#/monitoring" className="btn-ghost">&larr; Back to dashboard</a>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-pad" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'end' }}>
          <Field label="Component"><select className="input" value={f.component} onChange={(e)=>setF({...f, component:e.target.value})}>
            <option value="">All</option>
            <option value="api">API</option>
            <option value="auth">Authentication</option>
            <option value="database">Database</option>
            <option value="background_task">Background task</option>
            <option value="email">Email</option>
            <option value="storage">Storage</option>
            <option value="other">Other</option>
          </select></Field>
          <Field label="Resolved"><select className="input" value={f.resolved} onChange={(e)=>setF({...f, resolved:e.target.value})}>
            <option value="">All</option>
            <option value="true">Resolved</option>
            <option value="false">Unresolved</option>
          </select></Field>
          <button type="button" className="btn-primary" onClick={load}>Filter</button>
        </div>
      </div>
      <DataTable columns={[
        { key: 'title', label: 'Title', render: (r) => <span className="row-title">{r.title}</span> },
        { key: 'component', label: 'Component', render: (r) => r.component },
        { key: 'severity', label: 'Severity', render: (r) => <Badge kind="status" value={r.severity} label={r.severity} /> },
        { key: 'count', label: 'Occurrences', render: (r) => r.occurrence_count },
        { key: 'last', label: 'Last occurrence', render: (r) => r.last_occurred ? new Date(r.last_occurred).toLocaleString() : '—' },
        { key: 'resolved', label: 'Resolved', render: (r) => r.resolved ? <span className="badge badge-green">Yes</span> : <span className="badge badge-amber">No</span> },
        { key: 'actions', label: 'Actions', thClass: 'cell-actions', render: (r) => (
          <div className="cell-actions">
            {!r.resolved && (
              <button type="button" className="btn-small btn-primary" onClick={() => resolve(r.id)}>Resolve</button>
            )}
          </div>
        )},
      ]} rows={items} keyOf={(r)=>String(r.id)}
        emptyTitle="No application errors." emptyHint="Errors appear here when record_error() is called or failures occur." />
    </div>
  );
}

/* ---------------- Alerts ---------------- */

function AlertMonitor() {
  const [items, setItems] = useState([]);
  const [, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [f, setF] = useState({ component: '', severity: '', status: '' });
  const [busy, setBusy] = useState({});

  const load = async () => {
    setLoading(true); setError('');
    try {
      const p = new URLSearchParams();
      if (f.component) p.set('component', f.component);
      if (f.severity) p.set('severity', f.severity);
      if (f.status) p.set('status', f.status);
      const r = await fetchPage(`/common/alerts/?${p.toString()}`);
      setItems(r.items);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load alerts.');
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [f.component, f.severity, f.status]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect

  const act = async (id, action) => {
    setBusy({ ...busy, [id]: action });
    try {
      await api.post(`/common/alerts/${id}/${action}/`);
      load();
    } catch (e) {
      setError(parseApiError(e).global || `${action} failed.`);
    } finally { setBusy({ ...busy, [id]: null }); }
  };

  return (
    <div>
      <PageHeader title="Operational alerts" sub="Deduplicated alerts with acknowledgement and resolution."
        actions={(
          <div className="row-gap">
            <button type="button" className="btn-secondary" onClick={load}>Refresh</button>
            <a href="#/monitoring" className="btn-ghost">&larr; Back to dashboard</a>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-pad" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'end' }}>
          <Field label="Component"><select className="input" value={f.component} onChange={(e)=>setF({...f, component:e.target.value})}>
            <option value="">All</option>
            <option value="database">Database</option>
            <option value="redis">Redis</option>
            <option value="celery_worker">Celery worker</option>
            <option value="celery_beat">Celery beat</option>
            <option value="background_tasks">Background tasks</option>
            <option value="email">Email</option>
            <option value="storage">Storage</option>
            <option value="application_errors">Application errors</option>
            <option value="other">Other</option>
          </select></Field>
          <Field label="Severity"><select className="input" value={f.severity} onChange={(e)=>setF({...f, severity:e.target.value})}>
            <option value="">All</option>
            <option value="informational">Informational</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select></Field>
          <Field label="Status"><select className="input" value={f.status} onChange={(e)=>setF({...f, status:e.target.value})}>
            <option value="">All</option>
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
            <option value="closed">Closed</option>
          </select></Field>
          <button type="button" className="btn-primary" onClick={load}>Filter</button>
        </div>
      </div>
      <DataTable columns={[
        { key: 'title', label: 'Title', render: (r) => <span className="row-title">{r.title}</span> },
        { key: 'severity', label: 'Severity', render: (r) => <Badge kind="status" value={r.severity} label={r.severity} /> },
        { key: 'status', label: 'Status', render: (r) => <Badge kind="status" value={r.status} label={r.status} /> },
        { key: 'count', label: 'Occurrences', render: (r) => r.occurrence_count },
        { key: 'last', label: 'Last', render: (r) => r.last_occurred ? new Date(r.last_occurred).toLocaleString() : '—' },
        { key: 'actions', label: 'Actions', thClass: 'cell-actions', render: (r) => (
          <div className="cell-actions">
            {!r.acknowledged && (
              <button type="button" className="btn-small" onClick={() => act(r.id, 'acknowledge')} disabled={busy[r.id] === 'acknowledge'}>
                {busy[r.id] === 'acknowledge' ? '…' : 'Acknowledge'}
              </button>
            )}
            {!r.resolved && (
              <button type="button" className="btn-small btn-primary" onClick={() => act(r.id, 'resolve')} disabled={busy[r.id] === 'resolve'}>
                {busy[r.id] === 'resolve' ? '…' : 'Resolve'}
              </button>
            )}
          </div>
        )},
      ]} rows={items} keyOf={(r)=>String(r.id)}
        emptyTitle="No alerts." emptyHint="Alerts are raised by scheduled monitoring checks or created manually." />
    </div>
  );
}

/* ---------------- Incidents ---------------- */

function IncidentMonitor() {
  const auth = useAuth();
  const canCreateIncident = canAdministerMonitoring(auth);
  const [items, setItems] = useState([]);
  const [, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [openForm, setOpenForm] = useState(false);
  const [form, setForm] = useState({ title: '', description: '', severity: 'warning', affected_component: '', assigned_to: '', internal_notes: '' });
  const [formBusy, setFormBusy] = useState(false);

  const load = async () => {
    setLoading(true); setError('');
    try {
      const r = await fetchPage('/common/incidents/');
      setItems(r.items);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load incidents.');
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react/set-state-in-effect

  const save = async (ev) => {
    ev.preventDefault();
    if (!canCreateIncident) {
      setError('Incident creation requires System Admin permission.');
      return;
    }
    setFormBusy(true); setError('');
    try {
      await api.post('/common/incidents/', {
        title: form.title, description: form.description, severity: form.severity,
        affected_component: form.affected_component,
        assigned_to: form.assigned_to || null,
        internal_notes: form.internal_notes,
      });
      setOpenForm(false);
      setForm({ title: '', description: '', severity: 'warning', affected_component: '', assigned_to: '', internal_notes: '' });
      load();
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to create incident.');
    } finally { setFormBusy(false); }
  };

  return (
    <div>
      <PageHeader title="Operational incidents" sub="System-level incidents (distinct from support tickets)."
        actions={(
          <div className="row-gap">
            <button type="button" className="btn-secondary" onClick={load}>Refresh</button>
            {canCreateIncident && (
              <button type="button" className="btn-primary" onClick={() => setOpenForm(true)}>+ New incident</button>
            )}
            <a href="#/monitoring" className="btn-ghost">&larr; Back to dashboard</a>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <DataTable columns={[
        { key: 'title', label: 'Title', render: (r) => <span className="row-title">{r.title}</span> },
        { key: 'severity', label: 'Severity', render: (r) => <Badge kind="status" value={r.severity} label={r.severity} /> },
        { key: 'status', label: 'Status', render: (r) => <Badge kind="status" value={r.status} label={r.status} /> },
        { key: 'component', label: 'Component', render: (r) => r.affected_component || '—' },
        { key: 'assignee', label: 'Assigned to', render: (r) => r.assigned_to_email || '—' },
        { key: 'created', label: 'Created', render: (r) => r.created_at ? new Date(r.created_at).toLocaleString() : '—' },
      ]} rows={items} keyOf={(r)=>String(r.id)}
        emptyTitle="No incidents." emptyHint="Incidents track system-level operational issues." />
      {openForm && (
        <Modal title="New operational incident" onClose={() => setOpenForm(false)} size="lg">
          <form onSubmit={save} noValidate>
            <Field label="Title" required>
              <input className="input input-auto" value={form.title} onChange={(e)=>setForm({...form, title:e.target.value})} disabled={formBusy} />
            </Field>
            <Field label="Description" required>
              <textarea className="input input-auto" value={form.description} onChange={(e)=>setForm({...form, description:e.target.value})} rows={3} disabled={formBusy} />
            </Field>
            <Field label="Severity">
              <select className="input" value={form.severity} onChange={(e)=>setForm({...form, severity:e.target.value})} disabled={formBusy}>
                <option value="informational">Informational</option>
                <option value="warning">Warning</option>
                <option value="critical">Critical</option>
              </select>
            </Field>
            <Field label="Affected component"><input className="input input-auto" value={form.affected_component} onChange={(e)=>setForm({...form, affected_component:e.target.value})} placeholder="e.g. database" disabled={formBusy} /></Field>
            <Field label="Assignee (user ID)"><input className="input input-auto" type="number" value={form.assigned_to} onChange={(e)=>setForm({...form, assigned_to:e.target.value})} disabled={formBusy} /></Field>
            <Field label="Internal notes"><textarea className="input input-auto" value={form.internal_notes} onChange={(e)=>setForm({...form, internal_notes:e.target.value})} rows={2} disabled={formBusy} /></Field>
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setOpenForm(false)} disabled={formBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={formBusy}>{formBusy ? 'Creating…' : 'Create'}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

/* ---------------- API performance ---------------- */

function PerfMonitor() {
  const [data, setData] = useState({ endpoints: [] });
  const [, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [minutes, setMinutes] = useState(60);

  const load = async () => {
    setLoading(true); setError('');
    try {
      const r = await api.get(`/common/api-performance/?minutes=${minutes}`);
      setData(r.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load performance metrics.');
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [minutes]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect

  return (
    <div>
      <PageHeader title="API performance" sub="Aggregated request counts, response times and error rates (no per-request DB writes)."
        actions={(
          <div className="row-gap">
            <Field label="Window (min)">
              <select className="input input-auto" value={minutes} onChange={(e)=>setMinutes(parseInt(e.target.value, 10)||60)}>
                <option value="15">15</option>
                <option value="60">60</option>
                <option value="240">240</option>
                <option value="1440">1440</option>
              </select>
            </Field>
            <button type="button" className="btn-secondary" onClick={load}>Refresh</button>
            <a href="#/monitoring" className="btn-ghost">&larr; Back to dashboard</a>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <DataTable columns={[
        { key: 'endpoint', label: 'Endpoint', render: (r) => <span className="row-title">{r.endpoint}</span> },
        { key: 'request_count', label: 'Requests', render: (r) => r.request_count },
        { key: 'error_count', label: 'Errors', render: (r) => r.error_count },
        { key: 'error_rate', label: 'Error rate', render: (r) => `${r.error_rate}%` },
        { key: 'avg_response_ms', label: 'Avg ms', render: (r) => r.avg_response_ms != null ? r.avg_response_ms : '—' },
        { key: 'max_response_ms', label: 'Max ms', render: (r) => r.max_response_ms != null ? r.max_response_ms : '—' },
        { key: 'slow', label: 'Slow (>1s)', render: (r) => r.slow_request_count },
      ]} rows={data.endpoints} keyOf={(r)=>r.endpoint}
        emptyTitle="No API metrics." emptyHint="Metrics accumulate as requests are served." />
    </div>
  );
}

/* ---------------- Email & storage ---------------- */

function EmailStorageMonitor() {
  const [data, setData] = useState({ components: {} });
  const [, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const r = await api.get('/common/email-storage/');
        if (!cancelled) setData(r.data);
      } catch (e) {
        if (!cancelled) setError(parseApiError(e).global || 'Failed to load email/storage health.');
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, []);

  const comps = data ? data.components : {};
  return (
    <div>
      <PageHeader title="Email &amp; storage health" sub="Email backend and file storage availability."
        actions={(
          <div className="row-gap">
            <button type="button" className="btn-secondary" onClick={() => window.location.reload()}>Refresh</button>
            <a href="#/monitoring" className="btn-ghost">&larr; Back to dashboard</a>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <table className="grid">
        <thead>
          <tr><th>Component</th><th>Status</th><th>Diagnostic</th><th>Checked</th></tr>
        </thead>
        <tbody>
          {['email', 'storage'].map((key) => {
            const c = comps[key];
            if (!c) return null;
            return (
              <tr key={key}>
                <td>{key === 'email' ? 'Email' : 'Storage'}</td>
                <td><Badge kind="status" value={c.state} label={STATE_LABEL[c.state] ?? c.state} /></td>
                <td className="cell-muted small">{c.diagnostic || '—'}</td>
                <td className="cell-muted small">{c.evaluated_at ? new Date(c.evaluated_at).toLocaleString() : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {comps.storage && comps.storage.details && comps.storage.details.storage_total_bytes != null && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="panel-head"><h3>Storage usage</h3></div>
          <div className="panel-pad">
            <div className="field"><span className="form-label">Total</span><div className="small">{formatBytes(comps.storage.details.storage_total_bytes)}</div></div>
            <div className="field"><span className="form-label">Used</span><div className="small">{formatBytes(comps.storage.details.storage_used_bytes)}</div></div>
            <div className="field"><span className="form-label">Free</span><div className="small">{formatBytes(comps.storage.details.storage_free_bytes)}</div></div>
          </div>
        </div>
      )}
    </div>
  );
}

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '—';
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let b = bytes;
  while (b >= 1024 && i < sizes.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(2)} ${sizes[i]}`;
}

