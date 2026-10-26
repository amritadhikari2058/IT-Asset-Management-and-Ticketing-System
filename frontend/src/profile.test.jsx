import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

const { mockPost, mockPatch, mockAuth } = vi.hoisted(() => ({
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: vi.fn(),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { Profile } from './pages';

function user(over = {}) {
  return {
    employee_id: 'E1', email: 'e@x', role: 'employee',
    email_verified: false, receive_ticket_emails: true, ...over,
  };
}

function ctx(over = {}) {
  return {
    user: user(), refreshProfile: vi.fn(), isStaff: false, isAdmin: false,
    canCreateTickets: true, ...over,
  };
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.confirm = vi.fn(() => true);
});

afterEach(() => cleanup());

describe('Profile page', () => {
  it('shows unverified status from the server flag', () => {
    mockAuth.mockReturnValue(ctx());
    render(<Profile />);
    expect(screen.getByText('Unverified')).toBeTruthy();
  });

  it('shows verified status when the flag is true', () => {
    mockAuth.mockReturnValue(ctx({ user: user({ email_verified: true }) }));
    render(<Profile />);
    expect(screen.getByText('Verified')).toBeTruthy();
    expect(screen.queryByText('Unverified')).toBeNull();
  });

  it('changes password with current + validated new password', async () => {
    mockAuth.mockReturnValue(ctx());
    mockPost.mockResolvedValueOnce({ data: { detail: 'Password updated.' } });
    render(<Profile />);
    fireEvent.change(screen.getByLabelText(/^Current password/), {
      target: { value: 'old-pass-123' },
    });
    fireEvent.change(screen.getByLabelText(/^New password/), {
      target: { value: 'brand-new-pass-99' },
    });
    fireEvent.change(screen.getByLabelText(/^Confirm new password/), {
      target: { value: 'brand-new-pass-99' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }));
    await screen.findByText('Password updated.');
    expect(mockPost).toHaveBeenCalledWith('/accounts/change-password/', {
      current_password: 'old-pass-123', new_password: 'brand-new-pass-99',
    });
  });

  it('blocks mismatched confirmation client-side', async () => {
    mockAuth.mockReturnValue(ctx());
    render(<Profile />);
    fireEvent.change(screen.getByLabelText(/^Current password/), {
      target: { value: 'old-pass-123' },
    });
    fireEvent.change(screen.getByLabelText(/^New password/), {
      target: { value: 'brand-new-pass-99' },
    });
    fireEvent.change(screen.getByLabelText(/^Confirm new password/), {
      target: { value: 'different-pass-99' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByText('New passwords do not match.')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('surfaces wrong-current-password errors', async () => {
    mockAuth.mockReturnValue(ctx());
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'Current password is incorrect.' } },
    });
    render(<Profile />);
    fireEvent.change(screen.getByLabelText(/^Current password/), {
      target: { value: 'wrong' },
    });
    fireEvent.change(screen.getByLabelText(/^New password/), {
      target: { value: 'brand-new-pass-99' },
    });
    fireEvent.change(screen.getByLabelText(/^Confirm new password/), {
      target: { value: 'brand-new-pass-99' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByText('Current password is incorrect.')).toBeTruthy();
  });

  it('surfaces policy validation errors', async () => {
    mockAuth.mockReturnValue(ctx());
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { new_password: ['Too short.'] } },
    });
    render(<Profile />);
    fireEvent.change(screen.getByLabelText(/^Current password/), {
      target: { value: 'old-pass-123' },
    });
    fireEvent.change(screen.getByLabelText(/^New password/), {
      target: { value: 'short' },
    });
    fireEvent.change(screen.getByLabelText(/^Confirm new password/), {
      target: { value: 'short' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByText('Too short.')).toBeTruthy();
  });
});


