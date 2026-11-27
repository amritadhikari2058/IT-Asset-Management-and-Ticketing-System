/*
 * Change PIR - Post-Implementation Review
 * Route: #/changes/:id/pir
 *
 * Backend contract:
 * - PIR CRUD: /changes/post-implementation-reviews/ (ModelViewSet). The list
 *   endpoint supports `?change=<id>`, so only this change's PIR is fetched.
 * - PIR completion: /changes/post-implementation-reviews/{id}/complete/.
 * - Change lifecycle: /changes/{id}/request_pir/ and /changes/{id}/close/.
 * - The serializer exposes `status` read-only; there is no waive action.
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, Badge, Button, Col, Field, Form, Input, PageHeader, Row, Select, Textarea,
} from '../../components';
import { useAuth } from '../../auth';
import api from '../../api';
import { fieldMsg } from '../../api-utils';
import {
  fetchPage, parseApiError, formatDateTime, STATUS_LABELS,
} from '../../shared/changes-utils';

const OUTCOME_CHOICES = [
  ['', 'Not recorded'],
  ['successful', 'Successful'],
  ['successful_with_issues', 'Successful with Issues'],
  ['failed', 'Failed'],
  ['rolled_back', 'Rolled Back'],
  ['inconclusive', 'Inconclusive'],
];
const OUTCOME_VALUES = OUTCOME_CHOICES.map(([value]) => value).filter(Boolean);

const EMPTY_FORM = {
  outcome: '',
  objectives_met: '',
  validation_successful: false,
  unexpected_impact: '',
  downtime_within_estimate: false,
  rollback_used: false,
  incident_created: false,
  lessons_learned: '',
  follow_up_actions: '',
  scheduled_for: '',
  completed_at: '',
  knowledge_article: '',
  reviewed_by: '',
};

function toLocalInput(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    + `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toIsoOrNull(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function recordToForm(pir) {
  if (!pir) return { ...EMPTY_FORM };
  return {
    outcome: pir.outcome || '',
    objectives_met: pir.objectives_met || '',
    validation_successful: Boolean(pir.validation_successful),
    unexpected_impact: pir.unexpected_impact || '',
    downtime_within_estimate: Boolean(pir.downtime_within_estimate),
    rollback_used: Boolean(pir.rollback_used),
    incident_created: Boolean(pir.incident_created),
    lessons_learned: pir.lessons_learned || '',
    follow_up_actions: pir.follow_up_actions || '',
    scheduled_for: toLocalInput(pir.scheduled_for),
    completed_at: toLocalInput(pir.completed_at),
    knowledge_article: pir.knowledge_article == null ? '' : String(pir.knowledge_article),
    reviewed_by: pir.reviewed_by == null ? '' : String(pir.reviewed_by),
  };
}

function buildPayload(form) {
  return {
    outcome: form.outcome,
    objectives_met: form.objectives_met,
    validation_successful: Boolean(form.validation_successful),
    unexpected_impact: form.unexpected_impact,
    downtime_within_estimate: Boolean(form.downtime_within_estimate),
    rollback_used: Boolean(form.rollback_used),
    incident_created: Boolean(form.incident_created),
    lessons_learned: form.lessons_learned,
    follow_up_actions: form.follow_up_actions,
    scheduled_for: toIsoOrNull(form.scheduled_for),
    completed_at: toIsoOrNull(form.completed_at),
    knowledge_article: form.knowledge_article === '' ? null : Number(form.knowledge_article),
    reviewed_by: form.reviewed_by === '' ? null : Number(form.reviewed_by),
  };
}

function validateForm(form) {
  const errors = {};
  ['knowledge_article', 'reviewed_by'].forEach((key) => {
    const value = form[key];
    if (value !== '' && (!/^\d+$/.test(String(value)) || Number(value) < 1)) {
      errors[key] = 'Enter a valid record id.';
    }
  });
  return errors;
}

function validateOutcome(value) {
  return value && OUTCOME_VALUES.includes(value)
    ? ''
    : 'Select a valid outcome before completing the PIR.';
}

export function ChangePIR({ match }) {
  const auth = useAuth() || {};
  const canManage = Boolean(auth.isManagerOrAdmin);
  // Read access is separate from mutation access: the backend scopes employee
  // PIRs through their own changes and allows IT staff to read them.
  const canView = Boolean(auth.isStaff || auth.isEmployee);
  const id = match?.params?.id;
  const changeId = Number(id);

  const [change, setChange] = useState(null);
  const [pir, setPIR] = useState(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [closureSummary, setClosureSummary] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});
  const [busy, setBusy] = useState('');

  const loadData = useCallback(async () => {
    if (!id) {
      setLoading(false);
      return;
    }
    setLoadError('');
    try {
      const response = await api.get(`/changes/${id}/`);
      setChange(response.data);
      if (canView) {
        const page = await fetchPage(
          `/changes/post-implementation-reviews/?change=${changeId}`,
        );
        const found = (page.items || [])[0] || null;
        setPIR(found);
        setForm(recordToForm(found));
      }
    } catch (e) {
      setLoadError(parseApiError(e).global || 'Could not load PIR details.');
    } finally {
      setLoading(false);
    }
  }, [id, canView, changeId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const clearMessages = () => {
    setError('');
    setSuccess('');
    setFieldErrors({});
  };

  const showError = (e, fallback) => {
    const parsed = parseApiError(e);
    setError(parsed.global || Object.values(parsed.fields || {}).join(' ') || fallback);
    setFieldErrors(parsed.fields || {});
  };

  const setField = (key, value) => setForm((current) => ({ ...current, [key]: value }));

  const savePIR = async () => {
    if (!canManage || !changeId || busy) return;
    clearMessages();
    const idErrors = validateForm(form);
    if (Object.keys(idErrors).length > 0) {
      setFieldErrors(idErrors);
      return;
    }

    setBusy('save');
    try {
      if (pir?.id) {
        await api.patch(`/changes/post-implementation-reviews/${pir.id}/`, buildPayload(form));
        setSuccess('PIR updated.');
      } else {
        await api.post('/changes/post-implementation-reviews/', {
          change: changeId,
          ...buildPayload(form),
        });
        setSuccess('PIR created.');
      }
      await loadData();
    } catch (e) {
      showError(e, 'Could not save the PIR.');
    } finally {
      setBusy('');
    }
  };

  const completePIR = async () => {
    if (!canManage || !pir?.id || busy) return;
    clearMessages();

    const outcomeError = validateOutcome(form.outcome);
    if (outcomeError) {
      setFieldErrors({ outcome: outcomeError });
      return;
    }
    // The completion action takes no body, so it validates the persisted PIR.
    const savedOutcomeError = validateOutcome(pir.outcome);
    if (savedOutcomeError) {
      setFieldErrors({ outcome: 'Save a valid outcome before completing the PIR.' });
      return;
    }

    setBusy('complete');
    try {
      const response = await api.post(
        `/changes/post-implementation-reviews/${pir.id}/complete/`,
        {},
      );
      setSuccess('PIR completed.');
      if (response?.data) {
        setPIR(response.data);
        setForm(recordToForm(response.data));
      }
      await loadData();
    } catch (e) {
      showError(e, 'Could not complete the PIR.');
    } finally {
      setBusy('');
    }
  };

  const runLifecycle = async (action, label, body) => {
    if (!canManage || busy) return;
    clearMessages();
    setBusy(action);
    try {
      await api.post(`/changes/${id}/${action}/`, body);
      setSuccess(`${label} recorded.`);
      await loadData();
    } catch (e) {
      showError(e, `Could not ${label.toLowerCase()}.`);
    } finally {
      setBusy('');
    }
  };

  if (loading) {
    return <div className="mt-3"><p>Loading PIR…</p></div>;
  }

  if (loadError) {
    return (
      <div className="mt-3">
        <Alert variant="danger">{loadError}</Alert>
        <Button onClick={loadData}>Retry</Button>
      </div>
    );
  }

  if (!change || !canView) {
    return (
      <div className="mt-3">
        <p>PIR details are not available for this account.</p>
      </div>
    );
  }

  const canRequestPIR = canManage
    && ['completed', 'failed', 'rolled_back'].includes(change.status);
  const pirCompleted = Boolean(pir?.id && pir.status === 'completed');
  const canCompletePIR = canManage
    && Boolean(pir?.id)
    && ['pending', 'scheduled', 'in_progress'].includes(pir.status);
  // A requested PIR is mandatory for closure. Completed low/medium-risk
  // changes keep their existing no-PIR closure path.
  const canClose = canManage && (
    (change.status === 'completed' && !['high', 'critical'].includes(change.risk_level))
    || (change.status === 'pir_required' && pirCompleted)
  );

  return (
    <div>
      <PageHeader title="PIR & Closure" sub={change.change_number} />
      <div className="mt-3">
        {error ? <Alert variant="danger">{error}</Alert> : null}
        {success ? <Alert variant="success">{success}</Alert> : null}

        <p><strong>Change Number:</strong> {change.change_number}</p>
        <p><strong>Change Status:</strong> <Badge
          kind="status"
          value={change.status}
          label={STATUS_LABELS[change.status] || change.status || 'Draft'}
        /></p>
        <hr />

        <div className="mt-3">
          <h4>PIR Details</h4>
          {pir ? (
            <div>
              <Row>
                <Col sm={4}><strong>Status:</strong> {pir.status || '—'}</Col>
                <Col sm={4}><strong>Reviewer:</strong> {pir.reviewer_email || '—'}</Col>
                <Col sm={4}><strong>Reviewed By:</strong> {pir.reviewed_by_email || '—'}</Col>
              </Row>
              <Row className="mt-1">
                <Col sm={6}><strong>Outcome:</strong> {pir.outcome || '—'}</Col>
                <Col sm={6}><strong>Completed:</strong> {formatDateTime(pir.completed_at) || '—'}</Col>
              </Row>
              <Row className="mt-1">
                <Col sm={6}><strong>Scheduled For:</strong> {formatDateTime(pir.scheduled_for) || '—'}</Col>
                <Col sm={6}><strong>Knowledge Article:</strong> {pir.knowledge_article ?? '—'}</Col>
              </Row>
              <Row className="mt-1">
                <Col sm={6}><strong>Objectives Met:</strong> {pir.objectives_met || '—'}</Col>
                <Col sm={6}><strong>Unexpected Impact:</strong> {pir.unexpected_impact || '—'}</Col>
              </Row>
              <Row className="mt-1">
                <Col sm={6}><strong>Validation Successful:</strong> {pir.validation_successful ? 'Yes' : 'No'}</Col>
                <Col sm={6}><strong>Downtime Within Estimate:</strong> {pir.downtime_within_estimate ? 'Yes' : 'No'}</Col>
              </Row>
              <Row className="mt-1">
                <Col sm={6}><strong>Rollback Used:</strong> {pir.rollback_used ? 'Yes' : 'No'}</Col>
                <Col sm={6}><strong>Incident Created:</strong> {pir.incident_created ? 'Yes' : 'No'}</Col>
              </Row>
              {pir.lessons_learned ? (
                <Row className="mt-1"><Col sm={12}><strong>Lessons Learned:</strong> {pir.lessons_learned}</Col></Row>
              ) : null}
              {pir.follow_up_actions ? (
                <Row className="mt-1"><Col sm={12}><strong>Follow-Up Actions:</strong> {pir.follow_up_actions}</Col></Row>
              ) : null}
            </div>
          ) : (
            <p className="text-muted">No PIR has been recorded for this change.</p>
          )}
        </div>

        {canManage ? (
          <Form>
            <h4 className="mt-3">{pir ? 'Update PIR' : 'Record PIR'}</h4>
            <Row>
              <Col sm={6}>
                <Field label="Outcome" error={fieldMsg(fieldErrors, 'outcome')}>
                  <Select value={form.outcome} onChange={(e) => setField('outcome', e.target.value)}>
                    {OUTCOME_CHOICES.map(([value, label]) => (
                      <option key={value || 'none'} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
              </Col>
              <Col sm={6}>
                <Field label="Scheduled for" error={fieldMsg(fieldErrors, 'scheduled_for')}>
                  <Input
                    type="datetime-local"
                    value={form.scheduled_for}
                    onChange={(e) => setField('scheduled_for', e.target.value)}
                  />
                </Field>
              </Col>
            </Row>
            <Field label="Objectives met" error={fieldMsg(fieldErrors, 'objectives_met')}>
              <Textarea
                rows={3}
                value={form.objectives_met}
                onChange={(e) => setField('objectives_met', e.target.value)}
              />
            </Field>
            <Field label="Unexpected impact" error={fieldMsg(fieldErrors, 'unexpected_impact')}>
              <Textarea
                rows={3}
                value={form.unexpected_impact}
                onChange={(e) => setField('unexpected_impact', e.target.value)}
              />
            </Field>
            <Row>
              <Col sm={4}>
                <Field label="Validation successful">
                  <Input
                    type="checkbox"
                    checked={form.validation_successful}
                    onChange={(e) => setField('validation_successful', e.target.checked)}
                  />
                </Field>
              </Col>
              <Col sm={4}>
                <Field label="Downtime within estimate">
                  <Input
                    type="checkbox"
                    checked={form.downtime_within_estimate}
                    onChange={(e) => setField('downtime_within_estimate', e.target.checked)}
                  />
                </Field>
              </Col>
              <Col sm={4}>
                <Field label="Rollback used">
                  <Input
                    type="checkbox"
                    checked={form.rollback_used}
                    onChange={(e) => setField('rollback_used', e.target.checked)}
                  />
                </Field>
              </Col>
            </Row>
            <Row>
              <Col sm={6}>
                <Field label="Incident created">
                  <Input
                    type="checkbox"
                    checked={form.incident_created}
                    onChange={(e) => setField('incident_created', e.target.checked)}
                  />
                </Field>
              </Col>
              <Col sm={6}>
                <Field label="Completed at" error={fieldMsg(fieldErrors, 'completed_at')}>
                  <Input
                    type="datetime-local"
                    value={form.completed_at}
                    onChange={(e) => setField('completed_at', e.target.value)}
                  />
                </Field>
              </Col>
            </Row>
            <Field label="Lessons learned" error={fieldMsg(fieldErrors, 'lessons_learned')}>
              <Textarea
                rows={3}
                value={form.lessons_learned}
                onChange={(e) => setField('lessons_learned', e.target.value)}
              />
            </Field>
            <Field label="Follow-up actions" error={fieldMsg(fieldErrors, 'follow_up_actions')}>
              <Textarea
                rows={3}
                value={form.follow_up_actions}
                onChange={(e) => setField('follow_up_actions', e.target.value)}
              />
            </Field>
            <Row>
              <Col sm={6}>
                <Field label="Knowledge article id" error={fieldMsg(fieldErrors, 'knowledge_article')}>
                  <Input
                    type="number"
                    min="1"
                    value={form.knowledge_article}
                    onChange={(e) => setField('knowledge_article', e.target.value)}
                  />
                </Field>
              </Col>
              <Col sm={6}>
                <Field label="Reviewed by user id" error={fieldMsg(fieldErrors, 'reviewed_by')}>
                  <Input
                    type="number"
                    min="1"
                    value={form.reviewed_by}
                    onChange={(e) => setField('reviewed_by', e.target.value)}
                  />
                </Field>
              </Col>
            </Row>
            <div className="mt-3">
              <Button onClick={savePIR} disabled={Boolean(busy)}>
                {pir ? 'Update PIR' : 'Create PIR'}
              </Button>
            </div>

            {canCompletePIR || canRequestPIR || canClose ? (
              <div className="mt-3">
                <h4>Lifecycle</h4>
                {canCompletePIR ? (
                  <Button
                    onClick={completePIR}
                    disabled={Boolean(busy)}
                  >
                    Complete PIR
                  </Button>
                ) : null}
                {canRequestPIR ? (
                  <Button
                    onClick={() => runLifecycle('request_pir', 'PIR request', {})}
                    disabled={Boolean(busy)}
                  >
                    Request PIR
                  </Button>
                ) : null}
                {canClose ? (
                  <div className="mt-3">
                    <Field label="Closure summary">
                      <Textarea
                        rows={3}
                        value={closureSummary}
                        onChange={(e) => setClosureSummary(e.target.value)}
                      />
                    </Field>
                    <Button
                      kind="success"
                      onClick={() => runLifecycle('close', 'Closure', {
                        closure_summary: closureSummary.trim(),
                      })}
                      disabled={Boolean(busy)}
                    >
                      Close Change
                    </Button>
                  </div>
                ) : null}
              </div>
            ) : null}
          </Form>
        ) : (
          <p className="text-muted small">
            PIR actions available to IT managers and System Admins only
          </p>
        )}
      </div>
    </div>
  );
}
