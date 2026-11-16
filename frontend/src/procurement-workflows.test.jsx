import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
    delete: (...a) => mockDelete(...a),
  },
}));
vi.mock('./auth', () => ({ useAuth: (...a) => mockAuth(...a) }));

import { PurchaseRequestDetail } from './purchase-request-detail';
import { PurchaseRequestForm } from './purchase-request-form';

function makeAuth(role, id = 1) {
  return {
    access: 'token',
    role,
    user: { id, email: `${role}@x`, role },
    isStaff: ['system_admin', 'it_manager', 'it_support'].includes(role),
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isManagerOrAdmin: ['system_admin', 'it_manager'].includes(role),
  };
}

function page(results = []) {
  return { data: { results, count: results.length, next: null, previous: null } };
}

const BASE_REQUEST = {
  id: 1,
  pr_number: 'PR-2026-00001',
  requester: 2,
  requester_name: 'requester@x',
  department: null,
  status: 'draft',
  reason: 'Replacement laptops',
  notes: '',
  estimated_total: '100.00',
  requires_system_admin_approval: false,
  approver: null,
  approver_name: null,
  approval_decision: '',
  approval_reason: '',
  approved_at: null,
  created_at: '2026-11-01T10:00:00Z',
  updated_at: '2026-11-02T10:00:00Z',
  items: [{
    id: 11, item_name: 'Laptop', description: '', quantity: 2,
    estimated_unit_price: '50.00', estimated_total: '100.00',
    suggested_vendor: null, notes: '',
  }],
  quotations: [],
  history: [],
};

function routeGet(map) {
  mockGet.mockImplementation((url) => {
    const key = Object.keys(map).find((prefix) => String(url).startsWith(prefix));
    if (!key) return Promise.resolve(page([]));
    return Promise.resolve(map[key]);
  });
}

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  mockAuth.mockReturnValue(makeAuth('it_manager'));
  mockPost.mockResolvedValue({ data: { id: 1 } });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
  mockGet.mockResolvedValue(page([]));
});

afterEach(() => cleanup());

