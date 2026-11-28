import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent, act } from '@testing-library/react';

const { mockFetchPage, mockPost, mockPatch, mockAuth } = vi.hoisted(() => ({
  mockFetchPage: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../shared/changes-utils', () => ({
  fetchPage: (...args) => mockFetchPage(...args),
  parseApiError: vi.fn(() => ({ global: 'Error' })),
  STATUS_LABELS: { draft: 'Draft', submitted: 'Submitted', pending_approval: 'Pending Approval', approved: 'Approved' },
  CHANGE_TYPE_LABELS: {},
  CATEGORY_LABELS: {},
  PRIORITY_LABELS: {},
  RISK_LEVEL_LABELS: {},
  statusBadgeVariant: () => 'secondary',
  riskBadgeVariant: () => 'secondary',
  priorityBadgeVariant: () => 'secondary',
  formatDate: (d) => d || '',
  formatDateTime: (d) => d || '',
  actionAvailability: () => true,
  buildChangeListUrl: () => '',
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockFetchPage(...args).then((data) => ({ data })),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: (...a) => mockAuth(...a),
  AuthProvider: ({ children }) => children,
}));

import { ChangeDashboard } from '../../pages/changes/ChangeDashboard';
import { ChangeList } from '../../pages/changes/ChangeList';
import { ChangeDetail } from '../../pages/changes/ChangeDetail';
import { ChangeForm } from '../../pages/changes/ChangeForm';
import { ChangeScheduleView } from '../../pages/changes/ChangeScheduleView';
import { ChangeApprovals } from '../../pages/changes/ChangeApprovals';
import { MaintenanceWindows } from '../../pages/maintenance/MaintenanceWindows';
import { BlackoutPeriods } from '../../pages/blackout/BlackoutPeriods';
import { SchedulingExceptions } from '../../pages/procurement/SchedulingExceptions';

