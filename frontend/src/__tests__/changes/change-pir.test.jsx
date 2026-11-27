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

import { ChangePIR } from '../../pages/changes/ChangePIR';

const BASE_CHANGE = {
  id: 7,
  change_number: 'CHG-007',
  title: 'Restart API',
  status: 'completed',
  risk_level: 'low',
};

const BASE_PIR = {
  id: 11,
  change: 7,
  status: 'completed',
  reviewer: 3,
  reviewer_email: 'reviewer@example.com',
  reviewed_by: 4,
  reviewed_by_email: 'approver@example.com',
  scheduled_for: '2026-12-01T10:00:00Z',
  completed_at: '2026-12-02T10:00:00Z',
  outcome: 'successful',
  objectives_met: 'All objectives met',
  validation_successful: true,
  unexpected_impact: 'None',
  downtime_within_estimate: true,
  rollback_used: false,
  incident_created: false,
  lessons_learned: 'Communicate earlier',
  follow_up_actions: 'Update runbook',
  knowledge_article: 9,
  created_at: '2026-11-30T10:00:00Z',
  updated_at: '2026-12-02T10:00:00Z',
  version: 2,
};

const CHANGE_URL = '/changes/7/';
const PIR_LIST_URL = '/changes/post-implementation-reviews/?change=7';
const UNFILTERED_PIR_URL = '/changes/post-implementation-reviews/?page_size=100';
const COMPLETE_URL = '/changes/post-implementation-reviews/11/complete/';

function makeAuth(role) {
  const isStaff = ['system_admin', 'it_manager', 'it_support'].includes(role);
  return {
    role,
    isStaff,
    isEmployee: role === 'employee',
    isAdmin: role === 'system_admin',
    isManagerOrAdmin: role === 'system_admin' || role === 'it_manager',
    user: { id: 1, email: 'user@example.com', employee_id: 'E1', role },
    access: 'token',
    profileLoading: false,
  };
}

function resetMocks() {
  cleanup();
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
  mockAuth.mockReset();
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
}

async function renderPIR({
  role = 'it_manager',
  status = 'completed',
  riskLevel = 'low',
  pir = null,
} = {}) {
  const store = {
    change: { ...BASE_CHANGE, status, risk_level: riskLevel },
    pir,
  };

  mockAuth.mockReturnValue(makeAuth(role));
  mockGet.mockImplementation(async (url) => {
    if (url === CHANGE_URL) return { data: store.change };
    if (url === PIR_LIST_URL) {
      return {
        data: {
          count: store.pir ? 1 : 0,
          results: store.pir ? [store.pir] : [],
        },
      };
    }
    throw new Error(`Unexpected GET: ${url}`);
  });

  render(<ChangePIR match={{ params: { id: '7' } }} />);
  await screen.findByRole('heading', { name: 'PIR & Closure' });
  return store;
}

function pirStatusCell() {
  return screen.getByText('Status:', { selector: 'strong' }).parentElement;
}

function getCalls() {
  return mockGet.mock.calls.map(([url]) => url);
}

