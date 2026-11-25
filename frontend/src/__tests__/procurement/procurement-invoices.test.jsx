import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
  },
}));
vi.mock('../../auth', () => ({ useAuth: (...a) => mockAuth(...a) }));

import { ProcurementInvoicesPage, ProcurementInvoiceExceptionsPage } from '../../pages/procurement/ProcurementInvoices';
import { ProcurementInvoiceForm } from '../../pages/procurement/ProcurementInvoiceForm';
import { ProcurementInvoiceDetail } from '../../pages/procurement/ProcurementInvoiceDetail';

function authUser(role, id = 1, overrides = {}) {
  return {
    access: 'token',
    role,
    user: { id, role, ...overrides },
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isSuperuser: false,
  };
}

const invoice = {
  id: 1, invoice_number: 'INV-1', vendor_name: 'Acme', po_number: 'PO-1', purchase_order: 5,
  invoice_date: '2026-11-01', due_date: null, currency: 'NPR', status: 'draft', payment_status: 'not_ready',
  subtotal: '100.00', grand_total: '100.00', variance_total: '0.00', payment_hold: false, payment_hold_reason: '',
  latest_match: null, lines: [], version: 2, created_by: 2,
};

function mockInvoiceLoad(overrides = {}) {
  const inv = { ...invoice, ...overrides };
  mockGet.mockImplementation((url) => {
    if (url === '/procurement/supplier-invoices/1/') return Promise.resolve({ data: inv });
    if (url === '/procurement/supplier-invoices/1/readiness/') {
      return Promise.resolve({ data: overrides.readiness || { ready: false, blockers: [{ code: 'NOT_MATCHED', message: 'Match required', severity: 'high' }] } });
    }
    if (url.startsWith('/procurement/purchase-order-items/')) return Promise.resolve({ data: { results: [] } });
    if (url.startsWith('/procurement/goods-receipt-items/')) return Promise.resolve({ data: { results: [] } });
    if (url === '/procurement/supplier-invoices/?page_size=50') return Promise.resolve({ data: { results: [] } });
    return Promise.resolve({ data: { results: [] } });
  });
}

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  window.location.hash = '#/procurement/invoices';
  window.prompt = vi.fn(() => null);
  mockAuth.mockReturnValue(authUser('it_manager'));
  mockInvoiceLoad();
  mockPost.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('P3 invoice list', () => {
  it('renders the loading state then invoices from the exact endpoint', async () => {
    mockGet.mockImplementation((url) => {
      if (url === '/procurement/supplier-invoices/?page_size=50') {
        return Promise.resolve({ data: { results: [{
          id: 1, invoice_number: 'INV-1', vendor_name: 'Acme', po_number: 'PO-1', invoice_date: '2026-11-01', due_date: '2026-11-30',
          status: 'draft', payment_status: 'not_ready', grand_total: '100.00', currency: 'NPR', variance_total: '0.00', latest_match: null,
        }], count: 1 } });
      }
      return Promise.resolve({ data: { results: [] } });
    });
    render(<ProcurementInvoicesPage />);
    expect(screen.getByRole('status').textContent).toMatch(/Loading invoices/);
    expect(await screen.findByText('INV-1')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'INV-1' }).getAttribute('href')).toBe('#/procurement/invoices/1');
    expect(mockGet).toHaveBeenCalledWith('/procurement/supplier-invoices/?page_size=50');
  });

  it('shows an empty state when there are no invoices', async () => {
    render(<ProcurementInvoicesPage />);
    expect(await screen.findByText('No supplier invoices.')).toBeTruthy();
  });

  it('shows a standardized error and retries from the same endpoint', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 403, data: {} } });
    render(<ProcurementInvoicesPage />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/You do not have permission/);
    mockGet.mockResolvedValueOnce({ data: { results: [{ id: 3, invoice_number: 'INV-3', status: 'draft', currency: 'NPR' }] } });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('INV-3')).toBeTruthy();
  });

  it('renders invoice exceptions from the exceptions endpoint', async () => {
    mockGet.mockImplementation((url) => {
      if (url === '/procurement/invoice-exceptions/?page_size=50') {
        return Promise.resolve({ data: { results: [{ id: 4, invoice_number: 'INV-4', exception_type: 'price_variance', severity: 'high', status: 'open', variance: '12.00' }] } });
      }
      return Promise.resolve({ data: { results: [] } });
    });
    render(<ProcurementInvoiceExceptionsPage />);
    expect(await screen.findByText('INV-4')).toBeTruthy();
    expect(screen.getByText('price_variance')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/procurement/invoice-exceptions/?page_size=50');
  });
});

