/* 
 * Maintenance Windows - maintenance window management
 * Route: #/maintenance-windows
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Form, Input, Select } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError } from './changes-utils';

export function MaintenanceWindows() {
  const { isStaff, role } = useAuth();
  const [windows, setWindows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isStaff && role !== 'it_manager') {
      setWindows([]);
      setLoading(false);
      return;
    }
    fetchPage(`/maintenance-windows/`)
      .then((data) => {
        setWindows(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [isStaff, role]);

  if (loading) {
    return <div className="mt-3"><p>Loading maintenance windows…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  return (
    <div>
      <PageHeader title="Maintenance Windows" />
      <div className="mt-3">
        <p><strong>Total Windows:</strong> {windows.length}</p>
        {windows.length === 0 ? (
          <p>No maintenance windows found</p>
        ) : (
          <div>
            {windows.map((w, i) => (
              <div key={w.id || i} className="mt-3 p-2 border rounded">
                <Row>
                  <Col sm={6}><strong>Name:</strong> {w.name}</Col>
                  <Col sm={6}><strong>Code:</strong> {w.code}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}>
                    <strong>Description:</strong> {w.description}
                    <br />
                    <strong>Type:</strong> {w.type}
                  </Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Start:</strong> {w.start_at}</Col>
                  <Col sm={6}><strong>End:</strong> {w.end_at}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Timezone:</strong> {w.timezone}</Col>
                  <Col sm={6}><strong>Recurrence:</strong> {w.recurrence}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Department:</strong> {w.department}</Col>
                  <Col sm={6}><strong>Service:</strong> {w.service_catalogue_item}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Status:</strong> {w.status}</Col>
                  <Col sm={6}><strong>Max Parallel Changes:</strong> {w.maximum_parallel_changes}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}><strong>Blackout:</strong> {w.blackout}</Col>
                </Row>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}