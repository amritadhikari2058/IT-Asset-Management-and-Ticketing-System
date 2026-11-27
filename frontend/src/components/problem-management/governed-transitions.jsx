import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import { Badge, Button, Field, Input, LoadingRows, PageHeader, Panel, PanelPad } from '../../components';
import {
  acceptProblem, problemDetail, rejectProblem, reopenProblem, startInvestigation, submitProblem,
} from '../../services/problem-management';

export function GovernedTransitions({ problemId: problemIdProp, problem: problemProp }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const { isStaff, isManagerOrAdmin } = useAuth();
  const [problem, setProblem] = useState(problemProp ?? null);
  const [version, setVersion] = useState(problemProp?.version ?? 1);
  const [loading, setLoading] = useState(!problemProp);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [reopenOpen, setReopenOpen] = useState(false);

  const load = useCallback(async () => {
    if (problemProp) return;
    setLoading(true);
    setError('');
    try {
      const data = await problemDetail(problemId);
      setProblem(data);
      setVersion(data?.version ?? 1);
    } catch {
      setError('Could not load problem.');
    } finally {
      setLoading(false);
    }
  }, [problemId, problemProp]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const run = async (label, fn, payload = {}) => {
    if (busy) return;
    setBusy(label);
    setError('');
    setNotice('');
    try {
      const updated = await fn(problemId, { ...payload, expected_record_version: version });
      if (updated && typeof updated === 'object') {
        setProblem((prev) => ({ ...prev, ...updated }));
        if (updated.version != null) setVersion(updated.version);
      }
      setNotice(`${label} applied.`);
      setRejectOpen(false);
      setRejectReason('');
      setReopenOpen(false);
    } catch (e) {
      // A stale editor is the common failure here: the server refuses the
      // write and the operator must reload instead of retrying blindly.
      setError(e?.response?.data?.detail || `${label} failed.`);
    } finally {
      setBusy('');
    }
  };

  const submitReject = (ev) => {
    ev.preventDefault();
    if (!rejectReason.trim()) {
      setError('A reason is required to reject a problem.');
      return;
    }
    run('Reject', rejectProblem, { reason: rejectReason.trim() });
  };

  if (loading) return <LoadingRows n={4} />;
  if (!problem) {
    return <div className="error-summary" role="alert">{error || 'Problem not available.'}</div>;
  }

  return (
    <div>
      <PageHeader title={`${problem.problem_number}: ${problem.title}`} sub="Governed transitions" />
      {error && <div className="error-summary" role="alert">{error}</div>}
      {notice && <div className="success-summary" role="status">{notice}</div>}
      <Panel>
        <PanelPad>
          <Field label="Current status">
            <Badge kind="status-warning" value={problem.status} />
          </Field>
          <Field label="Current version">
            <Input value={version} readOnly />
          </Field>

          {isStaff && (
            <div className="row-gap">
              <Button disabled={busy === 'Submit'} onClick={() => run('Submit', submitProblem)}>Submit</Button>
              <Button disabled={busy === 'Accept'} onClick={() => run('Accept', acceptProblem)}>Accept</Button>
              <Button kind="danger" onClick={() => { setError(''); setRejectOpen(true); }}>Reject</Button>
              {isManagerOrAdmin && (
                <Button kind="secondary" onClick={() => run('Start Investigation', startInvestigation)}>
                  Start Investigation
                </Button>
              )}
              <Button kind="ghost" onClick={() => { setError(''); setReopenOpen(true); }}>Reopen…</Button>
            </div>
          )}

          {isStaff && rejectOpen && (
            <form onSubmit={submitReject} className="form-wrap">
              <Field label="Rejection reason" required>
                <Input value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} />
              </Field>
              <Button type="submit" kind="danger">Confirm reject</Button>
              <Button kind="ghost" onClick={() => { setRejectOpen(false); setRejectReason(''); }}>Cancel</Button>
            </form>
          )}

          {isStaff && reopenOpen && (
            <div className="form-wrap">
              <p>Reopening returns the problem to an active state.</p>
              <Button kind="primary" onClick={() => run('Reopen', reopenProblem)}>Confirm reopen</Button>
              <Button kind="ghost" onClick={() => setReopenOpen(false)}>Cancel</Button>
            </div>
          )}
        </PanelPad>
      </Panel>
    </div>
  );
}
