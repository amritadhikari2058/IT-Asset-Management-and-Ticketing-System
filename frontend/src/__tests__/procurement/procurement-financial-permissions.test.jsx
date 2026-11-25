import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

const { mockGet, mockAuth } = vi.hoisted(() => ({ mockGet: vi.fn(), mockAuth: vi.fn() }));
vi.mock('../../api', () => ({ default: { get: (...a) => mockGet(...a), post: vi.fn() } }));
vi.mock('../../auth', () => ({ useAuth: (...a) => mockAuth(...a) }));

import { ProcurementFinancialDashboard } from '../../pages/procurement/ProcurementFinancialDashboard';
import { ProcurementVendorPerformance } from '../../pages/procurement/ProcurementVendorPerformance';
import { ProcurementRouter } from '../../pages/procurement';
import { procurementCapabilities, invoiceActionState, vendorReturnActionState, vendorCreditNoteActionState } from '../../shared/procurement-utils';

function makeAuth(role, id = 1, extra = {}) {
  if (role === null) return { access: 'token', user: null, role: undefined };
  return {
    access: 'token',
    role,
    user: { id, role, ...extra },
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isSuperuser: false,
  };
}

const dashboard = {
  cards: {
    draft: 1, submitted: 2, awaiting_match: 2, matched: 5, match_exceptions: 1, approval_pending: 3,
    payment_holds: 0, payment_ready: 4, paid_in_period: 6, overdue: 1, open_returns: 2, pending_credits: 1,
    unresolved_high_critical: 2, match_rate: 0, exception_rate: 0,
  },
  totals_by_currency: [{ currency: 'NPR', invoiced: '1000.00', approved: '800.00', payment_ready: '400.00', paid: '200.00', credit_note_total: '50.00', exception_value: '30.00', outstanding: '750.00' }],
  recent_invoices: [], critical_exceptions: [], payment_ready_invoices: [], overdue_invoices: [], open_vendor_returns: [], credits_awaiting_application: [],
};

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  mockAuth.mockReturnValue(makeAuth('it_manager'));
  mockGet.mockResolvedValue({ data: { results: [] } });
});
afterEach(() => cleanup());

describe('P3 role capabilities', () => {
  it('grants System Admin full operational and financial controls', () => {
    const caps = procurementCapabilities(makeAuth('system_admin'));
    expect(caps.canViewProcurement).toBe(true);
    expect(caps.canViewProcurementReports).toBe(true);
    expect(caps.canManageFinancialControls).toBe(true);
    expect(caps.canApproveSupplierInvoice).toBe(true);
    expect(caps.canMarkSupplierInvoicePaymentReady).toBe(true);
    expect(caps.canRecordSupplierInvoicePayment).toBe(true);
    expect(caps.canApproveVendorReturn).toBe(true);
    expect(caps.canApproveVendorCreditNote).toBe(true);
    expect(caps.canAcceptInvoiceException).toBe(true);
  });

  it('grants IT Manager financial approval and reporting but not System Admin escalation', () => {
    const caps = procurementCapabilities(makeAuth('it_manager'));
    expect(caps.canManageProcurementFinance).toBe(true);
    expect(caps.canApproveVendorReturn).toBe(true);
    expect(caps.canApproveVendorCreditNote).toBe(true);
    expect(caps.canViewProcurementReports).toBe(true);
  });

  it('gives IT Support operational access with no financial controls', () => {
    const caps = procurementCapabilities(makeAuth('it_support'));
    expect(caps.canViewProcurement).toBe(true);
    expect(caps.canCreatePurchaseRequest).toBe(true);
    expect(caps.canManageProcurementFinance).toBe(false);
    expect(caps.canApproveSupplierInvoice).toBe(false);
    expect(caps.canMarkSupplierInvoicePaymentReady).toBe(false);
    expect(caps.canRecordSupplierInvoicePayment).toBe(false);
    expect(caps.canApproveVendorReturn).toBe(false);
    expect(caps.canApproveVendorCreditNote).toBe(false);
    expect(caps.canAcceptInvoiceException).toBe(false);
    expect(caps.canViewProcurementReports).toBe(false);
  });

  it('fails closed for employees, unknown roles, null users and inactive accounts', () => {
    for (const auth of [makeAuth('employee'), makeAuth('auditor'), makeAuth(null)]) {
      const caps = procurementCapabilities(auth);
      expect(caps.canViewProcurement).toBe(false);
      expect(caps.canManageProcurementFinance).toBe(false);
      expect(caps.canViewProcurementReports).toBe(false);
    }
    const inactive = procurementCapabilities(makeAuth('it_manager', 1, { is_active: false }));
    expect(inactive.canViewProcurement).toBe(false);
    expect(inactive.canManageProcurementFinance).toBe(false);
  });

  it('treats superusers as System Admin', () => {
    const caps = procurementCapabilities({ role: 'employee', isSuperuser: true, user: { id: 9, is_superuser: true } });
    expect(caps.canViewProcurement).toBe(true);
    expect(caps.canManageFinancialControls).toBe(true);
  });

  it('mirrors backend action rules for creator self-approval and source status', () => {
    const manager = procurementCapabilities(makeAuth('it_manager'));
    expect(invoiceActionState({ status: 'matched', created_by: 1 }, manager, 1).canApprove).toBe(false);
    expect(invoiceActionState({ status: 'matched', created_by: 2 }, manager, 1).canApprove).toBe(true);
    expect(invoiceActionState({ status: 'draft' }, manager, 1).canClose).toBe(false);
    expect(invoiceActionState({ status: 'paid' }, manager, 1).canCancel).toBe(false);
    expect(vendorReturnActionState({ status: 'pending_approval', created_by: 1 }, manager, 1).canApprove).toBe(false);
    expect(vendorReturnActionState({ status: 'pending_approval', created_by: 1 }, procurementCapabilities(makeAuth('system_admin')), 1, true).canApprove).toBe(true);
    expect(vendorCreditNoteActionState({ status: 'submitted', created_by: 1 }, manager, 1).canApprove).toBe(false);
    expect(vendorCreditNoteActionState({ status: 'approved' }, manager, 1).canApply).toBe(true);
    const support = procurementCapabilities(makeAuth('it_support'));
    expect(invoiceActionState({ status: 'submitted' }, support, 3).canMatch).toBe(true);
    expect(invoiceActionState({ status: 'submitted' }, support, 3).canApprove).toBe(false);
  });
});

