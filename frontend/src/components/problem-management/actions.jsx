import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import {
  Badge, Button, ConfirmDialog, DataTable, Field, Input, LoadingRows, Option,
  PageHeader, Panel, PanelPad, Select, Textarea,
} from '../../components';
import {
  approveAction, cancelAction, completeAction, createAction, editAction,
  listActions, listRCAs, markActionIneffective, startAction, validateAction,
} from '../../services/problem-management';

const ACTION_TYPES = [
  ['corrective', 'Corrective'],
  ['preventive', 'Preventive'],
  ['root_cause', 'Root cause'],
  ['validation', 'Validation'],
  ['exception', 'Exception'],
];

const EMPTY = {
  title: '', description: '', action_type: 'corrective', due_at: '',
  root_cause_analysis: '',
};
const LOCKED_ACTION_STATUSES = ['verified', 'ineffective', 'cancelled', 'closed'];
const CANCELABLE_ACTION_STATUSES = ['planned', 'approved', 'in_progress', 'completed'];

const EMPTY_REASON = { action: null, record: null, value: '', error: '' };

const REASON_SERVICES = {
  cancel: cancelAction,
  ineffective: markActionIneffective,
};

const REASON_CONFIG = {
  cancel: {
    title: 'Cancel action',
    message: 'A reason is required to cancel this action. It will be recorded in the action history and audit log.',
    field: 'Cancellation reason',
    confirm: 'Confirm cancellation',
    moveLabel: 'Cancel',
    missing: 'A cancellation reason is required.',
  },
  ineffective: {
    title: 'Mark action ineffective',
    message: 'This action is being marked ineffective. A reason is required and will be recorded in the action history and audit log.',
    field: 'Ineffectiveness reason',
    confirm: 'Confirm ineffective',
    moveLabel: 'Mark ineffective',
    missing: 'An ineffectiveness reason is required.',
  },
};

