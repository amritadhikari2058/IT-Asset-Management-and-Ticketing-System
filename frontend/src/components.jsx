import { useEffect, useRef, useState } from 'react';
import api from './api';
import { parseApiError } from './api-utils';
import { useAuth } from './auth';

const STATUS_TONE = {
  open: 'blue', in_progress: 'purple', resolved: 'green', closed: 'gray',
  reopened: 'amber', archived: 'gray',
  available: 'green', assigned: 'blue', in_repair: 'amber', retired: 'gray',
  lost: 'red', active: 'green', inactive: 'gray',
};
const PRIORITY_TONE = { low: 'gray', medium: 'blue', high: 'amber', critical: 'red' };

/** Small status/priority indicator. kind: 'status' | 'priority'. */
export function Badge({ kind, value, label }) {
  const tone = kind === 'priority'
    ? (PRIORITY_TONE[value] ?? 'gray')
    : (STATUS_TONE[value] ?? 'gray');
  const text = label ?? String(value ?? '—').replace(/_/g, ' ');
  return <span className={`badge badge-${tone}`}>{text}</span>;
}

export function PageHeader({ title, sub, actions }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub ? <div className="page-sub">{sub}</div> : null}
      </div>
      <div className="spacer" />
      <div className="row-gap">{actions}</div>
    </div>
  );
}

export function EmptyState({ title, hint, action }) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      {hint ? <div className="small">{hint}</div> : null}
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
}

/** Table-shaped skeleton: same row rhythm as `table.grid`. */
const SK_WIDTHS = [['10%', '30%', '14%', '14%'], ['10%', '24%', '14%', '18%'], ['10%', '34%', '14%', '12%']];

export function LoadingRows({ n = 5 }) {
  return (
    <div role="status" aria-label="Loading">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="skeleton-row">
          {SK_WIDTHS[i % SK_WIDTHS.length].map((w, j) => (
            <span key={j} className="sk-cell" style={{ width: w }} />
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * Compact data table. columns: [{key, label, render?(row), thClass?}].
 * Selectable via selectKey + selected Set + onToggle(id).
 */
/** Sort state for server-side sorted tables. Cycles asc → desc → none.
 * Returns [sort, changeSort, orderingParam]. changeSort(field) updates
 * state and returns the next value synchronously for immediate loads;
 * orderingParam() yields the `ordering` query value ("" when unset). */
export function useSort() {
  const [sort, setSort] = useState(null);
  const ref = useRef(null);
  const changeSort = (field) => {
    const cur = ref.current;
    const next = !cur || cur.field !== field ? { field, dir: 'asc' }
      : cur.dir === 'asc' ? { field, dir: 'desc' } : null;
    ref.current = next;
    setSort(next);
    return next;
  };
  const orderingParam = (s) => {
    const v = s === undefined ? ref.current : s;
    return !v ? '' : (v.dir === 'desc' ? `-${v.field}` : v.field);
  };
  return [sort, changeSort, orderingParam];
}

export function useTableColumns(allKeys, defaultKeys) {
  const [visible, setVisible] = useState(() => new Set(defaultKeys || allKeys));
  const [tableVisible, setTableVisible] = useState(true);
  const toggleColumn = (key) => {
    setVisible((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size > 1) next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };
  const resetColumns = () => setVisible(new Set(defaultKeys || allKeys));
  const toggleTable = () => setTableVisible((v) => !v);
  return {
    visibleColumns: visible,
    toggleColumn,
    resetColumns,
    tableVisible,
    toggleTable,
  };
}

export function TableControls({ tableVisible, onToggleTable, columns, visible, onToggleColumn, onReset }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="table-controls row-gap" style={{ marginBottom: 'var(--sp-2)' }}>
      <button type="button" className="btn-small" onClick={onToggleTable}>
        {tableVisible ? 'Hide table' : 'Show table'}
      </button>
      <button type="button" className="btn-small" onClick={() => setOpen((v) => !v)}>
        Columns
      </button>
      <button type="button" className="btn-small" onClick={onReset}>
        Reset columns
      </button>
      {open && (
        <div className="column-chooser">
          {columns.map((c) => (
            <label key={c.key} className="check-row">
              <input
                type="checkbox"
                checked={visible.has(c.key)}
                disabled={visible.size <= 1 && visible.has(c.key)}
                onChange={() => onToggleColumn(c.key)}
                aria-label={`Show ${c.label} column`}
              />
              {c.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function DataTable({ columns, rows, keyOf, selected, onToggle, emptyTitle, emptyHint, sort, onSort }) {
  if (!rows.length) return <EmptyState title={emptyTitle ?? 'Nothing here yet.'} hint={emptyHint} />;
  const selectable = typeof onToggle === 'function';
  const sortable = typeof onSort === 'function';
  const arrow = (field) => {
    if (!sort || sort.field !== field) return '';
    return sort.dir === 'desc' ? ' ▼' : ' ▲';
  };
  return (
    <div className="table-wrap">
      <table className="grid">
        <thead>
          <tr>
            {selectable && <th className="th-select"><span className="visually-hidden">Select rows</span><span className="muted small" aria-hidden="true">✓</span></th>}
            {columns.map((c) => (
              <th
                key={c.key}
                className={c.thClass}
                aria-sort={sort && sort.field === c.sortable ? (sort.dir === 'desc' ? 'descending' : 'ascending') : undefined}
              >
                {sortable && c.sortable ? (
                  <button
                    type="button" className="th-sort"
                    onClick={() => onSort(c.sortable)}
                    aria-label={`Sort by ${c.label}`}
                  >
                    {c.label}{arrow(c.sortable)}
                  </button>
                ) : c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const k = keyOf(r);
            const isSel = selected?.has(k);
            return (
              <tr key={k} className={isSel ? 'selected' : ''}>
                {selectable && (
                  <td>
                    <input
                      type="checkbox" checked={!!isSel} onChange={() => onToggle(k)}
                      aria-label={`Select row ${k}`}
                    />
                  </td>
                )}
                {columns.map((c) => (
                  <td key={c.key}>{c.render ? c.render(r) : String(r[c.key] ?? '—')}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function Pager({ count, hasNext, hasPrev, onPrev, onNext, busy }) {
  if (count == null && !hasNext && !hasPrev) return null;
  return (
    <div className="pager">
      <span>{count != null ? `${count} total` : ''}</span>
      <span className="spacer" />
      <button type="button" className="btn-small" onClick={onPrev} disabled={!hasPrev || busy}>← Prev</button>
      <button type="button" className="btn-small" onClick={onNext} disabled={!hasNext || busy}>Next →</button>
    </div>
  );
}

export function Field({ label, error, hint, required, children }) {
  const control = error && children && typeof children === 'object' && 'props' in children
    ? { ...children, props: { ...children.props, 'aria-invalid': 'true' } }
    : children;
  return (
    <div className="form-field">
      <label className="form-label">
        <span>
          {label}
          {required && <span className="required" aria-hidden="true"> *</span>}
        </span>
        {control}
      </label>
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      {!error && hint ? <div className="field-hint">{hint}</div> : null}
    </div>
  );
}

export function ErrorSummary({ parsed }) {
  if (!parsed?.global) return null;
  return <div className="error-summary" role="alert">{parsed.global}</div>;
}

export function Modal({ title, onClose, children, size }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, [onClose]);
  useEffect(() => {
    const first = document.querySelector('.modal .input, .modal button');
    if (first) first.focus();
  }, []);
  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal${size ? ` modal-${size}` : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button type="button" className="btn-close" onClick={onClose} aria-label="Close">✕</button>
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
