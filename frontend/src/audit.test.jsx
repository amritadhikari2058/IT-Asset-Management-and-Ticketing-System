import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: { get: (...args) => mockGet(...args) },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { AuditLogPage } from './audit';

const ROWS = [
  {
    id: 1, actor: 9, actor_email: 'a@x', action: 'create',
    entity_type: 'tickets.Ticket', object_id: '3', object_repr: '#3 Printer',
    timestamp: '2024-01-01T00:00:00Z', reason: '', details: {},
  },
];

function admin() {
  mockAuth.mockReturnValue({ isAdmin: true });
}

function nonAdmin() {
  mockAuth.mockReturnValue({ isAdmin: false });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockGet.mockResolvedValue({ data: { results: ROWS, count: 1, next: null, previous: null } });
});

afterEach(() => cleanup());

describe('AuditLogPage', () => {
  it('hides the page from non-admins without calling the API', () => {
    nonAdmin();
    render(<AuditLogPage />);
    expect(screen.getByText('System administrators only.')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('lists entries for admins', async () => {
    admin();
    render(<AuditLogPage />);
    expect(await screen.findByText('#3 Printer')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/common/audit-logs/');
    expect(screen.getByText('a@x')).toBeTruthy();
  });

  it('applies action and date filters to the query', async () => {
    admin();
    render(<AuditLogPage />);
    await screen.findByText('#3 Printer');
    fireEvent.change(screen.getByLabelText('Filter by action'), {
      target: { value: 'hard_delete' },
    });
    await waitFor(() => {
      expect(mockGet).toHaveBeenLastCalledWith(
        '/common/audit-logs/?action=hard_delete&page_size=20',
      );
    });
    fireEvent.change(screen.getByLabelText('Start date'), {
      target: { value: '2024-01-01' },
    });
    await waitFor(() => {
      expect(mockGet).toHaveBeenLastCalledWith(
        '/common/audit-logs/?action=hard_delete&date_from=2024-01-01&page_size=20',
      );
    });
  });

  it('rejects an end date before the start date without calling the API', async () => {
    admin();
    render(<AuditLogPage />);
    await screen.findByText('#3 Printer');
    const calls = mockGet.mock.calls.length;
    fireEvent.change(screen.getByLabelText('Start date'), {
      target: { value: '2024-02-01' },
    });
    fireEvent.change(screen.getByLabelText('End date'), {
      target: { value: '2024-01-01' },
    });
    expect(
      await screen.findByText('End date cannot be earlier than start date.'),
    ).toBeTruthy();
    // Only the start-date change fired; the invalid pair never did.
    expect(mockGet.mock.calls.length).toBe(calls + 1);
  });

  it('shows backend validation errors', async () => {
    admin();
    mockGet.mockRejectedValueOnce({
      response: { status: 400, data: { action: ['Unknown action.'] } },
    });
    render(<AuditLogPage />);
    expect(await screen.findByText('Unknown action.')).toBeTruthy();
  });
});
