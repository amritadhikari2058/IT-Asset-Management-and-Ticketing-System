import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import React from 'react';

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }));
vi.mock('./api', () => ({ default: { get: (...a) => mockGet(...a), post: vi.fn() } }));

import { VerifyEmail } from './pages';

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '';
});

afterEach(() => cleanup());

describe('VerifyEmail', () => {
  it('shows success after valid uid and token', async () => {
    window.location.hash = '#/verify-email?uid=abc&token=xyz';
    mockGet.mockResolvedValue({ data: { detail: 'Email verified.' } });
    render(<VerifyEmail />);
    await waitFor(() => expect(screen.getByText('Email verified.')).toBeTruthy());
    expect(mockGet).toHaveBeenCalledWith('/accounts/verify-email/confirm/?uid=abc&token=xyz');
  });

  it('shows invalid link on backend rejection', async () => {
    window.location.hash = '#/verify-email?uid=abc&token=bad';
    mockGet.mockRejectedValue(new Error('bad'));
    render(<VerifyEmail />);
    await waitFor(() => expect(screen.getByText('Invalid or expired link.')).toBeTruthy());
  });

  it('shows invalid link when uid is missing', async () => {
    window.location.hash = '#/verify-email?token=xyz';
    render(<VerifyEmail />);
    await waitFor(() => expect(screen.getByText('Invalid or expired link.')).toBeTruthy());
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('shows invalid link when token is missing', async () => {
    window.location.hash = '#/verify-email?uid=abc';
    render(<VerifyEmail />);
    await waitFor(() => expect(screen.getByText('Invalid or expired link.')).toBeTruthy());
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('shows invalid link on network failure', async () => {
    window.location.hash = '#/verify-email?uid=abc&token=xyz';
    mockGet.mockRejectedValue(new Error('network'));
    render(<VerifyEmail />);
    await waitFor(() => expect(screen.getByText('Invalid or expired link.')).toBeTruthy());
  });

  it('shows loading state while request is pending', async () => {
    window.location.hash = '#/verify-email?uid=abc&token=xyz';
    let resolve;
    mockGet.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<VerifyEmail />);
    expect(screen.getByText('Verifying...')).toBeTruthy();
    resolve({ data: { detail: 'Email verified.' } });
    await waitFor(() => expect(screen.getByText('Email verified.')).toBeTruthy());
  });

  it('does not show success before backend confirmation', async () => {
    window.location.hash = '#/verify-email?uid=abc&token=xyz';
    let resolve;
    mockGet.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<VerifyEmail />);
    expect(screen.queryByText('Email verified.')).toBeNull();
    resolve({ data: { detail: 'Email verified.' } });
    await waitFor(() => expect(screen.getByText('Email verified.')).toBeTruthy());
  });
});
