import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import { Badge, Button, DataTable, Field, Input, LoadingRows, PageHeader, Panel, PanelPad } from '../../components';
import {
  cancelValidation, createValidation, failValidation, listValidations,
  markValidationInconclusive, passValidation, startValidation,
} from '../../services/problem-management';

export function Validations({ problemId: problemIdProp }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const { isStaff } = useAuth();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [title, setTitle] = useState('');
  const [testPlan, setTestPlan] = useState('');
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listValidations(problemId);
      setRows(Array.isArray(data) ? data : data?.results ?? []);
    } catch {
      setError('Could not load validations.');
    } finally {
      setLoading(false);
    }
  }, [problemId]);

  useEffect(() => { load(); }, [load]);

  const submit = async (ev) => {
    ev.preventDefault();
    if (!title.trim() || saving) return;
    setSaving(true);
    setError('');
    try {
      await createValidation(problemId, { title: title.trim(), test_plan: testPlan.trim() });
      setTitle('');
      setTestPlan('');
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not create validation.');
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

  // `status` and `passed` are server-owned; transitions are the only writers.
  const columns = [
    { key: 'title', label: 'Validation' },
    { key: 'status', label: 'Status', render: (r) => <Badge kind="status-warning" value={r.status} /> },
    { key: 'passed', label: 'Passed', render: (r) => (r.passed ? 'Yes' : 'No') },
    {
      key: 'actions',
      label: 'Actions',
      render: (r) => {
        if (!isStaff) return '—';
        const disabled = busyId === r.id;
        const buttons = [];
        if (r.status === 'draft') {
          buttons.push(<Button key="start" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, startValidation, 'Start')}>Start</Button>);
        }
        if (['draft', 'in_progress'].includes(r.status)) {
          buttons.push(<Button key="pass" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, passValidation, 'Pass')}>Pass</Button>);
          buttons.push(<Button key="fail" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, failValidation, 'Fail')}>Fail</Button>);
          buttons.push(<Button key="inconclusive" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, markValidationInconclusive, 'Inconclusive')}>Inconclusive</Button>);
          buttons.push(<Button key="cancel" kind="ghost" size="small" disabled={disabled} onClick={() => move(r, cancelValidation, 'Cancel')}>Cancel</Button>);
        }
        return buttons.length ? <div className="row-gap">{buttons}</div> : '—';
      },
    },
  ];

  return (
    <div>
      <PageHeader title="Validations" sub="Validation runs recorded against this problem" />
      {error && <div className="error-summary" role="alert">{error}</div>}
      {notice && <div className="success-summary" role="status">{notice}</div>}
      {loading ? <LoadingRows n={3} /> : (
        <Panel>
          <PanelPad>
            <DataTable columns={columns} rows={rows} keyOf={(r) => r.id} emptyTitle="No validations yet" />
          </PanelPad>
        </Panel>
      )}

      {isStaff && (
        <form onSubmit={submit}>
          <Panel>
            <PanelPad>
              <Field label="Validation title" required>
                <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Validation title" />
              </Field>
              <Field label="Test plan">
                <Input value={testPlan} onChange={(e) => setTestPlan(e.target.value)} placeholder="Test plan" />
              </Field>
              <Button type="submit" disabled={!title.trim() || saving}>
                {saving ? 'Saving…' : 'Create Validation'}
              </Button>
              <Button kind="ghost" onClick={() => { setTitle(''); setTestPlan(''); }}>Cancel</Button>
            </PanelPad>
          </Panel>
        </form>
      )}
    </div>
  );
}
