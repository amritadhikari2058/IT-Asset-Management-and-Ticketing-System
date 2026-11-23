/*
 * Blackout Periods - blackout period management
 * Route: #/blackout-periods
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Row, Col, Badge, Button } from './components';
import { useAuth } from './auth';
import api from './api';
import { fetchPage, parseApiError } from './changes-utils';
import { formatDateTime } from './changes-utils';

const PERIOD_TYPE_LABELS = {
  financial: 'Financial Closing',
  critical: 'Critical Business Period',
  freeze: 'Organization-wide Freeze',
  infrastructure: 'Infrastructure Freeze',
};

export function BlackoutPeriods() {
  const { isManagerOrAdmin } = useAuth();
  const [periods, setPeriods] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    if (!isManagerOrAdmin) {
      setPeriods([]); // eslint-disable-line react/set-state-in-effect
      setLoading(false); // eslint-disable-line react/set-state-in-effect
      return;
    }
    fetchPage(`/blackout-periods/`)
      .then((data) => {
        setPeriods(data.items ?? data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [isManagerOrAdmin]);

  const toggleStatus = async (p) => {
    if (saving) return;
    if (!confirm(`${p.status === 'active' ? 'Deactivate' : 'Reactivate'} blackout period "${p.name}"?`)) return;
    setSaving(true);
    try {
      await api.patch(`/blackout-periods/${p.id}/`, { status: p.status === 'active' ? 'inactive' : 'active' });
      setMsg(`Blackout period "${p.name}" ${p.status === 'active' ? 'deactivated' : 'reactivated'}.`);
      const updated = periods.map((x) => x.id === p.id ? { ...x, status: p.status === 'active' ? 'inactive' : 'active' } : x);
      setPeriods(updated);
    } catch (e) {
      setError(parseApiError(e));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="mt-3"><p>Loading blackout periods…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  const msgEl = msg ? <div className="success-summary" role="status">{msg}</div> : null;

  return (
    <div>
      <PageHeader title="Blackout Periods" />
      {msgEl}
      <div className="mt-3">
        <p><strong>Total Blackout Periods:</strong> {periods.length}</p>
        {periods.length === 0 ? (
          <p>No blackout periods found</p>
        ) : (
          <div>
            {periods.map((p) => (
              <div key={p.id} className="mt-3 p-2 border rounded">
                <Row>
                  <Col sm={6}><strong>Name:</strong> {p.name}</Col>
                  <Col sm={6}><strong>Code:</strong> {p.code}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Type:</strong> {PERIOD_TYPE_LABELS[p.period_type] ?? p.period_type}</Col>
                  <Col sm={6}><strong>Status:</strong> <Badge kind="status" value={p.status} /></Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Start:</strong> {formatDateTime(p.start_at)}</Col>
                  <Col sm={6}><strong>End:</strong> {formatDateTime(p.end_at)}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}><strong>Description:</strong> {p.description}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Department:</strong> {p.scope_department ?? '—'}</Col>
                  <Col sm={6}><strong>Service:</strong> {p.scope_service ?? '—'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}>
                    {isManagerOrAdmin && (
                      <Button variant={p.status === 'active' ? 'danger' : 'success'} onClick={() => toggleStatus(p)} disabled={saving}>
                        {p.status === 'active' ? 'Deactivate' : 'Reactivate'}
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