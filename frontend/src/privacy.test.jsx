import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
    delete: (...args) => mockDelete(...args),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { Privacy } from './privacy';

function ctx(over = {}) {
  return { isAdmin: false, isStaff: false, ...over };
}

const REQ = {
  id: 7, entity_type: 'accounts.User', object_id: '42', scope: 'email, name',
  reason: 'leaver request', status: 'pending_review',
  requested_by: 1, requested_by_email: 'admin@example.com',
  requested_by_employee_id: 'A1',
  reviewed_by: null, reviewer_email: null, reviewed_at: null,
  review_decision: null, review_reason: '',
  executed_by: null, executor_email: null, executed_at: null,
  cancellation_reason: '', created_at: '2026-01-01T08:00:00Z',
  decided_at: null, result: {},
  dependency_check: {
    exists: true, is_deleted: false, entity_type: 'accounts.User',
    object_id: '42', can_proceed: true, requires_manual_review: false,
    related: { tickets_requested: 2, notifications: 0 },
    assessment: [{ category: 'tickets', action: 'retain', reason: 'Tickets remain.' }],
    retention: ['Audit logs are retained (never erased).'],
  },
  audit_history: [],
};

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '#/privacy';
});

afterEach(() => cleanup());

describe('Privacy erasure page', () => {
  it('restricts access to non-admins', () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: false }));
    render(<Privacy />);
    expect(screen.getByText('Access restricted')).toBeTruthy();
  });

  it('renders the dashboard for admins', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: { results: [], count: 0, next: null, previous: null } });
    render(<Privacy />);
    await screen.findByText('Privacy Erasure');
    expect(screen.getByText('Two-person-approval data lifecycle governance')).toBeTruthy();
  });

  it('lists erasure requests', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: { results: [REQ], count: 1, next: null, previous: null } });
    window.location.hash = '#/privacy/requests';
    render(<Privacy />);
    await screen.findByText('Erasure requests');
    const table = screen.getByRole('table');
    expect(table.textContent).toContain('Pending review');
    expect(table.textContent).toContain('42');
  });

  it('creates a request and shows dependency check', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: { results: [], count: 0, next: null, previous: null } });
    mockPost.mockResolvedValue({ data: { id: 3, status: 'pending_review', dependency_check: REQ.dependency_check } });
    window.location.hash = '#/privacy/requests/new';
    render(<Privacy />);
    await screen.findByText('Create erasure request');
    fireEvent.change(screen.getAllByLabelText(/Object ID/)[0], { target: { value: '42' } });
    fireEvent.change(screen.getByLabelText(/Scope/), { target: { value: 'email' } });
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: 'GDPR erasure' } });
    fireEvent.change(screen.getByLabelText(/Confirm Object ID/), { target: { value: '42' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create request' }));
    expect(mockPost).toHaveBeenCalledWith('/common/privacy-erasures/', {
      entity_type: 'accounts.User', object_id: '42', scope: 'email',
      reason: 'GDPR erasure', confirm: '42',
    });
  });

  it('shows request detail with reviewer and actions', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: REQ });
    window.location.hash = '#/privacy/requests/7';
    render(<Privacy />);
    await screen.findByText('Erasure request #7');
    expect(screen.getByText('Pending review')).toBeTruthy();
    expect(screen.getByText('admin@example.com')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve (independent review)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeTruthy();
  });

  it('approves a request via independent reviewer', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: REQ });
    mockPost.mockResolvedValue({ data: {} });
    window.location.hash = '#/privacy/requests/7';
    render(<Privacy />);
    await screen.findByText('Erasure request #7');
    fireEvent.click(screen.getByRole('button', { name: 'Approve (independent review)' }));
    await screen.findByText(/Independently approve this request/);
    const reasonInput = await screen.findByPlaceholderText(/Optional unless rejecting/);
    fireEvent.change(reasonInput, { target: { value: 'Approved.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await screen.findByText(/Erasure request #7/);
    expect(mockPost).toHaveBeenCalledWith('/common/privacy-erasures/7/approve/', {
      decision: 'approve', reason: 'Approved.',
    });
  });

  it('executes an approved request with confirmation', async () => {
    const approved = { ...REQ, status: 'approved' };
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: approved });
    mockPost.mockResolvedValue({ data: { executed: true, status: 'completed' } });
    window.location.hash = '#/privacy/requests/7';
    render(<Privacy />);
    await screen.findByText('Erasure request #7');
    fireEvent.click(screen.getByRole('button', { name: 'Execute erasure' }));
    fireEvent.click(screen.getByRole('button', { name: 'Execute' }));
    await screen.findByText(/Erasure request #7/);
    expect(mockPost).toHaveBeenCalledWith('/common/privacy-erasures/7/execute/', { confirm: '42' });
  });
});
