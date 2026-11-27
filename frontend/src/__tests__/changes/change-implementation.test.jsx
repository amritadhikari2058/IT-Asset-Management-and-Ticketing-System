import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: (...args) => mockAuth(...args),
  AuthProvider: ({ children }) => children,
}));

import { ChangeImplementation } from '../../pages/changes/ChangeImplementation';

const BASE_CHANGE = {
  id: 7,
  change_number: 'CHG-007',
  title: 'Restart API',
  status: 'scheduled',
  planned_start: '2026-11-30T10:00:00Z',
  actual_start: null,
  actual_end: null,
  implementation_plan: 'Restart the API service',
  validation_plan: 'Check health endpoint',
  rollback_plan: 'Restore previous version',
};

function makeAuth(role) {
  const isStaff = ['system_admin', 'it_manager', 'it_support'].includes(role);
  return {
    role,
    isStaff,
    isAdmin: role === 'system_admin',
    isManagerOrAdmin: role === 'system_admin' || role === 'it_manager',
    user: { id: 1, email: 'user@example.com', employee_id: 'E1', role },
    access: 'token',
    profileLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
    refreshProfile: vi.fn(),
  };
}

async function renderImplementation({
  role = 'it_manager',
  status = 'scheduled',
  implementation = null,
  readiness = { ready: true, blockers: [] },
  changeOverrides = {},
} = {}) {
  const store = {
    change: { ...BASE_CHANGE, status, ...changeOverrides },
    implementation,
    readiness,
  };

  mockAuth.mockReturnValue(makeAuth(role));
  mockGet.mockImplementation(async (url) => {
    if (url === '/changes/7/') return { data: store.change };
    if (url === '/changes/7/readiness/') return { data: store.readiness };
    if (url === '/changes/implementations/') {
      return { data: { results: store.implementation ? [store.implementation] : [] } };
    }
    throw new Error(`Unexpected GET: ${url}`);
  });

  render(<ChangeImplementation match={{ params: { id: '7' } }} />);
  await screen.findByRole('heading', { name: 'Implementation' });
  return store;
}

