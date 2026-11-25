import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

const { mockGet, mockPost } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
  },
}));

import { ProcurementMatchingPage } from '../../pages/procurement/ProcurementMatching';

const invoice = {
  id: 1, invoice_number: 'INV-1', currency: 'NPR',
  lines: [{
    id: 10, purchase_order_item: 5, po_item_name: 'Laptop', invoiced_quantity: '3', accepted_quantity_snapshot: '2',
    matched_quantity: '2', unit_price: '100.00', tax_amount: '13.00', line_total: '339.00',
    quantity_variance: '100.00', price_variance: '1.23', tax_variance: '0.40', total_variance: '101.63', match_status: 'quantity_variance',
    exception_reason: 'Invoiced above accepted quantity',
  }],
};

const history = [
  {
    match_version: 2, overall_status: 'quantity_variance', po_total_snapshot: '200.00', accepted_receipt_total_snapshot: '200.00',
    invoice_total_snapshot: '339.00', quantity_variance_total: '100.00', price_variance_total: '1.23', tax_variance_total: '0.40',
    total_variance: '101.63', tolerance_snapshot: { quantity: 0, price: '0.05' }, checksum: 'abc123',
    matched_at: '2026-11-01T10:00:00Z', matched_by_name: 'manager@example.com',
  },
  {
    match_version: 1, overall_status: 'matched', po_total_snapshot: '200.00', accepted_receipt_total_snapshot: '200.00',
    invoice_total_snapshot: '200.00', quantity_variance_total: '0.00', price_variance_total: '0.00', tax_variance_total: '0.00',
    total_variance: '0.00', tolerance_snapshot: {}, checksum: 'old999', matched_at: '2026-10-31T09:00:00Z', matched_by_name: 'other@example.com',
  },
];

const exceptions = [
  { id: 7, exception_type: 'quantity_variance', severity: 'high', status: 'open', expected_value: '2', actual_value: '3', variance: '1', reason: 'Over invoiced' },
  { id: 8, exception_type: 'price_variance', severity: 'low', status: 'resolved', expected_value: '100.00', actual_value: '101.23', variance: '1.23', reason: 'Corrected' },
];

function mockMatchLoad({ inv = invoice, hist = history, exc = exceptions } = {}) {
  mockGet.mockImplementation((url) => {
    if (url === '/procurement/supplier-invoices/1/') return Promise.resolve({ data: inv });
    if (url === '/procurement/supplier-invoices/1/match-history/') return Promise.resolve({ data: hist });
    if (url === '/procurement/supplier-invoices/1/exceptions/') return Promise.resolve({ data: exc });
    return Promise.resolve({ data: [] });
  });
}

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  mockMatchLoad();
  mockPost.mockResolvedValue({ data: {} });
});
afterEach(() => cleanup());

