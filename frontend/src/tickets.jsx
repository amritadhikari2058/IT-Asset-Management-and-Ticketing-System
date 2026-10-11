import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  AssetSelect, CategorySelect, ConfirmDialog, DepartmentSelect, ErrorSummary,
  Field, UserSelect, fieldMsg, parseApiError,
} from './components';

const PRIORITIES = ['low', 'medium', 'high', 'critical'];
const STATUSES = ['open', 'in_progress', 'resolved', 'closed', 'reopened', 'archived'];

export function TicketForm({ id }) {
  const { user, isStaff, canCreateTickets } = useAuth();
  const isEdit = !!id;
  const [loading, setLoading] = useState(isEdit);
  const [loadError, setLoadError] = useState('');
  const [form, setForm] = useState({
    title: '', description: '', priority: 'medium', category: '',
    department: '', on_behalf_reason: '', asset: '', assignee: '', status: 'open',
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [okMsg, setOkMsg] = useState('');

  useEffect(() => {
    if (!isEdit) {
      if (user?.home_department) setForm((f) => ({ ...f, department: user.home_department }));
      return;
    }
    (async () => {
      setLoading(true);
      try {
        const r = await api.get(`/tickets/${id}/`);
        const t = r.data;
        setForm({
          title: t.title ?? '', description: t.description ?? '',
          priority: t.priority ?? 'medium', category: t.category ?? '',
          department: t.department ?? '', on_behalf_reason: t.on_behalf_reason ?? '',
          asset: t.asset ?? '', assignee: t.assignee ?? '', status: t.status ?? 'open',
        });
      } catch (e) {
        setLoadError(parseApiError(e).global || 'Could not load ticket.');
      } finally {
        setLoading(false);
      }
    })();
  }, [id, isEdit, user]);

  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const crossDept = user?.home_department && form.department && Number(form.department) !== Number(user.home_department);

  const submit = async (ev) => {
    ev.preventDefault();
    if (submitting) return;
    setFieldErrors({});
    setGlobalError('');
    setOkMsg('');
    const payload = {
      title: form.title.trim(),
      description: form.description.trim(),
      priority: form.priority,
      category: form.category === '' ? null : Number(form.category),
      department: form.department === '' ? null : Number(form.department),
    };
    if (!isEdit) {
      if (form.on_behalf_reason.trim()) payload.on_behalf_reason = form.on_behalf_reason.trim();
      if (form.asset !== '') payload.asset = Number(form.asset);
      if (isStaff && form.assignee !== '') payload.assignee = Number(form.assignee);
    } else {
      payload.on_behalf_reason = form.on_behalf_reason;
      payload.asset = form.asset === '' ? null : Number(form.asset);
      if (isStaff) {
        payload.assignee = form.assignee === '' ? null : Number(form.assignee);
        payload.status = form.status;
      }
    }
    setSubmitting(true);
    try {
      const res = isEdit
        ? await api.patch(`/tickets/${id}/`, payload)
        : await api.post('/tickets/', payload);
      setOkMsg(isEdit ? 'Ticket updated.' : 'Ticket created.');
      location.hash = `#/tickets/${res.data.id}`;
    } catch (e) {
      const p = parseApiError(e);
      setFieldErrors(p.fields);
      setGlobalError(p.global);
    } finally {
      setSubmitting(false);
    }
  };

  if (!isEdit && !canCreateTickets) {
    return (
      <div>
        <h3>New ticket</h3>
        <div className="error-summary" role="alert">
          Ticket creation is disabled for your account. Contact an administrator.
        </div>
        <p><a href="#/tickets">Back to tickets</a></p>
      </div>
    );
  }
  if (loading) return <p>Loading ticket…</p>;
  if (loadError) return (<div><div className="error-summary" role="alert">{loadError}</div><p><a href="#/tickets">Back to tickets</a></p></div>);

  return (
    <div className="form-wrap">
      <h3>{isEdit ? `Edit ticket #${id}` : 'New ticket'}</h3>
      <ErrorSummary parsed={{ global: globalError }} />
      {okMsg && <div className="success-summary" role="status">{okMsg}</div>}
      <form onSubmit={submit} noValidate>
        <Field label="Subject" required error={fieldMsg(fieldErrors, 'title')}>
          <input className="input" value={form.title} onChange={(e) => set('title')(e.target.value)} placeholder="Brief summary of the issue" disabled={submitting} maxLength={255} />
        </Field>
        <Field label="Description" required error={fieldMsg(fieldErrors, 'description')}>
          <textarea className="input" rows={5} value={form.description} onChange={(e) => set('description')(e.target.value)} placeholder="Steps to reproduce, impact, environment…" disabled={submitting} />
        </Field>
        <div className="form-grid">
          <Field label="Priority" required error={fieldMsg(fieldErrors, 'priority')}>
            <select className="input" value={form.priority} onChange={(e) => set('priority')(e.target.value)} disabled={submitting}>
              {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
          <Field label="Category" required error={fieldMsg(fieldErrors, 'category')}>
            <CategorySelect kind="ticket" value={form.category} onChange={set('category')} disabled={submitting} />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Department" error={fieldMsg(fieldErrors, 'department')} hint="Defaults to your home department.">
            <DepartmentSelect value={form.department} onChange={set('department')} disabled={submitting} />
          </Field>
          <Field label="Related asset (optional)" error={fieldMsg(fieldErrors, 'asset')}>
            <AssetSelect value={form.asset} onChange={set('asset')} disabled={submitting} />
          </Field>
        </div>
        {(crossDept || form.on_behalf_reason) && (
          <Field
            label="On-behalf-of reason"
            required={!!crossDept}
            error={fieldMsg(fieldErrors, 'on_behalf_reason')}
            hint="Required when filing for a department other than your own."
          >
            <textarea className="input" rows={2} value={form.on_behalf_reason} onChange={(e) => set('on_behalf_reason')(e.target.value)} disabled={submitting} />
          </Field>
        )}
        {isStaff && (
          <div className="form-grid">
            <Field label="Assignee" error={fieldMsg(fieldErrors, 'assignee')}>
              <UserSelect value={form.assignee} onChange={set('assignee')} disabled={submitting} />
            </Field>
            {isEdit && (
              <Field label="Status" error={fieldMsg(fieldErrors, 'status')} hint="Invalid transitions are rejected by the server.">
                <select className="input" value={form.status} onChange={(e) => set('status')(e.target.value)} disabled={submitting}>
                  {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </Field>
            )}
          </div>
        )}
        <div className="row-end">
          <a className="btn-ghost" href={isEdit ? `#/tickets/${id}` : '#/tickets'}>Cancel</a>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? 'Saving…' : isEdit ? 'Save changes' : 'Create ticket'}
          </button>
        </div>
      </form>
    </div>
  );
}

export function TicketDetail({ id }) {
  const { isStaff, user } = useAuth();
  const [ticket, setTicket] = useState(null);
  const [notes, setNotes] = useState([]);
  const [history, setHistory] = useState(null); // null = not permitted / not loaded
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [noteBody, setNoteBody] = useState('');
  const [noteInternal, setNoteInternal] = useState(false);
  const [noteBusy, setNoteBusy] = useState(false);
  const [noteError, setNoteError] = useState('');
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const t = (await api.get(`/tickets/${id}/`)).data;
      setTicket(t);
      try {
        setNotes((await api.get(`/tickets/${id}/notes/`)).data ?? []);
      } catch { setNotes([]); }
      try {
        const h = await api.get('/tickets/histories/', { params: { ticket: id } });
        setHistory(h.data.results ?? h.data ?? []);
      } catch { setHistory(null); }
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load ticket.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const addNote = async (ev) => {
    ev.preventDefault();
    if (noteBusy || !noteBody.trim()) return;
    setNoteBusy(true);
    setNoteError('');
    try {
      const r = await api.post(`/tickets/${id}/notes/`, {
        body: noteBody.trim(),
        is_internal: isStaff ? noteInternal : false,
      });
      setNotes((n) => [...n, r.data]);
      setNoteBody('');
    } catch (e) {
      setNoteError(parseApiError(e).global || 'Could not add note.');
    } finally {
      setNoteBusy(false);
    }
  };

  const doDelete = async () => {
    setDeleteBusy(true);
    try {
      await api.delete(`/tickets/${id}/`);
      location.hash = '#/tickets';
    } catch (e) {
      setError(parseApiError(e).global || 'Could not delete ticket.');
      setConfirmingDelete(false);
    } finally {
      setDeleteBusy(false);
    }
  };

  if (loading) return <p>Loading ticket…</p>;
  if (error && !ticket) return (<div><div className="error-summary" role="alert">{error}</div><p><a href="#/tickets">Back to tickets</a></p></div>);
  const t = ticket;
  return (
    <div className="detail-wrap">
      <p><a href="#/tickets">← Tickets</a></p>
      {error && <div className="error-summary" role="alert">{error}</div>}
      <div className="detail-head">
        <h3>#{t.id} {t.title}</h3>
        <div className="row-gap">
          <a className="btn-secondary" href={`#/tickets/${t.id}/edit`}>Edit</a>
          <button type="button" className="btn-danger" onClick={() => setConfirmingDelete(true)}>Delete…</button>
        </div>
      </div>
      <dl className="detail-grid">
        <dt>Status</dt><dd>{t.status}</dd>
        <dt>Priority</dt><dd>{t.priority}</dd>
        <dt>Category</dt><dd>{t.category_name ?? t.category}</dd>
        <dt>Department</dt><dd>{t.department_name ?? t.department ?? '—'}</dd>
        <dt>Requester</dt><dd>{t.requester_email ?? t.requester}</dd>
        <dt>Assignee</dt><dd>{t.assignee_email ?? (t.assignee ? `#${t.assignee}` : 'Unassigned')}</dd>
        <dt>Asset</dt><dd>{t.asset ?? '—'}</dd>
        <dt>Created</dt><dd>{t.created_at ? new Date(t.created_at).toLocaleString() : '—'}</dd>
      </dl>
      {t.on_behalf_reason && (<><h4>On-behalf-of reason</h4><p>{t.on_behalf_reason}</p></>)}
      <h4>Description</h4>
      <p className="pre-wrap">{t.description}</p>
      {t.resolution_notes && (<><h4>Resolution notes</h4><p className="pre-wrap">{t.resolution_notes}</p></>)}

      <h4>Notes</h4>
      {notes.length === 0 ? <p className="muted">No notes yet.</p> : (
        <ul className="note-list">
          {notes.map((n) => (
            <li key={n.id}>
              <div className="muted small">{n.author_email ?? `#${n.author}`} · {n.created_at ? new Date(n.created_at).toLocaleString() : ''}{n.is_internal ? ' · internal' : ''}</div>
              <div className="pre-wrap">{n.body}</div>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={addNote} className="note-form">
        <textarea className="input" rows={3} value={noteBody} onChange={(e) => setNoteBody(e.target.value)} placeholder="Add an update…" disabled={noteBusy} aria-label="Note body" />
        {isStaff && user?.role !== 'employee' && (
          <label className="check-row">
            <input type="checkbox" checked={noteInternal} onChange={(e) => setNoteInternal(e.target.checked)} disabled={noteBusy} />
            Internal note (hidden from employees)
          </label>
        )}
        {noteError && <div className="field-error" role="alert">{noteError}</div>}
        <div className="row-end">
          <button type="submit" className="btn-secondary" disabled={noteBusy || !noteBody.trim()}>
            {noteBusy ? 'Adding…' : 'Add note'}
          </button>
        </div>
      </form>

      {history !== null && (
        <>
          <h4>History</h4>
          {history.length === 0 ? <p className="muted">No history entries.</p> : (
            <ul className="note-list">
              {history.map((h) => (
                <li key={h.id}>
                  <div className="muted small">{h.actor_email ?? `#${h.actor}`} · {h.timestamp ? new Date(h.timestamp).toLocaleString() : ''} · {h.action}</div>
                  {h.note && <div className="pre-wrap">{h.note}</div>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {confirmingDelete && (
        <ConfirmDialog
          title={`Delete ticket #${t.id}?`}
          message="This soft-deletes the ticket (it moves to the Recycle Bin and can be restored by a System Admin). History is preserved."
          confirmLabel="Delete ticket"
          danger
          busy={deleteBusy}
          onConfirm={doDelete}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}
    </div>
  );
}
