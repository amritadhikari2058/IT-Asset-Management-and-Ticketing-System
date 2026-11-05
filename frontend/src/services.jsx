import { useCallback, useEffect, useState } from 'react';
import { useAuth } from './auth';
import api from './api';
import { fetchPage, parseApiError } from './api-utils';
import {
  Badge, ConfirmDialog, DataTable, EmptyState, Field, Modal, PageHeader, Pager, UserSelect,
} from './components';

const PRIORITIES = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'urgent', label: 'Urgent' },
];

/** Coerce an API page payload into rows across DRF page / plain list shapes. */
function rowsOf(payload) {
  const d = payload?.data ?? payload;
  if (Array.isArray(d)) return d;
  return d?.results ?? d?.data ?? [];
}

/** Simple paginated loader shared by the staff queues below. */
function usePagedLoader(base) {
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const loadUrl = useCallback(async (url) => {
    setLoading(true);
    setError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
    } catch {
      setError('Could not load.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { loadUrl(base); }, [base, loadUrl]);
  return { items, setItems, count, next, previous, loading, error, loadUrl };
}

function CatalogueCard({ item, onRequest, staff, onEdit, onToggleActive, onDelete }) {
  return (
    <div className="panel" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="panel-pad" style={{ flex: 1 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <strong>{item.name}</strong>
          <Badge kind="status" value="open" label={item.category || 'other'} />
          {!item.is_active && <Badge kind="status" value="inactive" label="Inactive" />}
          {item.requires_approval && <Badge kind="status" value="pending" label="Approval required" />}
          {item.creates_ticket && <Badge kind="status" value="scheduled" label="Creates ticket" />}
        </div>
        <p className="muted" style={{ marginTop: 8 }}>{item.description || 'No description.'}</p>
        {item.instructions && <p className="small" style={{ marginTop: 8 }}>{item.instructions}</p>}
        {item.estimated_fulfilment_hours != null && (
          <div className="small muted">Est. fulfilment: {item.estimated_fulfilment_hours}h</div>
        )}
      </div>
      <div className="panel-pad" style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button type="button" className="btn-primary" onClick={() => onRequest(item)} disabled={!item.is_active}>
          Request
        </button>
        {staff && (
          <>
            <button type="button" className="btn-small" onClick={() => onEdit(item)}>Edit…</button>
            <button type="button" className="btn-small" onClick={() => onToggleActive(item)}>
              {item.is_active ? 'Deactivate' : 'Activate'}
            </button>
            <button type="button" className="btn-small btn-danger" onClick={() => onDelete(item)}>Delete…</button>
          </>
        )}
      </div>
    </div>
  );
}

export function ServicesCatalogue() {
  const { isStaff } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');

  const [showRequest, setShowRequest] = useState(null); // catalogue item
  const [reqForm, setReqForm] = useState({ description: '', priority: 'medium', answers: {} });
  const [reqBusy, setReqBusy] = useState(false);
  const [reqError, setReqError] = useState('');

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [catForm, setCatForm] = useState({ name: '', description: '', category: 'other', is_active: true, requires_approval: false, creates_ticket: false, estimated_fulfilment_hours: '', instructions: '' });
  const [catBusy, setCatBusy] = useState(false);
  const [catError, setCatError] = useState('');

  const [delFor, setDelFor] = useState(null);
  const [delBusy, setDelBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const r = await api.get('/services/catalogue/');
      setItems(rowsOf(r));
    } catch {
      setError('Could not load the service catalogue.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const visible = isStaff ? items : items.filter((i) => i.is_active);

  const openRequest = (item) => {
    setShowRequest(item);
    setReqForm({ description: '', priority: 'medium', answers: {} });
    setReqError('');
  };
  const setAnswer = (k, v) => setReqForm((p) => ({ ...p, answers: { ...p.answers, [k]: v } }));
  const setReqField = (k) => (e) => setReqForm((p) => ({ ...p, [k]: e.target.value }));

  const submitRequest = async (ev) => {
    ev.preventDefault();
    if (reqBusy || !showRequest) return;
    setReqBusy(true);
    setReqError('');
    try {
      const r = await api.post('/services/requests/', {
        catalogue_item: showRequest.id,
        description: reqForm.description.trim(),
        priority: reqForm.priority,
        answers: reqForm.answers,
      });
      setMsg(`Submitted ${r.data.request_number || 'request'}.`);
      setShowRequest(null);
    } catch (e) {
      setReqError(parseApiError(e).global || 'Could not submit request.');
    } finally {
      setReqBusy(false);
    }
  };

  const openForm = (item = null) => {
    setEditing(item ? { id: item.id } : null);
    setCatForm(item ? {
      name: item.name ?? '', description: item.description ?? '', category: item.category ?? 'other',
      is_active: !!item.is_active, requires_approval: !!item.requires_approval,
      creates_ticket: !!item.creates_ticket,
      estimated_fulfilment_hours: item.estimated_fulfilment_hours ?? '',
      instructions: item.instructions ?? '',
    } : { name: '', description: '', category: 'other', is_active: true, requires_approval: false, creates_ticket: false, estimated_fulfilment_hours: '', instructions: '' });
    setCatError('');
    setShowForm(true);
  };
  const setCat = (k) => (e) => setCatForm((p) => ({ ...p, [k]: e?.target?.value ?? e }));
  const setCatCheck = (k) => (e) => setCatForm((p) => ({ ...p, [k]: e.target.checked }));

  const saveCatalogue = async (ev) => {
    ev.preventDefault();
    if (catBusy) return;
    setCatBusy(true);
    setCatError('');
    const payload = {
      name: catForm.name.trim(),
      description: catForm.description.trim(),
      category: catForm.category,
      is_active: catForm.is_active === true || catForm.is_active === 'true',
      requires_approval: catForm.requires_approval === true || catForm.requires_approval === 'true',
      creates_ticket: catForm.creates_ticket === true || catForm.creates_ticket === 'true',
      estimated_fulfilment_hours: catForm.estimated_fulfilment_hours === '' ? null : Number(catForm.estimated_fulfilment_hours),
      instructions: catForm.instructions.trim(),
    };
    if (!payload.name) {
      setCatError('Name is required.');
      setCatBusy(false);
      return;
    }
    const url = editing ? `/services/catalogue/${editing.id}/` : '/services/catalogue/';
    try {
      await api[editing ? 'patch' : 'post'](url, payload);
      setShowForm(false);
      setEditing(null);
      await load();
      setMsg(editing ? 'Service updated.' : 'Service created.');
    } catch (e) {
      setCatError(parseApiError(e).global || 'Could not save service.');
    } finally {
      setCatBusy(false);
    }
  };

  const toggleActive = async (item) => {
    try {
      await api.patch(`/services/catalogue/${item.id}/`, { is_active: !item.is_active });
      await load();
      setMsg(`"${item.name}" ${item.is_active ? 'deactivated' : 'activated'}.`);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not update service.');
    }
  };

  const doDelete = async (item) => {
    if (!item) return;
    setDelBusy(true);
    try {
      await api.delete(`/services/catalogue/${item.id}/`);
      setItems(items.filter((r) => r.id !== item.id));
      setMsg(`"${item.name}" deleted.`);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not delete service.');
    } finally {
      setDelBusy(false);
      setDelFor(null);
    }
  };

  if (loading) return <div className="panel-pad"><div className="muted">Loading…</div></div>;

  return (
    <div>
      <PageHeader
        title="Service Catalogue"
        sub={`${visible.length} service${visible.length === 1 ? '' : 's'} available.`}
        actions={isStaff ? <button type="button" className="btn-primary" onClick={() => openForm()} disabled={catBusy}>+ New service</button> : null}
      />
      {error && <div className="error-summary" role="alert">{error}</div>}
      {msg && <div className="success-summary" role="status">{msg}</div>}
      {visible.length === 0 ? (
        <EmptyState title="No services available." hint={isStaff ? 'Create your first service with + New service.' : 'Ask IT staff to publish services.'} />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
          {visible.map((item) => (
            <CatalogueCard key={item.id} item={item} onRequest={openRequest} staff={isStaff}
              onEdit={openForm} onToggleActive={toggleActive} onDelete={setDelFor} />
          ))}
        </div>
      )}

      {showRequest && (
        <Modal title={`Request: ${showRequest.name}`} onClose={() => setShowRequest(null)} size="wide">
          <form onSubmit={submitRequest} noValidate>
            {Array.isArray(showRequest.form_fields) && showRequest.form_fields.length > 0 && (
              <>
                <Field label="Details">{''}</Field>
                {showRequest.form_fields.map((fld, idx) => {
                  const key = fld.key || fld.name || `field_${idx}`;
                  const label = fld.label || fld.name || key;
                  const required = !!fld.required;
                  const value = reqForm.answers[key] ?? '';
                  const common = {
                    className: 'input',
                    value,
                    disabled: reqBusy,
                    'aria-label': label,
                    onChange: (e) => setAnswer(key, e.target.value),
                  };
                  return (
                    <Field key={key} label={label} required={required}>
                      {fld.type === 'textarea'
                        ? <textarea rows={3} {...common} />
                        : fld.type === 'select' && Array.isArray(fld.options)
                          ? (
                            <select {...common}>
                              <option value="">Select…</option>
                              {fld.options.map((o) => <option key={String(o.value ?? o)} value={String(o.value ?? o)}>{o.label ?? o}</option>)}
                            </select>
                          )
                          : <input {...common} type={fld.type === 'number' ? 'number' : 'text'} />}
                    </Field>
                  );
                })}
              </>
            )}
            <Field label="Description">
              <textarea className="input" rows={3} value={reqForm.description} onChange={setReqField('description')}
                placeholder="What do you need?" disabled={reqBusy} />
            </Field>
            <Field label="Priority" required>
              <select className="input" value={reqForm.priority} onChange={setReqField('priority')} disabled={reqBusy}>
                {PRIORITIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </Field>
            {reqError && <div className="error-summary" role="alert">{reqError}</div>}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setShowRequest(null)} disabled={reqBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={reqBusy}>
                {reqBusy ? 'Submitting…' : 'Submit request'}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {showForm && (
        <Modal title={editing ? 'Edit service' : 'New service'} onClose={() => setShowForm(false)} size="wide">
          <form onSubmit={saveCatalogue} noValidate>
            <Field label="Name" required error={catError}>
              <input className="input" value={catForm.name} onChange={setCat('name')} disabled={catBusy} maxLength={120} />
            </Field>
            <Field label="Category" required>
              <select className="input" value={catForm.category} onChange={setCat('category')} disabled={catBusy}>
                {['hardware', 'software', 'account', 'access', 'network', 'email', 'onboarding', 'other'].map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </Field>
            <Field label="Description">
              <textarea className="input" rows={3} value={catForm.description} onChange={setCat('description')} disabled={catBusy} />
            </Field>
            <Field label="Instructions">
              <textarea className="input" rows={3} value={catForm.instructions} onChange={setCat('instructions')} disabled={catBusy} />
            </Field>
            <Field label="Estimated fulfilment (hours)">
              <input className="input" type="number" min="0" value={catForm.estimated_fulfilment_hours}
                onChange={setCat('estimated_fulfilment_hours')} disabled={catBusy} />
            </Field>
            <Field label="Flags">
              <label className="check-row">
                <input type="checkbox" checked={catForm.is_active === true || catForm.is_active === 'true'} onChange={setCatCheck('is_active')} disabled={catBusy} />
                Active (visible to employees)
              </label>
              <label className="check-row">
                <input type="checkbox" checked={catForm.requires_approval === true || catForm.requires_approval === 'true'} onChange={setCatCheck('requires_approval')} disabled={catBusy} />
                Requires approval
              </label>
              <label className="check-row">
                <input type="checkbox" checked={catForm.creates_ticket === true || catForm.creates_ticket === 'true'} onChange={setCatCheck('creates_ticket')} disabled={catBusy} />
                Creates a fulfilment ticket
              </label>
            </Field>
            {catError && <div className="error-summary" role="alert">{catError}</div>}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setShowForm(false)} disabled={catBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={catBusy || !catForm.name.trim()}>
                {catBusy ? 'Saving…' : (editing ? 'Save changes' : 'Create service')}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {delFor && (
        <ConfirmDialog
          title={`Delete service "${delFor.name}"?`}
          message="This soft-deletes the catalogue item. Existing requests are kept."
          confirmLabel="Delete service" danger busy={delBusy}
          onConfirm={() => doDelete(delFor)} onCancel={() => setDelFor(null)}
        />
      )}
    </div>
  );
}

export function MyServiceRequests() {
  const { isStaff } = useAuth();
  const { items, count, next, previous, loading, error, loadUrl } = usePagedLoader('/services/requests/');

  const columns = [
    { key: 'number', label: 'Number', render: (r) => <a href={`#/service-requests/${r.id}`}>{r.request_number}</a> },
    { key: 'service', label: 'Service', render: (r) => <span className="row-title">{r.catalogue_item_name || '—'}</span> },
    { key: 'status', label: 'Status', render: (r) => <Badge kind="status" value={r.status} /> },
    { key: 'priority', label: 'Priority', render: (r) => <Badge kind="priority" value={r.priority} /> },
    ...(isStaff ? [{ key: 'requester', label: 'Requester', render: (r) => <span className="ellipsis">{r.requester_name || r.requester}</span> }] : []),
    { key: 'submitted', label: 'Submitted', render: (r) => (r.submitted_at ? new Date(r.submitted_at).toLocaleDateString() : '—') },
  ];

  return (
    <div>
      <PageHeader title={isStaff ? 'Service requests' : 'My Service Requests'}
        sub={count != null ? `${count} request${count === 1 ? '' : 's'}` : undefined}
        actions={<a className="btn-primary" href="#/services">Browse catalogue</a>}
      />
      {error && <div className="error-summary" role="alert">{error}</div>}
      <div className="panel">
        {loading ? <div className="panel-pad"><div className="muted">Loading…</div></div>
          : count === 0 ? <EmptyState title="No service requests yet." hint="Request something from the Service Catalogue." />
          : (
            <>
              <DataTable columns={columns} rows={items} keyOf={(r) => r.id}
                emptyTitle="No requests match." emptyHint="Adjust the filters." />
              <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading}
                onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />
            </>
          )}
      </div>
    </div>
  );
}

export function ServiceRequestDetail({ id }) {
  const { isStaff } = useAuth();
  const [req, setReq] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(null);

  const [commentBody, setCommentBody] = useState('');
  const [commentInternal, setCommentInternal] = useState(false);

  const [assignOpen, setAssignOpen] = useState(false);
  const [assignUser, setAssignUser] = useState('');

  const [decisionOpen, setDecisionOpen] = useState(null); // 'approve' | 'reject'
  const [reason, setReason] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const r = await api.get(`/services/requests/${id}/`);
      setReq(r.data);
    } catch {
      setError('Could not load this request.');
    } finally {
      setLoading(false);
    }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const act = async (url, payload, done) => {
    setBusy(url);
    setError('');
    try {
      await api.post(url, payload ?? {});
      setMsg(done);
      await load();
    } catch (e) {
      setError(parseApiError(e).global || 'Action failed.');
    } finally {
      setBusy(null);
    }
  };

  const doCancel = () => act(`/services/requests/${id}/cancel/`, {}, `Request ${req.request_number} cancelled.`);
  const doApprove = () => act(`/services/requests/${id}/approve/`, { reason: reason.trim() }, `Request ${req.request_number} approved.`);
  const doReject = () => act(`/services/requests/${id}/reject/`, { reason: reason.trim() }, `Request ${req.request_number} rejected.`);
  const doAssign = () => act(`/services/requests/${id}/assign/`, { assigned_to: assignUser ? Number(assignUser) : null }, `Request ${req.request_number} assigned.`);
  const doComment = async (ev) => {
    ev.preventDefault();
    if (!commentBody.trim() || busy === 'comment') return;
    setBusy('comment');
    setError('');
    try {
      await api.post(`/services/requests/${id}/comment/`, {
        body: commentBody.trim(), is_internal: isStaff && commentInternal,
      });
      setCommentBody('');
      setCommentInternal(false);
      await load();
    } catch (e) {
      setError(parseApiError(e).global || 'Could not add comment.');
    } finally {
      setBusy(null);
    }
  };

  if (loading) return <div className="panel-pad"><div className="muted">Loading…</div></div>;
  if (!req) return (
    <div>
      <PageHeader title="Request" />
      {error && <div className="error-summary" role="alert">{error}</div>}
    </div>
  );

  const canCancel = !['fulfilled', 'cancelled', 'rejected'].includes(req.status);
  const canDecide = isStaff && req.status === 'pending_approval';
  const comments = Array.isArray(req.comments) ? req.comments : [];
  const history = Array.isArray(req.history) ? req.history : [];
  const visibleComments = isStaff ? comments : comments.filter((c) => !c.is_internal);

  return (
    <div>
      <PageHeader
        title={req.request_number}
        sub={`${req.catalogue_item_name || 'Service'} · ${req.status?.replace(/_/g, ' ')}`}
        actions={<a className="btn-small" href="#/service-requests">← All requests</a>}
      />
      {error && <div className="error-summary" role="alert">{error}</div>}
      {msg && <div className="success-summary" role="status">{msg}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
        <div>
          <div className="panel">
            <div className="panel-pad">
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                <Badge kind="status" value={req.status} />
                <Badge kind="priority" value={req.priority} />
                {req.approval_required && <Badge kind="status" value="pending" label="Approval required" />}
              </div>
              <dl className="detail-grid">
                <dt>Requester</dt><dd>{req.requester_name || req.requester}</dd>
                <dt>Department</dt><dd>{req.department ?? '—'}</dd>
                <dt>Assigned to</dt><dd>{req.assigned_to_name || req.assigned_to || 'Unassigned'}</dd>
                <dt>Submitted</dt><dd>{req.submitted_at ? new Date(req.submitted_at).toLocaleString() : '—'}</dd>
                {req.approved_at && <><dt>Decided</dt><dd>{new Date(req.approved_at).toLocaleString()}</dd></>}
                {req.approval_reason && <><dt>Decision note</dt><dd>{req.approval_reason}</dd></>}
                {req.fulfilment_ticket && <><dt>Fulfilment ticket</dt><dd>#{req.fulfilment_ticket}</dd></>}
                {req.fulfilment_details && <><dt>Fulfilment</dt><dd>{req.fulfilment_details}</dd></>}
              </dl>
              {req.description && <p style={{ marginTop: 8 }}>{req.description}</p>}
              {req.answers && typeof req.answers === 'object' && Object.keys(req.answers).length > 0 && (
                <>
                  <h4 style={{ marginTop: 12 }}>Answers</h4>
                  <dl className="detail-grid">
                    {Object.entries(req.answers).map(([k, v]) => (
                      <span key={k} style={{ display: 'contents' }}>
                        <dt>{k}</dt><dd>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
                      </span>
                    ))}
                  </dl>
                </>
              )}
            </div>
          </div>

          <div className="panel" style={{ marginTop: 12 }}>
            <div className="panel-head"><strong>Comments</strong></div>
            <div className="panel-pad">
              {visibleComments.length === 0
                ? <EmptyState title="No comments yet." />
                : (
                  <ul style={{ listStyle: 'none', padding: 0 }}>
                    {visibleComments.map((c) => (
                      <li key={c.id} style={{ marginBottom: 8 }}>
                        <span className="small muted">{c.author_name || c.author} · {c.created_at ? new Date(c.created_at).toLocaleString() : ''}{c.is_internal ? ' · Internal' : ''}</span>
                        <div>{c.body}</div>
                      </li>
                    ))}
                  </ul>
                )}
              <form onSubmit={doComment} noValidate style={{ marginTop: 8 }}>
                <Field label="Add a comment">
                  <textarea className="input" rows={2} value={commentBody}
                    onChange={(e) => setCommentBody(e.target.value)} disabled={busy === 'comment'} />
                </Field>
                {isStaff && (
                  <label className="check-row">
                    <input type="checkbox" checked={commentInternal}
                      onChange={(e) => setCommentInternal(e.target.checked)} disabled={busy === 'comment'} />
                    Internal note (hidden from the requester)
                  </label>
                )}
                <div className="row-end">
                  <button type="submit" className="btn-small" disabled={busy === 'comment' || !commentBody.trim()}>
                    {busy === 'comment' ? 'Posting…' : 'Post comment'}
                  </button>
                </div>
              </form>
            </div>
          </div>

          <div className="panel" style={{ marginTop: 12 }}>
            <div className="panel-head"><strong>History</strong></div>
            <div className="panel-pad">
              {history.length === 0 ? <EmptyState title="No history yet." /> : (
                <ul style={{ listStyle: 'none', padding: 0 }}>
                  {history.map((h) => (
                    <li key={h.id} className="small">
                      <strong>{h.event}</strong> — {h.detail || ''}{' '}
                      <span className="muted">{h.actor_name || h.actor || ''} · {h.created_at ? new Date(h.created_at).toLocaleString() : ''}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>

        <div>
          <div className="panel">
            <div className="panel-head"><strong>Actions</strong></div>
            <div className="panel-pad" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {canDecide && (
                <>
                  <button type="button" className="btn-primary" onClick={() => { setDecisionOpen('approve'); setReason(''); }}
                    disabled={busy === `/services/requests/${id}/approve/`}>Approve…</button>
                  <button type="button" className="btn-danger" onClick={() => { setDecisionOpen('reject'); setReason(''); }}
                    disabled={busy === `/services/requests/${id}/reject/`}>Reject…</button>
                </>
              )}
              {isStaff && (
                <button type="button" className="btn-small" onClick={() => setAssignOpen(true)}
                  disabled={busy === `/services/requests/${id}/assign/`}>Assign…</button>
              )}
              {canCancel && (
                <button type="button" className="btn-small btn-danger"
                  onClick={doCancel} disabled={busy === `/services/requests/${id}/cancel/`}>
                  {busy === `/services/requests/${id}/cancel/` ? 'Cancelling…' : 'Cancel request'}
                </button>
              )}
              {!canDecide && !isStaff && !canCancel && <span className="muted small">No actions available.</span>}
              {!canDecide && !isStaff && canCancel && <span className="muted small">You can cancel this request while it is open.</span>}
            </div>
          </div>
        </div>
      </div>

      {assignOpen && (
        <Modal title={`Assign ${req.request_number}`} onClose={() => setAssignOpen(false)}>
          <div className="panel-pad">
            <Field label="Assign to (staff user)">
              <UserSelect value={assignUser} onChange={setAssignUser} />
            </Field>
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setAssignOpen(false)}>Cancel</button>
              <button type="button" className="btn-primary" onClick={async () => { await doAssign(); setAssignOpen(false); }}
                disabled={busy === `/services/requests/${id}/assign/`}>
                {busy === `/services/requests/${id}/assign/` ? 'Assigning…' : 'Assign'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {decisionOpen && (
        <Modal title={`${decisionOpen === 'approve' ? 'Approve' : 'Reject'} ${req.request_number}`}
          onClose={() => setDecisionOpen(null)}>
          <form onSubmit={(ev) => { ev.preventDefault(); decisionOpen === 'approve' ? doApprove() : doReject(); setDecisionOpen(null); }} noValidate>
            <div className="panel-pad">
              <Field label="Reason (optional)">
                <textarea className="input" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
              </Field>
              <div className="row-end">
                <button type="button" className="btn-ghost" onClick={() => setDecisionOpen(null)}>Cancel</button>
                <button type="submit" className={decisionOpen === 'approve' ? 'btn-primary' : 'btn-danger'}
                  disabled={busy === `/services/requests/${id}/${decisionOpen}/`}>
                  {decisionOpen === 'approve' ? 'Approve request' : 'Reject request'}
                </button>
              </div>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
