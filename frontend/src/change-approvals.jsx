/* 
 * Change Approvals - approval history and actions for a change
 * Route: #/changes/:id/approvals
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Badge, Form, Input } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError } from './changes-utils';

export function ChangeApprovals({ match }) {
  const { isStaff, role } = useAuth();
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const id = match.params.id;
    if (!id) return;
    fetchPage(`/changes/${id}/approvals/`)
      .then((data) => {
        setApprovals(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [match.params.id]);

  if (loading) {
    return <div className="mt-3"><p>Loading approvals…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  return (
    <div>
      <PageHeader title="Approvals" subtitle={approvals.length > 0 ? approvals[0].change_number : ''} />
      <div className="mt-3">
        <p><strong>Total Approvals:</strong> {approvals.length}</p>
        {approvals.length === 0 ? (
          <p>No approvals found</p>
        ) : (
          <div>
            {approvals.map((a, i) => (
              <div key={a.id || i} className="mt-3 p-2 border rounded">
                <Row>
                  <Col sm={3}><strong>Level:</strong> {a.approval_level}</Col>
                  <Col sm={3}><strong>Status:</strong> {a.status}</Col>
                  <Col sm={3}><strong>Requested From:</strong> {a.requested_from || ''}</Col>
                  <Col sm={3}><strong>Decided By:</strong> {a.decided_by || '—'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}>
                    <strong>Requested:</strong> {a.requested_date || ''}
                    {a.decided_date && ` — Decided: ${a.decided_date}`}
                  </Col>
                </Row>
                {a.decision_reason && (
                  <Row className="mt-1">
                    <Col sm={12}><em><strong>Decision Reason:</strong> {a.decision_reason}</em></p></Col>
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