/* 
 * Change Conflicts - conflict management for a change
 * Route: #/changes/:id/conflicts
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Badge, Form } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError } from './changes-utils';

export function ChangeConflicts({ match }) {
  const { isStaff, role } = useAuth();
  const [conflicts, setConflicts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const id = match.params.id;
    if (!id) return;
    fetchPage(`/changes/${id}/conflicts/`)
      .then((data) => {
        setConflicts(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [match.params.id]);

  if (loading) {
    return <div className="mt-3"><p>Loading conflicts…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  return (
    <div>
      <PageHeader title="Conflicts" subtitle={conflicts.length > 0 ? conflicts[0].change_number : ''} />
      <div className="mt-3">
        <p><strong>Total Conflicts:</strong> {conflicts.length}</p>
        {conflicts.length === 0 ? (
          <p>No conflicts found</p>
        ) : (
          <div>
            {conflicts.map((c, i) => (
              <div key={c.id || i} className="mt-3 p-2 border rounded">
                <Row>
                  <Col sm={4}><strong>Conflicting Change:</strong> {c.conflicting_change_number}</Col>
                  <Col sm={2}><strong>Severity:</strong> {c.severity}</Col>
                  <Col sm={4}><strong>Status:</strong> {c.status}</Col>
                  <Col sm={2}>
                    {isStaff && (
                      <Select>
                        <option value="acknowledged">Acknowledged</option>
                        <option value="resolved">Resolved</option>
                        <option value="accepted">Accepted</option>
                      </Select>
                    )}
                  </Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}><strong>Overlap:</strong> {c.overlap || ''}</Col>
                </Row>
                {c.context && (
                  <Row className="mt-1">
                    <Col sm={12}><strong>Context:</strong> {c.context}</Col>
                  </Row>
                )}
                {c.resolution && (
                  <Row className="mt-1">
                    <Col sm={12}><em><strong>Resolution:</strong> {c.resolution}</em></Col>
                  </Row>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}