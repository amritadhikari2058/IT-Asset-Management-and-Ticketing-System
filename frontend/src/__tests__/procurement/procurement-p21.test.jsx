import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  render, screen, fireEvent, cleanup, waitFor, within,
} from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock('../../auth', () => ({ useAuth: (...a) => mockAuth(...a) }));

import { ProcurementAttachments } from '../../pages/procurement/ProcurementAttachments';
import { ProcurementAssetsPage } from '../../pages/procurement/ProcurementAssets';
import { ProcurementDashboard } from '../../pages/procurement/ProcurementDashboard';
import { GoodsReceiptForm } from '../../pages/procurement/GoodsReceiptForm';
import { PurchaseOrderDetail } from '../../pages/procurement/PurchaseOrderDetail';
import { PurchaseOrdersPage } from '../../pages/procurement/PurchaseOrders';
import { PurchaseRequestDetail } from '../../pages/procurement/PurchaseRequestDetail';

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

const PR = {
  id: 1, pr_number: 'PR-2026-00001', requester: 2, requester_name: 'r@x',
  department: null, status: 'draft', reason: 'Laptops', notes: '',
  estimated_total: '100.00', requires_system_admin_approval: false,
  approver: null, approver_name: null, approval_decision: '', approval_reason: '',
  approved_at: null, version: 3, purchase_order_ref: null,
  created_at: '2026-11-01T10:00:00Z', updated_at: '2026-11-02T10:00:00Z',
  items: [], quotations: [], history: [],
};

const PO = {
  id: 4, po_number: 'PO-2026-00004', purchase_request: 1,
  purchase_request_number: 'PR-2026-00001', vendor: 3,
  vendor_detail: { id: 3, name: 'Acme Supplies' }, created_by: 2,
  status: 'sent_to_vendor', subtotal: '100.00', tax: '0.00', discount: '0.00',
  shipping: '0.00', total: '100.00', currency: 'NPR',
  delivery_address: 'HQ', terms: 'Net 30', notes: '', version: 4,
  requires_system_admin_approval: false, approver: null, approver_name: null,
  approval_decision: '', approval_reason: '', approved_at: null, sent_at: null,
  completed_at: null, closed_at: null, closure_reason: '', cancellation_reason: '',
  expected_delivery_date: null,
  created_at: '2026-11-02T10:00:00Z', updated_at: '2026-11-02T10:00:00Z',
  items: [{
    id: 21, item_name: 'Laptop', description: '', quantity: 2,
    unit_price: '50.00', tax: '0.00', discount: '0.00', total: '100.00',
    received_qty: 0, rejected_qty: 0, damaged_qty: 0, is_serialized: false,
    stock_item: null, notes: '',
  }],
  goods_receipts: [], history: [],
};

const DASHBOARD = {
  purchase_requests: { draft: 1, pending_manager_approval: 0, pending_system_admin_approval: 0, approved: 0, rejected: 0, returned_for_correction: 0 },
  quotations: { awaiting_collection: 0, awaiting_selection: 0, selected: 0 },
  purchase_orders: { draft: 0, pending_approval: 0, approved: 0, sent_to_vendor: 0, partially_received: 0, fully_received: 0, overdue_delivery: 0, closed: 0, cancelled: 0 },
  goods_receipts: { recent: 0, with_rejections: 0, with_damage: 0, with_short_delivery: 0 },
  asset_registration: { pending: 0, completed: 0 },
  values_by_currency: [],
  recent_purchase_requests: [], recent_purchase_orders: [],
  upcoming_deliveries: [], overdue_deliveries: [], recent_receipts: [],
  pending_asset_registration: [], receipt_discrepancies: [],
};

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  mockAuth.mockReturnValue(makeAuth('it_manager'));
  mockPost.mockResolvedValue({ data: {} });
  mockGet.mockResolvedValue(page([]));
  window.URL.createObjectURL = vi.fn(() => 'blob:mock');
  window.URL.revokeObjectURL = vi.fn();
});

afterEach(() => cleanup());

describe('Dashboard aggregate endpoint', () => {
  it('sends server filter query parameters', async () => {
    mockGet.mockResolvedValue({ data: DASHBOARD });
    render(<ProcurementDashboard />);
    await screen.findByText('Pending request approval');

    fireEvent.change(screen.getByLabelText('Created from'), {
      target: { value: '2026-01-01' },
    });
    await waitFor(() => {
      const urls = mockGet.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.startsWith('/procurement/dashboard/')
        && u.includes('date_from=2026-01-01'))).toBe(true);
    });
  });
});

describe('Purchase request cancellation', () => {
  it('posts a reason and the expected version', async () => {
    mockGet.mockImplementation((url) => {
      if (String(url) === '/procurement/purchase-requests/1/') {
        return Promise.resolve({ data: PR });
      }
      return Promise.resolve(page([]));
    });
    render(<PurchaseRequestDetail id="1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Cancel request' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Cancellation reason'), {
      target: { value: 'No longer required' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel request' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/purchase-requests/1/cancel/',
      { reason: 'No longer required', version: 3 },
    ));
  });
});

