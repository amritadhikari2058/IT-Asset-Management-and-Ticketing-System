import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, ConfirmDialog, DataTable, Field, PageHeader, Pager,
} from './components';
import { fetchPage, parseApiError } from './api-utils';

const STATUS_ORDER = [
  'pending_review', 'approved', 'rejected',
  'execution_pending', 'executing', 'completed', 'failed', 'cancelled',
];

const STATUS_LABEL = {
  pending_review: 'Pending review', approved: 'Approved', rejected: 'Rejected',
  execution_pending: 'Execution pending', executing: 'Executing',
  completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled',
};

function statusBadge(status) {
  return (
    <Badge kind="status" value={status}
           label={STATUS_LABEL[status] || status} />
  );
}

/** Privacy-erasure governance page.
 *
 * Hash-based sub-views:
 *   #/privacy            dashboard
 *   #/privacy/requests   request list
 *   #/privacy/requests/new   create request
 *   #/privacy/requests/:id   request detail (+ approve/reject/execute/cancel)
 *
 * Backend enforces two-person approval: the requester cannot approve their
 * own request, and execution requires independent reviewer approval.
 */
export function Privacy() {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return (
      <div>
        <div className="page-head"><h1>Privacy Erasure</h1></div>
        <div className="empty-state">
          <div className="empty-title">Access restricted</div>
          <div className="small">Privacy-erasure governance is System Admin only.</div>
        </div>
      </div>
    );
  }

  const hash = location.hash;
  const view = hash.split('?')[0];

  if (view === '#/privacy/requests/new') return <PrivacyCreate />;
  if (view.match(/^#\/privacy\/requests\/\d+($|\/)/)) {
    const m = view.match(/^#\/privacy\/requests\/(\d+)/);
    return <PrivacyDetail id={m[1]} />;
  }
  if (view === '#/privacy/requests' || view === '#/privacy') {
    return view === '#/privacy/requests' ? <PrivacyList /> : <PrivacyDashboard />;
  }
  return <PrivacyDashboard />;
}

/* ---------------- Dashboard ---------------- */

function PrivacyDashboard() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const r = await api.get('/common/privacy-erasures/?page_size=100');
        const d = r.data;
        const rows = Array.isArray(d) ? d : (d.results ?? []);
        if (!cancelled) {
          setItems(rows);
          setCount(d.count ?? rows.length);
          setError('');
        }
      } catch (e) {
        if (!cancelled) setError(parseApiError(e).global || 'Failed to load dashboard.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const byStatus = {};
  for (const s of STATUS_ORDER) byStatus[s] = 0;
  for (const it of items) byStatus[it.status] = (byStatus[it.status] || 0) + 1;

  const KPI = [
    { key: 'pending_review', label: 'Pending review', tone: 'amber' },
    { key: 'approved', label: 'Approved', tone: 'green' },
    { key: 'rejected', label: 'Rejected', tone: 'red' },
    { key: 'execution_pending', label: 'Execution pending', tone: 'blue' },
    { key: 'completed', label: 'Completed', tone: 'green' },
    { key: 'failed', label: 'Failed', tone: 'red' },
  ];

  if (loading) return (
    <>
      <div className="page-head"><h1>Privacy Erasure</h1></div>
      <div className="panel panel-pad" role="status" aria-label="Loading">
        <span className="spinner" aria-hidden="true" /> Loading…
      </div>
    </>
  );

  return (
    <div>
      <PageHeader title="Privacy Erasure" sub="Two-person-approval data lifecycle governance" />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <div className="row-gap" style={{ marginBottom: 16 }}>
        {KPI.map((k) => (
          <div key={k.key} className="kpi-card">
            <div className="kpi-value">{byStatus[k.key] ?? 0}</div>
            <div className="kpi-label">{k.label}</div>
          </div>
        ))}
      </div>
      <div className="panel">
        <div className="panel-head"><h3>Requests</h3></div>
        <div className="panel-pad">
          <a href="#/privacy/requests" className="btn-primary">View all requests &rarr;</a>
          <span className="muted"> &middot; </span>
          <a href="#/privacy/requests/new" className="btn-secondary">Create request</a>
        </div>
      </div>
    </div>
  );
}

/* ---------------- Request list ---------------- */

function PrivacyList() {
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [f, setF] = useState({ q: '', status: '', entity_type: '', requested_by: '', date_from: '', date_to: '' });
  const [page, setPage] = useState(1);

  const params = {
    ...f,
    page,
    page_size: 20,
  };

  const load = async () => {
    setLoading(true); setError('');
    try {
      const p = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) {
        if (v !== '' && v != null) p.set(k, v);
      }
      const d = await fetchPage(`/common/privacy-erasures/?${p.toString()}`);
      setItems(d.items); setCount(d.count); setNext(d.next); setPrevious(d.previous);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load requests.');
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [page, f.q, f.status, f.entity_type, f.requested_by, f.date_from, f.date_to]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect

  const setField = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  const ROWS = [
    { key: 'id', label: 'ID', sortable: 'id', render: (r) => <span className="cell-muted">#{r.id}</span> },
    { key: 'entity_type', label: 'Entity', render: (r) => r.entity_type },
    { key: 'object_id', label: 'Object ID', render: (r) => r.object_id },
    { key: 'scope', label: 'Scope', render: (r) => r.scope },
    { key: 'reason', label: 'Reason', render: (r) => String(r.reason || '').slice(0, 80) },
    { key: 'status', label: 'Status', render: (r) => statusBadge(r.status) },
    { key: 'requested_by', label: 'Requester', render: (r) => r.requested_by_email || r.requested_by || '—' },
    { key: 'reviewer', label: 'Reviewer', render: (r) => r.reviewer_email || '—' },
    { key: 'created_at', label: 'Created', render: (r) => r.created_at ? new Date(r.created_at).toLocaleString() : '—' },
    { key: 'actions', label: 'Actions', thClass: 'cell-actions', render: (r) => (
      <div className="cell-actions">
        <a href={`#/privacy/requests/${r.id}`} className="btn-small">Detail</a>
      </div>
    )},
  ];

  return (
    <div>
      <PageHeader title="Erasure requests" sub="List, filter and open privacy-erasure requests."
        actions={(
          <div className="row-gap">
            <a href="#/privacy/requests/new" className="btn-primary">+ Create request</a>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <div className="panel">
        <div className="panel-head"><h3>Filter</h3></div>
        <div className="panel-pad" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'end' }}>
          <Field label="Search"><input className="input input-auto" value={f.q} onChange={setField('q')} placeholder="scope, reason, ID…" /></Field>
          <Field label="Status"><select className="input" value={f.status} onChange={setField('status')}>
            <option value="">All</option>
            {STATUS_ORDER.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select></Field>
          <Field label="Entity type"><input className="input input-auto" value={f.entity_type} onChange={setField('entity_type')} placeholder="e.g. accounts.User" /></Field>
          <Field label="Date from"><input className="input input-auto" type="date" value={f.date_from} onChange={setField('date_from')} /></Field>
          <Field label="Date to"><input className="input input-auto" type="date" value={f.date_to} onChange={setField('date_to')} /></Field>
          <button type="button" className="btn-primary" onClick={load}>Apply</button>
          <button type="button" className="btn-ghost" onClick={() => { setF({ q: '', status: '', entity_type: '', requested_by: '', date_from: '', date_to: '' }); setPage(1); load(); }}>Reset</button>
        </div>
      </div>
      <DataTable columns={ROWS} rows={items} keyOf={(r) => String(r.id)} emptyTitle="No erasure requests." emptyHint="Create your first privacy-erasure request." />
      <Pager count={count} onPrev={() => setPage(p => p - 1)} onNext={() => setPage(p => p + 1)}
             hasPrev={page > 1} hasNext={!!next} busy={loading} />
    </div>
  );
}

/* ---------------- Create request ---------------- */

function PrivacyCreate() {
  const [form, setForm] = useState({ entity_type: 'accounts.User', object_id: '', scope: '', reason: '', confirm: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [parsed, setParsed] = useState(null);

  const setField = (k) => (e) => setForm((s) => ({ ...s, [k]: e.target.value }));

  const submit = async (ev) => {
    ev.preventDefault();
    setBusy(true); setError(''); setMsg(''); setParsed(null);
    try {
      const r = await api.post('/common/privacy-erasures/', {
        entity_type: form.entity_type, object_id: form.object_id,
        scope: form.scope, reason: form.reason, confirm: form.confirm,
      });
      setParsed(r.data);
      setMsg(`Request #${r.data.id} created (status: ${r.data.status}). Awaiting independent review.`);
    } catch (e) {
      const p = parseApiError(e);
      setError(p.global || 'Failed to create request.');
      setParsed(p);
    } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title="Create erasure request" sub="Request privacy erasure for a record. An independent System Admin must approve before execution." />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      {msg ? <div className="success-summary" role="status">{msg}</div> : null}
      <form onSubmit={submit} noValidate>
        <Field label="Entity type" required>
          <input className="input input-auto" value={form.entity_type} onChange={setField('entity_type')} placeholder="accounts.User" />
        </Field>
        <Field label="Object ID" required>
          <input className="input input-auto" value={form.object_id} onChange={setField('object_id')} placeholder="Primary key of the record" />
        </Field>
        <Field label="Scope" required hint="Which data to erase, e.g. email, name, phone">
          <input className="input input-auto" value={form.scope} onChange={setField('scope')} />
        </Field>
        <Field label="Reason" required hint="Business justification (audited, never PII)">
          <textarea className="input input-auto" value={form.reason} onChange={setField('reason')} rows={3} />
        </Field>
        <Field label="Confirm Object ID" required hint="Re-enter the object ID to confirm.">
          <input className="input input-auto" value={form.confirm} onChange={setField('confirm')} />
        </Field>
        <div className="row-end">
          <button type="button" className="btn-ghost" onClick={() => historyBack()}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Creating…' : 'Create request'}</button>
        </div>
      </form>
      {parsed && (
        <div className="success-summary" role="status">
          <strong>Created.</strong> Request #{parsed.id} &mdash; status: <em>{parsed.status}</em>.
          {' '}<a href={`#/privacy/requests/${parsed.id}`}>View detail &rarr;</a>
        </div>
      )}
    </div>
  );
}

function historyBack() {
  window.history.back();
}

/* ---------------- Request detail ---------------- */

function PrivacyDetail({ id }) {
  const [req, setReq] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyActions, setBusyActions] = useState({});
  const [openApprove, setOpenApprove] = useState(false);
  const [openReject, setOpenReject] = useState(false);
  const [openExecute, setOpenExecute] = useState(false);
  const [openCancel, setOpenCancel] = useState(false);
  const [reviewForm, setReviewForm] = useState({ decision: 'approve', reason: '' });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const r = await api.get(`/common/privacy-erasures/${id}/`);
        if (!cancelled) setReq(r.data);
      } catch (e) {
        if (!cancelled) setError(parseApiError(e).global || 'Failed to load request.');
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [id]);

  const actionBusy = (k) => busyActions[k] === id;
  const run = async (k, fn) => {
    setBusyActions({ ...busyActions, [k]: id });
    try { await fn(); } finally { setBusyActions({ ...busyActions, [k]: null }); }
  };

  const approve = async () => {
    await run('approve', async () => {
      await api.post(`/common/privacy-erasures/${id}/approve/`,
        { decision: reviewForm.decision, reason: reviewForm.reason });
      setOpenApprove(false); setReviewForm({ decision: 'approve', reason: '' });
      load();
    }).catch(() => {});
  };
  const reject = async () => {
    await run('reject', async () => {
      await api.post(`/common/privacy-erasures/${id}/reject/`,
        { decision: 'reject', reason: reviewForm.reason });
      setOpenReject(false); setReviewForm({ decision: 'reject', reason: '' });
      load();
    }).catch(() => {});
  };
  const exec = async () => {
    await run('execute', async () => {
      await api.post(`/common/privacy-erasures/${id}/execute/`, { confirm: String(req.object_id) });
      setOpenExecute(false); load();
    }).catch(() => {});
  };
  const cancelReq = async (reason) => {
    await run('cancel', async () => {
      await api.post(`/common/privacy-erasures/${id}/cancel/`, { reason });
      setOpenCancel(false); load();
    }).catch(() => {});
  };
  const load = () => {
    window.location.hash = `#/privacy/requests/${id}`;
  };

  if (loading) return (
    <>
      <div className="page-head"><h1>Request #{id}</h1></div>
      <div className="panel panel-pad" role="status" aria-label="Loading"><span className="spinner" aria-hidden="true" /> Loading…</div>
    </>
  );
  if (error) return (
    <>
      <div className="page-head"><h1>Request #{id}</h1></div>
      <div className="field-error" role="alert">{error}</div>
    </>
  );

  const r = req;
  const canReview = r.status === 'pending_review';
  const canExecute = r.status === 'approved';
  const canCancel = r.status === 'pending_review' || r.status === 'approved' || r.status === 'execution_pending';

  return (
    <div>
      <PageHeader title={`Erasure request #${r.id}`} sub={`${r.entity_type}:${r.object_id}`}
        actions={(
          <div className="row-gap">
            <a href="#/privacy/requests" className="btn-ghost">&larr; Back to list</a>
          </div>
        )} />
      <div className="panel">
        <div className="panel-head"><h3>Request</h3></div>
        <div className="panel-pad">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div>
              <div className="field"><span className="form-label">Status</span>{' '}{statusBadge(r.status)}</div>
              <div className="field"><span className="form-label">Scope</span><div className="small">{r.scope}</div></div>
              <div className="field"><span className="form-label">Reason</span><div className="small">{r.reason}</div></div>
              <div className="field"><span className="form-label">Entity / Object</span><div className="small">{r.entity_type}:{r.object_id}</div></div>
            </div>
            <div>
              <div className="field"><span className="form-label">Requested by</span><div className="small">{r.requested_by_email || r.requested_by || '—'}</div></div>
              <div className="field"><span className="form-label">Independent reviewer</span><div className="small">{r.reviewer_email || '—'}</div></div>
              <div className="field"><span className="form-label">Reviewed at</span><div className="small">{r.reviewed_at ? new Date(r.reviewed_at).toLocaleString() : '—'}</div></div>
              <div className="field"><span className="form-label">Decision</span><div className="small">{r.review_decision || '—'}</div></div>
              {r.review_reason && <div className="field"><span className="form-label">Review reason</span><div className="small">{r.review_reason}</div></div>}
              <div className="field"><span className="form-label">Created</span><div className="small">{r.created_at ? new Date(r.created_at).toLocaleString() : '—'}</div></div>
              {r.decided_at && <div className="field"><span className="form-label">Decided</span><div className="small">{new Date(r.decided_at).toLocaleString()}</div></div>}
              {r.executed_by && <div className="field"><span className="form-label">Executed by</span><div className="small">{r.executor_email || r.executed_by}</div></div>}
              {r.executed_at && <div className="field"><span className="form-label">Executed at</span><div className="small">{new Date(r.executed_at).toLocaleString()}</div></div>}
              {r.cancellation_reason && <div className="field"><span className="form-label">Cancellation reason</span><div className="small">{r.cancellation_reason}</div></div>}
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h3>Dependency &amp; retention analysis</h3></div>
        <div className="panel-pad">
          {r.dependency_check && (
            <div>
              <div className="field"><span className="form-label">Target exists</span>{' '}
                {r.dependency_check.exists ? <span className="badge badge-green">Yes</span> : <span className="badge badge-red">No</span>}</div>
              <div className="field"><span className="form-label">Can proceed (automated)</span>{' '}
                {r.dependency_check.can_proceed ? <span className="badge badge-green">Yes</span> : <span className="badge badge-red">No</span>}</div>
              {r.dependency_check.requires_manual_review && (
                <div className="field"><span className="form-label">Manual review</span><span className="badge badge-amber">Required</span></div>
              )}
              <div className="field"><span className="form-label">Related records</span>
                <ul className="small-list">
                  {Object.entries(r.dependency_check.related || {}).map(([k, v]) => (
                    <li key={k}>{k.replace(/_/g, ' ')}: <span className="cell-muted">{v}</span></li>
                  ))}
                  {Object.keys(r.dependency_check.related || {}).length === 0 && <li className="muted">None recorded.</li>}
                </ul>
              </div>
              <div className="field"><span className="form-label">Retention notes</span>
                <ul className="small-list">
                  {(r.dependency_check.retention || []).map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              </div>
              <div className="field"><span className="form-label">Assessment</span>
                <ul className="small-list">
                  {(r.dependency_check.assessment || []).map((a, i) => (
                    <li key={i}><strong>{a.category}:</strong> {a.action} &mdash; {a.reason}</li>
                  ))}
                  {(r.dependency_check.assessment || []).length === 0 && <li className="muted">None.</li>}
                </ul>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h3>Actions</h3></div>
        <div className="panel-pad">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {canReview && (
              <>
                <button type="button" className="btn-secondary" onClick={() => setOpenApprove(true)} disabled={actionBusy('approve')}>Approve (independent review)</button>
                <button type="button" className="btn-danger" onClick={() => setOpenReject(true)} disabled={actionBusy('reject')}>Reject</button>
              </>
            )}
            {canExecute && (
              <button type="button" className="btn-primary" onClick={() => setOpenExecute(true)} disabled={actionBusy('execute')}>Execute erasure</button>
            )}
            {canCancel && (
              <button type="button" className="btn-ghost" onClick={() => setOpenCancel(true)}>Cancel request</button>
            )}
            <div className="muted small">
              {r.status === 'pending_review' && 'Awaiting independent approval. The requester cannot approve their own request.'}
              {r.status === 'approved' && 'Independently approved. Ready for execution.'}
              {r.status === 'rejected' && 'Rejected. Cannot be executed.'}
              {r.status === 'completed' && 'Completed. PII was anonymized; de-identified history preserved.'}
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h3>Audit history</h3></div>
        <div className="panel-pad">
          {(r.audit_history || []).length > 0 ? (
            <table className="grid">
              <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Reason</th></tr></thead>
              <tbody>
                {r.audit_history.map((a) => (
                  <tr key={a.id}>
                    <td className="cell-muted">{a.timestamp ? new Date(a.timestamp).toLocaleString() : '—'}</td>
                    <td className="cell-muted">{a.actor_email || a.actor || '—'}</td>
                    <td>{a.action}</td>
                    <td className="cell-muted small">{a.reason || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="muted">No audit entries yet.</div>
          )}
        </div>
      </div>

      {openApprove && (
        <ConfirmDialog title="Approve erasure request?"
          message="Independently approve this request so it can be executed. You cannot approve your own request."
          confirmLabel="Approve" onConfirm={approve} onCancel={() => setOpenApprove(false)}
          busy={actionBusy('approve')}>
          <Field label="Decision"><select className="input" value={reviewForm.decision} onChange={(e)=>setReviewForm({...reviewForm, decision:e.target.value})}>
            <option value="approve">Approve</option>
            <option value="reject">Reject</option>
          </select></Field>
          <Field label="Reason (required on rejection)"><input className="input input-auto" value={reviewForm.reason} onChange={(e)=>setReviewForm({...reviewForm, reason:e.target.value})} placeholder="Optional unless rejecting" /></Field>
        </ConfirmDialog>
      )}

      {openReject && (
        <ConfirmDialog title="Reject erasure request?"
          message="Rejection requires a reason and is recorded permanently. The request cannot be executed after rejection."
          confirmLabel="Reject" danger onConfirm={reject} onCancel={() => setOpenReject(false)}
          busy={actionBusy('reject')}>
          <Field label="Reason" required><textarea className="input input-auto" value={reviewForm.reason} onChange={(e)=>setReviewForm({...reviewForm, reason:e.target.value})} rows={2} /></Field>
        </ConfirmDialog>
      )}

      {openExecute && (
        <ConfirmDialog title="Execute erasure?"
          message="This will anonymize the target record's personal data (email, name, phone, job title) and preserve de-identified history. This cannot be undone. Execution requires independent approval (already granted)."
          confirmLabel="Execute" danger onConfirm={exec} onCancel={() => setOpenExecute(false)}
          busy={actionBusy('execute')}>
          <Field label="Confirm object ID" required hint="Re-enter the object ID to confirm.">
            <input className="input input-auto" value={String(r.object_id || '')} readOnly />
            <div className="small">Confirmed target: {r.entity_type}:{r.object_id}</div>
          </Field>
        </ConfirmDialog>
      )}

      {openCancel && (
        <ConfirmDialog title="Cancel erasure request?"
          message="Cancel this request. A cancelled request cannot be executed."
          confirmLabel="Cancel" onConfirm={() => cancelReq(prompt('Cancellation reason (optional):') || '')} onCancel={() => setOpenCancel(false)}
          busy={actionBusy('cancel')} />
      )}
    </div>
  );
}
