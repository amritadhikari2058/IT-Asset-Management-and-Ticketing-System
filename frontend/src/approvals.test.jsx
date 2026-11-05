import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ApprovalCenter } from './approvals';
import { useAuth } from './auth';
import api from './api';

vi.mock('./auth', () => ({
  useAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  get: vi.fn().mockResolvedValue({ data: { approvals: [], total: 0 } }),
}));

describe('ApprovalCenter', () => {
  it('shows empty state when not staff', () => {
    useAuth.mockReturnValue({ isStaff: false });
    render(<ApprovalCenter />);
    expect(screen.getByText('Approvals')).toBeInTheDocument();
    expect(screen.getByText('Only staff can access approvals.')).toBeInTheDocument();
  });

  it('loads and renders approval list when staff', async () => {
    useAuth.mockReturnValue({ isStaff: true });
    const getSpy = vi.spyOn(api, 'get');
    getSpy.mockResolvedValueOnce({ data: { approvals: [] } });
    getSpy.mockResolvedValueOnce({ data: { total: 0 } });

    render(<ApprovalCenter />);
    await waitFor(() => expect(screen.queryByText('No pending approvals')).toBeInTheDocument());
    expect(api.get).toHaveBeenCalledWith('/api/approvals/');
    expect(api.get).toHaveBeenCalledWith('/api/approvals/counts/');
  });

  it('shows error state when request fails', async () => {
    useAuth.mockReturnValue({ isStaff: true });
    api.get.mockRejectedValueOnce(new Error('network error'));
    vi.spyOn(api, 'get').mockRejectedValueOnce(new Error('network error'));


    render(<ApprovalCenter />);
    await waitFor(() => expect(screen.getByText('Could not load pending approvals.')).toBeInTheDocument());
  });
});
