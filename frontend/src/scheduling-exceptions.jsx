/*
 * Scheduling Exceptions - exception request and decision workflow
 * Route: #/scheduling-exceptions
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Row, Col, Badge, Button, Field } from './components';
import { useAuth } from './auth';
import api from './api';
import { fetchPage, parseApiError } from './changes-utils';
import { formatDateTime } from './changes-utils';

export function SchedulingExceptions() {
  const { isManagerOrAdmin, role, user } = useAuth();
  const [exceptions, setExceptions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState('');
  const [creating, setCreating] = useState(false);
  const [newEx, setNewEx] = useState({
    change: '',
    justification: '',
    blackout_period: '',
    maintenance_window: '',
  });
  const [newExErrors, setNewExErrors] = useState({});

  useEffect(() => {
    if (!isManagerOrAdmin && role !== 'employee') {
      setExceptions([]);
      setLoading(false);
      return;
    }
    fetchPage(`/changes/scheduling-exceptions/`)
      .then((data) => {
        setExceptions(data.items ?? data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [isManagerOrAdmin, role]);

  const handleNewExChange = (e) => {
    setNewEx({ ...newEx, [e.target.name]: e.target.value });
  };

  const createException = async (e) => {
    e.preventDefault();
    if (creating) return; // duplicate-submit prevention
    setNewExErrors({});
    // Required-field validation
    const errors = {};
    if (!String(newEx.change || '').trim()) errors.change = 'Change is required.';
    if (!String(newEx.justification || '').trim()) errors.justification = 'Justification is required.';
    if (Object.keys(errors).length) {
      setNewExErrors(errors);
      setMsg('Please fix the highlighted fields.');
      return;
    }
    setCreating(true);
    try {
      // Normalize references to backend PKs (empty -> null)
      const payload = {
        change: parseInt(newEx.change, 10),
        justification: String(newEx.justification).trim(),
        blackout_period: newEx.blackout_period ? parseInt(newEx.blackout_period, 10) : null,
        maintenance_window: newEx.maintenance_window ? parseInt(newEx.maintenance_window, 10) : null,
      };
      const response = await api.post('/changes/scheduling-exceptions/', payload);
      setMsg('Scheduling exception request submitted.');
      setExceptions([response.data, ...exceptions]);
      setNewEx({ change: '', justification: '', blackout_period: '', maintenance_window: '' });
      setCreating(false);
    } catch (err) {
      const parsed = parseApiError(err);
      setNewExErrors(parsed.fields);
      setMsg(parsed.global || 'Failed to submit exception request.');
    } finally {
      setCreating(false);
    }
  };

  const decideException = async (ex, status) => {
    if (!confirm(`${status.charAt(0).toUpperCase() + status.slice(1)} this scheduling exception?`)) return;
    try {
      const res = await api.patch(`/changes/scheduling-exceptions/${ex.id}/`, { status });
      setMsg(`Exception ${status}.`);
      const updated = exceptions.map((x) => x.id === ex.id ? { ...x, ...res.data, status } : x);
      setExceptions(updated);
    } catch (err) {
      const parsed = parseApiError(err);
      setMsg(parsed.global || `Failed to ${status} exception.`);
    }
  };

  if (loading) return <div className="mt-3"><p>Loading scheduling exceptions…</p></div>;
  if (error) return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;

  const msgEl = msg ? <div className="success-summary" role="status">{msg}</div> : null;

  const pendingExceptions = exceptions.filter((e) => e.status === 'pending');
  const approvedExceptions = exceptions.filter((e) => e.status === 'approved');
  const rejectedExceptions = exceptions.filter((e) => e.status === 'rejected');

  return (
    <div>
      <PageHeader title="Scheduling Exceptions" />
      {msgEl}

      {!isManagerOrAdmin && role === 'employee' && (
        <div className="mt-4">
          <h3>Request Scheduling Exception</h3>
          <form onSubmit={createException} className="mt-2">
            <Row className="mt-2">
              <Col sm={6}>
                <Field label="Change" name="change" required>
                  <input className="form-control" name="change" value={newEx.change} onChange={handleNewExChange} />
                </Field>
              </Col>
              <Col sm={6}>
                <Field label="Maintenance Window" name="maintenance_window">
                  <input className="form-control" name="maintenance_window" value={newEx.maintenance_window} onChange={handleNewExChange} />
                </Field>
              </Col>
            </Row>
            <Row className="mt-2">
              <Col sm={6}>
                <Field label="Blackout Period" name="blackout_period">
                  <input className="form-control" name="blackout_period" value={newEx.blackout_period} onChange={handleNewExChange} />
                </Field>
              </Col>
              <Col sm={6}>
                <Field label="Justification" name="justification" required>
                  <input className="form-control" name="justification" value={newEx.justification} onChange={handleNewExChange} />
                </Field>
              </Col>
            </Row>
            {newExErrors.justification && <p className="text-danger">{newExErrors.justification}</p>}
            {newExErrors.change && <p className="text-danger">{newExErrors.change}</p>}
            {newExErrors.blackout_period && <p className="text-danger">{newExErrors.blackout_period}</p>}
            {newExErrors.maintenance_window && <p className="text-danger">{newExErrors.maintenance_window}</p>}
            <Button kind="primary" type="submit" disabled={creating}>{creating ? 'Submitting…' : 'Submit Exception Request'}</Button>
            {creating && <span className="ml-2">Submitting…</span>}
          </form>
        </div>
      )}

      <div className="mt-4">
        <h3>Pending Exception Requests</h3>
        {pendingExceptions.length === 0 ? <p>No pending exceptions</p> : (
          <div>
            {pendingExceptions.map((ex) => (
              <div key={ex.id} className="mt-2 p-2 border rounded">
                <Row>
                  <Col sm={6}><strong>Change:</strong> {ex.change}</Col>
                  <Col sm={6}><strong>Requested by:</strong> {ex.requesting_user_email ?? ex.requesting_user}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}><strong>Justification:</strong> {ex.justification}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Blackout Period:</strong> {ex.blackout_period ?? '—'}</Col>
                  <Col sm={6}><strong>Maintenance Window:</strong> {ex.maintenance_window ?? '—'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}>
                    {isManagerOrAdmin && !(ex.requesting_user_email && user && ex.requesting_user_email === user.email) && (
                      <>
                        <Button variant="success" onClick={() => decideException(ex, 'approved')} className="me-2">Approve</Button>
                        <Button variant="danger" onClick={() => decideException(ex, 'rejected')}>Reject</Button>
                      </>
                    )}
                  </Col>
                </Row>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4">
        <h3>Approved Exceptions</h3>
        {approvedExceptions.length === 0 ? <p>No approved exceptions</p> : (
          <div>
            {approvedExceptions.map((ex) => (
              <div key={ex.id} className="mt-2 p-2 border rounded bg-success bg-opacity-10">
                <Row>
                  <Col sm={4}><strong>Change:</strong> {ex.change}</Col>
                  <Col sm={4}><strong>Requested by:</strong> {ex.requesting_user_email ?? ex.requesting_user}</Col>
                  <Col sm={4}><strong>Decided by:</strong> {ex.decided_by_email ?? ex.decided_by ?? '—'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Decision:</strong> <Badge kind="status" value="approved" /></Col>
                  <Col sm={6}><strong>Decision time:</strong> {ex.decision_timestamp ? formatDateTime(ex.decision_timestamp) : '—'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}><strong>Justification:</strong> {ex.justification}</Col>
                </Row>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4">
        <h3>Rejected Exceptions</h3>
        {rejectedExceptions.length === 0 ? <p>No rejected exceptions</p> : (
          <div>
            {rejectedExceptions.map((ex) => (
              <div key={ex.id} className="mt-2 p-2 border rounded bg-danger bg-opacity-10">
                <Row>
                  <Col sm={4}><strong>Change:</strong> {ex.change}</Col>
                  <Col sm={4}><strong>Requested by:</strong> {ex.requesting_user_email ?? ex.requesting_user}</Col>
                  <Col sm={4}><strong>Decided by:</strong> {ex.decided_by_email ?? ex.decided_by ?? '—'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Decision:</strong> <Badge kind="status" value="rejected" /></Col>
                  <Col sm={6}><strong>Decision time:</strong> {ex.decision_timestamp ? formatDateTime(ex.decision_timestamp) : '—'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}><strong>Justification:</strong> {ex.justification}</Col>
                </Row>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}