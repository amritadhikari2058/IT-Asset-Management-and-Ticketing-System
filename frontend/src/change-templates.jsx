/* 
 * Change Templates - change templates management
 * Routes: #/change-templates, #/change-templates/new, #/change-templates/:id/edit
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Row, Col } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError } from './changes-utils';

export function ChangeTemplates() {
  const { isStaff } = useAuth();
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isStaff) {
      setTemplates([]); // eslint-disable-line react/set-state-in-effect
      setLoading(false); // eslint-disable-line react/set-state-in-effect
      return;
    }
    fetchPage(`/change-templates/`)
      .then((data) => {
        setTemplates(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [isStaff]);

  if (loading) {
    return <div className="mt-3"><p>Loading templates…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  return (
    <div>
      <PageHeader title="Change Templates" />
      <div className="mt-3">
        <p><strong>Total Templates:</strong> {templates.length}</p>
        {templates.length === 0 ? (
          <p>No templates found</p>
        ) : (
          <div>
            {templates.map((t, i) => (
              <div key={t.id || i} className="mt-3 p-2 border rounded">
                <Row>
                  <Col sm={6}><strong>Name:</strong> {t.name}</Col>
                  <Col sm={6}><strong>Code:</strong> {t.code}</Col>
                  <Col sm={12}><strong>Category:</strong> {t.category}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}>
                    <strong>Risk:</strong> {t.risk}
                    {t.pre_approved && <span className="badge bg-success ms-2">Pre-approved</span>}
                    {t.is_active && <span className="badge bg-info ms-2">Active</span>}
                  </Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}><strong>Version:</strong> {t.version}</Col>
                  <Col sm={12}><strong>Owner:</strong> {t.owner?.employee_id || '—'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}><strong>Task Definitions:</strong> {t.task_definitions || '—'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}><strong>Approval Policy:</strong> {t.approval_policy || '—'}</Col>
                </Row>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}