import { useEffect, useRef, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  ErrorSummary, Field, PageHeader, UserSelect,
} from './components';
import { fieldMsg, parseApiError } from './api-utils';
import {
  CASE_TYPE_LABELS, CASE_STATUS_LABELS, PRIORITY_LABELS,
  RESPONSIBILITY_LABELS, CATEGORY_LABELS, DEFAULT_ASSIGNEE_ROLE_LABELS,
  formatDate, formatDateTime,
} from './lifecycle-utils';

// Re-exported label maps used by the wizard steps.
export {
  CASE_TYPE_LABELS, PRIORITY_LABELS, RESPONSIBILITY_LABELS,
  CATEGORY_LABELS, DEFAULT_ASSIGNEE_ROLE_LABELS,
};

const STEP_TITLES = {
  1: 'Case Basics',
  2: 'Dates & Organization',
  3: 'Checklist Preview',
  4: 'Review & Create',
};

const DEFAULT_FORM = {
  case_type: '',
  employee: '',
  template_id: '',
  priority: 'medium',
  planned_date: '',
  effective_date: '',
  completion_target: '',
  department: '',
  assigned_coordinator: '',
  new_department: '',
  notes: '',
};

export function LifecycleForm() {
  const { user, isStaff, isManagerOrAdmin, isEmployee, role } = useAuth();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState({ ...DEFAULT_FORM });
  const [templates, setTemplates] = useState([]);
  const [templateItems, setTemplateItems] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [okMsg, setOkMsg] = useState('');
  const [editCaseId, setEditCaseId] = useState(null);

  // Parse ?edit=<id> from hash for draft editing.
  useEffect(() => {
    const m = location.hash.match(/[?&]edit=(\d+)/);
    if (m && !editCaseId) setEditCaseId(m[1]);
  }, [editCaseId]);

  const loadLookup = async () => {
    setLoading(true);
    setLoadError('');
    try {
      const [tRes, eRes, dRes] = await Promise.all([
        api.get('/lifecycle/templates/', { params: { page_size: 100 } }),
        api.get('/accounts/users/', { params: { page_size: 100 } }),
        api.get('/accounts/departments/', { params: { page_size: 100 } }),
      ]);
      setTemplates(tRes.data.results ?? tRes.data ?? []);
      setEmployees((eRes.data.results ?? eRes.data ?? []).filter(
        (u) => u.is_active !== false && u.is_deleted !== true));
      setDepartments((dRes.data.results ?? dRes.data ?? []).filter(
        (d) => d.is_active !== false && d.is_deleted !== true));
    } catch (e) {
      setLoadError(parseApiError(e).global || 'Could not load lookup data.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isEmployee) {
      setLoadError('Employees cannot create lifecycle cases.');
      setLoading(false);
      return;
    }
    loadLookup();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadTemplateItems = async (templateId) => {
    if (!templateId) { setTemplateItems([]); return; }
    try {
      const r = await api.get('/lifecycle/template-items/', {
        params: { template: templateId, page_size: 100 },
      });
      setTemplateItems(r.data.results ?? r.data ?? []);
    } catch {
      setTemplateItems([]);
    }
  };

  const isTransfer = form.case_type === 'transfer';
  const isOffboarding = form.case_type === 'offboarding';
  const isOnboarding = form.case_type === 'onboarding';

  const selectedTemplate = templates.find((t) => String(t.id) === String(form.template_id));
  const selectedEmployee = employees.find((e) => String(e.id) === String(form.employee));
  const selectedDepartment = departments.find((d) => String(d.id) === String(form.department));

  // ---- Step navigation ----
  const nextStep = () => { if (step < 4) setStep((s) => s + 1); };
  const prevStep = () => { if (step > 1) setStep((s) => s - 1); };

  // ---- Step 1 validation ----
  const step1Valid = () => {
    const errs = {};
    if (!form.case_type) errs.case_type = 'Case type is required.';
    if (!form.employee) errs.employee = 'Employee is required.';
    else if (selectedEmployee && selectedEmployee.is_deleted) {
      errs.employee = 'Selected employee is not active.';
    }
    if (!form.template_id) errs.template_id = 'Template is required.';
    else if (selectedTemplate && selectedTemplate.case_type !== form.case_type) {
      errs.template_id = 'Template case type does not match the selected case type.';
    }
    if (!form.priority) errs.priority = 'Priority is required.';
    return errs;
  };

  // ---- Step 2 validation ----
  const step2Valid = () => {
    const errs = {};
    if (isTransfer && !form.new_department) {
      errs.new_department = 'A new department is required for transfers.';
    }
    if (form.planned_date && form.effective_date && form.effective_date < form.planned_date) {
      errs.effective_date = 'Effective date should not precede the planned date.';
    }
    if (form.completion_target && form.planned_date && form.completion_target < form.planned_date) {
      errs.completion_target = 'Completion target should not precede the planned date.';
    }
    return errs;
  };

  const canProceed = (s) => {
    const v = s === 1 ? step1Valid() : s === 2 ? step2Valid() : {};
    return Object.keys(v).length === 0;
  };

  const submit = async (ev) => {
    ev.preventDefault();
    if (submitting) return;
    const v = step1Valid();
    if (Object.keys(v).length) { setFieldErrors(v); return; }
    setFieldErrors({});
    setGlobalError('');
    setOkMsg('');
    setSubmitting(true);

    const payload = {
      template_id: Number(form.template_id),
      employee: Number(form.employee),
      priority: form.priority,
      department: form.department ? Number(form.department) : null,
      planned_date: form.planned_date || null,
      effective_date: form.effective_date || null,
      completion_target: form.completion_target || null,
      source: 'manual',
      source_reference: '',
      notes: form.notes || '',
      assigned_coordinator: form.assigned_coordinator ? Number(form.assigned_coordinator) : null,
    };

    try {
      const r = await api.post('/lifecycle/cases/', payload);
      setOkMsg(`Case ${r.data.case_number} created.`);
      setSubmitting(false);
      setTimeout(() => { location.hash = `#/lifecycle/${r.data.id}`; }, 600);
    } catch (e) {
      const p = parseApiError(e);
      setFieldErrors(p.fields);
      setGlobalError(p.global || 'Could not create the case.');
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading case creation form…
      </p>
    );
  }
  if (loadError && !templates.length) {
    return (
      <div className="form-wrap">
        <div className="error-summary" role="alert">{loadError}</div>
        <p><a className="back-link" href="#/lifecycle">← Back to Lifecycle</a></p>
      </div>
    );
  }
  if (isEmployee) {
    return (
      <div className="form-wrap">
        <h1>New Lifecycle Case</h1>
        <div className="error-summary" role="alert">
          Case creation is not available to employees. Only IT staff and above
          can create lifecycle cases.
        </div>
        <p><a className="back-link" href="#/lifecycle">← Back to Lifecycle</a></p>
      </div>
    );
  }

  const progressPct = (step - 1) / 3 * 100;

  return (
    <div className="lifecycle-form">
      <PageHeader
        title={`New Lifecycle Case — Step ${step} of 4`}
        sub={STEP_TITLES[step]}
        actions={
          <div className="row-gap" style={{ alignItems: 'center', gap: 'var(--sp-1)' }}>
            <span className="muted small">{Math.round(progressPct)}% complete</span>
          </div>
        }
      />
      {globalError && <ErrorSummary parsed={{ global: globalError }} />}
      {okMsg && <div className="success-summary" role="status">{okMsg}</div>}

      {/* Step indicator */}
      <div className="stepper" role="navigation" aria-label="Wizard steps">
        {[1, 2, 3, 4].map((n) => (
          <div key={n} className={`step ${n === step ? 'current' : n < step ? 'done' : 'todo'}`}>
            <span className="step-badge">{n}</span>
            <span className="step-label">{STEP_TITLES[n]}</span>
          </div>
        ))}
      </div>

      <form onSubmit={submit} noValidate>
        {/* ===== STEP 1: Case Basics ===== */}
        <div className={`wizard-step ${step === 1 ? '' : 'hidden'}`}>
          <Field label="Case Type" required error={fieldMsg(fieldErrors, 'case_type')}>
            <select className="input" data-testid="case-type-select" value={form.case_type} onChange={(e) => {
              setForm((f) => ({ ...f, case_type: e.target.value, template_id: '', department: '' }));
            }} disabled={submitting}>
              <option value="">Select a case type…</option>
              {Object.entries(CASE_TYPE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </Field>
          <Field label="Employee" required error={fieldMsg(fieldErrors, 'employee')}>
            <UserSelect value={form.employee} onChange={(val) => {
              const id = val != null ? Number(val) : '';
              setForm((f) => ({ ...f, employee: id }));
            }} disabled={submitting} label="Select the employee this case is for" />
          </Field>
          <Field label="Template" required error={fieldMsg(fieldErrors, 'template_id')}>
            <select className="input" data-testid="template-select" value={form.template_id} onChange={(e) => {
              const id = e.target.value ? Number(e.target.value) : '';
              setForm((f) => ({ ...f, template_id: id }));
              loadTemplateItems(id);
            }} disabled={submitting}>
              <option value="">Select a template…</option>
              {templates.filter((t) => !form.case_type || t.case_type === form.case_type)
                .filter((t) => t.is_active !== false && t.is_deleted !== true)
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.code} — {t.name} ({t.item_count || 0} items)
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Priority" required error={fieldMsg(fieldErrors, 'priority')}>
            <select className="input" value={form.priority} onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))} disabled={submitting}>
              {Object.entries(PRIORITY_LABELS).map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </Field>
          {Object.keys(step1Valid()).length && (
            <div className="field-error" role="alert">
              Please fix the errors above before continuing.
            </div>
          )}
        </div>

        {/* ===== STEP 2: Dates & Organization ===== */}
        <div className={`wizard-step ${step === 2 ? '' : 'hidden'}`}>
          <Field label="Planned Date">
            <input className="input" type="date" value={form.planned_date || ''}
              onChange={(e) => setForm((f) => ({ ...f, planned_date: e.target.value }))} disabled={submitting} />
          </Field>
          <Field label="Effective Date">
            <input className="input" type="date" value={form.effective_date || ''}
              onChange={(e) => setForm((f) => ({ ...f, effective_date: e.target.value }))} disabled={submitting} />
          </Field>
          <Field label="Completion Target">
            <input className="input" type="date" value={form.completion_target || ''}
              onChange={(e) => setForm((f) => ({ ...f, completion_target: e.target.value }))} disabled={submitting} />
          </Field>
          <Field label="Department">
            <select className="input" value={form.department || ''} onChange={(e) => setForm((f) => ({ ...f, department: e.target.value || null }))} disabled={submitting}>
              <option value="">Same as employee home department</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </Field>
          <Field label="Coordinator">
            <UserSelect value={form.assigned_coordinator} onChange={(id) => {
              setForm((f) => ({ ...f, assigned_coordinator: id != null ? Number(id) : '' }));
            }} disabled={submitting} label="Case coordinator" />
          </Field>
          {isTransfer && (
            <>
              <Field label="Previous Department" hint="Read-only — employee's current home department.">
                <input className="input" value={selectedEmployee?.home_department_name || ''} readOnly disabled={true} />
              </Field>
              <Field label="New Department" required error={fieldMsg(fieldErrors, 'new_department')}>
                <select className="input" value={form.new_department || ''} onChange={(e) => setForm((f) => ({ ...f, new_department: e.target.value || null }))} disabled={submitting}>
                  <option value="">Select a new department…</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
                {selectedEmployee && selectedDepartment && String(selectedDepartment.id) === String(form.new_department) && (
                  <div className="field-error" role="alert">
                    The new department must differ from the employee's current department.
                  </div>
                )}
              </Field>
            </>
          )}
          {Object.keys(step2Valid()).length && (
            <div className="field-error" role="alert">
              Please fix the errors above before continuing.
            </div>
          )}
        </div>

        {/* ===== STEP 3: Checklist Preview ===== */}
        <div className={`wizard-step ${step === 3 ? '' : 'hidden'}`}>
          <p className="muted small">
            Tasks below are copied from the selected template at case creation.
            They are read-only in O2.1; task management comes in O2.2.
          </p>
          {selectedTemplate && templateItems.length ? (
            <div>
              <table className="grid" style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left' }}>Seq.</th>
                    <th style={{ textAlign: 'left' }}>Title</th>
                    <th style={{ textAlign: 'left' }}>Category</th>
                    <th style={{ textAlign: 'left' }}>Responsibility</th>
                    <th style={{ textAlign: 'left' }}>Default Assignee</th>
                    <th style={{ textAlign: 'left' }}>Required</th>
                    <th style={{ textAlign: 'left' }}>Blocks Completion</th>
                    <th style={{ textAlign: 'left' }}>Evidence</th>
                    <th style={{ textAlign: 'left' }}>Due Offset</th>
                    <th style={{ textAlign: 'left' }}>Automation</th>
                  </tr>
                </thead>
                <tbody>
                  {templateItems.map((t) => (
                    <tr key={t.id} style={{ borderBottom: '1px solid #ddd' }}>
                      <td>{t.sequence}</td>
                      <td>{t.title}</td>
                      <td>{CATEGORY_LABELS[t.category] ?? t.category}</td>
                      <td>{RESPONSIBILITY_LABELS[t.responsibility] ?? t.responsibility}</td>
                      <td>{DEFAULT_ASSIGNEE_ROLE_LABELS[t.default_assignee_role] ?? t.default_assignee_role}</td>
                      <td>{t.required ? 'Yes' : 'No'}</td>
                      <td>{t.blocks_completion ? 'Yes' : 'No'}</td>
                      <td>{t.requires_evidence ? 'Yes' : 'No'}</td>
                      <td>{t.due_offset_days != null ? `${t.due_offset_days} days` : '—'}</td>
                      <td>{t.automation_type === 'none' ? 'None' : t.automation_type.replace(/_/g, ' ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="table-summary">
                <p className="muted small">
                  Total tasks: {templateItems.length} &middot;
                  Required: {templateItems.filter((t) => t.required).length} &middot;
                  Blocking: {templateItems.filter((t) => t.blocks_completion).length} &middot;
                  Evidence required: {templateItems.filter((t) => t.requires_evidence).length}
                </p>
              </div>
            </div>
          ) : (!selectedTemplate && form.template_id ? (
            <p className="muted">No checklist items found for this template.</p>
          ) : (
            <p className="muted">Select a template on Step 1 to preview its checklist.</p>
          ))}
        </div>

        {/* ===== STEP 4: Review ===== */}
        <div className={`wizard-step ${step === 4 ? '' : 'hidden'}`}>
          <dl className="detail-grid">
            <dt>Case Type</dt><dd>{CASE_TYPE_LABELS[form.case_type] ?? form.case_type}</dd>
            <dt>Employee</dt><dd>{selectedEmployee ? `${selectedEmployee.employee_id} — ${selectedEmployee.email}` : '—'}</dd>
            <dt>Template</dt><dd>{selectedTemplate ? `${selectedTemplate.code} — ${selectedTemplate.name}` : '—'}</dd>
            <dt>Priority</dt><dd>{PRIORITY_LABELS[form.priority] ?? form.priority}</dd>
            <dt>Planned Date</dt><dd>{formatDate(form.planned_date)}</dd>
            <dt>Effective Date</dt><dd>{formatDate(form.effective_date)}</dd>
            <dt>Completion Target</dt><dd>{formatDate(form.completion_target)}</dd>
            <dt>Department</dt><dd>{selectedDepartment ? selectedDepartment.name : 'Employee home department'}</dd>
            <dt>Coordinator</dt><dd>{form.assigned_coordinator ? String(form.assigned_coordinator) : 'Unassigned'}</dd>
            {isTransfer && <><dt>New Department</dt><dd>{form.new_department ? String(form.new_department) : '—'}</dd></>}
            <dt>Task Count</dt><dd>{templateItems.length}</dd>
            <dt>Required Tasks</dt><dd>{templateItems.filter((t) => t.required).length}</dd>
            <dt>Blocking Tasks</dt><dd>{templateItems.filter((t) => t.blocks_completion).length}</dd>
            <dt>Evidence Requirements</dt><dd>{templateItems.filter((t) => t.requires_evidence).length} task(s) require evidence</dd>
            <dt>Automation Warnings</dt>
            <dd>
              {templateItems.some((t) => t.automation_type !== 'none')
                ? 'Some tasks have automation configured. Automations run server-side when tasks complete.'
                : 'No automation configured.'}
            </dd>
          </dl>
          <div className="alert alert-info" role="status">
            <strong>Read-only fields:</strong> case number, status, progress, and
            version are set by the server and cannot be specified in this form.
          </div>
        </div>

        <div className="row-end" style={{ marginTop: 'var(--sp-3)' }}>
          {step > 1 && (
            <button type="button" className="btn-ghost" onClick={prevStep} disabled={submitting}>
              ← Back
            </button>
          )}
          {step < 4 ? (
            <button type="button" className="btn-primary" onClick={() => {
              if (canProceed(step)) nextStep();
            }} disabled={submitting || !canProceed(step)}>
              {step === 3 ? 'Review' : 'Next'}
            </button>
          ) : (
            <>
              <button type="button" className="btn-ghost" onClick={prevStep} disabled={submitting}>
                ← Back
              </button>
              <button type="submit" className="btn-primary" disabled={submitting}>
                {submitting ? 'Creating…' : 'Create Case'}
              </button>
            </>
          )}
        </div>
      </form>

      <style>{`
        .lifecycle-form .hidden { display: none; }
        .lifecycle-form .stepper { display: flex; gap: var(--sp-1); margin: var(--sp-2) 0; }
        .lifecycle-form .step { flex: 1; display: flex; align-items: center; gap: var(--sp-05); font-size: 0.9rem; }
        .lifecycle-form .step-badge { width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 600; flex-shrink: 0; }
        .lifecycle-form .step.todo .step-badge { background: #e9ecef; color: #6c757d; border: 1px solid #ced4da; }
        .lifecycle-form .step.done .step-badge { background: #198754; color: #fff; }
        .lifecycle-form .step.current .step-badge { background: #0d6efd; color: #fff; }
        .lifecycle-form .step.done .step-label { color: #6c757d; text-decoration: line-through; }
        .lifecycle-form .step.current .step-label { color: #0d6efd; font-weight: 600; }
        .lifecycle-form .detail-grid { display: grid; grid-template-columns: 180px 1fr; gap: var(--sp-1) var(--sp-2); margin: var(--sp-2) 0; }
        .lifecycle-form .detail-grid dt { margin: 0; font-weight: 600; color: #495057; }
        .lifecycle-form .detail-grid dd { margin: 0 0 var(--sp-1) 0; padding: 0; }
        .wizard-step { margin-top: var(--sp-2); }
      `}</style>
    </div>
  );
}
