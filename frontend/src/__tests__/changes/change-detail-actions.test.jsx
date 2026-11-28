import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: (...args) => mockAuth(...args),
  AuthProvider: ({ children }) => children,
}));

import { ChangeDetail } from '../../pages/changes/ChangeDetail';
import { ChangeUtils } from '../../shared/changes-utils';

function makeAuth(role) {
  const staffRoles = ['system_admin', 'it_manager', 'it_support'];
  const isStaff = staffRoles.includes(role);
  return {
    role,
    isStaff,
    isAdmin: role === 'system_admin',
    isManagerOrAdmin: role === 'system_admin' || role === 'it_manager',
    user: { id: 1, employee_id: 'E1', email: 'user@example.com', role },
    access: 'token',
    profileLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
    refreshProfile: vi.fn(),
  };
}

function baseChange(overrides = {}) {
  return {
    id: 7,
    change_number: 'CHG-007',
    title: 'Test change',
    status: 'draft',
    change_type: 'normal',
    risk_level: 'medium',
    priority: 'normal',
    version: 3,
    change_owner: null,
    implementation_lead: null,
    planned_start: null,
    planned_end: null,
    conflicts_count: 0,
    description: '',
    business_reason: '',
    customer_impact: '',
    business_impact: '',
    technical_impact: '',
    scope: '',
    out_of_scope: '',
    implementation_plan: '',
    validation_plan: '',
    rollback_plan: '',
    communication_plan: '',
    success_criteria: '',
    asset_impacts: [],
    service_impacts: [],
    tasks: [],
    risk_assessment: null,
    approvals: [],
    scheduled_at: null,
    expected_downtime_minutes: null,
    conflicts: [],
    attachments: [],
    communications: [],
    stakeholders: [],
    implementation: null,
    post_implementation_review: null,
    related_tickets: [],
    knowledge_links: [],
    history: [],
    ...overrides,
  };
}

async function renderDetail({ status = 'draft', role = 'it_manager', overrides = {}, responses } = {}) {
  const change = baseChange({ status, ...overrides });
  mockAuth.mockReturnValue(makeAuth(role));
  if (responses) {
    responses.forEach((response) => mockGet.mockResolvedValueOnce({ data: response }));
  } else {
    mockGet.mockResolvedValue({ data: change });
  }
  render(<ChangeDetail match={{ params: { id: '7' } }} />);
  await screen.findByRole('heading', { name: 'CHG-007' });
  return change;
}

