import { useEffect, useRef, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { Badge, EmptyState, ErrorSummary, Field, PageHeader } from './components';
import { fieldMsg, parseApiError, fetchPage } from './api-utils';
import {
  CASE_TYPE_LABELS, formatDate, formatDateTime, formatPercent,
  isTerminalCaseStatus,
} from './lifecycle-utils';

const KPIS = [
  { key: 'onboarding_in_progress', label: 'Onboarding In Progress', tone: 'blue' },
  { key: 'onboarding_due_7d', label: 'Onboarding Due in 7 Days', tone: 'amber' },
  { key: 'onboarding_blocked', label: 'Onboarding Blocked', tone: 'red' },
  { key: 'offboarding_in_progress', label: 'Offboarding In Progress', tone: 'blue' },
  { key: 'offboarding_effective_7d', label: 'Offboarding Effective in 7 Days', tone: 'amber' },
  { key: 'offboarding_unresolved_assets', label: 'Offboarding with Unresolved Assets', tone: 'red' },
  { key: 'offboarding_awaiting_deactivation', label: 'Awaiting Account Deactivation', tone: 'red' },
  { key: 'transfers_in_progress', label: 'Transfers In Progress', tone: 'blue' },
  { key: 'overdue_tasks', label: 'Overdue Tasks', tone: 'red' },
  { key: 'failed_automations', label: 'Failed Automations', tone: 'red' },
];

export function LifecycleDashboard() {
  const { isStaff, isAdmin, isManagerOrAdmin, isEmployee } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState(null);

  // Filters (UI only; passed through to list views when user navigates).
  const [filters, setFilters] = useState({
    case_type: '', department: '', coordinator: '', date_from: '', date_to: '',
  });

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const r = await api.get('/lifecycle/dashboard/');
      setData(r.data);
      setLastRefreshed(new Date());
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load the Lifecycle dashboard.');
    } finally {
      setLoading(false);
    }
  };

  const doRefresh = async () => {
    setRefreshBusy(true);
    try {
      const r = await api.get('/lifecycle/dashboard/');
      setData(r.data);
      setLastRefreshed(new Date());
      setError('');
    } catch (e) {
      setError(parseApiError(e).global || 'Refresh failed.');
    } finally {
      setRefreshBusy(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const canManage = isAdmin || isManagerOrAdmin || isStaff;

  const renderKpi = (key, label, tone) => {
    const value = data ? Number(data[key] || 0) : 0;
    return (
      <div key={key} className="kpi-card">
        <div className="kpi-value">{value}</div>
        <div className="kpi-label">{label}</div>
        <span className={`badge badge-${tone}`}>{label}</span>
      </div>
    );
  };

  if (loading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading Lifecycle dashboard…
      </p>
    );
  }
  if (error && !data) {
    return (
      <div className="detail-wrap">
        <div className="error-summary" role="alert">{error}</div>
        <button type="button" className="btn-secondary" onClick={doRefresh}>Retry</button>
        <p><a className="back-link" href="#/dashboard">← Back to Dashboard</a></p>
      </div>
    );
  }

  const isEmployeeView = isEmployee && !isStaff;
  const d = data || {};

  return (
    <div className="lifecycle-dashboard">
      <PageHeader
        title="Lifecycle Dashboard"
        sub={isEmployeeView ? 'Your own active case and assigned tasks.' : 'Management overview of onboarding, offboarding and transfer cases.'}
        actions={
          <div className="row-gap" style={{ alignItems: 'center', gap: 'var(--sp-1)' }}>
            {lastRefreshed && (
              <span className="muted small">Last refreshed {formatDateTime(lastRefreshed)}</span>
            )}
            <button
              type="button" className="btn-secondary" onClick={doRefresh}
              disabled={refreshBusy}
              aria-label="Refresh dashboard"
            >
              {refreshBusy ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        }
      />
      {error && <ErrorSummary parsed={{ global: error }} />}

      <section className="section" style={{ marginTop: 'var(--sp-3)' }}>
        <h3 className="section-title">
          {isEmployeeView ? 'Your Lifecycle Case' : 'Management KPIs'}
        </h3>
        <div className="kpi-grid">
          {isEmployeeView
            ? (() => {
                const own = {
                  onboarding_in_progress: d.onboarding_in_progress ?? 0,
                  overdue_tasks: d.overdue_tasks ?? 0,
                  failed_automations: d.failed_automations ?? 0,
                };
                return [
                  { key: 'onboarding_in_progress', label: 'Active Cases', value: own.onboarding_in_progress },
                  { key: 'overdue_tasks', label: 'Overdue Tasks', value: own.overdue_tasks },
                  { key: 'failed_automations', label: 'Failed Automations', value: own.failed_automations },
                ].map((k) => (
                  <div key={k.key} className="kpi-card">
                    <div className="kpi-value">{k.value}</div>
                    <div className="kpi-label">{k.label}</div>
                  </div>
                ));
              })()
            : KPIS.map((k) => renderKpi(k.key, k.label, k.tone))}
        </div>
      </section>

      {canManage && (
        <>
          <section className="section" style={{ marginTop: 'var(--sp-3)' }}>
            <h3 className="section-title">Filters</h3>
            <div className="filter-bar" style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-2)', alignItems: 'end' }}>
              <Field label="Case Type">
                <select className="input" value={filters.case_type} onChange={(e) => setFilters((f) => ({ ...f, case_type: e.target.value }))}>
                  <option value="">All case types</option>
                  {Object.entries(CASE_TYPE_LABELS).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </Field>
              <Field label="Department">
                <select className="input" value={filters.department} onChange={(e) => setFilters((f) => ({ ...f, department: e.target.value }))}>
                  <option value="">All departments</option>
                </select>
              </Field>
              <Field label="Coordinator">
                <select className="input" value={filters.coordinator} onChange={(e) => setFilters((f) => ({ ...f, coordinator: e.target.value }))}>
                  <option value="">All coordinators</option>
                </select>
              </Field>
              <Field label="Date From">
                <input className="input" type="date" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
              </Field>
              <Field label="Date To">
                <input className="input" type="date" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
              </Field>
            </div>
            <p className="muted small">Use the case lists below to browse filtered results.</p>
          </section>

          <section className="section" style={{ marginTop: 'var(--sp-3)' }}>
            <h3 className="section-title">Recent Cases</h3>
            {d.recent_cases && d.recent_cases.length ? (
              <ul className="note-list">
                {d.recent_cases.map((c) => (
                  <li key={c.case_number || c.id} className="mini-item">
                    <a href={`#/lifecycle/${c.id}`} className="mini-link">{c.case_number}</a>
                    <span className="mini-desc">{CASE_TYPE_LABELS[c.case_type] ?? c.case_type} · {c.status}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No recent cases.</p>
            )}
          </section>

          <section className="section" style={{ marginTop: 'var(--sp-3)' }}>
            <h3 className="section-title">Urgent Cases</h3>
            {d.urgent_cases && d.urgent_cases.length ? (
              <ul className="note-list">
                {d.urgent_cases.map((c) => (
                  <li key={c.case_number || c.id} className="mini-item">
                    <a href={`#/lifecycle/${c.id}`} className="mini-link">{c.case_number}</a>
                    <span className="mini-desc">{CASE_TYPE_LABELS[c.case_type] ?? c.case_type} · <span className="badge badge-red">Urgent</span></span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No urgent cases.</p>
            )}
          </section>

          <section className="section" style={{ marginTop: 'var(--sp-3)' }}>
            <h3 className="section-title">Assigned Tasks</h3>
            {d.tasks_assigned_to_me && d.tasks_assigned_to_me.length ? (
              <ul className="note-list">
                {d.tasks_assigned_to_me.map((t) => (
                  <li key={t.id} className="mini-item">
                    <a href={`#/lifecycle/${t.case__case_number}`} className="mini-link">{t.title}</a>
                    <span className="mini-desc">{t.case__case_number} · {t.status} · {t.due_date ? formatDate(t.due_date) : '—'}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No tasks assigned to you.</p>
            )}
          </section>
        </>
      )}

      {!canManage && (
        <section className="section" style={{ marginTop: 'var(--sp-3)' }}>
          <h3 className="section-title">Your Active Case</h3>
          <p className="muted">
            You have {d.onboarding_in_progress ?? 0} active onboarding case(s) and
            {d.overdue_tasks ?? 0} overdue task(s). Open your case from the
            navigation to view its checklist and progress.
          </p>
        </section>
      )}
    </div>
  );
}
