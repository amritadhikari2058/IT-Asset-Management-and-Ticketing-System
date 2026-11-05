/* 
 * Change Detail - displays detailed information about a change
 * Route: #/changes/:id
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Badge } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError, formatDate, formatDateTime, statusBadgeVariant, riskBadgeVariant, priorityBadgeVariant } from './changes-utils';

export function ChangeDetail({ match }) {
  const { isStaff, role } = useAuth();
  const [change, setChange] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');

  const tabLabels = {
    overview: 'Overview',
    impact: 'Impact',
    plans: 'Plans',
    assets: 'Assets',
    services: 'Services',
    tasks: 'Tasks',
    risk: 'Risk',
    approvals: 'Approvals',
    schedule: 'Schedule',
    conflicts: 'Conflicts',
    attachments: 'Attachments',
    communications: 'Communications',
    stakeholders: 'Stakeholders',
    implementation: 'Implementation',
    pir: 'PIR',
    related_tickets: 'Related Tickets',
    kb: 'Knowledge Base',
    history: 'History',
  };

  useEffect(() => {
    const id = match.params.id;
    if (!id) return;
    fetchPage(`/changes/${id}/`)
      .then((data) => {
        setChange(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [match.params.id]);

  const { change_number, title, change_type, status, risk_level, priority,
          change_owner, implementation_lead, planned_start, planned_end,
          version, conflicts_count, description, business_reason,
          customer_impact, business_impact, technical_impact } = change;

  const renderOverview = () =>
  <div>
    <p><strong>Change Number:</strong> {change_number}</p>
    <p><strong>Title:</strong> {title}</p>
    <p><strong>Type:</strong> {CHANGE_TYPE_LABELS[change_type] || change_type}</p>
    <p><strong>Status:</strong> <Badge kind={statusBadgeVariant(status)}>{STATUS_LABELS[status] || status}</Badge></p>
    <p><strong>Risk:</strong> <Badge kind={riskBadgeVariant(risk_level)}>{RISK_LEVEL_LABELS[risk_level] || risk_level}</Badge></p>
    <p><strong>Priority:</strong> <Badge kind={priorityBadgeVariant(priority)}>{PRIORITY_LABELS[priority] || priority}</Badge></p>
    <p><strong>Owner:</strong> {change_owner ? `${change_owner.employee_id} — ${change_owner.email}` : 'Unassigned'}</p>
    <p><strong>Implementation Lead:</strong> {implementation_lead ? `${implementation_lead.employee_id} — ${implementation_lead.email}` : 'Unassigned'}</p>
    <p><strong>Planned Start:</strong> {formatDate(planned_start)}</p>
    <p><strong>Planned End:</strong> {formatDate(planned_end)}</p>
    <p><strong>Version:</strong> {version}</p>
    <p><strong>Conflict Count:</strong> {conflicts_count || 0}</p>
  </div>;

  const renderImpact = () =>
  <div>
    <p><strong>Description:</strong> {description || ''}</p>
    <p><strong>Business Reason:</strong> {business_reason || ''}</p>
    <p><strong>Customer Impact:</strong> {customer_impact || ''}</p>
    <p><strong>Business Impact:</strong> {business_impact || ''}</p>
    <p><strong>Technical Impact:</strong> {technical_impact || ''}</p>
    <hr />
    <p><strong>Scope:</strong> {change.scope || ''}</p>
    <p><strong>Out of Scope:</strong> {change.out_of_scope || ''}</p>
  </div>;

  const { implementation_plan, validation_plan, rollback_plan,
          communication_plan, success_criteria } = change;

  const renderPlans = () =>
  <div>
    <p><strong>Implementation Plan:</strong> {implementation_plan || ''}</p>
    <p><strong>Validation Plan:</strong> {validation_plan || ''}</p>
    <p><strong>Rollback Plan:</strong> {rollback_plan || ''}</p>
    <p><strong>Communication Plan:</strong> {communication_plan || ''}</p>
    <p><strong>Success Criteria:</strong> {success_criteria || ''}</p>
  </div>;

  const { asset_impacts } = change;

  const renderAssets = () =>
  <div>
    {asset_impacts ? (
      <div>
        {asset_impacts.map((a, i) => (
          <div key={a.id || i} className="mt-1">
            <strong>{a.asset ? a.asset.name : 'Asset'}:</strong> {a.asset?.asset_id || a.name || 'N/A'}
            {a.service ? ` — Service: ${a.service.name}` : ''}
          </div>
        ))}
      </div>
    ) : (
      <p>No assets affected</p>
    )}
  </div>;

  const { service_impacts } = change;

  const renderServices = () =>
  <div>
    {service_impacts ? (
      <div>
        {service_impacts.map((s, i) => (
          <div key={s.id || i} className="mt-1">
            <strong>{s.service ? s.service.name : 'Service'}:</strong> {s.service?.name || s.name || 'N/A'}
          </div>
        ))}
      </div>
    ) : (
      <p>No services affected</p>
    )}
  </div>;

  const { tasks } = change;

  const renderTasks = () =>
  <div>
    {tasks ? (
      <div>
        {tasks.map((t, i) => (
          <div key={t.id || i} className="mt-1">
            <strong>{t.title}</strong> — Status: {t.status || 'pending'}
            {t.assigned_to ? ` — Assigned: ${t.assigned_to.employee_id}` : ''}
          </div>
        ))}
      </div>
    ) : (
      <p>No tasks</p>
    )}
  </div>;

  const { risk_assessment } = change;

  const renderRisk = () =>
  <div>
    {risk_assessment ? (
      <div>
        <p><strong>Calculated Risk:</strong> {risk_assessment.calculated_risk || '—'}</p>
        <p><strong>Assessment Version:</strong> {risk_assessment.version || '—'}</p>
        <p><strong>Assessor:</strong> {risk_assessment.assessor || '—'}</p>
        <p><strong>Date:</strong> {risk_assessment.date || '—'}</p>
        <p><strong>Override:</strong> {risk_assessment.override ? 'Yes' : 'No'}</p>
        {risk_assessment.override_reason && <p><strong>Override Reason:</strong> {risk_assessment.override_reason}</p>}
      </div>
    ) : (
      <p>No risk assessment</p>
    )}
  </div>;

  const { approvals } = change;

  const renderApprovals = () =>
  <div>
    {approvals ? (
      <div>
        {approvals.map((a, i) => (
          <div key={a.id || i} className="mt-1">
            <strong>Level {a.approval_level}:</strong> {a.status} by {a.decided_by || '—'} on {a.decided_date || '—'}
            {a.decision_reason && <p><em>{a.decision_reason}</em></p>}
          </div>
        ))}
      </div>
    ) : (
      <p>No approvals</p>
    )}
  </div>;

  const { scheduled_at, planned_start, planned_end, expected_downtime_minutes } = change;

  const renderSchedule = () =>
  <div>
    <p><strong>Planned Start:</strong> {formatDateTime(planned_start)}</p>
    <p><strong>Planned End:</strong> {formatDateTime(planned_end)}</p>
    <p><strong>Expected Downtime:</strong> {expected_downtime_minutes ? `${expected_downtime_minutes} minutes` : '—'}</p>
    <p><strong>Scheduled:</strong> {scheduled_at ? formatDate(scheduled_at) : '—'}</p>
  </div>;

  const { conflicts } = change;

  const renderConflicts = () =>
  <div>
    {conflicts ? (
      <div>
        {conflicts.map((c, i) => (
          <div key={c.id || i} className="mt-1">
            <strong>{c.conflicting_change_number}</strong> — {c.severity}
            {c.status && <p>{c.status}</p>}
          </div>
        ))}
      </div>
    ) : (
      <p>No conflicts</p>
    )}
  </div>;

  const { attachments } = change;

  const renderAttachments = () =>
  <div>
    {attachments ? (
      <div>
        {attachments.map((a, i) => (
          <div key={a.id || i} className="mt-1">
            <strong>{a.document_type}</strong>: {a.filename}
            {a.uploader && <p>Uploader: {a.uploader.email}</p>}
          </div>
        ))}
      </div>
    ) : (
      <p>No attachments</p>
    )}
  </div>;

  const { communications } = change;

  const renderCommunications = () =>
  <div>
    {communications ? (
      <div>
        {communications.map((c, i) => (
          <div key={c.id || i} className="mt-1">
            <strong>{c.type}</strong>: {c.subject}
            {c.sent_at && <p>Sent: {formatDateTime(c.sent_at)}</p>}
          </div>
        ))}
      </div>
    ) : (
      <p>No communications</p>
    )}
  </div>;

  const { stakeholders } = change;

  const renderStakeholders = () =>
  <div>
    {stakeholders ? (
      <div>
        {stakeholders.map((s, i) => (
          <div key={s.id || i} className="mt-1">
            <strong>{s.user?.employee_id}:</strong> {s.user?.email}
          </div>
        ))}
      </div>
    ) : (
      <p>No stakeholders</p>
    )}
  </div>;

  const { implementation } = change;

  const renderImplementation = () =>
  <div>
    {implementation ? (
      <div>
        <p><strong>Status:</strong> {implementation.status || '—'}</p>
        <p><strong>Started:</strong> {implementation.started_by ? implementation.started_by.employee_id : '—'}</p>
        <p><strong>Completed:</strong> {implementation.completed_by ? implementation.completed_by.employee_id : '—'}</p>
        <p><strong>Outcome:</strong> {implementation.outcome || '—'}</p>
      </div>
    ) : (
      <p>No implementation record</p>
    )}
  </div>;

  const { post_implementation_review } = change;

  const renderPIR = () =>
  <div>
    {post_implementation_review ? (
      <div>
        <p><strong>Reviewer:</strong> {post_implementation_review.reviewer?.employee_id || '—'}</p>
        <p><strong>Status:</strong> {post_implementation_review.status}</p>
        <p><strong>Outcome:</strong> {post_implementation_review.outcome}</p>
        <p><strong>Objectives Met:</strong> {post_implementation_review.objectives_met ? 'Yes' : 'No'}</p>
      </div>
    ) : (
      <p>No PIR</p>
    )}
  </div>;

  const { related_tickets } = change;

  const renderRelatedTickets = () =>
  <div>
    {related_tickets ? (
      <div>
        {related_tickets.map((t, i) => (
          <div key={t.id || i} className="mt-1">
            <strong>{t.ticket ? t.ticket.ticket_id : 'Ticket'}</strong> — {t.role || ''}
          </div>
        ))}
      </div>
    ) : (
      <p>No related tickets</p>
    )}
  </div>;

  const { knowledge_links } = change;

  const renderKnowledgeBase = () =>
  <div>
    {knowledge_links ? (
      <div>
        {knowledge_links.map((l, i) => (
          <div key={l.id || i} className="mt-1">
            <strong>{l.article_title}</strong>: {l.relation_type}
          </div>
        ))}
      </div>
    ) : (
      <p>No knowledge base references</p>
    )}
  </div>;

  const { history } = change;

  const renderHistory = () =>
  <div>
    {history ? (
      <div>
        {history.map((h, i) => (
          <div key={h.id || i} className="mt-1">
            <strong>{h.event_type}</strong>: {h.timestamp}
          </div>
        ))}
      </div>
    ) : (
      <p>No history</p>
    )}
  </div>;

  if (loading) {
    return <div className="mt-3"><p>Loading change…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  if (!change) {
    return <div className="mt-3"><p>Change not found</p></div>;
  }

  return (
    <div>
      <PageHeader title={change.change_number} subtitle={change.title} />
      <div className="mt-3">
        {Object.entries(tabLabels).map(([key, label]) => (
          <button
            key={key}
            className={`btn ${activeTab === key ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setActiveTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {activeTab === 'overview' && renderOverview()}
      {activeTab === 'impact' && renderImpact()}
      {activeTab === 'plans' && renderPlans()}
      {activeTab === 'assets' && renderAssets()}
      {activeTab === 'services' && renderServices()}
      {activeTab === 'tasks' && renderTasks()}
      {activeTab === 'risk' && renderRisk()}
      {activeTab === 'approvals' && renderApprovals()}
      {activeTab === 'schedule' && renderSchedule()}
      {activeTab === 'conflicts' && renderConflicts()}
      {activeTab === 'attachments' && renderAttachments()}
      {activeTab === 'communications' && renderCommunications()}
      {activeTab === 'stakeholders' && renderStakeholders()}
      {activeTab === 'implementation' && renderImplementation()}
      {activeTab === 'pir' && renderPIR()}
      {activeTab === 'related_tickets' && renderRelatedTickets()}
      {activeTab === 'kb' && renderKnowledgeBase()}
      {activeTab === 'history' && renderHistory()}
    </div>
  );
}