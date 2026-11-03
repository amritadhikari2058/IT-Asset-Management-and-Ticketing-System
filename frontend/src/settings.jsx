import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { Badge, EmptyState, Field, PageHeader } from './components';
import { parseApiError } from './api-utils';

/** Fallback category list + opt-in defaults (backend source of truth). */
const DEFAULT_CATEGORIES = [
  { key: 'ticket_assignment', label: 'Ticket assigned to me' },
  { key: 'ticket_status_change', label: 'Ticket status changed' },
  { key: 'ticket_reply', label: 'New reply or note on my ticket' },
  { key: 'sla_escalation', label: 'SLA escalation / breach' },
  { key: 'maintenance_reminder', label: 'Maintenance reminder' },
  { key: 'asset_assignment', label: 'Asset assigned or returned' },
  { key: 'system_alert', label: 'System alerts' },
];

const DEFAULT_ENABLED = {
  ticket_assignment: true,
  ticket_status_change: true,
  ticket_reply: true,
  sla_escalation: true,
  maintenance_reminder: true,
  asset_assignment: true,
  system_alert: true,
};

function prefsToState(pref) {
  const categories = { ...DEFAULT_ENABLED };
  const raw = pref?.categories;
  if (raw && typeof raw === 'object') {
    for (const key of Object.keys(DEFAULT_ENABLED)) {
      if (typeof raw[key] === 'boolean') categories[key] = raw[key];
    }
  }
  return {
    email_enabled: pref?.email_enabled !== false,
    categories,
  };
}

/** Notification preferences settings page (backed by /api/common/notification-preferences/). */
export function NotificationSettings() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [hasRecord, setHasRecord] = useState(false);
  const [recordId, setRecordId] = useState(null);
  const [emailEnabled, setEmailEnabled] = useState(true);
  const [categories, setCategories] = useState({ ...DEFAULT_ENABLED });
  const [emailCategories, setEmailCategories] = useState(DEFAULT_CATEGORIES);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const r = await api.get('/common/notification-preferences/');
      const data = r.data;
      const rows = data?.results ?? data ?? [];
      const mine = (Array.isArray(rows) ? rows : []).filter(
        (p) => !p?.user || String(p.user) === String(user?.id),
      );
      if (mine.length > 0) {
        const pref = mine[0];
        setHasRecord(true);
        setRecordId(pref.id ?? null);
        const st = prefsToState(pref);
        setEmailEnabled(st.email_enabled);
        setCategories(st.categories);
        setEmailCategories(
          pref.email_categories?.length
            ? pref.email_categories
            : DEFAULT_CATEGORIES,
        );
      } else {
        // No preference record yet -> sensible defaults (all email on).
        setHasRecord(false);
        setRecordId(null);
        setEmailEnabled(true);
        setCategories({ ...DEFAULT_ENABLED });
        setEmailCategories(DEFAULT_CATEGORIES);
      }
    } catch {
      setError('Could not load notification preferences. Please retry.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleCategory = (key, checked) => {
    setCategories((p) => ({ ...p, [key]: checked }));
    setMsg('');
  };

  const toggleEmailEnabled = () => {
    setEmailEnabled((v) => !v);
    setMsg('');
  };

  const save = async () => {
    setSaving(true);
    setError('');
    setMsg('');
    const payload = { email_enabled: emailEnabled, categories };
    try {
      if (recordId) {
        await api.patch(`/common/notification-preferences/${recordId}/`, payload);
      } else {
        const r = await api.post('/common/notification-preferences/', payload);
        setRecordId(r.data.id);
      }
      setHasRecord(true);
      setMsg('Notification preferences saved.');
    } catch (e) {
      // Keep the unsaved edits in place; surface the API error.
      setError(parseApiError(e).global || 'Could not save notification preferences.');
    } finally {
      setSaving(false);
    }
  };

  const enabledFor = (key) => !!categories[key];

  return (
    <div>
      <PageHeader
        title="Notification settings"
        sub="Control which ticket and system emails you receive."
        actions={
          <button type="button" className="btn-primary" onClick={save} disabled={saving || loading}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        }
      />
      {loading ? (
        <div className="panel"><div className="panel-pad"><span className="spinner" /> Loading notification preferences…</div></div>
      ) : (
        <>
          {error && <div className="error-summary" role="alert">{error}</div>}
          {msg && <div className="success-summary" role="status">{msg}</div>}

          <div className="panel">
            <div className="panel-title"><h4>Email notifications</h4></div>
            <div className="panel-pad">
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={emailEnabled}
                  onChange={toggleEmailEnabled}
                  disabled={saving}
                />
                Enable email notifications
              </label>
              <p className="muted small" style={{ marginTop: 'var(--sp-2)' }}>
                Master switch for all email notifications. Turn off to stop all
                (non-essential) email notifications. In-app notifications and
                security / password / verification emails are always delivered.
              </p>
            </div>
          </div>

          <div className="panel">
            <div className="panel-title"><h4>Notification categories</h4></div>
            <div className="panel-pad">
              {emailCategories.map((c) => (
                <div key={c.key} className="check-row" style={{ justifyContent: 'space-between' }}>
                  <span>
                    {c.label}
                    <span className="muted small" style={{ display: 'block' }}>{c.key}</span>
                  </span>
                  <label className="row-gap" style={{ marginBottom: 0 }}>
                    <span className="muted small">Off</span>
                    <input
                      type="checkbox"
                      checked={enabledFor(c.key)}
                      onChange={(e) => toggleCategory(c.key, e.target.checked)}
                      disabled={saving}
                      aria-label={`Email notifications for ${c.label}`}
                    />
                    <span className="muted small">On</span>
                  </label>
                </div>
              ))}
              <p className="muted small" style={{ marginTop: 'var(--sp-2)' }}>
                Choose which notification categories you receive by email. A
                disabled category never blocks unrelated categories, and users
                without a preference record receive all categories by default.
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default NotificationSettings;
