import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({ useAuth: (...args) => mockAuth(...args) }));

import Workflow from './workflow';

const BASE = {
  id: 5,
  ticket: 7,
  ticket_title: 'Broken laptop',
  requested_by: 3,
  requested_by_email: 'employee@x',
  approver: null,
  approver_email: null,
  operation: 'change_priority',
  operation_display: 'Change priority',
  context: { priority: 'critical' },
  reason: 'Vendor confirmed emergency',
  status: 'pending',
  status_display: 'Pending',
  decision_comment: '',
  decided_by: null,
  decided_by_email: null,
  decided_at: null,
  created_at: '2024-01-01T10:00:00Z',
  updated_at: '2024-01-01T10:00:00Z',
};

let decisionState;

function currentApproval() {
  if (decisionState === 'pending') return { ...BASE };
  return {
    ...BASE,
    status: decisionState,
    status_display: decisionState === 'approved' ? 'Approved' : 'Rejected',
    decision_comment: 'Emergency confirmed',
    decided_by: 2,
    decided_by_email: 'manager@x',
    decided_at: '2024-01-02T10:00:00Z',
  };
}

function approver(id = 2) {
  mockAuth.mockReturnValue({
    isStaff: true, isAdmin: false, user: { id, role: 'it_manager' },
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  decisionState = 'pending';
  approver(2);
  window.location.hash = '';
  mockGet.mockImplementation(async (url) => {
    if (String(url) === '/workflow/approval-requests/5/') return { data: currentApproval() };
    return { data: { results: [], count: 0, next: null, previous: null } };
  });
  mockPost.mockImplementation(async () => {
    decisionState = 'approved';
    return { data: currentApproval() };
  });
});

afterEach(() => cleanup());

describe('approval detail and decisions', () => {
  it('shows the complete approval request', async () => {
    render(<Workflow approvalId="5" />);
    await screen.findByRole('heading', { name: 'Approval #5' });

    expect(screen.getByText('#7 Broken laptop')).toBeTruthy();
    expect(screen.getByText('employee@x')).toBeTruthy();
    expect(screen.getAllByText('Change priority').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Pending approval').length).toBeGreaterThan(0);
    expect(screen.getByText('Priority: critical')).toBeTruthy();
    expect(screen.getByText(/Vendor confirmed emergency/)).toBeTruthy();
    expect(screen.getByText('Any IT staff')).toBeTruthy();
  });

  it('approves with a comment after confirmation and refreshes the detail', async () => {
    render(<Workflow approvalId="5" />);
    await screen.findByRole('heading', { name: 'Approval #5' });

    fireEvent.change(screen.getByLabelText('Decision comment'), {
      target: { value: 'Emergency confirmed' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Approve…' }));
    expect(await screen.findByText('Approve this request?')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Approve request' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/workflow/approval-requests/5/approve/',
      { comment: 'Emergency confirmed' },
    ));
    expect(await screen.findByText(/Approval recorded/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve…' })).toBeNull();
    // The detail was re-fetched after the decision.
    expect(mockGet.mock.calls.filter(([url]) => url === '/workflow/approval-requests/5/').length)
      .toBeGreaterThan(1);
  });

  it('rejects with a decision comment', async () => {
    mockPost.mockImplementationOnce(async () => {
      decisionState = 'rejected';
      return { data: currentApproval() };
    });
    render(<Workflow approvalId="5" />);
    await screen.findByRole('heading', { name: 'Approval #5' });

    fireEvent.change(screen.getByLabelText('Decision comment'), {
      target: { value: 'Not justified' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reject…' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Reject request' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/workflow/approval-requests/5/reject/',
      { comment: 'Not justified' },
    ));
    expect(await screen.findByText('Approval request rejected.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Reject…' })).toBeNull();
  });

  it('prevents duplicate submissions while a decision is in flight', async () => {
    let resolvePost;
    mockPost.mockImplementationOnce(() => new Promise((resolve) => { resolvePost = resolve; }));
    render(<Workflow approvalId="5" />);
    await screen.findByRole('heading', { name: 'Approval #5' });

    fireEvent.click(screen.getByRole('button', { name: 'Approve…' }));
    const confirm = await screen.findByRole('button', { name: 'Approve request' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(mockPost).toHaveBeenCalledTimes(1);

    decisionState = 'approved';
    resolvePost({ data: currentApproval() });
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Approve request' })).toBeNull());
  });

  it('handles a request already decided by another user', async () => {
    mockPost.mockImplementationOnce(async () => {
      decisionState = 'approved';
      throw {
        response: {
          status: 409,
          data: { detail: 'This approval has already been decided by another user.' },
        },
      };
    });
    render(<Workflow approvalId="5" />);
    await screen.findByRole('heading', { name: 'Approval #5' });

    fireEvent.click(screen.getByRole('button', { name: 'Approve…' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Approve request' }));

    expect(await screen.findByText(/already been decided by another user/i)).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Approve…' })).toBeNull());
    // Stale decision reloads the latest state.
    expect(mockGet.mock.calls.filter(([url]) => url === '/workflow/approval-requests/5/').length)
      .toBeGreaterThan(1);
  });

  it('does not offer decision controls to the requester', async () => {
    approver(3);
    render(<Workflow approvalId="5" />);
    await screen.findByRole('heading', { name: 'Approval #5' });
    expect(screen.getByText('You cannot decide your own approval request.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve…' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject…' })).toBeNull();
  });

  it('shows an error state for an unavailable approval', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 404, data: { detail: 'Not found.' } } });
    render(<Workflow approvalId="5" />);
    expect(await screen.findByText('Not found.')).toBeTruthy();
  });
});
