import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
    delete: (...args) => mockDelete(...args),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { Retention } from '../../pages/retention/Retention';

function ctx(over = {}) {
  return { isAdmin: false, ...over };
}

const POLICY = {
  id: 4, name: 'Old notifications', data_category: 'notifications',
  retention_duration: 30, enabled: true, conditions: {}, description: '',
  last_run_at: null, next_run_at: null, responsible_admin: 1,
  responsible_admin_email: 'admin@example.com',
};

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '#/retention';
});

afterEach(() => cleanup());

describe('Data retention page', () => {
  it('restricts access to non-admins', () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: false }));
    render(<Retention />);
    expect(screen.getByText('Access restricted')).toBeTruthy();
  });

  it('lists retention policies for admins', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: { results: [POLICY], count: 1, next: null, previous: null } });
    render(<Retention />);
    await screen.findByText('Data retention policies');
    expect(screen.getByText('Old notifications')).toBeTruthy();
    expect(screen.getByText('notifications')).toBeTruthy();
    expect(screen.getByText('30')).toBeTruthy();
  });

  it('shows preview and marks audit logs as excluded', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    const preview = {
      policy_id: 4, policy_name: 'Old notifications', data_category: 'security_events',
      retention_duration_days: 1, total_eligible: 0, can_execute: false,
      excluded: [{ model: 'common.AuditLog', reason: 'Audit logs are protected historical records.' }],
      notes: ['Security events (AuditLog) are retained permanently; no automated deletion applies.'],
    };
    mockGet.mockImplementation((url) => {
      if (url.includes('retention-policies/4/preview/')) return Promise.resolve({ data: preview });
      return Promise.resolve({ data: { results: [POLICY], count: 1, next: null, previous: null } });
    });
    render(<Retention />);
    await screen.findByText('Old notifications');
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await screen.findByText('Preview: Old notifications');
    expect(screen.getByText(/common\.AuditLog/)).toBeTruthy();
    expect(screen.getByText(/protected historical records/)).toBeTruthy();
  });

  it('executes a retention policy', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: { results: [POLICY], count: 1, next: null, previous: null } });
    mockPost.mockResolvedValue({ data: { executed: true, records_affected: 2, records_excluded: 1 } });
    render(<Retention />);
    await screen.findByText('Old notifications');
    fireEvent.click(screen.getByRole('button', { name: 'Execute' }));
    await screen.findByText(/Executed: 2 record\(s\)/);
    expect(mockPost).toHaveBeenCalledWith('/common/retention-policies/4/execute/', {});
  });

  it('creates a retention policy', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: { results: [], count: 0, next: null, previous: null } });
    mockPost.mockResolvedValue({ data: { id: 9, name: 'New policy' } });
    render(<Retention />);
    await screen.findByText('Data retention policies');
    fireEvent.click(screen.getByRole('button', { name: '+ Add policy' }));
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'New policy' } });
    fireEvent.change(screen.getByLabelText(/Retention duration/), { target: { value: '60' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(mockPost).toHaveBeenCalledWith('/common/retention-policies/', {
      name: 'New policy', data_category: 'notifications', retention_duration: 60,
      enabled: true, conditions: {}, description: '', responsible_admin: null,
    });
  });

  it('deletes a retention policy', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: { results: [POLICY], count: 1, next: null, previous: null } });
    mockDelete.mockResolvedValue({});
    window.confirm = vi.fn(() => true);
    render(<Retention />);
    await screen.findByText('Old notifications');
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await screen.findByText(/Data retention policies/);
    expect(mockDelete).toHaveBeenCalledWith('/common/retention-policies/4/');
  });
});
