import { useEffect, useRef, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  AssetSelect, Badge, CategorySelect, ConfirmDialog, DepartmentSelect, ErrorSummary,
  Field, PageHeader, UserSelect,
} from './components';
import { fieldMsg, parseApiError } from './api-utils';

const PRIORITIES = ['low', 'medium', 'high', 'critical'];
const STATUSES = ['open', 'in_progress', 'resolved', 'closed', 'reopened', 'archived'];

// Mirrors Ticket.VALID_TRANSITIONS in backend/tickets/models.py so the
// dropdown only offers moves the server accepts. The backend stays the
// authority (it still returns a 400 for anything invalid) - this just
// stops the UI from advertising rejected options.
const VALID_TRANSITIONS = {
  open: ['in_progress', 'resolved', 'closed', 'archived'],
  in_progress: ['open', 'resolved', 'closed'],
  resolved: ['closed', 'reopened'],
  closed: ['reopened', 'archived'],
  reopened: ['in_progress', 'resolved', 'closed'],
  archived: [],
};

export function TicketForm({ id }) {
  const { user, isStaff, canCreateTickets } = useAuth();
  const isEdit = !!id;
  const [loading, setLoading] = useState(isEdit);
  const [loadError, setLoadError] = useState('');
  const [form, setForm] = useState({
    title: '', description: '', priority: 'medium', category: '',
    department: '', on_behalf_reason: '', asset: '', assignee: '', status: 'open',
    resolution_notes: '',
  });
  const [kbSuggestions, setKbSuggestions] = useState([]);
  const kbSearchTimer = useRef(null);
  const [fieldErrors, setFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [okMsg, setOkMsg] = useState('');
  // Status the ticket had when the form loaded; the status dropdown only
  // offers this state plus its valid successors (create starts at open).
  const [initialStatus, setInitialStatus] = useState('open');

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
        setInitialStatus(t.status ?? 'open');
        setForm({
          title: t.title ?? '', description: t.description ?? '',
          priority: t.priority ?? 'medium', category: t.category ?? '',
          department: t.department ?? '', on_behalf_reason: t.on_behalf_reason ?? '',
          asset: t.asset ?? '', assignee: t.assignee ?? '', status: t.status ?? 'open',
          resolution_notes: t.resolution_notes ?? '',
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

  // Debounced KB article search while typing title/description.
  useEffect(() => {
    if (!isEdit) {
      clearTimeout(kbSearchTimer.current);
      kbSearchTimer.current = setTimeout(async () => {
        const query = (form.title.trim() + ' ' + form.description.trim()).trim();
        if (query.length < 3) {
          setKbSuggestions([]);
          return;
        }
        try {
          const r = await api.get('/assets/knowledge-base/', {
            params: { q: query, page_size: 5 },
          });
          setKbSuggestions(r.data.results ?? r.data ?? []);
        } catch {
          setKbSuggestions([]);
        }
      }, 300);
    }
    return () => clearTimeout(kbSearchTimer.current);
  }, [form.title, form.description, isEdit]);

  const submit = async (ev) => {
    ev.preventDefault();
    if (submitting) return;
    setFieldErrors({});
    setGlobalError('');
    setOkMsg('');
    const payload = {
      title: form.title.trim(),
      description: form.description.trim(),
      department: form.department === '' ? null : Number(form.department),
    };
    // Priority/category are settable by anyone at creation, but on edit
    // they are staff-only server-side: non-staff simply omit them (the
    // controls are disabled) so the request can never trip the 403.
    if (!isEdit || isStaff) {
      payload.priority = form.priority;
      payload.category = form.category === '' ? null : Number(form.category);
    }
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
        payload.resolution_notes = form.resolution_notes;
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
      <div className="form-wrap">
        <h1>New ticket</h1>
        <div className="error-summary" role="alert">
          Ticket creation is disabled for your account. Contact an administrator.
        </div>
        <p><a className="back-link" href="#/tickets">← Back to tickets</a></p>
      </div>
    );
  }
  if (loading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading ticket…
      </p>
    );
  }
  if (loadError) {
    return (
      <div className="form-wrap">
        <div className="error-summary" role="alert">{loadError}</div>
        <p><a className="back-link" href="#/tickets">← Back to tickets</a></p>
      </div>
    );
  }

  return (
    <div className="form-wrap">
      <PageHeader
        title={isEdit ? `Edit ticket #${id}` : 'New ticket'}
        sub={isEdit ? undefined : 'Fields marked * are required.'}
        actions={
          <a className="back-link" href={isEdit ? `#/tickets/${id}` : '#/tickets'}>
            ← {isEdit ? `Back to ticket #${id}` : 'Back to tickets'}
          </a>
        }
      />
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
          <Field
            label="Priority" required error={fieldMsg(fieldErrors, 'priority')}
            hint={isEdit && !isStaff ? 'Only IT staff can change priority.' : undefined}
          >
            <select
              className="input" value={form.priority}
              onChange={(e) => set('priority')(e.target.value)}
              disabled={submitting || (isEdit && !isStaff)}
            >
              {PRIORITIES.map((p) => <option key={p} value={p}>{p[0].toUpperCase() + p.slice(1)}</option>)}
            </select>
          </Field>
          <Field
            label="Category" required error={fieldMsg(fieldErrors, 'category')}
            hint={isEdit && !isStaff ? 'Only IT staff can change the category.' : undefined}
          >
            <CategorySelect
              kind="ticket" value={form.category} onChange={set('category')}
              disabled={submitting || (isEdit && !isStaff)}
            />
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
        {!isEdit && kbSuggestions.length > 0 && (
          <Field label="Related knowledge-base articles">
            <p className="muted small">
              Published articles that may help (click to open in a new tab):
            </p>
            <div className="row-gap" style={{ flexWrap: 'wrap', gap: 'var(--sp-1)' }}>
              {kbSuggestions.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  className="btn-ghost btn-small"
                  onClick={() => window.open(`#/kb/${a.id}`, '_blank')}
                >
                  {a.title}
                </button>
              ))}
            </div>
          </Field>
        )}
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
              <Field
                label="Status" error={fieldMsg(fieldErrors, 'status')}
                hint="Only valid next states are listed; the server still verifies the transition."
              >
                <select className="input" value={form.status} onChange={(e) => set('status')(e.target.value)} disabled={submitting}>
                  {STATUSES
                    .filter((s) => s === form.status
                      || s === initialStatus
                      || (VALID_TRANSITIONS[initialStatus] || []).includes(s))
                    .map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
                </select>
              </Field>
            )}
          </div>
        )}
        {isStaff && isEdit && (form.status === 'resolved' || form.status === 'closed' || form.resolution_notes) && (
          <Field
            label="Resolution notes" error={fieldMsg(fieldErrors, 'resolution_notes')}
            hint="Recorded when resolving or closing. Preserved on unrelated edits."
          >
            <textarea className="input" rows={3} value={form.resolution_notes} onChange={(e) => set('resolution_notes')(e.target.value)} placeholder="What fixed it, and any follow-up…" disabled={submitting} />
          </Field>
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
  const [kbArticles, setKbArticles] = useState([]); // linked KB articles
  const [approvals, setApprovals] = useState([]); // workflow approvals for this ticket
  const [executions, setExecutions] = useState(isStaff ? [] : null); // staff-only automation history
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [noteBody, setNoteBody] = useState('');
  const [noteInternal, setNoteInternal] = useState(false);
  const [noteBusy, setNoteBusy] = useState(false);
  const [noteError, setNoteError] = useState('');
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [uploadMsg, setUploadMsg] = useState('');
  const [dlBusy, setDlBusy] = useState(null);
  const [dlError, setDlError] = useState({});
  const [attToDelete, setAttToDelete] = useState(null);
  const [attBusy, setAttBusy] = useState(false);
  const [newKbSlug, setNewKbSlug] = useState('');
  const [kbLinkBusy, setKbLinkBusy] = useState(false);

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
        const at = await api.get('/tickets/attachments/', { params: { ticket: id } });
        setAttachments(at.data.results ?? at.data ?? []);
      } catch { setAttachments([]); }
      // History is staff-only server-side; non-staff never get the 403
      // round-trip and the section stays hidden.
      if (isStaff) {
        try {
          const h = await api.get('/tickets/histories/', { params: { ticket: id } });
          setHistory(h.data.results ?? h.data ?? []);
        } catch { setHistory(null); }
      }
      // Linked KB articles (visible to anyone who can see the ticket).
      try {
        const k = await api.get('/tickets/kb-articles/', { params: { ticket: id } });
        setKbArticles(k.data.results ?? k.data ?? []);
      } catch { setKbArticles([]); }
      // Related workflow approvals. The approval API applies ticket visibility
      // itself, so employees only receive approvals for tickets they can see.
      try {
        const ap = await api.get('/workflow/approval-requests/', { params: { ticket: id } });
        setApprovals(ap.data.results ?? ap.data ?? []);
      } catch { setApprovals([]); }
      // Execution history is IT-staff-only server-side: never request it for
      // employees, so the section cannot leak or add a guaranteed 403.
      if (isStaff) {
        try {
          const ex = await api.get('/workflow/rule-executions/', {
            params: { ticket: id, page_size: 10 },
          });
          setExecutions(ex.data.results ?? ex.data ?? []);
        } catch { setExecutions([]); }
      } else {
        setExecutions(null);
      }
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

  const reloadAttachments = async () => {
    try {
      const at = await api.get('/tickets/attachments/', { params: { ticket: id } });
      setAttachments(at.data.results ?? at.data ?? []);
    } catch {
      setAttachments([]);
    }
  };

  const doUpload = async (ev) => {
    ev.preventDefault();
    if (uploadBusy || !uploadFile) return;
    setUploadBusy(true);
    setUploadError('');
    setUploadMsg('');
    try {
      const fd = new FormData();
      fd.append('ticket', id);
      fd.append('file', uploadFile);
      const r = await api.post('/tickets/attachments/', fd);
      setUploadFile(null);
      setUploadMsg(`Uploaded "${r.data.original_filename || 'file'}".`);
      await reloadAttachments();
    } catch (e) {
      const p = parseApiError(e);
      setUploadError(p.global || p.fields.file || 'Upload failed.');
    } finally {
      setUploadBusy(false);
    }
  };

  const doDownload = async (f) => {
    if (dlBusy) return;
    setDlBusy(f.id);
    setDlError((d) => ({ ...d, [f.id]: '' }));
    try {
      const r = await api.get(`/tickets/attachments/${f.id}/download/`, {
        responseType: 'blob',
      });
      const cd = r.headers?.['content-disposition'] || '';
      const m = cd.match(/filename="([^"]+)"/);
      const name = (m && m[1]) || f.original_filename || `attachment-${f.id}`;
      const url = URL.createObjectURL(r.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) {
      const msg = e?.response?.status === 410
        ? 'File is missing from storage.'
        : e?.response?.status === 404
          ? 'Attachment not available (deleted or no access).'
          : 'Download failed.';
      setDlError((d) => ({ ...d, [f.id]: msg }));
    } finally {
      setDlBusy(null);
    }
  };

  const doDeleteAttachment = async () => {
    if (!attToDelete || attBusy) return;
    setAttBusy(true);
    try {
      await api.delete(`/tickets/attachments/${attToDelete.id}/`);
      setAttToDelete(null);
      await reloadAttachments();
    } catch (e) {
      setUploadError(parseApiError(e).global || 'Could not delete attachment.');
      setAttToDelete(null);
    } finally {
      setAttBusy(false);
    }
  };

  const voteKb = async (linkId, helpful) => {
    try {
      await api.patch(`/tickets/kb-articles/${linkId}/`, { helpful });
      setKbArticles(kbArticles.map((l) => l.id === linkId ? { ...l, helpful } : l));
    } catch (e) {
      setError(parseApiError(e).global || 'Could not record feedback.');
    }
  };

  const unlinkKb = async (linkId) => {
    if (!confirm('Unlink this KB article from the ticket?')) return;
    try {
      await api.delete(`/tickets/kb-articles/${linkId}/`);
      setKbArticles(kbArticles.filter((l) => l.id !== linkId));
    } catch (e) {
      setError(parseApiError(e).global || 'Could not unlink article.');
    }
  };

  const linkKb = async (ev) => {
    ev.preventDefault();
    if (kbLinkBusy || !newKbSlug.trim()) return;
    setKbLinkBusy(true);
    setError('');
    try {
      await api.post('/tickets/kb-articles/', { article: newKbSlug.trim(), ticket: id });
      setNewKbSlug('');
      // reload to get the full link with article details
      const k = await api.get('/tickets/kb-articles/', { params: { ticket: id } });
      setKbArticles(k.data.results ?? k.data ?? []);
    } catch (e) {
      const p = parseApiError(e);
      setError(p.global || 'Could not link article.');
    } finally {
      setKbLinkBusy(false);
    }
  };

  if (loading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading ticket…
      </p>
    );
  }
  if (error && !ticket) {
    return (
      <div className="detail-wrap">
        <div className="error-summary" role="alert">{error}</div>
        <p><a className="back-link" href="#/tickets">← Back to tickets</a></p>
      </div>
    );
  }
  const t = ticket;
  return (
    <div className="detail-wrap">
      <a className="back-link" href="#/tickets">← Tickets</a>
      {error && <div className="error-summary" role="alert">{error}</div>}
      <div className="detail-head">
        <div>
          <h1>#{t.id} {t.title}</h1>
          <div className="row-gap detail-badges">
            <Badge kind="status" value={t.status} />
            <Badge kind="priority" value={t.priority} />
            {t.is_overdue && <Badge kind="status" value="overdue" label="Overdue" />}
            {t.sla_breached && !t.is_overdue && <Badge kind="status" value="overdue" label="SLA breached" />}
            <span className="muted small">{t.category_name ?? ''}</span>
          </div>
        </div>
        <div className="row-gap">
          <a className="btn-secondary" href={`#/tickets/${t.id}/edit`}>Edit</a>
          {isStaff && <button type="button" className="btn-danger" onClick={() => setConfirmingDelete(true)}>Delete…</button>}
        </div>
      </div>
      <dl className="detail-grid">
        <dt>Department</dt><dd>{t.department_name ?? t.department ?? '—'}</dd>
        <dt>Requester</dt><dd>{t.requester_email ?? t.requester}</dd>
        <dt>Assignee</dt><dd>{t.assignee_email ?? (t.assignee ? `#${t.assignee}` : 'Unassigned')}</dd>
        <dt>Asset</dt>
        <dd>
          {t.asset ? <a href={`#/assets/${t.asset}`}>Asset #{t.asset}</a> : '—'}
        </dd>
        <dt>Created</dt><dd>{t.created_at ? new Date(t.created_at).toLocaleString() : '—'}</dd>
        <dt>SLA due</dt><dd>{t.sla_due_at ? new Date(t.sla_due_at).toLocaleString() : 'No SLA target'}</dd>
        <dt>SLA status</dt>
        <dd>
          {!t.sla_due_at ? <span className="muted">—</span>
            : t.sla_breached ? <Badge kind="status" value="overdue" label="Breached" />
              : ['resolved', 'closed', 'archived'].includes(t.status)
                ? <Badge kind="status" value="resolved" label="Met" />
                : <Badge kind="status" value="open" label="On track" />}
        </dd>
        {t.resolved_at && <><dt>Resolved</dt><dd>{new Date(t.resolved_at).toLocaleString()}</dd></>}
        {t.closed_at && <><dt>Closed</dt><dd>{new Date(t.closed_at).toLocaleString()}</dd></>}
      </dl>
      {t.on_behalf_reason && (
        <section className="section">
          <h4>On-behalf-of reason</h4>
          <p>{t.on_behalf_reason}</p>
        </section>
      )}
      <section className="section">
        <h4>Description</h4>
        <p className="pre-wrap">{t.description}</p>
      </section>
      {t.resolution_notes && (
        <section className="section">
          <h4>Resolution notes</h4>
          <p className="pre-wrap">{t.resolution_notes}</p>
        </section>
      )}

      <section className="section">
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
      </section>

      <section className="section">
        <h4>Attachments</h4>
        {isStaff && (
          <form onSubmit={doUpload} className="upload-row">
            <input
              type="file" onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
              disabled={uploadBusy} aria-label="Choose a file to upload"
            />
            <button type="submit" className="btn-secondary" disabled={uploadBusy || !uploadFile}>
              {uploadBusy ? 'Uploading…' : 'Upload'}
            </button>
          </form>
        )}
        {uploadError && <div className="field-error" role="alert">{uploadError}</div>}
        {uploadMsg && <div className="success-summary" role="status">{uploadMsg}</div>}
        {attachments.length === 0 ? <p className="muted">No attachments.</p> : (
          <ul className="file-list">
            {attachments.map((f) => (
              <li key={f.id} className="file-row">
                <div className="file-main">
                  <div className="file-name">{f.original_filename || `File #${f.id}`}</div>
                  <div className="file-meta">
                    {f.created_at ? new Date(f.created_at).toLocaleString() : ''}
                  </div>
                </div>
                <div className="file-actions">
                  <button
                    type="button" className="btn-small"
                    onClick={() => doDownload(f)} disabled={dlBusy === f.id}
                  >
                    {dlBusy === f.id ? 'Preparing…' : 'Download'}
                  </button>
                  {isStaff && (
                    <button
                      type="button" className="btn-small btn-danger"
                      onClick={() => setAttToDelete(f)}
                      aria-label={`Delete attachment ${f.original_filename || f.id}`}
                    >
                      Delete…
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        {Object.entries(dlError).filter(([, msg]) => msg).map(([id, msg]) => (
          <div key={id} className="field-error" role="alert">{msg}</div>
        ))}
        {attToDelete && (
          <ConfirmDialog
            title="Delete attachment?"
            message={`"${attToDelete.original_filename || 'This file'}" will be soft-deleted (kept in storage, restorable by a System Admin).`}
            confirmLabel="Delete attachment" danger busy={attBusy}
            onConfirm={doDeleteAttachment}
            onCancel={() => setAttToDelete(null)}
          />
        )}
      </section>

      {isStaff && history !== null && (
        <section className="section">
          <h4>History</h4>
          {history.length === 0 ? <p className="muted">No history entries.</p> : (
            <ul className="timeline">
              {history.map((h) => (
                <li key={h.id}>
                  <div className="muted small">{h.actor_email ?? `#${h.actor}`} · {h.timestamp ? new Date(h.timestamp).toLocaleString() : ''} · {h.action}</div>
                  {h.note && <div className="pre-wrap t-note">{h.note}</div>}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="section">
        <h4>Approvals</h4>
        {approvals.length === 0 ? (
          <p className="muted">No approval requests for this ticket.</p>
        ) : (
          <ul className="timeline">
            {approvals.map((a) => (
              <li key={a.id}>
                <div className="row-gap" style={{ alignItems: 'center' }}>
                  <Badge kind="status" value={a.status} />
                  <a className="row-title" href={`#/workflow/approvals/${a.id}`}>
                    Approval #{a.id}: {a.operation_display ?? a.operation}
                  </a>
                </div>
                <div className="muted small">
                  Requested by {a.requested_by_email ?? `#${a.requested_by}`}
                  {a.created_at ? ` · ${new Date(a.created_at).toLocaleString()}` : ''}
                  {a.decided_at ? ` · decided ${new Date(a.decided_at).toLocaleString()}` : ''}
                </div>
                {a.reason && <div className="pre-wrap t-note">Reason: {a.reason}</div>}
                {a.status !== 'pending' && (
                  <div className="pre-wrap t-note">
                    {a.decision_comment || 'No decision comment.'}
                    {a.decided_by_email ? ` — ${a.decided_by_email}` : ''}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {isStaff && executions !== null && (
        <section className="section">
          <h4>Automation activity</h4>
          {executions.length === 0 ? (
            <p className="muted">No automation rules have run for this ticket.</p>
          ) : (
            <ul className="file-list">
              {executions.map((ex) => (
                <li key={ex.id} className="file-row">
                  <div className="file-main">
                    <div className="file-name">
                      {ex.rule_name ?? `Rule #${ex.rule}`}{' '}
                      <Badge
                        kind="status"
                        value={ex.success ? 'completed' : 'rejected'}
                        label={ex.success ? 'Success' : 'Failed'}
                      />
                    </div>
                    <div className="file-meta">
                      {ex.created_at ? new Date(ex.created_at).toLocaleString() : ''}
                      {ex.detail ? ` · ${ex.detail}` : ''}
                    </div>
                  </div>
                  <div className="file-actions">
                    <a className="btn-small" href={`#/workflow/executions/${ex.id}`}>View run</a>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {kbArticles.length > 0 && (
        <section className="section">
          <h4>Related knowledge-base articles</h4>
          <ul className="file-list">
            {kbArticles.map((link) => (
              <li key={link.id} className="file-row">
                <div className="file-main">
                  <div className="file-name">
                    <a href={`#/kb/${link.article_id}`}>{link.article_title}</a>
                  </div>
                  <div className="file-meta">
                    {link.article_status ? link.article_status.charAt(0).toUpperCase() + link.article_status.slice(1) : ''} · linked {link.linked_at ? new Date(link.linked_at).toLocaleDateString() : ''}
                  </div>
                </div>
                <div className="file-actions">
                  {link.helpful === null && !isStaff && (
                    <div className="row-gap" style={{ gap: 'var(--sp-1)' }}>
                      <button type="button" className="btn-small" onClick={() => voteKb(link.id, true)}>Helped</button>
                      <button type="button" className="btn-small" onClick={() => voteKb(link.id, false)}>Not helpful</button>
                    </div>
                  )}
                  {link.helpful !== null && !isStaff && (
                    <span className="badge badge-gray">
                      You voted {link.helpful ? 'helped' : 'not helpful'}
                    </span>
                  )}
                  {isStaff && (
                    <button
                      type="button" className="btn-small btn-danger"
                      onClick={() => unlinkKb(link.id)}
                      aria-label={`Unlink article ${link.article_title}`}
                    >
                      Unlink
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {isStaff && (
            <form onSubmit={linkKb} className="form-grid" style={{ marginTop: 'var(--sp-2)' }}>
              <Field label="Link KB article">
                <input className="input" type="text" value={newKbSlug} onChange={(e) => setNewKbSlug(e.target.value)} placeholder="Article slug (e.g. vpn-reset)" disabled={kbLinkBusy} />
              </Field>
              <button type="submit" className="btn-secondary" disabled={kbLinkBusy || !newKbSlug.trim()}>Link article</button>
            </form>
          )}
        </section>
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