function makeAuth(role) {
  const isStaff = role === 'system_admin' || role === 'it_manager' || role === 'it_support';
  const isManagerOrAdmin = isStaff && (role === 'system_admin' || role === 'it_manager');
  const active = role !== null && role !== 'inactive';
  return {
    access: active ? 'token' : null,
    role,
    user: active ? { id: 1, email: 'u@x.io', employee_id: 'E1', role, is_active: true } : null,
    profileLoading: false,
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isStaff,
    isAdmin: role === 'system_admin',
    isManagerOrAdmin,
    canViewProcurement: isStaff,
    canViewProcurementReports: isStaff,
    canManageScheduledReports: isStaff,
    canViewVendors: isStaff,
    canManageChanges: isStaff,
    login: vi.fn(),
    logout: vi.fn(),
    refreshProfile: vi.fn(),
  };
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockFetchPage.mockResolvedValue({ items: [], count: 0 });
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
  // Mock window.confirm to return true for approval/rejection dialogs
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('Change Management page components render directly', () => {
  it('ChangeDashboard renders KPI cards', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockResolvedValue({
      draft: 5, pending_approval: 3, approved_unscheduled: 2,
      scheduled_next_7_days: 1, scheduled_next_30_days: 2,
      in_progress: 1, validation_pending: 0, pir_overdue: 0,
      failed: 0, rolled_back: 0, emergency_changes: 0,
      open_conflicts: 0, critical_conflicts: 0, scheduled_past_due: 0,
      in_progress_overdue: 0, awaiting_pir: 0, changes_with_conflicts: 0,
      success_rate: 95, rollback_rate: 0, emergency_rate: 0,
      average_implementation_duration_hours: 4.5,
    });
    render(<ChangeDashboard />);
    await waitFor(() => {
      expect(screen.getByText('Change Dashboard')).toBeTruthy();
    });
    await waitFor(() => {
      expect(screen.getByText('5')).toBeTruthy();
    });
  });

  it('ChangeList renders empty state', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    render(<ChangeList />);
    await waitFor(() => {
      expect(screen.getByText('No Changes Found')).toBeTruthy();
    });
  });

  it('ChangeList renders loading state', () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    // Never-resolving promise keeps loading true
    mockFetchPage.mockReturnValue(new Promise(() => {}));
    render(<ChangeList />);
    expect(screen.getByText('Loading changes…')).toBeTruthy();
  });

  it('ChangeDetail renders without crashing', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockResolvedValue({
      id: 1, change_number: 'CHG-001', title: 'Test Change', status: 'draft',
      change_type: 'standard', risk_level: 'low', priority: 'normal',
      change_owner: null, implementation_lead: null, planned_start: null, planned_end: null,
      version: 1, conflicts_count: 0, description: '', business_reason: '',
      customer_impact: '', business_impact: '', technical_impact: '',
      scope: '', out_of_scope: '', implementation_plan: '', validation_plan: '',
      rollback_plan: '', communication_plan: '', success_criteria: '',
      asset_impacts: [], service_impacts: [], tasks: [],
      risk_assessment: null, approvals: [], scheduled_at: null,
      expected_downtime_minutes: null, conflicts: [], attachments: [],
      communications: [], stakeholders: [], implementation: null,
      post_implementation_review: null, related_tickets: [],
      knowledge_links: [], history: [],
    });
    render(<ChangeDetail match={{ params: { id: '1' } }} />);
    // Should not crash - should show loading then change data
    await waitFor(() => {
      expect(screen.queryByText('Change not found')).toBeNull();
    });
    await waitFor(() => {
      expect(screen.getAllByText('CHG-001').length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getByText('Test Change')).toBeTruthy();
    expect(screen.getByText('Overview')).toBeTruthy();
  });

  it('ChangeForm renders classification step', () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    render(<ChangeForm />);
    expect(screen.getByText('Classification')).toBeTruthy();
  });

  it('ChangeScheduleView renders', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockResolvedValue({ results: [], count: 0, next: null, previous: null });
    render(<ChangeScheduleView />);
    await waitFor(() => {
      expect(screen.getByText('Change Schedule')).toBeTruthy();
    });
  });

  it('MaintenanceWindows renders list', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockResolvedValue({
      items: [{ id: 1, name: 'MW-001', code: 'MW1', status: 'active', window_type: 'scheduled', start_at: '2026-01-01T00:00:00Z', end_at: '2026-01-02T00:00:00Z' }],
      count: 1,
    });
    render(<MaintenanceWindows />);
    await waitFor(() => {
      expect(screen.getByText('MW-001')).toBeTruthy();
    });
  });

  it('BlackoutPeriods renders list', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockResolvedValue({
      items: [{ id: 1, name: 'BP-001', code: 'BP1', status: 'active', period_type: 'freeze', start_at: '2026-01-01T00:00:00Z', end_at: '2026-01-02T00:00:00Z' }],
      count: 1,
    });
    render(<BlackoutPeriods />);
    await waitFor(() => {
      expect(screen.getByText('BP-001')).toBeTruthy();
    });
  });

  it('SchedulingExceptions renders for employee with create form', async () => {
    mockAuth.mockReturnValue(makeAuth('employee'));
    render(<SchedulingExceptions />);
    await waitFor(() => {
      expect(screen.getByText('Request Scheduling Exception')).toBeTruthy();
    });
    expect(screen.getByText('Scheduling Exceptions')).toBeTruthy();
  });

  it('SchedulingExceptions shows pending/approved/rejected sections', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockResolvedValue({
      items: [
        { id: 1, status: 'pending', change: 'CHG-001', justification: 'test', requesting_user_email: 'user@x', requesting_user: 'user@x' },
        { id: 2, status: 'approved', change: 'CHG-002', justification: 'test', requesting_user_email: 'user@x', requesting_user: 'user@x', decided_by_email: 'mgr@x', decision_timestamp: '2026-01-01T00:00:00Z' },
        { id: 3, status: 'rejected', change: 'CHG-003', justification: 'test', requesting_user_email: 'user@x', requesting_user: 'user@x', decided_by_email: 'mgr@x', decision_timestamp: '2026-01-01T00:00:00Z' },
      ],
      count: 3,
    });
    render(<SchedulingExceptions />);
    await waitFor(() => {
      expect(screen.getByText('Pending Exception Requests')).toBeTruthy();
    });
    expect(screen.getByText('Approved Exceptions')).toBeTruthy();
    expect(screen.getByText('Rejected Exceptions')).toBeTruthy();
  });

  it('SchedulingExceptions manager can approve/reject', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockPatch.mockResolvedValue({ data: { id: 1, status: 'approved' } });
    mockFetchPage.mockResolvedValue({
      items: [{ id: 1, status: 'pending', change: 'CHG-001', justification: 'test', requesting_user_email: 'user@x', requesting_user: 'user@x' }],
      count: 1,
    });
    render(<SchedulingExceptions />);
    await waitFor(() => {
      expect(screen.getByText('Approve')).toBeTruthy();
    });
    const approveBtn = screen.getByText('Approve');
    approveBtn.click();
    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith('/changes/scheduling-exceptions/1/', { status: 'approved' });
    });
  });

  it('SchedulingExceptions employee submit form', async () => {
    mockAuth.mockReturnValue(makeAuth('employee'));
    mockPost.mockResolvedValue({ data: { id: 1, status: 'pending' } });
    render(<SchedulingExceptions />);
    await waitFor(() => {
      expect(screen.getByText('Request Scheduling Exception')).toBeTruthy();
    });
    const changeInput = screen.getByLabelText(/Change/);
    const justificationInput = screen.getByLabelText(/Justification/);
    act(() => {
      fireEvent.change(changeInput, { target: { value: '1', name: 'change' } });
      fireEvent.change(justificationInput, { target: { value: 'Emergency security patch', name: 'justification' } });
    });
    const form = document.querySelector('form');
    act(() => {
      fireEvent.submit(form);
    });
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/scheduling-exceptions/', expect.objectContaining({
        change: 1,
        justification: 'Emergency security patch',
      }));
    });
  });

  it('ChangeApprovals renders approvals list', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockResolvedValue({
      items: [{ id: 1, approval_level: 'manager', status: 'pending', requested_from: 'it@x', requested_by_email: 'mgr@x', decided_by_email: null, requested_at: '2026-01-01T08:00:00Z', decided_at: null, decision_reason: '' }],
      count: 1,
    });
    render(<ChangeApprovals match={{ params: { id: '1' } }} />);
    await screen.findByText('manager');
    await screen.findByText('mgr@x');
  });

  it('employee sees zeroed ChangeDashboard (no real data)', async () => {
    mockAuth.mockReturnValue(makeAuth('employee'));
    render(<ChangeDashboard />);
    await waitFor(() => {
      expect(screen.getByText('Change Dashboard')).toBeTruthy();
    });
    // Employee sees zeros, not real data
    expect(screen.getAllByText('0').length).toBeGreaterThanOrEqual(1);
  });
});


