import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

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

import { LicensingDashboard } from '../../pages/licensing/LicensingDashboard';
import { SoftwareProductsPage } from '../../pages/software-products/SoftwareProducts';
import { LicenseAgreementsPage } from '../../pages/licensing/LicenseAgreements';

const STAFF_ROLES = ['system_admin', 'it_manager', 'it_support'];

function makeAuth(role) {
  const isSystemAdmin = role === 'system_admin';
  const isITManager = role === 'it_manager';
  const isITSupport = role === 'it_support';
  const isEmployee = role === 'employee';
  const isStaff = role ? STAFF_ROLES.includes(role) : false;
  return {
    access: 'token', isStaff, isAdmin: isSystemAdmin, isSystemAdmin, isITManager, isITSupport, isEmployee,
    isManagerOrAdmin: isSystemAdmin || isITManager,
    isSupportOrAbove: isSystemAdmin || isITManager || isITSupport,
    canViewLicensing: isStaff || isEmployee,
    canManageSoftwareProducts: isSystemAdmin || isITManager,
    canManageLicenseAgreements: isSystemAdmin || isITManager,
    canViewLicenseCosts: isSystemAdmin || isITManager,
    canManageLicenseAllocations: isStaff,
    canManageLicenseInstallations: isStaff,
    canManageLicenseRenewals: isStaff,
    canApproveLicenseRenewals: isSystemAdmin || isITManager,
    canViewLicenseSecrets: isSystemAdmin || isITManager || isITSupport,
    canRevealLicenseSecrets: isSystemAdmin,
    canManageLicenseDocuments: isStaff,
    canManageLicenseCompliance: isSystemAdmin || isITManager,
    canViewLicenseReports: isSystemAdmin || isITManager,
    canViewMySoftware: isEmployee || isStaff,
  };
}

const EMPTY_PAGE = { data: { results: [], count: 0, next: null, previous: null } };

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockAuth.mockImplementation(() => makeAuth('it_manager'));
  mockGet.mockResolvedValue({ data: { active_products: 1, active_agreements: 1, purchased_seats: 10, allocated_seats: 2, available_seats: 8, utilization_percent: 20, expiring_30: 0, expiring_60: 0, expiring_90: 0, expired: 0, pending_renewals: 0, unused_findings: 0, unlicensed_installations: 0, prohibited_findings: 0, expiring_agreements: [], pending_renewals_list: [], annual_recurring_cost_by_currency: { USD: 100 } } });
});

afterEach(() => cleanup());

describe('Licensing dashboard', () => {
  it('renders KPIs', async () => {
    render(<LicensingDashboard />);
    expect(await screen.findByText('Active Products')).toBeTruthy();
  });
});

describe('Software products list', () => {
  it('renders page', async () => {
    mockGet.mockResolvedValueOnce(EMPTY_PAGE);
    render(<SoftwareProductsPage />);
    expect(await screen.findByText('Software Products')).toBeTruthy();
  });
});

describe('License agreements list', () => {
  it('renders page', async () => {
    mockGet.mockResolvedValueOnce(EMPTY_PAGE);
    render(<LicenseAgreementsPage />);
    expect(await screen.findByText('License Agreements')).toBeTruthy();
  });
});
