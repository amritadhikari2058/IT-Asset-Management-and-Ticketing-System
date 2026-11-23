import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, Field, Modal, PageHeader, Pager,
} from './components';
import { fetchPage, parseApiError } from './api-utils';

const CATEGORIES = [
  { value: 'security_events', label: 'Security events' },
  { value: 'notifications', label: 'Notifications' },
  { value: 'background_task_runs', label: 'Background task runs' },
  { value: 'temporary_import_reports', label: 'Temporary import reports' },
  { value: 'expired_temporary_records', label: 'Expired temporary records' },
  { value: 'other', label: 'Other operational data' },
];

/** Data-retention governance page.
 *
 * Hash-based sub-views:
 *   #/retention             policy list + create/edit/enable-disable
 *   #/retention/policies    same as #/retention
 *   #/retention/executions  execution history
 *
 * Retention policies are System Admin only. Audit logs (security events)
 * are never automatically deleted by a retention policy.
 */
export function Retention() {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return (
      <div>
        <div className="page-head"><h1>Data Retention</h1></div>
        <div className="empty-state">
          <div className="empty-title">Access restricted</div>
          <div className="small">Data-retention governance is System Admin only.</div>
        </div>
      </div>
    );
  }

  const hash = location.hash.split('?')[0];
  if (hash === '#/retention/executions') return <RetentionExecutions />;
  return <RetentionPolicies />;
}

/* ---------------- Policies ---------------- */

