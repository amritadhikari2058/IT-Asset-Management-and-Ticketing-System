import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

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

import { GoodsReceiptsPage } from '../../pages/procurement/GoodsReceipts';
import { ProcurementDashboard, ProcurementReports } from '../../pages/procurement/ProcurementDashboard';
import { PurchaseOrdersPage } from '../../pages/procurement/PurchaseOrders';
import { PurchaseRequestsPage } from '../../pages/procurement/PurchaseRequests';

const STAFF_ROLES = ['system_admin', 'it_manager', 'it_support'];

function makeAuth(role, extra = {}) {
  return {
    access: 'token',
    role,
    user: role ? { id: 1, email: `${role}@x`, role } : null,
    isStaff: STAFF_ROLES.includes(role),
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isManagerOrAdmin: ['system_admin', 'it_manager'].includes(role),
    ...extra,
  };
}

function page(results = []) {
  return { data: { results, count: results.length, next: null, previous: null } };
}

const PR = {
  id: 1,
  pr_number: 'PR-2026-00001',
  requester: 2,
  requester_name: 'requester@x',
  department: null,
  status: 'pending_approval',
  reason: 'Replacement laptops for the support desk',
  notes: '',
  estimated_total: '150000.00',
  requires_system_admin_approval: false,
  approver: null,
  approver_name: null,
  approval_decision: '',
  approval_reason: '',
  approved_at: null,
  created_at: '2026-11-01T10:00:00Z',
  updated_at: '2026-11-02T10:00:00Z',
  items: [
    {
      id: 11, item_name: 'Laptop', description: 'i7', quantity: 2,
      estimated_unit_price: '75000.00', estimated_total: '150000.00',
      suggested_vendor: null, notes: '',
    },
  ],
  quotations: [],
  history: [],
};

const PO = {
  id: 4,
  po_number: 'PO-2026-00004',
  purchase_request: 1,
  vendor: 3,
  vendor_detail: { id: 3, name: 'Acme Supplies' },
  created_by: 2,
  status: 'pending_approval',
  subtotal: '100000.00',
  tax: '13000.00',
  discount: '0.00',
  shipping: '0.00',
  total: '113000.00',
  currency: 'NPR',
  delivery_address: 'Head office',
  terms: 'Net 30',
  notes: '',
  requires_system_admin_approval: false,
  approver: null,
  approver_name: null,
  approval_decision: '',
  approval_reason: '',
  approved_at: null,
  sent_at: null,
  completed_at: null,
  created_at: '2026-11-02T10:00:00Z',
  updated_at: '2026-11-02T10:00:00Z',
  items: [{
    id: 21, item_name: 'Laptop', description: 'i7', quantity: 2, unit_price: '50000.00',
    tax: '13000.00', discount: '0.00', total: '113000.00', received_qty: 0,
    rejected_qty: 0, damaged_qty: 0, is_serialized: false, stock_item: null, notes: '',
  }],
  goods_receipts: [],
  history: [],
};

