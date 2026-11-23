import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { DataTable, LoadingRows, PageHeader, Panel, PanelPad } from '../../components';
import { problemHistory } from '../../services/problem-management';

export function History({ problemId: problemIdProp }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await problemHistory(problemId);
      setRows(Array.isArray(data) ? data : data?.results ?? []);
    } catch {
      setError('Could not load history.');
    } finally {
      setLoading(false);
    }
  }, [problemId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const columns = [
    { key: 'event_type', label: 'Event' },
    { key: 'actor_username', label: 'Actor', render: (r) => r.actor_username || '—' },
    { key: 'previous_status', label: 'From', render: (r) => r.previous_status || '—' },
    { key: 'new_status', label: 'To', render: (r) => r.new_status || '—' },
    { key: 'created_at', label: 'When', render: (r) => (r.created_at ? new Date(r.created_at).toLocaleString() : '—') },
    { key: 'detail', label: 'Detail', render: (r) => r.detail || '(no detail)' },
  ];

  return (
    <div>
      <PageHeader title="Problem History" sub="Append-only record of governed changes" />
      {error && <div className="error-summary" role="alert">{error}</div>}
      {loading ? <LoadingRows n={3} /> : (
        <Panel>
          <PanelPad>
            <DataTable columns={columns} rows={rows} keyOf={(r) => r.id} emptyTitle="No history events yet" />
          </PanelPad>
        </Panel>
      )}
    </div>
  );
}
