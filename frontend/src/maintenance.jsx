import { useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  AssetSelect, Badge, ConfirmDialog, DataTable, ExportDialog, Field,
  LoadingRows, Modal, PageHeader, Pager, UserSelect,
} from './components';
import { fetchPage, parseApiError } from './api-utils';

export const MAINTENANCE_TYPES = [
  ['preventive', 'Preventive'],
  ['corrective', 'Corrective'],
  ['inspection', 'Inspection'],
  ['upgrade', 'Upgrade'],
  ['cleaning', 'Cleaning'],
  ['other', 'Other'],
];

export const MAINTENANCE_STATUSES = [
  ['scheduled', 'Scheduled'],
  ['in_progress', 'In progress'],
  ['completed', 'Completed'],
  ['cancelled', 'Cancelled'],
  ['overdue', 'Overdue'],
];

export const OPEN_MAINTENANCE_STATUSES = ['scheduled', 'in_progress', 'overdue'];

function toLocalInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInput(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function defaultScheduled() {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  return toLocalInput(d.toISOString());
}

const fmtDateTime = (v) => (v ? new Date(v).toLocaleString() : '—');
const fmtMoney = (v) => {
  const n = Number(v);
  return Number.isFinite(n)
    ? n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : String(v);
};

/**
 * Create/edit maintenance record. Pass `asset` to lock the asset (used from
 * the asset detail page) or `record` to edit an existing maintenance.
 */
export function MaintenanceFormModal({ asset = null, record = null, onClose, onSaved }) {
  const isEdit = !!record;
  const [form, setForm] = useState(() => ({
    asset: asset?.id ?? record?.asset ?? '',
    title: record?.title ?? '',
    maintenance_type: record?.maintenance_type ?? 'preventive',
    status: record?.status ?? 'scheduled',
    scheduled_date: toLocalInput(record?.scheduled_date) || defaultScheduled(),
    start_date: toLocalInput(record?.start_date),
    completion_date: toLocalInput(record?.completion_date),
    assigned_to: record?.assigned_to ?? '',
    vendor: record?.vendor ?? '',
    cost: record?.cost ?? '',
    description: record?.description ?? '',
    resolution_notes: record?.resolution_notes ?? '',
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});

  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (ev) => {
    ev.preventDefault();
    if (busy) return;
    setError('');
    setFieldErrors({});
    if (!form.asset) {
      setFieldErrors({ asset: 'Choose an asset.' });
      return;
    }
    if (!form.title.trim()) {
      setFieldErrors({ title: 'A title is required.' });
      return;
    }
    if (!form.scheduled_date) {
      setFieldErrors({ scheduled_date: 'A scheduled date is required.' });
      return;
    }
    if (form.status === 'completed' && !form.completion_date) {
      setFieldErrors({ completion_date: 'Set a completion date when marking maintenance completed.' });
      return;
    }
    const payload = {
      asset: Number(form.asset),
      title: form.title.trim(),
      maintenance_type: form.maintenance_type,
      status: form.status,
      scheduled_date: fromLocalInput(form.scheduled_date),
      start_date: fromLocalInput(form.start_date),
      completion_date: form.status === 'completed'
        ? fromLocalInput(form.completion_date)
        : null,
      assigned_to: form.assigned_to ? Number(form.assigned_to) : null,
      vendor: form.vendor.trim(),
      cost: form.cost === '' ? null : form.cost,
      description: form.description.trim(),
      resolution_notes: form.resolution_notes.trim(),
    };
    setBusy(true);
    try {
      if (isEdit) {
        await api.patch(`/assets/maintenance/${record.id}/`, payload);
      } else {
        await api.post('/assets/maintenance/', payload);
      }
      onSaved?.();
      onClose();
    } catch (e) {
      const p = parseApiError(e);
      setFieldErrors(p.fields);
      setError(p.global);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={isEdit ? `Update maintenance — ${record.title}` : 'Schedule maintenance'}
      onClose={() => { if (!busy) onClose(); }}
      size="lg"
    >
      <form onSubmit={submit} noValidate>
        {error && <div className="error-summary" role="alert">{error}</div>}
        <div className="form-grid">
          <Field label="Asset" required error={fieldErrors.asset}>
            {asset ? (
              <input className="input" value={`${asset.asset_tag} — ${asset.name}`} disabled />
            ) : (
              <AssetSelect value={form.asset} onChange={set('asset')} disabled={busy || isEdit} />
            )}
          </Field>
          <Field label="Title" required error={fieldErrors.title}>
            <input
              className="input" value={form.title} maxLength={200}
              onChange={(e) => set('title')(e.target.value)} disabled={busy}
              placeholder="e.g. Replace thermal paste"
            />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Type" error={fieldErrors.maintenance_type}>
            <select className="input" value={form.maintenance_type}
              onChange={(e) => set('maintenance_type')(e.target.value)} disabled={busy}>
              {MAINTENANCE_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          <Field label="Status" error={fieldErrors.status}>
            <select className="input" value={form.status}
              onChange={(e) => set('status')(e.target.value)} disabled={busy}>
              {MAINTENANCE_STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Scheduled date" required error={fieldErrors.scheduled_date}>
            <input className="input" type="datetime-local" value={form.scheduled_date}
              onChange={(e) => set('scheduled_date')(e.target.value)} disabled={busy} />
          </Field>
          <Field label="Technician" error={fieldErrors.assigned_to}>
            <UserSelect value={form.assigned_to} onChange={set('assigned_to')} disabled={busy} label="Technician" />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Start date" error={fieldErrors.start_date}>
            <input className="input" type="datetime-local" value={form.start_date}
              onChange={(e) => set('start_date')(e.target.value)} disabled={busy} />
          </Field>
          <Field label="Completion date" error={fieldErrors.completion_date}
            hint="Required when the status is completed.">
            <input className="input" type="datetime-local" value={form.completion_date}
              onChange={(e) => set('completion_date')(e.target.value)} disabled={busy} />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Vendor" error={fieldErrors.vendor}>
            <input className="input" value={form.vendor} maxLength={200}
              onChange={(e) => set('vendor')(e.target.value)} disabled={busy} placeholder="External provider (optional)" />
          </Field>
          <Field label="Cost" error={fieldErrors.cost}>
            <input className="input" type="number" step="0.01" min="0" value={form.cost}
              onChange={(e) => set('cost')(e.target.value)} disabled={busy} placeholder="0.00" />
          </Field>
        </div>
        <Field label="Description" error={fieldErrors.description}>
          <textarea className="input" rows={2} value={form.description}
            onChange={(e) => set('description')(e.target.value)} disabled={busy} />
        </Field>
        <Field label="Resolution notes" error={fieldErrors.resolution_notes}
          hint="What was done, parts used, follow-up needed.">
          <textarea className="input" rows={2} value={form.resolution_notes}
            onChange={(e) => set('resolution_notes')(e.target.value)} disabled={busy} />
        </Field>
        <div className="row-end">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Saving…' : isEdit ? 'Save maintenance' : 'Schedule maintenance'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function buildMaintenanceUrl(filters) {
  const p = new URLSearchParams();
  for (const k of ['q', 'status', 'maintenance_type']) {
    if (filters[k]) p.set(k, filters[k]);
  }
  if (filters.open) p.set('open', 'true');
  p.set('page_size', '50');
  return `/assets/maintenance/?${p.toString()}`;
}

export function Maintenance() {
  const { isStaff } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [f, setF] = useState({ q: '', status: '', maintenance_type: '', open: false });
  const [modal, setModal] = useState(null); // {asset?, record?}
  const [exportOpen, setExportOpen] = useState(false);
  const [busyRow, setBusyRow] = useState(null);
  const [cancelTarget, setCancelTarget] = useState(null);

  const url = useMemo(() => buildMaintenanceUrl(f), [f]);

  const load = async (target = url) => {
    setLoading(true);
    setError('');
    try {
      const pg = await fetchPage(target);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
    } catch {
      setError('Could not load maintenance records.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(url); }, [url]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async (m) => {
    setBusyRow(m.id);
    setMsg('');
    setError('');
    try {
      await api.patch(`/assets/maintenance/${m.id}/`, { status: 'in_progress' });
      setMsg(`Maintenance "${m.title}" started.`);
      await load();
    } catch (e) {
      setError(parseApiError(e).global || 'Could not start maintenance.');
    } finally {
      setBusyRow(null);
    }
  };

  const cancel = async () => {
    if (!cancelTarget) return;
    setBusyRow(cancelTarget.id);
    setMsg('');
    setError('');
    try {
      await api.patch(`/assets/maintenance/${cancelTarget.id}/`, { status: 'cancelled' });
      setMsg(`Maintenance "${cancelTarget.title}" cancelled.`);
      setCancelTarget(null);
      await load();
    } catch (e) {
      setError(parseApiError(e).global || 'Could not cancel maintenance.');
      setCancelTarget(null);
    } finally {
      setBusyRow(null);
    }
  };

  if (!isStaff) {
    return <div className="error-summary" role="alert">Only IT staff can manage asset maintenance.</div>;
  }

  const columns = [
    { key: 'asset', label: 'Asset', render: (m) => (
      <a className="row-title" href={`#/assets/${m.asset}`}>{m.asset_tag}</a>
    ) },
    { key: 'title', label: 'Maintenance', render: (m) => (
      <span className="ellipsis" title={m.title}>{m.title}</span>
    ) },
    { key: 'maintenance_type', label: 'Type', render: (m) => (
      <span className="muted small">{m.maintenance_type?.replace(/_/g, ' ')}</span>
    ) },
    { key: 'status', label: 'Status', render: (m) => (
      <span className="row-gap" style={{ gap: 'var(--sp-1)', alignItems: 'center' }}>
        <Badge kind="status" value={m.status} />
        {m.is_overdue && m.status !== 'overdue' && <Badge kind="status" value="overdue" label="Overdue" />}
      </span>
    ) },
    { key: 'scheduled_date', label: 'Scheduled', render: (m) => fmtDateTime(m.scheduled_date) },
    { key: 'assigned_to', label: 'Technician', render: (m) => m.assigned_to_email || <span className="cell-muted">—</span> },
    { key: 'vendor', label: 'Vendor', render: (m) => m.vendor || <span className="cell-muted">—</span> },
    { key: 'cost', label: 'Cost', render: (m) => (m.cost != null ? fmtMoney(m.cost) : <span className="cell-muted">—</span>) },
    { key: 'completion_date', label: 'Completed', render: (m) => (m.completion_date ? fmtDateTime(m.completion_date) : <span className="cell-muted">—</span>) },
    { key: 'actions', label: 'Actions', thClass: 'table-actions', render: (m) => (
      <span className="row-gap" style={{ gap: 'var(--sp-1)' }}>
        {['scheduled', 'overdue'].includes(m.status) && (
          <button type="button" className="btn-small" disabled={busyRow === m.id}
            onClick={() => start(m)}>Start</button>
        )}
        {!['completed', 'cancelled'].includes(m.status) && (
          <button type="button" className="btn-small" disabled={busyRow === m.id}
            onClick={() => setModal({ record: m })}>Update…</button>
        )}
        {['scheduled', 'in_progress', 'overdue'].includes(m.status) && (
          <button type="button" className="btn-small btn-danger" disabled={busyRow === m.id}
            onClick={() => setCancelTarget(m)}>Cancel…</button>
        )}
      </span>
    ) },
  ];

  return (
    <div>
      <PageHeader
        title="Asset maintenance"
        sub={count != null ? `${count} maintenance ${count === 1 ? 'record' : 'records'}` : undefined}
        actions={<>
          <button type="button" className="btn-primary" onClick={() => setModal({})}>+ Schedule maintenance</button>
          <button type="button" className="btn-secondary" onClick={() => setExportOpen(true)}>Export…</button>
        </>}
      />
      {exportOpen && (
        <ExportDialog
          dataset="maintenance" open={exportOpen}
          filterParams={{ q: f.q, status: f.status, maintenance_type: f.maintenance_type }}
          onClose={() => setExportOpen(false)}
        />
      )}
      {error && <div className="error-summary" role="alert">{error}</div>}
      {msg && <div className="success-summary" role="status">{msg}</div>}
      <div className="filter-bar" role="search">
        <input
          className="input grow" value={f.q}
          onChange={(e) => setF((prev) => ({ ...prev, q: e.target.value }))}
          placeholder="Search title, asset tag, vendor…" aria-label="Search maintenance"
        />
        <select className="input" value={f.status}
          onChange={(e) => setF((prev) => ({ ...prev, status: e.target.value }))}
          aria-label="Filter by maintenance status">
          <option value="">All statuses</option>
          {MAINTENANCE_STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select className="input" value={f.maintenance_type}
          onChange={(e) => setF((prev) => ({ ...prev, maintenance_type: e.target.value }))}
          aria-label="Filter by maintenance type">
          <option value="">All types</option>
          {MAINTENANCE_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <label className="check-row" style={{ marginTop: 0 }}>
          <input type="checkbox" checked={f.open}
            onChange={(e) => setF((prev) => ({ ...prev, open: e.target.checked }))} />
          Open only
        </label>
      </div>
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={6} /></div>
          : (
            <>
              <DataTable
                columns={columns} rows={items} keyOf={(m) => m.id}
                emptyTitle="No maintenance records match."
                emptyHint="Schedule maintenance for an asset, or clear the filters."
              />
              <Pager
                count={count} hasNext={!!next} hasPrev={!!previous} busy={loading}
                onPrev={() => previous && load(previous)}
                onNext={() => next && load(next)}
              />
            </>
          )}
      </div>
      <p className="page-footnote">
        Assets with open maintenance cannot be assigned until the maintenance is completed or cancelled.
      </p>
      {modal && (
        <MaintenanceFormModal
          asset={modal.asset ?? null}
          record={modal.record ?? null}
          onClose={() => setModal(null)}
          onSaved={() => load()}
        />
      )}
      {cancelTarget && (
        <ConfirmDialog
          title={`Cancel maintenance "${cancelTarget.title}"?`}
          message="The record is kept for history; the asset can be assigned again once no other maintenance is open."
          confirmLabel="Cancel maintenance" danger busy={busyRow === cancelTarget.id}
          onConfirm={cancel}
          onCancel={() => setCancelTarget(null)}
        />
      )}
    </div>
  );
}
