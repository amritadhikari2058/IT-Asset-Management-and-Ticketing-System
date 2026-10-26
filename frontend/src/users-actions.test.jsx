import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

vi.mock('./bulk', () => ({
  AssetBulkCreateModal: () => null,
  EmployeeCreateModal: () => null,
  EmployeeImportModal: () => null,
  TicketBulkCreateModal: () => null,
}));

import { Users } from './pages';

const ACTIVE = {
  id: 5, employee_id: 'E5', email: 'e5@x', role: 'employee',
  home_department: 1, home_department_name: 'Eng', is_active: true,
};
const INACTIVE = { ...ACTIVE, id: 6, employee_id: 'E6', is_active: false };

function staff() {
  mockAuth.mockReturnValue({ isStaff: true, isAdmin: false, user: { id: 1 } });
}

function admin() {
  mockAuth.mockReturnValue({ isStaff: true, isAdmin: true, user: { id: 1 } });
}

function employee() {
  mockAuth.mockReturnValue({ isStaff: false, isAdmin: false, user: { id: 9 } });
}

function list(...rows) {
  mockGet.mockImplementation(async (url) => {
    if (String(url).startsWith('/accounts/users/')) {
      return { data: { results: rows, count: rows.length, next: null, previous: null } };
    }
    throw new Error(`unexpected GET ${url}`);
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.confirm = vi.fn(() => true);
  list(ACTIVE, INACTIVE);
  mockPost.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('Users row actions', () => {
  it('deactivates an active user after confirmation', async () => {
    staff();
    render(<Users />);
    await screen.findByText('E5');
    fireEvent.click(screen.getAllByRole('button', { name: 'Deactivate…' })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Deactivate' }));
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/accounts/users/5/deactivate/', {});
    });
    expect(await screen.findByText(/deactivated/)).toBeTruthy();
  });

  it('reactivates an inactive user', async () => {
    staff();
    render(<Users />);
    await screen.findByText('E6');
    const btns = screen.getAllByRole('button', { name: 'Reactivate…' });
    expect(btns.length).toBe(1);
    fireEvent.click(btns[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Reactivate' }));
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/accounts/users/6/reactivate/', {});
    });
  });

  it('shows role changes only to admins', async () => {
    staff();
    render(<Users />);
    await screen.findByText('E5');
    expect(screen.queryByRole('button', { name: 'Role…' })).toBeNull();
  });

  it('changes a role as admin with confirmation feedback', async () => {
    admin();
    mockPost.mockResolvedValueOnce({ data: {} });
    render(<Users />);
    await screen.findByText('E5');
    fireEvent.click(screen.getAllByRole('button', { name: 'Role…' })[0]);
    fireEvent.change(screen.getByLabelText('Role'), {
      target: { value: 'it_support' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Change role' }));
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/accounts/users/5/change_role/', {
        role: 'it_support', can_create_tickets: true,
      });
    });
    expect(await screen.findByText(/updated/)).toBeTruthy();
  });

  it('hides row actions from employees', async () => {
    employee();
    render(<Users />);
    await screen.findByText('E5');
    expect(screen.queryByRole('button', { name: /eactivate/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Role…' })).toBeNull();
  });

  it('surfaces backend errors', async () => {
    staff();
    mockPost.mockRejectedValueOnce({
      response: { status: 409, data: { detail: 'Blocked.' } },
    });
    render(<Users />);
    await screen.findByText('E5');
    fireEvent.click(screen.getAllByRole('button', { name: 'Deactivate…' })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Deactivate' }));
    expect(await screen.findByText('Blocked.')).toBeTruthy();
  });
});
