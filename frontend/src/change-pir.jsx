/* 
 * Change PIR - Post-Implementation Review
 * Route: #/changes/:id/pir
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Form, Row, Col, Button } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError } from './changes-utils';

export function ChangePIR({ match }) {
  const { role } = useAuth();
  const [pir, setPIR] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const id = match.params.id;
    if (!id) return;
    fetchPage(`/changes/${id}/pir/`)
      .then((data) => {
        setPIR(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [match.params.id]);

  if (loading) {
    return <div className="mt-3"><p>Loading PIR…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  if (!pir) {
    return <div className="mt-3"><p>PIR not found</p></div>;
  }

  // Determine if waiver is allowed
  const canWaiver = role === 'system_admin';

  return (
    <div>
      <PageHeader title="PIR & Closure" subtitle={pir.change_number} />
      <div className="mt-3">
        <p><strong>Change Number:</strong> {pir.change_number}</p>
        <hr />
        <div className="mt-3">
          <h4>PIR Details</h4>
          <Row>
            <Col sm={6}><strong>Reviewer:</strong> {pir.reviewer?.employee_id || '—'}</Col>
            <Col sm={6}><strong>Status:</strong> {pir.status}</Col>
          </Row>
          <Row className="mt-1">
            <Col sm={12}><strong>Outcome:</strong> {pir.outcome}</Col>
          </Row>
          <Row className="mt-1">
            <Col sm={6}><strong>Objectives Met:</strong> {pir.objectives_met ? 'Yes' : 'No'}</Col>
            <Col sm={6}><strong>Validation Successful:</strong> {pir.validation_successful ? 'Yes' : 'No'}</Col>
          </Row>
          <Row className="mt-1">
            <Col sm={6}><strong>Downtime Within Estimate:</strong> {pir.downtime_within_estimate ? 'Yes' : 'No'}</Col>
            <Col sm={6}><strong>Rollback Used:</strong> {pir.rollback_used ? 'Yes' : 'No'}</Col>
          </Row>
          <Row className="mt-1">
            <Col sm={12}><strong>Incident Created:</strong> {pir.incident_created ? 'Yes' : 'No'}</Col>
          </Row>
          {pir.lessons_learned && (
            <Row className="mt-3">
              <Col sm={12}><strong>Lessons Learned:</strong> {pir.lessons_learned}</Col>
            </Row>
          )}
          {pir.follow_up_actions && (
            <Row className="mt-3">
              <Col sm={12}><strong>Follow-Up Actions:</strong> {pir.follow_up_actions}</Col>
            </Row>
          )}
          {pir.knowledge_base_article && (
            <Row className="mt-3">
              <Col sm={12}><strong>Knowledge Base Article:</strong> {pir.knowledge_base_article}</Col>
            </Row>
          )}
        </div>
        {canWaiver && (
          <div className="mt-3">
            <h4>Waiver</h4>
            <p>System Admin waiver for PIR requirement</p>
            <Form>
              <Button type="primary">Waive PIR</Button>
            </Form>
          </div>
        )}
        {role === 'system_admin' && (
          <div className="mt-3">
            <h4>Close Change</h4>
            <p>Close the change through the official action</p>
            <Form>
              <Button type="success">Close Change</Button>
            </Form>
          </div>
        )}
      </div>
    </div>
  );
}