/*
 * Change Form - multi-step wizard for creating and editing changes
 * Routes: #/changes/new, #/changes/:id/edit
 */

import React, { useState, useEffect } from 'react';
import { Form, Input, Select, Textarea, Button, Row, Col } from './components';
import { useAuth } from './auth';
import { STATUS_LABELS, CHANGE_TYPE_LABELS, CATEGORY_LABELS, PRIORITY_LABELS } from './changes-utils';

const STEP1 = 'classification';
const STEP2 = 'description';
const STEP3 = 'planning';
const STEP4 = 'technical-plans';
const STEP5 = 'affected-records';
const STEP6 = 'review';

export function ChangeForm({ changeId = null }) {
  const { isStaff, role } = useAuth();
  const [step, setStep] = useState(STEP1);
  const [change, setChange] = useState({
    title: '',
    change_type: 'normal',
    category: '',
    priority: 'normal',
    risk_level: 'low',
    planned_start: '',
    planned_end: '',
    business_reason: '',
    scope: '',
    out_of_scope: '',
    customer_impact: '',
    business_impact: '',
    technical_impact: '',
    implementation_plan: '',
    validation_plan: '',
    rollback_plan: '',
    communication_plan: '',
    success_criteria: '',
    planned_downtime_minutes: 0,
    department: '',
    change_owner: null,
    implementation_lead: null,
    assets: [],
    services: [],
    related_tickets: [],
    knowledge_base_references: [],
  });
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (changeId) {
      // TODO: load existing change from API
    }
  }, [changeId]);

  const validate = () => {
    const e = {};
    if (!change.title) e.title = 'Required';
    if (!change.change_type) e.change_type = 'Required';
    if (!change.category) e.category = 'Required';
    if (!change.priority) e.priority = 'Required';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const next = () => {
    if (!validate()) return;
    const steps = { [STEP1]: STEP2, [STEP2]: STEP3, [STEP3]: STEP4, [STEP4]: STEP5, [STEP5]: STEP6 };
    setStep(steps[step]);
  };

  const prev = () => {
    const steps = { [STEP6]: STEP5, [STEP5]: STEP4, [STEP4]: STEP3, [STEP3]: STEP2, STEP2: STEP1 };
    setStep(steps[step] || STEP1);
  };

  const handleAssetChange = (assets) => setChange(c => ({ ...c, assets }));
  const handleServiceChange = (services) => setChange(c => ({ ...c, services }));

  const handleSubmit = () => {
    // TODO: submit change to API
    setSubmitting(false);
  };

  if (step === STEP1) {
    return (
      <Form>
        <h2>Classification</h2>
        <Row>
          <Col sm={6}>
            <Select onChange={(e) => setChange(c => ({ ...c, change_type: e.target.value }))} value={change.change_type || ''}>
              <option value="">Select type</option>
              {Object.keys(CHANGE_TYPE_LABELS).map(k => (
                <option key={k} value={k}>{CHANGE_TYPE_LABELS[k]}</option>
              ))}
            </Select>
          </Col>
          <Col sm={6}>
            <Select onChange={(e) => setChange(c => ({ ...c, category: e.target.value }))} value={change.category || ''}>
              <option value="">Select category</option>
              {Object.keys(CATEGORY_LABELS).map(k => (
                <option key={k} value={k}>{CATEGORY_LABELS[k]}</option>
              ))}
            </Select>
          </Col>
        </Row>
        <Row className="mt-3"><Col sm={4}><Select onChange={(e) => setChange(c => ({ ...c, priority: e.target.value }))} value={change.priority || ''}><option value="">Priority</option>{Object.keys(PRIORITY_LABELS).map(k => (
          <option key={k} value={k}>{PRIORITY_LABELS[k]}</option>
        ))}</Select></Col><Col sm={4}><Select onChange={(e) => setChange(c => ({ ...c, risk_level: e.target.value }))} value={change.risk_level || ''}><option value="">Risk</option>{['low','medium','high','critical'].map(l => <option key={l} value={l}>{l}</option>)}</Select></Col><Col sm={4}><Input placeholder="Emergency" value={change.emergency_reason || ''} onChange={(e) => setChange(c => ({ ...c, emergency_reason: e.target }))} /></Col></Row>
        <Button onClick={next}>Next</Button><Button onClick={prev}>Cancel</Button>
      </Form>
    );
  }

  if (step === STEP2) {
    return (
      <Form>
        <h2>Description</h2>
        <Input placeholder="Title" value={change.title || ''} onChange={(e) => setChange(c => ({ ...c, title: e.target.value }))} required />
        <Textarea rows={3} placeholder="Description" value={change.description || ''} onChange={(e) => setChange(c => ({ ...c, description: e.target.value }))} />
        <Button onClick={next}>Next</Button><Button onClick={prev}>Previous</Button>
      </Form>
    );
  }

  if (step === STEP3) {
    return (
      <Form>
        <h2>Planning</h2>
        <Input type="datetime-local" value={change.planned_start || ''} onChange={(e) => setChange(c => ({ ...c, planned_start: e.target.value }))} />
        <Input type="datetime-local" value={change.planned_end || ''} onChange={(e) => setChange(c => ({ ...c, planned_end: e.target.value }))} />
        <Input placeholder="Expected downtime (minutes)" value={change.planned_downtime_minutes || ''} onChange={(e) => setChange(c => ({ ...c, planned_downtime_minutes: Number(e.target.value) || 0 }))} />
        <Button onClick={next}>Next</Button><Button onClick={prev}>Previous</Button>
      </Form>
    );
  }

  if (step === STEP4) {
    return (
      <Form>
        <h2>Technical Plans</h2>
        <Textarea rows={4} placeholder="Implementation plan" value={change.implementation_plan || ''} onChange={(e) => setChange(c => ({ ...c, implementation_plan: e.target.value }))} />
        <Textarea rows={4} placeholder="Validation plan" value={change.validation_plan || ''} onChange={(e) => setChange(c => ({ ...c, validation_plan: e.target.value }))} />
        <Textarea rows={4} placeholder="Rollback plan" value={change.rollback_plan || ''} onChange={(e) => setChange(c => ({ ...c, rollback_plan: e.target.value }))} />
        <Textarea rows={4} placeholder="Communication plan" value={change.communication_plan || ''} onChange={(e) => setChange(c => ({ ...c, communication_plan: e.target.value }))} />
        <Input placeholder="Success criteria" value={change.success_criteria || ''} onChange={(e) => setChange(c => ({ ...c, success_criteria: e.target.value }))} />
        <Button onClick={next}>Next</Button><Button onClick={prev}>Previous</Button>
      </Form>
    );
  }

  if (step === STEP5) {
    return (
      <Form>
        <h2>Affected Records</h2>
        <Row>
          <Col sm={6}><h4>Assets</h4><Select multiple onChange={(e) => handleAssetChange(e.target.value)}>{/* Asset options */}</Select></Col>
          <Col sm={6}><h4>Services</h4><Select multiple onChange={(e) => handleServiceChange(e.target.value)}>{/* Service options */}</Select></Col>
        </Row>
        <Row className="mt-3"><Col sm={12}><Input placeholder="Related Tickets (IDs)" value={change.related_tickets_str || ''} onChange={(e) => setChange(c => ({ ...c, related_tickets_str: e.target.value }))} /></Col></Row>
        <Row className="mt-3"><Col sm={12}><Input placeholder="KB References" value={change.knowledge_base_references_str || ''} onChange={(e) => setChange(c => ({ ...c, knowledge_base_references_str: e.target.value }))} /></Col></Row>
        <Button onClick={next}>Next</Button><Button onClick={prev}>Previous</Button>
      </Form>
    );
  }

  if (step === STEP6) {
    return (
      <Form>
        <h2>Review</h2>
        <p>Please review the change details before submitting.</p>
        <Button onClick={() => setSubmitting(true)} type="primary">Save Draft</Button>
        <Button onClick={handleSubmit} type="success">Save and Submit</Button>
        <Button onClick={prev}>Cancel</Button>
      </Form>
    );
  }

  return null;
}