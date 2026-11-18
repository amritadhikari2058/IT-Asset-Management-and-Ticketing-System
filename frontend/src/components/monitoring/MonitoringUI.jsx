import { Badge } from '../../components';

export const SEVERITY_TONE = {
  info: 'blue',
  warning: 'amber',
  minor: 'blue',
  major: 'amber',
  critical: 'red',
};

export const SEVERITY_LABELS = {
  info: 'Info',
  warning: 'Warning',
  minor: 'Minor',
  major: 'Major',
  critical: 'Critical',
};

export const STATUS_TONE = {
  new: 'blue',
  open: 'blue',
  acknowledged: 'amber',
  suppressed: 'gray',
  recovered: 'green',
  resolved: 'green',
  closed: 'gray',
  flapping: 'purple',
};

export const STATUS_LABELS = {
  new: 'New',
  open: 'Open',
  acknowledged: 'Acknowledged',
  suppressed: 'Suppressed',
  recovered: 'Recovered',
  resolved: 'Resolved',
  closed: 'Closed',
  flapping: 'Flapping',
};

export const SOURCE_STATUS_TONE = {
  active: 'green',
  disabled: 'gray',
  degraded: 'amber',
  error: 'red',
  retired: 'gray',
};

export const SOURCE_STATUS_LABELS = {
  active: 'Active',
  disabled: 'Disabled',
  degraded: 'Degraded',
  error: 'Error',
  retired: 'Retired',
};

export const SOURCE_HEALTH_TONE = {
  healthy: 'green',
  degraded: 'amber',
  unhealthy: 'red',
  unknown: 'gray',
};

export const SOURCE_HEALTH_LABELS = {
  healthy: 'Healthy',
  degraded: 'Degraded',
  unhealthy: 'Unhealthy',
  unknown: 'Unknown',
};

/** Severity chip with text label. */
export function SeverityBadge({ value, label }) {
  const text = label ?? SEVERITY_LABELS[value] ?? String(value ?? '-').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  return <Badge kind="status" value={value} label={text} />;
}

/** Status chip with text label. */
export function StatusBadge({ value, label }) {
  const text = label ?? STATUS_LABELS[value] ?? String(value ?? '-').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  return <Badge kind="status" value={value} label={text} />;
}

/** Source status chip. */
export function SourceStatusBadge({ value, label }) {
  const text = label ?? SOURCE_STATUS_LABELS[value] ?? String(value ?? '-').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  return <Badge kind="status" value={value} label={text} />;
}

/** Source health chip. */
export function SourceHealthBadge({ value, label }) {
  const text = label ?? SOURCE_HEALTH_LABELS[value] ?? String(value ?? '-').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  return <Badge kind="status" value={value} label={text} />;
}

/** Safe date formatter — never renders raw payloads or internals. */
export function formatDate(value) {
  if (!value) return '—';
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleString();
  } catch {
    return '—';
  }
}

export function formatRelative(value) {
  if (!value) return '—';
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '—';
    const now = new Date();
    const diffSec = Math.floor((now - d) / 1000);
    if (diffSec < 60) return 'Just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return d.toLocaleDateString();
  } catch {
    return '—';
  }
}

/** KPI stat card. */
export function KpiCard({ title, value, tone = 'gray', sub, loading }) {
  const colorMap = {
    green: 'var(--success)',
    red: 'var(--danger)',
    amber: 'var(--warning)',
    blue: 'var(--info)',
    gray: 'var(--neutral-text)',
  };
  return (
    <div className="kpi-card" style={{ border: '1px solid var(--borders)', borderRadius: '8px', padding: 'var(--sp-3)', minWidth: 170, background: 'var(--surface)' }}>
      <div className="kpi-label">{title}</div>
      <div className="kpi-value" style={{ color: colorMap[tone] ?? 'var(--neutral-text)', fontSize: loading ? 0 : 28, visibility: loading ? 'hidden' : 'visible' }}>
        {loading ? '—' : value}
      </div>
      {sub ? <div className="kpi-sub">{sub}</div> : null}
    </div>
  );
}

/** Loading state for primary panels. */
export function LoadingPanel({ label = 'Loading…' }) {
  return (
    <div className="panel panel-pad" role="status" aria-label={label}>
      <span className="spinner" aria-hidden="true" /> {label}
    </div>
  );
}

/** Error state with optional retry. */
export function ErrorPanel({ message, onRetry }) {
  return (
    <div className="panel panel-pad" role="alert" aria-label="Error">
      <div className="error-summary">{message}</div>
      {onRetry ? <button type="button" className="btn-small btn-primary" onClick={onRetry}>Retry</button> : null}
    </div>
  );
}

/** Empty state. */
export function EmptyPanel({ title, hint }) {
  return (
    <div className="panel panel-pad">
      <div className="empty-state">
        <div className="empty-title">{title}</div>
        {hint ? <div className="small">{hint}</div> : null}
      </div>
    </div>
  );
}

/** Permission denied state. */
export function AccessDeniedPanel({ reason = 'access' }) {
  const messages = {
    access: 'You do not have permission to access this monitoring page.',
    admin: 'Monitoring administration requires System Admin permission.',
    write: 'You do not have permission to perform this monitoring action.',
  };
  return (
    <div className="access-denied" role="alert" aria-live="polite">
      <div className="alert alert-warning">
        <h4 className="alert-heading">{messages[reason] ?? messages.access}</h4>
        <p className="mb-0">
          If you believe you should have access, contact your system
          administrator.
        </p>
        <hr className="my-3" />
        <a className="btn btn-primary" href="#/dashboard">Go to Dashboard</a>
      </div>
    </div>
  );
}

/** Confirmation dialog wrapper (thin alias for shared ConfirmDialog for
 *  explicit confirmation intent on high-impact actions). */
export function ConfirmPanel({ title, message, confirmLabel = 'Confirm', danger, busy, onConfirm, onCancel, children }) {
  return (
    <div className="confirm-panel panel panel-pad">
      <h4>{title}</h4>
      <p style={{ marginTop: 0 }}>{message}</p>
      {children}
      <div className="row-end">
        <button type="button" className="btn-ghost" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="button" className={danger ? 'btn-danger' : 'btn-primary'} onClick={onConfirm} disabled={busy}>
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </div>
  );
}

/** Safe-value stripper: redacts secret-like keys from any object before
 *  rendering. Used so no secret ever reaches the DOM. */
const SECRET_KEYS = ['secret', 'password', 'token', 'authorization', 'api_key', 'apikey', 'private_key', 'client_secret', 'access_token', 'refresh_secret', 'signature', 'cookie'];

export function sanitizeRecord(record) {
  if (record === null || record === undefined) return record;
  if (Array.isArray(record)) return record.map(sanitizeRecord);
  if (typeof record === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(record)) {
      const key = String(k).toLowerCase();
      if (SECRET_KEYS.some((s) => key.includes(s))) {
        out[k] = '[REDACTED]';
      } else if (typeof v === 'object' && v !== null) {
        out[k] = sanitizeRecord(v);
      } else {
        out[k] = v;
      }
    }
    return out;
  }
  return record;
}
