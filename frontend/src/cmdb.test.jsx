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

import Dashboard from './cmdb-dashboard';
import { CmdbItemsList } from './cmdb-items';
import { CiTypesPage } from './cmdb-types';
import { VerificationQueue } from './cmdb-verification';

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

describe('CMDB Frontend Behavior', () => {
  describe('Dashboard', () => {
    it('renders dashboard for system_admin', async () => {
      mockAuth.mockReturnValue({
        access: 'token', user: { id: 1, email: 'admin@local', employee_id: 'E1', role: 'system_admin', is_active: true },
        profileLoading: false, isStaff: true, isAdmin: true,
      });
      mockGet.mockResolvedValueOnce({ data: { total_cis: 100, active_cis: 50, critical_cis: 10, unverified_cis: 5, open_drift_findings: 3 } });
      render(<Dashboard />);
      await screen.findByText('CMDB Dashboard');
    });

    it('denies employee access to dashboard', () => {
      mockAuth.mockReturnValue({
        access: 'token', user: { id: 1, email: 'emp@local', employee_id: 'E1', role: 'employee', is_active: true },
        profileLoading: false, isStaff: false, isAdmin: false,
      });
      render(<Dashboard />);
      expect(screen.getByText('Only IT staff can view the CMDB dashboard.')).toBeTruthy();
    });
  });

  describe('CI List', () => {
    it('renders CI list for it_manager', async () => {
      mockAuth.mockReturnValue({
        access: 'token', user: { id: 1, email: 'mgr@local', employee_id: 'E1', role: 'it_manager', is_active: true },
        profileLoading: false, isStaff: true, isAdmin: false,
      });
      mockGet.mockResolvedValueOnce(EMPTY_PAGE);
      mockGet.mockResolvedValueOnce({ data: [{ id: 1, ci_number: 'CI-2026-000001', name: 'Test CI', status: 'active', criticality: 'medium' }] });
      render(<CmdbItemsList />);
      await screen.findByText('CI Number');
    });

    it('denies employee access to CI list', () => {
      mockAuth.mockReturnValue({
        access: 'token', user: { id: 1, email: 'emp@local', employee_id: 'E1', role: 'employee', is_active: true },
        profileLoading: false, isStaff: false, isAdmin: false,
      });
      render(<CmdbItemsList />);
      expect(screen.getByText('Employees have no CMDB CI list access.')).toBeTruthy();
    });
  });

  describe('CI Types', () => {
    it('renders CI types page for system_admin', async () => {
      mockAuth.mockReturnValue({
        access: 'token', user: { id: 1, email: 'admin@local', employee_id: 'E1', role: 'system_admin', is_active: true },
        profileLoading: false, isStaff: true, isAdmin: true,
      });
      render(<CiTypesPage />);
      await screen.findByText('CI Types');
    });

    it('denies employee access to CI types', () => {
      mockAuth.mockReturnValue({
        access: 'token', user: { id: 1, email: 'emp@local', employee_id: 'E1', role: 'employee', is_active: true },
        profileLoading: false, isStaff: false, isAdmin: false,
      });
      render(<CiTypesPage />);
      expect(screen.getByText('Employees have no CMDB CI Types access.')).toBeTruthy();
    });
  });

  describe('Verification Queue', () => {
    it('renders verification queue for it_manager', async () => {
      mockAuth.mockReturnValue({
        access: 'token', user: { id: 1, email: 'mgr@local', employee_id: 'E1', role: 'it_manager', is_active: true },
        profileLoading: false, isStaff: true, isAdmin: false,
      });
      render(<VerificationQueue />);
      await screen.findByText('Verification Queue');
    });

    it('denies employee access to verification queue', () => {
      mockAuth.mockReturnValue({
        access: 'token', user: { id: 1, email: 'emp@local', employee_id: 'E1', role: 'employee', is_active: true },
        profileLoading: false, isStaff: false, isAdmin: false,
      });
      render(<VerificationQueue />);
      expect(screen.getByText('Employees have no CMDB verification access.')).toBeTruthy();
    });
  });
});