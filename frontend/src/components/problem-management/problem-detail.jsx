import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Badge, LoadingRows, PageHeader, Panel, PanelPad } from '../../components';
import {
  fiveWhys, getRCA, linkedAssets, linkedCIs, linkedProducts,
  linkedServices, linkedTickets, listEvidence, listExceptions, listTasks,
  listValidations, listWorkarounds, problemDetail, problemHistory, problemReadiness,
  rootCauseFactors,
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
  const [problem, setProblem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sections, setSections] = useState({});
  const [rca, setRca] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    problemDetail(problemId)
      .then((data) => { if (active) setProblem(data?.data ?? data); })
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
      ['evidence', () => listEvidence(problemId)],
      ['validations', () => listValidations(problemId)],
      ['exceptions', () => listExceptions(problemId)],
      ['workarounds', () => listWorkarounds(problemId)],
      ['whys', () => fiveWhys(problemId)],
      ['factors', () => rootCauseFactors(problemId)],
      ['history', () => problemHistory(problemId)],
      ['readiness', () => problemReadiness(problemId)],
      ['tickets', () => linkedTickets(problemId)],
      ['cis', () => linkedCIs(problemId)],
      ['assets', () => linkedAssets(problemId)],
      ['services', () => linkedServices(problemId)],
      ['products', () => linkedProducts(problemId)],
    ];
    loaders.forEach(([key, fn]) => {
      Promise.resolve()
        .then(fn)
        .then((data) => { if (active) setSections((s) => ({ ...s, [key]: { ok: true, data } })); })
        .catch(() => { if (active) setSections((s) => ({ ...s, [key]: { ok: false, data: null } })); });
    });
    return () => { active = false; };
  }, [problemId]);

  useEffect(() => {
    const rootCauseId = problem?.root_cause_analysis;
    if (!rootCauseId) { setRca(null); return () => {}; }
    let active = true;
    getRCA(rootCauseId)
      .then((data) => { if (active) setRca(data?.data ?? data); })
      .catch(() => { if (active) setRca(null); });
    return () => { active = false; };
  }, [problem?.root_cause_analysis]);

  if (loading) return <LoadingRows n={6} />;
  if (error) return <div className="error-summary" role="alert">{error}</div>;
  if (!problem) return <div className="error-summary" role="alert">Problem not available.</div>;

  const readiness = sections.readiness?.data;
  const counts = readiness?.counts ?? {};

  return (
    <div>
      <PageHeader title={problem.problem_number} sub={problem.title} />

      <Section title="Overview">
        {PROBLEM_ROWS.map(([key, label]) => (
          <p key={key}>{label}: {key === 'status' || key === 'priority'
            ? <Badge kind="status-warning" value={problem[key]} />
            : (problem[key] || '—')}</p>
        ))}
        {problem.description && <p>{problem.description}</p>}
      </Section>

      <Section title="Tasks" state={sections.tasks}>
        {listOf(sections.tasks?.data).length === 0
          ? <p className="muted">No tasks.</p>
          : listOf(sections.tasks?.data).map((t) => <p key={t.id}>{t.title} — {t.status}</p>)}
      </Section>

      <Section title="Evidence" state={sections.evidence}>
        {listOf(sections.evidence?.data).length === 0
          ? <p className="muted">No evidence.</p>
          : listOf(sections.evidence?.data).map((e) => (
            <p key={e.id}>{e.original_filename}{e.archived ? ' (Archived)' : ''}</p>
          ))}
      </Section>

      <Section title="RCA Workflow">
        {rca
          ? <p>{rca.title} — {rca.status}</p>
          : <p className="muted">No root-cause analysis linked.</p>}
      </Section>

      <Section title="Five Whys" state={sections.whys}>
        {listOf(sections.whys?.data).length === 0
          ? <p className="muted">No Five Whys recorded.</p>
          : listOf(sections.whys?.data).map((w) => <p key={w.id}>{w.question_number}. {w.question_text}</p>)}
      </Section>

      <Section title="Root-Cause Factors" state={sections.factors}>
        {listOf(sections.factors?.data).length === 0
          ? <p className="muted">No factors recorded.</p>
          : listOf(sections.factors?.data).map((f) => <p key={f.id}>{f.category}: {f.factor}</p>)}
      </Section>

      <Section title="Timeline">
        {(problem.timeline_events ?? []).length === 0
          ? <p className="muted">No timeline events.</p>
          : problem.timeline_events.map((e) => <p key={e.id}>{e.title}</p>)}
      </Section>

      <Section title="Actions">
        <p className="muted">Corrective and preventive actions are tracked as tasks above.</p>
      </Section>

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
          : listOf(sections.exceptions?.data).map((e) => <p key={e.id}>{e.title} — {e.exception_type}</p>)}
      </Section>

      <Section title="Readiness State" state={sections.readiness}>
        <p>Ready for resolution: {readiness?.ready_for_resolution ? 'Yes' : 'No'}</p>
        <p>Ready for closure: {readiness?.ready_for_closure ? 'Yes' : 'No'}</p>
        <p>Blockers: {(readiness?.blockers ?? []).join(', ') || 'None'}</p>
        <p>Warnings: {(readiness?.warnings ?? []).join(', ') || 'None'}</p>
        <p>Open blocking tasks: {counts.open_blocking_tasks ?? 0}</p>
        <p>Open required actions: {counts.open_required_actions ?? 0}</p>
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
        <p className="muted">Linked Changes are not supported by the backend.</p>
      </Section>

      <Section title="Permissions">
        <p>Problem management actions follow your role permissions.</p>
      </Section>
    </div>
  );
}
