import { useCallback, useEffect, useState } from 'react';
import api from './api';
import { fetchPage, parseApiError } from './api-utils';
import { useAuth } from './auth';
import { Badge, EmptyState, Field, LoadingRows, Modal, PageHeader, Pager } from './components';

const STATUS_LABELS = {
  previewed: 'Previewed',
  processing: 'Processing',
  completed: 'Completed',
  failed: 'Failed',
};

const STATUS_OPTIONS = ['', 'previewed', 'processing', 'completed', 'failed'];

function fmtDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

function shortDigest(value) {
  if (!value) return '—';
  const s = String(value);
  return s.length > 16 ? `${s.slice(0, 12)}…${s.slice(-8)}` : s;
}

function reasonLabel(code) {
  const map = {
    invalid_outcome_status: 'Invalid outcome status recorded.',
    duplicate_or_inconsistent_evidence: 'Duplicate or inconsistent row evidence.',
    unexpected_extra_outcomes: 'Unexpected extra row outcomes.',
    unprocessed_or_unrecorded_rows: 'Some expected rows are unprocessed or unrecorded.',
    missing_ticket_reference: 'A succeeded outcome is missing its ticket reference.',
    invalid_failure_evidence: 'A failed outcome is missing failure evidence.',
    result_conflict: 'Stored result conflicts with durable evidence.',
    legacy_or_ambiguous_evidence: 'Legacy or ambiguous evidence; row-level proof is incomplete.',
    not_processed: 'Operation has not been processed.',
    already_finalized: 'Operation is already finalized.',
    stale_or_interrupted: 'Processing appears stale or interrupted.',
    completed_without_stored_result: 'Completed without a stored result.',
    counter_inconsistency: 'Stored counters do not match durable row evidence.',
  };
  return map[code] || code.replace(/_/g, ' ');
}

function assessmentState(assessment) {
  if (!assessment) return 'unavailable';
  if (assessment.eligible_for_finalization) return 'eligible';
  const reasons = assessment.reasons || [];
  if (reasons.includes('already_finalized')) return 'already_finalized';
  return 'ineligible';
}

