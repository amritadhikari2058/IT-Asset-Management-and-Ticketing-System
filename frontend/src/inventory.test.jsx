import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({ useAuth: (...args) => mockAuth(...args) }));

import {
  Inventory, InventoryItems, StockItemForm, StockItemDetail,
} from './inventory';
import {
  ReceiveStock, Reservations, TransactionHistory, FulfilServiceRequest,
} from './inventory-ops';

function staff() {
  mockAuth.mockReturnValue({
    isStaff: true, isAdmin: true,
    user: { id: 1, employee_id: 'E1', role: 'system_admin', email: 'admin@x' },
  });
}

function employee() {
  mockAuth.mockReturnValue({
    isStaff: false, isAdmin: false,
    user: { id: 3, employee_id: 'E3', role: 'employee', email: 'emp@x' },
  });
}

const DASHBOARD = {
  data: {
    total_items: 10, total_units: 100, reserved: 20, low_stock: 3, out_of_stock: 1,
    recent_movements: [
      { id: 1, stock_item_name: 'AA batteries', movement_type: 'receive', quantity: 50,
        reference: 'PO-1', recorded_by_name: 'admin@x', created_at: '2026-01-02T10:00:00Z' },
    ],
  },
};
const ITEMS_PAGE = {
  data: { results: [
    { id: 1, sku: 'AA-001', name: 'AA batteries', category: 'Consumables', unit: 'pcs',
      quantity: 50, reserved: 5, available: 45, reorder_threshold: 10, unit_cost: '0.50',
      is_active: true, is_deleted: false },
    { id: 2, sku: 'USB-002', name: 'USB-C cable', category: 'Consumables', unit: 'pcs',
      quantity: 0, reserved: 0, available: 0, reorder_threshold: 5, unit_cost: null,
      is_active: true, is_deleted: false },
  ], count: 2, next: null, previous: null },
};
const ITEM_1 = {
  data: {
    id: 1, sku: 'AA-001', name: 'AA batteries', description: 'Alkaline', category: 'Consumables',
    unit: 'pcs', quantity: 50, reserved: 5, available: 45, reorder_threshold: 10,
    unit_cost: '0.50', preferred_vendor: null, preferred_vendor_name: null,
    is_active: true, is_deleted: false,
  },
};
const MOVEMENTS = [
  { id: 1, stock_item: 1, movement_type: 'receive', quantity: 50, previous_balance: 0,
    new_balance: 50, reference: 'PO-1', recorded_by_name: 'admin@x',
    created_at: '2026-01-02T10:00:00Z', reason: 'Initial receipt' },
];
const RECEIPTS = {
  data: { results: [
    { id: 7, purchase_reference: 'PO-1', vendor: 1, vendor_name: 'Acme Co.',
      purchase_date: '2026-01-01', total_cost: '250.00', lines: [{ id: 1 }] },
  ], count: 1, next: null, previous: null },
};
const REQUESTS = {
  data: { results: [
    { id: 41, request_number: 'SR-41', catalogue_item_name: 'Laptop request',
      requester_name: 'emp@x', status: 'approved', submitted_at: '2026-01-02T10:00:00Z' },
    { id: 42, request_number: 'SR-42', catalogue_item_name: 'Headset request',
      requester_name: 'emp@x', status: 'fulfilled', submitted_at: '2026-01-01T10:00:00Z' } ],
  count: 2, next: null, previous: null },
};
const VENDORS = { data: { results: [{ id: 1, name: 'Acme Co.' }], count: 1, next: null, previous: null } };
const STOCK_ITEMS = { data: { results: [ITEM_1.data, ITEMS_PAGE.data.results[1]], count: 2, next: null, previous: null } };
const RESERVATIONS = {
  data: { results: [
    { id: 1, stock_item: 1, quantity: 5, status: 'active', service_request: 41,
      created_by_name: 'admin@x', created_at: '2026-01-02T10:00:00Z' },
  ], count: 1, next: null, previous: null },
};

function mockRoutes(routes) {
  mockGet.mockImplementation(async (u) => {
    const url = String(u);
    for (const [prefix, data] of routes) {
      if (url.startsWith(prefix)) return data;
    }
    return { data: { results: [], count: 0, next: null, previous: null } };
  });
}

/** jsdom/React does not drive controlled <select> onChange via target value, so
 *  select an option and dispatch a real change event instead. */
function setSelect(sel, value) {
  const option = Array.from(sel.options).find((o) => o.value === String(value));
  if (option) option.selected = true;
  fireEvent.change(sel);
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '';
  staff();
});
afterEach(() => cleanup());