const GR = {
  id: 7,
  gr_number: 'GR-2026-00007',
  purchase_order: 4,
  purchase_order_number: 'PO-2026-00004',
  vendor_name: 'Acme Supplies',
  delivery_note_number: 'DN-1',
  invoice_number: 'INV-1',
  received_by: 1,
  received_by_name: 'staff@x',
  received_at: '2026-11-05T09:00:00Z',
  notes: '',
  created_at: '2026-11-05T09:00:00Z',
  updated_at: '2026-11-05T09:00:00Z',
  items: [{
    id: 31, goods_receipt: 7, purchase_order_item: 21, quantity_received: 2,
    quantity_rejected: 1, quantity_damaged: 0, notes: 'Rejection reason: dented', created_at: '',
  }],
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
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

const DASHBOARD = {
  purchase_requests: {
    draft: 1, pending_manager_approval: 1, pending_system_admin_approval: 0,
    approved: 0, rejected: 0, returned_for_correction: 0,
  },
  quotations: { awaiting_collection: 0, awaiting_selection: 0, selected: 0 },
  purchase_orders: {
    draft: 0, pending_approval: 1, approved: 0, sent_to_vendor: 0,
    partially_received: 0, fully_received: 0, overdue_delivery: 0,
    closed: 0, cancelled: 0,
  },
  goods_receipts: { recent: 1, with_rejections: 1, with_damage: 0, with_short_delivery: 0 },
  asset_registration: { pending: 0, completed: 0 },
  values_by_currency: [{
    currency: 'NPR', ordered_total: '113000.00',
    received_total: '0.00', outstanding_total: '113000.00',
  }],
  recent_purchase_requests: [PR],
  recent_purchase_orders: [PO],
  upcoming_deliveries: [],
  overdue_deliveries: [],
  recent_receipts: [GR],
  pending_asset_registration: [],
  receipt_discrepancies: [],
};

describe('Procurement dashboard', () => {
  it('renders KPIs and recent records from the aggregate endpoint', async () => {
    routeGet({ '/procurement/dashboard/': { data: DASHBOARD } });
    render(<ProcurementDashboard />);

    expect(await screen.findByText('Pending request approval')).toBeTruthy();
    expect((await screen.findAllByText('PR-2026-00001')).length).toBeGreaterThan(0);
    expect(screen.getByText('PO-2026-00004')).toBeTruthy();
    expect((await screen.findAllByText('GR-2026-00007')).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/NPR 113,000\.00/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Currencies are never combined/)).toBeTruthy();
    expect(screen.getByText(/Last refreshed/)).toBeTruthy();
    const urls = mockGet.mock.calls.map((c) => c[0]);
    expect(urls.every((u) => u.startsWith('/procurement/'))).toBe(true);
    expect(urls.some((u) => u.startsWith('/procurement/dashboard/'))).toBe(true);
    expect(urls.some((u) => u.includes('/api/api/'))).toBe(false);
  });

  it('shows an error with Retry when the API fails', async () => {
    mockGet.mockRejectedValue({ response: { status: 500, data: {} } });
    render(<ProcurementDashboard />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  });

  it('hides procurement from employees without calling the API', async () => {
    mockAuth.mockReturnValue(makeAuth('employee'));
    render(<ProcurementDashboard />);
    expect(await screen.findByText('Procurement is not available to your role')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('restricts reports to managers', async () => {
    mockAuth.mockReturnValue(makeAuth('it_support'));
    render(<ProcurementReports />);
    expect(await screen.findByText('Reports are restricted')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });
});

describe('Purchase request list', () => {
  it('renders requests with status and filters', async () => {
    routeGet({
      '/procurement/purchase-requests/': page([PR]),
      '/procurement/purchase-orders/': page([]),
    });
    render(<PurchaseRequestsPage />);

    expect(await screen.findByText('PR-2026-00001')).toBeTruthy();
    expect(screen.getAllByText('Pending approval').length).toBeGreaterThan(0);
    expect(screen.getByText('150,000.00')).toBeTruthy();

    mockGet.mockResolvedValue(page([]));
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'nothing-matches' } });
    await waitFor(() => expect(screen.getByText('No purchase requests match these filters.')).toBeTruthy());
    const urls = mockGet.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes('search=nothing-matches'))).toBe(true);
  });

  it('shows an empty state when there are no requests', async () => {
    routeGet({ '/procurement/purchase-requests/': page([]) });
    render(<PurchaseRequestsPage />);
    expect(await screen.findByText('No purchase requests match these filters.')).toBeTruthy();
  });
});

describe('Purchase order list', () => {
  it('lists orders with vendor and total, and shows approval actions for managers', async () => {
    routeGet({
      '/procurement/purchase-orders/': page([PO]),
      '/procurement/purchase-requests/': page([PR]),
    });
    render(<PurchaseOrdersPage />);

    expect(await screen.findByText('PO-2026-00004')).toBeTruthy();
    expect(screen.getAllByText('Acme Supplies').length).toBeGreaterThan(0);
    expect(screen.getByText('NPR 113,000.00')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
  });

  it('does not expose approval to IT Support', async () => {
    mockAuth.mockReturnValue(makeAuth('it_support'));
    routeGet({
      '/procurement/purchase-orders/': page([PO]),
      '/procurement/purchase-requests/': page([PR]),
    });
    render(<PurchaseOrdersPage />);
    expect(await screen.findByText('PO-2026-00004')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
  });

  it('navigates to a receipt draft from an approved order', async () => {
    routeGet({
      '/procurement/purchase-orders/': page([{ ...PO, status: 'approved' }]),
      '/procurement/purchase-requests/': page([PR]),
    });
    render(<PurchaseOrdersPage />);
    const link = await screen.findByRole('link', { name: 'Create receipt' });
    expect(link.getAttribute('href')).toBe('#/procurement/receipts/new?po=4');
  });
});

describe('Goods receipt list', () => {
  it('lists receipts with accepted, rejected and damaged totals', async () => {
    routeGet({
      '/procurement/goods-receipts/': page([GR]),
      '/procurement/purchase-orders/': page([PO]),
    });
    render(<GoodsReceiptsPage />);

    expect(await screen.findByText('GR-2026-00007')).toBeTruthy();
    expect(screen.getByText('PO-2026-00004')).toBeTruthy();
    expect(screen.getByText('Acme Supplies')).toBeTruthy();
    const row = screen.getByText('GR-2026-00007').closest('tr');
    expect(row.textContent).toContain('1');
  });

  it('reports load failures with a Retry control', async () => {
    mockGet.mockRejectedValue({ response: { status: 500, data: {} } });
    render(<GoodsReceiptsPage />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy());
  });
});
