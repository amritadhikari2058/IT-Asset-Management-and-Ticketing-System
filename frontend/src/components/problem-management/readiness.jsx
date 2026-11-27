import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Badge, LoadingRows, PageHeader, Panel, PanelPad } from '../../components';
import { problemReadiness } from '../../services/problem-management';

const EMPTY = {
  ready_for_resolution: false,
  ready_for_closure: false,
  blockers: [],
  warnings: [],
  counts: {
    open_blocking_tasks: 0,
    open_required_actions: 0,
    failed_validations: 0,
    open_critical_tickets: 0,
    active_exceptions: 0,
  },
};

export function Readiness({ problemId: problemIdProp }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const [readiness, setReadiness] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await problemReadiness(problemId);
      setReadiness({
        ...EMPTY,
        ...data,
        counts: { ...EMPTY.counts, ...(data?.counts ?? {}) },
      });
    } catch {
      setError('Could not load readiness.');
    } finally {
      setLoading(false);
    }
  }, [problemId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  if (loading) return <LoadingRows n={3} />;

  return (
    <div>
      <PageHeader title="Readiness State" sub="Resolution and closure gates" />
      {error && <div className="error-summary" role="alert">{error}</div>}
      <Panel>
        <PanelPad>
          <p>Resolution readiness:{' '}
            <Badge kind={readiness.ready_for_resolution ? 'status-success' : 'status-muted'}>
              {readiness.ready_for_resolution ? 'Ready' : 'Not ready'}
            </Badge>
          </p>
          <p>Closure readiness:{' '}
            <Badge kind={readiness.ready_for_closure ? 'status-success' : 'status-muted'}>
              {readiness.ready_for_closure ? 'Ready' : 'Not ready'}
            </Badge>
          </p>
          <p>Blockers: {readiness.blockers.join(', ') || 'None'}</p>
          <p>Warnings: {readiness.warnings.join(', ') || 'None'}</p>
          <p>Open blocking tasks: {readiness.counts.open_blocking_tasks}</p>
          <p>Open required actions: {readiness.counts.open_required_actions}</p>
          <p>Failed validations: {readiness.counts.failed_validations}</p>
          <p>Open critical tickets: {readiness.counts.open_critical_tickets}</p>
          <p>Active exceptions: {readiness.counts.active_exceptions}</p>
        </PanelPad>
      </Panel>
    </div>
  );
}
