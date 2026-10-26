import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPatch, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPatch: vi.fn(),
  mockPost: vi.fn(),
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

import { TicketForm, TicketDetail } from './tickets';

const OPEN_TICKET = {
  id: 7, title: 'Printer down', description: 'No power.', priority: 'high',
  category: 2, department: 1, on_behalf_reason: '', asset: null,
  assignee: null, status: 'open', resolution_notes: '',
};
const RESOLVED_TICKET = { ...OPEN_TICKET, status: 'resolved' };

const TICKET_DETAIL = {
  ...OPEN_TICKET, category_name: 'Hardware', department_name: 'IT',
  requester_email: 'e@x', assignee_email: null,
  created_at: '2024-01-01T00:00:00Z',
};

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

function formRoute(url) {
  if (url === '/tickets/7/') return { data: OPEN_TICKET };
  if (url === '/tickets/categories/') return { data: { results: [] } };
  if (url === '/accounts/departments/') return { data: { results: [] } };
  if (url === '/assets/') return { data: { results: [] } };
  if (url === '/accounts/users/') return { data: { results: [] } };
  throw new Error(`unexpected GET ${url}`);
}

function detailRoute(url) {
  if (url === '/tickets/7/') return { data: TICKET_DETAIL };
  if (url === '/tickets/7/notes/') return { data: [] };
  if (url === '/tickets/histories/') return { data: [{ id: 1, action: 'created', note: '' }] };
  if (url === '/tickets/attachments/') return { data: [] };
  throw new Error(`unexpected GET ${url}`);
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '';
  mockGet.mockImplementation(async (url) => formRoute(url));
  mockPatch.mockResolvedValue({ data: { ...OPEN_TICKET, id: 7 } });
  mockPost.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('TicketForm staff-only fields on edit', () => {
  it('disables priority and category for employees and omits them from the payload', async () => {
    employee();
    render(<TicketForm id="7" />);
    await screen.findByText('Edit ticket #7');
    // The category select stays disabled while its options load.
    await screen.findByText('Select a category…');
    const priority = screen.getByLabelText(/priority/i);
    const category = screen.getByLabelText(/^category/i);
    expect(priority.disabled).toBe(true);
    expect(category.disabled).toBe(true);
    expect(screen.getByText(/Only IT staff can change priority/i)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    const payload = mockPatch.mock.calls[0][1];
    expect(payload).not.toHaveProperty('priority');
    expect(payload).not.toHaveProperty('category');
    expect(payload).not.toHaveProperty('status');
    expect(payload).not.toHaveProperty('assignee');
    expect(payload.title).toBe('Printer down');
  });

  it('keeps priority and category editable for staff and sends them', async () => {
    staff();
    render(<TicketForm id="7" />);
    await screen.findByText('Edit ticket #7');
    await screen.findByText('Select a category…');
    expect(screen.getByLabelText(/priority/i).disabled).toBe(false);
    expect(screen.getByLabelText(/^category/i).disabled).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    const payload = mockPatch.mock.calls[0][1];
    expect(payload.priority).toBe('high');
    expect(payload.status).toBe('open');
    expect(payload.assignee).toBeNull();
  });

  it('lets employees choose priority at creation', async () => {
    employee();
    mockPost.mockResolvedValue({ data: { ...OPEN_TICKET, id: 12 } });
    render(<TicketForm />);
    await screen.findByText('New ticket');
    const priority = screen.getByLabelText(/priority/i);
    expect(priority.disabled).toBe(false);
    fireEvent.change(priority, { target: { value: 'critical' } });
    fireEvent.change(screen.getByPlaceholderText(/Brief summary/i), {
      target: { value: 'Mailbox full' },
    });
    fireEvent.change(screen.getByPlaceholderText(/Steps to reproduce/i), {
      target: { value: 'Cannot send.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create ticket' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    expect(mockPost.mock.calls[0][1].priority).toBe('critical');
  });
});

describe('TicketForm status dropdown', () => {
  it('only offers the current status and its valid successors', async () => {
    staff();
    mockGet.mockImplementation(async (url) => {
      if (url === '/tickets/7/') return { data: RESOLVED_TICKET };
      return formRoute(url);
    });
    render(<TicketForm id="7" />);
    await screen.findByText('Edit ticket #7');
    const options = [...screen.getByLabelText(/^status/i).querySelectorAll('option')].map(
      (o) => o.value,
    );
    // Mirrors Ticket.VALID_TRANSITIONS.resolved
    expect(options.sort()).toEqual(['closed', 'reopened', 'resolved']);
    expect(options).not.toContain('in_progress');
    expect(options).not.toContain('archived');
  });

  it('offers every move from an open ticket', async () => {
    staff();
    render(<TicketForm id="7" />);
    await screen.findByText('Edit ticket #7');
    const options = [...screen.getByLabelText(/^status/i).querySelectorAll('option')].map(
      (o) => o.value,
    );
    expect(options.sort()).toEqual(['archived', 'closed', 'in_progress', 'open', 'resolved']);
  });
});

describe('TicketDetail history visibility', () => {
  it('hides History from employees and never requests it', async () => {
    employee();
    mockGet.mockImplementation(async (url) => detailRoute(url));
    render(<TicketDetail id="7" />);
    await screen.findByRole('heading', { name: /Printer down/ });
    expect(screen.queryByText('History')).toBeNull();
    expect(
      mockGet.mock.calls.filter(([url]) => url === '/tickets/histories/'),
    ).toHaveLength(0);
  });

  it('shows History to staff', async () => {
    staff();
    mockGet.mockImplementation(async (url) => detailRoute(url));
    render(<TicketDetail id="7" />);
    await screen.findByRole('heading', { name: /Printer down/ });
    await screen.findByText('History');
    expect(mockGet).toHaveBeenCalledWith(
      '/tickets/histories/', { params: { ticket: '7' } },
    );
  });
});
