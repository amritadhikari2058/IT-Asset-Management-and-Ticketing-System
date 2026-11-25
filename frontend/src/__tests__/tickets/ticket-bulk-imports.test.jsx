import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
  },
}));
vi.mock('../../auth', () => ({ useAuth: () => mockAuth() }));

import { TicketBulkImportDetailPage, TicketBulkImportsPage } from '../../pages/tickets/TicketBulkImportsPage';

const baseOp = {
  id: 7,
  user: 2,
  user_email: 'mgr@example.com',
  status: 'failed',
  total_rows: 2,
  processed_count: 2,
  successful_count: 1,
  failed_count: 1,
  result_format: '',
  result_status_code: 200,
  result_available: false,
  error_detail: 'interrupted',
  is_expired: false,
  is_stale_processing: false,
  created_at: '2026-11-21T10:00:00Z',
  updated_at: '2026-11-21T10:05:00Z',
  started_at: '2026-11-21T10:01:00Z',
  completed_at: null,
  expires_at: '2026-11-22T10:00:00Z',
};

const eligibleAssessment = {
  operation_id: 7,
  current_status: 'failed',
  expected_row_count: 2,
  actual_outcome_count: 2,
  succeeded_outcome_count: 1,
  failed_outcome_count: 1,
  unprocessed_row_count: 0,
  duplicate_or_inconsistent_evidence: [],
  missing_ticket_references: [],
  counter_inconsistencies: [],
  legacy_or_ambiguous_indicators: [],
  reasons: [],
  eligible_for_finalization: true,
  proposed_status: 'completed',
  proposed_result_status_code: 200,
  evidence_digest: 'digest-abc123',
  result_stored: false,
  result_conflicts: [],
  has_row_level_evidence: true,
  is_stale_processing: false,
};

function ineligibleAssessment(overrides = {}) {
  return {
    ...eligibleAssessment,
    eligible_for_finalization: false,
    proposed_status: null,
    reasons: ['unprocessed_or_unrecorded_rows'],
    unprocessed_row_count: 1,
    ...overrides,
  };
}

