/*
 * Change Form - multi-step wizard for creating changes
 * Routes: #/changes/new, #/changes/:id/edit
 */

import React, { useEffect, useState } from 'react';
import api from '../../api';
import { Alert, Button, Col, Field, Form, Input, Row, Select, Textarea } from '../../components';
import { useAuth } from '../../auth';
import { fetchPage, parseApiError, CHANGE_TYPE_LABELS, CATEGORY_LABELS, PRIORITY_LABELS } from '../../shared/changes-utils';
import { fieldMsg } from '../../api-utils';

const STEP1 = 'classification';
const STEP2 = 'description';
const STEP3 = 'planning';
const STEP4 = 'technical-plans';
const STEP5 = 'affected-records';
const STEP6 = 'review';

const EMPTY_CHANGE = {
  title: '',
  change_type: 'normal',
  category: '',
  priority: 'normal',
  department: '',
  business_reason: '',
  description: '',
  scope: '',
  out_of_scope: '',
  implementation_plan: '',
  validation_plan: '',
  rollback_plan: '',
  communication_plan: '',
  success_criteria: '',
  emergency_reason: '',
  approval_required: true,
};

const STEP_ORDER = [STEP1, STEP2, STEP3, STEP4, STEP5, STEP6];

// Only fields declared writable by ChangeRequestCreateSerializer are sent.
// Ownership, status, risk level and scheduling are assigned by the backend or
// managed through separate workflow endpoints.
function buildPayload(change) {
  return {
    title: change.title.trim(),
    description: change.description || '',
    business_reason: change.business_reason || '',
    change_type: change.change_type,
    category: change.category,
    priority: change.priority,
    department: change.department ? Number(change.department) : null,
    scope: change.scope || '',
    out_of_scope: change.out_of_scope || '',
    implementation_plan: change.implementation_plan || '',
    validation_plan: change.validation_plan || '',
    rollback_plan: change.rollback_plan || '',
    communication_plan: change.communication_plan || '',
    success_criteria: change.success_criteria || '',
    emergency_reason: change.emergency_reason || '',
    approval_required: Boolean(change.approval_required),
  };
}

function validateStep(step, values) {
  const e = {};
  if (step === STEP1) {
    if (!values.change_type) e.change_type = 'Change type is required.';
    if (!values.category) e.category = 'Category is required.';
    if (!values.priority) e.priority = 'Priority is required.';
    if (values.change_type === 'emergency' && !values.emergency_reason.trim()) {
      e.emergency_reason = 'Emergency reason is required for emergency changes.';
    }
  }
  if (step === STEP2 && !values.title.trim()) {
    e.title = 'Title is required.';
  }
  return e;
}

function validateForSubmit(values) {
  const e = validateStep(STEP1, values);
  Object.assign(e, validateStep(STEP2, values));
  if (!values.business_reason.trim()) {
    e.business_reason = 'Business reason is required before submission.';
  }
  if (!values.implementation_plan.trim()) {
    e.implementation_plan = 'Implementation plan is required before submission.';
  }
  if (!values.rollback_plan.trim()) {
    e.rollback_plan = 'Rollback plan is required before submission.';
  }
  return e;
}

function firstStepWithErrors(errors) {
  if (errors.change_type || errors.category || errors.priority || errors.emergency_reason) return STEP1;
  if (errors.title || errors.business_reason) return STEP2;
  if (errors.implementation_plan || errors.rollback_plan) return STEP4;
  return null;
}