const formatServiceError = (error, fallback) => {
  const data = error?.response?.data;
  if (!data) return fallback;
  if (typeof data === 'string') return data;
  if (data.detail) return String(data.detail);
  const fields = Object.entries(data)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(' ') : value}`)
    .filter((part) => !part.endsWith(': '));
  return fields.join(' ') || fallback;
};

export function Actions({ problemId: problemIdProp, embedded = false }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const { isStaff, isManagerOrAdmin } = useAuth();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const savingRef = useRef(false);
  const busyRef = useRef(null);
  const [rcas, setRcas] = useState([]);
  const [rcasLoading, setRcasLoading] = useState(true);
  const [rcaError, setRcaError] = useState('');
  const [rcaDrafts, setRcaDrafts] = useState({});
  const [reasonDraft, setReasonDraft] = useState(EMPTY_REASON);
  const rcaById = new Map(rcas.map((rca) => [Number(rca.id), rca]));

  const load = useCallback(async () => {
    setLoading(true);
    setRcasLoading(true);
    setError('');
    setRcaError('');
    let actionRows = [];
    try {
      const data = await listActions(problemId);
      actionRows = Array.isArray(data) ? data : data?.results ?? [];
      setRows(actionRows);
    } catch {
      setError('Could not load actions.');
    }
    try {
      const data = await listRCAs(problemId);
      setRcas(Array.isArray(data) ? data : data?.results ?? []);
    } catch {
      setRcas([]);
      setRcaError('Could not load RCA options.');
    } finally {
      setLoading(false);
      setRcasLoading(false);
    }
    return actionRows;
  }, [problemId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const submit = async (ev) => {
    ev.preventDefault();
    if (!form.title.trim() || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError('');
    try {
      await createAction(problemId, {
        title: form.title.trim(),
        description: form.description.trim(),
        action_type: form.action_type,
        due_at: form.due_at || null,
        root_cause_analysis: form.root_cause_analysis
          ? Number(form.root_cause_analysis)
          : null,
      });
      setForm(EMPTY);
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not create action.');
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  // Every lifecycle move goes through its dedicated backend transition.
  const move = async (action, fn, label, extra = {}, onSuccess) => {
    if (busyRef.current != null) return false;
    busyRef.current = action.id;
    setBusyId(action.id);
    setError('');
    setNotice('');
    let succeeded = false;
    try {
      const updated = await fn(action.id, {
        expected_record_version: action.version,
        ...extra,
      });
      if (updated && typeof updated === 'object') {
        setRows((prev) => prev.map((row) => (
          row.id === action.id ? { ...row, ...updated } : row
        )));
      }
      setNotice(`${label} succeeded.`);
      await load();
      succeeded = true;
    } catch (e) {
      const status = e?.response?.status ?? e?.status;
      if (status === 409) {
        const refreshed = await load();
        const fresh = refreshed?.find((row) => row.id === action.id);
        if (fresh) {
          setReasonDraft((current) => (
            current.action && current.record?.id === action.id
              ? { ...current, record: fresh }
              : current
          ));
        }
        setError(
          'This action changed on the server. The latest version has been loaded; review it and try again.',
        );
      } else {
        setError(formatServiceError(e, `${label} failed.`));
      }
    } finally {
      busyRef.current = null;
      setBusyId(null);
    }
    if (succeeded && onSuccess) onSuccess();
    return succeeded;
  };

  const closeReason = () => {
    if (busyRef.current != null) return;
    setReasonDraft(EMPTY_REASON);
  };

  const openReason = (action, name) => {
    if (busyRef.current != null) return;
    setError('');
    setNotice('');
    setReasonDraft({ ...EMPTY_REASON, action: name, record: action });
  };

  const submitReason = (record, name) => {
    const config = REASON_CONFIG[name];
    const trimmed = reasonDraft.value.trim();
    if (!trimmed) {
      setReasonDraft((current) => ({ ...current, error: config.missing }));
      return;
    }
    setReasonDraft((current) => ({ ...current, error: '' }));
    return move(
      record, REASON_SERVICES[name], config.moveLabel,
      { reason: trimmed }, closeReason,
    );
  };

  const linkedRcaValue = (action) => (
    action.root_cause_analysis != null ? String(action.root_cause_analysis) : ''
  );

  const saveRca = async (action) => {
    if (busyRef.current != null) return;
    const current = linkedRcaValue(action);
    const next = rcaDrafts[action.id] ?? current;
    if (next === current) return;
    busyRef.current = action.id;
    setBusyId(action.id);
    setError('');
    setNotice('');
    try {
      await editAction(action.id, {
        root_cause_analysis: next ? Number(next) : null,
      }, action.version);
      setRcaDrafts((prev) => {
        const copy = { ...prev };
        delete copy[action.id];
        return copy;
      });
      setNotice('RCA link updated.');
      await load();
    } catch (e) {
      const data = e?.response?.data;
      setError(
        data?.root_cause_analysis?.[0]
        || data?.detail
        || 'Could not update the RCA link.',
      );
    } finally {
      busyRef.current = null;
      setBusyId(null);
    }
  };

  const columns = [
    { key: 'title', label: 'Action' },
    { key: 'action_type', label: 'Type', render: (r) => (r.action_type || '—').replace(/_/g, ' ') },
    {
      key: 'root_cause_analysis',
      label: 'RCA',
      render: (r) => {
        const linked = rcaById.get(Number(r.root_cause_analysis));
        const current = linkedRcaValue(r);
        const draft = rcaDrafts[r.id] ?? current;
        const locked = LOCKED_ACTION_STATUSES.includes(r.status);
        return (
          <div>
            {r.root_cause_analysis != null ? (
              <div className="row-gap">
                <span>{linked?.title ?? `RCA #${r.root_cause_analysis}`}</span>
                {linked?.status && <Badge kind="status-warning" value={linked.status} />}
              </div>
            ) : <span className="muted">—</span>}
            {isStaff && !locked && (
              <div className="row-gap">
                <Select
                  aria-label={`RCA for action ${r.id}`}
                  value={draft}
                  disabled={rcasLoading || busyId === r.id}
                  onChange={(e) => setRcaDrafts((prev) => ({
                    ...prev,
                    [r.id]: e.target.value,
                  }))}
                >
                  <Option value="">No RCA</Option>
                  {rcas.map((rca) => (
                    <Option key={rca.id} value={String(rca.id)}>
                      {rca.title} ({rca.status})
                    </Option>
                  ))}
                </Select>
                <Button
                  size="small"
                  disabled={rcasLoading || busyId === r.id || draft === current}
                  onClick={() => saveRca(r)}
                >
                  Save RCA
                </Button>
              </div>
            )}
          </div>
        );
      },
    },
    { key: 'status', label: 'Status', render: (r) => <Badge kind="status-warning" value={r.status} /> },
    { key: 'version', label: 'Version', render: (r) => (r.version ?? '—') },
    { key: 'due_at', label: 'Due', render: (r) => (r.due_at ? new Date(r.due_at).toLocaleDateString() : '—') },
    {
      key: 'actions',
      label: 'Actions',
      render: (r) => {
        if (!isStaff) return '—';
        const disabled = busyId === r.id;
        const buttons = [];
        if (r.status === 'planned' && isManagerOrAdmin) {
          buttons.push(<Button key="approve" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, approveAction, 'Approve')}>Approve</Button>);
        }
        if (['planned', 'approved'].includes(r.status)) {
          buttons.push(<Button key="start" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, startAction, 'Start')}>Start</Button>);
        }
        if (r.status === 'in_progress') {
          buttons.push(<Button key="complete" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, completeAction, 'Complete')}>Complete</Button>);
        }
        if (r.status === 'completed') {
          buttons.push(<Button key="validate" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, validateAction, 'Validate')}>Validate</Button>);
          buttons.push(<Button key="ineffective" kind="ghost" size="small" disabled={disabled} onClick={() => openReason(r, 'ineffective')}>Ineffective</Button>);
        }
        if (CANCELABLE_ACTION_STATUSES.includes(r.status)) {
          buttons.push(<Button key="cancel" kind="ghost" size="small" disabled={disabled} onClick={() => openReason(r, 'cancel')}>Cancel</Button>);
        }
        return buttons.length ? <div className="row-gap">{buttons}</div> : '—';
      },
    },
  ];

  return (
    <div>
      {embedded
        ? <h3>Actions</h3>
        : <PageHeader title="Actions" sub="Corrective and preventive work" />}
      {error && <div className="error-summary" role="alert">{error}</div>}
      {rcaError && <div className="error-summary" role="alert">{rcaError}</div>}
      {notice && <div className="success-summary" role="status">{notice}</div>}
      {loading ? <LoadingRows n={3} /> : (
        <Panel>
          <PanelPad>
            <DataTable columns={columns} rows={rows} keyOf={(r) => r.id} emptyTitle="No actions yet" />
          </PanelPad>
        </Panel>
      )}

      {isStaff && (
        <form onSubmit={submit}>
          <Panel>
            <PanelPad>
              <Field label="Action title" required>
                <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </Field>
              <Field label="Description">
                <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </Field>
              <Field label="Type">
                <Select value={form.action_type} onChange={(e) => setForm({ ...form, action_type: e.target.value })}>
                  {ACTION_TYPES.map(([value, label]) => <Option key={value} value={value}>{label}</Option>)}
                </Select>
              </Field>
              <Field
                label="Root cause analysis"
                hint={rcasLoading ? 'Loading RCA options…' : undefined}
              >
                <Select
                  value={form.root_cause_analysis}
                  disabled={rcasLoading || saving}
                  onChange={(e) => setForm({ ...form, root_cause_analysis: e.target.value })}
                >
                  <Option value="">No RCA</Option>
                  {rcas.map((rca) => (
                    <Option key={rca.id} value={String(rca.id)}>
                      {rca.title} ({rca.status})
                    </Option>
                  ))}
                </Select>
              </Field>
              <Field label="Due date">
                <Input type="date" value={form.due_at} onChange={(e) => setForm({ ...form, due_at: e.target.value })} />
              </Field>
              <Button type="submit" disabled={!form.title.trim() || saving}>
                {saving ? 'Saving…' : 'Create Action'}
              </Button>
              <Button kind="ghost" onClick={() => setForm(EMPTY)}>Cancel</Button>
            </PanelPad>
          </Panel>
        </form>
      )}

      {reasonDraft.action && reasonDraft.record && (
        <ConfirmDialog
          title={REASON_CONFIG[reasonDraft.action].title}
          message={REASON_CONFIG[reasonDraft.action].message}
          confirmLabel={REASON_CONFIG[reasonDraft.action].confirm}
          danger={reasonDraft.action === 'cancel'}
          busy={busyId != null}
          onConfirm={() => submitReason(reasonDraft.record, reasonDraft.action)}
          onCancel={closeReason}
        >
          <Field
            label={REASON_CONFIG[reasonDraft.action].field}
            error={reasonDraft.error}
            hint="Leading and trailing spaces are removed before submission."
            required
          >
            <Textarea
              rows={4}
              value={reasonDraft.value}
              onChange={(e) => setReasonDraft((current) => ({
                ...current, value: e.target.value, error: '',
              }))}
              placeholder={REASON_CONFIG[reasonDraft.action].field}
              aria-label={REASON_CONFIG[reasonDraft.action].field}
              disabled={busyId != null}
            />
          </Field>
        </ConfirmDialog>
      )}
    </div>
  );
}
