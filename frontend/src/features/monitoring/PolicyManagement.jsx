import { useAuth } from '../../auth';
import { PageHeader } from '../../components';
import { AccessDeniedPanel } from '../../components/monitoring/MonitoringUI';
import { canAdministerMonitoring } from '../../components/monitoring/access';
import { AutomationPolicyMinSeverity, AutomationPolicyEligibleState, AutomationPolicySourceFilter } from '../../types/monitoring';

/** Ticket Automation Policy — preview only.
 *
 * The MonitoringAutomationPolicy model exists but NO policy CRUD endpoints
 * are registered on the backend:
 *   GET/POST/PATCH/DELETE /monitoring/automation-policies/   (not registered)
 *
 * This panel is a non-submittable policy preview. Save and delete actions
 * are disabled. No policy state is stored. Policy administration is not
 * operational until the backend exposes the proposed endpoints.
 *
 * Proposed future backend API (not existing):
 *   GET /monitoring/automation-policies/
 *   POST /monitoring/automation-policies/
 *   GET /monitoring/automation-policies/{id}/
 *   PATCH /monitoring/automation-policies/{id}/
 *   DELETE /monitoring/automation-policies/{id}/
 */
export function PolicyManagement() {
  const auth = useAuth();
  const isAdmin = canAdministerMonitoring(auth);

  const form = {
    name: 'Example policy',
    description: 'Automatically create tickets for critical alerts.',
    is_active: true,
    source_filter: AutomationPolicySourceFilter.ALL,
    minimum_severity: AutomationPolicyMinSeverity.CRITICAL,
    eligible_alert_states: AutomationPolicyEligibleState.OPEN,
    target_service: 'monitoring',
    ticket_category: 'incident',
    default_priority: 'high',
    default_queue: 'infra',
    auto_create: true,
    auto_update: true,
    auto_resolve: true,
    reopen_behavior: 'reopen on new event',
    maximum_retries: 3,
    effective_from: '',
    effective_until: '',
    eligible_sources: [],
  };

  if (!isAdmin) {
    return (
      <div>
        <PageHeader title="Ticket automation policies" sub="Monitoring-to-ticket automation policy management." />
        <AccessDeniedPanel reason="admin" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Ticket automation policies"
        sub="Policy administration API not available."
      />
      <div className="panel panel-pad">
        <div className="error-summary" role="alert">
          Policy CRUD endpoints are not registered on the backend
          (GET/POST/PATCH/DELETE /monitoring/automation-policies/).
          Policy administration is not operational. The form below is an
          illustrative read-only preview of the MonitoringAutomationPolicy
          contract; its values are not saved and are not backend data.
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginTop: 12 }}>
        <dl className="detail-grid">
          <dt>Name</dt><dd>{form.name}</dd>
          <dt>Description</dt><dd>{form.description}</dd>
          <dt>Active</dt><dd>{form.is_active ? 'Yes' : 'No'}</dd>
          <dt>Source filter</dt><dd>{form.source_filter}</dd>
          <dt>Minimum severity</dt><dd>{form.minimum_severity}</dd>
          <dt>Eligible alert state</dt><dd>{form.eligible_alert_states}</dd>
          <dt>Target service</dt><dd>{form.target_service}</dd>
          <dt>Ticket category</dt><dd>{form.ticket_category}</dd>
          <dt>Default priority</dt><dd>{form.default_priority}</dd>
          <dt>Default queue</dt><dd>{form.default_queue}</dd>
          <dt>Auto-create ticket</dt><dd>{form.auto_create ? 'Yes' : 'No'}</dd>
          <dt>Auto-update ticket</dt><dd>{form.auto_update ? 'Yes' : 'No'}</dd>
          <dt>Auto-resolve ticket</dt><dd>{form.auto_resolve ? 'Yes' : 'No'}</dd>
          <dt>Reopen behavior</dt><dd>{form.reopen_behavior}</dd>
          <dt>Retry limit</dt><dd>{form.maximum_retries}</dd>
          <dt>Effective from</dt><dd>{form.effective_from || '—'}</dd>
          <dt>Effective until</dt><dd>{form.effective_until || '—'}</dd>
          <dt>Eligible sources</dt><dd className="cell-muted small">{form.eligible_sources.length ? form.eligible_sources.join(', ') : 'none (all when source_filter=all)'}</dd>
        </dl>
      </div>

      <div className="panel panel-pad" style={{ marginTop: 12 }}>
        <div className="row-end">
          <button type="button" className="btn-small btn-primary" disabled>
            Save (backend API missing)
          </button>
          <button type="button" className="btn-small btn-danger" disabled>
            Delete (backend API missing)
          </button>
        </div>
      </div>
    </div>
  );
}

export default PolicyManagement;