describe('Inventory dashboard', () => {
  it('renders operational metric cards from the backend dashboard', async () => {
    mockRoutes([
      ['/inventory/stock-items/dashboard/', DASHBOARD],
      ['/inventory/purchase-receipts/', RECEIPTS],
      ['/services/requests/', REQUESTS],
    ]);
    render(<Inventory />);
    expect(await screen.findByText('Total items')).toBeTruthy();
    expect(screen.getByText('10')).toBeTruthy();
    expect(screen.getByText('100')).toBeTruthy(); // on-hand units
    expect(screen.getByText('80')).toBeTruthy(); // 100 units - 20 reserved
    expect(screen.getByText('Reserved')).toBeTruthy();
    expect(screen.getByText('20')).toBeTruthy();
    expect(screen.getByText('Low stock')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.getByText('Out of stock')).toBeTruthy();
    expect(screen.getAllByText('1').length).toBeGreaterThanOrEqual(1);
  });

  it('renders recent movements, receipts and pending fulfilment requests', async () => {
    mockRoutes([
      ['/inventory/stock-items/dashboard/', DASHBOARD],
      ['/inventory/purchase-receipts/', RECEIPTS],
      ['/services/requests/', REQUESTS],
    ]);
    render(<Inventory />);
    await screen.findByText('AA batteries');
    expect(screen.getAllByText('PO-1').length).toBeGreaterThanOrEqual(1);
    await screen.findByText('SR-41');
    expect(screen.getByText('Fulfil a request…')).toBeTruthy();
  });

  it('low-stock card links to the filtered items view', async () => {
    mockRoutes([
      ['/inventory/stock-items/dashboard/', DASHBOARD],
      ['/inventory/purchase-receipts/', RECEIPTS],
      ['/services/requests/', REQUESTS],
    ]);
    render(<Inventory />);
    await screen.findByText('Total items');
    const hrefs = Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('#/inventory/items?low_stock=1');
  });

  it('shows an error state when the dashboard fails', async () => {
    mockGet.mockRejectedValue({ response: { status: 500, data: 'server exploded' } });
    render(<Inventory />);
    await waitFor(() => expect(screen.getByText(/server exploded/)).toBeTruthy());
  });
});

describe('Inventory items list', () => {
  const itemRow = () => within(screen.getByText('AA-001').closest('tr'));

  it('renders stock items with available/reserved quantities and status badges', async () => {
    mockRoutes([['/inventory/stock-items/', ITEMS_PAGE]]);
    render(<InventoryItems />);
    await screen.findByText('AA-001');
    expect(screen.getByText('AA batteries')).toBeTruthy();
    expect(itemRow().getByText('50')).toBeTruthy(); // quantity
    expect(itemRow().getByText('45')).toBeTruthy(); // available
    expect(itemRow().getByText('In stock')).toBeTruthy();
  });

  it('shows out-of-stock badge for zero available stock', async () => {
    mockRoutes([['/inventory/stock-items/', ITEMS_PAGE]]);
    render(<InventoryItems />);
    await screen.findByText('USB-002');
    expect(within(screen.getByText('USB-002').closest('tr')).getByText('Out of stock')).toBeTruthy();
  });

  it('searches by name/SKU', async () => {
    mockRoutes([['/inventory/stock-items/', ITEMS_PAGE]]);
    render(<InventoryItems />);
    const input = screen.getByPlaceholderText(/Name or SKU/);
    fireEvent.change(input, { target: { value: 'USB' } });
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(
      expect.stringContaining('/inventory/stock-items/?q=USB'),
    ));
  });

  it('filters by low stock via the URL', async () => {
    window.location.hash = '#/inventory/items?low_stock=1';
    mockRoutes([['/inventory/stock-items/', ITEMS_PAGE]]);
    render(<InventoryItems />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(
      expect.stringContaining('/inventory/stock-items/?low_stock=1'),
    ));
  });

  it('filters by category via the URL', async () => {
    window.location.hash = '#/inventory/items?category=Consumables';
    mockRoutes([['/inventory/stock-items/', ITEMS_PAGE]]);
    render(<InventoryItems />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(
      expect.stringContaining('/inventory/stock-items/?category=Consumables'),
    ));
  });

  it('filters by category through the select', async () => {
    mockRoutes([['/inventory/stock-items/', ITEMS_PAGE]]);
    render(<InventoryItems />);
    await screen.findByText('AA-001');
    setSelect(screen.getByRole('combobox', { name: /Filter by category/ }), 'Consumables');
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(
      expect.stringContaining('/inventory/stock-items/?category=Consumables'),
    ));
  });

  it('shows empty state when there are no items', async () => {
    mockGet.mockResolvedValue({ data: { results: [], count: 0, next: null, previous: null } });
    render(<InventoryItems />);
    expect(await screen.findByText(/No stock items yet/)).toBeTruthy();
  });

  it('hides item creation from non-staff', async () => {
    employee();
    mockRoutes([['/inventory/stock-items/', ITEMS_PAGE]]);
    render(<InventoryItems />);
    expect(screen.queryByRole('link', { name: /New stock item/ })).toBeNull();
  });
});

