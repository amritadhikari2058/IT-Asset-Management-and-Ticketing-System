/* 
 * Change Reports - change reports
 * Route: #/changes/reports
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Card } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError } from './changes-utils';

export function ChangeReports() {
  const { isStaff, role } = useAuth();
  const [reports, setReports] = useState({
    success_rate: 0,
    emergency_rate: 0,
    failures: 0,
    downtime: 0,
    risk: 0,
    conflicts: 0,
    pir: 0,
    by_service: [],
    by_asset: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isStaff && role !== 'it_manager') {
      setReports({
        success_rate: 0, emergency_rate: 0, failures: 0, downtime: 0,
        risk: 0, conflicts: 0, pir: 0, by_service: [], by_asset: [],
      });
      setLoading(false);
      return;
    }
    fetchPage(`/changes/reports/`)
      .then((data) => {
        setReports(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [isStaff, role]);

  if (loading) {
    return <div className="mt-3"><p>Loading reports…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  return (
    <div>
      <PageHeader title="Change Reports" />
      <div className="mt-3 row">
        <div className="col-md-4">
          <Card>
            <Card.Body>
              <Card.Title>Success Rate</Card.Title>
              <Card.Text>{reports.success_rate}%</Card.Text>
            </Card.Body>
          </Card>
        </div>
        <div className="col-md-4">
          <Card>
            <Card.Body>
              <Card.Title>Emergency Rate</Card.Title>
              <Card.Text>{reports.emergency_rate}%</Card.Text>
            </Card.Body>
          </Card>
        </div>
        <div className="col-md-4">
          <Card>
            <Card.Body>
              <Card.Title>Failures</Card.Title>
              <Card.Text>{reports.failures}</Card.Text>
            </Card.Body>
          </Card>
        </div>
      </div>
      <div className="mt-3 row">
        <div className="col-md-6">
          <Card>
            <Card.Body>
              <Card.Title>Total Downtime</Card.Title>
              <Card.Text>{reports.downtime} minutes</Card.Text>
            </Card.Body>
          </Card>
        </div>
        <div className="col-md-6">
          <Card>
            <Card.Body>
              <Card.Title>Risk</Card.Title>
              <Card.Text>{reports.risk}</Card.Text>
            </Card.Body>
          </Card>
        </div>
      </div>
      <div className="mt-3 row">
        <div className="col-md-6">
          <Card>
            <Card.Body>
              <Card.Title>Open Conflicts</Card.Title>
              <Card.Text>{reports.conflicts}</Card.Text>
            </Card.Body>
          </Card>
        </div>
        <div className="col-md-6">
          <Card>
            <Card.Body>
              <Card.Title>PIR</Card.Title>
              <Card.Text>{reports.pir}</Card.Text>
            </Card.Body>
          </Card>
        </div>
      </div>
      <div className="mt-3 row">
        <div className="col-md-6">
          <Card>
            <Card.Body>
              <Card.Title>By Service</Card.Title>
              <Card.Text>{JSON.stringify(reports.by_service)}</Card.Text>
            </Card.Body>
          </Card>
        </div>
        <div className="col-md-6">
          <Card>
            <Card.Body>
              <Card.Title>By Asset</Card.Title>
              <Card.Text>{JSON.stringify(reports.by_asset)}</Card.Text>
            </Card.Body>
          </Card>
        </div>
      </div>
    </div>
  );
}