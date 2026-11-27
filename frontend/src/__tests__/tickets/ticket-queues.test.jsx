import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPut, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPut: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    put: (...args) => mockPut(...args),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: () => mockAuth(),
}));

import { TicketQueuesPage } from '../../pages/tickets/TicketQueuesPage';

const queue = {
  id: 5,
  name: 'IT Support',
  code: 'IT-SUPPORT',
  description: 'General IT support queue',
  department: null,
  department_name: null,
  default_category: null,
  default_priority: 'medium',
  is_active: true,
  email_address: 'support@example.com',
  assignment_strategy: 'manual',
  allow_self_claim: true,
  manager: null,
  manager_email: null,
  ticket_count: 8,
};

function setupApi(queues = []) {
  mockGet.mockImplementation(async (url) => {
    if (url === '/tickets/queues/') {
      return { data: { results: queues } };
    }

    if (
      url.startsWith('/accounts/departments/') ||
      url.startsWith('/accounts/users/') ||
      url.startsWith('/tickets/categories/')
    ) {
      return { data: { results: [] } };
    }

    return { data: { results: [] } };
  });
}

function setupMembershipApi({ users = [], memberships = [] } = {}) {
  const metrics = {
    queue: 5,
    queue_name: 'IT Support',
    total_active: 0,
    unassigned: 0,
    assigned: 0,
    in_progress: 0,
    waiting_requester: 0,
    waiting_third_party: 0,
    overdue: 0,
    sla_breached: 0,
    urgent: 0,
    members: memberships.length,
    oldest_ticket_age_days: null,
    workload_by_member: [],
  };

  mockGet.mockImplementation(async (url) => {
    if (url === '/tickets/queues/') {
      return { data: { results: [queue] } };
    }
    if (url === '/tickets/queues/5/tickets/') {
      return { data: [] };
    }
    if (url === '/tickets/queues/5/metrics/') {
      return { data: metrics };
    }
    if (url === '/tickets/queue-memberships/?queue=5') {
      return { data: { results: memberships } };
    }
    if (url.startsWith('/accounts/users/')) {
      return { data: { results: users } };
    }
    if (
      url.startsWith('/accounts/departments/') ||
      url.startsWith('/tickets/categories/')
    ) {
      return { data: { results: [] } };
    }
    return { data: { results: [] } };
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();

  mockAuth.mockReturnValue({
    isStaff: true,
    isManagerOrAdmin: true,
    user: { id: 1, role: 'it_manager' },
  });

  setupApi();
  mockPost.mockResolvedValue({ data: { id: 10 } });
  mockPut.mockResolvedValue({ data: queue });
});

afterEach(() => cleanup());

describe('TicketQueuesPage', () => {
  it('loads and displays queue details from the backend', async () => {
    setupApi([queue]);

    render(<TicketQueuesPage />);

    expect(await screen.findByText('IT Support')).toBeTruthy();
    expect(screen.getByText('IT-SUPPORT')).toBeTruthy();
    expect(screen.getByText('8')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/tickets/queues/');
  });

  it('creates a queue using the backend-supported fields', async () => {
    render(<TicketQueuesPage />);

    const createButtons = await screen.findAllByRole('button', {
      name: 'Create queue',
    });
    fireEvent.click(createButtons[0]);

    fireEvent.change(screen.getByLabelText('Queue name'), {
      target: { value: 'Network Support' },
    });
    fireEvent.change(screen.getByLabelText('Queue code'), {
      target: { value: 'network-support' },
    });

    const submitButton = screen.getByRole('dialog').querySelector('button[type="submit"]');
    if (!submitButton) throw new Error('Queue form submit button was not found.');
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/tickets/queues/', {
        name: 'Network Support',
        code: 'NETWORK-SUPPORT',
        description: '',
        department: null,
        default_category: null,
        default_priority: '',
        email_address: '',
        assignment_strategy: 'manual',
        allow_self_claim: true,
        manager: null,
      });
    });
  });

  it('updates an existing queue using its ID', async () => {
    setupApi([queue]);

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));

    fireEvent.change(screen.getByLabelText('Queue name'), {
      target: { value: 'IT Operations' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledTimes(1);
    });

    const [url, payload] = mockPut.mock.calls[0];

    expect(url).toBe('/tickets/queues/5/');
    expect(payload).toEqual({
      name: 'IT Operations',
      code: 'IT-SUPPORT',
      description: 'General IT support queue',
      department: null,
      default_category: null,
      default_priority: 'medium',
      email_address: 'support@example.com',
      assignment_strategy: 'manual',
      allow_self_claim: true,
      manager: null,
    });
  });

  it('deactivates a queue only after confirmation', async () => {
    setupApi([queue]);

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Deactivate' }));

    expect(await screen.findByText(/will no longer be available as an active queue/i))
      .toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Deactivate queue' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/tickets/queues/5/deactivate/');
    });
  });

  it('allows IT Support to view queues but hides configuration actions', async () => {
    setupApi([queue]);

    mockAuth.mockReturnValue({
      isStaff: true,
      isManagerOrAdmin: false,
      user: { id: 2, role: 'it_support' },
    });

    render(<TicketQueuesPage />);

    expect(await screen.findByText('IT Support')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create queue' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Deactivate' })).toBeNull();
  });

  it('blocks employees from accessing queue management', () => {
    mockAuth.mockReturnValue({
      isStaff: false,
      isManagerOrAdmin: false,
      isEmployee: true,
      user: { id: 3, role: 'employee' },
    });

    render(<TicketQueuesPage />);

    expect(screen.getByText(/available to IT staff only/i)).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('loads queue metrics, member workload and tickets when View is clicked', async () => {
    setupApi([queue]);

    const metrics = {
      queue: 5,
      queue_name: 'IT Support',
      total_active: 12,
      unassigned: 3,
      assigned: 9,
      in_progress: 4,
      waiting_requester: 2,
      waiting_third_party: 1,
      overdue: 2,
      sla_breached: 1,
      urgent: 3,
      members: 1,
      oldest_ticket_age_days: 6,
      workload_by_member: [
        {
          user: 2,
          user_name: 'EMP-002',
          role: 'agent',
          assigned_active: 5,
        },
      ],
    };

    const ticket = {
      id: 42,
      title: 'Printer not responding',
      status: 'in_progress',
      priority: 'high',
      requester_email: 'employee@example.com',
      assignee_email: 'agent@example.com',
      is_overdue: false,
      sla_breached: false,
      sla_due_at: null,
      created_at: '2026-11-27T08:00:00Z',
    };

    mockGet.mockImplementation(async (url) => {
      if (url === '/tickets/queues/') {
        return { data: { results: [queue] } };
      }
      if (url === '/tickets/queues/5/tickets/') {
        return { data: [ticket] };
      }
      if (url === '/tickets/queues/5/metrics/') {
        return { data: metrics };
      }
      if (
        url.startsWith('/accounts/departments/') ||
        url.startsWith('/accounts/users/') ||
        url.startsWith('/tickets/categories/')
      ) {
        return { data: { results: [] } };
      }
      return { data: { results: [] } };
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));

    expect(await screen.findByText('Queue metrics')).toBeTruthy();
    expect(screen.getByText('12')).toBeTruthy();
    expect(screen.getByText('EMP-002')).toBeTruthy();
    expect(screen.getByText('5')).toBeTruthy();
    expect(screen.getByText('Printer not responding')).toBeTruthy();

    const ticketLink = screen.getByRole('link', {
      name: 'Printer not responding',
    });
    expect(ticketLink.getAttribute('href')).toBe('#/tickets/42');

    expect(mockGet).toHaveBeenCalledWith('/tickets/queues/5/tickets/');
    expect(mockGet).toHaveBeenCalledWith('/tickets/queues/5/metrics/');
  });

  it('adds an Agent with the selected membership permissions', async () => {
    setupMembershipApi({
      users: [
        {
          id: 7,
          employee_id: 'EMP-007',
          email: 'agent@example.com',
        },
      ],
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));
    expect(await screen.findByText('Queue membership')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Add member' }));

    const memberSelect = screen.getByLabelText('Queue member');
    await screen.findByRole('option', { name: /EMP-007.*agent@example\.com/ });

    fireEvent.change(memberSelect, { target: { value: '7' } });
    fireEvent.click(screen.getByLabelText('Can assign tickets to others'));
    fireEvent.click(screen.getByLabelText('Can view all queue tickets'));

    const submitButton = screen.getByLabelText('Queue role')
      .closest('form')
      .querySelector('button[type="submit"]');

    if (!submitButton) throw new Error('Membership submit button was not found.');

    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/tickets/queue-memberships/', {
        queue: 5,
        user: 7,
        role: 'agent',
        can_claim: true,
        can_assign_others: true,
        can_view_all: true,
      });
    });

    expect(await screen.findByText('Queue member added successfully.')).toBeTruthy();
  });

  it('forces Observer permissions to disable claiming and assigning', async () => {
    setupMembershipApi({
      users: [
        {
          id: 8,
          employee_id: 'EMP-008',
          email: 'observer@example.com',
        },
      ],
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));
    expect(await screen.findByText('Queue membership')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Add member' }));

    await screen.findByRole('option', { name: /EMP-008.*observer@example\.com/ });
    fireEvent.change(screen.getByLabelText('Queue member'), {
      target: { value: '8' },
    });

    fireEvent.change(screen.getByLabelText('Queue role'), {
      target: { value: 'observer' },
    });

    expect(screen.getByLabelText('Can claim tickets').disabled).toBe(true);
    expect(screen.getByLabelText('Can assign tickets to others').disabled).toBe(true);
    expect(screen.getByLabelText('Can view all queue tickets').disabled).toBe(false);

    const submitButton = screen.getByLabelText('Queue role')
      .closest('form')
      .querySelector('button[type="submit"]');

    if (!submitButton) throw new Error('Membership submit button was not found.');

    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/tickets/queue-memberships/', {
        queue: 5,
        user: 8,
        role: 'observer',
        can_claim: false,
        can_assign_others: false,
        can_view_all: false,
      });
    });
  });

  it('updates an existing Agent membership using its ID and permission fields', async () => {
    setupMembershipApi({
      memberships: [
        {
          id: 31,
          queue: 5,
          user: 7,
          user_email: 'agent@example.com',
          role: 'agent',
          is_active: true,
          can_claim: true,
          can_assign_others: false,
          can_view_all: false,
        },
      ],
    });

    mockPut.mockResolvedValue({
      data: { id: 31, role: 'manager' },
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));
    expect(await screen.findByText('Queue membership')).toBeTruthy();

    const memberRow = screen.getByText('agent@example.com').closest('tr');
    expect(memberRow).toBeTruthy();

    fireEvent.click(
      memberRow.querySelector('button')
    );

    expect(await screen.findByText('Edit queue member')).toBeTruthy();
    expect(screen.queryByLabelText('Queue member')).toBeNull();

    fireEvent.change(screen.getByLabelText('Queue role'), {
      target: { value: 'manager' },
    });
    fireEvent.click(screen.getByLabelText('Can assign tickets to others'));
    fireEvent.click(screen.getByLabelText('Can view all queue tickets'));

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledWith(
        '/tickets/queue-memberships/31/',
        {
          role: 'manager',
          can_claim: true,
          can_assign_others: true,
          can_view_all: true,
        }
      );
    });

    expect(await screen.findByText('Queue member updated successfully.')).toBeTruthy();
  });

  it('forces Observer permissions off when editing an existing membership', async () => {
    setupMembershipApi({
      memberships: [
        {
          id: 32,
          queue: 5,
          user: 8,
          user_email: 'observer@example.com',
          role: 'agent',
          is_active: true,
          can_claim: true,
          can_assign_others: true,
          can_view_all: false,
        },
      ],
    });

    mockPut.mockResolvedValue({
      data: { id: 32, role: 'observer' },
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));
    expect(await screen.findByText('Queue membership')).toBeTruthy();

    const memberRow = screen.getByText('observer@example.com').closest('tr');
    expect(memberRow).toBeTruthy();

    fireEvent.click(memberRow.querySelector('button'));

    expect(await screen.findByText('Edit queue member')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Queue role'), {
      target: { value: 'observer' },
    });

    expect(screen.getByLabelText('Can claim tickets').disabled).toBe(true);
    expect(screen.getByLabelText('Can assign tickets to others').disabled).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledWith(
        '/tickets/queue-memberships/32/',
        {
          role: 'observer',
          can_claim: false,
          can_assign_others: false,
          can_view_all: false,
        }
      );
    });
  });

  it('displays backend membership validation errors', async () => {
    setupMembershipApi({
      users: [
        {
          id: 7,
          employee_id: 'EMP-007',
          email: 'agent@example.com',
        },
      ],
    });

    mockPost.mockRejectedValue({
      response: {
        data: { detail: 'This user already belongs to the queue.' },
      },
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));
    expect(await screen.findByText('Queue membership')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Add member' }));

    await screen.findByRole('option', { name: /EMP-007.*agent@example\.com/ });
    fireEvent.change(screen.getByLabelText('Queue member'), {
      target: { value: '7' },
    });

    const submitButton = screen.getByLabelText('Queue role')
      .closest('form')
      .querySelector('button[type="submit"]');

    if (!submitButton) throw new Error('Membership submit button was not found.');

    fireEvent.click(submitButton);

    expect(await screen.findByText('This user already belongs to the queue.')).toBeTruthy();
  });

  it('does not expose membership management to IT Support', async () => {
    setupMembershipApi();

    mockAuth.mockReturnValue({
      isStaff: true,
      isManagerOrAdmin: false,
      user: { id: 2, role: 'it_support' },
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));
    expect(await screen.findByText('Queue metrics')).toBeTruthy();

    expect(screen.queryByRole('button', { name: 'Add member' })).toBeNull();
    expect(mockGet).not.toHaveBeenCalledWith('/tickets/queue-memberships/?queue=5');
  });

  it('cancels queue member removal without calling the backend', async () => {
    setupMembershipApi({
      memberships: [
        {
          id: 41,
          queue: 5,
          user: 9,
          user_email: 'remove@example.com',
          role: 'agent',
          is_active: true,
          can_claim: true,
          can_assign_others: false,
          can_view_all: false,
        },
      ],
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));
    expect(await screen.findByText('Queue membership')).toBeTruthy();

    const memberRow = screen.getByText('remove@example.com').closest('tr');
    expect(memberRow).toBeTruthy();

    fireEvent.click(
      memberRow.querySelectorAll('button')[1]
    );

    expect(await screen.findByText(/will lose membership in "IT Support"/i))
      .toBeTruthy();

    expect(mockPost).not.toHaveBeenCalledWith(
      '/tickets/queue-memberships/41/remove/'
    );

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => {
      expect(
        screen.queryByText(/will lose membership in "IT Support"/i)
      ).toBeNull();
    });

    expect(mockPost).not.toHaveBeenCalledWith(
      '/tickets/queue-memberships/41/remove/'
    );
  });

  it('removes a queue member only after confirmation and refreshes memberships', async () => {
    setupMembershipApi({
      memberships: [
        {
          id: 42,
          queue: 5,
          user: 10,
          user_email: 'leaving@example.com',
          role: 'agent',
          is_active: true,
          can_claim: true,
          can_assign_others: false,
          can_view_all: false,
        },
      ],
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));
    expect(await screen.findByText('Queue membership')).toBeTruthy();

    const memberRow = screen.getByText('leaving@example.com').closest('tr');
    expect(memberRow).toBeTruthy();

    fireEvent.click(memberRow.querySelectorAll('button')[1]);

    expect(await screen.findByText(/will lose membership in "IT Support"/i))
      .toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Remove member' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/tickets/queue-memberships/42/remove/'
      );
    });

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(
        '/tickets/queue-memberships/?queue=5'
      );
    });

    expect(
      await screen.findByText('leaving@example.com was removed from the queue.')
    ).toBeTruthy();
  });

  it('keeps inactive queue memberships visible without edit or remove actions', async () => {
    setupMembershipApi({
      memberships: [
        {
          id: 43,
          queue: 5,
          user: 11,
          user_email: 'former-member@example.com',
          role: 'agent',
          is_active: false,
          can_claim: false,
          can_assign_others: false,
          can_view_all: false,
        },
      ],
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));

    const memberRow = (await screen.findByText('former-member@example.com')).closest('tr');
    expect(memberRow).toBeTruthy();
    expect(memberRow.textContent).toContain('Inactive');

    expect(memberRow.querySelector('button').disabled).toBe(true);
    expect(memberRow.querySelectorAll('button')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull();
  });

  it('displays backend errors when queue member removal fails', async () => {
    setupMembershipApi({
      memberships: [
        {
          id: 44,
          queue: 5,
          user: 12,
          user_email: 'failed-remove@example.com',
          role: 'agent',
          is_active: true,
          can_claim: true,
          can_assign_others: false,
          can_view_all: false,
        },
      ],
    });

    mockPost.mockRejectedValue({
      response: {
        data: { detail: 'This membership cannot be removed.' },
      },
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));

    const memberRow = (await screen.findByText('failed-remove@example.com')).closest('tr');
    expect(memberRow).toBeTruthy();

    fireEvent.click(memberRow.querySelectorAll('button')[1]);

    fireEvent.click(
      await screen.findByRole('button', { name: 'Remove member' })
    );

    expect(
      await screen.findByText('This membership cannot be removed.')
    ).toBeTruthy();

    expect(mockPost).toHaveBeenCalledWith(
      '/tickets/queue-memberships/44/remove/'
    );
  });

  it('auto-assigns tickets after confirmation and refreshes queue details', async () => {
    setupApi([queue]);
    mockPost.mockResolvedValue({ data: { assigned: [42, 43] } });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));

    fireEvent.click(
      await screen.findByRole('button', { name: 'Auto-assign unassigned tickets' })
    );

    expect(
      await screen.findByText(/all currently unassigned open tickets/i)
    ).toBeTruthy();

    fireEvent.click(
      screen.getByRole('button', { name: 'Auto-assign tickets' })
    );

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/tickets/queues/5/auto-assign/'
      );
    });

    expect(
      await screen.findByText(/2 unassigned ticket\(s\) were assigned/i)
    ).toBeTruthy();

    await waitFor(() => {
      expect(mockGet.mock.calls.filter(
        ([url]) => url === '/tickets/queues/5/tickets/'
      )).toHaveLength(2);

      expect(mockGet.mock.calls.filter(
        ([url]) => url === '/tickets/queues/5/metrics/'
      )).toHaveLength(2);
    });
  });

  it('does not auto-assign tickets when confirmation is cancelled', async () => {
    setupApi([queue]);

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));

    fireEvent.click(
      await screen.findByRole('button', { name: 'Auto-assign unassigned tickets' })
    );

    fireEvent.click(
      screen.getByRole('button', { name: 'Cancel' })
    );

    expect(mockPost).not.toHaveBeenCalledWith(
      '/tickets/queues/5/auto-assign/'
    );
    expect(
      screen.queryByRole('button', { name: 'Auto-assign tickets' })
    ).toBeNull();
  });

  it('displays backend errors when queue auto-assignment fails', async () => {
    setupApi([queue]);

    mockPost.mockRejectedValue({
      response: {
        data: { detail: 'No eligible claim-eligible members on this queue.' },
      },
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));

    fireEvent.click(
      await screen.findByRole('button', { name: 'Auto-assign unassigned tickets' })
    );

    fireEvent.click(
      screen.getByRole('button', { name: 'Auto-assign tickets' })
    );

    expect(
      await screen.findByText('No eligible claim-eligible members on this queue.')
    ).toBeTruthy();

    expect(mockPost).toHaveBeenCalledWith(
      '/tickets/queues/5/auto-assign/'
    );
  });

  it('hides auto-assignment for unsupported queue strategies', async () => {
    setupApi([{ ...queue, assignment_strategy: 'category_owner' }]);

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));

    expect(await screen.findByText('Queue metrics')).toBeTruthy();

    expect(
      screen.queryByRole('button', { name: 'Auto-assign unassigned tickets' })
    ).toBeNull();
  });

  it('does not expose auto-assignment to IT Support users', async () => {
    setupApi([queue]);

    mockAuth.mockReturnValue({
      isStaff: true,
      isManagerOrAdmin: false,
      user: { id: 2, role: 'it_support' },
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));

    expect(await screen.findByText('Queue metrics')).toBeTruthy();

    expect(
      screen.queryByRole('button', { name: 'Auto-assign unassigned tickets' })
    ).toBeNull();
  });

  it('shows a useful error when queue detail requests fail', async () => {
    setupApi([queue]);

    mockGet.mockImplementation(async (url) => {
      if (url === '/tickets/queues/') {
        return { data: { results: [queue] } };
      }
      if (url === '/tickets/queues/5/tickets/') {
        return { data: [] };
      }
      if (url === '/tickets/queues/5/metrics/') {
        throw {
          response: {
            data: { detail: 'Queue metrics unavailable' },
          },
        };
      }
      if (
        url.startsWith('/accounts/departments/') ||
        url.startsWith('/accounts/users/') ||
        url.startsWith('/tickets/categories/')
      ) {
        return { data: { results: [] } };
      }
      return { data: { results: [] } };
    });

    render(<TicketQueuesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'View' }));

    expect(await screen.findByText('Queue metrics unavailable')).toBeTruthy();
    expect(screen.queryByText('Queue tickets')).toBeNull();
  });
});