describe('Stock item create / edit', () => {
  it('creates a stock item via POST', async () => {
    mockRoutes([['/assets/vendors/', VENDORS]]);
    mockPost.mockResolvedValue({ data: { id: 9 } });
    render(<StockItemForm />);
    fireEvent.change(screen.getByRole('textbox', { name: /Name/ }), { target: { value: 'AA batteries' } });
    fireEvent.change(screen.getByRole('textbox', { name: /SKU/ }), { target: { value: 'AA-009' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: /Quantity/ }), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: /Create item/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/inventory/stock-items/', expect.objectContaining({ name: 'AA batteries', sku: 'AA-009', quantity: 10 })));
  });

  it('reports backend field errors on create', async () => {
    mockRoutes([['/assets/vendors/', VENDORS]]);
    mockPost.mockRejectedValue({ response: { status: 400, data: { sku: ['SKU already exists.'] } } });
    render(<StockItemForm />);
    fireEvent.change(screen.getByRole('textbox', { name: /Name/ }), { target: { value: 'N' } });
    fireEvent.change(screen.getByRole('textbox', { name: /SKU/ }), { target: { value: 'DUP' } });
    fireEvent.click(screen.getByRole('button', { name: /Create item/ }));
    await waitFor(() => expect(screen.getAllByText(/SKU already exists/).length).toBeGreaterThanOrEqual(1));
  });

  it('loads an item and updates it via PATCH', async () => {
    mockRoutes([
      ['/inventory/stock-items/1/', ITEM_1],
      ['/assets/vendors/', VENDORS],
    ]);
    mockPatch.mockResolvedValue({ data: {} });
    render(<StockItemForm id={1} />);
    await waitFor(() => expect(screen.getByRole('textbox', { name: /Name/ }).value).toBe('AA batteries'));
    fireEvent.change(screen.getByRole('textbox', { name: /Name/ }), { target: { value: 'AA batteries updated' } });
    fireEvent.click(screen.getByRole('button', { name: /Update item/ }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/inventory/stock-items/1/', expect.objectContaining({ name: 'AA batteries updated' })));
  });
});

describe('Stock item detail', () => {
  it('renders item detail and movement history', async () => {
    mockRoutes([
      ['/inventory/stock-items/1/', ITEM_1],
      ['/inventory/stock-items/movements/', { data: MOVEMENTS }],
    ]);
    render(<StockItemDetail id={1} />);
    await screen.findByText('AA batteries');
    expect(screen.getByText('In stock')).toBeTruthy();
    expect(screen.getByText('Receive')).toBeTruthy();
  });
});

describe('Stock receiving', () => {
  beforeEach(() => {
    mockRoutes([
      ['/assets/vendors/', VENDORS],
      ['/inventory/stock-items/?page_size=100', STOCK_ITEMS],
    ]);
  });

  it('submits a purchase receipt through the confirmation dialog', async () => {
    mockPost.mockResolvedValue({ data: { id: 3 } });
    render(<ReceiveStock />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/inventory/stock-items/?page_size=100')));
    setSelect(screen.getByRole('combobox', { name: /Vendor/ }), '1');
    setSelect(screen.getAllByRole('combobox', { name: /Stock item/ })[0], '1');
    fireEvent.change(screen.getAllByRole('spinbutton')[0], { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: /Confirm & receive stock/ }));
    await screen.findByRole('button', { name: /Receive stock/ });
    fireEvent.click(screen.getByRole('button', { name: /Receive stock/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/inventory/purchase-receipts/', expect.objectContaining({ vendor: 1 })));
  });

  it('requires at least one line before submitting', async () => {
    mockPost.mockResolvedValue({ data: { id: 3 } });
    render(<ReceiveStock />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/inventory/stock-items/?page_size=100')));
    setSelect(screen.getByRole('combobox', { name: /Vendor/ }), '1');
    fireEvent.click(screen.getByRole('button', { name: /Confirm & receive stock/ }));
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('prevents duplicate submission while a request is in flight', async () => {
    let resolvePost;
    mockPost.mockImplementation(() => new Promise((res) => { resolvePost = res; }));
    render(<ReceiveStock />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/inventory/stock-items/?page_size=100')));
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/assets/vendors/')));
    setSelect(screen.getByRole('combobox', { name: /Vendor/ }), '1');
    setSelect(screen.getAllByRole('combobox', { name: /Stock item/ })[0], '1');
    fireEvent.change(screen.getAllByRole('spinbutton')[0], { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: /Confirm & receive stock/ }));
    await screen.findByRole('button', { name: /Receive stock/ });
    fireEvent.click(screen.getByRole('button', { name: /Receive stock/ }));
    await screen.findByRole('button', { name: /Working/ });
    expect(screen.getByRole('button', { name: /Working/ }).disabled).toBeTruthy();
    resolvePost({ data: { id: 3 } });
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
  });

  it('shows backend validation errors', async () => {
    mockPost.mockRejectedValue({ response: { status: 400, data: { vendor: ['Select a valid vendor.'] } } });
    render(<ReceiveStock />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/inventory/stock-items/?page_size=100')));
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/assets/vendors/')));
    setSelect(screen.getByRole('combobox', { name: /Vendor/ }), '1');
    setSelect(screen.getAllByRole('combobox', { name: /Stock item/ })[0], '1');
    fireEvent.change(screen.getAllByRole('spinbutton')[0], { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: /Confirm & receive stock/ }));
    await screen.findByRole('button', { name: /Receive stock/ });
    fireEvent.click(screen.getByRole('button', { name: /Receive stock/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText(/Select a valid vendor/)).toBeTruthy());
  });
});

describe('Reservations', () => {
  beforeEach(() => {
    mockRoutes([
      ['/inventory/reservations/', RESERVATIONS],
      ['/inventory/stock-items/?page_size=100', STOCK_ITEMS],
      ['/services/requests/?page_size=100', REQUESTS],
    ]);
  });

  it('lists reservations with quantity and status', async () => {
    render(<Reservations />);
    await screen.findByText('SR #41');
    const row = within(screen.getByText('SR #41').closest('tr'));
    expect(row.getByText('5')).toBeTruthy();
    expect(row.getByText('Active')).toBeTruthy();
  });

  it('creates a reservation via POST', async () => {
    mockPost.mockResolvedValue({ data: { id: 2 } });
    render(<Reservations />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/inventory/stock-items/?page_size=100')));
    fireEvent.click(screen.getByRole('button', { name: /\+ Reserve stock/ }));
    await screen.findByLabelText(/Stock item/);
    setSelect(screen.getAllByRole('combobox', { name: /Stock item/ })[0], '1');
    fireEvent.change(screen.getByRole('spinbutton', { name: /Quantity/ }), { target: { value: '3' } });
    setSelect(screen.getAllByRole('combobox', { name: /Service request/ })[0], '41');
    fireEvent.click(screen.getByRole('button', { name: 'Reserve' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/inventory/reservations/', expect.objectContaining({ stock_item: 1, quantity: 3, service_request: 41 })));
  });

  it('rejects invalid reservation quantities', async () => {
    render(<Reservations />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/inventory/stock-items/?page_size=100')));
    fireEvent.click(screen.getByRole('button', { name: /\+ Reserve stock/ }));
    await screen.findByLabelText(/Stock item/);
    setSelect(screen.getAllByRole('combobox', { name: /Stock item/ })[0], '1');
    fireEvent.change(screen.getByRole('spinbutton', { name: /Quantity/ }), { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Reserve' }));
    await waitFor(() => expect(screen.getByText(/positive quantity/)).toBeTruthy());
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('releases a reservation after confirmation', async () => {
    mockPost.mockResolvedValue({ data: {} });
    render(<Reservations />);
    await screen.findByText('SR #41');
    fireEvent.click(screen.getByRole('button', { name: /Release/ }));
    await screen.findByRole('button', { name: 'Release reservation' });
    fireEvent.click(screen.getByRole('button', { name: 'Release reservation' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/inventory/reservations/1/release/'));
  });

  it('fulfils a reservation after confirmation', async () => {
    mockPost.mockResolvedValue({ data: {} });
    render(<Reservations />);
    await screen.findByText('SR #41');
    fireEvent.click(screen.getByRole('button', { name: /Fulfil/ }));
    await screen.findByRole('button', { name: 'Fulfil reservation' });
    fireEvent.click(screen.getByRole('button', { name: 'Fulfil reservation' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/inventory/reservations/1/fulfil/'));
  });

  it('hides reservation creation from non-staff', async () => {
    employee();
    render(<Reservations />);
    expect(screen.queryByRole('button', { name: /\+ Reserve stock/ })).toBeNull();
  });
});

describe('Transaction history', () => {
  it('renders stock movements read-only with type badges', async () => {
    mockRoutes([
      ['/inventory/stock-items/movements/', { data: MOVEMENTS }],
      ['/inventory/stock-items/?page_size=100', STOCK_ITEMS],
    ]);
    render(<TransactionHistory />);
    await screen.findByText('AA batteries');
    const table = screen.getByRole('table');
    expect(within(table).getByText('Receive')).toBeTruthy();
    expect(within(table).getByText('+50')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Edit/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Delete/ })).toBeNull();
  });

  it('filters movements client-side without extra server calls', async () => {
    mockRoutes([
      ['/inventory/stock-items/movements/', { data: MOVEMENTS }],
      ['/inventory/stock-items/?page_size=100', STOCK_ITEMS],
    ]);
    render(<TransactionHistory />);
    await screen.findByText('Receive');
    setSelect(screen.getByRole('combobox', { name: /Filter by movement/ }), 'issue');
    await waitFor(() => expect(screen.getByText(/No stock movements/)).toBeTruthy());
    const calls = mockGet.mock.calls.map((c) => c[0]);
    expect(calls.filter((u) => String(u).startsWith('/inventory/stock-items/movements/'))).toHaveLength(1);
  });
});

describe('Service request fulfilment', () => {
  beforeEach(() => {
    mockRoutes([
      ['/services/requests/', REQUESTS],
      ['/inventory/stock-items/?page_size=100', STOCK_ITEMS],
    ]);
  });

  it('lists requests ready for fulfilment and excludes fulfilled ones', async () => {
    render(<FulfilServiceRequest />);
    await screen.findByText('SR-41');
    expect(screen.queryByText('SR-42')).toBeNull();
  });

  it('fulfils a request from available stock', async () => {
    mockPost.mockResolvedValue({ data: {} });
    render(<FulfilServiceRequest />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/inventory/stock-items/?page_size=100')));
    await screen.findByText('SR-41');
    fireEvent.click(screen.getByRole('button', { name: /Fulfil/ }));
    await screen.findByLabelText(/Stock item/);
    setSelect(screen.getByRole('combobox', { name: /Stock item/ }), '1');
    fireEvent.change(screen.getByRole('spinbutton', { name: /Quantity/ }), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: /Fulfil request/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/inventory/fulfil-service-request/', expect.objectContaining({ service_request: 41, stock_item: 1, quantity: 2 })));
  });

  it('blocks fulfilment above available stock', async () => {
    render(<FulfilServiceRequest />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/inventory/stock-items/?page_size=100')));
    await screen.findByText('SR-41');
    fireEvent.click(screen.getByRole('button', { name: /Fulfil/ }));
    await screen.findByLabelText(/Stock item/);
    setSelect(screen.getByRole('combobox', { name: /Stock item/ }), '1');
    fireEvent.change(screen.getByRole('spinbutton', { name: /Quantity/ }), { target: { value: '999' } });
    fireEvent.click(screen.getByRole('button', { name: /Fulfil request/ }));
    await waitFor(() => expect(screen.getByText(/Only 45 unit\(s\)/)).toBeTruthy());
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('shows backend rejection and disables resubmit while in flight', async () => {
    let rejectPost;
    mockPost.mockImplementation(() => new Promise((_res, rej) => { rejectPost = rej; }));
    render(<FulfilServiceRequest />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/inventory/stock-items/?page_size=100')));
    await screen.findByText('SR-41');
    fireEvent.click(screen.getByRole('button', { name: /Fulfil/ }));
    await screen.findByLabelText(/Stock item/);
    setSelect(screen.getByRole('combobox', { name: /Stock item/ }), '1');
    fireEvent.change(screen.getByRole('spinbutton', { name: /Quantity/ }), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: /Fulfil request/ }));
    const fulfilling = screen.getAllByRole('button', { name: 'Fulfilling…' });
    expect(fulfilling.length).toBeGreaterThanOrEqual(1);
    expect(fulfilling.some((b) => b.disabled)).toBeTruthy();
    rejectPost({ response: { status: 400, data: { detail: 'Already fulfilled' } } });
    await waitFor(() => expect(screen.getByText(/Already fulfilled/)).toBeTruthy());
  });
});
