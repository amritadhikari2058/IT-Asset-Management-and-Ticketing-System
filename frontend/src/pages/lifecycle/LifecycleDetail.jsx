import { useEffect, useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import {
  Badge, ErrorSummary, Field, PageHeader,
} from '../../components';
import { parseApiError } from '../../api-utils';
import {
  CASE_TYPE_LABELS, formatDate, formatDateTime, isTerminalCaseStatus,
  actionAvailability, getActionLabel, isActionReasonRequired,
} from '../../shared/lifecycle-utils';

const ACTION_SUFFIX = {
  plan: 'plan/',
  start: 'start/',
  mark_ready: 'mark_ready/',
  confirm_start: 'confirm_start/',
  complete: 'complete/',
  block: 'block/',
  unblock: 'unblock/',
  cancel: 'cancel/',
};

export function LifecycleDetail({ id }) {
  const { user, isStaff, isAdmin, isManagerOrAdmin, role } = useAuth();
  const [caseData, setCaseData] = useState(null);
  const [summary, setSummary] = useState(null);
  const [history, setHistory] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState({});
  const [transitionErr, setTransitionErr] = useState('');
  const [blockReason, setBlockReason] = useState('');
  const [cancelReason, setCancelReason] = useState('');
  const [confirming, setConfirming] = useState(null);
  const [staleMsg, setStaleMsg] = useState(null);

  const safeResults = (data) => {
    if (!data) return [];
    if (Array.isArray(data)) return data;
    return Array.isArray(data.results) ? data.results : [];
  };

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [cRes, sRes, hRes, tRes] = await Promise.allSettled([
        api.get(`/lifecycle/cases/${id}/`),
        api.get(`/lifecycle/cases/${id}/summary/`),
        api.get(`/lifecycle/cases/${id}/history/`, { params: { page_size: 20 } }),
        api.get('/lifecycle/tasks/', { params: { case: id, page_size: 50 } }),
      ]);
      if (cRes.status === 'fulfilled') setCaseData(cRes.value.data);
      else setError('Could not load case details.');
      if (sRes.status === 'fulfilled') setSummary(sRes.value.data);
      if (hRes.status === 'fulfilled') setHistory(safeResults(hRes.value.data));
      if (tRes.status === 'fulfilled') setTasks(safeResults(tRes.value.data));
      if (cRes.status === 'fulfilled') setVersion(cRes.value.data.version);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load case details.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect

  const doRefresh = async () => {
    setRefreshBusy(true);
    setStaleMsg(null);
    try {
      await load();
    } finally {
      setRefreshBusy(false);
    }
  };

  const c = caseData;
  const canSee = c ? (
    isAdmin || isManagerOrAdmin || isStaff || c.employee === (user?.id || user?.employee_id)
  ) : false;

  if (loading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading case…
      </p>
    );
  }
  if (error && !c) {
    const is404 = error.includes('404') || error.includes('not found');
    return (
      <div className="detail-wrap">
        <div className="error-summary" role="alert">
          {is404 ? 'This lifecycle case is unavailable or you no longer have access.' : error}
        </div>
        <button type="button" className="btn-secondary" onClick={doRefresh}>Retry</button>
        <p><a className="back-link" href="#/lifecycle">← Back to Lifecycle</a></p>
      </div>
    );
  }
  if (!canSee) {
    return (
      <div className="detail-wrap">
        <div className="error-summary" role="alert">
          You do not have permission to access this case.
        </div>
        <p><a className="back-link" href="#/lifecycle">← Back to Lifecycle</a></p>
      </div>
    );
  }

  const actions = actionAvailability(c.case_type, c.status, role);
  const isTerminal = isTerminalCaseStatus(c.status);

  const runTransition = async (action) => {
    if (!ACTION_SUFFIX[action]) return;
    if (actionBusy[action]) return;

    // Reason prompt for Block/Cancel.
    let reason = '';
    if (isActionReasonRequired(action)) {
      if (action === 'block') reason = blockReason.trim();
      if (action === 'cancel') reason = cancelReason.trim();
      if (!reason) {
        setTransitionErr(`A reason is required to ${getActionLabel(action).toLowerCase()} this case.`);
        return;
      }
    }

    setActionBusy((s) => ({ ...s, [action]: true }));
    setTransitionErr('');
    setStaleMsg(null);

    try {
      const payload = {
        version: c.version || 1,
        ...(reason ? { reason } : {}),
      };
      await api.post(`/lifecycle/cases/${c.id}/${ACTION_SUFFIX[action]}`, payload);
      if (action === 'block') setBlockReason('');
      if (action === 'cancel') setCancelReason('');
      setConfirming(null);
      await load(); // refresh case, summary, history, tasks
    } catch (e) {
      const p = parseApiError(e);
      if (e?.response?.status === 409) {
        setStaleMsg('This case changed while you were working. The latest version has been loaded.');
        setFieldErrors(p.fields);
        await load();
      } else if (e?.response?.status === 403) {
        setTransitionErr('You do not have permission to perform this action.');
      } else if (e?.response?.status === 404) {
        setTransitionErr('This case is no longer available.');
        await load();
      } else {
        setTransitionErr(p.global || `Could not ${def.label.toLowerCase()} the case.`);
      }
    } finally {
      setActionBusy((s) => { const n = { ...s }; delete n[action]; return n; });
    }
  };

  const handleBlockChange = (e) => setBlockReason(e.target.value);
  const handleCancelChange = (e) => setCancelReason(e.target.value);

  return (
    <div className="lifecycle-detail">
      <PageHeader
        title={`Case {c.case_number}`}
        sub={`${CASE_TYPE_LABELS[c.case_type] ?? c.case_type} · #${c.id}`}
        actions={
          <div className="row-gap" style={{ alignItems: 'center', gap: 'var(--sp-1)' }}>
            <button
              type="button" className="btn-secondary" onClick={doRefresh}
              disabled={refreshBusy}
              aria-label="Refresh case">
              {refreshBusy ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        }
      />
      {transitionErr && <div className="field-error" role="alert">{transitionErr}</div>}
      {staleMsg && <div className="alert alert-warning" role="status">{staleMsg}</div>}
      {error && <ErrorSummary parsed={{ global: error }} />}

      {/* Header info */}
      <section className="section" style={{ marginTop: 'var(--sp-2)' }}>
        <h3 className="section-title">Case Header</h3>
        <dl className="detail-grid">
          <dt>Case Number</dt><dd>{c.case_number}</dd>
          <dt>Employee</dt><dd>{c.employee_email || `User #${c.employee}`}</dd>
          <dt>Case Type</dt><dd>{CASE_TYPE_LABELS[c.case_type] ?? c.case_type}</dd>
          <dt>Status</dt><dd><Badge kind="status" value={c.status} /></dd>
          <dt>Priority</dt><dd><Badge kind="priority" value={c.priority} /></dd>
          <dt>Department</dt><dd>{c.department ? String(c.department) : '—'}</dd>
          <dt>Coordinator</dt><dd>{c.assigned_coordinator ? String(c.assigned_coordinator) : 'Unassigned'}</dd>
          <dt>Planned Date</dt><dd>{formatDate(c.planned_date)}</dd>
          <dt>Effective Date</dt><dd>{formatDate(c.effective_date)}</dd>
          <dt>Completion Target</dt><dd>{formatDate(c.completion_target)}</dd>
          <dt>Progress</dt><dd>
            <span className="badge badge-blue">{c.checklist_progress != null ? `${Math.round(c.checklist_progress)}%` : '0%'}</span>
          </dd>
          <dt>Overdue Tasks</dt><dd>{c.overdue_tasks || 0}</dd>
          <dt>Version</dt><dd>{c.version || 1}</dd>
        </dl>
      </section>

      {/* 1. Overview */}
      <section className="section" style={{ marginTop: 'var(--sp-3)' }}>
        <h3 className="section-title">Overview</h3>
        <p className="muted">
          {c.case_number} is a {CASE_TYPE_LABELS[c.case_type] ?? c.case_type} case for
          {c.employee_email || 'the employee'}, currently <strong>{c.status}</strong>.
          {c.notes && (
            <span>
              <br />
              <span className="pre-wrap">Notes: {c.notes}</span>
            </span>
          )}
        </p>
        <p className="muted small">
          Created {formatDateTime(c.created_at)} &middot;
          Last updated {formatDateTime(c.updated_at)} &middot;
          {c.started_at && `Started ${formatDateTime(c.started_at)}`} &middot;
          {c.completed_at && `Completed ${formatDateTime(c.completed_at)}`}
        </p>
      </section>

      {/* 2. Checklist Summary */}
      <section className="section" style={{ marginTop: 'var(--sp-3)' }}>
        <h3 className="section-title">Checklist Summary</h3>
        {summary ? (
          <>
            <div className="kpi-grid" style={{ gap: 'var(--sp-2)' }}>
              <div className="kpi-card">
                <div className="kpi-value">{summary.total_tasks || 0}</div>
                <div className="kpi-label">Total Tasks</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-value">{summary.completed_tasks || 0}</div>
                <div className="kpi-label">Completed Tasks</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-value">{summary.overdue_tasks || 0}</div>
                <div className="kpi-label">Overdue Tasks</div>
              </div>
            </div>
            <table className="grid" style={{ width: '100%', marginTop: 'var(--sp-2)' }}>
              <thead>
                <tr>
                  <th>Seq.</th><th>Title</th><th>Category</th><th>Responsibility</th>
                  <th>Status</th><th>Due</th><th>Required</th><th>Blocking</th><th>Evidence</th><th>Automation</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <tr key={t.id} style={{ borderBottom: '1px solid #eee' }}>
                    <td>{t.sequence}</td>
                    <td>{t.title}</td>
                    <td>{t.category || 'other'}</td>
                    <td>{t.responsibility || 'it'}</td>
                    <td><Badge kind="status" value={t.status} /></td>
                    <td>{formatDate(t.due_date)}</td>
                    <td>{t.required ? 'Yes' : 'No'}</td>
                    <td>{t.blocks_completion ? 'Yes' : 'No'}</td>
                    <td>{t.requires_evidence ? 'Yes' : 'No'}</td>
                    <td><span className={`badge badge-${t.automation_status === 'failed' ? 'red' : 'gray'}`}>{t.automation_status || 'not_applicable'}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p className="muted">Checklist summary unavailable.</p>
        )}
        <p className="muted small" style={{ marginTop: 'var(--sp-1)' }}>
          Task management (start, complete, block, evidence) is planned for O2.2.
          This summary is read-only in O2.1.
        </p>
      </section>

      {/* 3. History Summary */}
      <section className="section" style={{ marginTop: 'var(--sp-3)' }}>
        <h3 className="section-title">History</h3>
        {history.length ? (
          <ul className="timeline">
            {history.map((h) => (
              <li key={h.id} className="history-item">
                <div className="muted small">
                  {h.actor_email || `#${h.actor}`} · {h.created_at ? formatDateTime(h.created_at) : ''} · {h.event_type}
                </div>
                {h.detail && <div className="pre-wrap t-note">{h.detail}</div>}
                {h.previous_status || h.new_status && (
                  <div className="muted small">
                    {h.previous_status ? `from ${h.previous_status}` : ''}
                    {h.previous_status && h.new_status ? ' → ' : ''}
                    {h.new_status ? `to ${h.new_status}` : ''}
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No history entries.</p>
        )}
      </section>

      {/* 4. Completion Readiness Summary */}
      <section className="section" style={{ marginTop: 'var(--sp-3)' }}>
        <h3 className="section-title">Completion Readiness</h3>
        {summary ? (
          <>
            <p className="muted small">
              Progress: {summary.checklist_progress != null ? `${Math.round(summary.checklist_progress)}%` : '0%'} &middot;
              Completed: {summary.completed_tasks || 0} of {summary.total_tasks || 0} tasks &middot;
              Overdue: {summary.overdue_tasks || 0} tasks
            </p>
            <ul className="note-list">
              {summary.required_tasks_remaining != null && (
                <li>Required tasks remaining: <strong>{summary.required_tasks_remaining}</strong></li>
              )}
              {summary.blocking_tasks != null && (
                <li>Blocking tasks: <strong>{summary.blocking_tasks}</strong></li>
              )}
              {summary.failed_automations != null && (
                <li>Failed automations: <strong>{summary.failed_automations}</strong></li>
              )}
              {summary.unresolved_assets != null && (
                <li>Unresolved assets: <strong>{summary.unresolved_assets}</strong></li>
              )}
              {summary.access_revocation_pending != null && (
                <li>Access revocation pending: <strong>{summary.access_revocation_pending ? 'Yes' : 'No'}</strong></li>
              )}
              {summary.account_deactivation_pending != null && (
                <li>Account deactivation pending: <strong>{summary.account_deactivation_pending ? 'Yes' : 'No'}</strong></li>
              )}
              {summary.transfer_pending != null && (
                <li>Transfer pending: <strong>{summary.transfer_pending ? 'Yes' : 'No'}</strong></li>
              )}
              {summary.missing_evidence != null && (
                <li>Missing evidence: <strong>{summary.missing_evidence}</strong></li>
              )}
            </ul>
            <p className="muted small">
              Backend readiness is authoritative. Completion is enabled only when
              the backend accepts the transition.
            </p>
          </>
        ) : (
          <p className="muted">Readiness summary unavailable.</p>
        )}
      </section>

      {/* 5. Onboarding Actions */}
      <section className="section" style={{ marginTop: 'var(--sp-3)' }}>
        <h3 className="section-title">Onboarding Actions</h3>
        <p className="muted small">
          Actions are gated by your role ({role ?? '—'}) and the case's current
          status. The backend remains authoritative for all transitions.
        </p>
        <div className="action-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 'var(--sp-1)', marginTop: 'var(--sp-1)' }}>
          {Object.entries(actions).map(([actionKey, allowed]) => {
            if (!allowed || isTerminal) return null;
            const isOnboardingOnly = (actionKey === 'mark_ready' || actionKey === 'confirm_start') && c.case_type !== 'onboarding';
            if (isOnboardingOnly) return null;
            const needsReason = isActionReasonRequired(actionKey);
            const reasonField = needsReason ? (
              confirming === actionKey && (
                <Field label="Reason" required error={!blockReason && !cancelReason ? 'A reason is required.' : ''}>
                  <textarea className="input" rows={2}
                    value={actionKey === 'block' ? blockReason : cancelReason}
                    onChange={actionKey === 'block' ? handleBlockChange : handleCancelChange}
                    placeholder={`Reason for ${getActionLabel(actionKey).toLowerCase()}…`}
                    disabled={actionBusy[actionKey]}
                  />
                </Field>
              )
            ) : null;
            return (
              <div key={actionKey} className="action-card">
                <button
                  type="button"
                  className={`btn ${needsReason ? 'btn-outline' : 'btn-primary'} btn-block`}
                  onClick={() => setConfirming(actionKey)}
                  disabled={actionBusy[actionKey]}>
                  {actionBusy[actionKey] ? 'Working…' : getActionLabel(actionKey)}
                </button>
                {confirming === actionKey && (
                  <div className="action-confirm" style={{ marginTop: 'var(--sp-1)' }}>
                    {reasonField}
                    <div className="row-end" style={{ marginTop: 'var(--sp-1)' }}>
                      <button type="button" className="btn-ghost btn-small" onClick={() => setConfirming(null)}>
                        Cancel
                      </button>
                      <button type="button" className="btn-primary btn-small" onClick={() => runTransition(actionKey)} disabled={actionBusy[actionKey]}>
                        Confirm
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {Object.keys(actions).length === 0 || isTerminal && (
            <p className="muted">No actions available for this case in its current status.</p>
          )}
        </div>
      </section>

      <style>{`
        .lifecycle-detail .detail-grid { display: grid; grid-template-columns: 170px 1fr; gap: var(--sp-1) var(--sp-2); margin: var(--sp-2) 0; }
        .lifecycle-detail .detail-grid dt { margin: 0; font-weight: 600; color: #495057; }
        .lifecycle-detail .detail-grid dd { margin: 0 0 var(--sp-1) 0; padding: 0; }
        .lifecycle-detail .kpi-grid { display: flex; gap: var(--sp-1); }
        .lifecycle-detail .kpi-card { flex: 1; background: #f8f9fa; padding: var(--sp-2); border-radius: 6px; border: 1px solid #dee2e6; }
        .lifecycle-detail .kpi-value { font-size: 1.5rem; font-weight: 700; color: #0d6efd; }
        .lifecycle-detail .kpi-label { font-size: 0.85rem; color: #6c757d; }
        .lifecycle-detail .action-card { border: 1px solid #dee2e6; border-radius: 6px; padding: var(--sp-1); background: #fff; }
        .lifecycle-detail .action-card button.btn-block { width: 100%; }
        .lifecycle-detail .action-confirm { padding: var(--sp-1); background: #f8f9fa; border-radius: 4px; border: 1px dashed #ced4da; }
        .lifecycle-detail .history-item { padding: var(--sp-1) 0; border-bottom: 1px solid #eee; }
        .lifecycle-detail .t-note { margin-top: var(--sp-05); font-size: 0.9rem; }
        .lifecycle-detail .pre-wrap { white-space: pre-wrap; }
      `}</style>
    </div>
  );
}

