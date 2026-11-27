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
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: (...args) => mockAuth(...args),
  AuthProvider: ({ children }) => children,
}));

import { ChangeForm } from '../../pages/changes/ChangeForm';

const DEPARTMENTS = [
  { id: 4, name: 'Engineering', is_active: true },
  { id: 5, name: 'Retired Department', is_active: false },
];

function makeAuth(role) {
  const isStaff = ['system_admin', 'it_manager', 'it_support'].includes(role);
  return {
    role,
    isStaff,
    isAdmin: role === 'system_admin',
    user: { id: 1, email: 'user@example.com', employee_id: 'E1', role },
    access: 'token',
    profileLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
    refreshProfile: vi.fn(),
  };
}

async function renderForm({ role = 'it_manager' } = {}) {
  mockAuth.mockReturnValue(makeAuth(role));
  mockGet.mockImplementation(async (url) => {
    if (url === '/accounts/departments/') {
      return { data: { results: DEPARTMENTS, count: DEPARTMENTS.length } };
    }
    throw new Error(`Unexpected GET: ${url}`);
  });
  render(<ChangeForm />);
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/accounts/departments/'));
}

const clickNext = () => fireEvent.click(screen.getByRole('button', { name: 'Next' }));

async function fillToReview({ submitFields = false, department = '', uncheckApproval = false } = {}) {
  fireEvent.change(screen.getByLabelText(/^Category/), { target: { value: 'infrastructure' } });
  if (department) {
    fireEvent.change(screen.getByLabelText('Department'), { target: { value: department } });
  }
  if (uncheckApproval) {
    fireEvent.click(screen.getByLabelText('Approval required'));
  }
  clickNext();

  fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: 'Restart API' } });
  fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Restart service' } });
  if (submitFields) {
    fireEvent.change(screen.getByLabelText('Business reason'), { target: { value: 'Deploy fix' } });
  }
  clickNext();

  fireEvent.change(screen.getByLabelText('Scope'), { target: { value: 'API' } });
  fireEvent.change(screen.getByLabelText('Out of scope'), { target: { value: 'Database' } });
  clickNext();

  fireEvent.change(screen.getByLabelText('Implementation plan'), { target: { value: 'Stop service' } });
  fireEvent.change(screen.getByLabelText('Validation plan'), { target: { value: 'Check health' } });
  fireEvent.change(screen.getByLabelText('Rollback plan'), { target: { value: 'Restore service' } });
  fireEvent.change(screen.getByLabelText('Communication plan'), { target: { value: 'Notify users' } });
  fireEvent.change(screen.getByLabelText('Success criteria'), { target: { value: 'Healthy' } });
  clickNext();
  clickNext();

  expect(await screen.findByText('Please review the change details before submitting.')).toBeTruthy();
}

beforeEach(() => {
  cleanup();
  window.location.hash = '';
  mockGet.mockReset();
  mockPost.mockReset();
  mockAuth.mockReset();
  mockPost.mockResolvedValue({ data: { id: 12 } });
});

afterEach(() => {
  cleanup();
  window.location.hash = '';
  vi.restoreAllMocks();
});

