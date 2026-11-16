import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

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

import { ProcurementRouter } from './procurement';
import { procurementCapabilities } from './procurement-utils';

function makeAuth(role) {
  if (role === null) return { access: 'token', user: null, role: undefined };
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

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  mockAuth.mockReturnValue(makeAuth('it_manager'));
  mockGet.mockResolvedValue({ data: { results: [], count: 0, next: null, previous: null } });
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('procurementCapabilities', () => {
  it('grants System Admin every capability', () => {
    const caps = procurementCapabilities(makeAuth('system_admin'));
    expect(Object.values(caps).every(Boolean)).toBe(true);
  });

  it('gives IT Manager approval, vendor and order authority', () => {
    const caps = procurementCapabilities(makeAuth('it_manager'));
    expect(caps.canApprovePurchaseRequest).toBe(true);
    expect(caps.canSelectProcurementVendor).toBe(true);
    expect(caps.canApprovePurchaseOrder).toBe(true);
    expect(caps.canIssuePurchaseOrder).toBe(true);
    expect(caps.canViewProcurementReports).toBe(true);
  });

  it('gives IT Support operational access without approvals', () => {
    const caps = procurementCapabilities(makeAuth('it_support'));
    expect(caps.canViewProcurement).toBe(true);
    expect(caps.canCreatePurchaseRequest).toBe(true);
    expect(caps.canCreateGoodsReceipt).toBe(true);
    expect(caps.canApprovePurchaseRequest).toBe(false);
    expect(caps.canSelectProcurementVendor).toBe(false);
    expect(caps.canApprovePurchaseOrder).toBe(false);
    expect(caps.canIssuePurchaseOrder).toBe(false);
    expect(caps.canViewProcurementReports).toBe(false);
  });

  it('fails closed for employees, unknown roles and a null user', () => {
    for (const auth of [makeAuth('employee'), makeAuth(undefined), makeAuth(null)]) {
      const caps = procurementCapabilities(auth);
      expect(Object.values(caps).some(Boolean)).toBe(false);
    }
  });
});

describe('procurement routes', () => {
  it('renders the dashboard at #/procurement', async () => {
    window.location.hash = '#/procurement';
    render(<ProcurementRouter route="/procurement" />);
    expect(await screen.findByRole('heading', { name: 'Procurement' })).toBeTruthy();
  });

  it('denies employees with AccessDenied and makes no API call', () => {
    mockAuth.mockReturnValue(makeAuth('employee'));
    render(<ProcurementRouter route="/procurement/requests" />);
    expect(screen.getByText('You do not have permission to access this page.')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('denies an unknown role and a null user', () => {
    mockAuth.mockReturnValue(makeAuth(undefined));
    const first = render(<ProcurementRouter route="/procurement/orders" />);
    expect(screen.getByText('You do not have permission to access this page.')).toBeTruthy();
    first.unmount();
    mockAuth.mockReturnValue(makeAuth(null));
    render(<ProcurementRouter route="/procurement" />);
    expect(screen.getByText('You do not have permission to access this page.')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('handles invalid record ids without calling the API', () => {
    render(<ProcurementRouter route="/procurement/requests/not-a-number" />);
    expect(screen.getByText('This purchase request does not exist.')).toBeTruthy();
    cleanup();
    render(<ProcurementRouter route="/procurement/orders/abc" />);
    expect(screen.getByText('This purchase order does not exist.')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('routes nested request pages to the right component', async () => {
    mockGet.mockImplementation((url) => {
      if (String(url).startsWith('/procurement/purchase-requests/5/')) {
        return Promise.resolve({
          data: {
            id: 5, pr_number: 'PR-2026-00005', requester: 2, requester_name: 'r@x',
            department: null, status: 'approved', reason: 'Reason', notes: '',
            estimated_total: '10.00', requires_system_admin_approval: false,
            approver: null, approver_name: null, approval_decision: '', approval_reason: '',
            approved_at: null, created_at: '2026-11-01T10:00:00Z',
            updated_at: '2026-11-01T10:00:00Z', items: [], quotations: [], history: [],
          },
        });
      }
      return Promise.resolve({ data: { results: [], count: 0, next: null } });
    });
    render(<ProcurementRouter route="/procurement/requests/5/quotations" />);
    expect(await screen.findByText('Quotations · PR-2026-00005')).toBeTruthy();
    expect(mockGet.mock.calls.some((c) => String(c[0]).startsWith('/api/'))).toBe(false);
  });

  it('requires manager rights for reports', () => {
    mockAuth.mockReturnValue(makeAuth('it_support'));
    render(<ProcurementRouter route="/procurement/reports" />);
    expect(screen.getByText('Reports are restricted')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('renders asset registration for support staff', async () => {
    mockAuth.mockReturnValue(makeAuth('it_support'));
    render(<ProcurementRouter route="/procurement/assets" />);
    expect(await screen.findByRole('heading', { name: 'Pending asset registration' })).toBeTruthy();
  });

  it('uses only procurement and asset endpoints without a duplicate /api prefix', async () => {
    render(<ProcurementRouter route="/procurement" />);
    await screen.findByRole('heading', { name: 'Procurement' });
    const urls = mockGet.mock.calls.map((call) => String(call[0]));
    expect(urls.length).toBeGreaterThan(0);
    for (const url of urls) {
      expect(url.startsWith('/procurement/')).toBe(true);
      expect(url.includes('/api/api/')).toBe(false);
    }
  });

  it('shows an honest not-found state for unknown procurement pages', () => {
    render(<ProcurementRouter route="/procurement/nope" />);
    expect(screen.getByText('This procurement page does not exist.')).toBeTruthy();
  });
});
