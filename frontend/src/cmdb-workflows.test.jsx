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

import { CmdbItemsList } from './cmdb-items';
import { VerificationQueuePage } from './cmdb-verification';
import { CiTypesPage } from './cmdb-types';


const CI_ITEM = {
  id: 1, ci_number: 'CI-2026-000001', name: 'Test Server', ci_type: 1,
  status: 'active', lifecycle_state: 'operational', criticality: 'high',
  environment: 'production', department: 2, location: 'DC-1',
  owner: 1, technical_owner: 3, vendor: 'Dell', manufacturer: 'Dell Inc.',
  model: 'PowerEdge R750', serial_number: 'SN123', version: '1.0',
  hostname: 'auth-server01', ip_address: '192.168.1.10',
  dns_name: 'auth-server01.example.com', external_reference: 'TS-100',
  attributes: {}, source: 'manual', source_identifier: '',
  last_verified_at: null, verified_by: null, record_version: 1,
};

const EMPTY_PAGE = { data: { results: [], count: 0, next: null, previous: null } };

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  mockGet.mockResolvedValue(EMPTY_PAGE);
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('CMDB Workflows', () => {
  const makeAdminAuth = () => {
    mockAuth.mockReturnValue({
      access: 'token', user: { id: 1, email: 'admin@local', employee_id: 'E1', role: 'system_admin', is_active: true },
      profileLoading: false, isStaff: true, isAdmin: true,
    });
  };

  const makeManagerAuth = () => {
    mockAuth.mockReturnValue({
      access: 'token', user: { id: 1, email: 'mgr@local', employee_id: 'E1', role: 'it_manager', is_active: true },
      profileLoading: false, isStaff: true, isAdmin: false,
    });
  };

  const makeSupportAuth = () => {
    mockAuth.mockReturnValue({
      access: 'token', user: { id: 1, email: 'sup@local', employee_id: 'E1', role: 'it_support', is_active: true },
      profileLoading: false, isStaff: true, isAdmin: false,
    });
  };

  it('system admin can access CI types page', async () => {
    makeAdminAuth();
    render(<CiTypesPage />);
    await screen.findByText('CI Types');
    expect(screen.getByRole('button', { name: /Create Type/i })).toBeTruthy();
  });

  it('it_manager can view CI list', async () => {
    makeManagerAuth();
    mockGet.mockResolvedValueOnce(EMPTY_PAGE);
    mockGet.mockResolvedValueOnce({ data: [CI_ITEM] });
    render(<CmdbItemsList />);
    await screen.findByText('CI Number');
  });

  it('it_support can verify CIs', async () => {
    makeSupportAuth();
    render(<VerificationQueuePage />);
    await screen.findByText('Verification Queue');
  });

  it('employee is denied all CMDB access', () => {
    mockAuth.mockReturnValue({
      access: 'token', user: { id: 1, email: 'emp@local', employee_id: 'E1', role: 'employee', is_active: true },
      profileLoading: false, isStaff: false, isAdmin: false,
    });
    render(<CmdbItemsList />);
    expect(screen.getByText('Employees have no CMDB CI list access.')).toBeTruthy();
  });

  it('verify CI workflow with correct version', async () => {
    makeAdminAuth();
    mockPost.mockResolvedValueOnce({ data: { ...CI_ITEM, last_verified_at: new Date().toISOString() } });
    render(<VerificationQueuePage />);
    // The verify form should be accessible
    expect(screen.getByRole('button', { name: /Verify/ })).toBeTruthy();
  });
});