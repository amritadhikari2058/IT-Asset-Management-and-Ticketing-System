/* 
 * Change Scheduling - scheduling panel for a change
 * Route: #/changes/:id/implementation (or #/changes/:id/schedule)
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Badge, Form, Input, Select } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError } from './changes-utils';

export function ChangeSchedule({ match }) {
  const { isStaff, role } = useAuth();
  const [change, setChange] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [conflicts, setConflicts] = useState([]);

  useEffect(() => {
    const id = match.params.id;
    if (!id) return;
    fetchPage(`/changes/${id}/schedule/`)
      .then((data) => {
        setChange(data);
        setReadiness(data.readiness);
        setConflicts(data.conflicts || []);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [match.params.id]);

  if (loading) {
    return <div className="mt-3"><p>Loading schedule…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  if (!change) {
    return <div className="mt-3"><p>Change not found</p></div>;
  }

  return (
    <div>
      <PageHeader title="Scheduling" subtitle={change.change_number} />
      <div className="mt-3">
        <p><strong>Change Number:</strong> {change.change_number}</p>
        <p><strong>Title:</strong> {change.title}</p>
        <hr />
        {readiness && (
          <div className="mt-3">
            <h4>Readiness</h4>
            <p><strong>Ready:</strong> {readiness.ready ? 'Yes' : 'No'}</p>
            {readiness.blockers && readability.blockers.length > 0 && (
              <p><strong>Blockers:</strong> {readiness.blockers.map((b, i) => `${b}`).join(', ')}</p>
            )}
          </div>
        )}
        {conflicts && conflicts.length > 0 && (
          <div className="mt-3">
            <h4>Conflicts</h4>
            <p>{conflicts.map((c, i) => `${c.conflicting_change_number}: ${c.context}`).join(', ')}</p>
          </div>
        )}
        {isStaff && role !== 'employee' && (
          <Form>
            <Input type="datetime-local" placeholder="Planned start" />
            <Input type="datetime-local" placeholder="Planned end" />
            <Input placeholder="Expected downtime (minutes)" />
            <Select placeholder="Maintenance window" />
            <Button type="primary">Schedule Change</Button>
          </Form>
        )}
      </div>
    </div>
  );
}