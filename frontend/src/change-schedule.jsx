/* 
 * Change Scheduling - enhanced scheduling panel for a change
 * Route: #/changes/:id/implementation (or #/changes/:id/schedule)
 * 
 * Displays scheduled changes, conflicts, and scheduling UI.
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Badge, Button, Form, Input, Select, EmptyState } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError, formatDateTime, statusBadgeVariant, riskBadgeVariant, priorityBadgeVariant } from './changes-utils';

export function ChangeSchedule({ match }) {
  const { isStaff, role } = useAuth();
  const [change, setChange] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [conflicts, setConflicts] = useState([]);
  const [scheduleConflicts, setScheduleConflicts] = useState([]);
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
    ]).then(([changeData, readinessData, conflictsData, scheduleData]) => {
      setChange(changeData);
      setReadiness(readinessData);
      setConflicts(conflictsData || []);
      setScheduleConflicts(scheduleData || []);
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
        setActionError(errorData.detail || Object.values(errorData).join(' '));
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
