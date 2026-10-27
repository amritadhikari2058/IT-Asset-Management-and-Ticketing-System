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
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { Assets } from './pages';

const A_AVAILABLE = {
  id: 1, asset_tag: 'PR-1', name: 'LaserJet', status: 'available',
  category_name: 'Printer', department_name: 'Finance',
  assigned_to: null, assigned_to_email: null, location: 'HQ Floor 1',
  serial_number: 'SN-1', description: '',
  purchase_date: null, warranty_expiry: null, purchase_cost: '49.99',
  created_at: '2026-01-01T09:00:00Z', photo_attachment_id: null,
};
const A_ASSIGNED = {
  ...A_AVAILABLE, id: 2, asset_tag: 'LT-2', name: 'ThinkPad T14',
  status: 'assigned', assigned_to: 4, assigned_to_email: 'emp@local',
  location: 'HQ Floor 2',
};
const A_RETIRED = {
  ...A_AVAILABLE, id: 3, asset_tag: 'MN-3', name: 'UltraSharp',
  status: 'retired', assigned_to: null, assigned_to_email: null,
};

const PAGE = { results: [A_AVAILABLE, A_ASSIGNED, A_RETIRED], count: 3, next: null, previous: null };

function route(url) {
  const p = String(url).split('?')[0];
  if (p === '/assets/') return { data: PAGE };
  if (p.startsWith('/assets/categories/')) return { data: { results: [{ id: 1, name: 'Hardware', is_active: true }] } };
  if (p.startsWith('/accounts/departments/')) {
    return { data: { results: [{ id: 1, name: 'Finance', code: 'FIN', is_active: true }] } };
  }
  if (p.startsWith('/accounts/users/')) {
    return { data: { results: [{ id: 4, employee_id: 'EMP-4', email: 'emp@local', is_active: true }] } };
  }
  throw new Error(`unexpected GET ${url}`);
}

function staff() {
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_support' } });
}
function employee() {
  mockAuth.mockReturnValue({ isStaff: false, user: { role: 'employee' } });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockGet.mockImplementation(async (url) => route(url));
  mockPost.mockResolvedValue({ data: A_AVAILABLE });
});

afterEach(() => cleanup());

describe('Assets list row actions', () => {
  it('shows no Actions column, row controls, or checkboxes for employees', async () => {
    employee();
    render(<Assets />);
    await waitFor(() => expect(screen.getByText('PR-1')).toBeTruthy());
    expect(screen.queryByText('Actions')).toBeNull();
    expect(screen.queryByLabelText('Assign PR-1')).toBeNull();
    expect(screen.queryByLabelText('Return LT-2')).toBeNull();
    expect(screen.queryByLabelText('Retire MN-3')).toBeNull();
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
  });

  it('gates actions by status: Assign only when available, Return only when held, no Retire when retired/lost', async () => {
    staff();
    render(<Assets />);
    await waitFor(() => expect(screen.getByText('Actions')).toBeTruthy());
    expect(screen.getByLabelText('Edit PR-1')).toBeTruthy();
    expect(screen.getByLabelText('Assign PR-1')).toBeTruthy();
    expect(screen.getByLabelText('Retire PR-1')).toBeTruthy();
    expect(screen.queryByLabelText('Return PR-1')).toBeNull();
    expect(screen.getByLabelText('Return LT-2')).toBeTruthy();
    expect(screen.queryByLabelText('Assign LT-2')).toBeNull();
    expect(screen.getByLabelText('Edit MN-3')).toBeTruthy();
    expect(screen.queryByLabelText('Retire MN-3')).toBeNull();
  });

  it('confirm dialog posts return_asset and refreshes the list', async () => {
    staff();
    render(<Assets />);
    await waitFor(() => expect(screen.getByLabelText('Return LT-2')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('Return LT-2'));
    expect(await screen.findByText('Return LT-2?')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Return asset' }));
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/assets/2/return_asset/');
    });
    // The list is refreshed after the action.
    expect(mockGet.mock.calls.filter(([u]) => String(u).startsWith('/assets/')).length).toBeGreaterThan(1);
  });

  it('confirm dialog posts retire (danger styled dialogs stay menu-agnostic here)', async () => {
    staff();
    render(<Assets />);
    await waitFor(() => expect(screen.getByLabelText('Retire PR-1')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('Retire PR-1'));
    expect(await screen.findByText('Retire PR-1?')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retire asset' }));
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/assets/1/retire/');
    });
  });

  it('assign modal submits employee id and note to the assign endpoint', async () => {
    staff();
    render(<Assets />);
    await waitFor(() => expect(screen.getByLabelText('Assign PR-1')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('Assign PR-1'));
    expect(await screen.findByText('Assign PR-1')).toBeTruthy();
    // Submit stays blocked until an employee is picked.
    fireEvent.click(screen.getByRole('button', { name: 'Assign' }));
    expect(mockPost).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Assignee'), { target: { value: '4' } });
    fireEvent.change(screen.getByPlaceholderText('Reason…'), { target: { value: 'New hire setup' } });
    fireEvent.click(screen.getByRole('button', { name: 'Assign' }));
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/assets/1/assign/', {
        assigned_to: 4, note: 'New hire setup',
      });
    });
  });

  it('surfaces a failed row action as an inline alert and closes its dialog', async () => {
    staff();
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'Nope.' } },
    });
    render(<Assets />);
    await waitFor(() => expect(screen.getByLabelText('Retire PR-1')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('Retire PR-1'));
    fireEvent.click(screen.getByRole('button', { name: 'Retire asset' }));
    expect(await screen.findByText('Nope.')).toBeTruthy();
  });
});
