import { useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  AssetSelect, Badge, ConfirmDialog, DataTable, ExportDialog, Field,
  LoadingRows, Modal, PageHeader, Pager, UserSelect,
} from './components';
import { fetchPage, parseApiError } from './api-utils';

export const DISPOSAL_METHODS = [
  ['recycled', 'Recycled'],
  ['donated', 'Donated'],
  ['sold', 'Sold'],
  ['scrapped', 'Scrapped'],
  ['returned_to_vendor', 'Returned to vendor'],
  ['other', 'Other'],
];

const APPROVAL_LABELS = {
  pending: 'Pending approval',
  approved: 'Approved',
  rejected: 'Rejected',
};

const fmtDateTime = (v) => (v ? new Date(v).toLocaleString() : '—');
const fmtMoney = (v) => {
  const n = Number(v);
  return Number.isFinite(n)
    ? n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : String(v);
};

/**
 * Request disposal for an asset. Pass `asset` to lock it (used from the
 * asset detail page). New requests are always created pending approval.
 */
export function DisposalFormModal({ asset = null, onClose, onSaved }) {
  const [form, setForm] = useState({
    asset: asset?.id ?? '',
    disposal_reason: '',
    disposal_method: 'other',
    disposal_value: '',
    responsible_person: '',
    notes: '',
  });
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
    if (!form.disposal_reason.trim()) {
      setFieldErrors({ disposal_reason: 'Explain why the asset is being disposed.' });
      return;
    }
    setBusy(true);
    try {
      await api.post('/assets/disposals/', {
        asset: Number(form.asset),
        disposal_reason: form.disposal_reason.trim(),
        disposal_method: form.disposal_method,
        disposal_value: form.disposal_value === '' ? null : form.disposal_value,
        responsible_person: form.responsible_person ? Number(form.responsible_person) : null,
        notes: form.notes.trim(),
      });
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
    <Modal title="Request asset disposal" onClose={() => { if (!busy) onClose(); }} size="lg">
      <form onSubmit={submit} noValidate>
        {error && <div className="error-summary" role="alert">{error}</div>}
        <Field label="Asset" required error={fieldErrors.asset}>
          {asset ? (
            <input className="input" value={`${asset.asset_tag} — ${asset.name}`} disabled />
          ) : (
            <AssetSelect value={form.asset} onChange={set('asset')} disabled={busy} />
          )}
        </Field>
        <Field label="Reason for disposal" required error={fieldErrors.disposal_reason}>
          <textarea className="input" rows={3} value={form.disposal_reason}
            onChange={(e) => set('disposal_reason')(e.target.value)} disabled={busy}
            placeholder="Why is this asset being removed from service?" />
        </Field>
        <div className="form-grid">
          <Field label="Method" error={fieldErrors.disposal_method}>
            <select className="input" value={form.disposal_method}
              onChange={(e) => set('disposal_method')(e.target.value)} disabled={busy}>
              {DISPOSAL_METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          <Field label="Residual value" error={fieldErrors.disposal_value}>
            <input className="input" type="number" step="0.01" min="0"
              value={form.disposal_value} onChange={(e) => set('disposal_value')(e.target.value)}
              disabled={busy} placeholder="0.00" />
          </Field>
        </div>
        <Field label="Responsible person" error={fieldErrors.responsible_person}
          hint="Person carrying out the disposal (optional).">
          <UserSelect value={form.responsible_person} onChange={set('responsible_person')}
            disabled={busy} label="Responsible person" />
        </Field>
        <Field label="Notes" error={fieldErrors.notes}>
          <textarea className="input" rows={2} value={form.notes}
            onChange={(e) => set('notes')(e.target.value)} disabled={busy} />
        </Field>
        <p className="muted small" style={{ marginTop: 0 }}>
          New requests start as <strong>pending approval</strong>. A second IT staff member can
          approve or reject, and only approved disposals can be completed.
        </p>
        <div className="row-end">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Submitting…' : 'Request disposal'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function buildDisposalUrl(filters) {
  const p = new URLSearchParams();
  for (const k of ['q', 'approval_status', 'disposal_method']) {
    if (filters[k]) p.set(k, filters[k]);
  }
  if (filters.completed) p.set('completed', filters.completed);
  p.set('page_size', '50');
  return `/assets/disposals/?${p.toString()}`;
}

export function Disposals() {
  const { isStaff } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [f, setF] = useState({ q: '', approval_status: '', disposal_method: '', completed: '' });
  const [createOpen, setCreateOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [busyRow, setBusyRow] = useState(null);
  const [confirm, setConfirm] = useState(null); // {action, record}

  const url = useMemo(() => buildDisposalUrl(f), [f]);

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
      setError('Could not load disposal requests.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(url); }, [url]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (action, record) => {
    setBusyRow(record.id);
    setMsg('');
    setError('');
    try {
      await api.post(`/assets/disposals/${record.id}/${action}/`);
      const verb = action === 'approve' ? 'approved' : action === 'reject' ? 'rejected' : 'completed';
      setMsg(`Disposal for ${record.asset_tag} ${verb}.`);
      setConfirm(null);
      await load();
    } catch (e) {
      setError(parseApiError(e).global || `Could not ${action} this disposal.`);
      setConfirm(null);
    } finally {
      setBusyRow(null);
    }
  };

  if (!isStaff) {
    return <div className="error-summary" role="alert">Only IT staff can manage asset disposals.</div>;
  }

  const columns = [
    { key: 'asset', label: 'Asset', render: (d) => (
      <a className="row-title" href={`#/assets/${d.asset}`}>{d.asset_tag}</a>
    ) },
    { key: 'asset_name', label: 'Name', render: (d) => (
      <span className="ellipsis" title={d.asset_name}>{d.asset_name}</span>
    ) },
    { key: 'disposal_reason', label: 'Reason', render: (d) => (
      <span className="ellipsis" title={d.disposal_reason}>{d.disposal_reason}</span>
    ) },
    { key: 'disposal_method', label: 'Method', render: (d) => (
      <span className="muted small">{d.disposal_method?.replace(/_/g, ' ')}</span>
    ) },
    { key: 'approval_status', label: 'Approval', render: (d) => (
      <Badge kind="status" value={d.approval_status} label={APPROVAL_LABELS[d.approval_status]} />
    ) },
    { key: 'disposal_value', label: 'Value', render: (d) => (d.disposal_value != null ? fmtMoney(d.disposal_value) : <span className="cell-muted">—</span>) },
    { key: 'responsible_person', label: 'Responsible', render: (d) => d.responsible_person_email || <span className="cell-muted">—</span> },
    { key: 'created_at', label: 'Requested', render: (d) => (
      <span className="muted small">{fmtDateTime(d.created_at)}<br />{d.created_by_email || '—'}</span>
    ) },
    { key: 'disposal_date', label: 'Disposed', render: (d) => (d.disposal_date ? fmtDateTime(d.disposal_date) : <span className="cell-muted">—</span>) },
    { key: 'actions', label: 'Actions', thClass: 'table-actions', render: (d) => (
      <span className="row-gap" style={{ gap: 'var(--sp-1)' }}>
        {d.approval_status === 'pending' && !d.is_completed && (
          <>
            <button type="button" className="btn-small" disabled={busyRow === d.id}
              onClick={() => setConfirm({ action: 'approve', record: d })}>Approve</button>
            <button type="button" className="btn-small btn-danger" disabled={busyRow === d.id}
              onClick={() => setConfirm({ action: 'reject', record: d })}>Reject</button>
          </>
        )}
        {d.approval_status === 'approved' && !d.is_completed && (
          <button type="button" className="btn-small btn-danger" disabled={busyRow === d.id}
            onClick={() => setConfirm({ action: 'complete', record: d })}>Complete…</button>
        )}
        {d.is_completed && <span className="muted small">Completed</span>}
      </span>
    ) },
  ];

  const confirmCopy = confirm && {
    approve: {
      title: `Approve disposal for ${confirm.record.asset_tag}?`,
      message: 'The asset can then be disposed. Completing the disposal removes it from service permanently.',
      label: 'Approve', danger: false,
    },
    reject: {
      title: `Reject disposal for ${confirm.record.asset_tag}?`,
      message: 'The request stays on record as rejected and the asset remains in service.',
      label: 'Reject', danger: true,
    },
    complete: {
      title: `Complete disposal for ${confirm.record.asset_tag}?`,
      message: 'This sets the asset to disposed, clears its holder, closes open assignments, and cannot be undone.',
      label: 'Complete disposal', danger: true,
    },
  }[confirm.action];

  return (
    <div>
      <PageHeader
        title="Asset disposals"
        sub={count != null ? `${count} disposal ${count === 1 ? 'request' : 'requests'}` : undefined}
        actions={<>
          <button type="button" className="btn-primary" onClick={() => setCreateOpen(true)}>+ Request disposal</button>
          <button type="button" className="btn-secondary" onClick={() => setExportOpen(true)}>Export…</button>
        </>}
      />
      {exportOpen && (
        <ExportDialog
          dataset="disposals" open={exportOpen}
          filterParams={{ q: f.q, approval_status: f.approval_status, disposal_method: f.disposal_method, completed: f.completed }}
          onClose={() => setExportOpen(false)}
        />
      )}
      {error && <div className="error-summary" role="alert">{error}</div>}
      {msg && <div className="success-summary" role="status">{msg}</div>}
      <div className="filter-bar" role="search">
        <input className="input grow" value={f.q}
          onChange={(e) => setF((prev) => ({ ...prev, q: e.target.value }))}
          placeholder="Search asset tag, name, reason…" aria-label="Search disposals" />
        <select className="input" value={f.approval_status}
          onChange={(e) => setF((prev) => ({ ...prev, approval_status: e.target.value }))}
          aria-label="Filter by approval status">
          <option value="">All approvals</option>
          <option value="pending">Pending approval</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
        <select className="input" value={f.disposal_method}
          onChange={(e) => setF((prev) => ({ ...prev, disposal_method: e.target.value }))}
          aria-label="Filter by disposal method">
          <option value="">All methods</option>
          {DISPOSAL_METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select className="input" value={f.completed}
          onChange={(e) => setF((prev) => ({ ...prev, completed: e.target.value }))}
          aria-label="Filter by completion">
          <option value="">Any completion</option>
          <option value="false">Not completed</option>
          <option value="true">Completed</option>
        </select>
      </div>
      <div className="panel">
        {loading ? <div className="panel-pad"><LoadingRows n={6} /></div>
          : (
            <>
              <DataTable
                columns={columns} rows={items} keyOf={(d) => d.id}
                emptyTitle="No disposal requests match."
                emptyHint="Request a disposal from here or from an asset's detail page."
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
        Disposal is separate from retirement and loss. Only approved disposals can be completed,
        and completing one permanently removes the asset from service.
      </p>
      {createOpen && (
        <DisposalFormModal onClose={() => setCreateOpen(false)} onSaved={() => load()} />
      )}
      {confirm && confirmCopy && (
        <ConfirmDialog
          title={confirmCopy.title} message={confirmCopy.message}
          confirmLabel={confirmCopy.label} danger={confirmCopy.danger}
          busy={busyRow === confirm.record.id}
          onConfirm={() => act(confirm.action, confirm.record)}
          onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  );
}
