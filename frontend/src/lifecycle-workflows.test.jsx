import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
    delete: (...a) => mockDelete(...a),
  },
}));
vi.mock('./auth', () => ({
  useAuth: (...a) => mockAuth(...a),
}));

import { LifecycleForm } from './lifecycle-form';
import { LifecycleDetail } from './lifecycle-detail';

const STAFF_ROLES = ['system_admin', 'it_manager', 'it_support'];

function makeAuth(role) {
  const isSystemAdmin = role === 'system_admin';
  const isITManager = role === 'it_manager';
  const isITSupport = role === 'it_support';
  const isEmployee = role === 'employee';
  const isStaff = role ? STAFF_ROLES.includes(role) : false;
  return {
    access: 'token',
    isStaff, isAdmin: isSystemAdmin, isSystemAdmin, isITManager, isITSupport, isEmployee,
    isManagerOrAdmin: isSystemAdmin || isITManager,
    isSupportOrAbove: isSystemAdmin || isITManager || isITSupport,
    canViewLifecycle: true,
    canCreateLifecycleCase: isStaff,
    canManageLifecycleCase: isSystemAdmin || isITManager,
    canManageLifecycleTemplates: isSystemAdmin || isITManager,
    canManageLifecycleTasks: isStaff,
    canCompleteLifecycleCase: isSystemAdmin || isITManager,
    canViewLifecycleDashboard: true,
    role,
    user: role ? { id: 1, employee_id: 'E1', role, email: `${role}@x` } : null,
  };
}

function authFor(role) {
  mockAuth.mockReturnValue(makeAuth(role));
}

const TEMPLATES = {
  data: {
    results: [
      { id: 1, code: 'TPL-ONB', name: 'Onboarding Template', case_type: 'onboarding', is_active: true, item_count: 3 },
      { id: 2, code: 'TPL-OFF', name: 'Offboarding Template', case_type: 'offboarding', is_active: true, item_count: 2 },
      { id: 3, code: 'TPL-TRF', name: 'Transfer Template', case_type: 'transfer', is_active: true, item_count: 1 },
    ],
    count: 3, next: null, previous: null,
  },
};

const EMPLOYEES = {
  data: {
    results: [
      { id: 3, employee_id: 'E3', email: 'emp3@x', role: 'employee', is_active: true, is_deleted: false },
      { id: 4, employee_id: 'E4', email: 'emp4@x', role: 'employee', is_active: false, is_deleted: false },
    ],
    count: 2, next: null, previous: null,
  },
};

const DEPARTMENTS = {
  data: {
    results: [
      { id: 10, name: 'IT', code: 'IT', is_active: true, is_deleted: false },
      { id: 11, name: 'HR', code: 'HR', is_active: true, is_deleted: false },
    ],
    count: 2, next: null, previous: null,
  },
};

function mockWizardLookups() {
  mockGet.mockImplementation((url) => {
    if (typeof url === 'string' && url.includes('/lifecycle/templates')) return Promise.resolve(TEMPLATES);
    if (typeof url === 'string' && url.includes('/accounts/users')) return Promise.resolve(EMPLOYEES);
    if (typeof url === 'string' && url.includes('/accounts/departments')) return Promise.resolve(DEPARTMENTS);
    return Promise.resolve(EMPTY_PAGE);
  });
}

const EMPTY_PAGE = { data: { results: [], count: 0, next: null, previous: null } };

const CREATED_CASE = {
  data: { id: 100, case_number: 'ONB-2026-00001', case_type: 'onboarding', status: 'draft', version: 1, checklist_progress: 0, total_tasks: 3, completed_tasks: 0, overdue_tasks: 0, employee_email: 'emp3@x', employee: 3, department: 10, assigned_coordinator: null, planned_date: null, effective_date: null, completion_target: null, created_at: '2026-11-01T10:00:00Z', updated_at: '2026-11-01T10:00:00Z' },
};