describe('P3 direct-route protection', () => {
  const routes = [
    '/procurement/invoices', '/procurement/invoices/new', '/procurement/invoices/7', '/procurement/invoices/7/match',
    '/procurement/exceptions', '/procurement/returns', '/procurement/returns/new', '/procurement/returns/7',
    '/procurement/credit-notes', '/procurement/credit-notes/new', '/procurement/credit-notes/7',
    '/procurement/financial-dashboard', '/procurement/vendor-performance',
  ];

  it.each(routes)('denies employees at %s without any API call', (route) => {
    mockAuth.mockReturnValue(makeAuth('employee'));
    render(<ProcurementRouter route={route} />);
    expect(screen.getByRole('alert').textContent).toMatch(/You do not have permission to access this page\./);
    expect(mockGet).not.toHaveBeenCalled();
  });

  it.each(routes)('fails closed for unknown roles at %s', (route) => {
    mockAuth.mockReturnValue(makeAuth('auditor'));
    render(<ProcurementRouter route={route} />);
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it.each(routes)('fails closed for a null user at %s', (route) => {
    mockAuth.mockReturnValue(makeAuth(null));
    render(<ProcurementRouter route={route} />);
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('lets IT Support load operational routes', async () => {
    mockAuth.mockReturnValue(makeAuth('it_support'));
    const { unmount } = render(<ProcurementRouter route="/procurement/invoices" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/procurement/supplier-invoices/?page_size=50'));
    unmount();
    mockGet.mockClear();
    render(<ProcurementRouter route="/procurement/exceptions" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/procurement/invoice-exceptions/?page_size=50'));
    cleanup();
    mockGet.mockClear();
    render(<ProcurementRouter route="/procurement/returns" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/procurement/vendor-returns/?page_size=50'));
    cleanup();
    mockGet.mockClear();
    render(<ProcurementRouter route="/procurement/credit-notes" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/procurement/credit-notes/?page_size=50'));
  });

  it('denies IT Support the manager-only financial dashboard and vendor performance with no API call', () => {
    mockAuth.mockReturnValue(makeAuth('it_support'));
    const { unmount } = render(<ProcurementRouter route="/procurement/financial-dashboard" />);
    expect(screen.getByRole('alert').textContent).toMatch(/requires IT Manager or System Admin/);
    expect(mockGet).not.toHaveBeenCalled();
    unmount();
    render(<ProcurementRouter route="/procurement/vendor-performance" />);
    expect(screen.getByRole('alert').textContent).toMatch(/requires IT Manager or System Admin/);
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('lets a manager load the financial dashboard and vendor performance', async () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    mockGet.mockImplementation((url) => {
      if (url === '/procurement/financial-dashboard/') return Promise.resolve({ data: dashboard });
      if (url === '/procurement/reports/vendor-performance/') return Promise.resolve({ data: [] });
      return Promise.resolve({ data: { results: [] } });
    });
    const { unmount } = render(<ProcurementRouter route="/procurement/financial-dashboard" />);
    expect(await screen.findByText('Procurement Financial Dashboard')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/procurement/financial-dashboard/');
    unmount();
    render(<ProcurementRouter route="/procurement/vendor-performance" />);
    expect(await screen.findByText('Vendor Performance')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/procurement/reports/vendor-performance/');
  });
});

describe('P3 financial dashboard', () => {
  it('renders all backend KPI cards and currency totals without combining currencies', async () => {
    mockGet.mockResolvedValue({ data: {
      ...dashboard,
      totals_by_currency: [
        { currency: 'NPR', invoiced: '1000.00', approved: '800.00', payment_ready: '400.00', paid: '200.00', credit_note_total: '50.00', exception_value: '30.00', outstanding: '750.00' },
        { currency: 'USD', invoiced: '500.00', approved: '200.00', payment_ready: '100.00', paid: '50.00', credit_note_total: '10.00', exception_value: '5.00', outstanding: '440.00' },
      ],
    } });
    render(<ProcurementFinancialDashboard />);
    expect(await screen.findByText('Procurement Financial Dashboard')).toBeTruthy();
    for (const label of ['Draft', 'Submitted', 'Awaiting Match', 'Matched', 'Match Exceptions', 'Approval Pending', 'Payment Holds', 'Payment Ready', 'Paid in Period', 'Overdue', 'Open Returns', 'Pending Credits', 'High/Critical Exceptions', 'Match Rate', 'Exception Rate']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByText('NPR')).toBeTruthy();
    expect(screen.getByText('USD')).toBeTruthy();
    expect(screen.getByText('1,000.00')).toBeTruthy();
    expect(screen.getByText('500.00')).toBeTruthy();
    expect(screen.getByText('440.00')).toBeTruthy();
    expect(screen.getByText(/Currencies are never combined\./)).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/procurement/financial-dashboard/');
  });

  it('renders a safe zero state', async () => {
    mockGet.mockResolvedValue({ data: { cards: {}, totals_by_currency: [], recent_invoices: [], critical_exceptions: [], payment_ready_invoices: [], overdue_invoices: [], open_vendor_returns: [], credits_awaiting_application: [] } });
    render(<ProcurementFinancialDashboard />);
    expect(await screen.findByText('Procurement Financial Dashboard')).toBeTruthy();
    expect(screen.getAllByText('0').length).toBeGreaterThan(5);
    expect(screen.getByText('No financial totals.')).toBeTruthy();
  });

  it('renders missing optional totals safely', async () => {
    mockGet.mockResolvedValue({ data: { cards: {}, totals_by_currency: [{ currency: 'NPR' }], recent_invoices: [], critical_exceptions: [], payment_ready_invoices: [], overdue_invoices: [], open_vendor_returns: [], credits_awaiting_application: [] } });
    render(<ProcurementFinancialDashboard />);
    await screen.findByText('Procurement Financial Dashboard');
    expect(screen.getAllByText('—').length).toBeGreaterThan(5);
  });

  it('shows an error and retries', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 403, data: {} } });
    render(<ProcurementFinancialDashboard />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/You do not have permission/);
    mockGet.mockResolvedValueOnce({ data: dashboard });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Procurement Financial Dashboard')).toBeTruthy();
  });
});

describe('P3 vendor performance', () => {
  it('renders backend operational metrics and small-sample note without a composite score', async () => {
    mockGet.mockResolvedValue({ data: [{
      vendor_id: 1, vendor_name: 'Acme', purchase_orders: 1, on_time_delivery_rate: 100, complete_delivery_rate: 100,
      rejected_quantity_rate: 0, damaged_quantity_rate: 5, invoice_match_rate: 50, average_price_variance: 1.23,
      open_returns: 2, sample_note: 'Small sample',
    }] });
    render(<ProcurementVendorPerformance />);
    expect(await screen.findByText('Vendor Performance')).toBeTruthy();
    expect(screen.getByText('Acme')).toBeTruthy();
    expect(screen.getByText('Small sample')).toBeTruthy();
    expect(screen.getByText(/No composite vendor score is calculated\./)).toBeTruthy();
    expect(screen.queryByRole('columnheader', { name: /Score/i })).toBeNull();
    expect(mockGet).toHaveBeenCalledWith('/procurement/reports/vendor-performance/');
  });

  it('renders zero-denominator metrics safely as dashes', async () => {
    mockGet.mockResolvedValue({ data: [{
      vendor_id: 2, vendor_name: 'Beta', purchase_orders: 0, on_time_delivery_rate: null, complete_delivery_rate: null,
      rejected_quantity_rate: null, damaged_quantity_rate: null, invoice_match_rate: null, average_price_variance: null,
      open_returns: 0, sample_note: 'Small sample',
    }] });
    render(<ProcurementVendorPerformance />);
    expect(await screen.findByText('Beta')).toBeTruthy();
    expect(screen.getAllByText('—').length).toBeGreaterThan(5);
    expect(screen.getByText('Small sample')).toBeTruthy();
  });

  it('renders a safe empty state and retries after an error', async () => {
    render(<ProcurementVendorPerformance />);
    expect(await screen.findByText('No vendor performance data.')).toBeTruthy();
    cleanup();
    mockGet.mockRejectedValueOnce({ response: { status: 403, data: {} } });
    render(<ProcurementVendorPerformance />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    mockGet.mockResolvedValueOnce({ data: [] });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('No vendor performance data.')).toBeTruthy();
  });
});
