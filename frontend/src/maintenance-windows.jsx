/*
 * Maintenance Windows - maintenance window management
 * Route: #/maintenance-windows
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Row, Col, Badge, Button } from './components';
import { useAuth } from './auth';
import api from './api';
import { fetchPage, parseApiError } from './changes-utils';
import { formatDateTime } from './changes-utils';

const WINDOW_TYPE_LABELS = {
  scheduled: 'Scheduled',
  emergency: 'Emergency',
};

export function MaintenanceWindows() {
  const { isManagerOrAdmin } = useAuth();
  const [windows, setWindows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    if (!isManagerOrAdmin) {
      setWindows([]);
      setLoading(false);
      return;
    }
    fetchPage(`/changes/maintenance-windows/`)
      .then((data) => {
        setWindows(data.items ?? data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [isManagerOrAdmin]);

  const toggleStatus = async (w) => {
    if (saving) return;
    if (!confirm(`${w.status === 'active' ? 'Deactivate' : 'Reactivate'} maintenance window "${w.name}"?`)) return;
    setSaving(true);
    try {
      await api.patch(`/changes/maintenance-windows/${w.id}/`, { status: w.status === 'active' ? 'inactive' : 'active' });
      setMsg(`Maintenance window "${w.name}" ${w.status === 'active' ? 'deactivated' : 'reactivated'}.`);
      const updated = windows.map((x) => x.id === w.id ? { ...x, status: w.status === 'active' ? 'inactive' : 'active' } : x);
      setWindows(updated);
    } catch (e) {
      setError(parseApiError(e));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="mt-3"><p>Loading maintenance windows…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  const msgEl = msg ? <div className="success-summary" role="status">{msg}</div> : null;

  return (
    <div>
      <PageHeader title="Maintenance Windows" />
      {msgEl}
      <div className="mt-3">
        <p><strong>Total Windows:</strong> {windows.length}</p>
        {windows.length === 0 ? (
          <p>No maintenance windows found</p>
        ) : (
          <div>
            {windows.map((w) => (
              <div key={w.id} className="mt-3 p-2 border rounded">
                <Row>
                  <Col sm={6}><strong>Name:</strong> {w.name}</Col>
                  <Col sm={6}><strong>Code:</strong> {w.code}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}><strong>Description:</strong> {w.description}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Type:</strong> {WINDOW_TYPE_LABELS[w.window_type] ?? w.window_type}</Col>
                  <Col sm={6}><strong>Status:</strong> <Badge kind="status" value={w.status} /></Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Start:</strong> {formatDateTime(w.start_at)}</Col>
                  <Col sm={6}><strong>End:</strong> {formatDateTime(w.end_at)}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Timezone:</strong> {w.timezone_name ?? 'UTC'}</Col>
                  <Col sm={6}><strong>Recurrence:</strong> {w.recurrence_rule ?? 'None'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Department:</strong> {w.department ?? '—'}</Col>
                  <Col sm={6}><strong>Service:</strong> {w.service ?? '—'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Max Parallel Changes:</strong> {w.maximum_parallel_changes ?? 1}</Col>
                  <Col sm={6}><strong>Blackout:</strong> {w.blackout ? 'Yes' : 'No'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}>
                    {isManagerOrAdmin && (
                      <Button variant={w.status === 'active' ? 'danger' : 'success'} onClick={() => toggleStatus(w)} disabled={saving}>
                        {w.status === 'active' ? 'Deactivate' : 'Reactivate'}
                      </Button>
                    )}
                  </Col>
                </Row>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}