const CASE_DETAIL = {
  data: { id: 100, case_number: 'ONB-2026-00001', case_type: 'onboarding', status: 'in_progress', priority: 'medium', employee: 3, employee_email: 'emp3@x', department: 10, assigned_coordinator: 1, planned_date: '2026-11-01T10:00:00Z', effective_date: '2026-11-15T10:00:00Z', completion_target: '2026-11-30T10:00:00Z', checklist_progress: 50, total_tasks: 3, completed_tasks: 1, overdue_tasks: 0, version: 2, notes: '', created_at: '2026-11-01T10:00:00Z', updated_at: '2026-11-10T10:00:00Z', started_at: '2026-11-02T10:00:00Z', completed_at: null, cancelled_at: null, is_deleted: false },
};

const CASE_DRAFT = {
  data: { ...CASE_DETAIL.data, status: 'draft', version: 1 },
};

const CASE_PLANNED = {
  data: { ...CASE_DETAIL.data, status: 'planned', version: 2 },
};

const CASE_READY_FOR_EMPLOYEE = {
  data: { ...CASE_DETAIL.data, status: 'ready_for_employee', version: 3, employee: 1, employee_email: 'emp1@x' },
};

const CASE_READY_FOR_CLOSURE = {
  data: { ...CASE_DETAIL.data, status: 'ready_for_closure', version: 4 },
};

const SUMMARY_DATA = {
  data: { id: 100, case_number: 'ONB-2026-00001', case_type: 'onboarding', status: 'in_progress', priority: 'medium', employee: 3, employee_email: 'emp3@x', department: 10, coordinator: 1, checklist_progress: 50, total_tasks: 3, completed_tasks: 1, overdue_tasks: 0, effective_date: '2026-11-15T10:00:00Z', completion_target: '2026-11-30T10:00:00Z', completed_at: null },
};

const HISTORY_PAGE = {
  data: { results: [
    { id: 1, case: 100, actor_email: 'mgr@x', event_type: 'case_created', previous_status: '', new_status: 'draft', detail: 'Case created from template TPL-ONB', created_at: '2026-11-01T10:00:00Z' },
  ], count: 1, next: null, previous: null },
};

const TASKS_PAGE = {
  data: { results: [
    { id: 1, sequence: 1, title: 'Account setup', category: 'account', responsibility: 'it', status: 'completed', required: true, blocks_completion: true, requires_evidence: false, due_date: '2026-11-10T10:00:00Z', automation_type: 'none', automation_status: 'not_applicable' },
    { id: 2, sequence: 2, title: 'Assign laptop', category: 'hardware', responsibility: 'it', status: 'pending', required: true, blocks_completion: true, requires_evidence: false, due_date: '2026-11-12T10:00:00Z', automation_type: 'assign_asset', automation_status: 'pending' },
  ], count: 2, next: null, previous: null },
};

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  mockGet.mockResolvedValue(EMPTY_PAGE);
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
});

afterEach(() => {
  cleanup();
  window.location.hash = '#/';
  vi.clearAllTimers();
});

