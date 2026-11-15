import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import {
  Badge, DataTable, Field, Modal, PageHeader, Pager,
} from './components';

const SCHEDULE_TONE = {
  enabled: 'green', disabled: 'gray', paused: 'amber',
};
const JOB_STATUS = {
  success: 'green', failed: 'red', running: 'blue', skipped: 'gray',
};

/** Phase 27 — backup & disaster recovery (Staff only).
 *
 * Hash-based sub-views:
 *   #/backup               backup overview + schedules
 *   #/backup/schedules     backup schedule management
 *   #/backup/history       backup job history
 *   #/backup/restore       restore points
 */
export function Backup() {
  const { isStaff } = useAuth();
  if (!isStaff) {
    return (
      <div>
        <div className="page-head"><h1>Backup &amp; DR</h1></div>
        <div className="empty-state">
          <div className="empty-title">Access restricted</div>
          <div className="small">Backup &amp; DR is IT staff only.</div>
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
    setLoading(true); setError('');
    const mock = {
      schedules: [
        { id: 1, name: 'Daily configuration backup', type: 'config', frequency: 'daily', time: '02:00', enabled: true, next_run: '2026-11-16 02:00', last_status: 'success' },
        { id: 2, name: 'Weekly full database backup', type: 'database', frequency: 'weekly', time: '01:00', enabled: true, next_run: '2026-11-21 01:00', last_status: 'success' },
        { id: 3, name: 'Daily file share backup', type: 'files', frequency: 'daily', time: '03:00', enabled: false, next_run: '—', last_status: 'paused' },
      ],
      jobs: [
        { id: 101, schedule: 'Daily configuration backup', type: 'config', status: 'success', started: '2026-11-15 02:00', duration: '4m 12s', size: '12.4 MB', target: 'localhost' },
        { id: 100, schedule: 'Weekly full database backup', type: 'database', status: 'success', started: '2026-11-14 01:00', duration: '18m 30s', size: '1.84 GB', target: 'db-primary' },
        { id: 99, schedule: 'Daily file share backup', type: 'files', status: 'skipped', started: '2026-11-15 03:00', duration: '—', size: '—', target: 'fileserver-01' },
      ],
    };
    setSchedules(mock.schedules);
    setLastJobs(mock.jobs);
    setLoading(false);
  }, []);

  const enabledCount = schedules.filter((s) => s.enabled).length;
  const failedCount = lastJobs.filter((j) => j.status === 'failed').length;

  return (
    <div>
      <PageHeader title="Backup &amp; DR" sub="Backup schedules, job history and restore points."
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
          { key: 'status', label: 'Last status', render: (r) => <Badge kind="status" value={r.last_status} label={r.last_status === 'paused' ? 'Paused' : r.last_status.charAt(0).toUpperCase() + r.last_status.slice(1)} /> },
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

function failureSuffix(n) {
  return n === 1 ? '' : 's';
}

/* ---------------- Schedules ---------------- */

function BackupSchedules() {
  const [items, setItems] = useState([
    { id: 1, name: 'Daily configuration backup', type: 'config', frequency: 'daily', time: '02:00', enabled: true, retention: 30, targets: ['localhost'], last_run: '2026-11-15 02:00', last_status: 'success' },
    { id: 2, name: 'Weekly full database backup', type: 'database', frequency: 'weekly', time: '01:00', enabled: true, retention: 90, targets: ['db-primary'], last_run: '2026-11-14 01:00', last_status: 'success' },
    { id: 3, name: 'Daily file share backup', type: 'files', frequency: 'daily', time: '03:00', enabled: false, retention: 14, targets: ['fileserver-01'], last_run: '2026-11-14 03:00', last_status: 'paused' },
  ]);
  const [editing, setEditing] = useState(null);

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
        { key: 'retention', label: 'Retention (days)', render: (r) => r.retention },
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
              <input type="number" defaultValue={items.find((i) => i.id === editing)?.retention} min="1" />
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
  const [items, setItems] = useState([
    { id: 101, schedule: 'Daily configuration backup', type: 'config', status: 'success', started: '2026-11-15 02:00', finished: '2026-11-15 02:04', duration: '4m 12s', size: '12.4 MB', target: 'localhost', error: '—' },
    { id: 100, schedule: 'Weekly full database backup', type: 'database', status: 'success', started: '2026-11-14 01:00', finished: '2026-11-14 01:18', duration: '18m 30s', size: '1.84 GB', target: 'db-primary', error: '—' },
    { id: 99, schedule: 'Daily file share backup', type: 'files', status: 'skipped', started: '2026-11-15 03:00', finished: '—', duration: '—', size: '—', target: 'fileserver-01', error: 'Schedule disabled' },
    { id: 98, schedule: 'Weekly full database backup', type: 'database', status: 'failed', started: '2026-11-07 01:00', finished: '2026-11-07 01:05', duration: '5m 00s', size: '—', target: 'db-primary', error: 'Connection timeout' },
  ]);
  const [page, setPage] = useState(1);

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
        { key: 'status', label: 'Status', render: (r) => <Badge kind="status" value={r.status} label={r.status.charAt(0).toUpperCase() + r.status.slice(1)} /> },
        { key: 'started', label: 'Started', render: (r) => r.started ? new Date(r.started).toLocaleString() : '—' },
        { key: 'duration', label: 'Duration', render: (r) => r.duration },
        { key: 'size', label: 'Size', render: (r) => r.size },
        { key: 'target', label: 'Target', render: (r) => <span className="cell-muted">{r.target}</span> },
        { key: 'error', label: 'Error', render: (r) => <span className="cell-muted">{r.error}</span> },
      ]} rows={items} keyOf={(r) => `job-${r.id}`}
        emptyTitle="No backup job history." emptyHint="Run a scheduled backup to record its history here." />
      <Pager count={items.length} onPrev={() => setPage((p) => p - 1)} onNext={() => setPage((p) => p + 1)}
             hasPrev={page > 1} hasNext={page < 1} pageLabel="History" />
    </div>
  );
}

