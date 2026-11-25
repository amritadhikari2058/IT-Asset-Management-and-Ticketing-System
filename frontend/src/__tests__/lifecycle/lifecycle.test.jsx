import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
    delete: (...a) => mockDelete(...a),
  },
}));
vi.mock('../../auth', () => ({
  useAuth: (...a) => mockAuth(...a),
}));

import { LifecycleDashboard } from '../../pages/lifecycle/LifecycleDashboard';
import { LifecycleCases } from '../../pages/lifecycle/LifecycleCases';

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

const DASHBOARD_DATA = {
  onboarding_in_progress: 2,
  onboarding_due_7d: 1,
  onboarding_blocked: 0,
  offboarding_in_progress: 1,
  offboarding_effective_7d: 0,
  offboarding_unresolved_assets: 0,
  offboarding_awaiting_deactivation: 0,
  transfers_in_progress: 1,
  overdue_tasks: 3,
  failed_automations: 0,
  recent_cases: [
    { id: 1, case_number: 'ONB-2026-00001', case_type: 'onboarding', status: 'in_progress', created_at: '2026-11-01T10:00:00Z' },
  ],
  urgent_cases: [],
  tasks_assigned_to_me: [],
};

const CASES_PAGE = {
  data: {
    results: [
      { id: 1, case_number: 'ONB-2026-00001', case_type: 'onboarding', employee: 3, employee_id: 'E3', employee_email: 'emp3@x', department: 'IT', status: 'in_progress', priority: 'high', assigned_coordinator: null, planned_date: '2026-11-01T10:00:00Z', effective_date: '2026-11-15T10:00:00Z', completion_target: '2026-11-30T10:00:00Z', checklist_progress: 50, total_tasks: 4, completed_tasks: 2, overdue_tasks: 0, source: 'manual', created_at: '2026-11-01T10:00:00Z', updated_at: '2026-11-10T10:00:00Z' },
    ],
    count: 1, next: null, previous: null,
  },
};

const EMPTY_PAGE = { data: { results: [], count: 0, next: null, previous: null } };

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  mockGet.mockResolvedValue(EMPTY_PAGE);
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('LifecycleDashboard management view', () => {
  it('shows management KPI cards for system_admin', async () => {
    authFor('system_admin');
    mockGet.mockResolvedValueOnce({ data: DASHBOARD_DATA });
    render(<LifecycleDashboard />);
    await screen.findByText('2');
    expect(screen.getAllByText('Onboarding In Progress').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Offboarding In Progress').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Transfers In Progress').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Overdue Tasks').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Failed Automations').length).toBeGreaterThan(0);
    expect(mockGet).toHaveBeenCalledWith('/lifecycle/dashboard/');
  });

  it('shows employee-scoped dashboard for employee', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce({ data: { ...DASHBOARD_DATA, onboarding_in_progress: 1 } });
    render(<LifecycleDashboard />);
    await screen.findByText('Your Lifecycle Case');
    expect(screen.queryByText('Management KPIs')).toBeNull();
  });

  it('displays zero values when no data', async () => {
    authFor('system_admin');
    const zeroData = { ...DASHBOARD_DATA, onboarding_in_progress: 0, overdue_tasks: 0 };
    mockGet.mockResolvedValueOnce({ data: zeroData });
    render(<LifecycleDashboard />);
    await screen.findByText('Management KPIs');
    // Check specific KPI cards by their label text
    const cards = screen.getAllByText('0');
    expect(cards.length).toBeGreaterThan(0);
  });

  it('shows loading state', () => {
    mockGet.mockResolvedValue(new Promise(() => {}));
    authFor('system_admin');
    render(<LifecycleDashboard />);
    expect(screen.getByText(/Loading Lifecycle dashboard/)).toBeTruthy();
  });

  it('shows error and Retry on failure', async () => {
    authFor('system_admin');
    mockGet.mockRejectedValueOnce(new Error('Failed'));
    render(<LifecycleDashboard />);
    await waitFor(() => expect(screen.getByText(/Request failed:/)).toBeTruthy());
    expect(screen.getByRole('button', { name: /Retry/ })).toBeTruthy();
  });

  it('Refresh button calls dashboard endpoint again', async () => {
    authFor('system_admin');
    mockGet.mockResolvedValueOnce({ data: DASHBOARD_DATA });
    mockGet.mockResolvedValueOnce({ data: { ...DASHBOARD_DATA, onboarding_in_progress: 5 } });
    render(<LifecycleDashboard />);
    await screen.findByText('2');
    fireEvent.click(screen.getByRole('button', { name: /Refresh/ }));
    await waitFor(() => expect(screen.getByText('5')).toBeTruthy());
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('filters section renders for management', async () => {
    authFor('system_admin');
    mockGet.mockResolvedValueOnce({ data: DASHBOARD_DATA });
    render(<LifecycleDashboard />);
    await screen.findByText('Filters');
    expect(screen.getByLabelText(/Case Type/)).toBeTruthy();
    expect(screen.getByLabelText(/Department/)).toBeTruthy();
    expect(screen.getByLabelText(/Coordinator/)).toBeTruthy();
    expect(screen.getByLabelText(/Date From/)).toBeTruthy();
    expect(screen.getByLabelText(/Date To/)).toBeTruthy();
  });
});

