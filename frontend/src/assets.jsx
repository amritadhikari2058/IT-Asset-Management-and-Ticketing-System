import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  CategorySelect, ConfirmDialog, ErrorSummary, Field, Modal,
  fieldMsg, parseApiError,
} from './components';

const STATUSES = ['available', 'assigned', 'in_repair', 'retired', 'lost'];

export function AssetForm({ id }) {
  const { isStaff } = useAuth();
  const isEdit = !!id;
  const [loading, setLoading] = useState(isEdit);
  const [loadError, setLoadError] = useState('');
  const [form, setForm] = useState({
    asset_tag: '', name: '', category: '', status: 'available',
    serial_number: '', description: '', location: '',
    purchase_date: '', warranty_expiry: '', purchase_cost: '',
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [okMsg, setOkMsg] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!isEdit) return;
    (async () => {
      setLoading(true);
      try {
        const r = await api.get(`/assets/${id}/`);
        const a = r.data;
        setForm({
          asset_tag: a.asset_tag ?? '', name: a.name ?? '',
          category: a.category ?? '', status: a.status ?? 'available',
          serial_number: a.serial_number ?? '',
          description: a.description ?? '', location: a.location ?? '',
          purchase_date: a.purchase_date ?? '',
          warranty_expiry: a.warranty_expiry ?? '',
          purchase_cost: a.purchase_cost ?? '',
        });
      } catch (e) {
        setLoadError(parseApiError(e).global || 'Could not load asset.');
      } finally {
        setLoading(false);
      }
    })();
  }, [id, isEdit]);

  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (ev) => {
    ev.preventDefault();
    if (submitting) return;
    setFieldErrors({});
    setGlobalError('');
    setOkMsg('');
    // Assignment is never part of create/edit payloads (dedicated endpoints).
    const payload = {
      asset_tag: form.asset_tag.trim(),
      name: form.name.trim(),
      category: form.category === '' ? null : Number(form.category),
      status: form.status,
      serial_number: form.serial_number.trim(),
      description: form.description.trim(),
      location: form.location.trim(),
      purchase_date: form.purchase_date || null,
      warranty_expiry: form.warranty_expiry || null,
    };
    if (form.purchase_cost !== '') payload.purchase_cost = form.purchase_cost;
    setSubmitting(true);
    try {
      const res = isEdit
        ? await api.patch(`/assets/${id}/`, payload)
        : await api.post('/assets/', payload);
      setOkMsg(isEdit ? 'Asset updated.' : 'Asset created.');
      location.hash = `#/assets/${res.data.id}`;
    } catch (e) {
      const p = parseApiError(e);
      setFieldErrors(p.fields);
      setGlobalError(p.global);
    } finally {
      setSubmitting(false);
    }
  };

  if (!isStaff) {
    return (
      <div>
        <h3>{isEdit ? `Edit asset #${id}` : 'New asset'}</h3>
        <div className="error-summary" role="alert">Only IT staff can manage assets.</div>
        <p><a href="#/assets">Back to assets</a></p>
      </div>
    );
  }
  if (loading) return <p>Loading asset…</p>;
  if (loadError) return (<div><div className="error-summary" role="alert">{loadError}</div><p><a href="#/assets">Back to assets</a></p></div>);

  return (
    <div className="form-wrap">
      <h3>{isEdit ? `Edit asset #${id}` : 'New asset'}</h3>
      <ErrorSummary parsed={{ global: globalError }} />
      {okMsg && <div className="success-summary" role="status">{okMsg}</div>}
      <form onSubmit={submit} noValidate>
        <div className="form-grid">
          <Field label="Asset tag" required error={fieldMsg(fieldErrors, 'asset_tag')}>
            <input className="input" value={form.asset_tag} onChange={(e) => set('asset_tag')(e.target.value)} placeholder="e.g. LT-0001" disabled={submitting} maxLength={50} />
          </Field>
          <Field label="Name" required error={fieldMsg(fieldErrors, 'name')}>
            <input className="input" value={form.name} onChange={(e) => set('name')(e.target.value)} placeholder="e.g. ThinkPad T14" disabled={submitting} maxLength={200} />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Category" required error={fieldMsg(fieldErrors, 'category')}>
            <CategorySelect kind="asset" value={form.category} onChange={set('category')} disabled={submitting} />
          </Field>
          <Field label="Status" required error={fieldMsg(fieldErrors, 'status')}>
            <select className="input" value={form.status} onChange={(e) => set('status')(e.target.value)} disabled={submitting}>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Serial number" error={fieldMsg(fieldErrors, 'serial_number')}>
            <input className="input" value={form.serial_number} onChange={(e) => set('serial_number')(e.target.value)} disabled={submitting} maxLength={100} />
          </Field>
          <Field label="Location" error={fieldMsg(fieldErrors, 'location')}>
            <input className="input" value={form.location} onChange={(e) => set('location')(e.target.value)} placeholder="e.g. HQ Lab" disabled={submitting} maxLength={200} />
          </Field>
        </div>
        <Field label="Description" error={fieldMsg(fieldErrors, 'description')}>
          <textarea className="input" rows={3} value={form.description} onChange={(e) => set('description')(e.target.value)} disabled={submitting} />
        </Field>
        <div className="form-grid">
          <Field label="Purchase date" error={fieldMsg(fieldErrors, 'purchase_date')}>
            <input className="input" type="date" value={form.purchase_date} onChange={(e) => set('purchase_date')(e.target.value)} disabled={submitting} />
          </Field>
          <Field label="Warranty expiry" error={fieldMsg(fieldErrors, 'warranty_expiry')}>
            <input className="input" type="date" value={form.warranty_expiry} onChange={(e) => set('warranty_expiry')(e.target.value)} disabled={submitting} />
          </Field>
          <Field label="Purchase cost" error={fieldMsg(fieldErrors, 'purchase_cost')}>
            <input className="input" type="number" step="0.01" min="0" value={form.purchase_cost} onChange={(e) => set('purchase_cost')(e.target.value)} placeholder="0.00" disabled={submitting} />
          </Field>
        </div>
        {!isEdit && <p className="muted">Assignment happens after creation via the dedicated assign action on the asset page.</p>}
        <div className="row-end">
          <a className="btn-ghost" href={isEdit ? `#/assets/${id}` : '#/assets'}>Cancel</a>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? 'Saving…' : isEdit ? 'Save changes' : 'Create asset'}
          </button>
        </div>
      </form>
    </div>
  );
}