beforeEach(() => {
  cleanup();
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
  mockAuth.mockReset();
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
  vi.stubGlobal('fetch', vi.fn(() => {
    throw new Error('raw fetch must not be used for implementation requests');
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ChangeImplementation workflow', () => {
  it('loads change, readiness and implementation records through the backend API', async () => {
    await renderImplementation({
      implementation: { id: 3, change: 7, status: 'in_progress', outcome: '' },
      readiness: { ready: false, blockers: ['Rollback plan is missing.'] },
    });

    expect(mockGet).toHaveBeenCalledWith('/changes/7/');
    expect(mockGet).toHaveBeenCalledWith('/changes/7/readiness/');
    expect(mockGet).toHaveBeenCalledWith('/changes/implementations/');
    expect(mockGet).not.toHaveBeenCalledWith('/changes/tasks/');
    expect(screen.getByText('Restart API')).toBeTruthy();
    expect(screen.getByText('Restart the API service')).toBeTruthy();
    expect(screen.getByText('Check health endpoint')).toBeTruthy();
    expect(screen.getByText('Restore previous version')).toBeTruthy();
    expect(screen.getByText('Rollback plan is missing.')).toBeTruthy();
    expect(screen.getByText('#3')).toBeTruthy();
  });

  it('hides management controls from support staff but still shows details', async () => {
    await renderImplementation({ role: 'it_support', status: 'in_progress' });

    expect(screen.queryByRole('button', { name: 'Start Implementation' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Complete' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Create Implementation Record' })).toBeNull();
    expect(screen.getByText('Restart the API service')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/changes/implementations/');
  });

  it('does not query implementation records for an employee', async () => {
    await renderImplementation({ role: 'employee', status: 'in_progress' });

    expect(mockGet).not.toHaveBeenCalledWith('/changes/implementations/');
    expect(screen.queryByRole('button', { name: 'Create Implementation Record' })).toBeNull();
  });

  it.each([
    ['Complete', 'in_progress'],
    ['Fail Implementation', 'in_progress'],
    ['Complete', 'validation'],
    ['Fail Implementation', 'validation'],
  ])('exposes %s from %s', async (label, status) => {
    await renderImplementation({ status });

    expect(screen.getByRole('button', { name: label })).toBeTruthy();
  });

  it.each([
    'draft', 'submitted', 'approved', 'scheduled', 'on_hold',
    'failed', 'rolled_back', 'completed', 'pir_required', 'closed', 'cancelled',
  ])('does not expose Complete or Fail from %s', async (status) => {
    await renderImplementation({ status });

    expect(screen.queryByRole('button', { name: 'Complete' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Fail Implementation' })).toBeNull();
  });

  it.each(['it_support', 'employee'])(
    'hides Complete and Fail from %s in validation',
    async (role) => {
      await renderImplementation({ role, status: 'validation' });

      expect(screen.queryByRole('button', { name: 'Complete' })).toBeNull();
      expect(screen.queryByRole('button', { name: 'Fail Implementation' })).toBeNull();
      expect(screen.queryByLabelText('Failure reason')).toBeNull();
    },
  );

  it('starts implementation with an empty body and refreshes the change', async () => {
    const store = await renderImplementation();

    fireEvent.click(screen.getByRole('button', { name: 'Start Implementation' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/start_implementation/', {});
    });
    expect(await screen.findByText('Start Implementation recorded.')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(6);
    expect(global.fetch).not.toHaveBeenCalled();
    expect(store.change.status).toBe('scheduled');
  });

  it('creates an implementation record with only serializer-supported fields', async () => {
    await renderImplementation();

    fireEvent.change(screen.getByLabelText('Outcome'), { target: { value: 'successful' } });
    fireEvent.change(screen.getByLabelText('Actual downtime (minutes)'), { target: { value: '5' } });
    fireEvent.change(screen.getByLabelText('Implementation notes'), {
      target: { value: 'Restarted cleanly' },
    });
    fireEvent.change(screen.getByLabelText('Validation result'), {
      target: { value: 'Health checks passed' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Implementation Record' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/implementations/', {
        change: 7,
        status: 'in_progress',
        outcome: 'successful',
        implementation_notes: 'Restarted cleanly',
        validation_result: 'Health checks passed',
        rollback_required: false,
        actual_downtime_minutes: 5,
      });
    });
    expect(await screen.findByText('Implementation record saved.')).toBeTruthy();
  });

  it('updates an existing implementation record with PATCH', async () => {
    await renderImplementation({
      status: 'in_progress',
      implementation: {
        id: 22,
        change: 7,
        status: 'in_progress',
        outcome: '',
        implementation_notes: 'Old note',
        validation_result: '',
        rollback_required: false,
        actual_downtime_minutes: null,
      },
    });

    fireEvent.change(screen.getByLabelText('Implementation notes'), {
      target: { value: 'Updated note' },
    });
    fireEvent.click(screen.getByLabelText('Rollback required'));
    fireEvent.click(screen.getByRole('button', { name: 'Save Progress' }));

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith('/changes/implementations/22/', {
        status: 'in_progress',
        outcome: '',
        implementation_notes: 'Updated note',
        validation_result: '',
        rollback_required: true,
        actual_downtime_minutes: null,
      });
    });
  });

  it('validates completion notes before calling the API', async () => {
    await renderImplementation({ status: 'in_progress' });

    fireEvent.click(screen.getByRole('button', { name: 'Complete' }));

    expect(await screen.findByText(
      'Implementation notes are required to complete an implementation.',
    )).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('sends validation_passed and completion notes to the complete action', async () => {
    const store = await renderImplementation({ status: 'in_progress' });
    mockPost.mockImplementationOnce(async (url) => {
      if (url === '/changes/7/complete/') store.change.status = 'completed';
      return { data: {} };
    });

    fireEvent.change(screen.getByLabelText('Completion notes'), {
      target: { value: 'Deployment finished' },
    });
    fireEvent.click(screen.getByLabelText('Validation passed'));
    fireEvent.click(screen.getByRole('button', { name: 'Complete' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/complete/', {
        validation_passed: false,
        implementation_notes: 'Deployment finished',
      });
    });
    expect(await screen.findByText('Completed')).toBeTruthy();
    expect(screen.getByText('Complete recorded.')).toBeTruthy();
  });

  it('requires a failure reason before calling the fail action', async () => {
    await renderImplementation({ status: 'in_progress' });

    fireEvent.click(screen.getByRole('button', { name: 'Fail Implementation' }));

    expect(await screen.findByText('A failure reason is required.')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('sends the failure reason to the fail action', async () => {
    await renderImplementation({ status: 'in_progress' });

    fireEvent.change(screen.getByLabelText('Failure reason'), {
      target: { value: 'Health checks failed' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Fail Implementation' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/fail/', {
        failure_reason: 'Health checks failed',
      });
    });
  });

  it('sends completion payload and refreshes from validation', async () => {
    const store = await renderImplementation({ status: 'validation' });
    mockPost.mockImplementationOnce(async (url) => {
      if (url === '/changes/7/complete/') store.change.status = 'completed';
      return { data: {} };
    });

    fireEvent.change(screen.getByLabelText('Completion notes'), {
      target: { value: 'Validation complete' },
    });
    fireEvent.click(screen.getByLabelText('Validation passed'));
    fireEvent.click(screen.getByRole('button', { name: 'Complete' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/complete/', {
        validation_passed: false,
        implementation_notes: 'Validation complete',
      });
    });
    expect(await screen.findByText('Complete recorded.')).toBeTruthy();
    expect(await screen.findByText('Completed')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(6);
  });

  it('sends failure reason and refreshes from validation', async () => {
    await renderImplementation({ status: 'validation' });

    fireEvent.change(screen.getByLabelText('Failure reason'), {
      target: { value: 'Validation found a defect' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Fail Implementation' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/fail/', {
        failure_reason: 'Validation found a defect',
      });
    });
    expect(await screen.findByText('Fail Implementation recorded.')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(6);
  });

  it('requires completion notes and failure reason from validation', async () => {
    await renderImplementation({ status: 'validation' });

    fireEvent.click(screen.getByRole('button', { name: 'Complete' }));
    expect(await screen.findByText(
      'Implementation notes are required to complete an implementation.',
    )).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Fail Implementation' }));
    expect(await screen.findByText('A failure reason is required.')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('shows API validation errors from validation without reporting success', async () => {
    await renderImplementation({ status: 'validation' });
    mockPost.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { detail: 'Validation has failed; cannot complete this change.' },
      },
    });

    fireEvent.change(screen.getByLabelText('Completion notes'), {
      target: { value: 'Retry notes' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Complete' }));

    expect(await screen.findByText(
      'Validation has failed; cannot complete this change.',
    )).toBeTruthy();
    expect(screen.queryByText('Complete recorded.')).toBeNull();
    expect(mockGet).toHaveBeenCalledTimes(3);
  });

  it.each([
    ['failed', 'Start Rollback', '/changes/7/start_rollback/'],
    ['rolled_back', 'Complete Rollback', '/changes/7/complete_rollback/'],
  ])('exposes %s rollback action and posts to %s', async (status, label, endpoint) => {
    await renderImplementation({ status });

    fireEvent.click(screen.getByRole('button', { name: label }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(endpoint, {}));
  });

  it('does not expose actions for a status rejected by the backend', async () => {
    await renderImplementation({ status: 'completed' });

    expect(screen.queryByRole('button', { name: 'Complete' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Fail Implementation' })).toBeNull();
    expect(screen.getByText('No implementation actions are available for this status.')).toBeTruthy();
  });

  it('shows API validation errors and does not report success', async () => {
    await renderImplementation();
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'Only scheduled changes can be implemented.' } },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Start Implementation' }));

    expect(await screen.findByText('Only scheduled changes can be implemented.')).toBeTruthy();
    expect(screen.queryByText('Start Implementation recorded.')).toBeNull();
    expect(mockGet).toHaveBeenCalledTimes(3);
  });
});
