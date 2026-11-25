import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react';

const { mockGet, mockPatch, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPatch: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: () => {},
    patch: (...args) => mockPatch(...args),
    delete: vi.fn(),
  },
}));

vi.mock('../../auth', () => ({ useAuth: (...args) => mockAuth(...args) }));

vi.mock('../../pages/bulk/Bulk', () => ({
  AssetBulkCreateModal: () => null,
  EmployeeCreateModal: () => null,
  EmployeeImportModal: () => null,
  TicketBulkCreateModal: () => null,
}));

import { Tickets } from '../../pages';
import { TicketForm, TicketDetail } from '../../pages/tickets/Tickets';

const LIST_PAGE = {
  results: [
    { id: 1, title: 'Printer down', status: 'open', priority: 'high',
      category_name: 'Hardware', assignee_email: 'a@x', requester_email: 'r@x',
      department_name: 'IT', asset_tag: 'LT-1',
      sla_due_at: '2024-02-01T00:00:00Z', is_overdue: false,
      created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z',
      description: 'No power.', on_behalf_reason: '', resolution_notes: '',
      resolved_at: null, closed_at: null },
    { id: 2, title: 'Mailbox full', status: 'in_progress', priority: 'medium',
      category_name: 'Software', assignee_email: null, requester_email: 'r@x',
      department_name: 'IT', asset_tag: null,
      sla_due_at: null, is_overdue: false,
      created_at: '2024-01-02T00:00:00Z', updated_at: '2024-01-02T00:00:00Z',
      description: 'Cannot send.', on_behalf_reason: '', resolution_notes: '',
      resolved_at: null, closed_at: null },
  ],
  count: 2, next: null, previous: null,
};

const DETAIL_TICKET = {
  id: 7, title: 'Printer down', description: 'No power.', priority: 'high',
  category: 2, category_name: 'Hardware', department: 1, department_name: 'IT',
  on_behalf_reason: '', asset: 3, asset_tag: 'LT-3',
  assignee: 5, assignee_email: 'tech@x', requester_email: 'r@x',
  status: 'open', resolution_notes: '',
  sla_due_at: '2024-02-01T00:00:00Z', sla_breached: false, is_overdue: false,
  created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z',
  resolved_at: null, closed_at: null,
};

function staff() {
  mockAuth.mockReturnValue({
    isStaff: true, canCreateTickets: true,
    user: { role: 'it_support', home_department: 1, email: 'tech@x' },
  });
}

function employee() {
  mockAuth.mockReturnValue({
    isStaff: false, canCreateTickets: true,
    user: { role: 'employee', home_department: 1, email: 'r@x' },
  });
}

// Shared route handler for TicketForm/TicketDetail child-component API calls.
function ticketRoutes(url) {
  const u = String(url);
  if (u === '/tickets/') return { data: LIST_PAGE };
  if (u === '/tickets/7/') return { data: DETAIL_TICKET };
  if (u === '/tickets/categories/') return { data: { results: [] } };
  if (u === '/accounts/departments/') return { data: { results: [] } };
  if (u === '/assets/') return { data: { results: [] } };
  if (u === '/accounts/users/') return { data: { results: [] } };
  if (u === '/tickets/7/notes/') return { data: [] };
  if (u === '/tickets/attachments/') return { data: [] };
  if (u === '/tickets/histories/') return { data: [] };
  if (u === '/tickets/kb-articles/') return { data: [] };
  if (u === '/workflow/approval-requests/') return { data: [] };
  if (u === '/workflow/rule-executions/') return { data: [] };
  if (u === '/tickets/7/watchers/') return { data: [] };
  return { data: {} };
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '';
});

afterEach(() => cleanup());

describe('Ticket list — successful loading', () => {
  it('loads tickets from the backend and renders rows', async () => {
    staff();
    mockGet.mockImplementation(async (url) => {
      if (url === '/tickets/') return { data: LIST_PAGE };
      return ticketRoutes(url);
    });
    render(<Tickets />);
    await screen.findByText('Printer down');
    await screen.findByText('Mailbox full');
    expect(mockGet).toHaveBeenCalledWith('/tickets/');
  });

  it('renders count', async () => {
    staff();
    mockGet.mockImplementation(async (url) => {
      if (url === '/tickets/') return { data: LIST_PAGE };
      return ticketRoutes(url);
    });
    render(<Tickets />);
    await screen.findByText('Printer down');
    expect(screen.getByText('2 in scope')).toBeTruthy();
  });
});

describe('Ticket list — failed loading', () => {
  it('shows error state and retry when backend fails', async () => {
    staff();
    mockGet.mockImplementation(async () => {
      throw new Error('boom');
    });
    render(<Tickets />);
    await waitFor(() => expect(screen.getByText(/Could not load tickets./)).toBeTruthy());
    expect(screen.getByRole('button', { name: /Retry/ })).toBeTruthy();
  });
});

