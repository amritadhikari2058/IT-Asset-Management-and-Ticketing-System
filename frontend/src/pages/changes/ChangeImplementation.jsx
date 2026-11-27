/*
 * Change Implementation - implementation console for a change
 * Route: #/changes/:id/implementation
 *
 * Backend contract:
 * - ChangeRequest actions under /changes/{id}/ (start/fail/complete/rollback).
 * - ChangeImplementation CRUD under /changes/implementations/.
 * Task actions exist under /changes/tasks/, but the backend does not expose a
 * task-to-change field or a per-change filter, so they are not listed here.
 */

import React, { useEffect, useState } from 'react';
import api from '../../api';
import {
  Alert, Badge, Button, Col, Field, Form, Input, PageHeader, Row, Select, Textarea,
} from '../../components';
import { useAuth } from '../../auth';
import { fieldMsg } from '../../api-utils';
import {
  fetchPage, parseApiError, formatDateTime, STATUS_LABELS,
} from '../../shared/changes-utils';

const IMPLEMENTATION_STATUSES = [
  ['in_progress', 'In Progress'],
  ['validation', 'Validation'],
  ['succeeded', 'Succeeded'],
  ['failed', 'Failed'],
  ['rolled_back', 'Rolled Back'],
  ['partially_successful', 'Partially Successful'],
];

const IMPLEMENTATION_OUTCOMES = [
  ['', 'Not recorded'],
  ['successful', 'Successful'],
  ['successful_with_issues', 'Successful with Issues'],
  ['failed', 'Failed'],
  ['rolled_back', 'Rolled Back'],
  ['partial', 'Partial'],
  ['cancelled', 'Cancelled'],
];

// Statuses are the ones enforced by the backend services, not the stale
// labels in the shared actionAvailability helper.
const ACTIONS = {
  start_implementation: {
    label: 'Start Implementation',
    statuses: ['scheduled'],
    body: () => ({}),
  },
  begin_validation: {
    label: 'Begin Validation',
    statuses: ['in_progress'],
    body: () => ({}),
  },
  complete: {
    label: 'Complete',
    statuses: ['in_progress', 'validation'],
  },
  fail: {
    label: 'Fail Implementation',
    statuses: ['in_progress', 'validation'],
  },
  start_rollback: {
    label: 'Start Rollback',
    statuses: ['failed'],
    body: () => ({}),
  },
  complete_rollback: {
    label: 'Complete Rollback',
    statuses: ['rolled_back'],
    body: () => ({}),
  },
};

const EMPTY_RECORD = {
  status: 'in_progress',
  outcome: '',
  implementation_notes: '',
  validation_result: '',
  rollback_required: false,
  actual_downtime_minutes: '',
};

function recordToForm(record) {
  if (!record) return { ...EMPTY_RECORD };
  return {
    status: record.status || 'in_progress',
    outcome: record.outcome || '',
    implementation_notes: record.implementation_notes || '',
    validation_result: record.validation_result || '',
    rollback_required: Boolean(record.rollback_required),
    actual_downtime_minutes:
      record.actual_downtime_minutes === null || record.actual_downtime_minutes === undefined
        ? ''
        : String(record.actual_downtime_minutes),
  };
}

function findImplementation(items, changeId) {
  return (items || []).find(
    (item) => String(item.change) === String(changeId)
      || String(item.change?.id) === String(changeId),
  ) || null;
}

