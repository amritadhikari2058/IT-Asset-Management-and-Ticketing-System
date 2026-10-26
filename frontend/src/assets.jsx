import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, CategorySelect, ConfirmDialog, DepartmentSelect, ErrorSummary, Field,
  Modal, PageHeader, UserSelect,
} from './components';
import { fieldMsg, parseApiError } from './api-utils';

const STATUSES = ['available', 'assigned', 'in_repair', 'retired', 'lost'];
// Generic edits may only move between these two; assigned/retired/lost
// require their dedicated workflows (backend rejects those jumps).
const EDITABLE_STATUSES = ['available', 'in_repair'];
// Mirrors ATTACHMENT_ALLOWED_EXTENSIONS / ATTACHMENT_MAX_SIZE_MB in
// backend/config/settings.py, so an obviously bad file is rejected before
// anything is created. The server always re-validates.
const ATTACHMENT_EXTENSIONS = ['pdf', 'png', 'jpg', 'jpeg', 'txt', 'csv', 'log', 'docx', 'xlsx'];
const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'];

function isImageFilename(name) {
  const ext = (name || '').split('.').pop().toLowerCase();
  return IMAGE_EXTENSIONS.includes(ext);
}
const ATTACHMENT_MAX_MB = 10;

/** Client-side pre-check; returns a human message or '' when acceptable. */
function attachmentProblem(file) {
  if (!file) return '';
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  if (!ATTACHMENT_EXTENSIONS.includes(ext)) {
    return `"${file.name}" is not an allowed file type (.${ext || 'no extension'}). Allowed types: ${ATTACHMENT_EXTENSIONS.join(', ')}.`;
  }
  if (file.size > ATTACHMENT_MAX_MB * 1024 * 1024) {
    return `"${file.name}" is ${(file.size / (1024 * 1024)).toFixed(1)} MB — the maximum upload size is ${ATTACHMENT_MAX_MB} MB.`;
  }
  return '';
}