describe('Ticket list — pagination and filtering', () => {
  it('paginates using next URL', async () => {
    staff();
    const page2 = {
      results: [{ id: 3, title: 'Third ticket', status: 'open', priority: 'low',
        category_name: 'C', assignee_email: null, requester_email: 'r@x',
        department_name: 'IT', asset_tag: null, sla_due_at: null,
        is_overdue: false, created_at: '2024-01-03T00:00:00Z',
        updated_at: '2024-01-03T00:00:00Z', description: '', on_behalf_reason: '',
        resolution_notes: '', resolved_at: null, closed_at: null }],
      count: 3, next: null, previous: '/tickets/?page=1',
    };
    mockGet.mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/tickets/') return { data: { ...LIST_PAGE, next: '/tickets/?page=2' } };
      if (u === '/tickets/?page=2') return { data: page2 };
      return ticketRoutes(url);
    });
    render(<Tickets />);
    await screen.findByText('Printer down');
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    await waitFor(() => expect(screen.getByText('Third ticket')).toBeTruthy());
  });

  it('applies search filter', async () => {
    staff();
    mockGet.mockImplementation(async (url) => {
      const u = String(url);
      if (u.includes('q=Printer')) {
        return { data: { ...LIST_PAGE, results: [LIST_PAGE.results[0]], count: 1 } };
      }
      return ticketRoutes(url);
    });
    render(<Tickets />);
    await screen.findByText('Printer down');
    const search = screen.getByLabelText(/Search tickets/);
    fireEvent.change(search, { target: { value: 'Printer' } });
    await waitFor(() => expect(mockGet.mock.calls.some(
      ([u]) => String(u).includes('q=Printer'))).toBe(true));
  });

  it('applies status filter and shows empty state', async () => {
    staff();
    mockGet.mockImplementation(async (url) => {
      const u = String(url);
      if (u.includes('status=closed')) {
        return { data: { ...LIST_PAGE, results: [], count: 0 } };
      }
      return ticketRoutes(url);
    });
    render(<Tickets />);
    await screen.findByText('Printer down');
    fireEvent.change(screen.getByLabelText(/Filter by status/), { target: { value: 'closed' } });
    await waitFor(() => expect(screen.getByText('No tickets match.')).toBeTruthy());
  });
});

