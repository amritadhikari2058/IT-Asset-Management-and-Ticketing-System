import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, ConfirmDialog, DataTable, EmptyState, ErrorSummary, Field,
  LoadingRows, PageHeader, Pager,
} from './components';
import { fetchPage, fieldMsg, parseApiError } from './api-utils';

const TRIGGERS = [
  { value: 'ticket_created', label: 'Ticket Created' },
  { value: 'ticket_updated', label: 'Ticket Updated' },
  { value: 'status_changed', label: 'Status Changed' },
];

const PRIORITIES = ['low', 'medium', 'high', 'critical'];
const TICKET_STATUSES = ['open', 'in_progress', 'resolved', 'closed', 'reopened', 'archived'];
const CONDITION_IDS = ['category_id', 'department_id'];
const CONDITION_ENUMS = {
  priority: PRIORITIES,
  status: TICKET_STATUSES,
};
const ACTION_TYPES = [
  { value: 'assign', label: 'Assign user' },
  { value: 'priority', label: 'Set priority' },
  { value: 'status', label: 'Set status' },
  { value: 'note', label: 'Add internal note' },
  { value: 'notify', label: 'Send notification' },
];
const OPERATIONS = [
  { value: 'other', label: 'Other' },
  { value: 'change_priority', label: 'Change priority' },
  { value: 'change_status', label: 'Change status' },
  { value: 'reassign', label: 'Reassign' },
];

const fmtDateTime = (value) => (value ? new Date(value).toLocaleString() : '—');

function titleize(value) {
  return String(value ?? '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function triggerLabel(value) {
  return TRIGGERS.find((t) => t.value === value)?.label ?? titleize(value);
}

function apiMessage(value) {
  if (Array.isArray(value)) return value.join(' ');
  if (value && typeof value === 'object') return JSON.stringify(value);
  return String(value ?? '');
}

/** Map AutomationRuleSerializer errors (including nested conditions/actions)
 * to keys the structured form can render next to the field that failed. */
function ruleApiErrors(e) {
  const data = e?.response?.data;
  if (!data || typeof data !== 'object') {
    return { __form: parseApiError(e).global || 'Could not save rule.' };
  }
  const out = {};
  for (const [key, value] of Object.entries(data)) {
    if (key === 'conditions' || key === 'actions') {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        for (const [sub, msg] of Object.entries(value)) {
          out[`${key}.${sub}`] = apiMessage(msg);
        }
        continue;
      }
    }
    if (key === 'detail' || key === 'non_field_errors') out.__form = apiMessage(value);
    else out[key] = apiMessage(value);
  }
  if (!Object.keys(out).length) out.__form = 'Could not save rule.';
  return out;
}

function emptyRuleForm() {
  return {
    name: '',
    description: '',
    trigger: 'ticket_created',
    is_enabled: true,
    conditions: { category_id: '', department_id: '', priority: '', status: '' },
    actions: [],
  };
}

function actionToForm(action) {
  return {
    type: ACTION_TYPES.some((t) => t.value === action?.type) ? action.type : 'note',
    user_id: action?.user_id ?? '',
    value: action?.value ?? '',
    text: action?.text ?? '',
  };
}

function ruleToForm(rule) {
  const conditions = rule?.conditions && typeof rule.conditions === 'object' ? rule.conditions : {};
  return {
    name: rule?.name ?? '',
    description: rule?.description ?? '',
    trigger: rule?.trigger ?? 'ticket_created',
    is_enabled: rule?.is_enabled !== false,
    conditions: {
      category_id: conditions.category_id ?? '',
      department_id: conditions.department_id ?? '',
      priority: conditions.priority ?? '',
      status: conditions.status ?? '',
    },
    actions: Array.isArray(rule?.actions) ? rule.actions.map(actionToForm) : [],
  };
}

function validateRuleForm(form) {
  const errors = {};
  if (!form.name || !form.name.trim()) errors.name = 'Rule name is required.';
  if (!TRIGGERS.some((t) => t.value === form.trigger)) errors.trigger = 'Choose a supported trigger.';
  for (const key of CONDITION_IDS) {
    const value = form.conditions[key];
    if (value !== '' && (!/^\d+$/.test(String(value)) || Number(value) < 1)) {
      errors[`conditions.${key}`] = 'Enter a positive numeric id, or leave blank.';
    }
  }
  for (const [key, allowed] of Object.entries(CONDITION_ENUMS)) {
    const value = form.conditions[key];
    if (value && !allowed.includes(value)) {
      errors[`conditions.${key}`] = `Choose one of: ${allowed.join(', ')}.`;
    }
  }
  form.actions.forEach((action, i) => {
    const key = `actions.${i}`;
    if (!ACTION_TYPES.some((t) => t.value === action.type)) {
      errors[key] = 'Choose an action type.';
      return;
    }
    if (action.type === 'assign') {
      if (!/^\d+$/.test(String(action.user_id)) || Number(action.user_id) < 1) {
        errors[key] = 'Assign requires a positive user id.';
      }
    } else if (action.type === 'notify') {
      if (action.user_id !== '' && (!/^\d+$/.test(String(action.user_id)) || Number(action.user_id) < 1)) {
        errors[key] = 'Notification user id must be a positive number, or blank for assignee/requester.';
      }
    } else if (action.type === 'priority') {
      if (!PRIORITIES.includes(action.value)) errors[key] = `Choose a priority (${PRIORITIES.join(', ')}).`;
    } else if (action.type === 'status') {
      if (!TICKET_STATUSES.includes(action.value)) errors[key] = `Choose a status (${TICKET_STATUSES.join(', ')}).`;
    } else if (action.type === 'note') {
      if (!action.text || !action.text.trim()) errors[key] = 'Note text is required.';
    }
  });
  return errors;
}

