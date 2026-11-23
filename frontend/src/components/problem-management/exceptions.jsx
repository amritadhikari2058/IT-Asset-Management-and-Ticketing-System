import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import { Badge, Button, DataTable, Field, Input, LoadingRows, Option, PageHeader, Panel, PanelPad, Select } from '../../components';
import {
  approveException, createException, expireException, listExceptions,
  rejectException, revokeException, submitException,
} from '../../services/problem-management';

// Backend `exception_type` is a free-text CharField (default "operational");
// these are the values the readiness rules recognise.
const EXCEPTION_TYPES = [
  ['operational', 'Operational'],
  ['unknown_root_cause', 'Unknown root cause'],
  ['critical', 'Critical'],
];

export function Exceptions({ problemId: problemIdProp }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const { isStaff, isManagerOrAdmin, user } = useAuth();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [title, setTitle] = useState('');
  const [exceptionType, setExceptionType] = useState('operational');
  const [reason, setReason] = useState('');
  const [conditions, setConditions] = useState('');
  const [expiresAt, setExpiresAt] = useState('');
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listExceptions(problemId);
      setRows(Array.isArray(data) ? data : data?.results ?? []);
    } catch {
      setError('Could not load exceptions.');
    } finally {
      setLoading(false);
    }
  }, [problemId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const submit = async (ev) => {
    ev.preventDefault();
    if (!title.trim() || saving) return;
    setSaving(true);
    setError('');
    try {
      await createException(problemId, {
        title: title.trim(),
        exception_type: exceptionType,
        reason: reason.trim(),
        conditions: conditions.trim(),
        expires_at: expiresAt || null,
      });
      setTitle('');
      setExceptionType('operational');
      setReason('');
      setConditions('');
      setExpiresAt('');
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not create exception.');
    } finally {
      setSaving(false);
    }
  };

  const move = async (row, fn, label) => {
    if (busyId) return;
    setBusyId(row.id);
    setError('');
    setNotice('');
    try {
      await fn(row.id);
      setNotice(`${label} succeeded.`);
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || `${label} failed.`);
    } finally {
      setBusyId(null);
    }
  };

  const selfCreated = (row) => Boolean(
    row?.created_by_username && user?.username && row.created_by_username === user.username,
  );

  const columns = [
    { key: 'title', label: 'Exception' },
    { key: 'exception_type', label: 'Type', render: (r) => (r.exception_type || '—').replace(/_/g, ' ') },
    { key: 'status', label: 'Status', render: (r) => <Badge kind="status-warning" value={r.status} /> },
    { key: 'reason', label: 'Reason', render: (r) => r.reason || '—' },
    { key: 'expires_at', label: 'Expires', render: (r) => (r.expires_at ? new Date(r.expires_at).toLocaleDateString() : '—') },
    {
      key: 'actions',
      label: 'Actions',
      render: (r) => {
        if (!isStaff) return '—';
        const disabled = busyId === r.id;
        const buttons = [];
        if (r.status === 'draft') {
          buttons.push(<Button key="submit" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, submitException, 'Submit')}>Submit</Button>);
        }
        if (r.status === 'active' && isManagerOrAdmin) {
          buttons.push(
            <Button
              key="approve"
              kind="ghost"
              size="small"
              disabled={disabled || selfCreated(r)}
              title={selfCreated(r) ? 'You cannot approve your own exception.' : undefined}
              onClick={() => move(r, approveException, 'Approve')}
            >
              Approve
            </Button>,
          );
          buttons.push(<Button key="reject" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, rejectException, 'Reject')}>Reject</Button>);
        }
        if (['active', 'approved'].includes(r.status)) {
          buttons.push(<Button key="revoke" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, revokeException, 'Revoke')}>Revoke</Button>);
          buttons.push(<Button key="expire" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, expireException, 'Expire')}>Expire</Button>);
        }
        return buttons.length ? <div className="row-gap">{buttons}</div> : '—';
      },
    },
  ];

  return (
    <div>
      <PageHeader title="Exceptions" sub="Time-bounded risk acceptance" />
      {error && <div className="error-summary" role="alert">{error}</div>}
      {notice && <div className="success-summary" role="status">{notice}</div>}
      {loading ? <LoadingRows n={3} /> : (
        <Panel>
          <PanelPad>
            <DataTable columns={columns} rows={rows} keyOf={(r) => r.id} emptyTitle="No exceptions yet" />
          </PanelPad>
        </Panel>
      )}

      {isStaff && (
        <form onSubmit={submit}>
          <Panel>
            <PanelPad>
              <Field label="Exception title" required>
                <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Exception title" />
              </Field>
              <Field label="Type">
                <Select value={exceptionType} onChange={(e) => setExceptionType(e.target.value)}>
                  {EXCEPTION_TYPES.map(([value, label]) => <Option key={value} value={value}>{label}</Option>)}
                </Select>
              </Field>
              <Field label="Reason">
                <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason" />
              </Field>
              <Field label="Conditions">
                <Input value={conditions} onChange={(e) => setConditions(e.target.value)} placeholder="Conditions" />
              </Field>
              <Field label="Expires at">
                <Input type="date" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
              </Field>
              <Button type="submit" disabled={!title.trim() || saving}>
                {saving ? 'Saving…' : 'Create Exception'}
              </Button>
              <Button kind="ghost" onClick={() => { setTitle(''); setReason(''); setConditions(''); setExpiresAt(''); }}>Cancel</Button>
            </PanelPad>
          </Panel>
        </form>
      )}
    </div>
  );
}