describe('Purchase request wizard', () => {
  it('creates a draft request and its line items', async () => {
    mockPost
      .mockResolvedValueOnce({ data: { id: 9, pr_number: 'PR-2026-00009' } })
      .mockResolvedValue({ data: { id: 90 } });
    render(<PurchaseRequestForm />);

    fireEvent.change(screen.getByRole('textbox', { name: 'Business justification' }), {
      target: { value: 'Need replacement laptops for the service desk' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    fireEvent.change(await screen.findByRole('textbox', { name: 'Item name line 1' }), {
      target: { value: 'Laptop' },
    });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Quantity line 1' }), {
      target: { value: '2' },
    });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Estimated unit price line 1' }), {
      target: { value: '75000' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByText('Review')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2));
    expect(mockPost.mock.calls[0][0]).toBe('/procurement/purchase-requests/');
    expect(mockPost.mock.calls[0][1]).toMatchObject({
      reason: 'Need replacement laptops for the service desk',
      estimated_total: '150000.00',
    });
    expect(mockPost.mock.calls[1][0]).toBe('/procurement/purchase-request-items/');
    expect(mockPost.mock.calls[1][1]).toMatchObject({
      purchase_request: 9,
      item_name: 'Laptop',
      quantity: 2,
      estimated_unit_price: 75000,
    });
    expect(mockPost.mock.calls.some((c) => String(c[0]).includes('/submit/'))).toBe(false);
  });

  it('creates and submits in one flow when requested', async () => {
    mockPost.mockResolvedValue({ data: { id: 9 } });
    render(<PurchaseRequestForm />);

    fireEvent.change(screen.getByRole('textbox', { name: 'Business justification' }), {
      target: { value: 'Printer toner' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Item name line 1' }), {
      target: { value: 'Toner' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Save and submit for approval' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/purchase-requests/9/submit/', {},
    ));
  });

  it('blocks the first step without a business justification', async () => {
    render(<PurchaseRequestForm />);
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('Business justification is required.')).toBeTruthy();
  });

  it('blocks the line step without an item name', async () => {
    render(<PurchaseRequestForm />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Business justification' }), {
      target: { value: 'Reason' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Continue' }));
    expect(await screen.findByText('Item name is required.')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('supports multiple line items', async () => {
    render(<PurchaseRequestForm />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Business justification' }), {
      target: { value: 'Bulk order' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await screen.findByRole('textbox', { name: 'Item name line 1' });
    fireEvent.click(screen.getByRole('button', { name: 'Add another line' }));
    expect(screen.getByRole('textbox', { name: 'Item name line 2' })).toBeTruthy();
  });

  it('shows the informational estimate without posting totals as authoritative', async () => {
    render(<PurchaseRequestForm />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Business justification' }), {
      target: { value: 'Estimate check' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Item name line 1' }), {
      target: { value: 'Thing' },
    });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Quantity line 1' }), { target: { value: '3' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Estimated unit price line 1' }), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByText(/informational/)).toBeTruthy();
  });
});

describe('Purchase request detail and actions', () => {
  const detailRoutes = (request) => ({
    '/procurement/purchase-requests/1/': { data: request },
    '/procurement/purchase-orders/': page([]),
    '/procurement/goods-receipts/': page([]),
  });

  it('submits a draft request through the real endpoint', async () => {
    routeGet(detailRoutes(BASE_REQUEST));
    render(<PurchaseRequestDetail id="1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Submit for approval' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Submit' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/purchase-requests/1/submit/', { reason: '' },
    ));
  });

  it('shows approval only for a manager who is not the requester', async () => {
    routeGet(detailRoutes({ ...BASE_REQUEST, status: 'pending_approval' }));
    render(<PurchaseRequestDetail id="1" />);
    expect(await screen.findByRole('button', { name: 'Approve' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Return for correction' })).toBeTruthy();
  });

  it('never exposes self-approval', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager', 2));
    routeGet(detailRoutes({ ...BASE_REQUEST, status: 'pending_approval' }));
    render(<PurchaseRequestDetail id="1" />);
    await screen.findByText('PR-2026-00001');
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
  });

  it('does not expose approval to IT Support', async () => {
    mockAuth.mockReturnValue(makeAuth('it_support'));
    routeGet(detailRoutes({ ...BASE_REQUEST, status: 'pending_approval' }));
    render(<PurchaseRequestDetail id="1" />);
    await screen.findByText('PR-2026-00001');
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
  });

  it('requires a reason to reject and posts the decision', async () => {
    routeGet(detailRoutes({ ...BASE_REQUEST, status: 'pending_approval' }));
    render(<PurchaseRequestDetail id="1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }));
    const dialog = screen.getByRole('dialog');
    const confirm = within(dialog).getByRole('button', { name: 'Confirm' });
    expect(confirm.disabled).toBe(true);

    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Reason' }), {
      target: { value: 'Budget freeze this quarter' },
    });
    fireEvent.click(confirm);
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/purchase-requests/1/reject/', { reason: 'Budget freeze this quarter' },
    ));
  });

  it('returns a request for correction with a reason', async () => {
    routeGet(detailRoutes({ ...BASE_REQUEST, status: 'pending_approval' }));
    render(<PurchaseRequestDetail id="1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Return for correction' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Reason' }), {
      target: { value: 'Add the vendor quotation' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/purchase-requests/1/return_for_correction/',
      { reason: 'Add the vendor quotation' },
    ));
  });

  it('surfaces a 409 and reloads the record instead of retrying', async () => {
    routeGet(detailRoutes({ ...BASE_REQUEST, status: 'draft' }));
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: {} } });
    render(<PurchaseRequestDetail id="1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Submit for approval' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Submit' }));

    await waitFor(() => expect(screen.getByText(/This request changed while you were working/)).toBeTruthy());
    expect(mockPost).toHaveBeenCalledTimes(1);
  });
});
