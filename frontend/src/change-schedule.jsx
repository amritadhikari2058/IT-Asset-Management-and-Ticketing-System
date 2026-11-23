/* 
 * Change Scheduling - enhanced scheduling panel for a change
 * Route: #/changes/:id/implementation (or #/changes/:id/schedule)
 * 
 * Displays scheduled changes, conflicts, and scheduling UI.
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Badge, Button, Form, Input, EmptyState } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError, formatDateTime, statusBadgeVariant, riskBadgeVariant, priorityBadgeVariant } from './changes-utils';

export function ChangeSchedule({ match }) {
  const { isStaff } = useAuth();
  const [change, setChange] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [conflicts, setConflicts] = useState([]);
  const [scheduleConflicts, setScheduleConflicts] = useState([]);
  const [blackoutPeriods, setBlackoutPeriods] = useState([]);
  const [maintenanceWindows, setMaintenanceWindows] = useState([]);
  const [schedulingExceptions, setSchedulingExceptions] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState(null);

  // Scheduling form state
  const [plannedStart, setPlannedStart] = useState('');
  const [plannedEnd, setPlannedEnd] = useState('');
  const [expectedDowntime, setExpectedDowntime] = useState('');

  useEffect(() => {
    const id = match.params.id;
    if (!id) return;
    Promise.all([
      fetchPage(`/changes/${id}/`),
      fetchPage(`/changes/${id}/readiness/`),
      fetchPage(`/changes/${id}/conflicts/`),
      fetchPage(`/changes/${id}/schedule_conflicts/`),
      fetchPage(`/blackout-periods/`),
      fetchPage(`/maintenance-windows/`),
      fetchPage(`/scheduling-exceptions/`),
    ]).then(([changeData, readinessData, conflictsData, scheduleData, blackoutData, maintenanceData, exceptionData]) => {
      setChange(changeData);
      setReadiness(readinessData);
      setConflicts(conflictsData || []);
      setScheduleConflicts(scheduleData || []);
      setBlackoutPeriods((blackoutData && blackoutData.items) || blackoutData || []);
      setMaintenanceWindows((maintenanceData && maintenanceData.items) || maintenanceData || []);
      const exItems = (exceptionData && exceptionData.items) || exceptionData || [];
      setSchedulingExceptions(exItems.filter((ex) => String(ex.change) === String(id) || ex.change === parseInt(id, 10) || (ex.change && ex.change.id === parseInt(id, 10))));
      // Pre-fill form with existing scheduled times
      if (changeData.planned_start) {
        setPlannedStart(formatDateTimeForInput(changeData.planned_start));
      }
      if (changeData.planned_end) {
        setPlannedEnd(formatDateTimeForInput(changeData.planned_end));
      }
      if (changeData.expected_downtime_minutes) {
        setExpectedDowntime(changeData.expected_downtime_minutes);
      }
      setLoading(false);
    }).catch((e) => {
      setError(parseApiError(e));
      setLoading(false);
    });
  }, [match.params.id]);

  function formatDateTimeForInput(dateTimeStr) {
    if (!dateTimeStr) return '';
    const d = new Date(dateTimeStr);
    if (isNaN(d)) return '';
    // Format as YYYY-MM-DDTHH:MM for datetime-local input
    const pad = (n) => n.toString().padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  const handleSchedule = async () => {
    if (submitting) return;
    if (!plannedStart || !plannedEnd) {
      setActionError('Planned start and end are required.');
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      const response = await fetch(`/changes/${match.params.id}/schedule/`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json', 
          'Authorization': `Bearer ${localStorage.getItem('access')}` 
        },
        body: JSON.stringify({
          planned_start: plannedStart,
          planned_end: plannedEnd,
          expected_downtime_minutes: expectedDowntime ? parseInt(expectedDowntime) : null,
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        let msg = errorData.detail || errorData.scheduling_policy || Object.values(errorData).join(' ');
        if (!msg) msg = 'Scheduling failed.';
        setActionError(msg);
        setSubmitting(false);
        return;
      }
      // Refresh data
      const refreshed = await fetchPage(`/changes/${match.params.id}/`);
      setChange(refreshed);
      const scheduleData = await fetchPage(`/changes/${match.params.id}/schedule_conflicts/`);
      setScheduleConflicts(scheduleData || []);
    } catch (err) {
      setActionError(parseApiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <div className="mt-3"><p>Loading schedule...</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  if (!change) {
    return <div className="mt-3"><p>Change not found</p></div>;
  }

  const canSchedule = isStaff && (change.status === 'approved' || change.status === 'on_hold');

  return (
    <div>
      <PageHeader title="Scheduling" subtitle={change.change_number} />
      
      <div className="mt-3">
        <p><strong>Change Number:</strong> {change.change_number}</p>
        <p><strong>Title:</strong> {change.title}</p>
        <hr />
        
        {/* Current Schedule */}
        <div className="panel panel-default mt-3">
          <div className="panel-heading">Current Schedule</div>
          <div className="panel-body">
            <p><strong>Status:</strong> <Badge kind={statusBadgeVariant(change.status)}>{change.status}</Badge></p>
            {change.planned_start && (
              <p><strong>Planned Start:</strong> {formatDateTime(change.planned_start)}</p>
            )}
            {change.planned_end && (
              <p><strong>Planned End:</strong> {formatDateTime(change.planned_end)}</p>
            )}
            {change.expected_downtime_minutes && (
              <p><strong>Expected Downtime:</strong> {change.expected_downtime_minutes} minutes</p>
            )}
            {change.scheduled_at && (
              <p><strong>Scheduled At:</strong> {formatDateTime(change.scheduled_at)}</p>
            )}
          </div>
        </div>

        {/* Readiness */}
        {readiness && (
          <div className="panel panel-default mt-3">
            <div className="panel-heading">Readiness</div>
            <div className="panel-body">
              <p><strong>Ready:</strong> {readiness.ready ? 'Yes' : 'No'}</p>
              {readiness.blockers && readiness.blockers.length > 0 && (
                <div className="alert alert-warning">
                  <strong>Blockers:</strong>
                  <ul>
                    {readiness.blockers.map((b, i) => <li key={i}>{b}</li>)}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Schedule Conflicts */}
        {scheduleConflicts.length > 0 && (
          <div className="panel panel-default mt-3">
            <div className="panel-heading">
              Schedule Conflicts ({scheduleConflicts.length})
              <Badge kind="danger" className="pull-right">{scheduleConflicts.length}</Badge>
            </div>
            <div className="panel-body">
              <div className="table-responsive">
                <table className="table table-striped">
                  <thead>
                    <tr>
                      <th>Change</th>
                      <th>Type</th>
                      <th>Risk</th>
                      <th>Priority</th>
                      <th>Planned Start</th>
                      <th>Planned End</th>
                      <th>Conflict</th>
                      <th>Overlap</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {scheduleConflicts.map((c, i) => (
                      <tr key={i} className={c.severity === 'high' ? 'table-danger' : c.severity === 'medium' ? 'table-warning' : ''}>
                        <td>
                          <strong>{c.change_number}</strong><br/>
                          <small className="text-muted">{c.title}</small>
                        </td>
                        <td>{c.change_type}</td>
                        <td><Badge kind={riskBadgeVariant(c.risk_level)}>{c.risk_level}</Badge></td>
                        <td><Badge kind={c.severity === 'high' ? 'danger' : c.severity === 'medium' ? 'warning' : c.severity === 'low' ? 'info' : 'secondary'}>{c.severity}</Badge></td>
                        <td><Badge kind={priorityBadgeVariant(c.priority)}>{c.priority}</Badge></td>
                        <td>{formatDateTime(c.planned_start)}</td>
                        <td>{formatDateTime(c.planned_end)}</td>
                        <td>
                          <Badge kind={c.severity === 'high' ? 'danger' : c.severity === 'medium' ? 'warning' : c.severity === 'low' ? 'info' : 'secondary'}>
                            {c.conflict_type.replace(/_/g, ' ')}
                          </Badge>
                        </td>
                        <td>
                          {c.overlap_minutes != null ? `${Math.round(c.overlap_minutes)} min` : '—'}
                          {c.shared_assets && c.shared_assets.length > 0 && (
                            <span className="text-danger ml-1">
                              <small>{c.shared_assets.length} shared CI(s)</small>
                            </span>
                          )}
                          {c.shared_services && c.shared_services.length > 0 && (
                            <span className="text-warning ml-1">
                              <small>{c.shared_services.length} shared service(s)</small>
                            </span>
                          )}
                        </td>
                        <td>
                          <Button 
                            kind="ghost" 
                            size="small"
                            onClick={() => window.location.hash = `/changes/${c.id}`}
                          >
                            View
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* Existing Conflicts (from conflicts tab) */}
        {conflicts.length > 0 && conflicts !== scheduleConflicts && (
          <div className="panel panel-default mt-3">
            <div className="panel-heading">Registered Conflicts ({conflicts.length})</div>
            <div className="panel-body">
              <div className="table-responsive">
                <table className="table table-striped">
                  <thead>
                    <tr>
                      <th>Change</th>
                      <th>Type</th>
                      <th>Severity</th>
                      <th>Status</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {conflicts.map((c, i) => (
                      <tr key={i}>
                        <td>
                          <strong>{c.change_number}</strong><br/>
                          <small className="text-muted">{c.title || ''}</small>
                        </td>
                        <td>{c.conflicting_change_number}</td>
                        <td>
                          <Badge kind={c.severity === 'critical' ? 'danger' : c.severity === 'high' ? 'warning' : 'secondary'}>
                            {c.severity}
                          </Badge>
                        </td>
                        <td>{c.status}</td>
                        <td>
                          <Button 
                            kind="ghost" 
                            size="small"
                            onClick={() => window.location.hash = `/changes/${c.id}`}
                          >
                            View
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* Scheduling Policy Feedback */}
        <div className="panel panel-default mt-3">
          <div className="panel-heading">Scheduling Policy Feedback</div>
          <div className="panel-body">
            {(() => {
              const ps = plannedStart ? new Date(plannedStart) : (change.planned_start ? new Date(change.planned_start) : null);
              const pe = plannedEnd ? new Date(plannedEnd) : (change.planned_end ? new Date(change.planned_end) : null);
              const hasWindow = ps && pe && !isNaN(ps) && !isNaN(pe);
              const activeBlackouts = hasWindow ? blackoutPeriods.filter((bp) => {
                if (bp.status !== 'active') return false;
                const bps = new Date(bp.start_at);
                const bpe = new Date(bp.end_at);
                if (isNaN(bps) || isNaN(bpe)) return false;
                if (!(ps <= bpe && bps <= pe)) return false;
                // Scope matching (best-effort)
                if (bp.scope_department && change.department && String(bp.scope_department) !== String(change.department) && String(bp.scope_department) !== String(change.department_id)) return false;
                if (bp.scope_service && change.service && String(bp.scope_service) !== String(change.service) && String(bp.scope_service) !== String(change.service_id)) return false;
                return true;
              }) : [];
              const eligibleWindows = hasWindow ? maintenanceWindows.filter((w) => {
                if (w.status !== 'active') return false;
                const ws = new Date(w.start_at);
                const we = new Date(w.end_at);
                if (isNaN(ws) || isNaN(we)) return false;
                return ws <= pe && ps <= we;
              }) : [];
              const pendingEx = schedulingExceptions.filter((e) => e.status === 'pending');
              const approvedEx = schedulingExceptions.filter((e) => e.status === 'approved');
              const rejectedEx = schedulingExceptions.filter((e) => e.status === 'rejected');
              const blackoutRequiresException = activeBlackouts.length > 0 && !activeBlackouts.every((bp) =>
                approvedEx.some((ex) => String(ex.blackout_period) === String(bp.id) || (ex.blackout_period && String(ex.blackout_period.id) === String(bp.id)))
              );
              return (
                <div>
                  {!hasWindow && (
                    <p className="text-muted">Enter planned start/end to evaluate scheduling policy.</p>
                  )}
                  {hasWindow && (
                    <>
                      {/* Maintenance window eligibility */}
                      {eligibleWindows.length > 0 ? (
                        <div className="alert alert-success">
                          <strong>Maintenance window eligible:</strong> This change falls within active maintenance window(s): {eligibleWindows.map((w) => w.name || w.code).join(', ')}.
                        </div>
                      ) : (
                        <div className="alert alert-warning">
                          <strong>Maintenance window:</strong> Planned time is not within any active maintenance window.
                        </div>
                      )}
                      {/* Blackout conflicts */}
                      {activeBlackouts.length > 0 ? (
                        <div className="alert alert-danger">
                          <strong>Blackout-period conflict:</strong> Planned time overlaps blackout period(s): {activeBlackouts.map((bp) => bp.name).join(', ')}.
                          {blackoutRequiresException && (
                            <span> An approved scheduling exception is required before scheduling can proceed.</span>
                          )}
                          {!blackoutRequiresException && (
                            <span> An approved exception is on file.</span>
                          )}
                        </div>
                      ) : (
                        <div className="alert alert-success">
                          <strong>No blackout-period conflict:</strong> Planned time does not overlap any active blackout period.
                        </div>
                      )}
                      {/* Exception status summary */}
                      <p>
                        <strong>Scheduling exceptions for this change:</strong>{' '}
                        Pending: {pendingEx.length}, Approved: {approvedEx.length}, Rejected: {rejectedEx.length}.
                      </p>
                      {blackoutRequiresException && (
                        <p className="text-danger">
                          <strong>Exception required:</strong> Submit a scheduling exception request and obtain approval before scheduling.
                        </p>
                      )}
                      {schedulingExceptions.length > 0 && (
                        <ul className="list-unstyled">
                          {schedulingExceptions.map((ex) => (
                            <li key={ex.id}>
                              <Badge kind={ex.status === 'approved' ? 'success' : ex.status === 'rejected' ? 'danger' : 'warning'}>{ex.status}</Badge>{' '}
                              {ex.justification}
                              {ex.blackout_period ? ` (blackout: ${ex.blackout_period})` : ''}
                              {ex.maintenance_window ? ` (window: ${ex.maintenance_window})` : ''}
                            </li>
                          ))}
                        </ul>
                      )}
                    </>
                  )}
                  {actionError && (
                    <div className="alert alert-danger"><strong>Scheduling validation failed:</strong> {actionError}</div>
                  )}
                </div>
              );
            })()}
          </div>
        </div>

        {/* Scheduling Form */}
        {canSchedule && (
          <div className="panel panel-default mt-3">
            <div className="panel-heading">Schedule Change</div>
            <div className="panel-body">
              {actionError && (
                <div className="alert alert-danger">{actionError}</div>
              )}
              <Form>
                <div className="form-group">
                  <label>Planned Start</label>
                  <Input
                    type="datetime-local"
                    value={plannedStart}
                    onChange={(e) => setPlannedStart(e.target.value)}
                    placeholder="YYYY-MM-DDTHH:MM"
                  />
                </div>
                <div className="form-group">
                  <label>Planned End</label>
                  <Input
                    type="datetime-local"
                    value={plannedEnd}
                    onChange={(e) => setPlannedEnd(e.target.value)}
                    placeholder="YYYY-MM-DDTHH:MM"
                  />
                </div>
                <div className="form-group">
                  <label>Expected Downtime (minutes)</label>
                  <Input
                    type="number"
                    min="0"
                    value={expectedDowntime}
                    onChange={(e) => setExpectedDowntime(e.target.value)}
                    placeholder="0"
                  />
                </div>
                <Button 
                  kind="primary" 
                  onClick={handleSchedule}
                  disabled={submitting || !plannedStart || !plannedEnd}
                >
                  {submitting ? 'Scheduling...' : 'Schedule Change'}
                </Button>
              </Form>
            </div>
          </div>
        )}

        {/* No conflicts state */}
        {!canSchedule && scheduleConflicts.length === 0 && conflicts.length === 0 && (
          <EmptyState 
            title="No scheduling information"
            hint="This change is not yet scheduled or has no conflicts."
          />
        )}
      </div>
    </div>
  );
}
