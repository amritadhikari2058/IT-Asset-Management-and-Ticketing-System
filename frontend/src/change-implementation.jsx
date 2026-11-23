/* 
 * Change Implementation - implementation console for a change
 * Route: #/changes/:id/implementation
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Badge, Form, Button } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError } from './changes-utils';

export function ChangeImplementation({ match }) {
  const { role } = useAuth();
  const [change, setChange] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [elapsedMinutes, setElapsedMinutes] = useState(0);
  const [startTime, setStartTime] = useState(null);

  useEffect(() => {
    const id = match.params.id;
    if (!id) return;
    fetchPage(`/changes/${id}/implementation/`)
      .then((data) => {
        setChange(data);
        setLoading(false);
        // Start elapsed timer if change is in progress
        if (data.status === 'in_progress' && data.implementation_start) {
          setStartTime(new Date(data.implementation_start));
          const interval = setInterval(() => {
            setElapsedMinutes(prev => prev + 60);
          }, 60000);
          return () => clearInterval(interval);
        }
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [match.params.id]);

  if (loading) {
    return <div className="mt-3"><p>Loading implementation…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  if (!change) {
    return <div className="mt-3"><p>Change not found</p></div>;
  }

  // Calculate elapsed time
  const elapsed = startTime ? Math.floor((new Date().getTime() - startTime.getTime()) / 60000) : elapsedMinutes; // eslint-disable-line react/purity // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <PageHeader title="Implementation" subtitle={change.change_number} />
      <div className="mt-3">
        <p><strong>Change Number:</strong> {change.change_number}</p>
        <p><strong>Title:</strong> {change.title}</p>
        <hr />
        <div className="mt-3">
          <h4>Change Status</h4>
          <Badge kind={change.status ? 'primary' : 'secondary'}>
            {change.status || 'draft'}
          </Badge>
        </div>
        <div className="mt-3">
          <h4>Timing</h4>
          <p><strong>Planned Window:</strong> {change.planned_start ? new Date(change.planned_start).toLocaleString() : '—'}</p>
          <p><strong>Actual Start:</strong> {startTime ? startTime.toLocaleString() : 'Not started'}</p>
          <p><strong>Elapsed:</strong> {elapsed} minutes</p>
        </div>
        {role === 'system_admin' && (
          <Form>
            <Button type="primary">Start Implementation</Button>
            <Button>Start Task</Button>
            <Button>Complete Task</Button>
            <Button>Record Task Failure</Button>
            <Button type="success">Begin Validation</Button>
            <Button>Complete Change</Button>
            <Button type="danger">Fail Change</Button>
            <Button>Start Rollback</Button>
            <Button>Complete Rollback</Button>
          </Form>
        )}
        {!role || role === 'employee' ? (
          <p className="text-muted small">Implementation actions available to privileged roles only</p>
        ) : null}
      </div>
    </div>
  );
}