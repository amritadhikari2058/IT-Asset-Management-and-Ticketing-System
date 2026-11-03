import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

const { mockGet, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({ useAuth: (...args) => mockAuth(...args) }));

import { TicketDetail } from './tickets';

const TICKET = {
  id: 7,
  title: 'Broken laptop',
  description: 'Does not boot.',
  status: 'open',
  priority: 'high',
  category_name: 'Hardware',
  department_name: 'IT',
  requester_email: 'employee@x',
  assignee_email: null,
  assignee: null,
  asset: null,
  on_behalf_reason: '',
  resolution_notes: '',
  created_at: '2024-01-01T00:00:00Z',
};

const APPROVALS = [
  {
    id: 5,
    ticket: 7,
    ticket_title: 'Broken laptop',
    requested_by: 3,
    requested_by_email: 'employee@x',
    operation: 'change_priority',
    operation_display: 'Change priority',
    reason: 'Vendor confirmed emergency',
    status: 'approved',
    decision_comment: 'Emergency confirmed',
    decided_by_email: 'manager@x',
    decided_at: '2024-01-02T10:00:00Z',
    created_at: '2024-01-01T10:00:00Z',
  },
  {
    id: 6,
    ticket: 7,
    ticket_title: 'Broken laptop',
    requested_by: 3,
    requested_by_email: 'employee@x',
    operation: 'reassign',
    operation_display: 'Reassign',
    reason: 'Needs a specialist',
    status: 'pending',
    decision_comment: '',
    decided_at: null,
    created_at: '2024-01-03T10:00:00Z',
  },
];

const EXECUTIONS = [
  {
    id: 9,
    rule: 1,
    rule_name: 'Auto note',
    ticket: 7,
    ticket_title: 'Broken laptop',
    success: true,
    detail: 'note #1 created',
    created_at: '2024-01-04T10:00:00Z',
  },
];

function staff() {
  mockAuth.mockReturnValue({ isStaff: true, user: { id: 1, role: 'it_support' } });
}

function employee() {
  mockAuth.mockReturnValue({ isStaff: false, user: { id: 3, role: 'employee' } });
}

function route(url) {
  if (url === '/tickets/7/') return { data: TICKET };
  if (url === '/tickets/7/notes/') return { data: [] };
  if (url === '/tickets/histories/') return { data: [] };
  if (url === '/tickets/attachments/') return { data: [] };
  if (url === '/tickets/kb-articles/') return { data: [] };
  if (url === '/workflow/approval-requests/') return { data: { results: APPROVALS } };
  if (url === '/workflow/rule-executions/') return { data: { results: EXECUTIONS } };
  throw new Error(`unexpected GET ${url}`);
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockGet.mockImplementation(async (url) => route(url));
});

afterEach(() => cleanup());

describe('ticket detail workflow integration', () => {
  it('shows related approvals with status, decision history and links', async () => {
    staff();
    render(<TicketDetail id="7" />);
    await screen.findByRole('heading', { name: /Broken laptop/ });

    expect(screen.getByText('Approvals')).toBeTruthy();
    expect(await screen.findByText('Approval #5: Change priority')).toBeTruthy();
    expect(screen.getByText('Approval #6: Reassign')).toBeTruthy();
    expect(screen.getAllByText('Approved').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Pending approval').length).toBeGreaterThan(0);
    expect(screen.getByText('Reason: Vendor confirmed emergency')).toBeTruthy();
    expect(screen.getByText(/Emergency confirmed/)).toBeTruthy();
    expect(screen.getByText('Approval #5: Change priority').closest('a').getAttribute('href'))
      .toBe('#/workflow/approvals/5');
  });

  it('shows recent automation executions to staff', async () => {
    staff();
    render(<TicketDetail id="7" />);
    await screen.findByRole('heading', { name: /Broken laptop/ });

    expect(await screen.findByText('Automation activity')).toBeTruthy();
    expect(screen.getByText(/Auto note/)).toBeTruthy();
    expect(screen.getByText(/note #1 created/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'View run' }).getAttribute('href'))
      .toBe('#/workflow/executions/9');
    expect(mockGet).toHaveBeenCalledWith('/workflow/rule-executions/', {
      params: { ticket: '7', page_size: 10 },
    });
  });

  it('never requests or displays execution history for employees', async () => {
    employee();
    render(<TicketDetail id="7" />);
    await screen.findByRole('heading', { name: /Broken laptop/ });

    // Employees may see approvals on tickets they can see...
    expect(await screen.findByText('Approval #5: Change priority')).toBeTruthy();
    // ...but automation execution history is staff-only and is not requested.
    expect(screen.queryByText('Automation activity')).toBeNull();
    expect(screen.queryByRole('link', { name: 'View run' })).toBeNull();
    expect(
      mockGet.mock.calls.filter(([url]) => String(url).startsWith('/workflow/rule-executions/')),
    ).toHaveLength(0);
  });

  it('shows empty approval and automation states', async () => {
    staff();
    mockGet.mockImplementation(async (url) => {
      if (url === '/workflow/approval-requests/') return { data: { results: [] } };
      if (url === '/workflow/rule-executions/') return { data: { results: [] } };
      return route(url);
    });
    render(<TicketDetail id="7" />);
    await screen.findByRole('heading', { name: /Broken laptop/ });

    expect(await screen.findByText('No approval requests for this ticket.')).toBeTruthy();
    expect(await screen.findByText('No automation rules have run for this ticket.')).toBeTruthy();
  });
});