beforeEach(() => {
  cleanup();
  window.location.hash = '';
  mockGet.mockReset();
  mockPost.mockReset();
  mockAuth.mockReset();
  mockPost.mockResolvedValue({ data: {} });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  vi.spyOn(window, 'prompt').mockReturnValue('reason');
  vi.stubGlobal('fetch', vi.fn(() => {
    throw new Error('raw fetch must not be used for change actions');
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ChangeDetail workflow actions', () => {
  it('submits through the shared axios client and refreshes the detail object', async () => {
    const initial = baseChange({ status: 'draft' });
    const refreshed = { ...initial, status: 'submitted', change_number: 'CHG-008' };
    await renderDetail({ responses: [initial, refreshed] });

    fireEvent.click(screen.getByRole('button', { name: 'Submit for Review' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/submit/', {});
    });
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    expect(mockGet).toHaveBeenLastCalledWith('/changes/7/');
    expect(await screen.findByRole('heading', { name: 'CHG-008' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'CHG-007' })).toBeNull();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('approves with the decision reason supplied by the prompt', async () => {
    vi.spyOn(window, 'prompt').mockReturnValue('looks good');
    await renderDetail({ status: 'pending_approval' });

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/approve/', {
        decision_reason: 'looks good',
      });
    });
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('rejects through the reject endpoint with the supplied reason', async () => {
    vi.spyOn(window, 'prompt').mockReturnValue('not approved');
    await renderDetail({ status: 'pending_approval' });

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/reject/', {
        decision_reason: 'not approved',
      });
    });
  });

  it('returns a change for correction through the backend action', async () => {
    await renderDetail({ status: 'pending_approval' });

    fireEvent.click(screen.getByRole('button', { name: 'Return for Correction' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/return_for_correction/', {});
    });
  });

  it('cancels only after confirmation and uses the cancel endpoint', async () => {
    await renderDetail({ status: 'submitted' });

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(window.confirm).toHaveBeenCalledWith('Are you sure you want to cancel this change?');
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/cancel/', {});
    });
  });

  it.each([
    ['scheduled', 'Start Implementation', 'start_implementation', {}],
    ['scheduled', 'Put on Hold', 'hold', {}],
    ['in_progress', 'Begin Validation', 'begin_validation', {}],
    ['in_progress', 'Fail Implementation', 'fail', { failure_reason: 'reason' }],
    ['failed', 'Start Rollback', 'start_rollback', {}],
    ['rolled_back', 'Complete Rollback', 'complete_rollback', {}],
    ['validation', 'Complete', 'complete', { implementation_notes: 'reason' }],
    ['completed', 'Request PIR', 'request_pir', {}],
    ['pir_required', 'Close Change', 'close', { closure_summary: 'reason' }],
    ['on_hold', 'Resume', 'resume', {}],
  ])('dispatches %s / %s to its backend action', async (status, label, actionKey, body) => {
    await renderDetail({ status, role: 'system_admin' });

    fireEvent.click(screen.getByRole('button', { name: label }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(`/changes/7/${actionKey}/`, body);
    });
  });

  it('renders manager rollback actions only where actionAvailability allows them', async () => {
    const cases = [
      ['in_progress', 'start_rollback', 'Start Rollback', false],
      ['failed', 'start_rollback', 'Start Rollback', true],
      ['in_progress', 'complete_rollback', 'Complete Rollback', false],
      ['validation', 'complete_rollback', 'Complete Rollback', false],
      ['rolled_back', 'complete_rollback', 'Complete Rollback', true],
    ];

    for (const [status, action, label, expected] of cases) {
      cleanup();
      mockGet.mockReset();
      mockPost.mockReset();
      mockAuth.mockReset();

      await renderDetail({ status, role: 'it_manager' });

      expect(ChangeUtils.actionAvailability('it_manager', status, action)).toBe(expected);
      expect(screen.queryByRole('button', { name: label }) !== null).toBe(expected);
    }
  });

  it('does not send a request when an action confirmation is declined', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    await renderDetail({ status: 'submitted' });

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(window.confirm).toHaveBeenCalled();
    expect(mockPost).not.toHaveBeenCalled();
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it('keeps reschedule as navigation because scheduling requires a separate form payload', async () => {
    await renderDetail({ status: 'scheduled', role: 'system_admin' });
    window.location.hash = '';

    const link = screen.getByRole('link', { name: 'Reschedule' });
    fireEvent.click(link);

    expect(link.getAttribute('href')).toBe('#/changes/7/implementation');
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('shows an error and does not refresh the record when an action fails', async () => {
    await renderDetail({ status: 'pending_approval' });
    mockPost.mockRejectedValueOnce({
      response: { status: 403, data: { detail: 'Not allowed to approve.' } },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));

    expect(await screen.findByText('Not allowed to approve.')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Rejected')).toBeNull();
  });

  it('does not expose workflow actions to employees', async () => {
    await renderDetail({ status: 'draft', role: 'employee' });

    expect(screen.queryByRole('button', { name: 'Submit for Review' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
  });

  it('does not expose approval decisions to IT support', async () => {
    await renderDetail({ status: 'pending_approval', role: 'it_support' });

    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Return for Correction' })).toBeNull();
  });

  it('renders communication records using the API serializer fields', async () => {
    await renderDetail({
      overrides: {
        communications: [{
          id: 11,
          communication_type: 'email',
          subject: 'Maintenance notice',
          status: 'sent',
          sent_at: null,
        }],
      },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Communications' }));

    expect(screen.getByText('email')).toBeTruthy();
    expect(screen.getByText(/Maintenance notice/)).toBeTruthy();
    expect(screen.getByText('Status: sent')).toBeTruthy();
  });

  it('shows an empty state when there are no communications', async () => {
    await renderDetail({ overrides: { communications: [] } });

    fireEvent.click(screen.getByRole('button', { name: 'Communications' }));

    expect(screen.getByText('No communications')).toBeTruthy();
  });

  it('renders stakeholder records using the API serializer fields', async () => {
    await renderDetail({
      overrides: {
        stakeholders: [{
          id: 12,
          user: 5,
          user_email: 'alex@example.com',
          stakeholder_type: 'technical',
          department_name: 'IT',
          notification_level: 'all_updates',
        }],
      },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Stakeholders' }));

    expect(screen.getByText('alex@example.com')).toBeTruthy();
    expect(screen.getByText(/technical/)).toBeTruthy();
    expect(screen.getByText(/IT/)).toBeTruthy();
    expect(screen.getByText('Notifications: all_updates')).toBeTruthy();
  });

  it('shows an empty state when there are no stakeholders', async () => {
    await renderDetail({ overrides: { stakeholders: [] } });

    fireEvent.click(screen.getByRole('button', { name: 'Stakeholders' }));

    expect(screen.getByText('No stakeholders')).toBeTruthy();
  });

  it('does not expose actions for a closed change', async () => {
    await renderDetail({ status: 'closed', role: 'system_admin' });

    expect(screen.queryByRole('button', { name: 'Close Change' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Submit for Review' })).toBeNull();
  });
});
