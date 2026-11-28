import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import { Badge, Button, DataTable, Field, Input, LoadingRows, PageHeader, Panel, PanelPad } from '../../components';
import {
  approveWorkaround, createWorkaround, expireWorkaround, listWorkarounds,
  publishWorkaround, retireWorkaround, submitWorkaround,
} from '../../services/problem-management';

export function Workarounds({ problemId: problemIdProp, embedded = false }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const { isStaff, isManagerOrAdmin } = useAuth();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [title, setTitle] = useState('');
  const [steps, setSteps] = useState('');
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const busyRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listWorkarounds(problemId);
      setRows(Array.isArray(data) ? data : data?.results ?? []);
    } catch {
      setError('Could not load workarounds.');
    } finally {
      setLoading(false);
    }
  }, [problemId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const cleanTitle = title.trim();
  const cleanSteps = steps.trim();

  const submit = async (ev) => {
    ev.preventDefault();
    if (!cleanTitle || !cleanSteps || saving) return;
    setSaving(true);
    setError('');
    try {
      await createWorkaround(problemId, { title: cleanTitle, steps: cleanSteps });
      setTitle('');
      setSteps('');
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not create workaround.');
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

  const move = async (row, fn, label) => {
    if (busyRef.current !== null) return;
    busyRef.current = row.id;
    setBusyId(row.id);
    setError('');
    setNotice('');
    try {
      const updated = await fn(row.id, versionPayload(row));
      mergeRecord(updated);
      setNotice(`${label} succeeded.`);
      await load();
    } catch (e) {
      const status = e?.response?.status ?? e?.status;
      if (status === 409) {
        const detail = e?.response?.data?.detail
          || e?.response?.data?.error
          || (typeof e?.message === 'string' ? e.message : '')
          || 'The record changed on the server.';
        setError(`Version conflict: ${detail} Review the refreshed record before trying again.`);
        await load();
      } else {
        setError(e?.response?.data?.detail || `${label} failed.`);
      }
    } finally {
      busyRef.current = null;
      setBusyId(null);
    }
  };

  const columns = [
    { key: 'title', label: 'Workaround' },
    { key: 'status', label: 'Status', render: (r) => <Badge kind="status-warning" value={r.status} /> },
    { key: 'steps', label: 'Steps', render: (r) => r.steps || '—' },
    {
      key: 'actions',
      label: 'Actions',
      render: (r) => {
        if (!isStaff) return '—';
        const disabled = busyId !== null;
        const buttons = [];
        if (r.status === 'draft') {
          buttons.push(<Button key="submit" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, submitWorkaround, 'Submit')}>Submit</Button>);
        }
        if (r.status === 'submitted' && isManagerOrAdmin) {
          buttons.push(<Button key="approve" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, approveWorkaround, 'Approve')}>Approve</Button>);
        }
        if (r.status === 'approved' && isManagerOrAdmin) {
          buttons.push(<Button key="publish" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, publishWorkaround, 'Publish')}>Publish</Button>);
        }
        if (r.status === 'published') {
          buttons.push(<Button key="expire" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, expireWorkaround, 'Expire')}>Expire</Button>);
        }
        if (!['retired', 'expired'].includes(r.status)) {
          buttons.push(<Button key="retire" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, retireWorkaround, 'Retire')}>Retire</Button>);
        }
        return buttons.length ? <div className="row-gap">{buttons}</div> : '—';
      },
    },
  ];

  return (
    <div>
      {embedded
        ? <h3>Workarounds</h3>
        : <PageHeader title="Workarounds" sub="Temporary mitigations" />}
      {error && <div className="error-summary" role="alert">{error}</div>}
      {notice && <div className="success-summary" role="status">{notice}</div>}
      {loading ? <LoadingRows n={3} /> : (
        <Panel>
          <PanelPad>
            <DataTable columns={columns} rows={rows} keyOf={(r) => r.id} emptyTitle="No workarounds yet" />
          </PanelPad>
        </Panel>
      )}

      {isStaff && (
        <form onSubmit={submit}>
          <Panel>
            <PanelPad>
              <Field label="Workaround title" required>
                <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Workaround title" />
              </Field>
              <Field label="Steps" required>
                <Input value={steps} onChange={(e) => setSteps(e.target.value)} placeholder="Steps" />
              </Field>
              <Button type="submit" disabled={!cleanTitle || !cleanSteps || saving}>
                {saving ? 'Saving…' : 'Create Workaround'}
              </Button>
              <Button kind="ghost" onClick={() => { setTitle(''); setSteps(''); }}>Cancel</Button>
            </PanelPad>
          </Panel>
        </form>
      )}
    </div>
  );
}
