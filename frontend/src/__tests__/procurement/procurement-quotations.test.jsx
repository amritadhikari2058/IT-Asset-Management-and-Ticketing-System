import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
    delete: (...a) => mockDelete(...a),
  },
}));
vi.mock('../../auth', () => ({ useAuth: (...a) => mockAuth(...a) }));

import { PurchaseRequestQuotations } from '../../pages/procurement/ProcurementQuotations';

function makeAuth(role) {
  return {
    access: 'token',
    role,
    user: { id: 1, email: `${role}@x`, role },
    isStaff: ['system_admin', 'it_manager', 'it_support'].includes(role),
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isManagerOrAdmin: ['system_admin', 'it_manager'].includes(role),
  };
}

const VENDORS = [
  { id: 3, name: 'Acme Supplies', is_active: true },
  { id: 4, name: 'Retired Vendor', is_active: false },
];

const REQUEST = {
  id: 1,
  pr_number: 'PR-2026-00001',
  requester: 2,
  requester_name: 'requester@x',
  department: null,
  status: 'approved',
  reason: 'Laptops',
  notes: '',
  estimated_total: '100000.00',
  requires_system_admin_approval: false,
  approver: 1,
  approver_name: 'mgr@x',
  approval_decision: 'approved',
  approval_reason: '',
  approved_at: '2026-11-02T10:00:00Z',
  created_at: '2026-11-01T10:00:00Z',
  updated_at: '2026-11-02T10:00:00Z',
  items: [],
  quotations: [],
  history: [],
};

const QUOTATIONS = [
  {
    id: 40, purchase_request: 1, vendor: 3, vendor_detail: { id: 3, name: 'Acme Supplies' },
    quoted_amount: '98000.00', delivery_days: 12, warranty: '2 years', terms: 'Net 30',
    notes: '', is_selected: true, selected_by: 1, selected_by_name: 'mgr@x',
    selection_reason: 'Best price', selected_at: '2026-11-03T10:00:00Z', created_at: '',
  },
  {
    id: 41, purchase_request: 1, vendor: 4, vendor_detail: { id: 4, name: 'Second Vendor' },
    quoted_amount: '101000.00', delivery_days: 7, warranty: '1 year', terms: 'Net 15',
    notes: '', is_selected: false, selection_reason: '', created_at: '',
  },
];

function routeGet(request) {
  mockGet.mockImplementation((url) => {
    if (String(url).startsWith('/procurement/purchase-requests/1/')) {
      return Promise.resolve({ data: request });
    }
    if (String(url).startsWith('/assets/vendors/')) {
      return Promise.resolve({ data: { results: VENDORS, count: 2, next: null } });
    }
    return Promise.resolve({ data: { results: [], count: 0, next: null } });
  });
}

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  mockAuth.mockReturnValue(makeAuth('it_manager'));
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('Vendor quotations', () => {
  it('records a quotation with the real payload', async () => {
    routeGet({ ...REQUEST, quotations: [] });
    render(<PurchaseRequestQuotations id="1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Add quotation' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByRole('combobox', { name: 'Vendor' }), { target: { value: '3' } });
    fireEvent.change(within(dialog).getByRole('spinbutton', { name: 'Quoted amount' }), { target: { value: '98000' } });
    fireEvent.change(within(dialog).getByRole('spinbutton', { name: 'Delivery days' }), { target: { value: '12' } });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Warranty' }), { target: { value: '2 years' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save quotation' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/quotations/', {
      purchase_request: 1,
      vendor: 3,
      quoted_amount: '98000.00',
      delivery_days: 12,
      warranty: '2 years',
      terms: '',
      notes: '',
    }));
  });

  it('only offers active vendors', async () => {
    routeGet({ ...REQUEST, quotations: [] });
    render(<PurchaseRequestQuotations id="1" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add quotation' }));
    const select = screen.getByRole('combobox', { name: 'Vendor' });
    const options = [...select.querySelectorAll('option')].map((o) => o.textContent);
    expect(options).toContain('Acme Supplies');
    expect(options).not.toContain('Retired Vendor');
  });

  it('requires a vendor and a positive amount', async () => {
    routeGet({ ...REQUEST, quotations: [] });
    render(<PurchaseRequestQuotations id="1" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add quotation' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save quotation' }));
    expect(await screen.findByText('Select an active vendor.')).toBeTruthy();
    expect(screen.getByText('Quoted amount must be greater than zero.')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('compares quotations and links back to the request', async () => {
    routeGet({ ...REQUEST, quotations: QUOTATIONS });
    render(<PurchaseRequestQuotations id="1" />);

    expect((await screen.findAllByText('Acme Supplies')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Second Vendor').length).toBeGreaterThan(0);
    expect(screen.getByText(/Best price/)).toBeTruthy();
    expect(screen.getByText(/Price is only one selection factor/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Back to request' }).getAttribute('href'))
      .toBe('#/procurement/requests/1');
  });

  it('selects a vendor with a required reason through the real endpoint', async () => {
    routeGet({ ...REQUEST, quotations: QUOTATIONS });
    render(<PurchaseRequestQuotations id="1" />);

    const secondRow = (await screen.findAllByText('Second Vendor'))[0].closest('tr');
    fireEvent.click(within(secondRow).getByRole('button', { name: 'Select vendor' }));
    const dialog = screen.getByRole('dialog');
    const confirm = within(dialog).getByRole('button', { name: 'Confirm selection' });
    expect(confirm.disabled).toBe(true);

    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Selection reason' }), {
      target: { value: 'Faster delivery' },
    });
    fireEvent.click(confirm);

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/quotations/41/select/', { reason: 'Faster delivery' },
    ));
  });

  it('does not let IT Support select a vendor', async () => {
    mockAuth.mockReturnValue(makeAuth('it_support'));
    routeGet({ ...REQUEST, quotations: QUOTATIONS });
    render(<PurchaseRequestQuotations id="1" />);
    await screen.findAllByText('Acme Supplies');
    expect(screen.queryByRole('button', { name: 'Select vendor' })).toBeNull();
  });

  it('updates an existing quotation through PATCH', async () => {
    routeGet({ ...REQUEST, quotations: QUOTATIONS });
    render(<PurchaseRequestQuotations id="1" />);
    const rows = await screen.findAllByRole('button', { name: 'Edit' });
    fireEvent.click(rows[0]);
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByRole('spinbutton', { name: 'Quoted amount' }), {
      target: { value: '95000' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save quotation' }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      '/procurement/quotations/40/',
      expect.objectContaining({ quoted_amount: '95000.00' }),
    ));
  });

  it('refuses quotations until the request is approved', async () => {
    routeGet({ ...REQUEST, status: 'pending_approval', quotations: [] });
    render(<PurchaseRequestQuotations id="1" />);
    expect(await screen.findByText(/Quotations can only be recorded for an approved request/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Add quotation' })).toBeNull();
  });
});
