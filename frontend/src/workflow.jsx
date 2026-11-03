import React, { useEffect, useState } from 'react';
import api from './api';

const TRIGGERS = [
  { value: 'ticket_created', label: 'Ticket Created' },
  { value: 'ticket_updated', label: 'Ticket Updated' },
  { value: 'status_changed', label: 'Status Changed' },
];

const CONDITION_EXAMPLE = { category_id: 1, priority: 'high', department_id: 2, status: 'open' };
const ACTION_EXAMPLE = [{ type: 'assign', user_id: 5 }, { type: 'priority', value: 'high' }];

export default function Workflow() {
  const [rules, setRules] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [executions, setExecutions] = useState([]);
  const [loading, setLoading] = useState(true);

  const [name, setName] = useState('');
  const [trigger, setTrigger] = useState('ticket_created');

  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({
    name: '',
    description: '',
    trigger: 'ticket_created',
    is_enabled: true,
    conditions: {},
    actions: [],
  });
  const [editErrors, setEditErrors] = useState({});
  const [editLoading, setEditLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [r, a, e] = await Promise.all([
        api.get('/workflow/automation-rules/'),
        api.get('/workflow/approval-requests/'),
        api.get('/workflow/rule-executions/').catch(() => ({ data: [] })),
      ]);
      setRules(r.data.results || r.data);
      setApprovals(a.data.results || a.data);
      setExecutions(e.data.results || e.data);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const createRule = async (e) => {
    e.preventDefault();
    await api.post('/workflow/automation-rules/', { name, trigger, conditions: {}, actions: [], created_by: null }, { headers: {} });
    setName(''); load();
  };

  const toggle = async (rule) => {
    await api.patch(`/workflow/automation-rules/${rule.id}/`, { is_enabled: !rule.is_enabled });
    load();
  };

  const openEdit = (rule) => {
    setEditForm({
      name: rule.name || '',
      description: rule.description || '',
      trigger: rule.trigger || 'ticket_created',
      is_enabled: rule.is_enabled !== undefined ? rule.is_enabled : true,
      conditions: typeof rule.conditions === 'object' && rule.conditions !== null ? rule.conditions : {},
      actions: Array.isArray(rule.actions) ? rule.actions : [],
    });
    setEditErrors({});
    setEditingId(rule.id);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditErrors({});
  };

  const validateEdit = () => {
    const errors = {};
    if (!editForm.name || !editForm.name.trim()) errors.name = 'Rule name is required';
    try {
      JSON.stringify(editForm.conditions);
    } catch { errors.conditions = 'Conditions must be valid JSON'; }
    try {
      JSON.stringify(editForm.actions);
    } catch { errors.actions = 'Actions must be valid JSON'; }
    setEditErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const saveEdit = async (e) => {
    e.preventDefault();
    if (!validateEdit()) return;
    setEditLoading(true);
    try {
      await api.patch(`/workflow/automation-rules/${editingId}/`, {
        name: editForm.name.trim(),
        description: editForm.description,
        trigger: editForm.trigger,
        is_enabled: editForm.is_enabled,
        conditions: editForm.conditions,
        actions: editForm.actions,
      });
      setEditingId(null);
      setEditErrors({});
      load();
    } catch (err) {
      const data = err.response && err.response.data;
      if (data && typeof data === 'object') {
        setEditErrors(data);
      } else {
        setEditErrors({ __form: data && data.detail ? data.detail : 'Failed to save rule' });
      }
    } finally {
      setEditLoading(false);
    }
  };

  const approve = async (id) => {
    await api.post(`/workflow/approval-requests/${id}/approve/`, { comment: 'approved' });
    load();
  };

  if (loading) return <div className="p-3" role="status" aria-label="Loading">Loading...</div>;

  return (
    <div className="container-fluid p-3">
      <h3>Workflow Management</h3>

      <form className="mb-4 row g-2" onSubmit={createRule}>
        <div className="col-md-3">
          <input className="form-control" placeholder="Rule name" value={name} onChange={e => setName(e.target.value)} />
        </div>
        <div className="col-md-3">
          <select className="form-select" value={trigger} onChange={e => setTrigger(e.target.value)}>
            {TRIGGERS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <div className="col-md-2 d-flex align-items-end">
          <button className="btn btn-primary w-100" type="submit">Create Rule</button>
        </div>
      </form>

      <h5>Rules</h5>
      {editingId !== null ? (
        <div className="card mb-3">
          <div className="card-header">Edit Automation Rule</div>
          <div className="card-body">
            <form onSubmit={saveEdit}>
              <div className="mb-3">
                <label className="form-label">Rule name</label>
                <input className="form-control" value={editForm.name} onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} />
                {editErrors.name && <div className="text-danger small">{editErrors.name}</div>}
              </div>
              <div className="mb-3">
                <label className="form-label">Description</label>
                <textarea className="form-control" rows={2} value={editForm.description} onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))} />
              </div>
              <div className="mb-3">
                <label className="form-label">Trigger</label>
                <select className="form-select" value={editForm.trigger} onChange={e => setEditForm(f => ({ ...f, trigger: e.target.value }))}>
                  {TRIGGERS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>
              <div className="mb-3 form-check">
                <input className="form-check-input" type="checkbox" checked={editForm.is_enabled} onChange={e => setEditForm(f => ({ ...f, is_enabled: e.target.checked }))} />
                <label className="form-check-label">Enabled</label>
              </div>
              <div className="mb-3">
                <label className="form-label">Conditions (JSON)</label>
                <textarea className="form-control" rows={3} value={JSON.stringify(editForm.conditions, null, 2)} onChange={e => {
                  try { setEditForm(f => ({ ...f, conditions: JSON.parse(e.target.value) })); } catch { /* keep invalid, show error on submit */ }
                }} />
                <div className="form-text small">Supported keys: category_id, priority, department_id, status. Example: {JSON.stringify(CONDITION_EXAMPLE)}</div>
                {editErrors.conditions && <div className="text-danger small">{editErrors.conditions}</div>}
              </div>
              <div className="mb-3">
                <label className="form-label">Actions (JSON array)</label>
                <textarea className="form-control" rows={4} value={JSON.stringify(editForm.actions, null, 2)} onChange={e => {
                  try { setEditForm(f => ({ ...f, actions: JSON.parse(e.target.value) })); } catch { /* keep invalid, show error on submit */ }
                }} />
                <div className="form-text small">Supported types: assign, priority, status, note, notify. Example: {JSON.stringify(ACTION_EXAMPLE)}</div>
                {editErrors.actions && <div className="text-danger small">{editErrors.actions}</div>}
              </div>
              {editErrors.__form && <div className="alert alert-danger mb-3" role="alert">{editErrors.__form}</div>}
              <div className="d-flex gap-2">
                <button className="btn btn-primary" type="submit" disabled={editLoading}>{editLoading ? 'Saving…' : 'Save Changes'}</button>
                <button className="btn btn-outline-secondary" type="button" onClick={cancelEdit}>Cancel</button>
              </div>
            </form>
          </div>
        </div>
      ) : (
        <ul className="list-group mb-3">
          {rules.map(r => (
            <li key={r.id} className="list-group-item d-flex justify-content-between align-items-center">
              <span>{r.name} <span className="text-muted small">- {r.trigger}</span></span>
              <div className="d-flex gap-1">
                <span className={`badge ${r.is_enabled ? 'bg-success' : 'bg-secondary'}`}>{r.is_enabled ? 'enabled' : 'disabled'}</span>
                <button className="btn btn-sm btn-outline-secondary" onClick={() => toggle(r)}>{r.is_enabled ? 'Disable' : 'Enable'}</button>
                <button className="btn btn-sm btn-primary" onClick={() => openEdit(r)}>Edit</button>
              </div>
            </li>
          ))}
          {rules.length === 0 && <li className="list-group-item text-muted">No automation rules defined.</li>}
        </ul>
      )}

      <h5>Execution History</h5>
      <ul className="list-group mb-3">
        {executions.map(x => <li key={x.id} className="list-group-item">#{x.id} {x.success ? 'OK' : 'FAIL'} - {x.detail}</li>)}
        {executions.length === 0 && <li className="list-group-item text-muted">No executions recorded.</li>}
      </ul>
      <h5>Approvals</h5>
      <ul className="list-group">
        {approvals.map(a => (
          <li key={a.id} className="list-group-item d-flex justify-content-between">
            <span>#{a.id} {a.status}</span>
            {a.status === 'pending' && <button className="btn btn-sm btn-success" onClick={() => approve(a.id)}>Approve</button>}
          </li>
        ))}
        {approvals.length === 0 && <li className="list-group-item text-muted">No pending approvals.</li>}
      </ul>
    </div>
  );
}