describe('Ticket detail — successful loading', () => {
  it('loads and displays ticket fields including SLA info', async () => {
    staff();
    mockGet.mockImplementation(async (url) => ticketRoutes(url));
    render(<TicketDetail id="7" />);
    await screen.findByRole('heading', { name: /#7 Printer down/ });
    expect(screen.getByText('tech@x')).toBeTruthy();
    expect(screen.getByText('Hardware')).toBeTruthy();
    expect(screen.getByText('High')).toBeTruthy();
    expect(screen.getByText('Open')).toBeTruthy();
  });

  it('shows requester and assignee', async () => {
    staff();
    mockGet.mockImplementation(async (url) => ticketRoutes(url));
    render(<TicketDetail id="7" />);
    await screen.findByRole('heading', { name: /#7 Printer down/ });
    expect(screen.getByText('r@x')).toBeTruthy();
    expect(screen.getByText('tech@x')).toBeTruthy();
  });
});

describe('Ticket detail — missing / unauthorized', () => {
  it('shows error when ticket is missing', async () => {
    staff();
    mockGet.mockImplementation(async (url) => {
      if (url === '/tickets/999/') {
        throw { response: { status: 404, data: { detail: 'Not found.' } } };
      }
      return ticketRoutes(url);
    });
    render(<TicketDetail id="999" />);
    await waitFor(() => expect(screen.getByText(/Not found/)).toBeTruthy());
    expect(screen.getByRole('link', { name: /← Back to tickets/ })).toBeTruthy();
  });

  it('shows error when unauthorized', async () => {
    employee();
    mockGet.mockImplementation(async (url) => {
      if (url === '/tickets/7/') {
        throw { response: { status: 403, data: { detail: 'Forbidden.' } } };
      }
      return ticketRoutes(url);
    });
    render(<TicketDetail id="7" />);
    await waitFor(() => expect(screen.getByText(/Forbidden/)).toBeTruthy());
  });
});

describe('Ticket update — successful', () => {
  it('PATCHes supported fields', async () => {
    staff();
    mockGet.mockImplementation(async (url) => ticketRoutes(url));
    mockPatch.mockResolvedValue({
      data: { ...DETAIL_TICKET, status: 'resolved', priority: 'critical' },
    });
    render(<TicketForm id="7" />);
    await screen.findByText('Edit ticket #7');
    await screen.findByText('Select a category…');
    fireEvent.change(screen.getByLabelText(/^status/i), { target: { value: 'resolved' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    const payload = mockPatch.mock.calls[0][1];
    expect(payload.status).toBe('resolved');
    expect(mockPatch.mock.calls[0][0]).toBe('/tickets/7/');
  });

  it('prevents duplicate submissions while saving', async () => {
    staff();
    mockGet.mockImplementation(async (url) => ticketRoutes(url));
    let resolvePatch;
    mockPatch.mockImplementation(() => new Promise((r) => { resolvePatch = r; }));
    render(<TicketForm id="7" />);
    await screen.findByText('Edit ticket #7');
    await screen.findByText('Select a category…');
    const submit = screen.getByRole('button', { name: 'Save changes' });
    fireEvent.click(submit);
    // Button is disabled while the first request is in flight.
    await waitFor(() => expect(submit.disabled).toBe(true));
    // A second click while submitting must not trigger another PATCH.
    fireEvent.click(submit);
    resolvePatch({ data: DETAIL_TICKET });
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
  });
});

describe('Ticket update — failed', () => {
  it('shows meaningful error from backend validation', async () => {
    staff();
    mockGet.mockImplementation(async (url) => ticketRoutes(url));
    mockPatch.mockRejectedValueOnce({
      response: { status: 400, data: { status: ['Invalid transition.'] } },
    });
    render(<TicketForm id="7" />);
    await screen.findByText('Edit ticket #7');
    await screen.findByText('Select a category…');
    fireEvent.change(screen.getByLabelText(/^status/i), { target: { value: 'closed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(screen.getByText(/Invalid transition./)).toBeTruthy());
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeTruthy();
  });

  it('handles server error on update', async () => {
    staff();
    mockGet.mockImplementation(async (url) => ticketRoutes(url));
    mockPatch.mockRejectedValueOnce({
      response: { status: 500, data: { detail: 'Server error.' } },
    });
    render(<TicketForm id="7" />);
    await screen.findByText('Edit ticket #7');
    await screen.findByText('Select a category…');
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(screen.getByText(/Server error/)).toBeTruthy());
  });
});

describe('Ticket update — state refresh after mutation', () => {
  it('navigates to detail after successful update', async () => {
    staff();
    mockGet.mockImplementation(async (url) => ticketRoutes(url));
    mockPatch.mockResolvedValue({
      data: { ...DETAIL_TICKET, status: 'resolved' },
    });
    render(<TicketForm id="7" />);
    await screen.findByText('Edit ticket #7');
    await screen.findByText('Select a category…');
    fireEvent.change(screen.getByLabelText(/^status/i), { target: { value: 'resolved' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(window.location.hash).toBe('#/tickets/7'));
  });
});

describe('Ticket form request lifecycle', () => {
  it('does not let an older knowledge-base search replace newer suggestions', async () => {
    employee();
    const pendingSearches = [];
    mockGet.mockImplementation((url) => {
      if (url === '/assets/knowledge-base/') {
        return new Promise((resolve) => pendingSearches.push(resolve));
      }
      return Promise.resolve(ticketRoutes(url));
    });

    render(<TicketForm />);
    const subject = () => screen.getByPlaceholderText('Brief summary of the issue');
    fireEvent.change(subject(), { target: { value: 'Printer issue' } });
    await waitFor(() => expect(pendingSearches).toHaveLength(1));
    fireEvent.change(subject(), { target: { value: 'Monitor issue' } });
    await waitFor(() => expect(pendingSearches).toHaveLength(2));

    await act(async () => pendingSearches[1]({ data: { results: [{ id: 2, title: 'Monitor help' }] } }));
    expect(await screen.findByText('Monitor help')).toBeTruthy();
    await act(async () => pendingSearches[0]({ data: { results: [{ id: 1, title: 'Printer help' }] } }));

    expect(screen.getByText('Monitor help')).toBeTruthy();
    expect(screen.queryByText('Printer help')).toBeNull();
  });

  it('ignores a ticket detail response after the form switches records', async () => {
    staff();
    let resolveFirstTicket;
    mockGet.mockImplementation((url) => {
      if (url === '/tickets/7/') return new Promise((resolve) => { resolveFirstTicket = resolve; });
      if (url === '/tickets/8/') {
        return Promise.resolve({ data: { ...DETAIL_TICKET, id: 8, title: 'Ticket eight' } });
      }
      return Promise.resolve(ticketRoutes(url));
    });

    const view = render(<TicketForm id="7" />);
    view.rerender(<TicketForm id="8" />);
    const subject = await screen.findByPlaceholderText('Brief summary of the issue');
    await waitFor(() => expect(subject.value).toBe('Ticket eight'));
    await act(async () => resolveFirstTicket({ data: { ...DETAIL_TICKET, title: 'Stale ticket seven' } }));

    expect(subject.value).toBe('Ticket eight');
  });
});