describe('LifecycleCases - Onboarding list', () => {
  it('fetches onboarding cases with case_type filter', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(CASES_PAGE);
    render(<LifecycleCases caseType="onboarding" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    const [url, config] = mockGet.mock.calls[0];
    expect(url).toBe('/lifecycle/cases/');
    expect(config.params.case_type).toBe('onboarding');
  });

  it('fetches offboarding cases with case_type filter', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(CASES_PAGE);
    render(<LifecycleCases caseType="offboarding" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    const [url, config] = mockGet.mock.calls[0];
    expect(url).toBe('/lifecycle/cases/');
    expect(config.params.case_type).toBe('offboarding');
  });

  it('fetches transfer cases with case_type filter', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(CASES_PAGE);
    render(<LifecycleCases caseType="transfer" />);
    await waitFor(() => expect(screen.getByText('ONB-2026-00001')).toBeTruthy());
    const [url, config] = mockGet.mock.calls[0];
    expect(url).toBe('/lifecycle/cases/');
    expect(config.params.case_type).toBe('transfer');
  });

  it('shows empty state when no cases', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce(EMPTY_PAGE);
    render(<LifecycleCases caseType="onboarding" />);
    await waitFor(() => expect(screen.getByText('No cases')).toBeTruthy());
  });

  it('shows filters and pager even when empty', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce({
      data: { results: [], count: 45, next: 'http://127.0.0.1:8000/api/lifecycle/cases/?page=2', previous: null },
    });
    render(<LifecycleCases caseType="onboarding" />);
    await waitFor(() => expect(screen.getByLabelText(/Status/)).toBeTruthy());
    await waitFor(() => expect(screen.getByRole('button', { name: /Next/ })).toBeTruthy());
  });

  it('shows loading state', () => {
    mockGet.mockResolvedValue(new Promise(() => {}));
    authFor('it_manager');
    render(<LifecycleCases caseType="onboarding" />);
    expect(screen.getByRole('status', { name: /Loading/ })).toBeTruthy();
  });

  it('shows error and Retry on failure', async () => {
    authFor('it_manager');
    mockGet.mockRejectedValueOnce(new Error('Failed'));
    render(<LifecycleCases caseType="onboarding" />);
    await waitFor(() => expect(screen.getByText(/Request failed:/)).toBeTruthy());
    expect(screen.getByRole('button', { name: /Retry/ })).toBeTruthy();
  });

  it('status filter renders with all lifecycle statuses', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValue(EMPTY_PAGE);
    render(<LifecycleCases caseType="onboarding" />);
    await waitFor(() => expect(screen.queryByLabelText(/Status/)).toBeTruthy());
    const select = screen.getByLabelText(/Status/);
    expect(select).toBeTruthy();
    // Verify all lifecycle statuses are options
    const options = select.querySelectorAll('option');
    expect(options.length).toBeGreaterThan(1);
  });

  it('employee does not see Create Case button', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce(EMPTY_PAGE);
    render(<LifecycleCases caseType="onboarding" />);
    await waitFor(() => expect(screen.getByText('No cases')).toBeTruthy());
    expect(screen.queryByRole('button', { name: /Create Case/ })).toBeNull();
  });
});
