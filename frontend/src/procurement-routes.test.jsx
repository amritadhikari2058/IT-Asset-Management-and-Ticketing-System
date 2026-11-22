import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

const { mockGet, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...a) => mockAuth(...a),
  AuthProvider: ({ children }) => children,
}));

import App from './App';

function makeAuth(role) {
  const isStaff = role === 'system_admin' || role === 'it_manager' || role === 'it_support';
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
    canViewProcurementReports: isStaff,
    login: vi.fn(),
    logout: vi.fn(),
    refreshProfile: vi.fn(),
  };
}

function setupApi() {
  mockGet.mockImplementation(async (url) => {
    return { data: { results: [], count: 0 } };
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  setupApi();
});

afterEach(() => cleanup());

/** All supported Procurement routes that must NOT show the fallback. */
const VALID_ROUTES = [
  '#/procurement',
  '#/procurement/requests',
  '#/procurement/requests/new',
  '#/procurement/requests/1',
  '#/procurement/requests/1/edit',
  '#/procurement/requests/1/quotations',
  '#/procurement/orders',
  '#/procurement/orders/1',
  '#/procurement/receipts',
  '#/procurement/receipts/new',
  '#/procurement/receipts/1',
  '#/procurement/assets',
  '#/procurement/vendor-performance',
  '#/procurement/invoices',
  '#/procurement/exceptions',
  '#/procurement/returns',
  '#/procurement/credit-notes',
  '#/procurement/financial-dashboard',
  '#/procurement/reports',
];

describe('Procurement route resolution', () => {
  for (const route of VALID_ROUTES) {
    it(`does not show "does not exist" fallback for ${route}`, () => {
      mockAuth.mockReturnValue(makeAuth('system_admin'));
      window.location.hash = route;
      render(<App />);

      expect(screen.queryByText('This procurement page does not exist.')).toBeNull();
    });
  }

  it('shows fallback for unknown procurement route', async () => {
    mockAuth.mockReturnValue(makeAuth('system_admin'));
    window.location.hash = '#/procurement/bogus';
    render(<App />);

    expect(await screen.findByText('This procurement page does not exist.', {}, { timeout: 10_000 })).toBeTruthy();
  });

  it('renders dashboard content for bare #/procurement', async () => {
    mockAuth.mockReturnValue(makeAuth('system_admin'));
    window.location.hash = '#/procurement';
    render(<App />);

    expect(screen.queryByText('This procurement page does not exist.')).toBeNull();
    await waitFor(() => {
      expect(screen.getByText('Pending asset registration')).toBeTruthy();
    }, { timeout: 10_000 });
  });

  it('renders vendor performance content for #/procurement/vendor-performance', async () => {
    mockAuth.mockReturnValue(makeAuth('system_admin'));
    window.location.hash = '#/procurement/vendor-performance';
    render(<App />);

    expect(screen.queryByText('This procurement page does not exist.')).toBeNull();
    await waitFor(() => {
      expect(screen.getAllByText('Vendor Performance').length).toBeGreaterThanOrEqual(2);
    });
  });

  it('navigates from dashboard to requests via sidebar link click', async () => {
    mockAuth.mockReturnValue(makeAuth('system_admin'));
    window.location.hash = '#/procurement';
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Pending asset registration')).toBeTruthy();
    });

    const requestsLink = screen.getByText('Purchase requests');
    requestsLink.click();

    await waitFor(() => {
      expect(screen.getByText('Purchase requests')).toBeTruthy();
    });
    expect(screen.queryByText('This procurement page does not exist.')).toBeNull();
  });
});
