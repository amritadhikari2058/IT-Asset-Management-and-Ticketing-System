import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { NotificationSettings } from './settings';

function user(over = {}) {
  return { id: 7, employee_id: 'E7', email: 'e@x', role: 'employee', ...over };
}

function ctx(over = {}) {
  return { user: user(), ...over };
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
});

afterEach(() => cleanup());

describe('Notification settings page', () => {
  it('loads preferences and renders toggles', async () => {
    mockAuth.mockReturnValue(ctx());
    mockGet.mockResolvedValueOnce({
      data: {
        results: [{
          id: 3, user: 7, email_enabled: true,
          categories: {
            ticket_assignment: true, ticket_status_change: false, ticket_reply: true,
            sla_escalation: true, maintenance_reminder: true, asset_assignment: true, system_alert: true,
          },
          email_categories: [
            { key: 'ticket_assignment', label: 'Ticket assigned to me', enabled: true },
            { key: 'ticket_status_change', label: 'Ticket status changed', enabled: false },
            { key: 'ticket_reply', label: 'New reply or note on my ticket', enabled: true },
            { key: 'sla_escalation', label: 'SLA escalation / breach', enabled: true },
            { key: 'maintenance_reminder', label: 'Maintenance reminder', enabled: true },
            { key: 'asset_assignment', label: 'Asset assigned or returned', enabled: true },
            { key: 'system_alert', label: 'System alerts', enabled: true },
          ],
        }],
      },
    });
    render(<NotificationSettings />);
    await screen.findByText('Notification settings');
    expect(mockGet).toHaveBeenCalledWith('/common/notification-preferences/');
    expect(screen.getByLabelText('Enable email notifications').checked).toBe(true);
    expect(screen.getByLabelText(/Email notifications for Ticket status changed/).checked).toBe(false);
  });

  it('uses sensible defaults when no preference record exists', async () => {
    mockAuth.mockReturnValue(ctx());
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<NotificationSettings />);
    await screen.findByText('Notification settings');
    expect(screen.getByLabelText('Enable email notifications').checked).toBe(true);
    // All category toggles checked by default.
    expect(screen.getByLabelText(/Email notifications for Ticket assigned to me/).checked).toBe(true);
  });

  it('saves via PATCH when a preference record exists', async () => {
    mockAuth.mockReturnValue(ctx());
    mockGet.mockResolvedValueOnce({
      data: { results: [{ id: 3, user: 7, email_enabled: true, categories: {} }] },
    });
    mockPatch.mockResolvedValueOnce({ data: { id: 3 } });
    render(<NotificationSettings />);
    await screen.findByText('Notification settings');
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByText('Notification preferences saved.');
    expect(mockPatch).toHaveBeenCalledWith('/common/notification-preferences/3/', {
      email_enabled: true, categories: expect.any(Object),
    });
  });

  it('saves via POST when no preference record exists', async () => {
    mockAuth.mockReturnValue(ctx());
    mockGet.mockResolvedValueOnce({ data: [] });
    mockPost.mockResolvedValueOnce({ data: { id: 9 } });
    render(<NotificationSettings />);
    await screen.findByText('Notification settings');
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByText('Notification preferences saved.');
    expect(mockPost).toHaveBeenCalledWith('/common/notification-preferences/', {
      email_enabled: true, categories: expect.any(Object),
    });
  });

  it('keeps unsaved edits and shows error when save fails', async () => {
    mockAuth.mockReturnValue(ctx());
    mockGet.mockResolvedValueOnce({
      data: { results: [{ id: 3, user: 7, email_enabled: true, categories: {} }] },
    });
    mockPatch.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'Invalid category key.' } },
    });
    render(<NotificationSettings />);
    await screen.findByText('Notification settings');
    // Flip the master switch off.
    fireEvent.click(screen.getByLabelText('Enable email notifications'));
    expect(screen.getByLabelText('Enable email notifications').checked).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByText('Invalid category key.');
    // The unsaved edit (off) is still in place.
    expect(screen.getByLabelText('Enable email notifications').checked).toBe(false);
  });

  it('shows loading state while fetching', () => {
    mockAuth.mockReturnValue(ctx());
    mockGet.mockReturnValue(new Promise(() => { /* never resolves */ }));
    render(<NotificationSettings />);
    expect(screen.getByText(/Loading notification preferences/)).toBeTruthy();
  });
});
