import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

const { mockAuth } = vi.hoisted(() => ({ mockAuth: vi.fn() }));

vi.mock('./api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock('./auth', () => ({ useAuth: (...args) => mockAuth(...args) }));
vi.mock('./bulk', () => ({
  AssetBulkCreateModal: () => null,
  EmployeeCreateModal: () => null,
  EmployeeImportModal: () => null,
  TicketBulkCreateModal: () => null,
}));

import api from './api';
import { Tickets, Assets } from './pages';

const TICKET_ROWS = [
  { id: 1, title: 'B ticket', status: 'open', priority: 'low',
    category_name: 'C', assignee_email: null,
    created_at: '2024-01-02T00:00:00Z', updated_at: '2024-01-02T00:00:00Z' },
];
const ASSET_ROWS = [
  { id: 1, asset_tag: 'LT-1', name: 'ThinkPad', status: 'available',
    category_name: 'Laptop', serial_number: '', location: '',
    assigned_to_email: null },
];

function staff() {
  mockAuth.mockReturnValue({ canCreateTickets: true, isStaff: true });
}

function employee() {
  mockAuth.mockReturnValue({ canCreateTickets: true, isStaff: false });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  api.get.mockImplementation(async (url) => {
    const u = String(url);
    if (u.startsWith('/tickets/')) {
      return { data: { results: [...TICKET_ROWS], count: 1,
                       next: null, previous: null } };
    }
    if (u.startsWith('/assets/')) {
      return { data: { results: [...ASSET_ROWS], count: 1,
                       next: null, previous: null } };
    }
    return { data: { results: [] } };
  });
});

afterEach(() => cleanup());

describe('Tickets list bulk gating', () => {
  it('shows selection checkboxes and the bulk toolbar to staff', async () => {
    staff();
    render(<Tickets />);
    await screen.findByText('B ticket');
    fireEvent.click(screen.getByLabelText('Select row 1'));
    const toolbar = await screen.findByRole('toolbar', { name: 'Bulk actions' });
    expect(toolbar.textContent).toContain('1 selected');
    expect(screen.getByRole('button', { name: 'Close selected' })).toBeTruthy();
  });

  it('gives employees no checkboxes and no bulk toolbar', async () => {
    employee();
    render(<Tickets />);
    await screen.findByText('B ticket');
    expect(screen.queryByLabelText('Select row 1')).toBeNull();
    expect(screen.queryByRole('toolbar', { name: 'Bulk actions' })).toBeNull();
  });
});

describe('Assets list bulk gating', () => {
  it('gives employees no checkboxes and no bulk toolbar', async () => {
    employee();
    render(<Assets />);
    await screen.findByText('LT-1');
    expect(screen.queryByLabelText('Select row 1')).toBeNull();
    expect(
      screen.queryByRole('toolbar', { name: 'Bulk actions' }),
    ).toBeNull();
  });

  it('shows the bulk toolbar to staff after selecting a row', async () => {
    staff();
    render(<Assets />);
    await screen.findByText('LT-1');
    fireEvent.click(screen.getByLabelText('Select row 1'));
    expect(
      await screen.findByRole('toolbar', { name: 'Bulk actions' }),
    ).toBeTruthy();
  });
});
