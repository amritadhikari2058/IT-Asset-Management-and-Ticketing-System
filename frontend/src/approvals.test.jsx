import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
  },
}));

vi.mock('./auth', () => ({ useAuth: (...args) => mockAuth(...args) }));

import { ApprovalCenter } from './approvals';

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockAuth.mockReturnValue({ isStaff: false });
  mockGet.mockResolvedValue({ data: { approvals: [], total: 0 } });
});

afterEach(() => cleanup());

describe('ApprovalCenter', () => {
  it('shows empty state when not staff', () => {
    render(<ApprovalCenter />);
    expect(screen.getByText('Approvals')).toBeTruthy();
    expect(screen.getByText('Only staff can access approvals.')).toBeTruthy();
  });

  it('loads and renders approval list when staff', async () => {
    mockAuth.mockReturnValue({ isStaff: true });
    mockGet.mockResolvedValueOnce({ data: { approvals: [] } });
    mockGet.mockResolvedValueOnce({ data: { total_pending: 0, service_requests: 0, disposals: 0, procurement: 0, workflow: 0, knowledge_base: 0, by_type: {} } });

    render(<ApprovalCenter />);
    await waitFor(() => expect(screen.queryByText('No pending approvals')).toBeTruthy());
    expect(mockGet).toHaveBeenCalledWith('/approvals/');
    expect(mockGet).toHaveBeenCalledWith('/approvals/counts/');
  });

  it('shows error state when request fails', async () => {
    mockAuth.mockReturnValue({ isStaff: true });
    mockGet.mockRejectedValueOnce(new Error('network error'));

    render(<ApprovalCenter />);
    await waitFor(() => expect(screen.getByText('Could not load pending approvals.')).toBeTruthy());
  });
});