function useBulkImportList(enabled = true) {
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(!!enabled);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [currentUrl, setCurrentUrl] = useState('/tickets/bulk-imports/');

  const buildUrl = useCallback((status = statusFilter) => {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    const qs = params.toString();
    return `/tickets/bulk-imports/${qs ? `?${qs}` : ''}`;
  }, [statusFilter]);

  const load = useCallback(async (url) => {
    if (!enabled) return;
    setLoading(true);
    setError('');
    try {
      const page = await fetchPage(url);
      setItems(page.items);
      setCount(page.count);
      setNext(page.next);
      setPrevious(page.previous);
      setCurrentUrl(url);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load bulk import operations.');
      setItems([]);
      setCount(null);
      setNext(null);
      setPrevious(null);
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => { if (enabled) load(buildUrl(statusFilter)); }, [enabled, statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect

  return {
    items, count, next, previous, loading, error, statusFilter,
    setStatusFilter: (v) => { setStatusFilter(v); },
    refresh: () => load(currentUrl),
    goNext: () => next && load(next),
    goPrev: () => previous && load(previous),
  };
}

export function TicketBulkImportsPage() {
  const { isStaff } = useAuth();
  const list = useBulkImportList(isStaff);

  if (!isStaff) {
    return <div className="access-denied" role="alert">You do not have permission to access this page.</div>;
  }

  return (
    <div className="page">
      <PageHeader
        title="Ticket bulk import operations"
        sub="Staff-only inspection of tokenized ticket bulk imports. Reconciliation and finalization use durable backend evidence only."
      />
      <div className="panel panel-pad">
        <div className="row-gap" style={{ marginBottom: 'var(--sp-3)', alignItems: 'end' }}>
          <Field label="Status">
            <select className="input" value={list.statusFilter} onChange={(e) => list.setStatusFilter(e.target.value)} aria-label="Filter by status">
              {STATUS_OPTIONS.map((s) => (
                <option key={s || 'all'} value={s}>{s ? STATUS_LABELS[s] : 'All statuses'}</option>
              ))}
            </select>
          </Field>
          <button type="button" className="btn-secondary" onClick={list.refresh} disabled={list.loading}>Refresh</button>
        </div>

        {list.error && <div className="error-summary" role="alert">{list.error}</div>}
        {list.loading ? <LoadingRows n={6} /> : list.items.length === 0 ? (
          <EmptyState title="No bulk import operations" hint="Tokenized bulk imports will appear here for staff inspection." />
        ) : (
          <>
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>User</th>
                    <th>Status</th>
                    <th>Rows</th>
                    <th>Counts</th>
                    <th>Created</th>
                    <th>Completed</th>
                    <th>Error</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {list.items.map((op) => (
                    <tr key={op.id}>
                      <td>#{op.id}</td>
                      <td>{op.user_email || op.user || '—'}</td>
                      <td><Badge kind="status" value={op.status} label={STATUS_LABELS[op.status] || op.status} /></td>
                      <td>{op.total_rows ?? 0}</td>
                      <td className="small muted">ok {op.successful_count ?? 0} / failed {op.failed_count ?? 0} / processed {op.processed_count ?? 0}</td>
                      <td className="small">{fmtDate(op.created_at)}</td>
                      <td className="small">{fmtDate(op.completed_at)}</td>
                      <td className="small" title={op.error_detail || ''}>{op.error_detail ? String(op.error_detail).slice(0, 60) : '—'}</td>
                      <td><a className="btn-small" href={`#/tickets/bulk-imports/${op.id}`}>Inspect</a></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager
              count={list.count}
              hasNext={!!list.next}
              hasPrev={!!list.previous}
              onNext={list.goNext}
              onPrev={list.goPrev}
              busy={list.loading}
            />
          </>
        )}
      </div>
    </div>
  );
}

function AssessmentWarnings({ assessment }) {
  if (!assessment) return null;
  const reasons = assessment.reasons || [];
  const missing = assessment.missing_ticket_references || [];
  const counters = assessment.counter_inconsistencies || [];
  const dupes = assessment.duplicate_or_inconsistent_evidence || [];
  const conflicts = assessment.result_conflicts || [];
  const legacy = assessment.legacy_or_ambiguous_indicators || [];
  const hasAny = reasons.length || missing.length || counters.length || dupes.length || conflicts.length || legacy.length;
  if (!hasAny) return <p className="muted small">No integrity warnings reported.</p>;
  return (
    <div className="stack-gap-sm">
      {missing.length > 0 && (
        <div className="error-summary" role="alert">
          <strong>Missing ticket references (finalization blocked)</strong>
          <div className="small" style={{ marginTop: 'var(--sp-1)' }}>
            One or more succeeded outcomes no longer reference an existing ticket. This is an integrity issue.
            The operation cannot be safely finalized, and tickets will not be recreated or replayed.
          </div>
          <ul style={{ margin: 'var(--sp-2) 0 0', paddingLeft: '1.2rem' }}>
            {missing.map((m, i) => (
              <li key={i} className="small">Row index {m.row_index}, outcome #{m.outcome_id}: {m.issue || 'missing ticket reference'}{m.ticket_id == null ? ' (ticket_id is null)' : ` (ticket ${m.ticket_id})`}</li>
            ))}
          </ul>
        </div>
      )}
      {counters.length > 0 && (
        <div className="alert-warning" role="status" style={{ padding: 'var(--sp-2)', border: '1px solid var(--border, #d0d7de)', borderRadius: 6 }}>
          <strong>Counter discrepancies reported</strong>
          <div className="small" style={{ marginTop: 'var(--sp-1)' }}>
            Stored counters differ from durable row evidence. If the operation is otherwise eligible, explicit audited finalization may set counters to evidence-derived values. Counters are not repaired silently.
          </div>
          <ul style={{ margin: 'var(--sp-2) 0 0', paddingLeft: '1.2rem' }}>
            {counters.map((c, i) => <li key={i} className="small">{c}</li>)}
          </ul>
        </div>
      )}
      {dupes.length > 0 && (
        <div className="error-summary" role="alert">
          <strong>Duplicate/inconsistent evidence</strong>
          <ul style={{ margin: 'var(--sp-2) 0 0', paddingLeft: '1.2rem' }}>{dupes.map((d, i) => <li key={i} className="small">{d}</li>)}</ul>
        </div>
      )}
      {conflicts.length > 0 && (
        <div className="error-summary" role="alert">
          <strong>Result conflicts</strong>
          <ul style={{ margin: 'var(--sp-2) 0 0', paddingLeft: '1.2rem' }}>{conflicts.map((c, i) => <li key={i} className="small">{c}</li>)}</ul>
        </div>
      )}
      {legacy.length > 0 && (
        <div className="alert-warning" role="status" style={{ padding: 'var(--sp-2)', border: '1px solid var(--border, #d0d7de)', borderRadius: 6 }}>
          <strong>Legacy/ambiguous evidence</strong>
          <ul style={{ margin: 'var(--sp-2) 0 0', paddingLeft: '1.2rem' }}>{legacy.map((c, i) => <li key={i} className="small">{c}</li>)}</ul>
        </div>
      )}
      {reasons.length > 0 && (
        <div>
          <strong className="small">Assessment reasons</strong>
          <ul style={{ margin: 'var(--sp-1) 0 0', paddingLeft: '1.2rem' }}>
            {reasons.map((r, i) => <li key={i} className="small"><code>{r}</code> — {reasonLabel(r)}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function FinalizeModal({ operation, assessment, onClose, onFinalized }) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [stale, setStale] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (busy || stale) return;
    const trimmed = reason.trim();
    if (!trimmed) {
      setError('A reason is required for finalization.');
      return;
    }
    const digest = assessment?.evidence_digest;
    if (!digest) {
      setError('Current evidence digest is missing. Refresh the reconciliation assessment.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const payload = {
        reason: trimmed,
        evidence_digest: digest,
      };
      if (assessment.current_status) payload.expected_status = assessment.current_status;
      const res = await api.post(`/tickets/bulk-imports/${operation.id}/reconciliation/finalize/`, payload);
      onFinalized(res.data);
    } catch (err) {
      const status = err?.response?.status;
      const data = err?.response?.data;
      const code = data?.code;
      if (status === 409 || code === 'stale_evidence' || code === 'not_eligible' || code === 'conflict') {
        setStale(true);
        setError(parseApiError(err).global || 'Evidence changed or the operation is no longer eligible. Refresh and review the latest assessment before confirming again.');
        onFinalized(null, { stale: true, error: err });
        return;
      }
      setError(parseApiError(err).global || 'Finalization failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={`Finalize import operation #${operation.id}`} size="lg" onClose={() => { if (!busy) onClose(); }}>
      <form onSubmit={submit} noValidate>
        <p className="muted small modal-intro">
          This is an explicit, audited administrative action. It does not create tickets, replay rows, or fabricate evidence.
          The backend will re-evaluate durable row evidence under lock before finalizing.
        </p>
        <div className="panel panel-pad" style={{ marginBottom: 'var(--sp-3)' }}>
          <div className="small"><strong>Current status:</strong> {STATUS_LABELS[assessment.current_status] || assessment.current_status}</div>
          <div className="small"><strong>Proposed status:</strong> {STATUS_LABELS[assessment.proposed_status] || assessment.proposed_status || '—'}</div>
          <div className="small"><strong>Expected rows:</strong> {assessment.expected_row_count ?? 0}</div>
          <div className="small"><strong>Succeeded rows:</strong> {assessment.succeeded_outcome_count ?? 0}</div>
          <div className="small"><strong>Failed rows:</strong> {assessment.failed_outcome_count ?? 0}</div>
          <div className="small"><strong>Evidence digest:</strong> <code>{assessment.evidence_digest}</code></div>
        </div>
        {(assessment.counter_inconsistencies || []).length > 0 && (
          <div className="alert-warning" role="status" style={{ padding: 'var(--sp-2)', marginBottom: 'var(--sp-3)', border: '1px solid var(--border, #d0d7de)', borderRadius: 6 }}>
            <strong>Counter discrepancies will be recorded</strong>
            <div className="small">Finalization will use durable row evidence and may set stored counters to evidence-derived values. This is audited.</div>
          </div>
        )}
        {error && !( !reason.trim() && error === 'A reason is required for finalization.') && <div className="error-summary" role="alert">{error}</div>}
        {stale && (
          <div className="alert-warning" role="status" style={{ padding: 'var(--sp-2)', marginBottom: 'var(--sp-3)', border: '1px solid var(--border, #d0d7de)', borderRadius: 6 }}>
            The assessment is stale or no longer eligible. Review the refreshed assessment before taking any further action. Do not resubmit with an old digest.
          </div>
        )}
        <Field label="Reason for finalization" required error={!reason.trim() && error === 'A reason is required for finalization.' ? error : ''}>
          <textarea
            className="input"
            rows={4}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            disabled={busy || stale}
            aria-label="Reason for finalization"
            placeholder="Explain why this operation is being finalized"
          />
        </Field>
        <div className="row-end">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy || stale}>
            {busy ? 'Finalizing…' : 'Confirm finalization'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function TicketBulkImportDetailPage({ id }) {
  const { isStaff } = useAuth();
  const [operation, setOperation] = useState(null);
  const [assessment, setAssessment] = useState(null);
  const [audit, setAudit] = useState([]);
  const [loading, setLoading] = useState(true);
  const [assessLoading, setAssessLoading] = useState(false);
  const [auditLoading] = useState(false);
  const [error, setError] = useState('');
  const [assessError, setAssessError] = useState('');
  const [auditError, setAuditError] = useState('');
  const [showFinalize, setShowFinalize] = useState(false);
  const [notice, setNotice] = useState('');

  const loadAll = useCallback(async ({ silent = false } = {}) => {
    if (!isStaff) return;
    if (!silent) setLoading(true);
    setError(''); setAssessError(''); setAuditError(''); setNotice('');
    try {
      const [opRes, assessRes, auditRes] = await Promise.all([
        api.get(`/tickets/bulk-imports/${id}/`),
        api.get(`/tickets/bulk-imports/${id}/reconciliation/`),
        api.get(`/tickets/bulk-imports/${id}/reconciliation/audit/`),
      ]);
      setOperation(opRes.data);
      setAssessment(assessRes.data);
      setAudit(Array.isArray(auditRes.data?.audit) ? auditRes.data.audit : []);
    } catch (e) {
      const msg = parseApiError(e).global || 'Could not load import operation.';
      setError(msg);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [id, isStaff]);

  const refreshAssessment = useCallback(async () => {
    if (!isStaff) return;
    setAssessLoading(true); setAssessError('');
    try {
      const [opRes, assessRes, auditRes] = await Promise.all([
        api.get(`/tickets/bulk-imports/${id}/`),
        api.get(`/tickets/bulk-imports/${id}/reconciliation/`),
        api.get(`/tickets/bulk-imports/${id}/reconciliation/audit/`),
      ]);
      setOperation(opRes.data);
      setAssessment(assessRes.data);
      setAudit(Array.isArray(auditRes.data?.audit) ? auditRes.data.audit : []);
    } catch (e) {
      setAssessError(parseApiError(e).global || 'Could not refresh reconciliation assessment.');
    } finally {
      setAssessLoading(false);
    }
  }, [id, isStaff]);

  useEffect(() => { if (isStaff) loadAll(); else setLoading(false); }, [isStaff, loadAll]); // eslint-disable-line react/set-state-in-effect

  if (!isStaff) {
    return <div className="access-denied" role="alert">You do not have permission to access this page.</div>;
  }

  if (loading) return <p className="page-loading" role="status"><span className="spinner" aria-hidden="true" />Loading import operation…</p>;
  if (error) {
    return (
      <div className="page">
        <PageHeader title={`Import operation #${id}`} />
        <div className="error-summary" role="alert">{error}</div>
        <p><a href="#/tickets/bulk-imports">Back to import operations</a></p>
      </div>
    );
  }
  if (!operation) return null;

  const state = assessmentState(assessment);
  const canFinalize = state === 'eligible' && !assessLoading;

  const onFinalized = async (result, meta) => {
    if (meta?.stale) {
      setShowFinalize(false);
      setNotice('The finalization was not applied because evidence changed or the operation is no longer eligible. The latest assessment has been refreshed.');
      await refreshAssessment();
      return;
    }
    setShowFinalize(false);
    if (result?.idempotent) {
      setNotice('Operation was already finalized. Showing the current recorded state.');
    } else {
      setNotice('Finalization completed. The operation, assessment, and audit history have been refreshed.');
    }
    await refreshAssessment();
  };

  return (
    <div className="page">
      <PageHeader
        title={`Import operation #${operation.id}`}
        sub={(
          <span>
            <Badge kind="status" value={operation.status} label={STATUS_LABELS[operation.status] || operation.status} />{' '}
            <span className="muted small">User: {operation.user_email || operation.user || '—'}</span>
          </span>
        )}
        actions={<a className="btn-ghost" href="#/tickets/bulk-imports">Back to operations</a>}
      />
      {notice && <div className="alert-warning" role="status" style={{ padding: 'var(--sp-2)', marginBottom: 'var(--sp-3)', border: '1px solid var(--border, #d0d7de)', borderRadius: 6 }}>{notice}</div>}
      {assessError && <div className="error-summary" role="alert">{assessError}</div>}

      <div className="panel panel-pad" style={{ marginBottom: 'var(--sp-3)' }}>
        <h3>Operation details</h3>
        <div className="detail-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--sp-2)' }}>
          <div className="small"><strong>Status:</strong> {STATUS_LABELS[operation.status] || operation.status}</div>
          <div className="small"><strong>User:</strong> {operation.user_email || operation.user || '—'}</div>
          <div className="small"><strong>Created:</strong> {fmtDate(operation.created_at)}</div>
          <div className="small"><strong>Started:</strong> {fmtDate(operation.started_at)}</div>
          <div className="small"><strong>Completed:</strong> {fmtDate(operation.completed_at)}</div>
          <div className="small"><strong>Expires:</strong> {fmtDate(operation.expires_at)}</div>
          <div className="small"><strong>Total rows:</strong> {operation.total_rows ?? 0}</div>
          <div className="small"><strong>Processed:</strong> {operation.processed_count ?? 0}</div>
          <div className="small"><strong>Successful:</strong> {operation.successful_count ?? 0}</div>
          <div className="small"><strong>Failed:</strong> {operation.failed_count ?? 0}</div>
          <div className="small"><strong>Result available:</strong> {operation.result_available ? 'Yes' : 'No'}</div>
          <div className="small"><strong>Stale processing:</strong> {operation.is_stale_processing ? 'Yes' : 'No'}</div>
        </div>
        {operation.error_detail ? <div className="small" style={{ marginTop: 'var(--sp-2)' }}><strong>Error:</strong> {operation.error_detail}</div> : null}
      </div>

      <div className="panel panel-pad" style={{ marginBottom: 'var(--sp-3)' }}>
        <div className="row-gap" style={{ justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--sp-2)' }}>
          <h3 style={{ margin: 0 }}>Reconciliation assessment</h3>
          <button type="button" className="btn-secondary" onClick={refreshAssessment} disabled={assessLoading}>{assessLoading ? 'Refreshing…' : 'Refresh assessment'}</button>
        </div>
        {!assessment ? (
          <p className="muted">Assessment unavailable.</p>
        ) : (
          <>
            <div className="row-gap" style={{ marginBottom: 'var(--sp-2)', alignItems: 'center' }}>
              <strong>Eligibility:</strong>
              {state === 'eligible' && <span className="badge badge-green">Eligible for finalization</span>}
              {state === 'ineligible' && <span className="badge badge-red">Ineligible for finalization</span>}
              {state === 'already_finalized' && <span className="badge badge-blue">Already finalized</span>}
              {state === 'unavailable' && <span className="badge badge-gray">Assessment unavailable</span>}
            </div>
            <div className="detail-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--sp-2)', marginBottom: 'var(--sp-3)' }}>
              <div className="small"><strong>Current status:</strong> {STATUS_LABELS[assessment.current_status] || assessment.current_status}</div>
              <div className="small"><strong>Proposed status:</strong> {STATUS_LABELS[assessment.proposed_status] || assessment.proposed_status || '—'}</div>
              <div className="small"><strong>Expected rows:</strong> {assessment.expected_row_count ?? 0}</div>
              <div className="small"><strong>Actual outcomes:</strong> {assessment.actual_outcome_count ?? 0}</div>
              <div className="small"><strong>Succeeded:</strong> {assessment.succeeded_outcome_count ?? 0}</div>
              <div className="small"><strong>Failed:</strong> {assessment.failed_outcome_count ?? 0}</div>
              <div className="small"><strong>Unprocessed/unrecorded:</strong> {assessment.unprocessed_row_count ?? 0}</div>
              <div className="small"><strong>Result stored:</strong> {assessment.result_stored ? 'Yes' : 'No'}</div>
              <div className="small"><strong>Row-level evidence:</strong> {assessment.has_row_level_evidence ? 'Yes' : 'No'}</div>
              <div className="small"><strong>Stale processing:</strong> {assessment.is_stale_processing ? 'Yes' : 'No'}</div>
            </div>
            <div className="small" style={{ marginBottom: 'var(--sp-3)' }}>
              <strong>Evidence digest:</strong> <code title={assessment.evidence_digest}>{shortDigest(assessment.evidence_digest)}</code>
              {assessment.evidence_digest ? <span className="muted"> (used for confirmation binding)</span> : null}
            </div>
            <AssessmentWarnings assessment={assessment} />
            <div style={{ marginTop: 'var(--sp-3)' }}>
              {canFinalize ? (
                <button type="button" className="btn-primary" onClick={() => { setNotice(''); setShowFinalize(true); }}>
                  Finalize operation
                </button>
              ) : (
                <p className="muted small" style={{ marginBottom: 0 }}>
                  {state === 'already_finalized'
                    ? 'This operation is already finalized. No further finalization action is available.'
                    : 'Finalization is unavailable because the backend assessment is not eligible.'}
                </p>
              )}
            </div>
          </>
        )}
      </div>

      <div className="panel panel-pad">
        <h3>Finalization audit history</h3>
        {auditError ? <div className="error-summary" role="alert">{auditError}</div> : null}
        {auditLoading ? <LoadingRows n={3} /> : audit.length === 0 ? (
          <EmptyState title="No finalization audit records" hint="Finalization audit entries appear after a staff finalization action." />
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Outcome</th>
                  <th>State</th>
                  <th>Counts</th>
                  <th>Reason</th>
                  <th>Digest</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((a) => (
                  <tr key={a.id}>
                    <td className="small">{fmtDate(a.timestamp)}</td>
                    <td className="small">{a.actor_email || a.actor || '—'}</td>
                    <td className="small">{a.action || '—'}</td>
                    <td className="small">{a.finalization_outcome || '—'}</td>
                    <td className="small">{a.previous_operation_state || '—'} → {a.resulting_operation_state || '—'}</td>
                    <td className="small">exp {a.expected_row_count ?? '—'} / ok {a.succeeded_row_count ?? '—'} / failed {a.failed_row_count ?? '—'}</td>
                    <td className="small">{a.reason || '—'}</td>
                    <td className="small"><code title={a.evidence_digest || ''}>{shortDigest(a.evidence_digest)}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showFinalize && assessment && (
        <FinalizeModal
          operation={operation}
          assessment={assessment}
          onClose={() => setShowFinalize(false)}
          onFinalized={onFinalized}
        />
      )}
    </div>
  );
}