describe('P3 invoice create', () => {
  function mockLookups() {
    mockGet.mockImplementation((url) => {
      if (url === '/procurement/purchase-orders/?page_size=100') return Promise.resolve({ data: { results: [{ id: 5, po_number: 'PO-5', vendor: 2 }] } });
      if (url === '/assets/vendors/?page_size=100') return Promise.resolve({ data: { results: [{ id: 2, name: 'Acme' }] } });
      return Promise.resolve({ data: { results: [] } });
    });
  }

  async function fillForm(invoiceNumber = 'INV-1') {
    mockLookups();
    render(<ProcurementInvoiceForm />);
    await screen.findByRole('option', { name: 'Acme' });
    fireEvent.change(screen.getByLabelText(/Invoice Number/i), { target: { value: invoiceNumber } });
    fireEvent.change(screen.getByLabelText(/^Vendor$/i), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText(/Purchase Order/i), { target: { value: '5' } });
    fireEvent.change(screen.getByLabelText(/Invoice Date/i), { target: { value: '2026-11-10' } });
    fireEvent.change(screen.getByLabelText(/Received Date/i), { target: { value: '2026-11-11' } });
  }

  it('loads vendors and purchase orders and filters POs by the selected vendor', async () => {
    mockGet.mockImplementation((url) => {
      if (url === '/procurement/purchase-orders/?page_size=100') {
        return Promise.resolve({ data: { results: [
          { id: 5, po_number: 'PO-5', vendor: 2 },
          { id: 6, po_number: 'PO-6', vendor: 3 },
        ] } });
      }
      if (url === '/assets/vendors/?page_size=100') {
        return Promise.resolve({ data: { results: [{ id: 2, name: 'Acme' }, { id: 3, name: 'Beta' }] } });
      }
      return Promise.resolve({ data: { results: [] } });
    });
    render(<ProcurementInvoiceForm />);
    await screen.findByRole('option', { name: 'Acme' });
    expect(await screen.findByRole('option', { name: /PO-5/ })).toBeTruthy();
    expect(screen.getByRole('option', { name: /PO-6/ })).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/^Vendor$/i), { target: { value: '2' } });
    expect(screen.queryByRole('option', { name: /PO-6/ })).toBeNull();
    expect(screen.getByRole('option', { name: /PO-5/ })).toBeTruthy();
  });

  it('posts the exact payload and navigates with the returned invoice id', async () => {
    await fillForm('INV-9');
    mockPost.mockResolvedValue({ data: { id: 9 } });
    fireEvent.click(screen.getByRole('button', { name: /Create Invoice/i }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/supplier-invoices/', expect.any(Object)));
    const payload = mockPost.mock.calls[0][1];
    expect(payload).toMatchObject({ invoice_number: 'INV-9', vendor: '2', purchase_order: '5', currency: 'NPR', due_date: null });
    expect(payload).not.toHaveProperty('subtotal');
    expect(payload).not.toHaveProperty('grand_total');
    expect(payload).not.toHaveProperty('status');
    expect(payload).not.toHaveProperty('normalized_invoice_number');
    await waitFor(() => expect(window.location.hash).toBe('#/procurement/invoices/9'));
  });

  it('does not navigate when the server omits the new invoice id', async () => {
    await fillForm('INV-X');
    mockPost.mockResolvedValue({ data: {} });
    fireEvent.click(screen.getByRole('button', { name: /Create Invoice/i }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/did not return the new invoice id/);
    expect(window.location.hash).toBe('#/procurement/invoices');
  });

  it('renders 400 field errors readably instead of raw JSON', async () => {
    await fillForm('INV-DUP');
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { invoice_number: ['Duplicate invoice number.'], due_date: ['Due date cannot precede invoice date.'] } } });
    fireEvent.click(screen.getByRole('button', { name: /Create Invoice/i }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('Duplicate invoice number.')).toBeTruthy();
    expect(screen.getByText('Due date cannot precede invoice date.')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).not.toMatch(/[{}]/);
  });

  it('shows a permission message and prevents double submission', async () => {
    let rejectPost;
    await fillForm('INV-2');
    mockPost.mockReturnValue(new Promise((resolve, reject) => { rejectPost = reject; }));
    const button = screen.getByRole('button', { name: /Create Invoice/i });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    rejectPost({ response: { status: 403, data: {} } });
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/You do not have permission/);
  });
});