function rulePayload(form) {
  const conditions = {};
  for (const key of CONDITION_IDS) {
    if (form.conditions[key] !== '') conditions[key] = Number(form.conditions[key]);
  }
  for (const key of Object.keys(CONDITION_ENUMS)) {
    if (form.conditions[key]) conditions[key] = form.conditions[key];
  }
  const actions = form.actions.map((action) => {
    if (action.type === 'assign') return { type: 'assign', user_id: Number(action.user_id) };
    if (action.type === 'notify') {
      return { type: 'notify', user_id: action.user_id === '' ? null : Number(action.user_id) };
    }
    if (action.type === 'note') return { type: 'note', text: action.text.trim() };
    return { type: action.type, value: action.value };
  });
  return {
    name: form.name.trim(),
    description: form.description,
    trigger: form.trigger,
    is_enabled: form.is_enabled,
    conditions,
    actions,
  };
}

function actionSummary(action) {
  if (!action || typeof action !== 'object') return 'Invalid action';
  if (action.type === 'assign') return `Assign user #${action.user_id}`;
  if (action.type === 'priority') return `Set priority to ${titleize(action.value)}`;
  if (action.type === 'status') return `Set status to ${titleize(action.value)}`;
  if (action.type === 'note') return `Add internal note: “${action.text}”`;
  if (action.type === 'notify') {
    return action.user_id == null
      ? 'Notify the assignee (or requester when unassigned)'
      : `Notify user #${action.user_id}`;
  }
  return `Unknown action (${action.type ?? 'missing type'})`;
}

function conditionsSummary(conditions) {
  const entries = Object.entries(conditions || {});
  if (!entries.length) return ['Always matches (no conditions).'];
  return entries.map(([key, value]) => `${titleize(key)} = ${titleize(value)}`);
}

function contextSummary(context) {
  const entries = Object.entries(context || {});
  if (!entries.length) return ['No extra context.'];
  return entries.map(([key, value]) => `${titleize(key)}: ${typeof value === 'object' ? JSON.stringify(value) : value}`);
}

function FieldError({ text }) {
  return text ? <div className="field-error" role="alert">{text}</div> : null;
}

function Loading() {
  return (
    <div className="panel-pad">
      <LoadingRows n={5} />
    </div>
  );
}

