import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import { Badge, Button, Field, Input, LoadingRows, Option, PageHeader, Panel, PanelPad, Select, Textarea } from '../../components';
import {
  approveRCA, createFactor, createFiveWhy, createRCA, deleteFactor, deleteFiveWhy,
  editFactor, editFiveWhy, editRCA, fiveWhys, getRCA, problemDetail, problemRCA,
  rejectRCA, rootCauseFactors, submitRCA, supersedeRCA,
} from '../../services/problem-management';

const FINAL_STATUSES = ['approved', 'rejected', 'superseded'];
const EDITABLE_STATUSES = ['draft', 'in_review'];
const FACTOR_CATEGORIES = [
  ['people', 'People'],
  ['method', 'Method'],
  ['machine', 'Machine'],
  ['material', 'Material'],
  ['environment', 'Environment'],
  ['other', 'Other'],
];
const FACTOR_CATEGORY_LABELS = Object.fromEntries(FACTOR_CATEGORIES);
const EMPTY_WHY = { question_number: 1, question_text: '', answer: '' };
const EMPTY_FACTOR = { category: 'people', factor: '' };
const EMPTY_FORM = {
  title: '',
  description: '',
  analysis_method: 'five_whys',
  findings: '',
  concluded_at: '',
};
const FIELD_LABELS = {
  title: 'Title',
  description: 'Description',
  analysis_method: 'Analysis method',
  findings: 'Findings',
  concluded_at: 'Concluded at',
  analysis: 'RCA',
  question_number: 'Question number',
  question_text: 'Question',
  answer: 'Answer',
  category: 'Category',
  factor: 'Factor',
  non_field_errors: 'Error',
};

const normalizeRows = (data) => (Array.isArray(data) ? data : data?.results ?? []);

const sortWhys = (rows) => [...rows].sort((a, b) => {
  const left = Number(a.question_number) || 0;
  const right = Number(b.question_number) || 0;
  return left - right || Number(a.id) - Number(b.id);
});

const sortFactors = (rows) => [...rows].sort((a, b) => (
  String(a.factor ?? '').localeCompare(String(b.factor ?? ''))
  || Number(a.id) - Number(b.id)
));

const toDateTimeInput = (value) => {
  if (!value) return '';
  const text = String(value);
  return text.length > 19 ? text.slice(0, 19) : text;
};

const readError = (error, fallback) => {
  const data = error?.response?.data;
  if (!data) return fallback;
  if (typeof data === 'string') return data;
  if (Array.isArray(data)) return data.join(' ');
  if (data.detail) {
    return Array.isArray(data.detail) ? data.detail.join(' ') : String(data.detail);
  }
  const parts = Object.entries(data).map(([field, value]) => {
    const text = Array.isArray(value)
      ? value.join(' ')
      : (value && typeof value === 'object' ? JSON.stringify(value) : String(value));
    return `${FIELD_LABELS[field] || field.replace(/_/g, ' ')}: ${text}`;
  });
  return parts.length ? parts.join(' ') : fallback;
};

