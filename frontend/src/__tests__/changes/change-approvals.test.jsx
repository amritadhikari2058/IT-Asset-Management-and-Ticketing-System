import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

const mockFetchPage = vi.fn();

vi.mock('../../shared/changes-utils', () => ({
  fetchPage: (...args) => mockFetchPage(...args),
  parseApiError: vi.fn(() => ({ global: 'Error' })),
}));

vi.mock('../../auth', () => ({
  useAuth: vi.fn(() => ({ isStaff: true, role: 'it_manager' })),
}));

import { ChangeApprovals } from '../../pages/changes/ChangeApprovals';

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '#/changes/1/approvals';
});

afterEach(() => cleanup());

describe('ChangeApprovals', () => {
  it('consumes the paginated helper response via data.items', async () => {
    mockFetchPage.mockResolvedValue({
      items: [
        {
          id: 1, approval_level: 'manager', status: 'pending',
          requested_from: 'it@x', requested_by_email: 'mgr@x',
          decided_by_email: null, requested_at: '2026-01-01T08:00:00Z',
          decided_at: null, decision_reason: '',
        },
      ],
      count: 1,
    });
    render(<ChangeApprovals match={{ params: { id: '1' } }} />);
    expect(mockFetchPage).toHaveBeenCalledWith('/changes/1/approvals/');
    await screen.findByText('manager');
    await screen.findByText('mgr@x');
  });

  it('displays fields that exist in the serializer', async () => {
    mockFetchPage.mockResolvedValue({
      items: [
        {
          id: 1, approval_level: 'manager', status: 'approved',
          requested_from: 'it@x', requested_by_email: 'mgr@x',
          decided_by_email: 'admin@x',
          requested_at: '2026-01-01T08:00:00Z',
          decided_at: '2026-01-02T09:00:00Z',
          decision_reason: 'looks good',
        },
      ],
      count: 1,
    });
    render(<ChangeApprovals match={{ params: { id: '1' } } } />);
    await screen.findByText('2026-01-01T08:00:00Z');
    await screen.findByText('2026-01-02T09:00:00Z');
    await screen.findByText('mgr@x');
    await screen.findByText('admin@x');
    await screen.findByText('looks good');
  });

  it('shows an error state when the fetch fails', async () => {
    mockFetchPage.mockRejectedValue(new Error('boom'));
    render(<ChangeApprovals match={{ params: { id: '1' } }} />);
    await screen.findByText(/Error/);
  });
});