describe('ChangeForm creation workflow', () => {
  it('renders backend-supported classification fields and loads active departments', async () => {
    await renderForm();

    expect(screen.getByLabelText(/^Change type/)).toBeTruthy();
    expect(screen.getByLabelText(/^Category/)).toBeTruthy();
    expect(screen.getByLabelText(/^Priority/)).toBeTruthy();
    expect(screen.getByLabelText('Department')).toBeTruthy();
    expect(screen.getByLabelText('Approval required')).toBeTruthy();
    expect(screen.getByLabelText('Emergency reason')).toBeTruthy();
    expect(screen.queryByLabelText(/Risk level/i)).toBeNull();
    expect(screen.queryByLabelText(/planned start/i)).toBeNull();

    await waitFor(() => {
      const options = [...screen.getByLabelText('Department').querySelectorAll('option')];
      expect(options.some((o) => o.textContent === 'Engineering')).toBe(true);
      expect(options.some((o) => o.textContent === 'Retired Department')).toBe(false);
    });
  });

  it('blocks navigation when a required field is missing', async () => {
    await renderForm();

    clickNext();

    expect(await screen.findByText('Category is required.')).toBeTruthy();
    expect(screen.getByText('Classification')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('requires an emergency reason for emergency changes', async () => {
    await renderForm();
    fireEvent.change(screen.getByLabelText(/^Change type/), { target: { value: 'emergency' } });
    fireEvent.change(screen.getByLabelText(/^Category/), { target: { value: 'infrastructure' } });

    clickNext();

    expect(await screen.findByText('Emergency reason is required for emergency changes.')).toBeTruthy();
    expect(screen.getByText('Classification')).toBeTruthy();
  });

  it('submits the exact create payload and navigates on draft save', async () => {
    await renderForm();
    await fillToReview({ department: '4', uncheckApproval: true });

    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/', {
        title: 'Restart API',
        description: 'Restart service',
        business_reason: '',
        change_type: 'normal',
        category: 'infrastructure',
        priority: 'normal',
        department: 4,
        scope: 'API',
        out_of_scope: 'Database',
        implementation_plan: 'Stop service',
        validation_plan: 'Check health',
        rollback_plan: 'Restore service',
        communication_plan: 'Notify users',
        success_criteria: 'Healthy',
        emergency_reason: '',
        approval_required: false,
      });
    });
    expect(mockPost).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(window.location.hash).toBe('#/changes/12'));
  });

  it('creates and submits when Save and Submit is used', async () => {
    mockPost
      .mockResolvedValueOnce({ data: { id: 9 } })
      .mockResolvedValueOnce({ data: {} });
    await renderForm();
    await fillToReview({ submitFields: true });

    fireEvent.click(screen.getByRole('button', { name: 'Save and Submit' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2));
    expect(mockPost).toHaveBeenNthCalledWith(1, '/changes/', expect.objectContaining({
      title: 'Restart API',
      business_reason: 'Deploy fix',
      department: null,
      approval_required: true,
    }));
    expect(mockPost).toHaveBeenNthCalledWith(2, '/changes/9/submit/', {});
    await waitFor(() => expect(window.location.hash).toBe('#/changes/9'));
  });

  it('shows create API errors and does not navigate or fake success', async () => {
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { title: ['Invalid title.'] } },
    });
    await renderForm();
    await fillToReview();

    fireEvent.click(screen.getByRole('button', { name: 'Save Draft' }));

    expect(await screen.findByText('Invalid title.')).toBeTruthy();
    expect(screen.getByText('Could not create the change.')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Description' })).toBeTruthy();
    expect(window.location.hash).toBe('');
  });

  it('keeps the created id when submission fails so retry does not duplicate the change', async () => {
    mockPost
      .mockResolvedValueOnce({ data: { id: 21 } })
      .mockRejectedValueOnce({
        response: { status: 400, data: { detail: 'Submission rejected.' } },
      })
      .mockResolvedValueOnce({ data: {} });
    await renderForm();
    await fillToReview({ submitFields: true });

    fireEvent.click(screen.getByRole('button', { name: 'Save and Submit' }));

    expect(await screen.findByText('Submission rejected.')).toBeTruthy();
    expect(window.location.hash).toBe('');
    expect(mockPost).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole('button', { name: 'Save and Submit' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(3));
    expect(mockPost).toHaveBeenNthCalledWith(3, '/changes/21/submit/', {});
    await waitFor(() => expect(window.location.hash).toBe('#/changes/21'));
  });

  it('does not add a new client-side role gate beyond existing route protection', async () => {
    await renderForm({ role: 'employee' });

    expect(screen.getByText('Classification')).toBeTruthy();
    expect(mockAuth).toHaveBeenCalled();
  });
});