export function ChangeForm({ changeId = null }) {
  useAuth();
  const [step, setStep] = useState(STEP1);
  const [change, setChange] = useState({ ...EMPTY_CHANGE });
  const [departments, setDepartments] = useState([]);
  const [lookupError, setLookupError] = useState('');
  const [errors, setErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [createdId, setCreatedId] = useState(null);

  useEffect(() => {
    // Editing an existing change remains a separate workflow.
    if (changeId) return undefined;
    let active = true;
    fetchPage('/accounts/departments/')
      .then(({ items }) => {
        if (!active) return;
        setDepartments((items || []).filter(
          (d) => d.is_active !== false && d.is_deleted !== true,
        ));
      })
      .catch((e) => {
        if (!active) return;
        setLookupError(parseApiError(e).global || 'Could not load departments.');
      });
    return () => { active = false; };
  }, [changeId]);

  const update = (key, value) => setChange((c) => ({ ...c, [key]: value }));

  const next = () => {
    const e = validateStep(step, change);
    if (Object.keys(e).length) {
      setErrors(e);
      return;
    }
    setErrors({});
    setStep(STEP_ORDER[STEP_ORDER.indexOf(step) + 1] || STEP6);
  };

  const prev = () => {
    setErrors({});
    setStep(STEP_ORDER[Math.max(0, STEP_ORDER.indexOf(step) - 1)]);
  };

  const save = async (shouldSubmit) => {
    if (submitting) return;
    setErrors({});
    setGlobalError('');

    if (changeId) {
      setGlobalError('Editing an existing change is not supported by this form.');
      return;
    }

    const validationErrors = shouldSubmit
      ? validateForSubmit(change)
      : validateStep(STEP1, change);
    if (!shouldSubmit) Object.assign(validationErrors, validateStep(STEP2, change));
    if (Object.keys(validationErrors).length) {
      setErrors(validationErrors);
      const errorStep = firstStepWithErrors(validationErrors);
      if (errorStep) setStep(errorStep);
      return;
    }

    setSubmitting(true);
    try {
      let id = createdId;
      if (!id) {
        const response = await api.post('/changes/', buildPayload(change));
        id = response.data?.id;
        if (!id) throw new Error('Create response did not include a change id.');
        setCreatedId(id);
      }
      if (shouldSubmit) {
        await api.post(`/changes/${id}/submit/`, {});
      }
      window.location.hash = `#/changes/${id}`;
    } catch (e) {
      const parsed = parseApiError(e);
      const fieldErrors = parsed.fields || {};
      setErrors(fieldErrors);
      const errorStep = firstStepWithErrors(fieldErrors);
      if (errorStep) setStep(errorStep);
      setGlobalError(parsed.global || (shouldSubmit
        ? 'Could not save and submit the change.'
        : 'Could not create the change.'));
    } finally {
      setSubmitting(false);
    }
  };

  const errorSummary = globalError || lookupError ? (
    <Alert variant="danger">{globalError || lookupError}</Alert>
  ) : null;

  const navigation = (backLabel = 'Previous') => (
    <div className="mt-3">
      <Button onClick={next}>Next</Button>
      <Button onClick={prev}>{backLabel}</Button>
    </div>
  );

  if (step === STEP1) {
    return (
      <Form>
        <h2>Classification</h2>
        {errorSummary}
        <Row>
          <Col sm={6}>
            <Field label="Change type" required error={fieldMsg(errors, 'change_type')}>
              <Select onChange={(e) => update('change_type', e.target.value)} value={change.change_type}>
                <option value="">Select type</option>
                {Object.keys(CHANGE_TYPE_LABELS).map((k) => (
                  <option key={k} value={k}>{CHANGE_TYPE_LABELS[k]}</option>
                ))}
              </Select>
            </Field>
          </Col>
          <Col sm={6}>
            <Field label="Category" required error={fieldMsg(errors, 'category')}>
              <Select onChange={(e) => update('category', e.target.value)} value={change.category}>
                <option value="">Select category</option>
                {Object.keys(CATEGORY_LABELS).map((k) => (
                  <option key={k} value={k}>{CATEGORY_LABELS[k]}</option>
                ))}
              </Select>
            </Field>
          </Col>
        </Row>
        <Row className="mt-3">
          <Col sm={4}>
            <Field label="Priority" required error={fieldMsg(errors, 'priority')}>
              <Select onChange={(e) => update('priority', e.target.value)} value={change.priority}>
                <option value="">Select priority</option>
                {Object.keys(PRIORITY_LABELS).map((k) => (
                  <option key={k} value={k}>{PRIORITY_LABELS[k]}</option>
                ))}
              </Select>
            </Field>
          </Col>
          <Col sm={4}>
            <Field label="Department" error={fieldMsg(errors, 'department')}>
              <Select onChange={(e) => update('department', e.target.value)} value={change.department}>
                <option value="">No department</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </Select>
            </Field>
          </Col>
          <Col sm={4}>
            <Field label="Approval required" error={fieldMsg(errors, 'approval_required')}>
              <Input
                type="checkbox"
                checked={Boolean(change.approval_required)}
                onChange={(e) => update('approval_required', e.target.checked)}
              />
            </Field>
          </Col>
        </Row>
        <Row className="mt-3">
          <Col sm={12}>
            <Field
              label="Emergency reason"
              error={fieldMsg(errors, 'emergency_reason')}
              hint="Required when change type is Emergency."
            >
              <Input
                value={change.emergency_reason}
                onChange={(e) => update('emergency_reason', e.target.value)}
              />
            </Field>
          </Col>
        </Row>
        {navigation('Cancel')}
      </Form>
    );
  }

  if (step === STEP2) {
    return (
      <Form>
        <h2>Description</h2>
        {errorSummary}
        <Field label="Title" required error={fieldMsg(errors, 'title')}>
          <Input value={change.title} onChange={(e) => update('title', e.target.value)} />
        </Field>
        <Field label="Description" error={fieldMsg(errors, 'description')}>
          <Textarea rows={3} value={change.description} onChange={(e) => update('description', e.target.value)} />
        </Field>
        <Field
          label="Business reason"
          error={fieldMsg(errors, 'business_reason')}
          hint="Required before submission."
        >
          <Textarea rows={3} value={change.business_reason} onChange={(e) => update('business_reason', e.target.value)} />
        </Field>
        {navigation()}
      </Form>
    );
  }

  if (step === STEP3) {
    return (
      <Form>
        <h2>Planning</h2>
        {errorSummary}
        <Field label="Scope" error={fieldMsg(errors, 'scope')}>
          <Textarea rows={4} value={change.scope} onChange={(e) => update('scope', e.target.value)} />
        </Field>
        <Field label="Out of scope" error={fieldMsg(errors, 'out_of_scope')}>
          <Textarea rows={4} value={change.out_of_scope} onChange={(e) => update('out_of_scope', e.target.value)} />
        </Field>
        {navigation()}
      </Form>
    );
  }

  if (step === STEP4) {
    return (
      <Form>
        <h2>Technical Plans</h2>
        {errorSummary}
        <Field label="Implementation plan" error={fieldMsg(errors, 'implementation_plan')}>
          <Textarea rows={4} value={change.implementation_plan} onChange={(e) => update('implementation_plan', e.target.value)} />
        </Field>
        <Field label="Validation plan" error={fieldMsg(errors, 'validation_plan')}>
          <Textarea rows={4} value={change.validation_plan} onChange={(e) => update('validation_plan', e.target.value)} />
        </Field>
        <Field label="Rollback plan" error={fieldMsg(errors, 'rollback_plan')}>
          <Textarea rows={4} value={change.rollback_plan} onChange={(e) => update('rollback_plan', e.target.value)} />
        </Field>
        <Field label="Communication plan" error={fieldMsg(errors, 'communication_plan')}>
          <Textarea rows={4} value={change.communication_plan} onChange={(e) => update('communication_plan', e.target.value)} />
        </Field>
        <Field label="Success criteria" error={fieldMsg(errors, 'success_criteria')}>
          <Textarea rows={3} value={change.success_criteria} onChange={(e) => update('success_criteria', e.target.value)} />
        </Field>
        {navigation()}
      </Form>
    );
  }

  if (step === STEP5) {
    return (
      <Form>
        <h2>Affected Records</h2>
        {errorSummary}
        <p>Assets, services, related tickets, and KB references can be linked after the change is created.</p>
        {navigation()}
      </Form>
    );
  }

  if (step === STEP6) {
    return (
      <Form>
        <h2>Review</h2>
        {errorSummary}
        <p>Please review the change details before submitting.</p>
        <div className="mt-3">
          <Button onClick={() => save(false)} disabled={submitting}>Save Draft</Button>
          <Button onClick={() => save(true)} disabled={submitting}>Save and Submit</Button>
          <Button onClick={prev}>Cancel</Button>
        </div>
      </Form>
    );
  }

  return null;
}
