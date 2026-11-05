/* 
 * Change Dashboard - change KPI dashboard
 * Route: #/changes/dashboard
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Card, Badge } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError } from './changes-utils';

export function ChangeDashboard() {
  const { isStaff, role } = useAuth();
  const [kpi, setKPI] = useState({
    draft: 0,
    pending_risk: 0,
    pending_technical_review: 0,
    pending_approval: 0,
    approved_unscheduled: 0,
    scheduled_7_days: 0,
    scheduled_30_days: 0,
    in_progress: 0,
    validation: 0,
    pir_overdue: 0,
    failed: 0,
    rolled_back: 0,
    emergency: 0,
    open_conflicts: 0,
    critical_conflicts: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isStaff) {
      setKPI({
        draft: 0, pending_risk: 0, pending_technical_review: 0, pending_approval: 0,
        approved_unscheduled: 0, scheduled_7_days: 0, scheduled_30_days: 0,
        in_progress: 0, validation: 0, pir_overdue: 0, failed: 0, rolled_back: 0,
        emergency: 0, open_conflicts: 0, critical_conflicts: 0,
      });
      setLoading(false);
      return;
    }
    fetchPage(`/changes/dashboard/`)
      .then((data) => {
        setKPI(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [isStaff]);

  if (loading) {
    return <div className="mt-3"><p>Loading dashboard…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  const renderKPI = (key, label) => (
    <Card style={{ width: '18rem' }} key={key}>
      <Card.Body>
        <Card.Title>{label}</Card.Title>
        <Card.Text>{kpi[key] || 0}</Card.Text>
      </Card.Body>
    </Card>
  );

  return (
    <div>
      <PageHeader title="Change Dashboard" />
      <div className="mt-3 row">
        {['draft', 'pending_risk', 'pending_technical_review', 'pending_approval',
          'approved_unscheduled', 'scheduled_7_days', 'scheduled_30_days',
          'in_progress', 'validation', 'pir_overdue', 'failed', 'rolled_back',
          'emergency', 'open_conflicts', 'critical_conflicts'].map(key => (
          <React.Fragment key={key}>
            {renderKPI(key, {
              draft: 'Draft',
              pending_risk: 'Pending Risk',
              pending_technical_review: 'Pending Technical Review',
              pending_approval: 'Pending Approval',
              approved_unscheduled: 'Approved Unscheduled',
              scheduled_7_days: 'Scheduled 7 Days',
              scheduled_30_days: 'Scheduled 30 Days',
              in_progress: 'In Progress',
              validation: 'Validation',
              pir_overdue: 'PIR Overdue',
              failed: 'Failed',
              rolled_back: 'Rolled Back',
              emergency: 'Emergency',
              open_conflicts: 'Open Conflicts',
              critical_conflicts: 'Critical Conflicts',
            }[key])}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}