export function AssetDetail({ id }) {
  const { isStaff } = useAuth();
  const [asset, setAsset] = useState(null);
  const [assignments, setAssignments] = useState([]);
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState(null); // 'return' | 'retire' | 'delete'
  const [busy, setBusy] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [employeeId, setEmployeeId] = useState('');
  const [assignNote, setAssignNote] = useState('');
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [uploadMsg, setUploadMsg] = useState('');
  const [dlBusy, setDlBusy] = useState(null);
  const [dlError, setDlError] = useState({});
  const [attToDelete, setAttToDelete] = useState(null);
  const [attBusy, setAttBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      setAsset((await api.get(`/assets/${id}/`)).data);
      try {
        const r = await api.get('/assets/assignments/history/', { params: { asset: id } });
        setAssignments(r.data.results ?? r.data ?? []);
      } catch { setAssignments([]); }
      try {
        const at = await api.get('/assets/attachments/', { params: { asset: id } });
        setAttachments(at.data.results ?? at.data ?? []);
      } catch { setAttachments([]); }
      try {
        const h = await api.get('/assets/histories/', { params: { asset: id } });
        setHistory(h.data.results ?? h.data ?? []);
      } catch { setHistory(null); }
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load asset.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const runAction = async (path, okMsg) => {
    setBusy(true);
    try {
      setAsset((await api.post(path, {})).data);
      setConfirm(null);
      load();
    } catch (e) {
      setError(parseApiError(e).global || okMsg);
      setConfirm(null);
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async () => {
    setBusy(true);
    try {
      await api.delete(`/assets/${id}/`);
      location.hash = '#/assets';
    } catch (e) {
      const p = parseApiError(e);
      setError(p.global || JSON.stringify(p.fields) || 'Could not delete asset.');
      setConfirm(null);
    } finally {
      setBusy(false);
    }
  };

  const reloadAttachments = async () => {
    try {
      const at = await api.get('/assets/attachments/', { params: { asset: id } });
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
      fd.append('asset', id);
      fd.append('file', uploadFile);
      const r = await api.post('/assets/attachments/', fd);
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
      const r = await api.get(`/assets/attachments/${f.id}/download/`, {
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
      await api.delete(`/assets/attachments/${attToDelete.id}/`);
      setAttToDelete(null);
      await reloadAttachments();
    } catch (e) {
      setUploadError(parseApiError(e).global || 'Could not delete attachment.');
      setAttToDelete(null);
    } finally {
      setAttBusy(false);
    }
  };

  const doAssign = async (ev) => {
    ev.preventDefault();
    if (assignBusy || !employeeId.trim()) return;
    setAssignBusy(true);
    setAssignError('');
    try {
      // Single-assign API takes the user PK; resolve the business key first.
      const q = employeeId.trim();
      const r = await api.get('/accounts/users/', { params: { q } });
      const list = r.data.results ?? r.data ?? [];
      const match = list.find((u) => u.employee_id === q)
        ?? list.find((u) => String(u.employee_id).toLowerCase() === q.toLowerCase());
      if (!match) throw { response: { data: { detail: `Employee "${q}" not found.` } } };
      const res = await api.post(`/assets/${id}/assign/`, {
        assigned_to: match.id, note: assignNote.trim(),
      });
      setAsset(res.data);
      setAssignOpen(false);
      setEmployeeId('');
      setAssignNote('');
      load();
    } catch (e) {
      setAssignError(parseApiError(e).global || 'Could not assign asset.');
    } finally {
      setAssignBusy(false);
    }
  };

  if (loading) return <p>Loading asset…</p>;
  if (error && !asset) return (<div><div className="error-summary" role="alert">{error}</div><p><a href="#/assets">Back to assets</a></p></div>);
  const a = asset;
  return (
    <div className="detail-wrap">
      <p><a href="#/assets">← Assets</a></p>
      {error && <div className="error-summary" role="alert">{error}</div>}
      <div className="detail-head">
        <h3>{a.asset_tag} — {a.name}</h3>
        {isStaff && (
          <div className="row-gap">
            <a className="btn-secondary" href={`#/assets/${a.id}/edit`}>Edit</a>
            <button type="button" className="btn-secondary" onClick={() => { setAssignError(''); setAssignOpen(true); }}>Assign…</button>
            {a.assigned_to && <button type="button" className="btn-ghost" onClick={() => setConfirm('return')}>Return…</button>}
            <button type="button" className="btn-ghost" onClick={() => setConfirm('retire')}>Retire…</button>
            <button type="button" className="btn-danger" onClick={() => setConfirm('delete')}>Delete…</button>
          </div>
        )}
      </div>
      <dl className="detail-grid">
        <dt>Status</dt><dd>{a.status}</dd>
        <dt>Category</dt><dd>{a.category_name ?? a.category}</dd>
        <dt>Assigned to</dt><dd>{a.assigned_to_email ?? (a.assigned_to ? `#${a.assigned_to}` : '—')}</dd>
        <dt>Serial</dt><dd>{a.serial_number || '—'}</dd>
        <dt>Location</dt><dd>{a.location || '—'}</dd>
        <dt>Purchased</dt><dd>{a.purchase_date ?? '—'}</dd>
        <dt>Warranty until</dt><dd>{a.warranty_expiry ?? '—'}</dd>
        <dt>Cost</dt><dd>{a.purchase_cost ?? '—'}</dd>
      </dl>
      {a.description && (<><h4>Description</h4><p className="pre-wrap">{a.description}</p></>)}

      <h4>Assignments</h4>
      {assignments.length === 0 ? <p className="muted">No assignment records.</p> : (
        <ul className="note-list">
          {assignments.map((x) => (
            <li key={x.id}>
              <div className="muted small">
                #{x.id} · {x.assigned_at ? new Date(x.assigned_at).toLocaleString() : ''}
                {x.returned_at ? ` · returned ${new Date(x.returned_at).toLocaleString()}` : ' · active'}
              </div>
              <div>To user #{x.assigned_to} by #{x.assigned_by}{x.note ? ` — ${x.note}` : ''}</div>
            </li>
          ))}
        </ul>
      )}

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

      <h4>Attachments</h4>
      {isStaff && (
        <form onSubmit={doUpload} className="row-gap" style={{ marginBottom: 10 }}>
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
        <ul className="note-list">
          {attachments.map((f) => (
            <li key={f.id}>
              <div style={{ fontWeight: 600 }}>{f.original_filename || `File #${f.id}`}</div>
              <div className="muted small">
                {f.created_at ? new Date(f.created_at).toLocaleString() : ''}
              </div>
              <div className="row-gap" style={{ marginTop: 6 }}>
                <button
                  type="button" className="btn-ghost"
                  onClick={() => doDownload(f)} disabled={dlBusy === f.id}
                >
                  {dlBusy === f.id ? 'Preparing…' : 'Download'}
                </button>
                {isStaff && (
                  <button type="button" className="btn-ghost" onClick={() => setAttToDelete(f)}>
                    Delete…
                  </button>
                )}
              </div>
              {dlError[f.id] && <div className="field-error" role="alert">{dlError[f.id]}</div>}
            </li>
          ))}
        </ul>
      )}
      {attToDelete && (
        <ConfirmDialog
          title="Delete attachment?"
          message={`"${attToDelete.original_filename || 'This file'}" will be soft-deleted (kept in storage, restorable by a System Admin).`}
          confirmLabel="Delete attachment" danger busy={attBusy}
          onConfirm={doDeleteAttachment}
          onCancel={() => setAttToDelete(null)}
        />
      )}

      {assignOpen && (
        <Modal title={`Assign ${a.asset_tag}`} onClose={() => { if (!assignBusy) setAssignOpen(false); }}>
          <form onSubmit={doAssign}>
            <Field label="Employee ID" required hint="Business key (e.g. E1); leading zeros preserved.">
              <input className="input" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} placeholder="E1" disabled={assignBusy} autoFocus />
            </Field>
            <Field label="Note (optional)">
              <input className="input" value={assignNote} onChange={(e) => setAssignNote(e.target.value)} placeholder="Reason…" disabled={assignBusy} />
            </Field>
            {assignError && <div className="field-error" role="alert">{assignError}</div>}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setAssignOpen(false)} disabled={assignBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={assignBusy || !employeeId.trim()}>
                {assignBusy ? 'Assigning…' : 'Assign'}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {confirm === 'return' && (
        <ConfirmDialog
          title={`Return ${a.asset_tag}?`}
          message="This clears the assignee, sets status to available, closes the open assignment, and records history. It cannot be undone except by re-assigning."
          confirmLabel="Return asset" busy={busy}
          onConfirm={() => runAction(`/assets/${id}/return_asset/`, 'Could not return asset.')}
          onCancel={() => setConfirm(null)}
        />
      )}
      {confirm === 'retire' && (
        <ConfirmDialog
          title={`Retire ${a.asset_tag}?`}
          message="This sets status to retired and records history. Prefer retirement over deletion for assets with history."
          confirmLabel="Retire asset" busy={busy}
          onConfirm={() => runAction(`/assets/${id}/retire/`, 'Could not retire asset.')}
          onCancel={() => setConfirm(null)}
        />
      )}
      {confirm === 'delete' && (
        <ConfirmDialog
          title={`Delete ${a.asset_tag}?`}
          message="This soft-deletes the asset (Recycle Bin, restorable by a System Admin). Assets with history are blocked from deletion — retire them instead."
          confirmLabel="Delete asset" danger busy={busy}
          onConfirm={doDelete}
          onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  );
}
