import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Badge, Button, Field, Input, LoadingRows, PageHeader, Panel, PanelPad, Select, Textarea } from '../../components';
import { Evidence } from '../../components/problem-management/evidence';
import { RCA } from '../../components/problem-management/rca';
import { Actions } from '../../components/problem-management/actions';
import { GovernedTransitions } from '../../components/problem-management/governed-transitions';
import { useAuth } from '../../auth';
import {
  linkedAssets, linkedCIs, linkedKBs, linkedProducts,
  linkedServices, linkedTickets, listExceptions, listTasks,
  listValidations, listWorkarounds, problemDetail, problemHistory, problemReadiness, createKbLink, deleteKbLink,
  updateProblem,
} from '../../services/problem-management';

function Section({ title, state, children }) {
  return (
    <Panel>
      <PanelPad>
        <h3>{title}</h3>
        {state?.ok === false ? <p className="muted">Section unavailable.</p> : children}
      </PanelPad>
    </Panel>
  );
}

function listOf(value) {
  if (Array.isArray(value)) return value;
  return value?.results ?? [];
}

const PROBLEM_ROWS = [
  ['status', 'Status'],
  ['priority', 'Priority'],
  ['problem_type', 'Type'],
  ['owner_username', 'Owner'],
  ['service_name', 'Service'],
  ['category_name', 'Category'],
  ['environment', 'Environment'],
];

