import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import { Badge, Button, DataTable, Field, Input, LoadingRows, PageHeader, Panel, PanelPad } from '../../components';
import { createTimelineEvent, problemTimeline } from '../../services/problem-management';

// Values mirror ProblemTimelineEvent.EVENT_TYPE_CHOICES / SOURCE_CHOICES.
const EVENT_TYPES = [
  ['milestone', 'Milestone'],
  ['investigation_start', 'Investigation start'],
  ['root_cause_found', 'Root cause found'],
  ['workaround_implemented', 'Workaround implemented'],
  ['action_taken', 'Action taken'],
  ['validation_completed', 'Validation completed'],
  ['fix_implemented', 'Fix implemented'],
  ['problem_resolved', 'Problem resolved'],
  ['problem_closed', 'Problem closed'],
  ['exception_granted', 'Exception granted'],
  ['exception_denied', 'Exception denied'],
];
const SOURCES = [
  ['manual', 'Manual'],
  ['ticket', 'Ticket'],
  ['major_incident', 'Major incident'],
  ['change_review', 'Change review'],
  ['knowledge', 'Knowledge'],
  ['monitoring', 'Monitoring'],
  ['cmdb', 'CMDB'],
];

const localNow = () => {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 16);
};

export function Timeline({ problemId: problemIdProp, embedded = false }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const { isStaff } = useAuth();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState({
    event_type: 'milestone',
    source: 'manual',
    title: '',
    description: '',
    occurred_at: localNow(),
  });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await problemTimeline(problemId);
      setRows(Array.isArray(data) ? data : data?.results ?? []);
    } catch {
      setError('Could not load the timeline.');
    } finally {
      setLoading(false);
    }
  }, [problemId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const submit = async (ev) => {
    ev.preventDefault();
    if (!form.title.trim() || !form.occurred_at || saving) return;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      await createTimelineEvent(problemId, {
        event_type: form.event_type,
        source: form.source,
        title: form.title.trim(),
        description: form.description.trim(),
        occurred_at: new Date(form.occurred_at).toISOString(),
      });
      setForm((f) => ({ ...f, title: '', description: '', occurred_at: localNow() }));
      setNotice('Timeline event added.');
      await load();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not create the timeline event.');
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    { key: 'occurred_at', label: 'Occurred', render: (r) => (r.occurred_at ? new Date(r.occurred_at).toLocaleString() : '—') },
    { key: 'event_type', label: 'Type', render: (r) => <Badge kind="status-warning" value={r.event_type} /> },
    { key: 'title', label: 'Event' },
    { key: 'source', label: 'Source', render: (r) => r.source || '—' },
    { key: 'recorded_by_username', label: 'Recorded by', render: (r) => r.recorded_by_username || '—' },
  ];

  return (
    <div>
      {embedded
        ? <h3>Timeline</h3>
        : <PageHeader title="Timeline" sub="What happened, in order" />}
      {error && <div className="error-summary" role="alert">{error}</div>}
      {notice && <div className="success-summary" role="status">{notice}</div>}
      {loading ? <LoadingRows n={3} /> : (
        <Panel>
          <PanelPad>
            <DataTable columns={columns} rows={rows} keyOf={(r) => r.id} emptyTitle="No timeline events yet" />
          </PanelPad>
        </Panel>
      )}

      {isStaff && (
        <form onSubmit={submit}>
          <Panel>
            <PanelPad>
              <Field label="Event title" required>
                <Input value={form.title} placeholder="Event title" onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </Field>
              <Field label="Description">
                <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </Field>
              <Field label="Type">
                <select value={form.event_type} onChange={(e) => setForm({ ...form, event_type: e.target.value })}>
                  {EVENT_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </Field>
              <Field label="Source">
                <select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}>
                  {SOURCES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </Field>
              <Field label="Occurred at">
                <Input type="datetime-local" value={form.occurred_at} onChange={(e) => setForm({ ...form, occurred_at: e.target.value })} />
              </Field>
              <Button type="submit" disabled={!form.title.trim() || saving}>
                {saving ? 'Saving…' : 'Add Timeline Event'}
              </Button>
            </PanelPad>
          </Panel>
        </form>
      )}
    </div>
  );
}
