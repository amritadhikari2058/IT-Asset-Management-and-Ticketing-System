import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import { Badge, Button, DataTable, Field, Input, LoadingRows, Option, PageHeader, Panel, PanelPad, Select } from '../../components';
import {
  approveException, createException, expireException, listExceptions,
  rejectException, revokeException, submitException,
} from '../../services/problem-management';

// Verified free-text values recognised by the readiness rules; the model has
// no formal choices, but these are the values this workflow supports.
const EXCEPTION_TYPES = [
  ['operational', 'Operational'],
  ['unknown_root_cause', 'Unknown root cause'],
  ['critical', 'Critical'],
];

const REASON_SERVICES = {
  reject: rejectException,
  revoke: revokeException,
};

const REASON_CONFIG = {
  reject: {
    field: 'Rejection reason',
    placeholder: 'Rejection reason',
    confirm: 'Confirm rejection',
    moveLabel: 'Reject',
    missing: 'A rejection reason is required.',
  },
  revoke: {
    field: 'Revocation reason',
    placeholder: 'Revocation reason',
    confirm: 'Confirm revocation',
    moveLabel: 'Revoke',
    missing: 'A revocation reason is required.',
  },
};

// The date input picks a calendar day; the API validates a future DateTime.
// End of the selected local day keeps same-day selections valid after parsing.
const expiryPayload = (value) => (
  value ? new Date(`${value}T23:59:59`).toISOString() : null
);

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

export function Exceptions({ problemId: problemIdProp, embedded = false }) {
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
  const busyRef = useRef(null);
  const [reasonDraft, setReasonDraft] = useState({
    id: null, action: null, value: '', error: '',
  });

  const load = useCallback(async () => {
    setLoading(true);
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

  const cleanTitle = title.trim();

  const submit = async (ev) => {
    ev.preventDefault();
    if (!cleanTitle || saving) return;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      await createException(problemId, {
        title: cleanTitle,
        exception_type: exceptionType,
        reason: reason.trim(),
        conditions: conditions.trim(),
        expires_at: expiryPayload(expiresAt),
      });
      setTitle('');
      setExceptionType('operational');
      setReason('');
      setConditions('');
      setExpiresAt('');
      setNotice('Exception created.');
      await load();
    } catch (e) {
      setError(formatServiceError(e, 'Could not create exception.'));
    } finally {
      setSaving(false);
    }
  };

  const versionPayload = (row) => (
    row?.version == null ? {} : { expected_record_version: row.version }
  );

  const mergeRecord = (updated) => {
    if (!updated || updated.id == null) return;
    setRows((current) => current.map((row) => (
      row.id === updated.id ? { ...row, ...updated } : row
    )));
  };

  const closeReason = () => {
    setReasonDraft({ id: null, action: null, value: '', error: '' });
  };

  const move = async (row, fn, label, extra = {}) => {
    if (busyRef.current !== null) return;
    busyRef.current = row.id;
    setBusyId(row.id);
    setError('');
    setNotice('');
    try {
      const updated = await fn(row.id, { ...versionPayload(row), ...extra });
      mergeRecord(updated);
      setNotice(`${label} succeeded.`);
      closeReason();
      await load();
    } catch (e) {
      const status = e?.response?.status ?? e?.status;
      if (status === 409) {
        const detail = e?.response?.data?.detail
          || e?.response?.data?.error
          || (typeof e?.message === 'string' ? e.message : '')
          || 'The record changed on the server.';
        setError(`Version conflict: ${detail} Review the refreshed record before trying again.`);
        closeReason();
        await load();
      } else {
        setError(formatServiceError(e, `${label} failed.`));
      }
    } finally {
      busyRef.current = null;
      setBusyId(null);
    }
  };

  const openReason = (row, action) => {
    if (busyRef.current !== null) return;
    setError('');
    setNotice('');
    setReasonDraft({ id: row.id, action, value: '', error: '' });
  };

  const submitReason = (row, action) => {
    const config = REASON_CONFIG[action];
    const trimmed = reasonDraft.value.trim();
    if (!trimmed) {
      setReasonDraft((current) => ({ ...current, error: config.missing }));
      return;
    }
    setReasonDraft((current) => ({ ...current, error: '' }));
    move(row, REASON_SERVICES[action], config.moveLabel, { reason: trimmed });
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
    { key: 'created_by_username', label: 'Created by', render: (r) => r.created_by_username || '—' },
    { key: 'approved_by_username', label: 'Approved by', render: (r) => r.approved_by_username || '—' },
    {
      key: 'actions',
      label: 'Actions',
      render: (r) => {
        if (!isStaff) return '—';
        const disabled = busyId !== null;
        if (reasonDraft.id === r.id && reasonDraft.action) {
          const config = REASON_CONFIG[reasonDraft.action];
          return (
            <form
              className="form"
              aria-label={`${config.moveLabel} exception ${r.id}`}
              onSubmit={(ev) => {
                ev.preventDefault();
                submitReason(r, reasonDraft.action);
              }}
            >
              <Field label={config.field} error={reasonDraft.error} required>
                <Input
                  value={reasonDraft.value}
                  onChange={(e) => setReasonDraft((current) => ({
                    ...current, value: e.target.value, error: '',
                  }))}
                  placeholder={config.placeholder}
                  aria-label={config.field}
                  disabled={disabled}
                />
              </Field>
              <div className="row-gap">
                <Button type="submit" size="small" disabled={disabled}>
                  {config.confirm}
                </Button>
                <Button type="button" kind="ghost" size="small" disabled={disabled} onClick={closeReason}>
                  Cancel
                </Button>
              </div>
            </form>
          );
        }
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
          buttons.push(<Button key="reject" kind="ghost" size="small" disabled={disabled} onClick={() => openReason(r, 'reject')}>Reject</Button>);
        }
        if (['active', 'approved'].includes(r.status)) {
          buttons.push(<Button key="revoke" kind="ghost" size="small" disabled={disabled} onClick={() => openReason(r, 'revoke')}>Revoke</Button>);
          buttons.push(<Button key="expire" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, expireException, 'Expire')}>Expire</Button>);
        }
        return buttons.length ? <div className="row-gap">{buttons}</div> : '—';
      },
    },
  ];

  return (
    <div>
      {embedded
        ? <h3>Exceptions</h3>
        : <PageHeader title="Exceptions" sub="Time-bounded risk acceptance" />}
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
              <Field label="Exception type">
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
              <Button type="submit" disabled={!cleanTitle || saving}>
                {saving ? 'Saving…' : 'Create Exception'}
              </Button>
              <Button
                type="button"
                kind="ghost"
                onClick={() => {
                  setTitle('');
                  setExceptionType('operational');
                  setReason('');
                  setConditions('');
                  setExpiresAt('');
                }}
              >
                Cancel
              </Button>
            </PanelPad>
          </Panel>
        </form>
      )}
    </div>
  );
}