export function ChangeImplementation({ match }) {
  const auth = useAuth() || {};
  const { isStaff, isManagerOrAdmin } = auth;
  const canManage = Boolean(isManagerOrAdmin);
  const canViewRecord = Boolean(isStaff);
  const id = match?.params?.id;

  const [change, setChange] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [implementation, setImplementation] = useState(null);
  const [recordForm, setRecordForm] = useState({ ...EMPTY_RECORD });
  const [actionForm, setActionForm] = useState({
    implementation_notes: '',
    validation_passed: true,
    failure_reason: '',
  });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [actionErrors, setActionErrors] = useState({});
  const [recordErrors, setRecordErrors] = useState({});
  const [busy, setBusy] = useState('');
  const [now, setNow] = useState(Date.now());

  const loadData = async () => {
    if (!id) {
      setLoading(false);
      return;
    }
    setLoadError('');
    try {
      const requests = [
        api.get(`/changes/${id}/`),
        api.get(`/changes/${id}/readiness/`),
      ];
      if (canViewRecord) requests.push(fetchPage('/changes/implementations/'));

      const [changeResponse, readinessResponse, implementationData] = await Promise.all(requests);
      const found = canViewRecord
        ? findImplementation(implementationData?.items, id)
        : null;

      setChange(changeResponse.data);
      setReadiness(readinessResponse.data);
      setImplementation(found);
      setRecordForm(recordToForm(found));
    } catch (e) {
      const parsed = parseApiError(e);
      setLoadError(parsed.global || 'Could not load implementation details.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    // Reload if the viewing role changes (different data visibility).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, canViewRecord]);

  useEffect(() => {
    if (!change?.actual_start) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 60000);
    return () => clearInterval(timer);
  }, [change?.actual_start]);

  const clearMessages = () => {
    setError('');
    setSuccess('');
    setActionErrors({});
    setRecordErrors({});
  };

  const showError = (e, fallback, target = 'action') => {
    const parsed = parseApiError(e);
    setError(parsed.global || Object.values(parsed.fields || {}).join(' ') || fallback);
    if (target === 'record') setRecordErrors(parsed.fields || {});
    else setActionErrors(parsed.fields || {});
  };

  const runAction = async (key) => {
    const action = ACTIONS[key];
    if (!canManage || !action || !change || !action.statuses.includes(change.status)) return;
    clearMessages();

    let body = action.body ? action.body() : {};
    if (key === 'complete') {
      const notes = actionForm.implementation_notes.trim();
      if (!notes) {
        setActionErrors({
          implementation_notes: 'Implementation notes are required to complete an implementation.',
        });
        return;
      }
      body = {
        validation_passed: Boolean(actionForm.validation_passed),
        implementation_notes: notes,
      };
    }
    if (key === 'fail') {
      const reason = actionForm.failure_reason.trim();
      if (!reason) {
        setActionErrors({ failure_reason: 'A failure reason is required.' });
        return;
      }
      body = { failure_reason: reason };
    }

    setBusy(key);
    try {
      await api.post(`/changes/${id}/${key}/`, body);
      setSuccess(`${action.label} recorded.`);
      await loadData();
    } catch (e) {
      showError(e, `Could not ${action.label.toLowerCase()}.`);
    } finally {
      setBusy('');
    }
  };

  const saveRecord = async () => {
    if (!canManage) return;
    clearMessages();

    const minutes = recordForm.actual_downtime_minutes;
    if (minutes !== '' && (!/^\d+$/.test(String(minutes)) || Number(minutes) < 0)) {
      setRecordErrors({
        actual_downtime_minutes: 'Enter a non-negative whole number of minutes.',
      });
      return;
    }

    const payload = {
      status: recordForm.status,
      outcome: recordForm.outcome,
      implementation_notes: recordForm.implementation_notes,
      validation_result: recordForm.validation_result,
      rollback_required: Boolean(recordForm.rollback_required),
      actual_downtime_minutes: minutes === '' ? null : Number(minutes),
    };

    setBusy('record');
    try {
      if (implementation?.id) {
        await api.patch(`/changes/implementations/${implementation.id}/`, payload);
      } else {
        await api.post('/changes/implementations/', { change: Number(id), ...payload });
      }
      setSuccess('Implementation record saved.');
      await loadData();
    } catch (e) {
      showError(e, 'Could not save the implementation record.', 'record');
    } finally {
      setBusy('');
    }
  };

  if (loading) {
    return <div className="mt-3"><p>Loading implementation…</p></div>;
  }

  if (loadError) {
    return (
      <div className="mt-3">
        <Alert variant="danger">{loadError}</Alert>
        <Button onClick={loadData}>Retry</Button>
      </div>
    );
  }

  if (!change) {
    return <div className="mt-3"><p>Change not found</p></div>;
  }

  const elapsed = change.actual_start
    ? Math.max(0, Math.floor((now - new Date(change.actual_start).getTime()) / 60000))
    : null;
  const availableActions = Object.entries(ACTIONS).filter(
    ([, action]) => action.statuses.includes(change.status),
  );

  return (
    <div>
      <PageHeader title="Implementation" sub={change.change_number} />
      <div className="mt-3">
        {error ? <Alert variant="danger">{error}</Alert> : null}
        {success ? <Alert variant="success">{success}</Alert> : null}

        <p><strong>Change Number:</strong> {change.change_number}</p>
        <p><strong>Title:</strong> {change.title}</p>
        <hr />

        <div className="mt-3">
          <h4>Change Status</h4>
          <Badge
            kind="status"
            value={change.status}
            label={STATUS_LABELS[change.status] || change.status || 'Draft'}
          />
        </div>

        <div className="mt-3">
          <h4>Timing</h4>
          <p><strong>Planned Window:</strong> {formatDateTime(change.planned_start) || '—'}</p>
          <p><strong>Actual Start:</strong> {formatDateTime(change.actual_start) || 'Not started'}</p>
          <p><strong>Actual End:</strong> {formatDateTime(change.actual_end) || '—'}</p>
          <p><strong>Elapsed:</strong> {elapsed === null ? '—' : `${elapsed} minutes`}</p>
        </div>

        <div className="mt-3">
          <h4>Plan</h4>
          <p><strong>Implementation Plan:</strong> {change.implementation_plan || '—'}</p>
          <p><strong>Validation Plan:</strong> {change.validation_plan || '—'}</p>
          <p><strong>Rollback Plan:</strong> {change.rollback_plan || '—'}</p>
        </div>

        {readiness && Array.isArray(readiness.blockers) && readiness.blockers.length > 0 ? (
          <div className="mt-3">
            <h4>Readiness Blockers</h4>
            <ul>
              {readiness.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
            </ul>
          </div>
        ) : null}

        <div className="mt-3">
          <h4>Implementation Record</h4>
          {implementation ? (
            <div>
              <p><strong>Record:</strong> #{implementation.id}</p>
              <p><strong>Status:</strong> {implementation.status || '—'}</p>
              <p><strong>Outcome:</strong> {implementation.outcome || 'Not recorded'}</p>
              <p><strong>Notes:</strong> {implementation.implementation_notes || '—'}</p>
              <p><strong>Validation Result:</strong> {implementation.validation_result || '—'}</p>
              <p><strong>Actual Downtime:</strong> {implementation.actual_downtime_minutes ?? '—'} minutes</p>
              <p><strong>Rollback Required:</strong> {implementation.rollback_required ? 'Yes' : 'No'}</p>
            </div>
          ) : (
            <p className="text-muted">No implementation record has been created for this change.</p>
          )}
        </div>

        {canManage ? (
          <Form>
            <h4 className="mt-3">Record Progress</h4>
            <Row>
              <Col sm={4}>
                <Field label="Status" error={fieldMsg(recordErrors, 'status')}>
                  <Select
                    value={recordForm.status}
                    onChange={(e) => setRecordForm((f) => ({ ...f, status: e.target.value }))}
                  >
                    {IMPLEMENTATION_STATUSES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
              </Col>
              <Col sm={4}>
                <Field label="Outcome" error={fieldMsg(recordErrors, 'outcome')}>
                  <Select
                    value={recordForm.outcome}
                    onChange={(e) => setRecordForm((f) => ({ ...f, outcome: e.target.value }))}
                  >
                    {IMPLEMENTATION_OUTCOMES.map(([value, label]) => (
                      <option key={value || 'none'} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
              </Col>
              <Col sm={4}>
                <Field
                  label="Actual downtime (minutes)"
                  error={fieldMsg(recordErrors, 'actual_downtime_minutes')}
                >
                  <Input
                    type="number"
                    min="0"
                    value={recordForm.actual_downtime_minutes}
                    onChange={(e) => setRecordForm((f) => ({
                      ...f,
                      actual_downtime_minutes: e.target.value,
                    }))}
                  />
                </Field>
              </Col>
            </Row>
            <Field
              label="Implementation notes"
              error={fieldMsg(recordErrors, 'implementation_notes')}
            >
              <Textarea
                rows={3}
                value={recordForm.implementation_notes}
                onChange={(e) => setRecordForm((f) => ({
                  ...f,
                  implementation_notes: e.target.value,
                }))}
              />
            </Field>
            <Field
              label="Validation result"
              error={fieldMsg(recordErrors, 'validation_result')}
            >
              <Textarea
                rows={3}
                value={recordForm.validation_result}
                onChange={(e) => setRecordForm((f) => ({
                  ...f,
                  validation_result: e.target.value,
                }))}
              />
            </Field>
            <Field label="Rollback required" error={fieldMsg(recordErrors, 'rollback_required')}>
              <Input
                type="checkbox"
                checked={recordForm.rollback_required}
                onChange={(e) => setRecordForm((f) => ({
                  ...f,
                  rollback_required: e.target.checked,
                }))}
              />
            </Field>
            <div className="mt-3">
              <Button onClick={saveRecord} disabled={busy === 'record'}>
                {implementation ? 'Save Progress' : 'Create Implementation Record'}
              </Button>
            </div>

            <h4 className="mt-3">Implementation Actions</h4>
            <Field
              label="Completion notes"
              error={fieldMsg(actionErrors, 'implementation_notes')}
              hint="Required when completing an implementation."
            >
              <Textarea
                rows={3}
                value={actionForm.implementation_notes}
                onChange={(e) => setActionForm((f) => ({
                  ...f,
                  implementation_notes: e.target.value,
                }))}
              />
            </Field>
            <Field label="Validation passed" error={fieldMsg(actionErrors, 'validation_passed')}>
              <Input
                type="checkbox"
                checked={actionForm.validation_passed}
                onChange={(e) => setActionForm((f) => ({
                  ...f,
                  validation_passed: e.target.checked,
                }))}
              />
            </Field>
            <Field
              label="Failure reason"
              error={fieldMsg(actionErrors, 'failure_reason')}
              hint="Required when failing an implementation."
            >
              <Textarea
                rows={3}
                value={actionForm.failure_reason}
                onChange={(e) => setActionForm((f) => ({
                  ...f,
                  failure_reason: e.target.value,
                }))}
              />
            </Field>
            <div className="mt-3 row-gap">
              {availableActions.length === 0 ? (
                <p className="text-muted">No implementation actions are available for this status.</p>
              ) : availableActions.map(([key, action]) => (
                <Button
                  key={key}
                  kind={key === 'fail' ? 'danger' : 'primary'}
                  onClick={() => runAction(key)}
                  disabled={Boolean(busy)}
                >
                  {action.label}
                </Button>
              ))}
            </div>
          </Form>
        ) : (
          <p className="text-muted small">
            Implementation actions available to IT managers and System Admins only
          </p>
        )}
      </div>
    </div>
  );
}