export function RCA({
  rcaId: rcaIdProp, problemId: problemIdProp, problemTitle, onChanged,
}) {
  const params = useParams();
  const rcaId = rcaIdProp ?? params.rcaId;
  const problemId = problemIdProp ?? params.id;
  const { isStaff, isManagerOrAdmin, user } = useAuth();
  const [rca, setRca] = useState(null);
  const [whys, setWhys] = useState([]);
  const [factors, setFactors] = useState([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [version, setVersion] = useState(null);
  const [loadedConcludedAt, setLoadedConcludedAt] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [whyForm, setWhyForm] = useState(EMPTY_WHY);
  const [factorForm, setFactorForm] = useState(EMPTY_FACTOR);
  const [whysLoading, setWhysLoading] = useState(true);
  const [factorsLoading, setFactorsLoading] = useState(true);
  const [whysError, setWhysError] = useState('');
  const [factorsError, setFactorsError] = useState('');
  const [editingWhyId, setEditingWhyId] = useState(null);
  const [whyEdit, setWhyEdit] = useState({ question_text: '', answer: '' });
  const [editingFactorId, setEditingFactorId] = useState(null);
  const [factorEdit, setFactorEdit] = useState({ category: 'people', factor: '' });
  const [analysisId, setAnalysisId] = useState(null);
  const [createdId, setCreatedId] = useState(null);
  const [rejectReason, setRejectReason] = useState('');
  const activeId = rcaId ?? createdId;
  const canManage = Boolean(isStaff);
  const canGovern = Boolean(isManagerOrAdmin);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      if (activeId) {
        const data = await getRCA(activeId);
        const record = data?.data ?? data;
        setRca(record);
        setForm({
          title: record?.title ?? '',
          description: record?.description ?? '',
          analysis_method: record?.analysis_method ?? 'five_whys',
          findings: record?.findings ?? '',
          concluded_at: toDateTimeInput(record?.concluded_at),
        });
        setVersion(record?.version ?? null);
        setLoadedConcludedAt(record?.concluded_at ?? '');
        setAnalysisId(record?.id ?? null);
      } else if (problemId) {
        let scopedRca = null;

        try {
          const scopedData = await problemRCA(problemId);
          scopedRca = scopedData?.data ?? scopedData;
        } catch (e) {
          if (e?.response?.status !== 404) {
            throw e;
          }
        }

        if (scopedRca?.id) {
          const data = await getRCA(scopedRca.id);
          const record = data?.data ?? data;

          setRca(record);
          setForm({
            title: record?.title ?? '',
            description: record?.description ?? '',
            analysis_method: record?.analysis_method ?? 'five_whys',
            findings: record?.findings ?? '',
            concluded_at: toDateTimeInput(record?.concluded_at),
          });
          setVersion(record?.version ?? null);
          setLoadedConcludedAt(record?.concluded_at ?? '');
          setAnalysisId(record?.id ?? null);
        } else {
          let title = problemTitle;
          if (title === undefined) {
            const problem = await problemDetail(problemId);
            title = problem?.title ? `RCA for ${problem.problem_number}` : '';
          }

          setRca(null);
          setVersion(null);
          setAnalysisId(null);
          setLoadedConcludedAt('');
          setForm({
            ...EMPTY_FORM,
            title: title ?? '',
          });
        }
      }
    } catch (e) {
      setError(readError(e, 'Could not load RCA.'));
    } finally {
      setLoading(false);
    }
  }, [activeId, problemId, problemTitle]);

  const scopeId = rca?.problem != null
    ? String(rca.problem)
    : (problemId != null ? String(problemId) : null);

  const loadWhys = useCallback(async () => {
    if (!scopeId) {
      setWhys([]);
      setWhysLoading(false);
      return;
    }
    setWhysLoading(true);
    setWhysError('');
    try {
      setWhys(sortWhys(normalizeRows(await fiveWhys(scopeId))));
    } catch (e) {
      setWhys([]);
      setWhysError(readError(e, 'Could not load Five Whys.'));
    } finally {
      setWhysLoading(false);
    }
  }, [scopeId]);

  const loadFactors = useCallback(async () => {
    if (!scopeId) {
      setFactors([]);
      setFactorsLoading(false);
      return;
    }
    setFactorsLoading(true);
    setFactorsError('');
    try {
      setFactors(sortFactors(normalizeRows(await rootCauseFactors(scopeId))));
    } catch (e) {
      setFactors([]);
      setFactorsError(readError(e, 'Could not load root-cause factors.'));
    } finally {
      setFactorsLoading(false);
    }
  }, [scopeId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect
  useEffect(() => { loadWhys(); }, [loadWhys]); // eslint-disable-line react/set-state-in-effect
  useEffect(() => { loadFactors(); }, [loadFactors]); // eslint-disable-line react/set-state-in-effect
  useEffect(() => { setCreatedId(null); setRejectReason(''); }, [rcaId, problemId]);

  const locked = FINAL_STATUSES.includes(rca?.status);
  const canEditRows = canManage && EDITABLE_STATUSES.includes(rca?.status);
  const canDeleteRows = canManage && rca?.status === 'draft';
  const canAddRows = canEditRows && Boolean(analysisId);
  // The backend collection endpoints list every why/factor for a Problem.
  // The RCA editor only exposes rows that belong to the active analysis.
  const visibleWhys = analysisId == null
    ? []
    : whys.filter((w) => String(w.analysis) === String(analysisId));
  const visibleFactors = analysisId == null
    ? []
    : factors.filter((f) => String(f.analysis) === String(analysisId));
  const selfApproval = Boolean(
    rca?.created_by_username && user?.username && rca.created_by_username === user.username,
  );
  const fieldsDisabled = !canManage || locked || Boolean(busy);

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
        if (label === 'Create' && result.id) setCreatedId(result.id);
        if (label === 'Update') {
          if (result.concluded_at !== undefined) {
            setLoadedConcludedAt(result.concluded_at ?? '');
          }
          setForm((prev) => ({
            title: result.title ?? prev.title,
            description: result.description ?? prev.description,
            analysis_method: result.analysis_method ?? prev.analysis_method,
            findings: result.findings ?? prev.findings,
            concluded_at: result.concluded_at !== undefined
              ? toDateTimeInput(result.concluded_at)
              : prev.concluded_at,
          }));
        }
      }
      if (label === 'Reject') setRejectReason('');
      if (typeof onChanged === 'function') {
        onChanged({
          action: label,
          id: result?.id ?? activeId,
          rca: result,
        });
      }
      setNotice(`${label} succeeded.`);
    } catch (e) {
      setError(readError(e, `${label} failed.`));
    } finally {
      setBusy('');
    }
  };

  const concludedAtPayload = () => {
    if (form.concluded_at === toDateTimeInput(loadedConcludedAt)) {
      return loadedConcludedAt || null;
    }
    return form.concluded_at || null;
  };

  const payload = () => ({
    title: form.title,
    description: form.description,
    analysis_method: form.analysis_method.trim(),
    findings: form.findings,
    concluded_at: concludedAtPayload(),
  });

  const create = () => {
    if (!form.analysis_method.trim()) {
      setError('Analysis method is required.');
      return;
    }
    return run('Create', () => createRCA({
      problem: Number(problemId),
      title: form.title,
      description: form.description,
      analysis_method: form.analysis_method.trim(),
    }));
  };

  const update = () => {
    if (!form.title.trim()) {
      setError('Title is required.');
      return;
    }
    if (!form.analysis_method.trim()) {
      setError('Analysis method is required.');
      return;
    }
    return run('Update', () => editRCA(activeId, payload(), version));
  };

  // Why/factor mutations refresh only their own section from the server list.
  const mutateWhy = async (label, fn) => {
    if (busy) return;
    setBusy(label);
    setWhysError('');
    setNotice('');
    try {
      await fn();
      await loadWhys();
      setNotice(`${label} succeeded.`);
    } catch (e) {
      setWhysError(readError(e, `${label} failed.`));
    } finally {
      setBusy('');
    }
  };

  const mutateFactor = async (label, fn) => {
    if (busy) return;
    setBusy(label);
    setFactorsError('');
    setNotice('');
    try {
      await fn();
      await loadFactors();
      setNotice(`${label} succeeded.`);
    } catch (e) {
      setFactorsError(readError(e, `${label} failed.`));
    } finally {
      setBusy('');
    }
  };

  const addWhy = () => {
    const questionNumber = Number(whyForm.question_number);
    if (
      !analysisId
      || !Number.isInteger(questionNumber)
      || questionNumber < 1
      || !whyForm.question_text.trim()
      || !whyForm.answer.trim()
    ) {
      setWhysError('Enter a question number of at least 1, a question, and an answer.');
      return;
    }
    return mutateWhy('Add Why', async () => {
      await createFiveWhy({
        analysis: analysisId,
        question_number: questionNumber,
        question_text: whyForm.question_text.trim(),
        answer: whyForm.answer.trim(),
      });
      setWhyForm(EMPTY_WHY);
    });
  };

  const startEditWhy = (row) => {
    setWhysError('');
    setEditingWhyId(row.id);
    setWhyEdit({
      question_text: row.question_text ?? '',
      answer: row.answer ?? '',
    });
  };

  const cancelEditWhy = () => {
    setEditingWhyId(null);
    setWhyEdit({ question_text: '', answer: '' });
  };

  const saveWhy = (row) => {
    if (!whyEdit.question_text.trim() || !whyEdit.answer.trim()) {
      setWhysError('Question and answer are required.');
      return;
    }
    return mutateWhy('Update Why', async () => {
      await editFiveWhy(row.id, {
        question_text: whyEdit.question_text.trim(),
        answer: whyEdit.answer.trim(),
      });
      setEditingWhyId(null);
    });
  };

  const removeWhy = (row) => {
    if (!window.confirm(`Delete Five Why #${row.question_number}?`)) return;
    return mutateWhy('Delete Why', async () => {
      await deleteFiveWhy(row.id);
      if (editingWhyId === row.id) setEditingWhyId(null);
    });
  };

  const addFactor = () => {
    if (
      !analysisId
      || !FACTOR_CATEGORY_LABELS[factorForm.category]
      || !factorForm.factor.trim()
    ) {
      setFactorsError('Select a valid category and enter a factor.');
      return;
    }
    return mutateFactor('Add Factor', async () => {
      await createFactor({
        analysis: analysisId,
        category: factorForm.category,
        factor: factorForm.factor.trim(),
      });
      setFactorForm(EMPTY_FACTOR);
    });
  };

  const startEditFactor = (row) => {
    setFactorsError('');
    setEditingFactorId(row.id);
    setFactorEdit({
      category: row.category ?? 'people',
      factor: row.factor ?? '',
    });
  };

  const cancelEditFactor = () => {
    setEditingFactorId(null);
    setFactorEdit({ category: 'people', factor: '' });
  };

  const saveFactor = (row) => {
    if (
      !FACTOR_CATEGORY_LABELS[factorEdit.category]
      || !factorEdit.factor.trim()
    ) {
      setFactorsError('Select a valid category and enter a factor.');
      return;
    }
    return mutateFactor('Update Factor', async () => {
      await editFactor(row.id, {
        category: factorEdit.category,
        factor: factorEdit.factor.trim(),
      });
      setEditingFactorId(null);
    });
  };

  const removeFactor = (row) => {
    if (!window.confirm(`Delete root-cause factor "${row.factor}"?`)) return;
    return mutateFactor('Delete Factor', async () => {
      await deleteFactor(row.id);
      if (editingFactorId === row.id) setEditingFactorId(null);
    });
  };

  const reject = () => {
    if (!rejectReason.trim()) {
      setError('A rejection reason is required.');
      return;
    }
    return run('Reject', () => rejectRCA(activeId, {
      reason: rejectReason.trim(),
      expected_record_version: version,
    }));
  };

  if (loading) return <LoadingRows n={4} />;

  return (
    <div>
      <PageHeader
        title={activeId ? `RCA #${activeId}` : 'Create RCA'}
        sub={rca?.status ? `Status: ${rca.status}` : 'Root-cause analysis'}
      />
      {error && <div className="error-summary" role="alert">{error}</div>}
      {notice && <div className="success-summary" role="status">{notice}</div>}
      <Panel>
        <PanelPad>
          <p><strong>Title: {rca?.title ?? form.title ?? ''}</strong></p>
          {rca?.status && <p><Badge kind="status-warning" value={rca.status} /></p>}

          {activeId && rca && (!canManage || locked) && (
            <div className="muted">
              <p><strong>Saved analysis method:</strong> {rca.analysis_method || '—'}</p>
              <p><strong>Saved findings:</strong> {rca.findings || '—'}</p>
              <p><strong>Saved concluded at:</strong> {rca.concluded_at ? String(rca.concluded_at) : '—'}</p>
            </div>
          )}

          <Field label="Title" required>
            <Input value={form.title} disabled={fieldsDisabled} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Description">
            <Input value={form.description} disabled={fieldsDisabled} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <Field
            label="Analysis method"
            required
            hint="Backend-defined method label, for example five_whys."
          >
            <Input
              value={form.analysis_method}
              maxLength={30}
              disabled={fieldsDisabled}
              onChange={(e) => setForm({ ...form, analysis_method: e.target.value })}
            />
          </Field>
          {activeId && (
            <>
              <Field label="Findings">
                <Textarea
                  rows={4}
                  value={form.findings}
                  disabled={fieldsDisabled}
                  onChange={(e) => setForm({ ...form, findings: e.target.value })}
                />
              </Field>
              <Field label="Concluded at" hint="Stored in UTC. Leave empty for no conclusion time.">
                <Input
                  type="datetime-local"
                  step="1"
                  value={form.concluded_at}
                  disabled={fieldsDisabled}
                  onChange={(e) => setForm({ ...form, concluded_at: e.target.value })}
                />
              </Field>
            </>
          )}
          <Input type="hidden" value={version ?? ''} readOnly />

          {!activeId && canManage && (
            <Button
              disabled={!form.title.trim() || !form.analysis_method.trim() || Boolean(busy)}
              onClick={create}
            >
              Create RCA
            </Button>
          )}

          {activeId && !locked && canManage && (
            <Button
              disabled={!form.title.trim() || !form.analysis_method.trim() || Boolean(busy)}
              onClick={update}
            >
              Update RCA
            </Button>
          )}

          {activeId && !locked && canManage && (
            <Button disabled={Boolean(busy)} onClick={() => run('Submit', () => submitRCA(activeId, { expected_record_version: version }))}>
              Submit RCA
            </Button>
          )}

          {activeId && !locked && canGovern && (
            <div className="row-gap">
              <Button
                kind="danger"
                disabled={Boolean(busy)}
                onClick={() => run('Supersede', () => supersedeRCA(activeId, { expected_record_version: version }))}
              >
                Supersede
              </Button>
              <Button
                disabled={selfApproval || Boolean(busy)}
                title={selfApproval ? 'You cannot approve your own RCA.' : undefined}
                onClick={() => run('Approve', () => approveRCA(activeId, { expected_record_version: version }))}
              >
                Approve RCA
              </Button>
              <Field label="Rejection reason" required>
                <Input value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} />
              </Field>
              <Button kind="danger" disabled={Boolean(busy)} onClick={reject}>
                Reject RCA
              </Button>
            </div>
          )}

          {activeId && locked && (
            <p className="muted">This analysis is {rca?.status} and can no longer be edited.</p>
          )}

          {activeId && canGovern && selfApproval && (
            <p className="muted">You cannot approve your own RCA.</p>
          )}
        </PanelPad>
      </Panel>

      <Panel>
        <PanelPad>
          <h3>Five Whys</h3>
          {whysError && <div className="error-summary" role="alert">{whysError}</div>}
          {whysLoading ? (
            <p className="muted" role="status">Loading Five Whys…</p>
          ) : visibleWhys.length === 0 ? (
            <p className="muted">No Five Whys recorded.</p>
          ) : visibleWhys.map((w) => (
            <div key={w.id}>
              {editingWhyId === w.id ? (
                <form onSubmit={(ev) => { ev.preventDefault(); saveWhy(w); }}>
                  <Field label={`Edit why question #${w.question_number}`} required>
                    <Input
                      value={whyEdit.question_text}
                      disabled={Boolean(busy)}
                      onChange={(e) => setWhyEdit({ ...whyEdit, question_text: e.target.value })}
                    />
                  </Field>
                  <Field label="Edit why answer" required>
                    <Input
                      value={whyEdit.answer}
                      disabled={Boolean(busy)}
                      onChange={(e) => setWhyEdit({ ...whyEdit, answer: e.target.value })}
                    />
                  </Field>
                  <div className="row-gap">
                    <Button
                      type="submit"
                      disabled={Boolean(busy) || !whyEdit.question_text.trim() || !whyEdit.answer.trim()}
                    >
                      Save Why
                    </Button>
                    <Button type="button" kind="ghost" disabled={Boolean(busy)} onClick={cancelEditWhy}>
                      Cancel
                    </Button>
                  </div>
                </form>
              ) : (
                <>
                  <p>{w.question_number}. {w.question_text}{w.answer ? ` — ${w.answer}` : ''}</p>
                  {canEditRows && (
                    <div className="row-gap">
                      <Button
                        kind="ghost"
                        size="small"
                        aria-label={`Edit why ${w.id}`}
                        disabled={Boolean(busy)}
                        onClick={() => startEditWhy(w)}
                      >
                        Edit
                      </Button>
                      {canDeleteRows && (
                        <Button
                          kind="ghost"
                          size="small"
                          aria-label={`Delete why ${w.id}`}
                          disabled={Boolean(busy)}
                          onClick={() => removeWhy(w)}
                        >
                          Delete
                        </Button>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
          {canAddRows && (
            <form onSubmit={(ev) => { ev.preventDefault(); addWhy(); }}>
              <Field label="Why question" required>
                <Input value={whyForm.question_text} onChange={(e) => setWhyForm({ ...whyForm, question_text: e.target.value })} />
              </Field>
              <Field label="Question number" required>
                <Input type="number" min="1" step="1" value={whyForm.question_number} onChange={(e) => setWhyForm({ ...whyForm, question_number: Number(e.target.value) })} />
              </Field>
              <Field label="Answer" required>
                <Input value={whyForm.answer} onChange={(e) => setWhyForm({ ...whyForm, answer: e.target.value })} />
              </Field>
              <Button
                type="submit"
                disabled={
                  Boolean(busy)
                  || !whyForm.question_text.trim()
                  || !whyForm.answer.trim()
                  || !Number.isInteger(Number(whyForm.question_number))
                  || Number(whyForm.question_number) < 1
                }
              >
                Add Why
              </Button>
            </form>
          )}

          <h3>Root-Cause Factors</h3>
          {factorsError && <div className="error-summary" role="alert">{factorsError}</div>}
          {factorsLoading ? (
            <p className="muted" role="status">Loading root-cause factors…</p>
          ) : visibleFactors.length === 0 ? (
            <p className="muted">No root-cause factors recorded.</p>
          ) : visibleFactors.map((f) => (
            <div key={f.id}>
              {editingFactorId === f.id ? (
                <form onSubmit={(ev) => { ev.preventDefault(); saveFactor(f); }}>
                  <Field label="Edit factor category">
                    <Select
                      value={factorEdit.category}
                      disabled={Boolean(busy)}
                      onChange={(e) => setFactorEdit({ ...factorEdit, category: e.target.value })}
                    >
                      {FACTOR_CATEGORIES.map(([value, label]) => (
                        <Option key={value} value={value}>{label}</Option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Edit factor" required>
                    <Input
                      value={factorEdit.factor}
                      disabled={Boolean(busy)}
                      onChange={(e) => setFactorEdit({ ...factorEdit, factor: e.target.value })}
                    />
                  </Field>
                  <div className="row-gap">
                    <Button
                      type="submit"
                      disabled={Boolean(busy) || !factorEdit.factor.trim()}
                    >
                      Save Factor
                    </Button>
                    <Button type="button" kind="ghost" disabled={Boolean(busy)} onClick={cancelEditFactor}>
                      Cancel
                    </Button>
                  </div>
                </form>
              ) : (
                <>
                  <p>
                    {FACTOR_CATEGORY_LABELS[f.category] ?? f.category}: {f.factor}
                    {f.contribution ? ` — ${f.contribution}` : ''}
                  </p>
                  {canEditRows && (
                    <div className="row-gap">
                      <Button
                        kind="ghost"
                        size="small"
                        aria-label={`Edit factor ${f.id}`}
                        disabled={Boolean(busy)}
                        onClick={() => startEditFactor(f)}
                      >
                        Edit
                      </Button>
                      {canDeleteRows && (
                        <Button
                          kind="ghost"
                          size="small"
                          aria-label={`Delete factor ${f.id}`}
                          disabled={Boolean(busy)}
                          onClick={() => removeFactor(f)}
                        >
                          Delete
                        </Button>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
          {canAddRows && (
            <form onSubmit={(ev) => { ev.preventDefault(); addFactor(); }}>
              <Field label="Factor category">
                <Select value={factorForm.category} onChange={(e) => setFactorForm({ ...factorForm, category: e.target.value })}>
                  {FACTOR_CATEGORIES.map(([value, label]) => (
                    <Option key={value} value={value}>{label}</Option>
                  ))}
                </Select>
              </Field>
              <Field label="Factor" required>
                <Input value={factorForm.factor} onChange={(e) => setFactorForm({ ...factorForm, factor: e.target.value })} />
              </Field>
              <Button type="submit" disabled={Boolean(busy) || !factorForm.factor.trim()}>
                Add Factor
              </Button>
            </form>
          )}
        </PanelPad>
      </Panel>
    </div>
  );
}