describe('P3 invoice detail readiness and visibility', () => {
  it('renders backend readiness blockers and only draft-relevant manager actions', async () => {
    render(<ProcurementInvoiceDetail id={1} />);
    expect(await screen.findByText(/Invoice INV-1/)).toBeTruthy();
    expect(screen.getByText(/NOT_MATCHED/)).toBeTruthy();
    expect(screen.getByText(/Match required/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Submit' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Run Match' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Place Hold' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mark Payment Ready' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mark Paid' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Release Hold' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Add Line' })).toBeTruthy();
  });

  it('shows Approve to a non-creator manager for a matched invoice', async () => {
    mockInvoiceLoad({ status: 'matched' });
    render(<ProcurementInvoiceDetail id={1} />);
    expect(await screen.findByText(/Invoice INV-1/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Add Line' })).toBeNull();
  });

  it('keeps Mark Payment Ready disabled until the backend readiness is true', async () => {
    mockInvoiceLoad({ status: 'approved', payment_status: 'not_ready' });
    render(<ProcurementInvoiceDetail id={1} />);
    expect(await screen.findByText(/Invoice INV-1/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    const ready = screen.getByRole('button', { name: 'Mark Payment Ready' });
    expect(ready.disabled).toBe(true);
    expect(ready.getAttribute('title')).toMatch(/readiness is false/);
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy();
  });

  it('never offers self-approval to the invoice creator', async () => {
    mockAuth.mockReturnValue(authUser('it_manager', 2));
    mockInvoiceLoad({ status: 'matched' });
    render(<ProcurementInvoiceDetail id={1} />);
    expect(await screen.findByText(/Invoice INV-1/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeTruthy();
  });

  it('gives IT Support operational actions but no financial approval or payment controls', async () => {
    mockAuth.mockReturnValue(authUser('it_support', 3));
    mockInvoiceLoad({ status: 'submitted' });
    render(<ProcurementInvoiceDetail id={1} />);
    expect(await screen.findByText(/Invoice INV-1/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Run Match' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Place Hold' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mark Payment Ready' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mark Paid' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('offers Close only for paid invoices and Release Hold only while a hold exists', async () => {
    mockInvoiceLoad({ status: 'paid', payment_status: 'paid' });
    render(<ProcurementInvoiceDetail id={1} />);
    expect(await screen.findByText(/Invoice INV-1/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Close' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mark Paid' })).toBeNull();
    cleanup();

    mockInvoiceLoad({ status: 'approved', payment_status: 'on_hold', payment_hold: true, payment_hold_reason: 'Query' });
    render(<ProcurementInvoiceDetail id={1} />);
    expect(await screen.findByText(/Invoice INV-1/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Release Hold' })).toBeTruthy();
    expect(screen.getByText(/Yes: Query/)).toBeTruthy();
  });

  it('renders unknown backend blocker codes safely', async () => {
    mockInvoiceLoad({ readiness: { ready: false, blockers: [{ code: 'FUTURE_BLOCKER', message: 'Something new', severity: 'info' }] } });
    render(<ProcurementInvoiceDetail id={1} />);
    expect(await screen.findByText(/FUTURE_BLOCKER/)).toBeTruthy();
    expect(screen.getByText(/Something new/)).toBeTruthy();
  });
});

describe('P3 invoice actions and errors', () => {
  it('records payment with the exact endpoint and payload after both prompts', async () => {
    window.prompt = vi.fn().mockReturnValueOnce('REF-1').mockReturnValueOnce('2026-11-10');
    mockInvoiceLoad({ status: 'payment_ready', payment_status: 'ready' });
    render(<ProcurementInvoiceDetail id={1} />);
    expect(await screen.findByText(/Invoice INV-1/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Mark Paid' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/procurement/supplier-invoices/1/mark-paid/',
      { payment_reference: 'REF-1', payment_date: '2026-11-10' },
    ));
    expect(screen.queryByText(/Payment sent|Payment transferred|Payment executed/)).toBeNull();
  });

  it('reloads exactly once on a 409 conflict without resubmitting', async () => {
    mockInvoiceLoad({ status: 'draft' });
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: {} } });
    render(<ProcurementInvoiceDetail id={1} />);
    await screen.findByText(/Invoice INV-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByText(/This invoice changed while you were working\. The latest version has been loaded\./)).toBeTruthy();
    await waitFor(() => {
      const invoiceLoads = mockGet.mock.calls.filter(([url]) => url === '/procurement/supplier-invoices/1/');
      expect(invoiceLoads.length).toBe(2);
    });
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it('standardizes 403 action failures', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 403, data: {} } });
    render(<ProcurementInvoiceDetail id={1} />);
    await screen.findByText(/Invoice INV-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByText('You do not have permission to perform this action.')).toBeTruthy();
  });

  it('surfaces 400 field errors from submit near the action', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { lines: ['At least one line is required.'], detail: 'Invalid invoice.' } } });
    render(<ProcurementInvoiceDetail id={1} />);
    await screen.findByText(/Invoice INV-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByText('Invalid invoice.')).toBeTruthy();
    expect(screen.getByText('At least one line is required.')).toBeTruthy();
  });

  it('surfaces a 400 readiness/variance rejection on approve', async () => {
    mockInvoiceLoad({ status: 'matched' });
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { detail: 'Unresolved exceptions block approval.' } } });
    render(<ProcurementInvoiceDetail id={1} />);
    await screen.findByText(/Invoice INV-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(await screen.findByText('Unresolved exceptions block approval.')).toBeTruthy();
    expect(mockPost).toHaveBeenCalledWith('/procurement/supplier-invoices/1/approve/', {});
  });
});
