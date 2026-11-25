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

import { PurchaseOrdersPage } from '../../pages/procurement/PurchaseOrders';

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
  items: [],
  goods_receipts: [],
  history: [],
};

function makeAuth(role = 'it_manager') {
  return {
    access: 'token',
    role,
    user: { id: 1, email: `${role}@x`, role, is_active: true },
    isStaff: true,
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isManagerOrAdmin: ['system_admin', 'it_manager'].includes(role),
  };
}

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  localStorage.clear();
  mockAuth.mockReturnValue(makeAuth('it_manager'));
  mockGet.mockImplementation((url) => {
    if (String(url).includes('/procurement/purchase-orders/')) {
      return Promise.resolve({ data: { results: [PO], count: 45, next: null, previous: null } });
    }
    return Promise.resolve({ data: { results: [], count: 0 } });
  });
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('PurchaseOrdersPage reliability', () => {
  it('renders the initial list', async () => {
    render(<PurchaseOrdersPage />);
    expect(await screen.findByText('PO-2026-00004')).toBeTruthy();
    expect(screen.getByText('Acme Supplies')).toBeTruthy();
  });

  it('uses the default page size of 20 when nothing is saved', async () => {
    render(<PurchaseOrdersPage />);
    await screen.findByText('PO-2026-00004');
    expect(mockGet.mock.calls.some((c) => String(c[0]).includes('page_size=20'))).toBe(true);
  });

  it('uses a saved page size on initial render', async () => {
    localStorage.setItem('itdesk.pageSize', '25');
    render(<PurchaseOrdersPage />);
    await screen.findByText('PO-2026-00004');
    expect(mockGet.mock.calls.some((c) => String(c[0]).includes('page_size=25'))).toBe(true);
  });

  it('changes page size and reloads with page 1', async () => {
    render(<PurchaseOrdersPage />);
    await screen.findByText('PO-2026-00004');
    const select = screen.getByLabelText('Rows per page');
    fireEvent.change(select, { target: { value: '50' } });
    await waitFor(() => {
      expect(mockGet.mock.calls.some((c) => String(c[0]).includes('page_size=50'))).toBe(true);
    });
    expect(screen.getByText(/Page 1 of/)).toBeTruthy();
  });

  it('paginates after a page size change', async () => {
    render(<PurchaseOrdersPage />);
    await screen.findByText('PO-2026-00004');
    const select = screen.getByLabelText('Rows per page');
    fireEvent.change(select, { target: { value: '10' } });
    await waitFor(() => {
      expect(mockGet.mock.calls.some((c) => String(c[0]).includes('page_size=10'))).toBe(true);
    });
    // 45 items / 10 = 5 pages, so next is enabled
    const next = screen.getByRole('button', { name: /Next/ });
    expect(next.disabled).toBe(false);
    fireEvent.click(next);
    await waitFor(() => {
      expect(mockGet.mock.calls.some((c) => String(c[0]).includes('page=2') && String(c[0]).includes('page_size=10'))).toBe(true);
    });
  });

  it('unmounts and remounts without crashing', async () => {
    const { unmount } = render(<PurchaseOrdersPage />);
    await screen.findByText('PO-2026-00004');
    unmount();
    render(<PurchaseOrdersPage />);
    expect(await screen.findByText('PO-2026-00004')).toBeTruthy();
  });

  it('falls back to the default page size when localStorage throws', async () => {
    const throwingStorage = {
      getItem: () => { throw new Error('boom'); },
      setItem: () => {},
      removeItem: () => {},
      clear: () => {},
    };
    const original = window.localStorage;
    Object.defineProperty(window, 'localStorage', { value: throwingStorage, configurable: true });
    render(<PurchaseOrdersPage />);
    await screen.findByText('PO-2026-00004');
    expect(mockGet.mock.calls.some((c) => String(c[0]).includes('page_size=20'))).toBe(true);
    Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
  });
});
