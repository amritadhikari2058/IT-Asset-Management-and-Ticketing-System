import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

const { mockGet, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: (...a) => mockAuth(...a),
  AuthProvider: ({ children }) => children,
}));

import App from '../../App';

function makeAuth(role) {
  const isStaff = role === 'system_admin' || role === 'it_manager' || role === 'it_support';
  const isManager = role === 'system_admin' || role === 'it_manager';
  const active = role !== null && role !== 'inactive';
  return {
    access: active ? 'token' : null,
    role,
    user: active ? { id: 1, email: 'u@x.io', employee_id: 'E1', role, is_active: true } : null,
    profileLoading: false,
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isStaff,
    isAdmin: role === 'system_admin',
    canViewProcurement: isStaff,
    canViewProcurementReports: isManager,
    login: vi.fn(),
    logout: vi.fn(),
    refreshProfile: vi.fn(),
  };
}

function setupApi() {
  mockGet.mockImplementation(async (url) => {
    const u = String(url);
    if (u.startsWith('/procurement/invoice-exceptions/')) return { data: { results: [], count: 0 } };
    if (u.startsWith('/procurement/')) return { data: { results: [], count: 0 } };
    return { data: { results: [], count: 0 } };
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  setupApi();
  window.location.hash = '#/procurement';
});

afterEach(() => cleanup());

const NAV_ITEMS = [
  'Supplier Invoices',
  'Invoice Exceptions',
  'Vendor Returns',
  'Vendor Credit Notes',
  'Procurement Financial Dashboard',
  'Vendor Performance',
];

describe('Procurement navigation visibility', () => {
  it('System Admin sees all six P3 entries', () => {
    mockAuth.mockReturnValue(makeAuth('system_admin'));
    render(<App />);
    for (const label of NAV_ITEMS) expect(screen.getByText(label)).toBeTruthy();
  });

  it('IT Manager sees all six P3 entries', () => {
    mockAuth.mockReturnValue(makeAuth('it_manager'));
    render(<App />);
    for (const label of NAV_ITEMS) expect(screen.getByText(label)).toBeTruthy();
  });

  it('IT Support sees four operational entries but not financial dashboards', () => {
    mockAuth.mockReturnValue(makeAuth('it_support'));
    render(<App />);
    for (const label of ['Supplier Invoices', 'Invoice Exceptions', 'Vendor Returns', 'Vendor Credit Notes']) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    expect(screen.queryByText('Procurement Financial Dashboard')).toBeNull();
    expect(screen.queryByText('Vendor Performance')).toBeNull();
  });

  it('Employee sees none of the six P3 entries', () => {
    mockAuth.mockReturnValue(makeAuth('employee'));
    render(<App />);
    for (const label of NAV_ITEMS) expect(screen.queryByText(label)).toBeNull();
  });

  it('Unknown role sees none of the six P3 entries', () => {
    mockAuth.mockReturnValue(makeAuth('unknown'));
    render(<App />);
    for (const label of NAV_ITEMS) expect(screen.queryByText(label)).toBeNull();
  });

  it('Null user sees none of the six P3 entries', () => {
    mockAuth.mockReturnValue(makeAuth(null));
    render(<App />);
    for (const label of NAV_ITEMS) expect(screen.queryByText(label)).toBeNull();
  });
});

describe('Procurement breadcrumbs', () => {
  const cases = [
    ['#/procurement/invoices', 'Supplier Invoices'],
    ['#/procurement/invoices/new', 'New Supplier Invoice'],
    ['#/procurement/invoices/42', 'Supplier Invoice'],
    ['#/procurement/invoices/42/match', 'Matching'],
    ['#/procurement/exceptions', 'Invoice Exceptions'],
    ['#/procurement/returns', 'Vendor Returns'],
    ['#/procurement/returns/new', 'New Vendor Return'],
    ['#/procurement/returns/7', 'Vendor Return'],
    ['#/procurement/credit-notes', 'Vendor Credit Notes'],
    ['#/procurement/credit-notes/new', 'New Vendor Credit Note'],
    ['#/procurement/credit-notes/9', 'Vendor Credit Note'],
    ['#/procurement/financial-dashboard', 'Financial Dashboard'],
    ['#/procurement/vendor-performance', 'Vendor Performance'],
  ];

  for (const [hash, last] of cases) {
    it(`renders breadcrumb for ${hash}`, async () => {
      mockAuth.mockReturnValue(makeAuth('system_admin'));
      window.location.hash = hash;
      render(<App />);
      const nav = screen.getByLabelText('Breadcrumb');
      expect(nav.textContent).toContain('Procurement');
      expect(nav.textContent).toContain(last);
    });
  }

  it('does not treat new as an id', () => {
    mockAuth.mockReturnValue(makeAuth('system_admin'));
    window.location.hash = '#/procurement/invoices/new';
    render(<App />);
    const nav = screen.getByLabelText('Breadcrumb');
    expect(nav.textContent).toContain('New Supplier Invoice');
    expect(nav.textContent).not.toContain('Supplier Invoice\n');
  });
});

describe('Procurement title fallback', () => {
  it('shows Supplier Invoices title in breadcrumb list', () => {
    mockAuth.mockReturnValue(makeAuth('system_admin'));
    window.location.hash = '#/procurement/invoices';
    render(<App />);
    expect(screen.getByLabelText('Breadcrumb').textContent).toContain('Supplier Invoices');
  });
});
