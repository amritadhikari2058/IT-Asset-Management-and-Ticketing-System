/* 
 * Change Risk - risk assessment component for a change
 * Route: #/changes/:id/risk
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Form, Input, Select, Button, Row, Col } from '../../components';
import { useAuth } from '../../auth';
import { fetchPage, parseApiError } from '../../shared/changes-utils';

export function ChangeRisk({ match }) {
  const { role } = useAuth();
  const [risk, setRisk] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [override, setOverride] = useState(false);
  const [overrideReason, setOverrideReason] = useState('');

  useEffect(() => {
    const id = match.params.id;
    if (!id) return;
    fetchPage(`/changes/${id}/risk/`)
      .then((data) => {
        setRisk(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [match.params.id]);

  if (loading) {
    return <div className="mt-3"><p>Loading risk assessment…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  if (!risk) {
    return <div className="mt-3"><p>Risk assessment not found</p></div>;
  }

  return (
    <div>
      <PageHeader title="Risk Assessment" subtitle={risk.change_number || ''} />
      <div className="mt-3">
        <p><strong>Change Number:</strong> {risk.change_number}</p>
        <p><strong>Title:</strong> {risk.title}</p>
        <hr />
        <h4>Questionnaire</h4>
        <Form>
          <Row>
            <Col sm={6}><Input placeholder="Affected users" value={risk.affected_users || ''} onChange={(e) => setRisk(c => ({ ...c, affected_users: e.target.value }))} /></Col>
            <Col sm={6}><Input placeholder="Critical service impact" value={risk.critical_service_impact || ''} onChange={(e) => setRisk(c => ({ ...c, critical_service_impact: e.target.value }))} /></Col>
          </Row>
          <Row className="mt-3">
            <Col sm={6}><Input placeholder="Expected downtime" value={risk.expected_downtime || ''} onChange={(e) => setRisk(c => ({ ...c, expected_downtime: e.target.value }))} /></Col>
            <Col sm={6}><Input placeholder="Data migration" value={risk.data_migration || ''} onChange={(e) => setRisk(c => ({ ...c, data_migration: e.target.value }))} /></Col>
          </Row>
          <Row className="mt-3">
            <Col sm={6}><Input placeholder="Security configuration change" value={risk.security_configuration || ''} onChange={(e) => setRisk(c => ({ ...c, security_configuration: e.target.value }))} /></Col>
            <Col sm={6}><Input placeholder="Database schema change" value={risk.database_schema || ''} onChange={(e) => setRisk(c => ({ ...c, database_schema: e.target.value }))} /></Col>
          </Row>
          <Row className="mt-3">
            <Col sm={6}><Input placeholder="External dependency" value={risk.external_dependency || ''} onChange={(e) => setRisk(c => ({ ...c, external_dependency: e.target.value }))} /></Col>
            <Col sm={6}><Input placeholder="Rollback tested" value={risk.rollback_tested || ''} onChange={(e) => setRisk(c => ({ ...c, rollback_tested: e.target.value }))} /></Col>
          </Row>
          <Row className="mt-3">
            <Col sm={6}><Input placeholder="Implementation tested" value={risk.implementation_tested || ''} onChange={(e) => setRisk(c => ({ ...c, implementation_tested: e.target.value }))} /></Col>
            <Col sm={6}><Select placeholder="First-time Change"><option value="">Select</option><option value="yes">Yes</option><option value="no">No</option></Select></Col>
          </Row>
          <Row className="mt-3">
            <Col sm={6}><Input placeholder="Multi-team coordination" value={risk.multi_team_coordination || ''} onChange={(e) => setRisk(c => ({ ...c, multi_team_coordination: e.target.value }))} /></Col>
            <Col sm={6}><Input placeholder="Out-of-hours" value={risk.out_of_hours || ''} onChange={(e) => setRisk(c => ({ ...c, out_of_hours: e.target.value }))} /></Col>
          </Row>
          <Row className="mt-3">
            <Col sm={12}><Input placeholder="Validated-system impact" value={risk.validated_system_impact || ''} onChange={(e) => setRisk(c => ({ ...c, validated_system_impact: e.target.value }))} /></Col>
          </Row>
          <Row className="mt-3">
            <Col sm={12}><Input placeholder="Backup verified" value={risk.backup_verified || ''} onChange={(e) => setRisk(c => ({ ...c, backup_verified: e.target.value }))} /></Col>
          </Row>
          <Row className="mt-3">
            <Col sm={12}><Input placeholder="Monitoring plan" value={risk.monitoring_plan || ''} onChange={(e) => setRisk(c => ({ ...c, monitoring_plan: e.target.value }))} /></Col>
          </Row>
        </Form>
        <hr />
        <h4>Scores</h4>
        <Row>
          <Col sm={6}><p><strong>Factor Scores:</strong> {risk.factor_scores || '—'}</p></Col>
          <Col sm={6}><p><strong>Total Score:</strong> {risk.total_score || '—'}</p></Col>
        </Row>
        <Row className="mt-3">
          <Col sm={12}><p><strong>Calculated Risk:</strong> {risk.calculated_risk || '—'}</p></Col>
        </Row>
        {role === 'system_admin' && (
          <Row className="mt-3">
            <Col sm={6}><Input placeholder="Override level" value={override ? 'high' : 'none'} readOnly />{" "}<Input placeholder="Override reason" value={overrideReason || ''} onChange={(e) => setOverrideReason(e.target.value)} /></Col>
            <Col sm={6}><Button onClick={() => setOverride(true)}>Apply Override</Button></Col>
          </Row>
        )}
      </div>
    </div>
  );
}
