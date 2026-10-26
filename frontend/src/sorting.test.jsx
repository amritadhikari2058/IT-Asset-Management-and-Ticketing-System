import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

vi.mock('./api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock('./auth', () => ({
  useAuth: () => ({ canCreateTickets: true, isStaff: true }),
}));
vi.mock('./bulk', () => ({
  AssetBulkCreateModal: () => null,
  EmployeeCreateModal: () => null,
  EmployeeImportModal: () => null,
  TicketBulkCreateModal: () => null,
}));

import api from './api';
import { Tickets } from './pages';

const ROWS = [
  { id: 1, title: 'B ticket', status: 'open', priority: 'low', category_name: 'C', assignee_email: null, created_at: '2024-01-02T00:00:00Z', updated_at: '2024-01-02T00:00:00Z' },
  { id: 2, title: 'A ticket', status: 'closed', priority: 'critical', category_name: 'C', assignee_email: null, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
];

beforeEach(() => {
  cleanup();
  api.get.mockImplementation(async (url) => {
    if (String(url).startsWith('/tickets/')) {
      return { data: { results: [...ROWS], count: 2, next: null, previous: null } };
    }
    return { data: { results: [] } };
  });
});
afterEach(() => cleanup());

describe('Tickets list sorting', () => {
  it('sorts ascending then descending then clears', async () => {
    render(<Tickets />);
    await screen.findByText('B ticket');
    const calls = api.get.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: 'Sort by Priority' }));
    expect(api.get).toHaveBeenLastCalledWith('/tickets/?ordering=priority');
    expect(api.get.mock.calls.length).toBe(calls + 1);

    // Header clicks reload the list; wait for rows to come back first.
    fireEvent.click(await screen.findByRole('button', { name: 'Sort by Priority' }));
    expect(api.get).toHaveBeenLastCalledWith('/tickets/?ordering=-priority');

    fireEvent.click(await screen.findByRole('button', { name: 'Sort by Priority' }));
    expect(api.get).toHaveBeenLastCalledWith('/tickets/');
  });

  it('marks the active sort direction for assistive tech', async () => {
    render(<Tickets />);
    await screen.findByText('B ticket');
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Created' }));
    const th = (await screen.findByRole('button', { name: 'Sort by Created' })).closest('th');
    expect(th.getAttribute('aria-sort')).toBe('ascending');
  });

  it('keeps filters when sorting', async () => {
    render(<Tickets />);
    await screen.findByText('B ticket');
    fireEvent.change(screen.getByLabelText('Filter by status'), {
      target: { value: 'open' },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Sort by Created' }));
    expect(api.get).toHaveBeenLastCalledWith('/tickets/?status=open&ordering=created_at');
  });
});