export function ProblemDetail({ problemId: problemIdProp }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const { user, isStaff, isManagerOrAdmin, isSupportOrAbove } = useAuth();
  const [problem, setProblem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sections, setSections] = useState({});
  const [kbForm, setKbForm] = useState({
    article: '', relation_type: 'reference', relevance: 'medium', note: '',
  });
  const [kbAdding, setKbAdding] = useState(false);
  const [kbRemoving, setKbRemoving] = useState(new Set());
  const [kbMessage, setKbMessage] = useState('');
  const [editingProblemFields, setEditingProblemFields] = useState(false);
  const [savingProblemFields, setSavingProblemFields] = useState(false);
  const problemSaveLock = useRef(false);
  const [problemFieldsError, setProblemFieldsError] = useState('');
  const [problemFields, setProblemFields] = useState({
    title: problem?.title ?? '',
    description: problem?.description ?? '',
    priority: problem?.priority ?? '',
    severity: problem?.severity ?? '',
    impact: problem?.impact ?? '',
    urgency: problem?.urgency ?? '',
    criticality: problem?.criticality ?? '',
    owner: problem?.owner_username ?? '',
    problem_manager: problem?.problem_manager_username ?? '',
    assigned_group: problem?.assigned_group ?? '',
    department: problem?.department_name ?? '',
    service: problem?.service_name ?? '',
    category: problem?.category_name ?? '',
    subcategory: problem?.subcategory ?? '',
    environment: problem?.environment ?? '',
    detection_method: problem?.detection_method ?? '',
    target_resolution_date: problem?.target_resolution_date ? problem.target_resolution_date.slice(0, 10) : '',
    next_review_at: problem?.next_review_at ? problem.next_review_at.slice(0, 10) : '',
  });

  useEffect(() => {
    let active = true;
    setLoading(true);
    problemDetail(problemId)
      .then((data) => {
        if (active) {
          const p = data?.data ?? data;
          setProblem(p);
          // Initialize form with current problem values
          setProblemFields({
            title: p.title ?? '',
            description: p.description ?? '',
            priority: p.priority ?? '',
            severity: p.severity ?? '',
            impact: p.impact ?? '',
            urgency: p.urgency ?? '',
            criticality: p.criticality ?? '',
            owner: p.owner?.toString() ?? '',
            problem_manager: p.problem_manager?.toString() ?? '',
            assigned_group: p.assigned_group ?? '',
            department: p.department ?? '',
            service: p.service?.toString() ?? '',
            category: p.category?.toString() ?? '',
            subcategory: p.subcategory ?? '',
            environment: p.environment ?? '',
            detection_method: p.detection_method ?? '',
            target_resolution_date: p.target_resolution_date ? p.target_resolution_date.slice(0, 10) : '',
            next_review_at: p.next_review_at ? p.next_review_at.slice(0, 10) : '',
          });
        }
      })
      .catch(() => { if (active) setError('Could not load problem detail.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [problemId]);

  // Each section loads independently: one failing endpoint degrades that
  // section only and never blanks the page.
  useEffect(() => {
    if (!problemId) return () => {};
    let active = true;
    const loaders = [
      ['tasks', () => listTasks(problemId)],
      ['validations', () => listValidations(problemId)],
      ['exceptions', () => listExceptions(problemId)],
      ['workarounds', () => listWorkarounds(problemId)],
      ['history', () => problemHistory(problemId)],
      ['readiness', () => problemReadiness(problemId)],
      ['tickets', () => linkedTickets(problemId)],
      ['cis', () => linkedCIs(problemId)],
      ['assets', () => linkedAssets(problemId)],
      ['services', () => linkedServices(problemId)],
      ['products', () => linkedProducts(problemId)],
      ['kbs', () => linkedKBs(problemId)],
    ];
    loaders.forEach(([key, fn]) => {
      Promise.resolve()
        .then(fn)
        .then((data) => { if (active) setSections((s) => ({ ...s, [key]: { ok: true, data } })); })
        .catch(() => { if (active) setSections((s) => ({ ...s, [key]: { ok: false, data: null } })); });
    });
    return () => { active = false; };
  }, [problemId]);

  const handleProblemFieldsChange = useCallback((e) => {
    const { name, value } = e.target;
    setProblemFields((prev) => ({ ...prev, [name]: value }));
  }, []);

  const handleEditProblemFields = useCallback(() => {
    if (!isStaff) return;

    setProblemFields({
      title: problem?.title ?? '',
      description: problem?.description ?? '',
      priority: problem?.priority ?? '',
      severity: problem?.severity ?? '',
      impact: problem?.impact ?? '',
      urgency: problem?.urgency ?? '',
      criticality: problem?.criticality ?? '',
      owner: problem?.owner?.toString() ?? '',
      problem_manager: problem?.problem_manager?.toString() ?? '',
      assigned_group: problem?.assigned_group?.toString() ?? '',
      department: problem?.department?.toString() ?? '',
      service: problem?.service?.toString() ?? '',
      category: problem?.category?.toString() ?? '',
      subcategory: problem?.subcategory ?? '',
      environment: problem?.environment ?? '',
      detection_method: problem?.detection_method ?? '',
      target_resolution_date: problem?.target_resolution_date
        ? problem.target_resolution_date.slice(0, 10) : '',
      next_review_at: problem?.next_review_at
        ? problem.next_review_at.slice(0, 10) : '',
    });
    setProblemFieldsError('');
    setEditingProblemFields(true);
  }, [isStaff, problem]);

  const handleCancelProblemFields = useCallback(() => {
    setProblemFields({
      title: problem?.title ?? '',
      description: problem?.description ?? '',
      priority: problem?.priority ?? '',
      severity: problem?.severity ?? '',
      impact: problem?.impact ?? '',
      urgency: problem?.urgency ?? '',
      criticality: problem?.criticality ?? '',
      owner: problem?.owner?.toString() ?? '',
      problem_manager: problem?.problem_manager?.toString() ?? '',
      assigned_group: problem?.assigned_group?.toString() ?? '',
      department: problem?.department?.toString() ?? '',
      service: problem?.service?.toString() ?? '',
      category: problem?.category?.toString() ?? '',
      subcategory: problem?.subcategory ?? '',
      environment: problem?.environment ?? '',
      detection_method: problem?.detection_method ?? '',
      target_resolution_date: problem?.target_resolution_date
        ? problem.target_resolution_date.slice(0, 10) : '',
      next_review_at: problem?.next_review_at
        ? problem.next_review_at.slice(0, 10) : '',
    });
    setProblemFieldsError('');
    setEditingProblemFields(false);
  }, [problem]);

  const handleSaveProblemFields = useCallback(async () => {
    if (!isStaff || problemSaveLock.current) return;

    problemSaveLock.current = true;
    setSavingProblemFields(true);
    setProblemFieldsError('');

    try {
      const updatePayload = {
        title: problemFields.title,
        description: problemFields.description,
        priority: problemFields.priority,
        severity: problemFields.severity,
        impact: problemFields.impact,
        urgency: problemFields.urgency,
        criticality: problemFields.criticality,
        subcategory: problemFields.subcategory,
        environment: problemFields.environment,
        detection_method: problemFields.detection_method,
        ...(isManagerOrAdmin ? {
          target_resolution_date: problemFields.target_resolution_date || null,
          next_review_at: problemFields.next_review_at || null,
        } : {}),
      };

      await updateProblem(problemId, updatePayload, problem?.record_version);
      setProblem((current) => ({ ...current, ...updatePayload }));
      setEditingProblemFields(false);

      try {
        const data = await problemDetail(problemId);
        setProblem(data?.data ?? data);
      } catch {
        // The update succeeded; retain the locally updated record.
      }
    } catch (e) {
      const status = e.response?.status;

      if (status === 409) {
        try {
          const data = await problemDetail(problemId);
          setProblem(data?.data ?? data);
        } catch {
          // Keep the user's entered values if refresh fails.
        }
        setProblemFieldsError(
          'The problem record changed while you were editing. Review the latest record and try again.'
        );
      } else if (status === 400) {
        setProblemFieldsError(
          'Could not save problem fields. Please check the submitted values.'
        );
      } else if (status === 403) {
        setProblemFieldsError('You do not have permission to edit problem fields.');
      } else {
        setProblemFieldsError('Failed to save problem fields. Please try again.');
      }
    } finally {
      problemSaveLock.current = false;
      setSavingProblemFields(false);
    }
  }, [isStaff, isManagerOrAdmin, problemId, problemFields, problem?.record_version]);

  if (loading) return <LoadingRows n={6} />;
  if (error) return <div className="error-summary" role="alert">{error}</div>;
  if (!problem) return <div className="error-summary" role="alert">Problem not available.</div>;

  const readiness = sections.readiness?.data;
  const counts = readiness?.counts ?? {};

  return (
    <div>
      <PageHeader title={problem.problem_number} sub={problem.title} />

      <Section title="Overview">
        {editingProblemFields ? (
          <>
            <h3>Edit Problem Fields</h3>

            {problemFieldsError && (
              <div className="error-summary" role="alert">
                {problemFieldsError}
              </div>
            )}

            <form
              className="form"
              aria-label="Edit problem fields"
              onSubmit={(e) => {
                e.preventDefault();
                handleSaveProblemFields();
              }}
            >
              <Field label="Title" required>
                <Input
                  name="title"
                  value={problemFields.title}
                  onChange={handleProblemFieldsChange}
                  required
                  disabled={savingProblemFields}
                />
              </Field>

              <Field label="Description">
                <Textarea
                  name="description"
                  value={problemFields.description}
                  onChange={handleProblemFieldsChange}
                  rows={3}
                  disabled={savingProblemFields}
                />
              </Field>

              <Field label="Priority">
                <Select
                  name="priority"
                  value={problemFields.priority}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                >
                  <option value="">—</option>
                  <option value="p1">P1 — Critical</option>
                  <option value="p2">P2 — High</option>
                  <option value="p3">P3 — Medium</option>
                  <option value="p4">P4 — Low</option>
                </Select>
              </Field>

              <Field label="Severity">
                <Select
                  name="severity"
                  value={problemFields.severity}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                >
                  <option value="">—</option>
                  <option value="minor">Minor</option>
                  <option value="major">Major</option>
                  <option value="critical">Critical</option>
                </Select>
              </Field>

              <Field label="Impact">
                <Textarea
                  name="impact"
                  value={problemFields.impact}
                  onChange={handleProblemFieldsChange}
                  rows={3}
                  disabled={savingProblemFields}
                />
              </Field>

              <Field label="Urgency">
                <Select
                  name="urgency"
                  value={problemFields.urgency}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                >
                  <option value="">—</option>
                  <option value="urgent">Urgent</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </Select>
              </Field>

              <Field label="Criticality">
                <Select
                  name="criticality"
                  value={problemFields.criticality}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                >
                  <option value="">—</option>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </Select>
              </Field>

              <Field label="Subcategory">
                <Input
                  name="subcategory"
                  value={problemFields.subcategory}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                />
              </Field>

              <Field label="Environment">
                <Input
                  name="environment"
                  value={problemFields.environment}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                />
              </Field>

              <Field label="Detection Method">
                <Input
                  name="detection_method"
                  value={problemFields.detection_method}
                  onChange={handleProblemFieldsChange}
                  disabled={savingProblemFields}
                />
              </Field>

              {isManagerOrAdmin && (
                <>
                  <Field label="Target Resolution Date">
                    <Input
                      type="date"
                      name="target_resolution_date"
                      value={problemFields.target_resolution_date}
                      onChange={handleProblemFieldsChange}
                      disabled={savingProblemFields}
                    />
                  </Field>

                  <Field label="Next Review Date">
                    <Input
                      type="date"
                      name="next_review_at"
                      value={problemFields.next_review_at}
                      onChange={handleProblemFieldsChange}
                      disabled={savingProblemFields}
                    />
                  </Field>
                </>
              )}

              <div className="row-gap">
                <Button type="submit" disabled={savingProblemFields}>
                  {savingProblemFields ? 'Saving...' : 'Save changes'}
                </Button>

                <Button
                  type="button"
                  onClick={handleCancelProblemFields}
                  disabled={savingProblemFields}
                >
                  Cancel
                </Button>
              </div>
            </form>
          </>
        ) : (
          <>
            {PROBLEM_ROWS.map(([key, label]) => (
              <p key={key}>
                {label}: {key === 'status' || key === 'priority'
                  ? <Badge kind="status-warning" value={problem[key]} />
                  : (problem[key] || '—')}
              </p>
            ))}
            {problem.description && <p>{problem.description}</p>}
          </>
        )}

        {isStaff && !editingProblemFields && (
          <div style={{ marginTop: '0.5rem' }}>
            <Button onClick={handleEditProblemFields}>
              Edit problem fields
            </Button>
          </div>
        )}
      </Section>
      <GovernedTransitions problemId={problemId} problem={problem} />

      <Section title="Tasks" state={sections.tasks}>
        {listOf(sections.tasks?.data).length === 0
          ? <p className="muted">No tasks.</p>
          : listOf(sections.tasks?.data).map((t) => <p key={t.id}>{t.title} — {t.status}</p>)}
      </Section>

      <Evidence problemId={problemId} />

      <section>
        <h3>RCA Workflow</h3>
        <RCA
          rcaId={problem.root_cause_analysis ?? undefined}
          problemId={problemId}
          problemTitle={problem.title}
        />
      </section>

      <Section title="Timeline">
        {(problem.timeline_events ?? []).length === 0
          ? <p className="muted">No timeline events.</p>
          : problem.timeline_events.map((e) => <p key={e.id}>{e.title}</p>)}
      </Section>

      <Actions problemId={problemId} />

      <Section title="Workarounds" state={sections.workarounds}>
        {listOf(sections.workarounds?.data).length === 0
          ? <p className="muted">No workarounds.</p>
          : listOf(sections.workarounds?.data).map((w) => <p key={w.id}>{w.title}</p>)}
      </Section>

      <Section title="Validations" state={sections.validations}>
        {listOf(sections.validations?.data).length === 0
          ? <p className="muted">No validations.</p>
          : listOf(sections.validations?.data).map((v) => (
              <p key={v.id}>{v.title} — {v.status}</p>
            ))}
      </Section>

      <Section title="Exceptions" state={sections.exceptions}>
        {listOf(sections.exceptions?.data).length === 0
          ? <p className="muted">No exceptions.</p>
          : listOf(sections.exceptions?.data).map((e) => (
              <p key={e.id}>{e.title} — {e.exception_type}</p>
            ))}
      </Section>

      <Section title="Readiness State" state={sections.readiness}>
        <p>Ready for resolution: {readiness?.ready_for_resolution ? 'Yes' : 'No'}</p>
        <p>Ready for closure: {readiness?.ready_for_closure ? 'Yes' : 'No'}</p>
        <p>Blockers: {(readiness?.blockers ?? []).join(', ') || 'None'}</p>
        {readiness?.warnings?.length && <p>Warnings: {readiness.warnings.join(', ') || 'None'}</p>}
        <p>Open required actions: {counts.open_required_actions ?? 0}</p>
        <p>Open blocking tasks: {counts.open_blocking_tasks ?? 0}</p>
        <p>Failed validations: {counts.failed_validations ?? 0}</p>
        <p>Open critical tickets: {counts.open_critical_tickets ?? 0}</p>
        <p>Active exceptions: {counts.active_exceptions ?? 0}</p>
      </Section>

      <Section title="Problem History" state={sections.history}>
        {listOf(sections.history?.data).length === 0
          ? <p className="muted">No history events.</p>
          : listOf(sections.history?.data).map((h) => (
              <p key={h.id}>{h.event_type}: {h.previous_status || '—'} → {h.new_status || '—'}</p>
            ))}
      </Section>

      <Section title="Linked Records">
        <p>Tickets: {listOf(sections.tickets?.data).length}</p>
        <p>Configuration items: {listOf(sections.cis?.data).length}</p>
        <p>Assets: {listOf(sections.assets?.data).length}</p>
        <p>Services: {listOf(sections.services?.data).length}</p>
        <p>Software products: {listOf(sections.products?.data).length}</p>
        <p>KB articles: {listOf(sections.kbs?.data).length}</p>
        <p className="muted">Linked Changes are not supported by the backend.</p>
      </Section>

      <Section title="Permissions">
        <p>Problem management actions follow your role permissions.</p>
      </Section>
    </div>
  );
}