import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';

/** Flatten a DRF error response to {fields: {name: msg}, global: msg}. */
export function parseApiError(e) {
  const data = e?.response?.data;
  const out = { fields: {}, global: '' };
  if (!data) {
    out.global = e?.message ? `Request failed: ${e.message}` : 'Request failed.';
    return out;
  }
  if (typeof data === 'string') {
    out.global = data;
    return out;
  }
  for (const [k, v] of Object.entries(data)) {
    const msg = Array.isArray(v) ? v.join(' ') : (typeof v === 'object' ? JSON.stringify(v) : String(v));
    if (k === 'detail' || k === 'non_field_errors') out.global = out.global ? `${out.global} ${msg}` : msg;
    else out.fields[k] = msg;
  }
  if (!out.global && Object.keys(out.fields).length === 0) out.global = 'Request failed.';
  if (e?.response?.status === 403 && !out.global) out.global = 'Forbidden: you lack permission for this action.';
  return out;
}

export function fieldMsg(fieldErrors, name) {
  return fieldErrors?.[name] ?? '';
}

export function Field({ label, error, hint, required, children }) {
  return (
    <div className="form-field">
      <label className="form-label">
        {label}
        {required && <span className="required" aria-hidden="true"> *</span>}
      </label>
      {children}
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      {!error && hint ? <div className="field-hint">{hint}</div> : null}
    </div>
  );
}

export function ErrorSummary({ parsed }) {
  if (!parsed?.global) return null;
  return <div className="error-summary" role="alert">{parsed.global}</div>;
}

