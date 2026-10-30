import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { EmployeeDetail } from './pages';

const DETAIL = {
  user: {
    id: 5, employee_id: 'E5', email: 'e5@x', role: 'employee',
    home_department_name: 'Eng', phone: '555-0100', job_title: 'Analyst',
    is_active: true, date_joined: '2026-01-01T00:00:00Z',
  },
  assigned_assets: [
    { id: 9, asset_tag: 'L1', name: 'Laptop', status: 'assigned',
      category_name: 'Laptops', department_name: 'Eng' },
  ],
  tickets_requested: [
    { id: 3, title: 'Broken monitor', status: 'open',
      category_name: 'SW', department_name: 'Eng' },
  ],
  tickets_assigned: [],
  recent_audit: [],
};

function staff() {
  mockAuth.mockReturnValue({ isStaff: true, user: { id: 1 } });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockResolvedValue({ data: DETAIL });
});

afterEach(() => cleanup());

describe('Employee detail', () => {
  it('loads and shows the employee profile', async () => {
    staff();
    render(<EmployeeDetail id={5} />);
    await waitFor(() => expect(screen.getByText('Employee E5')).toBeTruthy());
    expect(screen.getByText('e5@x')).toBeTruthy();
    expect(screen.getByText('employee')).toBeTruthy();
    expect(screen.getByText('555-0100')).toBeTruthy();
    expect(screen.getByText('Analyst')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/accounts/users/5/employee_detail/');
  });

  it('shows assigned assets and requested tickets with links', async () => {
    staff();
    render(<EmployeeDetail id={5} />);
    await waitFor(() => expect(screen.getByText('L1')).toBeTruthy());
    expect(screen.getByText('Broken monitor')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'L1' })).toBeTruthy();
    expect(screen.getByRole('link', { name: '#3' })).toBeTruthy();
  });

  it('shows an error when the detail request fails', async () => {
    staff();
    mockGet.mockRejectedValueOnce({
      response: { status: 403, data: { detail: 'Forbidden.' } },
    });
    render(<EmployeeDetail id={5} />);
    expect(await screen.findByText(/Forbidden/i)).toBeTruthy();
  });
});
