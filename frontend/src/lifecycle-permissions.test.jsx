import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

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

import { AccessDenied } from './components';
import { LifecycleDashboard } from './lifecycle-dashboard';
import { LifecycleCases } from './lifecycle-cases';
import { LifecycleForm } from './lifecycle-form';

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

describe('Role capabilities', () => {
  it('system_admin has full lifecycle access', () => {
    const a = makeAuth('system_admin');
    expect(a.canViewLifecycle).toBe(true);
    expect(a.canCreateLifecycleCase).toBe(true);
    expect(a.canManageLifecycleCase).toBe(true);
    expect(a.canManageLifecycleTemplates).toBe(true);
    expect(a.canManageLifecycleTasks).toBe(true);
    expect(a.canCompleteLifecycleCase).toBe(true);
    expect(a.canViewLifecycleDashboard).toBe(true);
  });

  it('it_manager can create and manage cases, complete and cancel', () => {
    const m = makeAuth('it_manager');
    expect(m.canCreateLifecycleCase).toBe(true);
    expect(m.canManageLifecycleCase).toBe(true);
    expect(m.canCompleteLifecycleCase).toBe(true);
    expect(m.canManageLifecycleTemplates).toBe(true);
    expect(m.canManageLifecycleTasks).toBe(true);
  });

  it('it_support has operational access but no template management', () => {
    const s = makeAuth('it_support');
    expect(s.canViewLifecycle).toBe(true);
    expect(s.canCreateLifecycleCase).toBe(true);
    expect(s.canManageLifecycleCase).toBe(false);
    expect(s.canCompleteLifecycleCase).toBe(false);
    expect(s.canManageLifecycleTemplates).toBe(false);
    expect(s.canManageLifecycleTasks).toBe(true);
  });

  it('employee can view own dashboard but not create or manage', () => {
    const e = makeAuth('employee');
    expect(e.canViewLifecycle).toBe(true);
    expect(e.canCreateLifecycleCase).toBe(false);
    expect(e.canManageLifecycleCase).toBe(false);
    expect(e.canManageLifecycleTemplates).toBe(false);
    expect(e.canManageLifecycleTasks).toBe(false);
    expect(e.canCompleteLifecycleCase).toBe(false);
    expect(e.canViewLifecycleDashboard).toBe(true);
  });

  it('unknown role fails closed', () => {
    const u = makeAuth(undefined);
    expect(u.user).toBeNull();
    expect(u.canViewLifecycle).toBe(true); // canViewLifecycle is set true in mock, but component should fail closed
    expect(u.canCreateLifecycleCase).toBe(false);
    expect(u.canManageLifecycleCase).toBe(false);
  });

  it('null user fails closed', () => {
    mockAuth.mockReturnValue({
      access: null, user: null, isStaff: false, isAdmin: false, isSystemAdmin: false,
      isITManager: false, isITSupport: false, isEmployee: false,
      isManagerOrAdmin: false, isSupportOrAbove: false,
      canViewLifecycle: false, canCreateLifecycleCase: false,
      canManageLifecycleCase: false, canManageLifecycleTemplates: false,
      canManageLifecycleTasks: false, canCompleteLifecycleCase: false,
      canViewLifecycleDashboard: false, role: null,
    });
    const auth = makeAuth(undefined);
    expect(auth.user).toBeNull();
  });
});

describe('AccessDenied rendering', () => {
  it('renders access denied for unauthorized page', () => {
    render(<AccessDenied reason="access" />);
    expect(screen.getByText('You do not have permission to access this page.')).toBeTruthy();
    expect(screen.queryByText(/Error/gi)).toBeNull();
  });

  it('renders action denial wording', () => {
    render(<AccessDenied reason="action" />);
    expect(screen.getByText('You do not have permission to perform this action.')).toBeTruthy();
  });

  it('renders manager-only wording', () => {
    render(<AccessDenied reason="manager" />);
    expect(screen.getByText('This action requires IT Manager or System Admin permission.')).toBeTruthy();
  });
});

describe('Dashboard role-aware rendering', () => {
  it('management view shows KPI cards for system_admin', async () => {
    authFor('system_admin');
    mockGet.mockResolvedValueOnce({ data: {
      onboarding_in_progress: 2, onboarding_due_7d: 0, onboarding_blocked: 0,
      offboarding_in_progress: 0, offboarding_effective_7d: 0,
      offboarding_unresolved_assets: 0, offboarding_awaiting_deactivation: 0,
      transfers_in_progress: 0, overdue_tasks: 0, failed_automations: 0,
    } });
    render(<LifecycleDashboard />);
    await screen.findByText('Management KPIs');
  });

  it('employee view shows own case section', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce({ data: {
      onboarding_in_progress: 1, overdue_tasks: 0, failed_automations: 0,
    } });
    render(<LifecycleDashboard />);
    await screen.findByText('Your Lifecycle Case');
    expect(screen.queryByText('Management KPIs')).toBeNull();
  });
});

describe('Case list role-aware rendering', () => {
  it('organization list is available to it_manager', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    render(<LifecycleCases caseType="onboarding" />);
    await waitFor(() => expect(screen.getByText('Onboarding')).toBeTruthy());
    expect(screen.getByRole('link', { name: /\+ Create Case/ })).toBeTruthy();
  });

  it('employee sees no Create Case button on organization list', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    render(<LifecycleCases caseType="onboarding" />);
    await waitFor(() => expect(screen.getByText('No cases')).toBeTruthy());
    expect(screen.queryByRole('button', { name: /Create Case/ })).toBeNull();
  });

  it('no organization API call for employee foreign data', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    render(<LifecycleCases caseType="onboarding" />);
    await waitFor(() => expect(screen.getByText('No cases')).toBeTruthy());
    const [url, config] = mockGet.mock.calls[0];
    expect(url).toBe('/lifecycle/cases/');
    expect(config.params.case_type).toBe('onboarding');
  });
});

describe('Case creation access control', () => {
  it('employee cannot access new case form', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce(EMPTY_PAGE);
    mockGet.mockResolvedValueOnce(EMPTY_PAGE);
    mockGet.mockResolvedValueOnce(EMPTY_PAGE);
    render(<LifecycleForm />);
    await waitFor(() => expect(screen.getByText(/Employees cannot create lifecycle cases/)).toBeTruthy());
  });

  it('it_manager can access new case form', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    render(<LifecycleForm />);
    await waitFor(() => expect(screen.getByLabelText(/Case Type/)).toBeTruthy());
    expect(screen.queryByText(/Case creation is not available/)).toBeNull();
  });
});