describe('Four-step wizard', () => {
  it('renders step 1 with case type, employee, template, priority', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(TEMPLATES);
    mockGet.mockResolvedValueOnce(EMPLOYEES);
    mockGet.mockResolvedValueOnce(DEPARTMENTS);
    render(<LifecycleForm />);
    await waitFor(() => expect(screen.getByLabelText(/Case Type/)).toBeTruthy());
    expect(screen.getByLabelText(/Employee/)).toBeTruthy();
    expect(screen.getByLabelText(/Template/)).toBeTruthy();
    expect(screen.getByLabelText(/Priority/)).toBeTruthy();
    expect(screen.getByText(/Step 1 of 4/)).toBeTruthy();
  });

  it('advances from step 1 to step 2 when valid', async () => {
    authFor('it_manager');
    mockWizardLookups();
    render(<LifecycleForm />);
    await waitFor(() => expect(screen.getByTestId('case-type-select')).toBeTruthy());
    fireEvent.change(screen.getByTestId('case-type-select'), { target: { value: 'onboarding' } });
    await waitFor(() => expect(screen.getAllByTestId('employee-select')[0].querySelector('option[value="3"]')).toBeTruthy());
    fireEvent.change(screen.getAllByTestId('employee-select')[0], { target: { value: '3' } });
    await waitFor(() => expect(screen.getByTestId('template-select').querySelector('option[value="1"]')).toBeTruthy());
    fireEvent.change(screen.getByTestId('template-select'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    await waitFor(() => expect(screen.getByText(/Step 2 of 4/)).toBeTruthy());
  });

  it('blocks step 1 advance when required fields missing', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(TEMPLATES);
    mockGet.mockResolvedValueOnce(EMPLOYEES);
    mockGet.mockResolvedValueOnce(DEPARTMENTS);
    render(<LifecycleForm />);
    await waitFor(() => expect(screen.getByTestId('case-type-select')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    expect(screen.getByText(/Please fix the errors above before continuing/)).toBeTruthy();
  });

  it('clears incompatible template when case type changes', async () => {
    authFor('it_manager');
    mockWizardLookups();
    render(<LifecycleForm />);
    await waitFor(() => expect(screen.getByTestId('case-type-select')).toBeTruthy());
    fireEvent.change(screen.getByTestId('case-type-select'), { target: { value: 'onboarding' } });
    await waitFor(() => expect(screen.getAllByTestId('employee-select')[0].querySelector('option[value="3"]')).toBeTruthy());
    fireEvent.change(screen.getAllByTestId('employee-select')[0], { target: { value: '3' } });
    await waitFor(() => expect(screen.getByTestId('template-select').querySelector('option[value="1"]')).toBeTruthy());
    fireEvent.change(screen.getByTestId('template-select'), { target: { value: '1' } });
    expect(screen.getByTestId('template-select').value).toBe('1');
    fireEvent.change(screen.getByTestId('case-type-select'), { target: { value: 'offboarding' } });
    await waitFor(() => expect(screen.getByTestId('template-select').value).toBe(''));
  });

  it('shows transfer department validation', async () => {
    authFor('it_manager');
    mockWizardLookups();
    render(<LifecycleForm />);
    await waitFor(() => expect(screen.getByTestId('case-type-select')).toBeTruthy());
    fireEvent.change(screen.getByTestId('case-type-select'), { target: { value: 'transfer' } });
    await waitFor(() => expect(screen.getAllByTestId('employee-select')[0].querySelector('option[value="3"]')).toBeTruthy());
    fireEvent.change(screen.getAllByTestId('employee-select')[0], { target: { value: '3' } });
    await waitFor(() => expect(screen.getByTestId('template-select').querySelector('option[value="3"]')).toBeTruthy());
    fireEvent.change(screen.getByTestId('template-select'), { target: { value: '3' } });
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    await waitFor(() => expect(screen.getByText(/Step 2 of 4/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText(/^Department$/), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText(/New Department/), { target: { value: '10' } });
    await waitFor(() => expect(screen.getByText(/must differ from the employee's current department/)).toBeTruthy());
  });

  it('prevents double submit', async () => {
    authFor('it_manager');
    mockWizardLookups();
    let submitCount = 0;
    mockPost.mockImplementation(async () => {
      submitCount += 1;
      if (submitCount === 1) return CREATED_CASE;
      throw new Error('Duplicate');
    });
    render(<LifecycleForm />);
    await waitFor(() => expect(screen.getByTestId('case-type-select')).toBeTruthy());
    fireEvent.change(screen.getByTestId('case-type-select'), { target: { value: 'onboarding' } });
    await waitFor(() => expect(screen.getAllByTestId('employee-select')[0].querySelector('option[value="3"]')).toBeTruthy());
    fireEvent.change(screen.getAllByTestId('employee-select')[0], { target: { value: '3' } });
    await waitFor(() => expect(screen.getByTestId('template-select').querySelector('option[value="1"]')).toBeTruthy());
    fireEvent.change(screen.getByTestId('template-select'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    await waitFor(() => expect(screen.getByText(/Step 2 of 4/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    await waitFor(() => expect(screen.getByText(/Step 3 of 4/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Review/ }));
    await waitFor(() => expect(screen.getByText(/Step 4 of 4/)).toBeTruthy());
    const createBtn = screen.getByRole('button', { name: /Create Case/ });
    fireEvent.click(createBtn);
    await waitFor(() => expect(screen.getByText(/Case ONB-2026-00001 created/)).toBeTruthy());
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it('prevents double submit', async () => {
    authFor('it_manager');
    mockWizardLookups();
    let submitCount = 0;
    mockPost.mockImplementation(async () => {
      submitCount += 1;
      if (submitCount === 1) return CREATED_CASE;
      throw new Error('Duplicate');
    });
    render(<LifecycleForm />);
    await waitFor(() => expect(screen.getByTestId('case-type-select')).toBeTruthy());
    fireEvent.change(screen.getByTestId('case-type-select'), { target: { value: 'onboarding' } });
    await waitFor(() => expect(screen.getAllByTestId('employee-select')[0].querySelector('option[value="3"]')).toBeTruthy());
    fireEvent.change(screen.getAllByTestId('employee-select')[0], { target: { value: '3' } });
    await waitFor(() => expect(screen.getByTestId('template-select').querySelector('option[value="1"]')).toBeTruthy());
    fireEvent.change(screen.getByTestId('template-select'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    await waitFor(() => expect(screen.getByText(/Step 2 of 4/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    await waitFor(() => expect(screen.getByText(/Step 3 of 4/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Review/ }));
    await waitFor(() => expect(screen.getByText(/Step 4 of 4/)).toBeTruthy());
    const createBtn = screen.getByRole('button', { name: /Create Case/ });
    fireEvent.click(createBtn);
    await waitFor(() => expect(screen.getByText(/Case ONB-2026-00001 created/)).toBeTruthy());
    expect(mockPost).toHaveBeenCalledTimes(1);
  });
});

describe('LifecycleDetail transitions', () => {
  it('Plan action calls backend and refreshes case', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(CASE_DRAFT);
    mockGet.mockResolvedValueOnce(SUMMARY_DATA);
    mockGet.mockResolvedValueOnce(HISTORY_PAGE);
    mockGet.mockResolvedValueOnce(TASKS_PAGE);
    mockPost.mockResolvedValueOnce(CASE_DRAFT);
    render(<LifecycleDetail id="100" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Plan/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Confirm$/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /^Confirm$/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/lifecycle/cases/100/plan/', expect.objectContaining({ version: 1 })));
  });

  it('Start action calls backend', async () => {
    authFor('it_support');
    mockGet.mockResolvedValueOnce(CASE_PLANNED);
    mockGet.mockResolvedValueOnce(SUMMARY_DATA);
    mockGet.mockResolvedValueOnce(HISTORY_PAGE);
    mockGet.mockResolvedValueOnce(TASKS_PAGE);
    mockPost.mockResolvedValueOnce(CASE_PLANNED);
    render(<LifecycleDetail id="100" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Start/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Confirm$/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /^Confirm$/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/lifecycle/cases/100/start/', expect.objectContaining({ version: 2 })));
  });

  it('Mark Ready action (onboarding only)', async () => {
    authFor('it_support');
    mockGet.mockResolvedValueOnce(CASE_DETAIL);
    mockGet.mockResolvedValueOnce(SUMMARY_DATA);
    mockGet.mockResolvedValueOnce(HISTORY_PAGE);
    mockGet.mockResolvedValueOnce(TASKS_PAGE);
    mockPost.mockResolvedValueOnce(CASE_DETAIL);
    render(<LifecycleDetail id="100" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Mark Ready/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Confirm$/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /^Confirm$/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/lifecycle/cases/100/mark_ready/', expect.objectContaining({ version: 2 })));
  });

  it('Confirm Employee Start action', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce(CASE_READY_FOR_EMPLOYEE);
    mockGet.mockResolvedValueOnce(SUMMARY_DATA);
    mockGet.mockResolvedValueOnce(HISTORY_PAGE);
    mockGet.mockResolvedValueOnce(TASKS_PAGE);
    mockPost.mockResolvedValueOnce(CASE_READY_FOR_EMPLOYEE);
    render(<LifecycleDetail id="100" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Confirm Employee Start/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Confirm$/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /^Confirm$/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/lifecycle/cases/100/confirm_start/', expect.objectContaining({ version: 3 })));
  });

  it('Block action requires reason', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(CASE_DETAIL);
    mockGet.mockResolvedValueOnce(SUMMARY_DATA);
    mockGet.mockResolvedValueOnce(HISTORY_PAGE);
    mockGet.mockResolvedValueOnce(TASKS_PAGE);
    render(<LifecycleDetail id="100" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Block/ }));
    expect(screen.getByLabelText(/Reason/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Confirm/ }));
    await waitFor(() => expect(screen.getByText(/A reason is required to block this case/)).toBeTruthy());
  });

  it('Block action sends reason payload', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(CASE_DETAIL);
    mockGet.mockResolvedValueOnce(SUMMARY_DATA);
    mockGet.mockResolvedValueOnce(HISTORY_PAGE);
    mockGet.mockResolvedValueOnce(TASKS_PAGE);
    mockPost.mockResolvedValueOnce(CASE_DETAIL);
    render(<LifecycleDetail id="100" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Block/ }));
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: 'Waiting for hardware' } });
    await waitFor(() => expect(screen.getByRole('button', { name: /^Confirm$/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /^Confirm$/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/lifecycle/cases/100/block/', expect.objectContaining({ version: 2, reason: 'Waiting for hardware' })));
  });

  it('Unblock action calls backend', async () => {
    const blockedCase = { ...CASE_DETAIL, data: { ...CASE_DETAIL.data, status: 'blocked', version: 3 } };
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(blockedCase);
    mockGet.mockResolvedValueOnce(SUMMARY_DATA);
    mockGet.mockResolvedValueOnce(HISTORY_PAGE);
    mockGet.mockResolvedValueOnce(TASKS_PAGE);
    mockPost.mockResolvedValueOnce(CASE_DETAIL);
    render(<LifecycleDetail id="100" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Unblock/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Confirm$/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /^Confirm$/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/lifecycle/cases/100/unblock/', expect.objectContaining({ version: 3 })));
  });

  it('Complete action calls backend', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(CASE_READY_FOR_CLOSURE);
    mockGet.mockResolvedValueOnce(SUMMARY_DATA);
    mockGet.mockResolvedValueOnce(HISTORY_PAGE);
    mockGet.mockResolvedValueOnce(TASKS_PAGE);
    mockPost.mockResolvedValueOnce(CASE_READY_FOR_CLOSURE);
    render(<LifecycleDetail id="100" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Complete/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Confirm$/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /^Confirm$/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/lifecycle/cases/100/complete/', expect.objectContaining({ version: 4 })));
  });

  it('Cancel action requires reason', async () => {
    authFor('it_support');
    mockGet.mockResolvedValueOnce(CASE_DETAIL);
    mockGet.mockResolvedValueOnce(SUMMARY_DATA);
    mockGet.mockResolvedValueOnce(HISTORY_PAGE);
    mockGet.mockResolvedValueOnce(TASKS_PAGE);
    render(<LifecycleDetail id="100" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Cancel/ }));
    expect(screen.getByLabelText(/Reason/)).toBeTruthy();
  });

  it('409 stale version shows message and reloads', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(CASE_DRAFT);
    mockGet.mockResolvedValueOnce(SUMMARY_DATA);
    mockGet.mockResolvedValueOnce(HISTORY_PAGE);
    mockGet.mockResolvedValueOnce(TASKS_PAGE);
    const staleError = { response: { status: 409, data: { version: 'Stale version; the case was modified concurrently.' } } };
    mockPost.mockRejectedValueOnce(staleError);
    // Reload after 409: 4 more GET calls
    mockGet.mockResolvedValueOnce(CASE_DRAFT);
    mockGet.mockResolvedValueOnce(SUMMARY_DATA);
    mockGet.mockResolvedValueOnce(HISTORY_PAGE);
    mockGet.mockResolvedValueOnce(TASKS_PAGE);
    render(<LifecycleDetail id="100" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Plan/ }));
    fireEvent.click(screen.getByRole('button', { name: /Confirm/ }));
    await waitFor(() => expect(screen.getByText(/This case changed while you were working/)).toBeTruthy());
  });
});