/* ---------------- Restore ---------------- */

function BackupRestore() {
  const [points, setPoints] = useState([
    { id: 1, schedule: 'Weekly full database backup', type: 'database', created: '2026-11-14 01:18', size: '1.84 GB', target: 'db-primary', status: 'available' },
    { id: 2, schedule: 'Daily configuration backup', type: 'config', created: '2026-11-15 02:04', size: '12.4 MB', target: 'localhost', status: 'available' },
    { id: 3, schedule: 'Daily file share backup', type: 'files', created: '2026-11-14 03:00', size: '442 MB', target: 'fileserver-01', status: 'available' },
  ]);
  const [restoring, setRestoring] = useState(null);

  const handleRestore = (id) => { setRestoring(id); setTimeout(() => setRestoring(null), 1200); };

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
          { key: 'status', label: 'Status', render: (r) => <Badge kind="status" value={r.status} label={r.status.charAt(0).toUpperCase() + r.status.slice(1)} /> },
          { key: 'action', label: 'Restore', render: (r) => (
            <button type="button" className="btn-ghost" disabled={restoring === r.id} onClick={() => handleRestore(r.id)}>
              {restoring === r.id ? 'Restoring...' : 'Restore'}
            </button>
          )},
        ]}
        rows={points}
        keyOf={(r) => `point-${r.id}`}
        emptyTitle="No restore points."
        emptyHint="Run a backup to create a restore point."
      />
      {restoring && (
        <div className="panel" style={{ marginTop: 16 }}>
          <div className="panel-head"><h3>Restore in progress</h3></div>
          <div className="panel-pad">
            <div className="field"><span className="form-label">Restoring backup point #{restoring}</span></div>
            <div className="small">This is a placeholder. Connect a real backup backend to perform restores.</div>
          </div>
        </div>
      )}
    </div>
  );
}