function RetentionPolicies() {
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({
    name: '', data_category: 'notifications', retention_duration: 30,
    enabled: true, conditions: {}, description: '', responsible_admin: '',
  });
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState('');
  const [formMsg, setFormMsg] = useState('');

  const [previewFor, setPreviewFor] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [execBusy, setExecBusy] = useState(null);
  const [execMsg, setExecMsg] = useState('');

  const load = async () => {
    setLoading(true); setError('');
    try {
      const p = new URLSearchParams({ page, page_size: 20 });
      const d = await fetchPage(`/common/retention-policies/?${p.toString()}`);
      setItems(d.items); setCount(d.count); setNext(d.next);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load policies.');
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [page]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect

  const setField = (k) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setForm((s) => ({ ...s, [k]: v }));
  };

  const openForm = (p = null) => {
    setEditing(p);
    if (p) {
      setForm({
        name: p.name, data_category: p.data_category,
        retention_duration: p.retention_duration, enabled: p.enabled,
        conditions: p.conditions || {}, description: p.description || '',
        responsible_admin: p.responsible_admin || '',
      });
    } else {
      setForm({ name: '', data_category: 'notifications', retention_duration: 30, enabled: true, conditions: {}, description: '', responsible_admin: '' });
    }
    setFormError(''); setFormMsg('');
    setShowForm(true);
  };

  const saveForm = async (ev) => {
    ev.preventDefault();
    setFormBusy(true); setFormError(''); setFormMsg('');
    try {
      const payload = {
        name: form.name, data_category: form.data_category,
        retention_duration: Number(form.retention_duration),
        enabled: form.enabled, conditions: form.conditions,
        description: form.description,
        responsible_admin: form.responsible_admin ? Number(form.responsible_admin) : null,
      };
      if (editing) {
        await api.patch(`/common/retention-policies/${editing.id}/`, payload);
        setFormMsg('Policy updated.');
      } else {
        await api.post('/common/retention-policies/', payload);
        setFormMsg('Policy created.');
      }
      setShowForm(false); load();
    } catch (e) {
      const p = parseApiError(e);
      setFormError(p.global || p.fields.data_category || 'Failed to save policy.');
    } finally { setFormBusy(false); }
  };

  const toggleEnabled = async (policy) => {
    setExecBusy(policy.id);
    try {
      await api.patch(`/common/retention-policies/${policy.id}/`, { enabled: !policy.enabled });
      setExecMsg(`${policy.name} ${policy.enabled ? 'disabled' : 'enabled'}.`);
      load();
    } catch (e) {
      setExecMsg(parseApiError(e).global || 'Failed to update policy.');
    } finally { setExecBusy(null); }
  };

  const removePolicy = async (id) => {
    if (!window.confirm('Delete this retention policy?')) return;
    setExecBusy(id);
    try {
      await api.delete(`/common/retention-policies/${id}/`);
      load();
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to delete policy.');
    } finally { setExecBusy(null); }
  };

  const showPreview = async (policy) => {
    setPreviewFor(policy.id); setPreview(null); setPreviewLoading(true);
    try {
      const r = await api.get(`/common/retention-policies/${policy.id}/preview/`);
      setPreview(r.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Preview failed.');
    } finally { setPreviewLoading(false); }
  };

  const execute = async (policy) => {
    setExecBusy(policy.id); setExecMsg('');
    try {
      const r = await api.post(`/common/retention-policies/${policy.id}/execute/`, {});
      setExecMsg(`Executed: ${r.data.records_affected || 0} record(s) affected, ${r.data.records_excluded || 0} excluded.`);
      load();
    } catch (e) {
      setExecMsg(parseApiError(e).global || 'Execution failed.');
    } finally { setExecBusy(null); }
  };

  const POLICY_COLUMNS = [
    { key: 'name', label: 'Name', render: (r) => <span className="row-title">{r.name}</span> },
    { key: 'category', label: 'Category', render: (r) => r.data_category },
    { key: 'duration', label: 'Retention (days)', render: (r) => r.retention_duration },
    { key: 'enabled', label: 'Enabled', render: (r) => r.enabled ? <Badge kind="status" value="resolved" label="On" /> : <Badge kind="status" value="reopened" label="Off" /> },
    { key: 'last_run', label: 'Last run', render: (r) => r.last_run_at ? new Date(r.last_run_at).toLocaleString() : <span className="cell-muted">—</span> },
    { key: 'actions', label: 'Actions', thClass: 'cell-actions', render: (r) => (
      <div className="cell-actions">
        <button type="button" className="btn-small" onClick={() => openForm(r)} disabled={formBusy}>Edit</button>
        <button type="button" className="btn-small" onClick={() => toggleEnabled(r)} disabled={execBusy === r.id || formBusy}>
          {execBusy === r.id ? '…' : (r.enabled ? 'Disable' : 'Enable')}
        </button>
        <button type="button" className="btn-small" onClick={() => showPreview(r)} disabled={previewLoading}>Preview</button>
        <button type="button" className="btn-small btn-primary" onClick={() => execute(r)} disabled={execBusy === r.id || !r.enabled || formBusy}>
          {execBusy === r.id ? '…' : 'Execute'}
        </button>
        <button type="button" className="btn-small btn-danger" onClick={() => removePolicy(r.id)} disabled={execBusy === r.id || formBusy}>Delete</button>
      </div>
    )},
  ];

  return (
    <div>
      <PageHeader title="Data retention policies" sub="Configure, preview and execute retention policies. System Admin only."
        actions={(
          <div className="row-gap">
            <a href="#/retention/executions" className="btn-secondary">Execution history</a>
            <button type="button" className="btn-primary" onClick={() => openForm()}>+ Add policy</button>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <DataTable columns={POLICY_COLUMNS} rows={items} keyOf={(r) => String(r.id)}
        emptyTitle="No retention policies." emptyHint="Create your first retention policy." />
      <Pager count={count} onPrev={() => setPage(p => p - 1)} onNext={() => setPage(p => p + 1)}
             hasPrev={page > 1} hasNext={!!next} busy={loading} />

      {showForm && (
        <Modal title={editing ? 'Edit retention policy' : 'Add retention policy'} onClose={() => setShowForm(false)} size="lg">
          <form onSubmit={saveForm} noValidate>
            <Field label="Name" required>
              <input className="input input-auto" value={form.name} onChange={setField('name')} disabled={formBusy} />
            </Field>
            <Field label="Data category">
              <select className="input" value={form.data_category} onChange={setField('data_category')} disabled={formBusy}>
                {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
              <div className="small">Audit logs (security events) are never automatically deleted.</div>
            </Field>
            <Field label="Retention duration (days)" required>
              <input className="input input-auto" type="number" value={form.retention_duration || ''} onChange={setField('retention_duration')} disabled={formBusy} />
            </Field>
            <Field label="Enabled">
              <input type="checkbox" checked={form.enabled} onChange={setField('enabled')} disabled={formBusy} />
            </Field>
            <Field label="Description">
              <input className="input input-auto" value={form.description} onChange={setField('description')} disabled={formBusy} />
            </Field>
            <Field label="Responsible admin (ID)">
              <input className="input input-auto" value={form.responsible_admin} onChange={setField('responsible_admin')} disabled={formBusy} />
            </Field>
            {formError && <div className="field-error" role="alert">{formError}</div>}
            {formMsg && <div className="success-summary" role="status">{formMsg}</div>}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setShowForm(false)} disabled={formBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={formBusy}>{formBusy ? 'Saving…' : 'Save'}</button>
            </div>
          </form>
        </Modal>
      )}

      {previewFor && preview !== null && (
        <Modal title={`Preview: ${preview.policy_name}`} onClose={() => setPreviewFor(null)} size="lg">
          <div className="panel-pad">
            <div className="field"><span className="form-label">Category</span><div className="small">{preview.data_category}</div></div>
            <div className="field"><span className="form-label">Retention (days)</span><div className="small">{preview.retention_duration_days}</div></div>
            <div className="field"><span className="form-label">Eligible records</span><div className="small">{preview.total_eligible}</div></div>
            <div className="field"><span className="form-label">Can execute</span>{' '}
              {preview.can_execute ? <span className="badge badge-green">Yes</span> : <span className="badge badge-red">No</span>}</div>
            {preview.excluded && preview.excluded.length > 0 && (
              <div className="field"><span className="form-label">Excluded</span>
                <ul className="small-list">
                  {preview.excluded.map((e, i) => <li key={i}>{e.model}: {e.reason}</li>)}
                </ul>
              </div>
            )}
            {(preview.notes || []).length > 0 && (
              <div className="field"><span className="form-label">Notes</span>
                <ul className="small-list">
                  {preview.notes.map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              </div>
            )}
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={() => setPreviewFor(null)}>Close</button>
              {preview.can_execute && (
                <button type="button" className="btn-primary" onClick={() => { setPreviewFor(null); execute(preview.policy_id ? { id: preview.policy_id, name: preview.policy_name, enabled: true } : null); }}>
                  Execute now
                </button>
              )}
            </div>
          </div>
        </Modal>
      )}

      {execMsg && <div className={`field-error ${execMsg.startsWith('Executed') ? 'success-summary' : ''}`} role="status">{execMsg}</div>}
    </div>
  );
}

/* ---------------- Execution history ---------------- */

function RetentionExecutions() {
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);

  const load = async () => {
    setLoading(true); setError('');
    try {
      const p = new URLSearchParams({ page, page_size: 20 });
      const d = await fetchPage(`/common/retention-executions/?${p.toString()}`);
      setItems(d.items); setCount(d.count); setNext(d.next);
    } catch (e) {
      setError(parseApiError(e).global || 'Failed to load execution history.');
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [page]); // eslint-disable-line react-hooks/exhaustive-deps, react/set-state-in-effect

  return (
    <div>
      <PageHeader title="Retention execution history" sub="Per-policy retention execution outcomes and failure reporting."
        actions={(
          <div className="row-gap">
            <a href="#/retention" className="btn-ghost">&larr; Back to policies</a>
          </div>
        )} />
      {error ? <div className="field-error" role="alert">{error}</div> : null}
      <DataTable columns={[
        { key: 'policy', label: 'Policy', render: (r) => <span className="row-title">Policy #{r.policy}</span> },
        { key: 'status', label: 'Status', render: (r) => <Badge kind="status" value={r.status} label={r.status} /> },
        { key: 'eligible', label: 'Eligible', render: (r) => r.records_eligible },
        { key: 'affected', label: 'Affected', render: (r) => r.records_affected },
        { key: 'excluded', label: 'Excluded', render: (r) => r.records_excluded },
        { key: 'started', label: 'Started', render: (r) => r.started_at ? new Date(r.started_at).toLocaleString() : '—' },
        { key: 'error', label: 'Error', render: (r) => <span className="cell-muted">{r.error_summary || '—'}</span> },
      ]} rows={items} keyOf={(r) => String(r.id)}
        emptyTitle="No retention executions." emptyHint="Run a retention policy to record its execution here." />
      <Pager count={count} onPrev={() => setPage(p => p - 1)} onNext={() => setPage(p => p + 1)}
             hasPrev={page > 1} hasNext={!!next} busy={loading} />
    </div>
  );
}