function setupDetail({ op = baseOp, assessment = eligibleAssessment, audit = [] } = {}) {
  mockGet.mockImplementation(async (url) => {
    if (url === `/tickets/bulk-imports/${op.id}/`) return { data: op };
    if (url === `/tickets/bulk-imports/${op.id}/reconciliation/`) return { data: assessment };
    if (url === `/tickets/bulk-imports/${op.id}/reconciliation/audit/`) return { data: { operation_id: op.id, audit } };
    throw new Error(`unexpected GET ${url}`);
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_manager' } });
});

afterEach(() => cleanup());

describe('TicketBulkImportsPage', () => {
  it('renders staff-only list and loads operations', async () => {
    mockGet.mockResolvedValueOnce({
      data: { count: 1, next: null, previous: null, results: [baseOp] },
    });
    render(<TicketBulkImportsPage />);
    await waitFor(() => expect(screen.getByText('#7')).toBeTruthy());
    expect(screen.getByText('mgr@example.com')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Inspect' }).getAttribute('href')).toBe('#/tickets/bulk-imports/7');
  });

  it('shows loading and empty states', async () => {
    let resolve;
    mockGet.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    render(<TicketBulkImportsPage />);
    expect(screen.getByRole('status')).toBeTruthy();
    resolve({ data: { count: 0, next: null, previous: null, results: [] } });
    await waitFor(() => expect(screen.getByText('No bulk import operations')).toBeTruthy());
  });

  it('shows API failure', async () => {
    mockGet.mockRejectedValueOnce({ response: { data: { detail: 'boom' } } });
    render(<TicketBulkImportsPage />);
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('boom'));
  });

  it('blocks non-staff users', () => {
    mockAuth.mockReturnValue({ isStaff: false, user: { role: 'employee' } });
    render(<TicketBulkImportsPage />);
    expect(screen.getByRole('alert').textContent).toMatch(/permission/i);
    expect(mockGet).not.toHaveBeenCalled();
  });
});

describe('TicketBulkImportDetailPage assessment', () => {
  it('shows eligible assessment with backend-provided digest and no independent eligibility', async () => {
    setupDetail();
    render(<TicketBulkImportDetailPage id={7} />);
    await waitFor(() => expect(screen.getByText('Eligible for finalization')).toBeTruthy());
    expect(screen.getByText(/digest-abc123/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Finalize operation' })).toBeTruthy();
  });

  it('shows ineligible assessment with reasons', async () => {
    setupDetail({ assessment: ineligibleAssessment() });
    render(<TicketBulkImportDetailPage id={7} />);
    await waitFor(() => expect(screen.getByText('Ineligible for finalization')).toBeTruthy());
    expect(screen.getAllByText(/unprocessed_or_unrecorded_rows/).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Finalize operation' })).toBeNull();
  });

  it('shows missing ticket reference as blocking integrity warning', async () => {
    setupDetail({ assessment: ineligibleAssessment({
      reasons: ['missing_ticket_reference'],
      missing_ticket_references: [{ row_index: 1, outcome_id: 99, ticket_id: null, issue: 'succeeded_outcome_missing_ticket_reference' }],
    }) });
    render(<TicketBulkImportDetailPage id={7} />);
    await waitFor(() => expect(screen.getByText(/Missing ticket references \(finalization blocked\)/)).toBeTruthy());
    expect(screen.getByText(/cannot be safely finalized/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Finalize operation' })).toBeNull();
  });

  it('shows counter inconsistency warning transparently', async () => {
    setupDetail({ assessment: { ...eligibleAssessment, counter_inconsistencies: ['successful_count_mismatch:stored=0,actual=1'] } });
    render(<TicketBulkImportDetailPage id={7} />);
    await waitFor(() => expect(screen.getByText(/Counter discrepancies reported/)).toBeTruthy());
    expect(screen.getByText(/explicit audited finalization/i)).toBeTruthy();
  });

  it('shows already finalized state', async () => {
    setupDetail({ assessment: ineligibleAssessment({ reasons: ['already_finalized'], current_status: 'completed', proposed_status: null, result_stored: true }) });
    render(<TicketBulkImportDetailPage id={7} />);
    await waitFor(() => expect(screen.getByText('Already finalized')).toBeTruthy());
    expect(screen.queryByRole('button', { name: 'Finalize operation' })).toBeNull();
  });

  it('shows assessment failure', async () => {
    mockGet.mockImplementation(async (url) => {
      if (url.endsWith('/reconciliation/')) throw { response: { data: { detail: 'assess boom' } } };
      if (url.endsWith('/reconciliation/audit/')) return { data: { operation_id: 7, audit: [] } };
      if (url.endsWith('/7/')) return { data: baseOp };
      throw new Error(url);
    });
    render(<TicketBulkImportDetailPage id={7} />);
    await waitFor(() => expect(screen.getByText(/assess boom|Could not load/)).toBeTruthy());
  });

  it('denies non-staff users', () => {
    mockAuth.mockReturnValue({ isStaff: false, user: { role: 'employee' } });
    render(<TicketBulkImportDetailPage id={7} />);
    expect(screen.getByRole('alert').textContent).toMatch(/permission/i);
    expect(mockGet).not.toHaveBeenCalled();
  });
});

describe('TicketBulkImportDetailPage finalization', () => {
  async function openFinalize() {
    setupDetail();
    render(<TicketBulkImportDetailPage id={7} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Finalize operation' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Finalize operation' }));
    await waitFor(() => expect(screen.getByRole('dialog', { name: /Finalize import operation #7/ })).toBeTruthy());
  }

  it('requires a reason and rejects whitespace-only reason', async () => {
    await openFinalize();
    const reason = screen.getByLabelText('Reason for finalization');
    fireEvent.change(reason, { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm finalization' }));
    await waitFor(() => expect(screen.getByText('A reason is required for finalization.')).toBeTruthy());
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('submits exact digest and expected status binding', async () => {
    await openFinalize();
    mockPost.mockResolvedValueOnce({ data: { finalized: true, idempotent: false, status: 'completed' } });
    // refresh after finalize
    mockGet.mockImplementation(async (url) => {
      if (url.endsWith('/7/')) return { data: { ...baseOp, status: 'completed' } };
      if (url.endsWith('/reconciliation/')) return { data: ineligibleAssessment({ reasons: ['already_finalized'], current_status: 'completed', result_stored: true }) };
      if (url.endsWith('/reconciliation/audit/')) return { data: { operation_id: 7, audit: [{ id: 1, timestamp: '2026-11-21T10:10:00Z', actor_email: 'admin@example.com', action: 'update', finalization_outcome: 'finalized', previous_operation_state: 'failed', resulting_operation_state: 'completed', expected_row_count: 2, succeeded_row_count: 1, failed_row_count: 1, reason: 'ok', evidence_digest: 'digest-abc123' }] } };
      throw new Error(url);
    });
    fireEvent.change(screen.getByLabelText('Reason for finalization'), { target: { value: 'Reviewed evidence' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm finalization' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    expect(mockPost.mock.calls[0][0]).toBe('/tickets/bulk-imports/7/reconciliation/finalize/');
    expect(mockPost.mock.calls[0][1]).toEqual({
      reason: 'Reviewed evidence',
      evidence_digest: 'digest-abc123',
      expected_status: 'failed',
    });
    await waitFor(() => expect(screen.getByText(/Finalization completed/)).toBeTruthy());
  });

  it('handles idempotent success', async () => {
    await openFinalize();
    mockPost.mockResolvedValueOnce({ data: { finalized: true, idempotent: true, status: 'completed' } });
    mockGet.mockImplementation(async (url) => {
      if (url.endsWith('/7/')) return { data: { ...baseOp, status: 'completed' } };
      if (url.endsWith('/reconciliation/')) return { data: ineligibleAssessment({ reasons: ['already_finalized'], current_status: 'completed', result_stored: true }) };
      if (url.endsWith('/reconciliation/audit/')) return { data: { operation_id: 7, audit: [] } };
      throw new Error(url);
    });
    fireEvent.change(screen.getByLabelText('Reason for finalization'), { target: { value: 'retry' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm finalization' }));
    await waitFor(() => expect(screen.getByText(/Operation was already finalized\. Showing the current recorded state\./i)).toBeTruthy());
  });

  it('prevents duplicate in-flight submissions', async () => {
    await openFinalize();
    let resolve;
    mockPost.mockImplementation(() => new Promise((r) => { resolve = r; }));
    fireEvent.change(screen.getByLabelText('Reason for finalization'), { target: { value: 'once' } });
    const btn = screen.getByRole('button', { name: 'Confirm finalization' });
    fireEvent.click(btn);
    fireEvent.click(btn);
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    resolve({ data: { finalized: true, idempotent: false } });
  });

  it('does not auto-retry stale evidence and refreshes assessment', async () => {
    await openFinalize();
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: { code: 'stale_evidence', detail: 'stale' } } });
    mockGet.mockImplementation(async (url) => {
      if (url.endsWith('/7/')) return { data: baseOp };
      if (url.endsWith('/reconciliation/')) return { data: ineligibleAssessment({ reasons: ['missing_ticket_reference'], missing_ticket_references: [{ row_index: 0, outcome_id: 1, ticket_id: null, issue: 'missing' }] }) };
      if (url.endsWith('/reconciliation/audit/')) return { data: { operation_id: 7, audit: [] } };
      throw new Error(url);
    });
    fireEvent.change(screen.getByLabelText('Reason for finalization'), { target: { value: 'stale test' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm finalization' }));
    await waitFor(() => expect(screen.getByText(/not applied because evidence changed/i)).toBeTruthy());
    // Only the initial finalize POST; no auto-retry.
    expect(mockPost).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByText(/Missing ticket references \(finalization blocked\)/)).toBeTruthy());
  });

  it('handles 403/404/500 errors', async () => {
    for (const [status, detail] of [[403, 'Forbidden'], [404, 'Not found'], [500, 'Server error']]) {
      cleanup();
      vi.clearAllMocks();
      mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_manager' } });
      await openFinalize();
      mockPost.mockRejectedValueOnce({ response: { status, data: { detail } } });
      fireEvent.change(screen.getByLabelText('Reason for finalization'), { target: { value: 'reason' } });
      fireEvent.click(screen.getByRole('button', { name: 'Confirm finalization' }));
      await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(new RegExp(detail, 'i')));
    }
  });
});

describe('TicketBulkImportDetailPage audit history', () => {
  it('renders audit entries read-only', async () => {
    setupDetail({
      assessment: ineligibleAssessment({ reasons: ['already_finalized'], current_status: 'completed', result_stored: true }),
      audit: [{
        id: 1, timestamp: '2026-11-21T10:10:00Z', actor_email: 'admin@example.com', action: 'update',
        finalization_outcome: 'finalized', previous_operation_state: 'failed', resulting_operation_state: 'completed',
        expected_row_count: 2, succeeded_row_count: 1, failed_row_count: 1, reason: 'manual close', evidence_digest: 'digest-abc123',
      }],
    });
    render(<TicketBulkImportDetailPage id={7} />);
    await waitFor(() => expect(screen.getByText('manual close')).toBeTruthy());
    expect(screen.getByText('admin@example.com')).toBeTruthy();
    expect(screen.getByText('finalized')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /edit audit/i })).toBeNull();
  });

  it('shows empty audit state', async () => {
    setupDetail({ audit: [] });
    render(<TicketBulkImportDetailPage id={7} />);
    await waitFor(() => expect(screen.getByText('No finalization audit records')).toBeTruthy());
  });
});
