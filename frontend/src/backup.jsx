import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import {
  Badge, DataTable, Field, Modal, PageHeader, Pager,
} from './components';

export function Backup() {
  const { isStaff } = useAuth();
  if (!isStaff) {
    return (
      <div>
        <div className="page-head"><h1>Backup & DR</h1></div>
        <div className="empty-state">
          <div className="empty-title">Access restricted</div>
          <div className="small">Backup & DR is IT staff only.</div>
        </div>
      </div>
    );
  }

  const hash = location.hash.split('?')[0];
  if (hash === '#/backup/schedules') return <BackupSchedules />;
  if (hash === '#/backup/history') return <BackupHistory />;
  if (hash === '#/backup/restore') return <BackupRestore />;
  return <BackupOverview />;
}

/* ---------------- Overview ---------------- */

function BackupOverview() {
  const [schedules, setSchedules] = useState([]);
  const [lastJobs, setLastJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true); setError(''); // eslint-disable-line react/set-state-in-effect
    api.get('/api/backup/schedules/')
      .then((r) => setSchedules(r.data))
      .catch((_e) => setError('Could not load schedules.'))
      .finally(() => {
        api.get('/api/backup/jobs/', { params: { page_size: 30 } })
          .then((r) => setLastJobs(r.data.results))
          .catch((_e) => setError('Could not load jobs.'))
          .finally(() => setLoading(false));
      });
  }, []);

  const enabledCount = schedules.filter((s) => s.enabled).length;
  const failedCount = lastJobs.filter(
    (j) => j.status === 'failed' || j.status === 'backup_failed'
  ).length;

  return (
    <div>
      <PageHeader title="Backup & DR" sub="Backup schedules, job history and restore points."
        actions={(
          <div className="row-gap">
            <a href="#/backup/schedules" className="btn-ghost">Schedules &rarr;</a>
            <a href="#/backup/history" className="btn-ghost">History &rarr;</a>
            <a href="#/backup/restore" className="btn-ghost">Restore &rarr;</a>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-head"><h3>Summary</h3></div>
        <div className="panel-pad">
          <div className="field"><span className="form-label">Schedules</span><div className="small">{schedules.length} configured &bull; {enabledCount} enabled</div></div>
          <div className="field"><span className="form-label">Last 30 days</span><div className="small">{lastJobs.length} jobs &bull; {failedCount} failed</div></div>
          <div className="field"><span className="form-label">Status</span>
            <span className="small" style={{ color: failedCount ? '#c0392b' : '#27ae60' }}>
              {failedCount ? `Attention needed ({failedCount} failure{s})` : 'All backups healthy'}
            </span>
          </div>
        </div>
      </div>
      <div style={{ marginTop: 16 }}>
        <DataTable columns={[
          { key: 'name', label: 'Schedule', render: (r) => <span className="row-title">{r.name}</span> },
          { key: 'type', label: 'Type', render: (r) => r.type.charAt(0).toUpperCase() + r.type.slice(1) },
          { key: 'frequency', label: 'Frequency', render: (r) => r.frequency },
          { key: 'time', label: 'Time', render: (r) => r.time },
          { key: 'enabled', label: 'Enabled', render: (r) => <Badge kind={r.enabled ? 'status' : 'neutral'} value={r.enabled ? 'on' : 'off'} label={r.enabled ? 'Enabled' : 'Disabled'} /> },
          { key: 'next', label: 'Next run', render: (r) => <span className="cell-muted">{r.next_run}</span> },
          { key: 'status', label: 'Last status', render: (r) => <Badge kind="status" value={r.last_status || 'available'} label={r.last_status === 'paused' ? 'Paused' : r.last_status.charAt(0).toUpperCase() + r.last_status.slice(1)} /> },
        ]} rows={schedules} keyOf={(r) => `schedule-${r.id}`}
          emptyTitle="No backup schedules." emptyHint="Create a schedule under Schedules." />
      </div>
      <div style={{ marginTop: 24 }}>
        <DataTable columns={[
          { key: 'schedule', label: 'Schedule', render: (r) => <span className="row-title">{r.schedule}</span> },
          { key: 'type', label: 'Type', render: (r) => r.type },
          { key: 'status', label: 'Status', render: (r) => <Badge kind="status" value={r.status} label={r.status.charAt(0).toUpperCase() + r.status.slice(1)} /> },
          { key: 'started', label: 'Started', render: (r) => r.started ? new Date(r.started).toLocaleString() : '—' },
          { key: 'duration', label: 'Duration', render: (r) => r.duration },
          { key: 'size', label: 'Size', render: (r) => r.size },
          { key: 'target', label: 'Target', render: (r) => <span className="cell-muted">{r.target}</span> },
        ]} rows={lastJobs} keyOf={(r) => `job-${r.id}`} busy={loading}
          emptyTitle="No backup jobs." emptyHint="Run a scheduled backup to record its history here." />
      </div>
    </div>
  );
}

/* ---------------- Schedules ---------------- */

function BackupSchedules() {
  const [items, setItems] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get('/api/backup/schedules/')
      .then((r) => {
        setItems(r.data);
        setLoading(false);
      })
      .catch((_e) => {
        setError('Could not load schedules.');
        setLoading(false);
      });
  }, []);

  if (loading) return <div className="panel-pad"><div className="muted">Loading schedules…</div></div>;
  if (error) return <div className="field-error" role="alert">{error}</div>;

  return (
    <div>
      <PageHeader title="Backup schedules" sub="Create and manage automated backup schedules."
        actions={(
          <div className="row-gap">
            <a href="#/backup" className="btn-ghost">&larr; Back to overview</a>
          </div>
        )} />
      <DataTable columns={[
        { key: 'name', label: 'Schedule', render: (r) => <span className="row-title">{r.name}</span> },
        { key: 'type', label: 'Type', render: (r) => r.type.charAt(0).toUpperCase() + r.type.slice(1) },
        { key: 'frequency', label: 'Frequency', render: (r) => r.frequency },
        { key: 'time', label: 'Time', render: (r) => r.time },
        { key: 'retention', label: 'Retention (days)', render: (r) => r.retention_days },
        { key: 'targets', label: 'Targets', render: (r) => r.targets.join(', ') },
        { key: 'enabled', label: 'Enabled', render: (r) => <Badge kind={r.enabled ? 'status' : 'neutral'} value={r.enabled ? 'on' : 'off'} label={r.enabled ? 'Enabled' : 'Disabled'} /> },
        { key: 'last', label: 'Last run', render: (r) => (
          <span>{r.last_run} &bull; <span style={r.last_status === 'success' ? { color: '#27ae60' } : { color: '#c0392b' }}>{r.last_status.charAt(0).toUpperCase() + r.last_status.slice(1)}</span></span>
        ) },
      ]} rows={items} keyOf={(r) => `schedule-${r.id}`}
        emptyTitle="No backup schedules." emptyHint="Add a schedule to start automated backups." />
      {editing && (
        <Modal title={`Edit schedule: ${items.find((i) => i.id === editing)?.name}`} onClose={() => setEditing(null)} size="wide">
          <div>
            <Field label="Schedule name" required>
              <input defaultValue={items.find((i) => i.id === editing)?.name} />
            </Field>
            <Field label="Backup type">
              <select defaultValue={items.find((i) => i.id === editing)?.type}>
                <option value="config">Configuration</option>
                <option value="database">Database</option>
                <option value="files">File shares</option>
                <option value="media">Media / attachments</option>
              </select>
            </Field>
            <Field label="Frequency">
              <select defaultValue={items.find((i) => i.id === editing)?.frequency}>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </Field>
            <Field label="Time (24h)">
              <input type="time" defaultValue={items.find((i) => i.id === editing)?.time} />
            </Field>
            <Field label="Retention (days)">
              <input type="number" defaultValue={items.find((i) => i.id === editing)?.retention_days} min="1" />
            </Field>
            <Field label="Targets">
              <input defaultValue={items.find((i) => i.id === editing)?.targets.join(', ')} placeholder="comma-separated hosts" />
            </Field>
            <div className="row-end" style={{ marginTop: 12 }}>
              <button type="button" className="btn-ghost" onClick={() => setEditing(null)}>Cancel</button>
              <button type="button" className="btn-primary" onClick={() => setEditing(null)}>Save schedule</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

/* ---------------- History ---------------- */

function BackupHistory() {
  const [items, setItems] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get('/api/backup/jobs/', { params: { page_size: 50 } })
      .then((r) => {
        setItems(r.data.results);
        setLoading(false);
      })
      .catch((_e) => {
        setError('Could not load job history.');
        setLoading(false);
      });
  }, []);

  if (loading) return <div className="panel-pad"><div className="muted">Loading job history…</div></div>;
  if (error) return <div className="field-error" role="alert">{error}</div>;

  const statusMap = {
    success: 'backup_success', failed: 'backup_failed', running: 'backup_running', skipped: 'backup_skipped',
    cancelled: 'backup_cancelled', restoring: 'backup_restoring', expired: 'backup_expired',
  };

  return (
    <div>
      <PageHeader title="Backup job history" sub="Outcomes of recent backup runs."
        actions={(
          <div className="row-gap">
            <a href="#/backup" className="btn-ghost">&larr; Back to overview</a>
          </div>
        )} />
      <DataTable columns={[
        { key: 'schedule', label: 'Schedule', render: (r) => <span className="row-title">{r.schedule}</span> },
        { key: 'type', label: 'Type', render: (r) => r.type },
        { key: 'status', label: 'Status', render: (r) => <Badge kind={statusMap[r.status] || 'status'} value={r.status} /> },
        { key: 'started', label: 'Started', render: (r) => r.started ? new Date(r.started).toLocaleString() : '—' },
        { key: 'duration', label: 'Duration', render: (r) => r.duration },
        { key: 'size', label: 'Size', render: (r) => r.size },
        { key: 'target', label: 'Target', render: (r) => <span className="cell-muted">{r.target}</span> },
        { key: 'error', label: 'Error', render: (r) => <span className="cell-muted">{r.error || '—'}</span> },
      ]} rows={items} keyOf={(r) => `job-${r.id}`}
        emptyTitle="No backup job history." emptyHint="Run a scheduled backup to record its history here." />
      <Pager count={items?.length ?? 0} onPrev={() => setPage((p) => p - 1)} onNext={() => setPage((p) => p + 1)}
             hasPrev={page > 1} hasNext={page < 1} pageLabel="History" />
    </div>
  );
}

/* ---------------- Restore ---------------- */

function BackupRestore() {
  const [points, setPoints] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get('/api/backup/restore-points/')
      .then((r) => {
        setPoints(r.data);
        setLoading(false);
      })
      .catch((_e) => {
        setError('Could not load restore points.');
        setLoading(false);
      });
  }, []);

  if (loading) return <div className="panel-pad"><div className="muted">Loading restore points…</div></div>;
  if (error) return <div className="field-error" role="alert">{error}</div>;

  const statusMap = {
    available: 'status', restoring: 'restoring', expired: 'expired', corrupt: 'corrupt',
  };

  return (
    <div>
      <PageHeader title="Restore from backup" sub="Select a backup point to restore."
        actions={(
          <div className="row-gap">
            <a href="#/backup" className="btn-ghost">&larr; Back to overview</a>
          </div>
        )} />
      <DataTable
        columns={[
          { key: 'schedule', label: 'Source schedule', render: (r) => <span className="row-title">{r.schedule}</span> },
          { key: 'type', label: 'Type', render: (r) => r.type },
          { key: 'created', label: 'Created', render: (r) => r.created ? new Date(r.created).toLocaleString() : '—' },
          { key: 'size', label: 'Size', render: (r) => r.size },
          { key: 'target', label: 'Target', render: (r) => <span className="cell-muted">{r.target}</span> },
          { key: 'status', label: 'Status', render: (r) => <Badge kind={statusMap[r.status] || 'status'} value={r.status} /> },
          { key: 'action', label: 'Restore', render: (r) => (
            <button type="button" className="btn-ghost" disabled={false} onClick={() => alert(`Restore from point ${r.id} — connect real backend to perform restore.`)}>
              {restoring !== r.id ? 'Restore' : 'Restoring...'}
            </button>
          )},
        ]}
        rows={points}
        keyOf={(r) => `point-${r.id}`}
        emptyTitle="No restore points."
        emptyHint="Run a backup to create a restore point."
      />
    </div>
  );
}