function LoadError({ message, onRetry }) {
  return (
    <div className="panel-pad">
      <div className="error-summary" role="alert">
        {message}
        {onRetry && <button type="button" className="btn-small" onClick={onRetry}>Retry</button>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Automation rules                                                    */
/* ------------------------------------------------------------------ */

function RuleForm({ rule, onCancel, onSaved }) {
  const [form, setForm] = useState(() => ruleToForm(rule));
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  const setField = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));
  const setCondition = (key) => (value) => setForm((f) => ({
    ...f, conditions: { ...f.conditions, [key]: value },
  }));
  const setAction = (index, key, value) => setForm((f) => ({
    ...f,
    actions: f.actions.map((a, i) => (i === index ? { ...a, [key]: value } : a)),
  }));
  const setActionType = (index, type) => setForm((f) => ({
    ...f,
    actions: f.actions.map((a, i) => (i === index
      ? { type, user_id: '', value: '', text: '' }
      : a)),
  }));
  const addAction = () => setForm((f) => ({
    ...f, actions: [...f.actions, { type: 'note', user_id: '', value: '', text: '' }],
  }));
  const removeAction = (index) => setForm((f) => ({
    ...f, actions: f.actions.filter((_, i) => i !== index),
  }));

  const submit = async (ev) => {
    ev.preventDefault();
    if (saving) return;
    const nextErrors = validateRuleForm(form);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    setSaving(true);
    try {
      const res = await api.patch(`/workflow/automation-rules/${rule.id}/`, rulePayload(form));
      onSaved(res.data);
    } catch (e) {
      setErrors(ruleApiErrors(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate className="panel">
      <div className="panel-pad">
        <ErrorSummary parsed={{ global: errors.__form }} />
        <Field label="Rule name" required error={fieldMsg(errors, 'name')}>
          <input
            className="input" value={form.name} maxLength={120}
            onChange={(e) => setField('name')(e.target.value)} disabled={saving}
          />
        </Field>
        <Field label="Description" error={fieldMsg(errors, 'description')}>
          <textarea
            className="input" rows={2} value={form.description}
            onChange={(e) => setField('description')(e.target.value)} disabled={saving}
          />
        </Field>
        <div className="form-grid">
          <Field label="Trigger" required error={fieldMsg(errors, 'trigger')}>
            <select
              className="input" value={form.trigger}
              onChange={(e) => setField('trigger')(e.target.value)} disabled={saving}
            >
              {TRIGGERS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </Field>
          <div className="form-field">
            <div className="form-label">Status</div>
            <label className="check-row" style={{ paddingTop: '8px' }}>
              <input
                type="checkbox" checked={form.is_enabled}
                onChange={(e) => setField('is_enabled')(e.target.checked)} disabled={saving}
              />
              Enabled
            </label>
          </div>
        </div>

        <h4 style={{ marginTop: 'var(--sp-4)' }}>Conditions</h4>
        <p className="muted small">All filled conditions must match. Leave a field blank to ignore it.</p>
        <div className="form-grid">
          <Field label="Category id" error={fieldMsg(errors, 'conditions.category_id')}>
            <input
              className="input" type="number" min="1" value={form.conditions.category_id}
              onChange={(e) => setCondition('category_id')(e.target.value)} disabled={saving}
            />
          </Field>
          <Field label="Department id" error={fieldMsg(errors, 'conditions.department_id')}>
            <input
              className="input" type="number" min="1" value={form.conditions.department_id}
              onChange={(e) => setCondition('department_id')(e.target.value)} disabled={saving}
            />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Priority" error={fieldMsg(errors, 'conditions.priority')}>
            <select
              className="input" value={form.conditions.priority}
              onChange={(e) => setCondition('priority')(e.target.value)} disabled={saving}
            >
              <option value="">Any priority</option>
              {PRIORITIES.map((p) => <option key={p} value={p}>{titleize(p)}</option>)}
            </select>
          </Field>
          <Field label="Status" error={fieldMsg(errors, 'conditions.status')}>
            <select
              className="input" value={form.conditions.status}
              onChange={(e) => setCondition('status')(e.target.value)} disabled={saving}
            >
              <option value="">Any status</option>
              {TICKET_STATUSES.map((s) => <option key={s} value={s}>{titleize(s)}</option>)}
            </select>
          </Field>
        </div>

        <h4 style={{ marginTop: 'var(--sp-4)' }}>Actions</h4>
        {form.actions.length === 0 && (
          <p className="muted small">No actions configured. The rule will record an execution but change nothing.</p>
        )}
        {form.actions.map((action, i) => {
          const rowError = errors[`actions.${i}`];
          return (
            <div className="file-row" key={i}>
              <div className="file-main" style={{ flex: 1 }}>
                <div className="form-grid">
                  <Field label={`Action ${i + 1}`}>
                    <select
                      className="input" value={action.type}
                      aria-label={`Action ${i + 1} type`}
                      onChange={(e) => setActionType(i, e.target.value)} disabled={saving}
                    >
                      {ACTION_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                    </select>
                  </Field>
                  {action.type === 'assign' && (
                    <Field label="User id" required>
                      <input
                        className="input" type="number" min="1" value={action.user_id}
                        aria-label={`Action ${i + 1} user id`}
                        onChange={(e) => setAction(i, 'user_id', e.target.value)} disabled={saving}
                      />
                    </Field>
                  )}
                  {action.type === 'notify' && (
                    <Field label="User id (optional)" hint="Blank notifies the assignee, or the requester when unassigned.">
                      <input
                        className="input" type="number" min="1" value={action.user_id}
                        aria-label={`Action ${i + 1} user id`}
                        onChange={(e) => setAction(i, 'user_id', e.target.value)} disabled={saving}
                      />
                    </Field>
                  )}
                  {(action.type === 'priority' || action.type === 'status') && (
                    <Field label={action.type === 'priority' ? 'Priority' : 'Status'} required>
                      <select
                        className="input" value={action.value}
                        aria-label={`Action ${i + 1} value`}
                        onChange={(e) => setAction(i, 'value', e.target.value)} disabled={saving}
                      >
                        <option value="">Choose…</option>
                        {(action.type === 'priority' ? PRIORITIES : TICKET_STATUSES).map((v) => (
                          <option key={v} value={v}>{titleize(v)}</option>
                        ))}
                      </select>
                    </Field>
                  )}
                  {action.type === 'note' && (
                    <Field label="Note text" required>
                      <input
                        className="input" value={action.text}
                        aria-label={`Action ${i + 1} text`}
                        onChange={(e) => setAction(i, 'text', e.target.value)} disabled={saving}
                      />
                    </Field>
                  )}
                </div>
                <FieldError text={rowError} />
              </div>
              <button
                type="button" className="btn-small btn-danger"
                onClick={() => removeAction(i)} disabled={saving}
                aria-label={`Remove action ${i + 1}`}
              >
                Remove
              </button>
            </div>
          );
        })}
        <div className="toolbar" style={{ marginTop: 'var(--sp-2)' }}>
          <button type="button" className="btn-secondary btn-small" onClick={addAction} disabled={saving}>
            + Add action
          </button>
        </div>
        <div className="row-end">
          <button type="button" className="btn-ghost" onClick={onCancel} disabled={saving}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>
    </form>
  );
}

function RuleEditPage({ id }) {
  const [rule, setRule] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = async () => {
    setLoading(true);
    setError('');
    try {
      setRule((await api.get(`/workflow/automation-rules/${id}/`)).data);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load this rule.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div className="panel"><Loading /></div>;
  if (error) return <div className="panel"><LoadError message={error} onRetry={load} /></div>;
  return (
    <div>
      <a className="back-link" href={`#/workflow/rules/${id}`}>← Back to rule #{id}</a>
      <PageHeader title={`Edit ${rule.name}`} sub="Changes apply to future ticket events." />
      <RuleForm
        rule={rule}
        onCancel={() => { location.hash = `#/workflow/rules/${id}`; }}
        onSaved={() => { location.hash = `#/workflow/rules/${id}`; }}
      />
    </div>
  );
}

function RuleDetail({ id, isAdmin }) {
  const [rule, setRule] = useState(null);
  const [executions, setExecutions] = useState([]);
  const [executionError, setExecutionError] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    setError('');
    setExecutionError('');
    try {
      const r = (await api.get(`/workflow/automation-rules/${id}/`)).data;
      setRule(r);
      try {
        const ex = await api.get('/workflow/rule-executions/', {
          params: { rule: id, page_size: 10 },
        });
        setExecutions(ex.data.results ?? ex.data ?? []);
      } catch {
        setExecutions([]);
        setExecutionError('Could not load execution history for this rule.');
      }
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load this rule.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const r = await api.patch(`/workflow/automation-rules/${id}/`, { is_enabled: !rule.is_enabled });
      setRule(r.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not change the rule status.');
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <div className="panel"><Loading /></div>;
  if (error && !rule) return <div className="panel"><LoadError message={error} onRetry={load} /></div>;

  const columns = [
    { key: 'id', label: 'ID' },
    {
      key: 'result',
      label: 'Result',
      render: (ex) => <Badge kind="status" value={ex.success ? 'completed' : 'rejected'} label={ex.success ? 'Success' : 'Failed'} />,
    },
    { key: 'ticket', label: 'Ticket', render: (ex) => <a href={`#/tickets/${ex.ticket}`}>#{ex.ticket} {ex.ticket_title}</a> },
    { key: 'detail', label: 'Result detail', render: (ex) => <span className="ellipsis" title={ex.detail}>{ex.detail || '—'}</span> },
    { key: 'created', label: 'When', render: (ex) => fmtDateTime(ex.created_at) },
    { key: 'actions', label: 'Actions', render: (ex) => <a className="btn-small" href={`#/workflow/executions/${ex.id}`}>View</a> },
  ];

  return (
    <div>
      <a className="back-link" href="#/workflow/rules">← All automation rules</a>
      {error && <div className="error-summary" role="alert">{error}</div>}
      <PageHeader
        title={rule.name}
        sub={`Automation rule #${rule.id}`}
        actions={isAdmin ? (
          <>
            <a className="btn-secondary" href={`#/workflow/rules/${rule.id}/edit`}>Edit rule</a>
            <button type="button" className="btn-secondary" onClick={toggle} disabled={busy}>
              {busy ? 'Working…' : rule.is_enabled ? 'Disable' : 'Enable'}
            </button>
          </>
        ) : undefined}
      />
      <div className="row-gap detail-badges">
        <Badge kind="status" value={rule.is_enabled ? 'active' : 'inactive'} label={rule.is_enabled ? 'Enabled' : 'Disabled'} />
        <Badge kind="status" value="pending" label={triggerLabel(rule.trigger)} />
      </div>
      <dl className="detail-grid">
        <dt>Trigger</dt><dd>{rule.trigger_display ?? triggerLabel(rule.trigger)}</dd>
        <dt>Status</dt><dd>{rule.is_enabled ? 'Enabled — evaluated on every matching ticket event.' : 'Disabled — never evaluated.'}</dd>
        <dt>Created</dt><dd>{fmtDateTime(rule.created_at)}</dd>
        <dt>Updated</dt><dd>{fmtDateTime(rule.updated_at)}</dd>
        <dt>Created by</dt><dd>{rule.created_by_email ?? '—'}</dd>
        <dt>Updated by</dt><dd>{rule.updated_by_email ?? '—'}</dd>
        <dt>Description</dt><dd>{rule.description || '—'}</dd>
      </dl>

      <section className="section">
        <h4>Conditions</h4>
        <ul className="file-list">
          {conditionsSummary(rule.conditions).map((line) => (
            <li key={line} className="file-row"><span className="file-name">{line}</span></li>
          ))}
        </ul>
      </section>

      <section className="section">
        <h4>Actions</h4>
        {Array.isArray(rule.actions) && rule.actions.length > 0 ? (
          <ul className="file-list">
            {rule.actions.map((action, i) => (
              <li key={i} className="file-row"><span className="file-name">{actionSummary(action)}</span></li>
            ))}
          </ul>
        ) : <p className="muted">No actions configured.</p>}
      </section>

      <section className="section">
        <h4>Recent execution history</h4>
        {executionError && <div className="error-summary" role="alert">{executionError}</div>}
        <DataTable
          columns={columns}
          rows={executions}
          keyOf={(ex) => ex.id}
          emptyTitle="No executions for this rule yet."
          emptyHint="Executions appear when a matching ticket event runs this rule."
        />
      </section>
    </div>
  );
}

function RulesList({ isAdmin }) {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [trigger, setTrigger] = useState('ticket_created');
  const [createError, setCreateError] = useState('');
  const [creating, setCreating] = useState(false);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const r = await api.get('/workflow/automation-rules/');
      setRules(r.data.results ?? r.data ?? []);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load automation rules.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const create = async (ev) => {
    ev.preventDefault();
    if (creating) return;
    setCreateError('');
    if (!name.trim()) {
      setCreateError('Rule name is required.');
      return;
    }
    setCreating(true);
    try {
      const res = await api.post('/workflow/automation-rules/', {
        name: name.trim(), description, trigger, is_enabled: true,
        conditions: {}, actions: [],
      });
      setName('');
      setDescription('');
      location.hash = `#/workflow/rules/${res.data.id}`;
    } catch (e) {
      const mapped = ruleApiErrors(e);
      setCreateError(mapped.name || mapped.trigger || mapped.__form || 'Could not create rule.');
    } finally {
      setCreating(false);
    }
  };

  const toggle = async (rule) => {
    if (busyId) return;
    setBusyId(rule.id);
    setError('');
    try {
      const r = await api.patch(`/workflow/automation-rules/${rule.id}/`, { is_enabled: !rule.is_enabled });
      setRules((rows) => rows.map((row) => (row.id === rule.id ? r.data : row)));
    } catch (e) {
      setError(parseApiError(e).global || 'Could not change the rule status.');
    } finally {
      setBusyId(null);
    }
  };

  const columns = [
    { key: 'name', label: 'Rule', render: (r) => <a className="row-title" href={`#/workflow/rules/${r.id}`}>{r.name}</a> },
    { key: 'trigger', label: 'Trigger', render: (r) => r.trigger_display ?? triggerLabel(r.trigger) },
    {
      key: 'status',
      label: 'Status',
      render: (r) => <Badge kind="status" value={r.is_enabled ? 'active' : 'inactive'} label={r.is_enabled ? 'Enabled' : 'Disabled'} />,
    },
    { key: 'conditions', label: 'Conditions', render: (r) => <span className="ellipsis" title={conditionsSummary(r.conditions).join(' · ')}>{conditionsSummary(r.conditions).join(' · ')}</span> },
    { key: 'actions', label: 'Actions', render: (r) => (Array.isArray(r.actions) ? r.actions.length : 0) },
    { key: 'updated', label: 'Updated', render: (r) => fmtDateTime(r.updated_at) },
    {
      key: 'row-actions',
      label: 'Actions',
      render: (r) => (
        <span className="row-gap" style={{ gap: 'var(--sp-1)' }}>
          <a className="btn-small" href={`#/workflow/rules/${r.id}`}>View</a>
          {isAdmin && <a className="btn-small" href={`#/workflow/rules/${r.id}/edit`}>Edit</a>}
          {isAdmin && (
            <button type="button" className="btn-small" onClick={() => toggle(r)} disabled={busyId === r.id}>
              {busyId === r.id ? 'Working…' : r.is_enabled ? 'Disable' : 'Enable'}
            </button>
          )}
        </span>
      ),
    },
  ];

  return (
    <div>
      {isAdmin ? (
        <form onSubmit={create} className="filter-bar" aria-label="Create automation rule">
          <div className="field-inline grow">
            <div className="caption">New rule name</div>
            <input
              className="input" value={name} onChange={(e) => setName(e.target.value)}
              disabled={creating} maxLength={120} aria-label="New rule name"
            />
          </div>
          <div className="field-inline grow">
            <div className="caption">Description</div>
            <input
              className="input" value={description} onChange={(e) => setDescription(e.target.value)}
              disabled={creating} aria-label="New rule description"
            />
          </div>
          <div className="field-inline">
            <div className="caption">Trigger</div>
            <select className="input" value={trigger} onChange={(e) => setTrigger(e.target.value)} disabled={creating} aria-label="New rule trigger">
              {TRIGGERS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          <button type="submit" className="btn-primary" disabled={creating}>
            {creating ? 'Creating…' : 'Create rule'}
          </button>
        </form>
      ) : (
        <p className="muted small">View-only: only System Admins can create, edit or toggle automation rules.</p>
      )}
      {createError && <div className="error-summary" role="alert">{createError}</div>}
      <div className="panel">
        {loading ? <Loading />
          : error ? <LoadError message={error} onRetry={load} />
            : (
              <DataTable
                columns={columns}
                rows={rules}
                keyOf={(r) => r.id}
                emptyTitle="No automation rules defined."
                emptyHint="Create a rule to automate ticket assignment, priority, status, notes or notifications."
              />
            )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Approvals                                                           */
/* ------------------------------------------------------------------ */

function ApprovalsList() {
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [filters, setFilters] = useState({ q: '', status: 'pending', operation: '' });
  const [draft, setDraft] = useState({ q: '', status: 'pending', operation: '' });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const buildUrl = (f) => {
    const p = new URLSearchParams();
    if (f.q.trim()) p.set('q', f.q.trim());
    if (f.status) p.set('status', f.status);
    if (f.operation) p.set('operation', f.operation);
    const qs = p.toString();
    return `/workflow/approval-requests/${qs ? `?${qs}` : ''}`;
  };

  const loadUrl = async (url) => {
    setLoading(true);
    setError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load approval requests.');
    } finally {
      setLoading(false);
    }
  };

  const apply = (ev) => {
    if (ev) ev.preventDefault();
    setFilters(draft);
    loadUrl(buildUrl(draft));
  };

  useEffect(() => { loadUrl(buildUrl(filters)); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const columns = [
    { key: 'id', label: 'ID' },
    { key: 'ticket', label: 'Ticket', render: (a) => <a className="row-title" href={`#/tickets/${a.ticket}`}>#{a.ticket} {a.ticket_title}</a> },
    { key: 'operation', label: 'Operation', render: (a) => a.operation_display ?? titleize(a.operation) },
    { key: 'requested_by', label: 'Requested by', render: (a) => a.requested_by_email ?? `#${a.requested_by}` },
    { key: 'status', label: 'Status', render: (a) => <Badge kind="status" value={a.status} /> },
    { key: 'created', label: 'Requested', render: (a) => fmtDateTime(a.created_at) },
    { key: 'actions', label: 'Actions', render: (a) => <a className="btn-small" href={`#/workflow/approvals/${a.id}`}>View</a> },
  ];

  return (
    <div>
      <form className="filter-bar" role="search" onSubmit={apply}>
        <div className="field-inline grow">
          <div className="caption">Search</div>
          <input
            className="input" value={draft.q} aria-label="Search approvals"
            placeholder="Ticket title, reason or id…"
            onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value }))}
          />
        </div>
        <div className="field-inline">
          <div className="caption">Status</div>
          <select
            className="input" value={draft.status} aria-label="Filter approvals by status"
            onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}
          >
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>
        <div className="field-inline">
          <div className="caption">Operation</div>
          <select
            className="input" value={draft.operation} aria-label="Filter approvals by operation"
            onChange={(e) => setDraft((d) => ({ ...d, operation: e.target.value }))}
          >
            <option value="">All operations</option>
            {OPERATIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <button type="submit" className="btn-secondary">Apply filters</button>
      </form>
      <div className="panel">
        {loading ? <Loading />
          : error ? <LoadError message={error} onRetry={() => loadUrl(buildUrl(filters))} />
            : (
              <>
                <DataTable
                  columns={columns}
                  rows={items}
                  keyOf={(a) => a.id}
                  emptyTitle="No approval requests match."
                  emptyHint="Approval requests appear when a sensitive ticket operation needs review."
                />
                <Pager
                  count={count}
                  hasNext={!!next}
                  hasPrev={!!previous}
                  busy={loading}
                  onPrev={() => previous && loadUrl(previous)}
                  onNext={() => next && loadUrl(next)}
                />
              </>
            )}
      </div>
    </div>
  );
}

function ApprovalDetail({ id }) {
  const { isStaff, user } = useAuth();
  const [approval, setApproval] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [decisionError, setDecisionError] = useState('');
  const [success, setSuccess] = useState('');
  const [comment, setComment] = useState('');
  const [decision, setDecision] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      setApproval((await api.get(`/workflow/approval-requests/${id}/`)).data);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load this approval request.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const isOwn = approval && user?.id != null
    && Number(approval.requested_by) === Number(user.id);
  const canDecide = !!approval && isStaff && approval.status === 'pending' && !isOwn;

  const decide = async () => {
    if (busy || !decision) return;
    setBusy(true);
    setDecisionError('');
    setSuccess('');
    try {
      const res = await api.post(
        `/workflow/approval-requests/${id}/${decision}/`,
        { comment: comment.trim() },
      );
      setApproval(res.data);
      setComment('');
      setDecision(null);
      setSuccess(decision === 'approve' ? 'Approval recorded and the operation was applied.' : 'Approval request rejected.');
      await load();
    } catch (e) {
      const status = e?.response?.status;
      setDecision(null);
      if (status === 409) {
        setDecisionError('This approval has already been decided by another user. The latest details are shown below.');
        await load();
      } else if (status === 403) {
        setDecisionError(parseApiError(e).global || 'You cannot decide this approval request.');
      } else {
        setDecisionError(parseApiError(e).global || 'Could not submit the decision.');
      }
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <div className="panel"><Loading /></div>;
  if (error && !approval) return <div className="panel"><LoadError message={error} onRetry={load} /></div>;
  const a = approval;

  return (
    <div>
      <a className="back-link" href={isStaff ? '#/workflow/approvals' : `#/tickets/${a.ticket}`}>
        ← {isStaff ? 'Approval queue' : `Ticket #${a.ticket}`}
      </a>
      {error && <div className="error-summary" role="alert">{error}</div>}
      {decisionError && <div className="error-summary" role="alert">{decisionError}</div>}
      {success && <div className="success-summary" role="status">{success}</div>}
      <PageHeader
        title={`Approval #${a.id}`}
        sub={a.operation_display ?? titleize(a.operation)}
        actions={<Badge kind="status" value={a.status} />}
      />
      <dl className="detail-grid">
        <dt>Ticket</dt>
        <dd><a href={`#/tickets/${a.ticket}`}>#{a.ticket} {a.ticket_title}</a></dd>
        <dt>Requester</dt><dd>{a.requested_by_email ?? `#${a.requested_by}`}</dd>
        <dt>Assigned approver</dt><dd>{a.approver_email ?? 'Any IT staff'}</dd>
        <dt>Requested operation</dt><dd>{a.operation_display ?? titleize(a.operation)}</dd>
        <dt>Status</dt><dd><Badge kind="status" value={a.status} /></dd>
        <dt>Requested</dt><dd>{fmtDateTime(a.created_at)}</dd>
        <dt>Updated</dt><dd>{fmtDateTime(a.updated_at)}</dd>
        <dt>Decided</dt><dd>{a.decided_at ? fmtDateTime(a.decided_at) : 'Not decided'}</dd>
        <dt>Decided by</dt><dd>{a.decided_by_email ?? '—'}</dd>
      </dl>

      <section className="section">
        <h4>Request context</h4>
        <ul className="file-list">
          {contextSummary(a.context).map((line) => (
            <li key={line} className="file-row"><span className="file-name">{line}</span></li>
          ))}
        </ul>
        <p><strong>Reason:</strong> {a.reason || <span className="muted">No reason supplied.</span>}</p>
      </section>

      {a.status !== 'pending' && (
        <section className="section">
          <h4>Decision</h4>
          <p>
            <Badge kind="status" value={a.status} />
            {' '}by {a.decided_by_email ?? '—'} on {fmtDateTime(a.decided_at)}
          </p>
          <p>{a.decision_comment || <span className="muted">No decision comment.</span>}</p>
        </section>
      )}

      {a.status === 'pending' && (
        <section className="section">
          <h4>Decision</h4>
          {!isStaff && <p className="muted">Only IT staff can decide approval requests.</p>}
          {isStaff && isOwn && <p className="muted">You cannot decide your own approval request.</p>}
          {canDecide && (
            <>
              <Field label="Decision comment (optional)">
                <textarea
                  className="input" rows={3} value={comment}
                  aria-label="Decision comment"
                  onChange={(e) => setComment(e.target.value)} disabled={busy}
                  placeholder="Why this request is approved or rejected…"
                />
              </Field>
              <div className="row-end">
                <button type="button" className="btn-danger" onClick={() => setDecision('reject')} disabled={busy}>
                  Reject…
                </button>
                <button type="button" className="btn-primary" onClick={() => setDecision('approve')} disabled={busy}>
                  Approve…
                </button>
              </div>
            </>
          )}
        </section>
      )}

      {decision && (
        <ConfirmDialog
          title={decision === 'approve' ? 'Approve this request?' : 'Reject this request?'}
          message={decision === 'approve'
            ? `Approving will apply ${a.operation_display ?? titleize(a.operation)} to ticket #${a.ticket}.`
            : `Rejecting leaves ticket #${a.ticket} unchanged.`}
          confirmLabel={decision === 'approve' ? 'Approve request' : 'Reject request'}
          danger={decision === 'reject'}
          busy={busy}
          onConfirm={decide}
          onCancel={() => setDecision(null)}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Execution history                                                   */
/* ------------------------------------------------------------------ */

function ExecutionsList() {
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [rules, setRules] = useState([]);
  const [filters, setFilters] = useState({
    rule: '', status: '', dateFrom: '', dateTo: '', q: '',
  });
  const [draft, setDraft] = useState({
    rule: '', status: '', dateFrom: '', dateTo: '', q: '',
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const buildUrl = (f) => {
    const p = new URLSearchParams();
    if (f.rule) p.set('rule', f.rule);
    if (f.status) p.set('status', f.status);
    if (f.dateFrom) p.set('date_from', f.dateFrom);
    // A date input means "through the end of this day", not midnight.
    if (f.dateTo) p.set('date_to', `${f.dateTo}T23:59:59`);
    if (f.q.trim()) p.set('q', f.q.trim());
    const qs = p.toString();
    return `/workflow/rule-executions/${qs ? `?${qs}` : ''}`;
  };

  const loadUrl = async (url) => {
    setLoading(true);
    setError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load execution history.');
    } finally {
      setLoading(false);
    }
  };

  const loadRules = async () => {
    try {
      const r = await api.get('/workflow/automation-rules/');
      setRules(r.data.results ?? r.data ?? []);
    } catch {
      setRules([]);
    }
  };

  const apply = (ev) => {
    if (ev) ev.preventDefault();
    setFilters(draft);
    loadUrl(buildUrl(draft));
  };

  useEffect(() => {
    loadRules();
    loadUrl(buildUrl(filters));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const reset = () => {
    const blank = { rule: '', status: '', dateFrom: '', dateTo: '', q: '' };
    setDraft(blank);
    setFilters(blank);
    loadUrl(buildUrl(blank));
  };

  const columns = [
    { key: 'id', label: 'ID' },
    { key: 'rule', label: 'Rule', render: (ex) => <a className="row-title" href={`#/workflow/rules/${ex.rule}`}>{ex.rule_name ?? `#${ex.rule}`}</a> },
    { key: 'ticket', label: 'Ticket', render: (ex) => <a href={`#/tickets/${ex.ticket}`}>#{ex.ticket} {ex.ticket_title}</a> },
    {
      key: 'result',
      label: 'Result',
      render: (ex) => <Badge kind="status" value={ex.success ? 'completed' : 'rejected'} label={ex.success ? 'Success' : 'Failed'} />,
    },
    { key: 'detail', label: 'Result detail', render: (ex) => <span className="ellipsis" title={ex.detail}>{ex.detail || '—'}</span> },
    { key: 'created', label: 'When', render: (ex) => fmtDateTime(ex.created_at) },
    { key: 'actions', label: 'Actions', render: (ex) => <a className="btn-small" href={`#/workflow/executions/${ex.id}`}>View</a> },
  ];

  return (
    <div>
      <form className="filter-bar" role="search" onSubmit={apply}>
        <div className="field-inline grow">
          <div className="caption">Search</div>
          <input
            className="input" value={draft.q} aria-label="Search executions"
            placeholder="Rule, ticket title, result or id…"
            onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value }))}
          />
        </div>
        <div className="field-inline">
          <div className="caption">Rule</div>
          <select
            className="input" value={draft.rule} aria-label="Filter executions by rule"
            onChange={(e) => setDraft((d) => ({ ...d, rule: e.target.value }))}
          >
            <option value="">All rules</option>
            {rules.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </div>
        <div className="field-inline">
          <div className="caption">Status</div>
          <select
            className="input" value={draft.status} aria-label="Filter executions by status"
            onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value }))}
          >
            <option value="">All results</option>
            <option value="success">Success</option>
            <option value="failure">Failure</option>
          </select>
        </div>
        <div className="field-inline">
          <div className="caption">From</div>
          <input
            className="input" type="date" value={draft.dateFrom} aria-label="Execution start date"
            onChange={(e) => setDraft((d) => ({ ...d, dateFrom: e.target.value }))}
          />
        </div>
        <div className="field-inline">
          <div className="caption">To</div>
          <input
            className="input" type="date" value={draft.dateTo} aria-label="Execution end date"
            onChange={(e) => setDraft((d) => ({ ...d, dateTo: e.target.value }))}
          />
        </div>
        <button type="submit" className="btn-secondary">Apply filters</button>
        <button type="button" className="btn-ghost" onClick={reset}>Reset</button>
      </form>
      <div className="panel">
        {loading ? <Loading />
          : error ? <LoadError message={error} onRetry={() => loadUrl(buildUrl(filters))} />
            : (
              <>
                <DataTable
                  columns={columns}
                  rows={items}
                  keyOf={(ex) => ex.id}
                  emptyTitle="No executions match."
                  emptyHint="Adjust the filters, or wait for a matching ticket event."
                />
                <Pager
                  count={count}
                  hasNext={!!next}
                  hasPrev={!!previous}
                  busy={loading}
                  onPrev={() => previous && loadUrl(previous)}
                  onNext={() => next && loadUrl(next)}
                />
              </>
            )}
      </div>
    </div>
  );
}

function ExecutionDetail({ id }) {
  const [execution, setExecution] = useState(null);
  const [rule, setRule] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    setRule(null);
    try {
      const ex = (await api.get(`/workflow/rule-executions/${id}/`)).data;
      setExecution(ex);
      if (ex.rule) {
        try {
          setRule((await api.get(`/workflow/automation-rules/${ex.rule}/`)).data);
        } catch {
          setRule(null);
        }
      }
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load this execution.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div className="panel"><Loading /></div>;
  if (error && !execution) return <div className="panel"><LoadError message={error} onRetry={load} /></div>;
  const ex = execution;

  return (
    <div>
      <a className="back-link" href="#/workflow/executions">← Execution history</a>
      {error && <div className="error-summary" role="alert">{error}</div>}
      <PageHeader
        title={`Execution #${ex.id}`}
        sub={ex.rule_name ?? `Rule #${ex.rule}`}
        actions={<Badge kind="status" value={ex.success ? 'completed' : 'rejected'} label={ex.success ? 'Success' : 'Failed'} />}
      />
      <dl className="detail-grid">
        <dt>Rule</dt>
        <dd><a href={`#/workflow/rules/${ex.rule}`}>{ex.rule_name ?? `#${ex.rule}`}</a></dd>
        <dt>Ticket</dt>
        <dd><a href={`#/tickets/${ex.ticket}`}>#{ex.ticket} {ex.ticket_title}</a></dd>
        <dt>Status</dt>
        <dd><Badge kind="status" value={ex.success ? 'completed' : 'rejected'} label={ex.success ? 'Success' : 'Failed'} /></dd>
        <dt>Trigger</dt>
        <dd>{rule ? (rule.trigger_display ?? triggerLabel(rule.trigger)) : 'Rule details unavailable.'}</dd>
        <dt>Executed</dt><dd>{fmtDateTime(ex.created_at)}</dd>
      </dl>

      {rule && (
        <section className="section">
          <h4>Rule configuration at execution time</h4>
          <p className="muted small">This is the rule's current configuration, which may have been edited since this execution.</p>
          <ul className="file-list">
            {conditionsSummary(rule.conditions).map((line) => (
              <li key={line} className="file-row"><span className="file-name">{line}</span></li>
            ))}
            {(rule.actions || []).map((action, i) => (
              <li key={`a${i}`} className="file-row"><span className="file-name">{actionSummary(action)}</span></li>
            ))}
          </ul>
        </section>
      )}

      <section className="section">
        <h4>{ex.success ? 'Action results' : 'Failure information'}</h4>
        {!ex.success && (
          <div className="error-summary" role="alert">
            This automation run failed. The recorded error is shown below; the ticket was left at its last valid state.
          </div>
        )}
        <p className="pre-wrap">{ex.detail || (ex.success ? 'No action output recorded.' : 'No failure detail recorded.')}</p>
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Page shell                                                          */
/* ------------------------------------------------------------------ */

const TABS = [
  { id: 'rules', label: 'Automation rules', hash: '#/workflow/rules' },
  { id: 'approvals', label: 'Approvals', hash: '#/workflow/approvals' },
  { id: 'executions', label: 'Execution history', hash: '#/workflow/executions' },
];

export default function Workflow({ tab, ruleId, ruleEdit, approvalId, executionId }) {
  const { isStaff, isAdmin } = useAuth();
  const activeTab = ruleId ? 'rules' : approvalId ? 'approvals' : executionId ? 'executions' : (tab || 'rules');

  // Employees have no workflow-management page, but may open an approval on
  // a ticket they can see (the API still scopes the queryset to their tickets).
  if (!isStaff && !approvalId) {
    return (
      <div>
        <PageHeader title="Workflow" sub="Automation and approvals are managed by IT staff." />
        <div className="error-summary" role="alert">You do not have permission to view workflow management.</div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Workflow"
        sub="Automation rules, approval decisions and execution history."
      />
      {isStaff && (
        <nav className="tabs" aria-label="Workflow sections">
          {TABS.map((t) => (
            <a
              key={t.id}
              href={t.hash}
              className={activeTab === t.id ? 'active' : undefined}
              aria-current={activeTab === t.id ? 'page' : undefined}
            >
              {t.label}
            </a>
          ))}
        </nav>
      )}

      {ruleId ? (
        ruleEdit ? <RuleEditPage id={ruleId} /> : <RuleDetail id={ruleId} isAdmin={isAdmin} />
      ) : approvalId ? (
        <ApprovalDetail id={approvalId} />
      ) : executionId ? (
        <ExecutionDetail id={executionId} />
      ) : activeTab === 'approvals' ? (
        <ApprovalsList />
      ) : activeTab === 'executions' ? (
        <ExecutionsList />
      ) : (
        <RulesList isAdmin={isAdmin} />
      )}
    </div>
  );
}