describe('ChangeScheduleView coverage', () => {
  const scheduleRow = {
    id: 101,
    change_number: 'CHG-2026-0101',
    title: 'Database maintenance',
    status: 'scheduled',
    risk_level: 'high',
    priority: 'high',
    change_type: 'normal',
    planned_start: '2026-12-01T10:00:00Z',
    planned_end: '2026-12-01T11:00:00Z',
    department: 'IT',
  };

  const emptyPage = {
    results: [],
    count: 0,
    next: null,
    previous: null,
  };

  const latestRequestParams = () => {
    const calls = mockFetchPage.mock.calls;
    const latestUrl = calls[calls.length - 1]?.[0];
    return new URLSearchParams(String(latestUrl).split('?')[1] || '');
  };

  it('denies employees access without requesting schedule data', () => {
    mockAuth.mockReturnValue(makeAuth('employee'));

    render(<ChangeScheduleView />);

    expect(screen.getByText('Access Denied')).toBeTruthy();
    expect(screen.getByText('Only IT staff can view the schedule.')).toBeTruthy();
    expect(mockFetchPage).not.toHaveBeenCalled();
  });

  it('shows the loading state while the schedule request is pending', () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockReturnValue(new Promise(() => {}));

    render(<ChangeScheduleView />);

    expect(screen.getByText('Loading schedule...')).toBeTruthy();
  });

  it('shows a parsed error when the schedule request fails', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockRejectedValue(new Error('Request failed'));

    render(<ChangeScheduleView />);

    expect(await screen.findByText('Error: Error')).toBeTruthy();
  });

  it('serializes all filters and resets pagination to page one', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockResolvedValue(emptyPage);

    render(<ChangeScheduleView />);
    await screen.findByText('Change Schedule');

    fireEvent.change(screen.getByLabelText('Status'), {
      target: { value: 'scheduled' },
    });
    fireEvent.change(screen.getByLabelText('Priority'), {
      target: { value: 'high' },
    });
    fireEvent.change(screen.getByLabelText('Risk Level'), {
      target: { value: 'critical' },
    });
    fireEvent.change(screen.getByPlaceholderText('Search changes...'), {
      target: { value: 'database' },
    });
    fireEvent.change(screen.getByLabelText('From Date'), {
      target: { value: '2026-12-01' },
    });
    fireEvent.change(screen.getByLabelText('To Date'), {
      target: { value: '2026-12-31' },
    });

    await waitFor(() => {
      const params = latestRequestParams();

      expect(params.get('page')).toBe('1');
      expect(params.get('page_size')).toBe('20');
      expect(params.get('status')).toBe('scheduled');
      expect(params.get('priority')).toBe('high');
      expect(params.get('risk')).toBe('critical');
      expect(params.get('search')).toBe('database');
      expect(params.get('date_from')).toBe('2026-12-01');
      expect(params.get('date_to')).toBe('2026-12-31');
    });
  });

  it('clears all filters and reloads the first page when Reset Filters is clicked', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockResolvedValue(emptyPage);

    render(<ChangeScheduleView />);
    await screen.findByText('Change Schedule');

    fireEvent.change(screen.getByLabelText('Status'), {
      target: { value: 'scheduled' },
    });
    fireEvent.change(screen.getByPlaceholderText('Search changes...'), {
      target: { value: 'database' },
    });

    await waitFor(() => {
      expect(latestRequestParams().get('status')).toBe('scheduled');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Reset Filters' }));

    await waitFor(() => {
      const params = latestRequestParams();

      expect(params.get('page')).toBe('1');
      expect(params.get('page_size')).toBe('20');
      expect(params.has('status')).toBe(false);
      expect(params.has('priority')).toBe(false);
      expect(params.has('risk')).toBe(false);
      expect(params.has('search')).toBe(false);
      expect(params.has('date_from')).toBe(false);
      expect(params.has('date_to')).toBe(false);
    });

    expect(screen.getByLabelText('Status').value).toBe('');
    expect(screen.getByPlaceholderText('Search changes...').value).toBe('');
  });

  it('shows the empty state when no changes match the request', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockFetchPage.mockResolvedValue(emptyPage);

    render(<ChangeScheduleView />);

    expect(await screen.findByText('No scheduled changes')).toBeTruthy();
    expect(screen.getByText('No changes match the current filters.')).toBeTruthy();
  });

  it('moves forward and backward through server pagination', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));

    mockFetchPage.mockImplementation((url) => {
      const params = new URLSearchParams(String(url).split('?')[1] || '');
      const page = params.get('page');

      return Promise.resolve({
        results: [scheduleRow],
        count: 21,
        next: page === '1' ? 'http://testserver/api/changes/?page=2' : null,
        previous: page === '2' ? 'http://testserver/api/changes/?page=1' : null,
      });
    });

    render(<ChangeScheduleView />);

    expect(await screen.findByText('CHG-2026-0101')).toBeTruthy();

    const nextButton = screen.getByRole('button', { name: /Next/ });
    expect(nextButton.disabled).toBe(false);

    fireEvent.click(nextButton);

    await waitFor(() => {
      expect(latestRequestParams().get('page')).toBe('2');
    });

    const previousButton = screen.getByRole('button', { name: /Prev/ });
    await waitFor(() => {
      expect(previousButton.disabled).toBe(false);
    });

    fireEvent.click(previousButton);

    await waitFor(() => {
      expect(latestRequestParams().get('page')).toBe('1');
    });
  });
});