beforeEach(() => {
  resetMocks();
  vi.stubGlobal('fetch', vi.fn(() => {
    throw new Error('raw fetch must not be used for PIR requests');
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ChangePIR workflow', () => {
  it('loads only this change\'s PIR from the filtered endpoint and displays it', async () => {
    await renderPIR({ pir: BASE_PIR });

    expect(mockGet).toHaveBeenCalledWith(CHANGE_URL);
    expect(mockGet).toHaveBeenCalledWith(PIR_LIST_URL);
    expect(mockGet).not.toHaveBeenCalledWith(UNFILTERED_PIR_URL);
    expect(mockGet).not.toHaveBeenCalledWith('/changes/7/pir/');
    expect(getCalls().every((url) => url === CHANGE_URL || url === PIR_LIST_URL))
      .toBe(true);
    expect(screen.getAllByText('CHG-007').length).toBeGreaterThan(0);
    expect(screen.getByText('reviewer@example.com')).toBeTruthy();
    expect(screen.getByText('approver@example.com')).toBeTruthy();
    expect(pirStatusCell().textContent).toContain('completed');
    expect(screen.getAllByText('All objectives met').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Communicate earlier').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Update runbook').length).toBeGreaterThan(0);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('does not fetch a page of unrelated PIRs or filter the list client-side', async () => {
    await renderPIR({ pir: BASE_PIR });

    expect(getCalls().some((url) => url.includes('page_size=100'))).toBe(false);
    expect(mockGet.mock.calls.length).toBe(2);
  });

  it('shows the no-PIR state when the filtered result is empty', async () => {
    await renderPIR({ pir: null });

    expect(mockGet).toHaveBeenCalledWith(PIR_LIST_URL);
    expect(screen.getByText('No PIR has been recorded for this change.')).toBeTruthy();
  });

  it('creates a PIR with the serializer payload and refreshes through the filtered URL', async () => {
    await renderPIR();

    fireEvent.change(screen.getByLabelText('Outcome'), { target: { value: 'successful' } });
    fireEvent.change(screen.getByLabelText('Objectives met'), {
      target: { value: 'Objectives confirmed' },
    });
    fireEvent.change(screen.getByLabelText('Lessons learned'), {
      target: { value: 'Plan earlier' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create PIR' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/post-implementation-reviews/', {
        change: 7,
        outcome: 'successful',
        objectives_met: 'Objectives confirmed',
        validation_successful: false,
        unexpected_impact: '',
        downtime_within_estimate: false,
        rollback_used: false,
        incident_created: false,
        lessons_learned: 'Plan earlier',
        follow_up_actions: '',
        scheduled_for: null,
        completed_at: null,
        knowledge_article: null,
        reviewed_by: null,
      });
    });
    expect(await screen.findByText('PIR created.')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(4);
    expect(getCalls().filter((url) => url === PIR_LIST_URL).length).toBe(2);
    expect(getCalls().every((url) => url === CHANGE_URL || url === PIR_LIST_URL))
      .toBe(true);
  });

  it('updates an existing PIR with PATCH and refreshes', async () => {
    await renderPIR({
      pir: { ...BASE_PIR, scheduled_for: null, completed_at: null },
    });

    fireEvent.change(screen.getByLabelText('Outcome'), { target: { value: 'failed' } });
    fireEvent.click(screen.getByLabelText('Validation successful'));
    fireEvent.click(screen.getByRole('button', { name: 'Update PIR' }));

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith('/changes/post-implementation-reviews/11/', {
        outcome: 'failed',
        objectives_met: 'All objectives met',
        validation_successful: false,
        unexpected_impact: 'None',
        downtime_within_estimate: true,
        rollback_used: false,
        incident_created: false,
        lessons_learned: 'Communicate earlier',
        follow_up_actions: 'Update runbook',
        scheduled_for: null,
        completed_at: null,
        knowledge_article: 9,
        reviewed_by: 4,
      });
    });
    expect(mockPost).not.toHaveBeenCalled();
    expect(await screen.findByText('PIR updated.')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(4);
    expect(getCalls().filter((url) => url === PIR_LIST_URL).length).toBe(2);
  });

  it('validates related record ids before saving', async () => {
    await renderPIR();

    fireEvent.change(screen.getByLabelText('Knowledge article id'), {
      target: { value: '0' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create PIR' }));

    expect(await screen.findByText('Enter a valid record id.')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('shows save API errors without reporting success and without refreshing', async () => {
    await renderPIR();
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'PIR save rejected.' } },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Create PIR' }));

    expect(await screen.findByText('PIR save rejected.')).toBeTruthy();
    expect(screen.queryByText('PIR created.')).toBeNull();
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('requests a PIR from a completed change and refreshes', async () => {
    await renderPIR();

    fireEvent.click(screen.getByRole('button', { name: 'Request PIR' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/request_pir/', {});
    });
    expect(await screen.findByText('PIR request recorded.')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(4);
    expect(getCalls().filter((url) => url === PIR_LIST_URL).length).toBe(2);
  });

  it('closes a completed low-risk change with a closure summary and refreshes', async () => {
    await renderPIR();

    fireEvent.change(screen.getByLabelText('Closure summary'), {
      target: { value: 'All objectives met.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Close Change' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/close/', {
        closure_summary: 'All objectives met.',
      });
    });
    expect(await screen.findByText('Closure recorded.')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(4);
    expect(getCalls().filter((url) => url === PIR_LIST_URL).length).toBe(2);
    expect(getCalls().every((url) => url === CHANGE_URL || url === PIR_LIST_URL))
      .toBe(true);
  });

  it('shows Complete PIR for pending, scheduled, and in_progress reviews', async () => {
    for (const pirStatus of ['pending', 'scheduled', 'in_progress']) {
      resetMocks();
      await renderPIR({
        status: 'pir_required',
        pir: { ...BASE_PIR, status: pirStatus, completed_at: null },
      });

      expect(screen.getByRole('button', { name: 'Complete PIR' })).toBeTruthy();
    }
  });

  it('hides Complete PIR for completed, waived, unsupported, and missing reviews', async () => {
    for (const pir of [
      { ...BASE_PIR, status: 'completed' },
      { ...BASE_PIR, status: 'waived' },
      { ...BASE_PIR, status: 'draft' },
      null,
    ]) {
      resetMocks();
      await renderPIR({ status: 'pir_required', pir });

      expect(screen.queryByRole('button', { name: 'Complete PIR' })).toBeNull();
    }
  });

  it('requires a valid outcome before completing a PIR', async () => {
    for (const outcome of ['', 'unknown_outcome']) {
      resetMocks();
      await renderPIR({
        status: 'pir_required',
        pir: { ...BASE_PIR, status: 'pending', outcome, completed_at: null },
      });

      fireEvent.click(screen.getByRole('button', { name: 'Complete PIR' }));

      expect(await screen.findByText(
        'Select a valid outcome before completing the PIR.',
      )).toBeTruthy();
      expect(mockPost).not.toHaveBeenCalled();
      expect(mockGet).toHaveBeenCalledTimes(2);
    }
  });

  it('requires a saved outcome even when the form has a valid value', async () => {
    await renderPIR({
      status: 'pir_required',
      pir: { ...BASE_PIR, status: 'pending', outcome: '', completed_at: null },
    });

    fireEvent.change(screen.getByLabelText('Outcome'), { target: { value: 'successful' } });
    fireEvent.click(screen.getByRole('button', { name: 'Complete PIR' }));

    expect(await screen.findByText(
      'Save a valid outcome before completing the PIR.',
    )).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('completes the PIR with an empty payload, displays status, and refreshes', async () => {
    const activePir = { ...BASE_PIR, status: 'in_progress', completed_at: null };
    const store = await renderPIR({ status: 'pir_required', pir: activePir });
    const completedPir = {
      ...activePir,
      status: 'completed',
      completed_at: '2026-12-03T10:00:00Z',
      reviewed_by: 1,
      reviewed_by_email: 'user@example.com',
    };
    mockPost.mockImplementation(async (url, body) => {
      if (url !== COMPLETE_URL) throw new Error(`Unexpected POST: ${url}`);
      store.pir = completedPir;
      return { data: completedPir };
    });

    fireEvent.click(screen.getByRole('button', { name: 'Complete PIR' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(COMPLETE_URL, {});
    });
    await waitFor(() => {
      expect(pirStatusCell().textContent).toContain('completed');
    });
    expect(await screen.findByText('PIR completed.')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(4);
    expect(getCalls().filter((url) => url === PIR_LIST_URL).length).toBe(2);
    expect(getCalls().every((url) => url === CHANGE_URL || url === PIR_LIST_URL))
      .toBe(true);
    expect(screen.queryByRole('button', { name: 'Complete PIR' })).toBeNull();
  });

  it('shows completion API errors without false success or refresh', async () => {
    await renderPIR({
      status: 'pir_required',
      pir: { ...BASE_PIR, status: 'pending', completed_at: null },
    });
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'PIR completion rejected.' } },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Complete PIR' }));

    expect(await screen.findByText('PIR completion rejected.')).toBeTruthy();
    expect(screen.queryByText('PIR completed.')).toBeNull();
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('prevents duplicate completion submissions while the request is in progress', async () => {
    const activePir = { ...BASE_PIR, status: 'pending', completed_at: null };
    const store = await renderPIR({ status: 'pir_required', pir: activePir });
    const completedPir = { ...activePir, status: 'completed' };
    let resolvePost;
    mockPost.mockImplementation(() => new Promise((resolve) => {
      store.pir = completedPir;
      resolvePost = resolve;
    }));

    fireEvent.click(screen.getByRole('button', { name: 'Complete PIR' }));

    expect(mockPost).toHaveBeenCalledTimes(1);
    const inFlightButton = screen.getByRole('button', { name: 'Complete PIR' });
    expect(inFlightButton.disabled).toBe(true);
    fireEvent.click(inFlightButton);
    expect(mockPost).toHaveBeenCalledTimes(1);

    resolvePost({ data: completedPir });

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledTimes(4);
    });
    expect(await screen.findByText('PIR completed.')).toBeTruthy();
    expect(pirStatusCell().textContent).toContain('completed');
  });

  it('hides lifecycle actions where the backend cannot perform them', async () => {
    const cases = [
      {
        status: 'pir_required',
        riskLevel: 'low',
        pirStatus: 'pending',
        request: false,
        close: false,
      },
      {
        status: 'completed',
        riskLevel: 'high',
        pirStatus: 'completed',
        request: true,
        close: false,
      },
    ];
    for (const testCase of cases) {
      resetMocks();
      await renderPIR({
        status: testCase.status,
        riskLevel: testCase.riskLevel,
        pir: { ...BASE_PIR, status: testCase.pirStatus },
      });

      expect(screen.queryByRole('button', { name: 'Request PIR' }) !== null)
        .toBe(testCase.request);
      expect(screen.queryByRole('button', { name: 'Close Change' }) !== null)
        .toBe(testCase.close);
    }
  });

  it('shows Close Change for pir_required only after the PIR is completed', async () => {
    resetMocks();
    await renderPIR({
      status: 'pir_required',
      pir: { ...BASE_PIR, status: 'in_progress', completed_at: null },
    });
    expect(screen.queryByRole('button', { name: 'Close Change' })).toBeNull();

    resetMocks();
    await renderPIR({
      status: 'pir_required',
      pir: { ...BASE_PIR, status: 'completed' },
    });
    fireEvent.change(screen.getByLabelText('Closure summary'), {
      target: { value: 'Reviewed and closed.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Close Change' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/changes/7/close/', {
        closure_summary: 'Reviewed and closed.',
      });
    });
    expect(await screen.findByText('Closure recorded.')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(4);
    expect(getCalls().filter((url) => url === PIR_LIST_URL).length).toBe(2);
  });

  it('keeps closure unavailable for pir_required with missing or incomplete PIRs', async () => {
    for (const pir of [
      null,
      { ...BASE_PIR, status: 'pending', completed_at: null },
      { ...BASE_PIR, status: 'waived' },
    ]) {
      resetMocks();
      await renderPIR({ status: 'pir_required', pir });

      expect(screen.queryByRole('button', { name: 'Close Change' })).toBeNull();
    }
  });

  it('preserves completed low/medium-risk closure without a PIR', async () => {
    for (const riskLevel of ['low', 'medium']) {
      resetMocks();
      await renderPIR({ status: 'completed', riskLevel, pir: null });

      expect(screen.getByRole('button', { name: 'Close Change' })).toBeTruthy();
    }
  });

  it('lets an employee load and view their own PIR without mutation controls', async () => {
    await renderPIR({
      role: 'employee',
      pir: { ...BASE_PIR, status: 'pending', completed_at: null },
    });

    expect(mockGet).toHaveBeenCalledWith(PIR_LIST_URL);
    expect(getCalls().every((url) => url === CHANGE_URL || url === PIR_LIST_URL))
      .toBe(true);
    expect(screen.getByText('reviewer@example.com')).toBeTruthy();
    expect(pirStatusCell().textContent).toContain('pending');
    expect(screen.queryByRole('button', { name: 'Create PIR' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Update PIR' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Complete PIR' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Request PIR' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Close Change' })).toBeNull();
    expect(screen.getByText(
      'PIR actions available to IT managers and System Admins only',
    )).toBeTruthy();
  });

  it('lets IT Support view PIR details but not invoke mutations', async () => {
    await renderPIR({
      role: 'it_support',
      pir: { ...BASE_PIR, status: 'pending', completed_at: null },
    });

    expect(mockGet).toHaveBeenCalledWith(PIR_LIST_URL);
    expect(screen.getByText('reviewer@example.com')).toBeTruthy();
    expect(pirStatusCell().textContent).toContain('pending');
    expect(screen.queryByRole('button', { name: 'Complete PIR' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Create PIR' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Update PIR' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Request PIR' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Close Change' })).toBeNull();
    expect(screen.getByText(
      'PIR actions available to IT managers and System Admins only',
    )).toBeTruthy();
  });

  it('retains manager and admin view and mutation controls', async () => {
    for (const role of ['it_manager', 'system_admin']) {
      resetMocks();
      await renderPIR({
        role,
        pir: { ...BASE_PIR, status: 'pending', completed_at: null },
      });

      expect(mockGet).toHaveBeenCalledWith(PIR_LIST_URL);
      expect(screen.getByRole('button', { name: 'Update PIR' })).toBeTruthy();
      expect(screen.getByRole('button', { name: 'Complete PIR' })).toBeTruthy();
      expect(screen.getByRole('button', { name: 'Request PIR' })).toBeTruthy();
    }
  });

  it('does not load PIRs for an account without read access', async () => {
    mockAuth.mockReturnValue(makeAuth('unknown_role'));
    mockGet.mockImplementation(async (url) => {
      if (url === CHANGE_URL) return { data: { ...BASE_CHANGE } };
      throw new Error(`Unexpected GET: ${url}`);
    });

    render(<ChangePIR match={{ params: { id: '7' } }} />);

    expect(await screen.findByText(
      'PIR details are not available for this account.',
    )).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith(CHANGE_URL);
    expect(mockGet).not.toHaveBeenCalledWith(PIR_LIST_URL);
    expect(mockGet).not.toHaveBeenCalledWith(UNFILTERED_PIR_URL);
  });

  it('shows a load failure with a retry control', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockGet.mockRejectedValueOnce({
      response: { status: 500, data: { detail: 'PIR service unavailable.' } },
    });

    render(<ChangePIR match={{ params: { id: '7' } }} />);

    expect(await screen.findByText('PIR service unavailable.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  });

  it('retries the filtered PIR request after a load failure', async () => {
    const store = { change: { ...BASE_CHANGE }, pir: BASE_PIR };
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockGet
      .mockRejectedValueOnce({
        response: { status: 500, data: { detail: 'PIR service unavailable.' } },
      })
      .mockImplementation(async (url) => {
        if (url === CHANGE_URL) return { data: store.change };
        if (url === PIR_LIST_URL) {
          return { data: { count: 1, results: [store.pir] } };
        }
        throw new Error(`Unexpected GET: ${url}`);
      });

    render(<ChangePIR match={{ params: { id: '7' } }} />);

    expect(await screen.findByText('PIR service unavailable.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByRole('heading', { name: 'PIR & Closure' })).toBeTruthy();
    expect(screen.getByText('reviewer@example.com')).toBeTruthy();
    expect(getCalls().filter((url) => url === PIR_LIST_URL).length).toBe(1);
    expect(getCalls().every((url) => url === CHANGE_URL || url === PIR_LIST_URL))
      .toBe(true);
  });
});