describe('Purchase order documents and closure', () => {
  const orderRoutes = (order = PO) => (url) => {
    const text = String(url);
    if (text === '/procurement/purchase-orders/4/') return Promise.resolve({ data: order });
    if (text.endsWith('/pdf/')) {
      return Promise.resolve({
        data: new Blob(['pdf'], { type: 'application/pdf' }),
        headers: { 'content-disposition': 'attachment; filename="PO-2026-00004.pdf"' },
      });
    }
    return Promise.resolve(page([]));
  };

  it('downloads the PDF as an authenticated blob and revokes the object URL', async () => {
    mockGet.mockImplementation(orderRoutes());
    render(<PurchaseOrderDetail id="4" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Download PDF' }));
    await waitFor(() => expect(window.URL.createObjectURL).toHaveBeenCalled());
    expect(window.URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock');
    const urls = mockGet.mock.calls.map((c) => String(c[0]));
    expect(urls).toContain('/procurement/purchase-orders/4/pdf/');
    expect(urls.some((u) => u.includes('token='))).toBe(false);
  });

  it('closes an order with a reason and expected version', async () => {
    mockGet.mockImplementation(orderRoutes({ ...PO, status: 'partially_received' }));
    render(<PurchaseOrderDetail id="4" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Close order' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Closure reason'), {
      target: { value: 'Vendor cannot supply the remainder' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close order' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/purchase-orders/4/close/',
      { reason: 'Vendor cannot supply the remainder', version: 4 },
    ));
  });

  it('does not expose direct purchase order creation', async () => {
    mockGet.mockResolvedValue(page([PO]));
    render(<PurchaseOrdersPage />);
    await screen.findByText('PO-2026-00004');
    expect(screen.queryByRole('link', { name: /new order/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /create order/i })).toBeNull();
  });
});

describe('Protected attachments', () => {
  const ATTACHMENT = {
    id: 5, purchase_request: 1, document_type: 'specification',
    original_filename: 'spec.pdf', description: 'Spec', status: 'active',
    uploaded_by_name: 'manager@x', created_at: '2026-11-02T10:00:00Z',
  };

  it('downloads through the protected endpoint as a blob and revokes the URL', async () => {
    mockGet.mockImplementation((url) => {
      if (String(url).includes('/download/')) {
        return Promise.resolve({
          data: new Blob(['x'], { type: 'application/pdf' }),
          headers: { 'content-disposition': 'attachment; filename="spec.pdf"' },
        });
      }
      return Promise.resolve(page([ATTACHMENT]));
    });
    render(<ProcurementAttachments parentType="purchase_request" parentId={1} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Download' }));
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(
      '/procurement/attachments/5/download/', { responseType: 'blob' },
    ));
    expect(window.URL.revokeObjectURL).toHaveBeenCalled();
  });

  it('uploads with the parent and file in a multipart body', async () => {
    mockGet.mockResolvedValue(page([]));
    render(
      <ProcurementAttachments parentType="purchase_request" parentId={1} canUpload />,
    );
    fireEvent.change(await screen.findByLabelText('Attachment file'), {
      target: { files: [new File(['spec'], 'spec.pdf', { type: 'application/pdf' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Upload attachment' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/attachments/', expect.any(FormData),
    ));
    const body = mockPost.mock.calls[0][1];
    expect(body.get('purchase_request')).toBe('1');
    expect(body.get('file').name).toBe('spec.pdf');
  });
});

describe('Structured receipt discrepancies', () => {
  it('shows accepted quantity and structured reasons', async () => {
    const receipt = {
      id: 7, gr_number: 'GR-2026-00007', purchase_order: 4,
      received_by_name: 'support@x', received_at: '2026-11-05T09:00:00Z',
      delivery_note_number: 'DN-1', invoice_number: 'INV-1', notes: '',
      items: [{
        id: 31, goods_receipt: 7, purchase_order_item: 21,
        quantity_received: 3, quantity_rejected: 1, quantity_damaged: 1,
        accepted_quantity: 1, rejection_reason: 'Dented case',
        damage_notes: 'Screen cracked', discrepancy_status: 'mixed',
        inspection_status: 'failed', notes: '',
      }],
    };
    mockGet.mockImplementation((url) => {
      const text = String(url);
      if (text === '/procurement/goods-receipts/7/') return Promise.resolve({ data: receipt });
      if (text === '/procurement/purchase-orders/4/') return Promise.resolve({ data: PO });
      return Promise.resolve(page([]));
    });
    render(<GoodsReceiptForm id="7" />);

    expect(await screen.findByText('GR-2026-00007')).toBeTruthy();
    expect(screen.getAllByText('Dented case').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Screen cracked').length).toBeGreaterThan(0);
    const row = screen.getByText('Dented case').closest('tr');
    expect(row.textContent).toContain('1');
  });
});

describe('Receipt-to-asset registration', () => {
  const ITEM = {
    id: 9, goods_receipt: 7, gr_number: 'GR-2026-00007',
    purchase_order: 4, po_number: 'PO-2026-00004',
    purchase_order_item: 21, item_name: 'Laptop', vendor_name: 'Acme Supplies',
    sequence: 1, status: 'pending_registration', purchase_cost: '50.00',
    expected_purchase_date: '2026-11-05', asset_category: 2, asset: null,
  };

  it('registers through the atomic receipt-item endpoint', async () => {
    mockGet.mockImplementation((url) => {
      const text = String(url);
      if (text.startsWith('/procurement/asset-receipt-items/')) return Promise.resolve(page([ITEM]));
      if (text.startsWith('/assets/categories/')) {
        return Promise.resolve(page([{ id: 2, name: 'Laptop', is_active: true }]));
      }
      return Promise.resolve(page([]));
    });
    mockPost.mockResolvedValue({ data: { ...ITEM, status: 'registered', asset: 99, asset_tag: 'AT-1' } });
    render(<ProcurementAssetsPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Register asset' }));
    fireEvent.change(screen.getByLabelText('Asset tag'), { target: { value: 'AT-1' } });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Register asset' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/asset-receipt-items/9/register-asset/',
      expect.objectContaining({ asset_tag: 'AT-1', name: 'Laptop', category: 2 }),
    ));
    expect(mockPost.mock.calls.every((c) => !String(c[0]).startsWith('/assets/'))).toBe(true);
  });
});