export function Modal({ title, onClose, children }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button type="button" className="btn-ghost" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

/** Reusable confirmation dialog. Message must describe the actual operation. */
export function ConfirmDialog({ title, message, confirmLabel = 'Confirm', danger = false, busy = false, onConfirm, onCancel }) {
  return (
    <Modal title={title} onClose={onCancel}>
      <p style={{ marginTop: 0 }}>{message}</p>
      <div className="row-end">
        <button type="button" className="btn-ghost" onClick={onCancel} disabled={busy}>Cancel</button>
        <button
          type="button"
          className={danger ? 'btn-danger' : 'btn-primary'}
          onClick={onConfirm}
          disabled={busy}
        >
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

async function fetchAllPages(url) {
  let items = [];
  let next = url;
  while (next) {
    const r = await api.get(next.replace('http://127.0.0.1:8000/api', ''));
    const d = r.data;
    if (Array.isArray(d)) return [...items, ...d];
    items = [...items, ...(d.results ?? [])];
    next = d.next;
  }
  return items;
}

/**
 * Managed category dropdown with an authorized "+ Add" modal.
 * kind: 'ticket' | 'asset'. After creation the new entry is auto-selected.
 */
export function CategorySelect({ kind, value, onChange, error, disabled }) {
  const { isStaff } = useAuth();
  const base = kind === 'ticket' ? '/tickets/categories/' : '/assets/categories/';
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  const load = async () => {
    setLoading(true);
    setLoadError('');
    try {
      setItems(await fetchAllPages(base));
    } catch {
      setLoadError('Could not load categories.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (ev) => {
    ev.preventDefault();
    if (saving) return;
    const trimmed = name.trim();
    if (!trimmed) {
      setSaveError('Name is required.');
      return;
    }
    setSaving(true);
    setSaveError('');
    try {
      const r = await api.post(base, { name: trimmed, description: description.trim() });
      await load();
      onChange(r.data.id); // auto-select the newly created category
      setName('');
      setDescription('');
      setModalOpen(false);
    } catch (e) {
      const p = parseApiError(e);
      setSaveError(p.global || p.fields.name || 'Could not create category.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="row-gap">
        <select
          className="input"
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value ? Number(e.target.value) : '')}
          disabled={disabled || loading}
          aria-label={kind === 'ticket' ? 'Ticket category' : 'Asset category'}
        >
          <option value="">{loading ? 'Loading…' : 'Select a category…'}</option>
          {items.filter((c) => c.is_active !== false).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        {isStaff && (
          <button type="button" className="btn-secondary" onClick={() => { setSaveError(''); setModalOpen(true); }} disabled={disabled}>
            + Add
          </button>
        )}
      </div>
      {loadError ? <div className="field-error" role="alert">{loadError}</div> : null}
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      {modalOpen && (
        <Modal title={kind === 'ticket' ? 'Add ticket category' : 'Add asset category'} onClose={() => { if (!saving) setModalOpen(false); }}>
          <form onSubmit={submit}>
            <Field label="Name" required>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Hardware" disabled={saving} autoFocus />
            </Field>
            <Field label="Description">
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional" disabled={saving} />
            </Field>
            {saveError && <div className="field-error" role="alert">{saveError}</div>}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setModalOpen(false)} disabled={saving}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={saving || !name.trim()}>
                {saving ? 'Saving…' : 'Create category'}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

export function DepartmentSelect({ value, onChange, error, disabled }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  useEffect(() => {
    (async () => {
      try {
        setItems(await fetchAllPages('/accounts/departments/'));
      } catch {
        setLoadError('Could not load departments.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);
  return (
    <div>
      <select
        className="input"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : '')}
        disabled={disabled || loading}
        aria-label="Department"
      >
        <option value="">{loading ? 'Loading…' : 'Select a department…'}</option>
        {items.filter((d) => d.is_active !== false).map((d) => (
          <option key={d.id} value={d.id}>{d.name}</option>
        ))}
      </select>
      {loadError ? <div className="field-error" role="alert">{loadError}</div> : null}
      {error ? <div className="field-error" role="alert">{error}</div> : null}
    </div>
  );
}

/** Optional related-asset picker for ticket forms (search + dropdown). */
export function AssetSelect({ value, onChange, error, disabled }) {
  const [q, setQ] = useState('');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const r = await api.get('/assets/', { params: q ? { q } : {} });
        if (!cancelled) setItems(r.data.results ?? r.data ?? []);
      } catch {
        if (!cancelled) setItems([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, q ? 300 : 0);
    return () => { cancelled = true; clearTimeout(t); };
  }, [q]);
  const selected = items.find((a) => a.id === Number(value));
  return (
    <div>
      <div className="row-gap">
        <select
          className="input"
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value ? Number(e.target.value) : '')}
          disabled={disabled}
          aria-label="Related asset (optional)"
        >
          <option value="">No asset</option>
          {selected ? <option value={selected.id}>{selected.asset_tag} — {selected.name}</option> : null}
          {items.filter((a) => a.id !== Number(value)).slice(0, 30).map((a) => (
            <option key={a.id} value={a.id}>{a.asset_tag} — {a.name}</option>
          ))}
        </select>
        <input
          className="input input-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search tag/name…"
          disabled={disabled}
          aria-label="Search assets"
        />
      </div>
      {loading ? <div className="field-hint">Loading assets…</div> : null}
      {error ? <div className="field-error" role="alert">{error}</div> : null}
    </div>
  );
}

/** Assignee picker (IT staff only; lists active users). */
export function UserSelect({ value, onChange, error, disabled, label }) {
  const [q, setQ] = useState('');
  const [items, setItems] = useState([]);
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await api.get('/accounts/users/', { params: q ? { q } : {} });
        if (!cancelled) setItems(r.data.results ?? r.data ?? []);
      } catch {
        if (!cancelled) setItems([]);
      }
    }, q ? 300 : 0);
    return () => { cancelled = true; clearTimeout(t); };
  }, [q]);
  const selected = items.find((u) => u.id === Number(value));
  return (
    <div>
      <div className="row-gap">
        <select
          className="input"
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value ? Number(e.target.value) : '')}
          disabled={disabled}
          aria-label={label || 'Assignee'}
        >
          <option value="">Unassigned</option>
          {selected ? <option value={selected.id}>{selected.employee_id} — {selected.email}</option> : null}
          {items.filter((u) => u.id !== Number(value)).slice(0, 30).map((u) => (
            <option key={u.id} value={u.id}>{u.employee_id} — {u.email}</option>
          ))}
        </select>
        <input
          className="input input-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search users…"
          disabled={disabled}
          aria-label="Search users"
        />
      </div>
      {error ? <div className="field-error" role="alert">{error}</div> : null}
    </div>
  );
}