export function AssetForm({ id }) {
  const { isStaff } = useAuth();
  const isEdit = !!id;
  const [loading, setLoading] = useState(isEdit);
  const [loadError, setLoadError] = useState('');
  const [form, setForm] = useState({
    asset_tag: '', name: '', category: '', status: 'available',
    serial_number: '', description: '', location: '', department: '',
    purchase_date: '', warranty_expiry: '', purchase_cost: '',
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [okMsg, setOkMsg] = useState('');
  const [submitting, setSubmitting] = useState(false);
  // Optional file chosen on the create page. It is sent as a second request
  // (POST /assets/attachments/) right after the asset row is created.
  const [file, setFile] = useState(null);
  // Set only when the asset WAS created but its upload failed:
  // {assetId, assetTag, fileName}. Retrying re-sends just the upload, so a
  // retry can never create a second asset.
  const [partial, setPartial] = useState(null);
  const [partialError, setPartialError] = useState('');
  const [retrying, setRetrying] = useState(false);
  // Status the record had when the form loaded (create starts available).
  // Dedicated statuses stay selectable only so an unchanged value can be
  // resubmitted; the backend rejects actual jumps to them.
  const [initialStatus, setInitialStatus] = useState('available');

  useEffect(() => {
    if (!isEdit) return;
    (async () => {
      setLoading(true);
      try {
        const r = await api.get(`/assets/${id}/`);
        const a = r.data;
        setInitialStatus(a.status ?? 'available');
        setForm({
          asset_tag: a.asset_tag ?? '', name: a.name ?? '',
          category: a.category ?? '', status: a.status ?? 'available',
          serial_number: a.serial_number ?? '',
          description: a.description ?? '', location: a.location ?? '',
          department: a.department ?? '',
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

  // Create-then-upload: the asset row first (JSON), then the file against
  // the new id. Two separate calls, so each step can fail independently.
  const uploadAttachment = async (assetId, f) => {
    const fd = new FormData();
    fd.append('asset', assetId);
    fd.append('file', f);
    return api.post('/assets/attachments/', fd);
  };

  const submit = async (ev) => {
    ev.preventDefault();
    // After a partial failure the asset already exists: the form stays
    // locked behind the retry banner so submitting cannot create a twin.
    if (submitting || partial) return;
    setFieldErrors({});
    setGlobalError('');
    setOkMsg('');
    if (!isEdit) {
      const problem = attachmentProblem(file);
      if (problem) {
        setGlobalError(problem);
        return;
      }
    }
    // Assignment is never part of create/edit payloads (dedicated endpoints).
    const payload = {
      asset_tag: form.asset_tag.trim(),
      name: form.name.trim(),
      category: form.category === '' ? null : Number(form.category),
      status: form.status,
      serial_number: form.serial_number.trim(),
      description: form.description.trim(),
      location: form.location.trim(),
      department: form.department === '' ? null : Number(form.department),
      purchase_date: form.purchase_date || null,
      warranty_expiry: form.warranty_expiry || null,
    };
    if (form.purchase_cost !== '') payload.purchase_cost = form.purchase_cost;
    setSubmitting(true);
    try {
      if (isEdit) {
        await api.patch(`/assets/${id}/`, payload);
        setOkMsg('Asset updated.');
        location.hash = `#/assets/${id}`;
        return;
      }
      const created = (await api.post('/assets/', payload)).data;
      if (file) {
        try {
          await uploadAttachment(created.id, file);
        } catch (e) {
          // Asset exists, file does not: report both halves honestly and
          // offer an upload-only retry (no second create).
          const p = parseApiError(e);
          setPartial({
            assetId: created.id,
            assetTag: created.asset_tag || payload.asset_tag,
            fileName: file.name,
          });
          setPartialError(p.fields.file || p.global || 'The upload failed.');
          return;
        }
      }
      setOkMsg('Asset created.');
      location.hash = `#/assets/${created.id}`;
    } catch (e) {
      const p = parseApiError(e);
      setFieldErrors(p.fields);
      setGlobalError(p.global);
    } finally {
      setSubmitting(false);
    }
  };

  // Upload-only retry: re-sends the stored file to the already-created
  // asset. Never calls POST /assets/ again.
  const retryUpload = async () => {
    if (!partial || retrying || !file) return;
    setRetrying(true);
    setPartialError('');
    try {
      await uploadAttachment(partial.assetId, file);
      setPartial(null);
      setOkMsg('Attachment uploaded.');
      location.hash = `#/assets/${partial.assetId}`;
    } catch (e) {
      const p = parseApiError(e);
      setPartialError(p.fields.file || p.global || 'The upload failed again.');
    } finally {
      setRetrying(false);
    }
  };

  if (!isStaff) {
    return (
      <div className="form-wrap">
        <h1>{isEdit ? `Edit asset #${id}` : 'New asset'}</h1>
        <div className="error-summary" role="alert">Only IT staff can manage assets.</div>
        <p><a className="back-link" href="#/assets">← Back to assets</a></p>
      </div>
    );
  }
  if (loading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading asset…
      </p>
    );
  }
  if (loadError) {
    return (
      <div className="form-wrap">
        <div className="error-summary" role="alert">{loadError}</div>
        <p><a className="back-link" href="#/assets">← Back to assets</a></p>
      </div>
    );
  }

  return (
    <div className="form-wrap">
      <PageHeader
        title={isEdit ? `Edit asset #${id}` : 'New asset'}
        sub={isEdit ? undefined : 'Assignment happens after creation, on the asset page.'}
        actions={
          <a className="back-link" href={isEdit ? `#/assets/${id}` : '#/assets'}>
            ← {isEdit ? `Back to asset #${id}` : 'Back to assets'}
          </a>
        }
      />
      <ErrorSummary parsed={{ global: globalError }} />
      {okMsg && <div className="success-summary" role="status">{okMsg}</div>}
      {partial && (
        <div className="error-summary" role="alert">
          <p>
            Asset <strong>#{partial.assetId}</strong> ({partial.assetTag}) was created, but
            the file &ldquo;{partial.fileName}&rdquo; could not be attached: {partialError}
            {' '}The asset exists without the file — retrying uploads the file only and will
            not create a second asset.
          </p>
          <div className="row-end">
            <a className="btn-ghost" href={`#/assets/${partial.assetId}`}>Open asset</a>
            <button
              type="button" className="btn-primary" onClick={retryUpload}
              disabled={retrying || !file}
            >
              {retrying ? 'Uploading…' : 'Retry upload'}
            </button>
          </div>
        </div>
      )}
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
          <Field
            label="Status" required error={fieldMsg(fieldErrors, 'status')}
            hint="Use Assign, Return, Retire, or Mark lost for other statuses."
          >
            <select className="input" value={form.status} onChange={(e) => set('status')(e.target.value)} disabled={submitting}>
              {STATUSES.map((s) => (
                <option
                  key={s} value={s}
                  disabled={isEdit && !EDITABLE_STATUSES.includes(s) && s !== initialStatus}
                >
                  {s.replace(/_/g, ' ')}
                </option>
              ))}
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
          <Field label="Department (optional)" error={fieldMsg(fieldErrors, 'department')}>
            <DepartmentSelect value={form.department} onChange={set('department')} disabled={submitting} />
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
        {!isEdit && (
          <Field
            label="Attachment (optional)"
            error={fieldMsg(fieldErrors, 'file')}
            hint="Uploaded right after the asset is created. PDF, PNG, JPG, TXT, CSV, LOG, DOCX or XLSX, up to 10 MB."
          >
            <input
              type="file" className="input"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              disabled={submitting || retrying || !!partial}
            />
          </Field>
        )}
        {!isEdit && <p className="muted">Assignment happens after creation via the dedicated assign action on the asset page.</p>}
        <div className="row-end">
          <a className="btn-ghost" href={isEdit ? `#/assets/${id}` : '#/assets'}>Cancel</a>
          <button type="submit" className="btn-primary" disabled={submitting || !!partial}>
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
  const [assignUser, setAssignUser] = useState('');
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
  const [previewUrl, setPreviewUrl] = useState(null);
  const [previewName, setPreviewName] = useState('');
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [attToDelete, setAttToDelete] = useState(null);
  const [attBusy, setAttBusy] = useState(false);
  const [lostOpen, setLostOpen] = useState(false);
  const [lostReason, setLostReason] = useState('');
  const [lostBusy, setLostBusy] = useState(false);
  const [lostError, setLostError] = useState('');

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

  const openAttachmentPreview = async (f) => {
    if (previewBusy) return;
    setPreviewBusy(true);
    setPreviewError('');
    try {
      const r = await api.get(`/assets/attachments/${f.id}/download/`, {
        responseType: 'blob',
      });
      const url = URL.createObjectURL(r.data);
      setPreviewUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
      setPreviewName(f.original_filename || `attachment-${f.id}`);
    } catch (e) {
      const msg = e?.response?.status === 403
        ? 'You do not have permission to preview this file.'
        : e?.response?.status === 404
          ? 'Attachment not available (deleted or no access).'
          : 'Preview failed.';
      setPreviewError(msg);
    } finally {
      setPreviewBusy(false);
    }
  };

  const closeAttachmentPreview = () => {
    setPreviewUrl((url) => {
      if (url) URL.revokeObjectURL(url);
      return null;
    });
    setPreviewName('');
    setPreviewError('');
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

  const doMarkLost = async (ev) => {
    ev.preventDefault();
    if (lostBusy || !lostReason.trim()) return;
    setLostBusy(true);
    setLostError('');
    try {
      const res = await api.post(`/assets/${id}/mark_lost/`, {
        reason: lostReason.trim(),
      });
      setAsset(res.data);
      setLostOpen(false);
      setLostReason('');
      load();
    } catch (e) {
      setLostError(parseApiError(e).global || 'Could not mark asset lost.');
    } finally {
      setLostBusy(false);
    }
  };

  const doAssign = async (ev) => {
    ev.preventDefault();
    if (assignBusy || !assignUser) return;
    setAssignBusy(true);
    setAssignError('');
    try {
      const res = await api.post(`/assets/${id}/assign/`, {
        assigned_to: Number(assignUser), note: assignNote.trim(),
      });
      setAsset(res.data);
      setAssignOpen(false);
      setAssignUser('');
      setAssignNote('');
      load();
    } catch (e) {
      setAssignError(parseApiError(e).global || 'Could not assign asset.');
    } finally {
      setAssignBusy(false);
    }
  };

  if (loading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading asset…
      </p>
    );
  }
  if (error && !asset) {
    return (
      <div className="detail-wrap">
        <div className="error-summary" role="alert">{error}</div>
        <p><a className="back-link" href="#/assets">← Back to assets</a></p>
      </div>
    );
  }
  const a = asset;
  return (
    <div className="detail-wrap">
      <a className="back-link" href="#/assets">← Assets</a>
      {error && <div className="error-summary" role="alert">{error}</div>}
      <div className="detail-head">
        <div>
          <h1>{a.asset_tag} — {a.name}</h1>
          <div className="row-gap detail-badges">
            <Badge kind="status" value={a.status} />
            <span className="muted small">{a.category_name ?? ''}</span>
          </div>
        </div>
        {isStaff && (
          <div className="row-gap">
            <a className="btn-secondary" href={`#/assets/${a.id}/edit`}>Edit</a>
            <button type="button" className="btn-secondary" onClick={() => { setAssignError(''); setAssignOpen(true); }}>Assign…</button>
            {a.assigned_to && <button type="button" className="btn-ghost" onClick={() => setConfirm('return')}>Return…</button>}
            <button type="button" className="btn-ghost" onClick={() => setConfirm('retire')}>Retire…</button>
            <button type="button" className="btn-ghost" onClick={() => { setLostError(''); setLostOpen(true); }}>Mark lost…</button>
            <button type="button" className="btn-danger" onClick={() => setConfirm('delete')}>Delete…</button>
          </div>
        )}
      </div>
      <dl className="detail-grid">
        <dt>Assigned to</dt><dd>{a.assigned_to_email ?? (a.assigned_to ? `#${a.assigned_to}` : '—')}</dd>
        <dt>Serial</dt><dd>{a.serial_number || '—'}</dd>
        <dt>Department</dt><dd>{a.department_name || '-'}</dd>
        <dt>Location</dt><dd>{a.location || '-'}</dd>
        <dt>Purchased</dt><dd>{a.purchase_date ?? '—'}</dd>
        <dt>Warranty until</dt><dd>{a.warranty_expiry ?? '—'}</dd>
        <dt>Cost</dt><dd>{a.purchase_cost ?? '—'}</dd>
      </dl>
      {a.description && (
        <section className="section">
          <h4>Description</h4>
          <p className="pre-wrap">{a.description}</p>
        </section>
      )}

      <section className="section">
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
      </section>

      {history !== null && (
        <section className="section">
          <h4>History</h4>
          {history.length === 0 ? <p className="muted">No history entries.</p> : (
            <ul className="timeline">
              {history.map((h) => (
                <li key={h.id}>
                  <div className="muted small">{h.actor_email ?? `#${h.actor}`} · {h.timestamp ? new Date(h.timestamp).toLocaleString() : ''} · {h.action}</div>
                  {h.note && <div className="pre-wrap">{h.note}</div>}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

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
                  {isImageFilename(f.original_filename) && (
                    <button
                      type="button" className="btn-small"
                      onClick={() => openAttachmentPreview(f)}
                      disabled={previewBusy}
                      aria-label={`Preview ${f.original_filename || f.id}`}
                    >
                      {previewBusy ? 'Loading…' : 'Preview'}
                    </button>
                  )}
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
        {previewError && <div className="field-error" role="alert">{previewError}</div>}
        {previewUrl && (
          <Modal title={previewName || 'Photo preview'} onClose={closeAttachmentPreview}>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <img
                src={previewUrl}
                alt={previewName || 'Attachment preview'}
                style={{ maxWidth: '100%', maxHeight: '70vh', objectFit: 'contain' }}
              />
            </div>
          </Modal>
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
      </section>

      {assignOpen && (
        <Modal title={`Assign ${a.asset_tag}`} onClose={() => { if (!assignBusy) setAssignOpen(false); }}>
          <form onSubmit={doAssign}>
            <Field label="Employee" required hint="Search by employee ID or email.">
              <UserSelect value={assignUser} onChange={setAssignUser} disabled={assignBusy} label="Assignee" />
            </Field>
            <Field label="Note (optional)">
              <input className="input" value={assignNote} onChange={(e) => setAssignNote(e.target.value)} placeholder="Reason…" disabled={assignBusy} />
            </Field>
            {assignError && <div className="field-error" role="alert">{assignError}</div>}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setAssignOpen(false)} disabled={assignBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={assignBusy || !assignUser}>
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

      {lostOpen && (
        <Modal title={`Mark ${a.asset_tag} lost`} onClose={() => { if (!lostBusy) setLostOpen(false); }}>
          <form onSubmit={doMarkLost}>
            <Field label="Reason" required hint="What happened, and when it was last seen. Recorded in history.">
              <textarea
                className="input" rows={3} value={lostReason}
                onChange={(e) => setLostReason(e.target.value)}
                placeholder="e.g. Not returned after offboarding; last seen HQ Lab on Friday."
                disabled={lostBusy} autoFocus
              />
            </Field>
            {lostError && <div className="field-error" role="alert">{lostError}</div>}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setLostOpen(false)} disabled={lostBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={lostBusy || !lostReason.trim()}>
                {lostBusy ? 'Marking…' : 'Mark lost'}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
