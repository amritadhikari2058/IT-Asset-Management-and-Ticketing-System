import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({ default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) } }));
vi.mock('../../auth', () => ({ useAuth: (...a) => mockAuth(...a) }));

import { ProcurementReturnsPage, ProcurementReturnForm, ProcurementReturnDetail } from '../../pages/procurement/ProcurementReturns';

function authUser(role, id = 1) {
  return {
    access: 'token',
    role,
    user: { id, role },
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isSuperuser: false,
  };
}

const vendorReturn = {
  id: 1, return_number: 'VR-1', vendor_name: 'Acme', po_number: 'PO-1', goods_receipt: 9, supplier_invoice: 4,
  status: 'draft', reason: 'damaged', return_method: 'physical_return', authorization_reference: 'AUTH-1',
  created_by: 2, lines: [], version: 1,
};

function mockReturnLoad(overrides = {}) {
  const vr = { ...vendorReturn, ...overrides };
  mockGet.mockImplementation((url) => {
    if (url === '/procurement/vendor-returns/1/') return Promise.resolve({ data: vr });
    return Promise.resolve({ data: { results: [] } });
  });
}

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  window.prompt = vi.fn(() => null);
  mockAuth.mockReturnValue(authUser('it_manager'));
  mockReturnLoad();
  mockPost.mockResolvedValue({ data: {} });
});
afterEach(() => cleanup());

describe('P3 vendor returns list', () => {
  it('renders the loading state and rows from the exact endpoint', async () => {
    mockGet.mockImplementation((url) => {
      if (url === '/procurement/vendor-returns/?page_size=50') {
        return Promise.resolve({ data: { results: [{ id: 1, return_number: 'VR-1', vendor_name: 'Acme', po_number: 'PO-1', status: 'draft', reason: 'damaged', return_method: 'physical_return' }] } });
      }
      return Promise.resolve({ data: { results: [] } });
    });
    render(<ProcurementReturnsPage />);
    expect(screen.getByRole('status').textContent).toMatch(/Loading vendor returns/);
    expect(await screen.findByText('VR-1')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'VR-1' }).getAttribute('href')).toBe('#/procurement/returns/1');
    expect(mockGet).toHaveBeenCalledWith('/procurement/vendor-returns/?page_size=50');
  });

  it('shows an empty state', async () => {
    render(<ProcurementReturnsPage />);
    expect(await screen.findByText('No vendor returns.')).toBeTruthy();
  });

  it('shows a standardized error with Retry', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 403, data: {} } });
    render(<ProcurementReturnsPage />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/You do not have permission/);
    mockGet.mockResolvedValueOnce({ data: { results: [{ id: 2, return_number: 'VR-2', status: 'approved' }] } });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('VR-2')).toBeTruthy();
  });
});

describe('P3 vendor return create', () => {
  async function fillForm() {
    render(<ProcurementReturnForm />);
    fireEvent.change(screen.getByLabelText(/Vendor ID/i), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText(/Purchase Order ID/i), { target: { value: '5' } });
    fireEvent.change(screen.getByLabelText(/Return Date/i), { target: { value: '2026-11-12' } });
  }

  it('posts the exact payload and uses the returned id', async () => {
    mockPost.mockResolvedValue({ data: { id: 3 } });
    await fillForm();
    fireEvent.click(screen.getByRole('button', { name: /Create Return/i }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/vendor-returns/', expect.any(Object)));
    expect(mockPost.mock.calls[0][1]).toMatchObject({
      vendor: '2', purchase_order: '5', reason: 'damaged', return_method: 'physical_return',
      goods_receipt: null, supplier_invoice: null, replacement_due_date: null, return_date: '2026-11-12',
    });
    await waitFor(() => expect(window.location.hash).toBe('#/procurement/returns/3'));
  });

  it('does not navigate when the returned id is missing', async () => {
    window.location.hash = '#/procurement/returns/new';
    mockPost.mockResolvedValue({ data: {} });
    await fillForm();
    fireEvent.click(screen.getByRole('button', { name: /Create Return/i }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/did not return the new return id/);
    expect(window.location.hash).toBe('#/procurement/returns/new');
  });

  it('renders 400 field errors readably', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { quantity: ['Return quantity exceeds eligible quantity.'] } } });
    await fillForm();
    fireEvent.click(screen.getByRole('button', { name: /Create Return/i }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('Return quantity exceeds eligible quantity.')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).not.toMatch(/[{}]/);
  });
});

