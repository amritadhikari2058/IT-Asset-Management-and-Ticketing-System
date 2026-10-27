import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

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

vi.mock('./bulk', () => ({
  AssetBulkCreateModal: () => null,
  EmployeeCreateModal: () => null,
  EmployeeImportModal: () => null,
  TicketBulkCreateModal: () => null,
}));

import { Tickets, Assets, Categories } from './pages';
import { TicketForm } from './tickets';
import { AssetForm } from './assets';

const DEPARTMENTS = [
  { id: 1, name: 'Engineering', code: 'ENG', is_active: true },
  { id: 2, name: 'Marketing', code: 'MKT', is_active: true },
];
const TICKET_CATEGORIES = [{ id: 3, name: 'Hardware', is_active: true }];
const ASSET_CATEGORIES = [{ id: 4, name: 'Laptops', is_active: true }];

function staff() {
  mockAuth.mockReturnValue({
    isStaff: true, isAdmin: false, canCreateTickets: true,
    user: { id: 1, role: 'it_support', home_department: 1 },
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockGet.mockImplementation(async (url) => {
    const u = String(url);
    if (u.startsWith('/tickets/categories/')) {
      return { data: { results: TICKET_CATEGORIES, count: 1, next: null, previous: null } };
    }
    if (u.startsWith('/assets/categories/')) {
      return { data: { results: ASSET_CATEGORIES, count: 1, next: null, previous: null } };
    }
    if (u.startsWith('/accounts/departments/')) {
      return { data: { results: DEPARTMENTS, count: 2, next: null, previous: null } };
    }
    if (u === '/tickets/7/') {
      return {
        data: {
          id: 7, title: 'Printer down', description: 'No power.', priority: 'high',
          category: 3, department: 1, on_behalf_reason: '', asset: null,
          assignee: null, status: 'open', resolution_notes: '',
        },
      };
    }
    if (u === '/assets/3/') {
      return {
        data: {
          id: 3, asset_tag: 'LT-1', name: 'ThinkPad', status: 'available',
          category: 4, serial_number: '', description: '', location: '',
          department: 1, purchase_date: null, warranty_expiry: null,
          purchase_cost: null, assigned_to: null,
        },
      };
    }
    if (u.startsWith('/tickets/')) {
      return { data: { results: [], count: 0, next: null, previous: null } };
    }
    if (u.startsWith('/assets/')) {
      return {
        data: {
          results: [{
            id: 1, asset_tag: 'LT-1', name: 'ThinkPad', status: 'available',
            category_name: 'Laptops', department_name: null,
            assigned_to_email: null, serial_number: '', location: 'HQ',
            description: '', purchase_date: null, warranty_expiry: null,
            purchase_cost: null, photo_attachment_id: null, created_at: null,
          }],
          count: 1, next: null, previous: null,
        },
      };
    }
    return { data: { results: [], count: 0, next: null, previous: null } };
  });
});

afterEach(() => cleanup());

function expectNoDepartmentCreationControls() {
  // No buttons or creation text anywhere in the rendered tree.
  expect(screen.queryByRole('button', { name: /new department/i })).toBeNull();
  expect(screen.queryByRole('button', { name: /create department/i })).toBeNull();
  expect(screen.queryByRole('button', { name: /add department/i })).toBeNull();
  expect(screen.queryByText(/Create department/i)).toBeNull();
}

describe('Requirement: no category creation in the ticket workflow', () => {
  it('shows no "+ Add" trigger next to the ticket category in the ticket form', async () => {
    staff();
    render(<TicketForm />);
    await screen.findByText('New ticket');
    await screen.findByLabelText(/category/i);
    await waitFor(() => expect(
      [...screen.getByLabelText(/category/i).querySelectorAll('option')].filter(
        (o) => o.value,
      ).length >= 1,
    ).toBe(true));
    expect(screen.queryByRole('button', { name: '+ Add' })).toBeNull();
    // Existing categories remain selectable.
    expect(
      [...screen.getByLabelText(/category/i).querySelectorAll('option')]
        .map((o) => o.textContent),
    ).toContain('Hardware');
  });

  it('shows no "+ Add" trigger on the Tickets page category filter', async () => {
    staff();
    render(<Tickets />);
    await screen.findByText('Hardware');
    expect(screen.queryByRole('button', { name: '+ Add' })).toBeNull();
  });

  it('keeps the Categories management page as the category source of truth', async () => {
    staff();
    render(<Categories />);
    await screen.findByText('Laptops');
    // The dedicated page still creates/edits categories.
    expect(screen.getByText('Add category')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Edit…' }).length).toBe(2);
    expect(screen.getByText('Hardware')).toBeTruthy();
  });
});

describe('Requirement: no department creation in the asset workflow', () => {
  it('Assets page: selector-only departments, no creation control', async () => {
    staff();
    render(<Assets />);
    await screen.findByText('LT-1');
    expectNoDepartmentCreationControls();
    // The department select is populated from existing departments.
    const sel = screen.getByLabelText('Department');
    expect(
      [...sel.querySelectorAll('option')].map((o) => o.textContent),
    ).toEqual(expect.arrayContaining(['Engineering', 'Marketing']));
  });

  it('AssetForm: selector-only departments, no creation control', async () => {
    staff();
    render(<AssetForm />);
    await screen.findByText('New asset');
    expectNoDepartmentCreationControls();
    const sel = screen.getByLabelText('Department');
    await waitFor(() => expect(
      [...sel.querySelectorAll('option')].map((o) => o.textContent),
    ).toEqual(expect.arrayContaining(['Engineering'])));
  });

  it('AssetForm keeps the asset category "+ Add" affordance (asset-side, by design)', async () => {
    staff();
    render(<AssetForm />);
    await screen.findByText('New asset');
    expect(screen.getByRole('button', { name: '+ Add' })).toBeTruthy();
  });
});