describe('P3 matching display', () => {
  it('renders backend-provided line quantities, prices and variances verbatim', async () => {
    render(<ProcurementMatchingPage id={1} />);
    expect(screen.getByText('Loading…')).toBeTruthy();
    expect(await screen.findByText(/Three-Way Match: INV-1/)).toBeTruthy();
    expect(screen.getByText('Laptop')).toBeTruthy();
    expect(screen.getByText('Invoiced above accepted quantity')).toBeTruthy();
    expect(screen.getAllByText('100.00').length).toBeGreaterThan(0);
    expect(screen.getAllByText('1.23').length).toBeGreaterThan(0);
    expect(screen.getByText('0.40')).toBeTruthy();
    expect(screen.getAllByText('101.63').length).toBeGreaterThan(0);
    expect(screen.getByText(/Matching is performed by the backend and is authoritative/i)).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/procurement/supplier-invoices/1/');
    expect(mockGet).toHaveBeenCalledWith('/procurement/supplier-invoices/1/match-history/');
    expect(mockGet).toHaveBeenCalledWith('/procurement/supplier-invoices/1/exceptions/');
  });

  it('renders latest match metadata: version, totals, tolerance, checksum and actor', async () => {
    render(<ProcurementMatchingPage id={1} />);
    await screen.findByText(/Three-Way Match: INV-1/);
    expect(screen.getByText(/version 2/)).toBeTruthy();
    expect(screen.getAllByText(/abc123/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/manager@example.com/).length).toBeGreaterThan(0);
    expect(screen.getByText(/"quantity":0/)).toBeTruthy();
    expect(screen.getByText(/Quantity variance NPR 100\.00/)).toBeTruthy();
    expect(screen.getByText(/Price variance NPR 1\.23/)).toBeTruthy();
    expect(screen.getByText(/Tax variance NPR 0\.40/)).toBeTruthy();
  });

  it('renders every prior match version in backend order', async () => {
    render(<ProcurementMatchingPage id={1} />);
    await screen.findByText(/Three-Way Match: INV-1/);
    expect(screen.getByText('Checksum')).toBeTruthy();
    expect(screen.getAllByText('abc123').length).toBeGreaterThan(0);
    expect(screen.getByText('old999')).toBeTruthy();
    expect(screen.getByText('other@example.com')).toBeTruthy();
  });

  it('renders open and resolved exceptions with backend values', async () => {
    render(<ProcurementMatchingPage id={1} />);
    await screen.findByText(/Three-Way Match: INV-1/);
    expect(screen.getByText('Open')).toBeTruthy();
    expect(screen.getByText('Resolved')).toBeTruthy();
    expect(screen.getByText('Corrected')).toBeTruthy();
  });

  it('shows safe empty states for missing history and exceptions', async () => {
    mockMatchLoad({ hist: [], exc: [] });
    render(<ProcurementMatchingPage id={1} />);
    await screen.findByText(/Three-Way Match: INV-1/);
    expect(screen.getByText('No match results.')).toBeTruthy();
    expect(screen.getByText('No exceptions.')).toBeTruthy();
  });
});

describe('P3 matching run and errors', () => {
  it('runs the match through the exact endpoint and reloads the backend history', async () => {
    render(<ProcurementMatchingPage id={1} />);
    await screen.findByText(/Three-Way Match: INV-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Run Match' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/supplier-invoices/1/match/', {}));
    await waitFor(() => {
      const historyLoads = mockGet.mock.calls.filter(([url]) => url === '/procurement/supplier-invoices/1/match-history/');
      expect(historyLoads.length).toBe(2);
    });
  });

  it('allows a repeated match request without inventing client results', async () => {
    render(<ProcurementMatchingPage id={1} />);
    await screen.findByText(/Three-Way Match: INV-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Run Match' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'Run Match' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2));
    expect(screen.getAllByText('abc123').length).toBeGreaterThan(0);
  });

  it('shows a 400 invalid-state message from the backend', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { detail: 'Invoice cannot be matched without lines.' } } });
    render(<ProcurementMatchingPage id={1} />);
    await screen.findByText(/Three-Way Match: INV-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Run Match' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/cannot be matched without lines/);
  });

  it('standardizes 403 permission failures', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 403, data: {} } });
    render(<ProcurementMatchingPage id={1} />);
    await screen.findByText(/Three-Way Match: INV-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Run Match' }));
    expect(await screen.findByText('You do not have permission to perform this action.')).toBeTruthy();
  });

  it('standardizes 404 unavailable records', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 404, data: {} } });
    render(<ProcurementMatchingPage id={1} />);
    await screen.findByText(/Three-Way Match: INV-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Run Match' }));
    expect(await screen.findByText(/This Procurement record is unavailable or you no longer have access\./)).toBeTruthy();
  });

  it('surfaces a 409 conflict from the backend without crashing', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'Invoice changed.' } } });
    render(<ProcurementMatchingPage id={1} />);
    await screen.findByText(/Three-Way Match: INV-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Run Match' }));
    expect(await screen.findByText(/Invoice changed\./)).toBeTruthy();
  });
});
