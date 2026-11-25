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

import { GoodsReceiptForm } from '../../pages/procurement/GoodsReceiptForm';

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

const ORDER = {
  id: 4,
  po_number: 'PO-2026-00004',
  purchase_request: 1,
  vendor: 3,
  vendor_detail: { id: 3, name: 'Acme Supplies' },
  created_by: 2,
  status: 'sent_to_vendor',
  subtotal: '50000.00',
  tax: '0.00',
  discount: '0.00',
  shipping: '0.00',
  total: '50000.00',
  currency: 'NPR',
  delivery_address: '',
  terms: '',
  notes: '',
  requires_system_admin_approval: false,
  approver: null,
  approval_decision: '',
  created_at: '2026-11-02T10:00:00Z',
  sent_at: '2026-11-03T10:00:00Z',
  updated_at: '2026-11-03T10:00:00Z',
  items: [
    {
      id: 21, item_name: 'Laptop', description: 'i7', quantity: 3, unit_price: '16666.67',
      tax: '0.00', discount: '0.00', total: '50000.01', received_qty: 1,
      rejected_qty: 0, damaged_qty: 0, is_serialized: true, stock_item: null, notes: '',
    },
  ],
  goods_receipts: [],
  history: [],
};

const RECEIPT = {
  id: 7,
  gr_number: 'GR-2026-00007',
  purchase_order: 4,
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
    quantity_rejected: 1, quantity_damaged: 0, notes: 'Rejection reason: dented case',
    created_at: '',
  }],
};

function routeGet() {
  mockGet.mockImplementation((url) => {
    if (String(url) === '/procurement/purchase-orders/4/') return Promise.resolve({ data: ORDER });
    if (String(url) === '/procurement/goods-receipts/7/') return Promise.resolve({ data: RECEIPT });
    if (String(url).startsWith('/procurement/purchase-orders/')) {
      return Promise.resolve({ data: { results: [ORDER], count: 1, next: null } });
    }
    return Promise.resolve({ data: { results: [], count: 0, next: null } });
  });
}

async function openReceiptForm() {
  routeGet();
  render(<GoodsReceiptForm poId="4" />);
  return screen.findByRole('spinbutton', { name: 'received quantity for Laptop' });
}

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  mockAuth.mockReturnValue(makeAuth('it_support'));
  mockPost.mockResolvedValue({ data: { id: 12, gr_number: 'GR-2026-00012' } });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('Goods receipt form', () => {
  it('shows the outstanding balance from the server', async () => {
    await openReceiptForm();
    expect(screen.getByText(/previously accepted 1/)).toBeTruthy();
    expect(screen.getByText(/remaining 2/)).toBeTruthy();
  });

  it('refuses an over-receipt before calling the API', async () => {
    const input = await openReceiptForm();
    fireEvent.change(input, { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review and record receipt' }));
    expect(await screen.findByText(/Only 2 unit\(s\) remain/)).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('requires a reason for rejected units', async () => {
    const input = await openReceiptForm();
    fireEvent.change(input, { target: { value: '2' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'rejected quantity for Laptop' }), {
      target: { value: '1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Review and record receipt' }));
    expect(await screen.findByText('A reason is required for rejected units.')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('requires damage notes for damaged units', async () => {
    const input = await openReceiptForm();
    fireEvent.change(input, { target: { value: '2' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'damaged quantity for Laptop' }), {
      target: { value: '1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Review and record receipt' }));
    expect(await screen.findByText('Describe the damage for damaged units.')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('cannot book rejected plus damaged above the received quantity', async () => {
    const input = await openReceiptForm();
    fireEvent.change(input, { target: { value: '1' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'rejected quantity for Laptop' }), {
      target: { value: '1' },
    });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'damaged quantity for Laptop' }), {
      target: { value: '1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Review and record receipt' }));
    expect(await screen.findByText(/cannot exceed the quantity received/)).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('posts a full receipt and each receipt line', async () => {
    const input = await openReceiptForm();
    fireEvent.change(input, { target: { value: '2' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Delivery note number' }), {
      target: { value: 'DN-9' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Review and record receipt' }));

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/2 accepted, 0 rejected, 0 damaged/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Record receipt' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/goods-receipts/', {
      purchase_order: 4,
      delivery_note_number: 'DN-9',
      invoice_number: '',
      notes: '',
    }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/goods-receipt-items/',
      expect.objectContaining({
        goods_receipt: 12,
        purchase_order_item: 21,
        quantity_received: 2,
        quantity_rejected: 0,
        quantity_damaged: 0,
        accepted_quantity: 2,
      }),
    ));
  });

  it('records a partial receipt with a rejected quantity and notes', async () => {
    const input = await openReceiptForm();
    fireEvent.change(input, { target: { value: '2' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'rejected quantity for Laptop' }), {
      target: { value: '1' },
    });
    fireEvent.change(await screen.findByRole('textbox', { name: 'Rejection reason for Laptop' }), {
      target: { value: 'Dented case' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Review and record receipt' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Record receipt' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/goods-receipt-items/',
      expect.objectContaining({
        quantity_received: 2,
        quantity_rejected: 1,
        quantity_damaged: 0,
        notes: 'Rejection reason: Dented case',
      }),
    ));
  });

  it('reloads balances when the server reports a conflict', async () => {
    const input = await openReceiptForm();
    fireEvent.change(input, { target: { value: '1' } });
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: {} } });
    fireEvent.click(screen.getByRole('button', { name: 'Review and record receipt' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Record receipt' }));

    expect(await screen.findByText(/This order changed while you were working/)).toBeTruthy();
  });

  it('renders a posted receipt with discrepancy follow-up text', async () => {
    routeGet();
    render(<GoodsReceiptForm id="7" />);
    expect(await screen.findByText('GR-2026-00007')).toBeTruthy();
    expect(screen.getByText(/Discrepancy recorded for follow-up/)).toBeTruthy();
    expect(screen.getAllByText(/Rejection reason: dented case/).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Record receipt' })).toBeNull();
  });
});
