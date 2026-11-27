import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import { Badge, Button, DataTable, Field, Input, LoadingRows, Option, PageHeader, Panel, PanelPad, Select } from '../../components';
import {
  approveAction, cancelAction, completeAction, createAction, listActions,
  markActionIneffective, startAction, validateAction,
} from '../../services/problem-management';

const ACTION_TYPES = [
  ['corrective', 'Corrective'],
  ['preventive', 'Preventive'],
  ['root_cause', 'Root cause'],
  ['validation', 'Validation'],
  ['exception', 'Exception'],
];

const EMPTY = { title: '', description: '', action_type: 'corrective', due_at: '' };

export function Actions({ problemId: problemIdProp }) {
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

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listActions(problemId);
      setRows(Array.isArray(data) ? data : data?.results ?? []);
    } catch {
      setError('Could not load actions.');
    } finally {
      setLoading(false);
    }
  }, [problemId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const submit = async (ev) => {
    ev.preventDefault();
    if (!form.title.trim() || saving) return;
    setSaving(true);
    setError('');
    try {
      await createAction(problemId, {
        title: form.title.trim(),
        description: form.description.trim(),
        action_type: form.action_type,
        due_at: form.due_at || null,
      });
      setForm(EMPTY);
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not create action.');
    } finally {
      setSaving(false);
    }
  };

  // Every lifecycle move goes through its dedicated backend transition.
  const move = async (action, fn, label) => {
    if (busyId) return;
    setBusyId(action.id);
    setError('');
    setNotice('');
    try {
      await fn(action.id);
      setNotice(`${label} succeeded.`);
      await load();
    } catch (e) {
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail;
      setError(detail || (status === 409
        ? 'This action changed on the server. Reload and try again.'
        : `${label} failed.`));
    } finally {
      setBusyId(null);
    }
  };

  const columns = [
    { key: 'title', label: 'Action' },
    { key: 'action_type', label: 'Type', render: (r) => (r.action_type || '—').replace(/_/g, ' ') },
    { key: 'status', label: 'Status', render: (r) => <Badge kind="status-warning" value={r.status} /> },
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
          buttons.push(<Button key="ineffective" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, markActionIneffective, 'Mark ineffective')}>Ineffective</Button>);
        }
        if (!['verified', 'cancelled'].includes(r.status)) {
          buttons.push(<Button key="cancel" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, cancelAction, 'Cancel')}>Cancel</Button>);
        }
        return buttons.length ? <div className="row-gap">{buttons}</div> : '—';
      },
    },
  ];

  return (
    <div>
      <PageHeader title="Actions" sub="Corrective and preventive work" />
      {error && <div className="error-summary" role="alert">{error}</div>}
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
    </div>
  );
}
