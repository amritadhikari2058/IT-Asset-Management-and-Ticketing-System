import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

const { mockGet, mockPatch, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPatch: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: vi.fn(),
    patch: (...args) => mockPatch(...args),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { TicketForm } from './tickets';

const OPEN_TICKET = {
  id: 7, title: 'Printer down', description: 'No power.', priority: 'high',
  category: 2, department: 1, on_behalf_reason: '', asset: null,
  assignee: null, status: 'open', resolution_notes: '',
};
const RESOLVED_TICKET = { ...OPEN_TICKET, status: 'resolved', resolution_notes: 'Replaced toner.' };

function staff() {
  mockAuth.mockReturnValue({
    isStaff: true, canCreateTickets: true,
    user: { role: 'it_support', home_department: 1 },
  });
}

function employee() {
  mockAuth.mockReturnValue({
    isStaff: false, canCreateTickets: true,
    user: { role: 'employee', home_department: 1 },
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockGet.mockImplementation(async (url) => {
    if (url === '/tickets/7/') return { data: OPEN_TICKET };
    if (url === '/tickets/categories/') return { data: { results: [] } };
    if (url === '/accounts/departments/') return { data: { results: [] } };
    if (url === '/assets/') return { data: { results: [] } };
    if (url === '/accounts/users/') return { data: { results: [] } };
    throw new Error(`unexpected GET ${url}`);
  });
  mockPatch.mockResolvedValue({ data: { ...OPEN_TICKET, id: 7 } });
});

afterEach(() => cleanup());

describe('TicketForm resolution notes', () => {
  it('shows the textarea to staff on a resolved ticket', async () => {
    staff();
    mockGet.mockImplementation(async (url) => {
      if (url === '/tickets/7/') return { data: RESOLVED_TICKET };
      return { data: { results: [] } };
    });
    render(<TicketForm id="7" />);
    const area = await screen.findByLabelText(/resolution notes/i);
    expect(area.value).toBe('Replaced toner.');
  });

  it('submits resolution notes with staff edits', async () => {
    staff();
    mockGet.mockImplementation(async (url) => {
      if (url === '/tickets/7/') return { data: RESOLVED_TICKET };
      return { data: { results: [] } };
    });
    render(<TicketForm id="7" />);
    const area = await screen.findByLabelText(/resolution notes/i);
    fireEvent.change(area, { target: { value: 'New ribbon installed.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByText('Ticket updated.');
    const [, payload] = mockPatch.mock.calls[0];
    expect(payload.resolution_notes).toBe('New ribbon installed.');
  });

  it('hides the textarea from employees entirely', async () => {
    employee();
    render(<TicketForm id="7" />);
    await screen.findByText('Edit ticket #7');
    expect(screen.queryByLabelText(/resolution notes/i)).toBeNull();
  });
});
