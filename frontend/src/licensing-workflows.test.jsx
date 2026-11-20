import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

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
vi.mock('./auth', () => ({ useAuth: (...a) => mockAuth(...a) }));

import { LicenseAgreementDetail } from './license-agreement-detail';

function makeAuth() {
  return {
    access: 'token',
    isStaff: true,
    canViewLicensing: true,
    canViewLicenseCosts: true,
    canManageLicenseAgreements: true,
  };
}

const AGREEMENT = {
  id: 3,
  agreement_number: 'LIC-2026-00001',
  product_name: 'Acrobat',
  status: 'active',
  is_unlimited: false,
  quantity_allocated: 2,
  quantity_purchased: 5,
  quantity_available: 3,
  utilization_percent: 40,
  currency: 'USD',
  total_cost: '1000.00',
  expiry_date: '2027-01-01',
  renewal_date: '2026-12-01',
};

const HISTORY = [
  {
    id: 900,
    event_type: 'allocation_revoked',
    previous_status: 'assigned',
    new_status: 'revoked',
    actor_email: 'manager@x.io',
    detail: { reason: 'Returned laptop' },
    created_at: '2026-02-01T09:30:00Z',
  },
  {
    id: 899,
    event_type: 'agreement_activated',
    previous_status: '',
    new_status: 'active',
    actor_email: null,
    detail: {},
    created_at: '2026-01-02T09:30:00Z',
  },
];

function setupGet(history = HISTORY) {
  mockGet.mockImplementation(async (url) => {
    if (String(url).endsWith('/history/')) return { data: history };
    if (String(url).endsWith('/utilization/')) throw new Error('no utilization');
    return { data: AGREEMENT };
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockAuth.mockImplementation(() => makeAuth());
  setupGet();
});

afterEach(() => cleanup());

describe('License agreement detail - history integration', () => {
  it('renders agreement and allocation lifecycle events from the history endpoint', async () => {
    render(<LicenseAgreementDetail id={3} />);

    await screen.findByText('Allocation Revoked');
    expect(mockGet).toHaveBeenCalledWith('/licensing/agreements/3/history/');
    expect(screen.getByText('Agreement Activated')).toBeTruthy();
    expect(screen.getByText('Assigned → Revoked')).toBeTruthy();
    expect(screen.getByText('manager@x.io')).toBeTruthy();
    expect(screen.getByText('System')).toBeTruthy();
    expect(screen.getByText('Reason: Returned laptop')).toBeTruthy();
  });

  it('shows an empty state when the agreement has no history', async () => {
    setupGet([]);
    render(<LicenseAgreementDetail id={3} />);

    await screen.findByText('No history recorded for this agreement.');
  });

  it('shows a permission message for a forbidden history request and still renders the agreement', async () => {
    mockGet.mockImplementation(async (url) => {
      if (String(url).endsWith('/history/')) throw { response: { status: 403 } };
      if (String(url).endsWith('/utilization/')) throw new Error('no utilization');
      return { data: AGREEMENT };
    });
    render(<LicenseAgreementDetail id={3} />);

    await screen.findByText('You do not have permission to view this agreement history.');
    expect(screen.getByText('LIC-2026-00001')).toBeTruthy();
  });

  it('shows the API error detail when history fails to load', async () => {
    mockGet.mockImplementation(async (url) => {
      if (String(url).endsWith('/history/')) {
        throw { response: { status: 500, data: { detail: 'History unavailable.' } } };
      }
      if (String(url).endsWith('/utilization/')) throw new Error('no utilization');
      return { data: AGREEMENT };
    });
    render(<LicenseAgreementDetail id={3} />);

    await screen.findByText('History unavailable.');
  });
});