describe('P3 vendor return actions', () => {
  it('shows approval controls to a non-creator manager for a pending return', async () => {
    mockReturnLoad({ status: 'pending_approval' });
    render(<ProcurementReturnDetail id={1} />);
    expect(await screen.findByText(/Return VR-1/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Ship' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Complete' })).toBeNull();
    expect(screen.getByText(/does not automatically create a refund; credit notes are tracked separately\./)).toBeTruthy();
  });

  it('hides approval from IT Support and issues no privileged request', async () => {
    mockAuth.mockReturnValue(authUser('it_support', 3));
    mockReturnLoad({ status: 'pending_approval' });
    render(<ProcurementReturnDetail id={1} />);
    expect(await screen.findByText(/Return VR-1/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Ship' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('never offers self-approval to the creator, except a System Admin', async () => {
    mockAuth.mockReturnValue(authUser('it_manager', 2));
    mockReturnLoad({ status: 'pending_approval' });
    render(<ProcurementReturnDetail id={1} />);
    expect(await screen.findByText(/Return VR-1/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    cleanup();

    mockAuth.mockReturnValue(authUser('system_admin', 2));
    mockReturnLoad({ status: 'pending_approval' });
    render(<ProcurementReturnDetail id={1} />);
    expect(await screen.findByText(/Return VR-1/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
  });

  it('posts approval with the authorization reference', async () => {
    window.prompt = vi.fn(() => 'AUTH-NEW');
    mockReturnLoad({ status: 'pending_approval' });
    render(<ProcurementReturnDetail id={1} />);
    await screen.findByText(/Return VR-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/vendor-returns/1/approve/',
      { authorization_reference: 'AUTH-NEW' },
    ));
  });

  it('posts ship, complete and cancel to their exact endpoints', async () => {
    mockReturnLoad({ status: 'approved' });
    render(<ProcurementReturnDetail id={1} />);
    await screen.findByText(/Return VR-1/);
    window.prompt = vi.fn(() => 'SHIP-1');
    fireEvent.click(screen.getByRole('button', { name: 'Ship' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/vendor-returns/1/ship/', { shipping_reference: 'SHIP-1' }));
    cleanup();

    mockReturnLoad({ status: 'shipped' });
    render(<ProcurementReturnDetail id={1} />);
    await screen.findByText(/Return VR-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Complete' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/vendor-returns/1/complete/', {}));
    cleanup();

    window.prompt = vi.fn(() => 'No longer needed');
    mockReturnLoad({ status: 'pending_approval' });
    render(<ProcurementReturnDetail id={1} />);
    await screen.findByText(/Return VR-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/vendor-returns/1/cancel/', { reason: 'No longer needed' }));
  });

  it('adds a return line through the exact endpoint while draft', async () => {
    mockReturnLoad({ status: 'draft' });
    render(<ProcurementReturnDetail id={1} />);
    await screen.findByText(/Return VR-1/);
    fireEvent.change(screen.getByLabelText(/Goods Receipt Item ID/i), { target: { value: '11' } });
    fireEvent.change(screen.getByLabelText(/Purchase Order Item ID/i), { target: { value: '5' } });
    fireEvent.change(screen.getByLabelText(/^Quantity$/i), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add Line' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/vendor-return-lines/', expect.any(Object)));
    expect(mockPost.mock.calls[0][1]).toMatchObject({ vendor_return: 1, goods_receipt_item: '11', purchase_order_item: '5', quantity: '2' });
  });

  it('reloads exactly once on a 409 conflict without retrying the action', async () => {
    mockReturnLoad({ status: 'draft' });
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: {} } });
    render(<ProcurementReturnDetail id={1} />);
    await screen.findByText(/Return VR-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByText(/This return changed while you were working\. The latest version has been loaded\./)).toBeTruthy();
    await waitFor(() => {
      const loads = mockGet.mock.calls.filter(([url]) => url === '/procurement/vendor-returns/1/');
      expect(loads.length).toBe(2);
    });
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it('surfaces backend blockers on submit as a clear message', async () => {
    mockReturnLoad({ status: 'draft' });
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { detail: 'At least one return line is required.' } } });
    render(<ProcurementReturnDetail id={1} />);
    await screen.findByText(/Return VR-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByText('At least one return line is required.')).toBeTruthy();
  });
});
