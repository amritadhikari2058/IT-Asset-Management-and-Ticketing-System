import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import { Badge, Button, Field, Input, LoadingRows, Option, PageHeader, Panel, PanelPad, Select } from '../../components';
import {
  approveRCA, createFactor, createFiveWhy, createRCA, deleteFactor, deleteFiveWhy,
  editFactor, editFiveWhy, editRCA, fiveWhys, getRCA, problemDetail,
  rejectRCA, rootCauseFactors, submitRCA, supersedeRCA,
} from '../../services/problem-management';

const FINAL_STATUSES = ['approved', 'rejected', 'superseded'];
const FACTOR_CATEGORIES = ['people', 'process', 'technology', 'method', 'environment', 'supplier', 'management'];
const EMPTY_WHY = { question_number: 1, question_text: '', answer: '' };
const EMPTY_FACTOR = { category: 'technology', factor: '', contribution: '' };

export function RCA({ rcaId: rcaIdProp, problemId: problemIdProp }) {
  const params = useParams();
  const rcaId = rcaIdProp ?? params.rcaId;
  const problemId = problemIdProp ?? params.id;
  const { isManagerOrAdmin, user } = useAuth();
  const [rca, setRca] = useState(null);
  const [whys, setWhys] = useState([]);
  const [factors, setFactors] = useState([]);
  const [form, setForm] = useState({ title: '', description: '' });
  const [version, setVersion] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [whyForm, setWhyForm] = useState(EMPTY_WHY);
  const [factorForm, setFactorForm] = useState(EMPTY_FACTOR);
  const [analysisId, setAnalysisId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      if (rcaId) {
        const data = await getRCA(rcaId);
        const record = data?.data ?? data;
        setRca(record);
        setForm({
          title: record?.title ?? '',
          description: record?.description ?? '',
        });
        setVersion(record?.version ?? null);
        setAnalysisId(record?.id ?? null);
        const target = record?.problem ?? problemId;
        if (target) {
          try { setWhys((await fiveWhys(target))?.results ?? []); } catch { setWhys([]); }
          try { setFactors((await rootCauseFactors(target))?.results ?? []); } catch { setFactors([]); }
        }
      } else if (problemId) {
        const problem = await problemDetail(problemId);
        setRca(null);
        setForm((f) => ({ ...f, title: problem?.title ? `RCA for ${problem.problem_number}` : f.title }));
      }
    } catch {
      setError('Could not load RCA.');
    } finally {
      setLoading(false);
    }
  }, [rcaId, problemId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const locked = FINAL_STATUSES.includes(rca?.status);
  const selfApproval = Boolean(
    rca?.created_by_username && user?.username && rca.created_by_username === user.username,
  );

  const run = async (label, fn) => {
    if (busy) return;
    setBusy(label);
    setError('');
    setNotice('');
    try {
      const result = await fn();
      if (result && typeof result === 'object') {
        setRca((prev) => ({ ...prev, ...result }));
        if (result.version != null) setVersion(result.version);
      }
      setNotice(`${label} succeeded.`);
    } catch (e) {
      setError(e?.response?.data?.detail || `${label} failed.`);
    } finally {
      setBusy('');
    }
  };

  const payload = () => ({
    title: form.title,
    description: form.description,
  });

  // Why/factor mutations refresh from the server list; the response body is
  // never merged into local state as an authoritative collection.
  const refresh = async () => {
    const target = rca?.problem ?? problemId;
    if (!target) return;
    try {
      const data = await fiveWhys(target);
      setWhys(Array.isArray(data) ? data : data?.results ?? []);
    } catch { setWhys([]); }
    try {
      const data = await rootCauseFactors(target);
      setFactors(Array.isArray(data) ? data : data?.results ?? []);
    } catch { setFactors([]); }
  };

  const addWhy = async () => {
    if (!analysisId || !whyForm.question_text.trim()) return;
    try {
      await createFiveWhy({
        analysis: analysisId,
        question_number: Number(whyForm.question_number) || 1,
        question_text: whyForm.question_text.trim(),
        answer: whyForm.answer.trim(),
      });
      setWhyForm(EMPTY_WHY);
      setError('');
      await refresh();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not add the why.');
    }
  };

  const moveWhy = async (row, changes) => {
    try {
      await editFiveWhy(row.id, changes);
      setError('');
      await refresh();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not update the why.');
    }
  };

  const removeWhy = async (row) => {
    try {
      await deleteFiveWhy(row.id);
      setError('');
      await refresh();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not delete the why.');
    }
  };

  const addFactor = async () => {
    if (!analysisId || !factorForm.factor.trim()) return;
    try {
      await createFactor({
        analysis: analysisId,
        category: factorForm.category,
        factor: factorForm.factor.trim(),
        contribution: factorForm.contribution.trim(),
      });
      setFactorForm(EMPTY_FACTOR);
      setError('');
      await refresh();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not add the factor.');
    }
  };

  const moveFactor = async (row, changes) => {
    try {
      await editFactor(row.id, changes);
      setError('');
      await refresh();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not update the factor.');
    }
  };

  const removeFactor = async (row) => {
    try {
      await deleteFactor(row.id);
      setError('');
      await refresh();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not delete the factor.');
    }
  };

  if (loading) return <LoadingRows n={4} />;

  return (
    <div>
      <PageHeader
        title={rcaId ? `RCA #${rcaId}` : 'Create RCA'}
        sub={rca?.status ? `Status: ${rca.status}` : 'Root-cause analysis'}
      />
      {error && <div className="error-summary" role="alert">{error}</div>}
      {notice && <div className="success-summary" role="status">{notice}</div>}
      <Panel>
        <PanelPad>
          <p><strong>Title: {rca?.title ?? form.title ?? ''}</strong></p>
          {rca?.status && <p><Badge kind="status-warning" value={rca.status} /></p>}

          <Field label="Title" required>
            <Input value={form.title} disabled={locked} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Description">
            <Input value={form.description} disabled={locked} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <Input type="hidden" value={version ?? ''} readOnly />

          {!rcaId && (
            <Button
              disabled={!form.title.trim() || busy === 'Create'}
              onClick={() => run('Create', () => createRCA({ problem: Number(problemId), ...payload() }))}
            >
              Create RCA
            </Button>
          )}

          {rcaId && !locked && (
            <div className="row-gap">
              <Button
                disabled={busy === 'Update'}
                onClick={() => run('Update', () => editRCA(rcaId, payload(), version))}
              >
                Update RCA
              </Button>
              <Button kind="danger" onClick={() => run('Supersede', () => supersedeRCA(rcaId, { expected_record_version: version }))}>
                Supersede
              </Button>
            </div>
          )}

          {rcaId && locked && (
            <p className="muted">This analysis is {rca?.status} and can no longer be edited.</p>
          )}

          {rcaId && isManagerOrAdmin && !locked && (
            <div className="row-gap">
              <Button disabled={busy === 'Submit'} onClick={() => run('Submit', () => submitRCA(rcaId, { expected_record_version: version }))}>
                Submit RCA
              </Button>
              <Button
                disabled={selfApproval || busy === 'Approve'}
                title={selfApproval ? 'You cannot approve your own RCA.' : undefined}
                onClick={() => run('Approve', () => approveRCA(rcaId, { expected_record_version: version }))}
              >
                Approve RCA
              </Button>
              <Button kind="danger" onClick={() => run('Reject', () => rejectRCA(rcaId, { expected_record_version: version }))}>
                Reject RCA
              </Button>
            </div>
          )}

          {rcaId && isManagerOrAdmin && selfApproval && (
            <p className="muted">You cannot approve your own RCA.</p>
          )}
        </PanelPad>
      </Panel>

      <Panel>
        <PanelPad>
          <h3>Five Whys</h3>
          {whys.length === 0
            ? <p className="muted">No Five Whys recorded.</p>
            : whys.map((w) => (
              <div key={w.id}>
                <p>{w.question_number}. {w.question_text}{w.answer ? ` — ${w.answer}` : ''}</p>
                {!locked && (
                  <div className="row-gap">
                    <Button kind="ghost" size="small" onClick={() => moveWhy(w, { answer: w.answer || 'Answered' })}>Set answer</Button>
                    <Button kind="ghost" size="small" onClick={() => removeWhy(w)}>Delete</Button>
                  </div>
                )}
              </div>
            ))}
          {analysisId && !locked && (
            <form onSubmit={(ev) => { ev.preventDefault(); addWhy(); }}>
              <Field label="Why question" required>
                <Input value={whyForm.question_text} onChange={(e) => setWhyForm({ ...whyForm, question_text: e.target.value })} />
              </Field>
              <Field label="Question number">
                <Input type="number" min="1" value={whyForm.question_number} onChange={(e) => setWhyForm({ ...whyForm, question_number: Number(e.target.value) })} />
              </Field>
              <Field label="Answer">
                <Input value={whyForm.answer} onChange={(e) => setWhyForm({ ...whyForm, answer: e.target.value })} />
              </Field>
              <Button type="submit" disabled={!whyForm.question_text.trim()}>Add Why</Button>
            </form>
          )}

          <h3>Root-Cause Factors</h3>
          {factors.length === 0
            ? <p className="muted">No root-cause factors recorded.</p>
            : factors.map((f) => (
              <div key={f.id}>
                <p>{f.category}: {f.factor}{f.contribution ? ` — ${f.contribution}` : ''}</p>
                {!locked && (
                  <div className="row-gap">
                    <Button kind="ghost" size="small" onClick={() => moveFactor(f, { factor: `${f.factor} (reviewed)` })}>Mark reviewed</Button>
                    <Button kind="ghost" size="small" onClick={() => removeFactor(f)}>Delete</Button>
                  </div>
                )}
              </div>
            ))}
          {analysisId && !locked && (
            <form onSubmit={(ev) => { ev.preventDefault(); addFactor(); }}>
              <Field label="Factor category">
                <Select value={factorForm.category} onChange={(e) => setFactorForm({ ...factorForm, category: e.target.value })}>
                  {FACTOR_CATEGORIES.map((c) => <Option key={c} value={c}>{c}</Option>)}
                </Select>
              </Field>
              <Field label="Factor" required>
                <Input value={factorForm.factor} onChange={(e) => setFactorForm({ ...factorForm, factor: e.target.value })} />
              </Field>
              <Field label="Contribution">
                <Input value={factorForm.contribution} onChange={(e) => setFactorForm({ ...factorForm, contribution: e.target.value })} />
              </Field>
              <Button type="submit" disabled={!factorForm.factor.trim()}>Add Factor</Button>
            </form>
          )}
        </PanelPad>
      </Panel>
    </div>
  );
}
