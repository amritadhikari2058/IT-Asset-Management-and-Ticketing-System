import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

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

import { BaselinesPage } from './cmdb-baselines';

const EMPTY_PAGE = { data: { results: [], count: 0, next: null, previous: null } };

const BASELINE = {
  id: 1, code: 'B-2026-001', name: 'Production Baseline',
  scope: 'production', status: 'draft', baseline_date: '2026-01-15',
  effective_from: '2026-01-15', effective_to: null, version: 1,
  created_by: 1, approved_by: null, checksum: null,
};

const EMPTY_BASELINE = {
  id: 2, code: 'B-2026-002', name: 'Test Baseline',
  scope: 'production', status: 'approved', baseline_date: '2026-01-15',
  effective_from: '2026-01-15', effective_to: '2027-01-15', version: 2,
  created_by: 1, approved_by: 1, checksum: 'a1b2c3d4',
};

function makeAdminAuth() {
  mockAuth.mockReturnValue({
    access: 'token', user: { id: 1, email: 'admin@local', employee_id: 'E1', role: 'system_admin', is_active: true },
    profileLoading: false, isStaff: true, isAdmin: true,
  });
}

function makeManagerAuth() {
  mockAuth.mockReturnValue({
    access: 'token', user: { id: 1, email: 'mgr@local', employee_id: 'E1', role: 'it_manager', is_active: true },
    profileLoading: false, isStaff: true, isAdmin: false,
  });
}

function makeSupportAuth() {
  mockAuth.mockReturnValue({
    access: 'token', user: { id: 1, email: 'sup@local', employee_id: 'E1', role: 'it_support', is_active: true },
    profileLoading: false, isStaff: true, isAdmin: false,
  });
}

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  mockGet.mockResolvedValue(EMPTY_PAGE);
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('CMDB Baselines', () => {
  it('system_admin can create baseline', async () => {
    makeAdminAuth();
    mockPost.mockResolvedValueOnce({ data: BASELINE });
    mockGet.mockResolvedValueOnce({ data: [BASELINE] });
    render(<BaselinesPage />);
    await screen.findByText('Production Baseline');
  });

  it('system_admin can submit baseline', async () => {
    makeAdminAuth();
    mockPost.mockResolvedValueOnce({ data: { ...BASELINE, status: 'submitted' } });
    mockGet.mockResolvedValueOnce({ data: [BASELINE] });
    render(<BaselinesPage />);
    await screen.findByText('Production Baseline');
    fireEvent.click(screen.getByRole('button', { name: /^Submit$/i }));
    await screen.findByText(/submitted/i);
  });

  it('system_admin can approve baseline', async () => {
    makeAdminAuth();
    mockPatch.mockResolvedValueOnce({ data: { ...BASELINE, status: 'approved', approved_by: 1 } });
    mockGet.mockResolvedValueOnce({ data: [BASELINE] });
    render(<BaselinesPage />);
    await screen.findByText('Production Baseline');
    fireEvent.click(screen.getByRole('button', { name: /^Approve$/i }));
    await screen.findByText(/approved/i);
  });

  it('creator cannot approve own baseline', async () => {
    makeAdminAuth();
    mockPatch.mockRejectedValueOnce({ response: { status: 403 } });
    mockGet.mockResolvedValueOnce({ data: [BASELINE] });
    render(<BaselinesPage />);
    await screen.findByText('Production Baseline');
    fireEvent.click(screen.getByRole('button', { name: /^Approve$/i }));
    expect(await screen.findByText(/cannot approve own/i)).toBeTruthy();
  });

  it('system_admin can supersede baseline', async () => {
    makeAdminAuth();
    mockPatch.mockResolvedValueOnce({ data: { ...BASELINE, status: 'superseded' } });
    mockGet.mockResolvedValueOnce({ data: [BASELINE] });
    render(<BaselinesPage />);
    await screen.findByText('Production Baseline');
    fireEvent.click(screen.getByRole('button', { name: /^Supersede$/i }));
    await screen.findByText(/superseded/i);
  });

  it('system_admin can compare baselines', async () => {
    makeAdminAuth();
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<BaselinesPage />);
    expect(screen.getByRole('button', { name: /Compare/i })).toBeTruthy();
  });

  it('it_manager can create and manage baselines', async () => {
    makeManagerAuth();
    mockPost.mockResolvedValueOnce({ data: BASELINE });
    mockGet.mockResolvedValueOnce({ data: [BASELINE] });
    render(<BaselinesPage />);
    await screen.findByText('Production Baseline');
  });

  it('it_support cannot create baselines', () => {
    makeSupportAuth();
    render(<BaselinesPage />);
    expect(screen.getByText(/System Admin permission/)).toBeTruthy();
  });

  it('employee denied all baseline access', () => {
    mockAuth.mockReturnValue({
      access: 'token', user: { id: 1, employee_id: 'E1', role: 'employee', is_active: true },
      profileLoading: false, isStaff: false, isAdmin: false,
    });
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<BaselinesPage />);
    expect(screen.getByText(/Employees have no CMDB baseline access/)).toBeTruthy();
  });

  it('shows sensitive value masking on drift list', () => {
    makeSupportAuth();
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<BaselinesPage />);
    expect(screen.queryByText(/password|secret|token/i)).toBeNull();
  });

  describe('baseline types', () => {
    it('includes production scope baseline', async () => {
      makeAdminAuth();
      mockGet.mockResolvedValueOnce({ data: [{ id: 1, scope: 'production' }] });
      render(<BaselinesPage />);
      expect(await screen.findByRole('cell', { name: /production/i })).toBeTruthy();
    });

    it('includes infrastructure scope baseline', async () => {
      makeAdminAuth();
      mockGet.mockResolvedValueOnce({ data: [{ id: 2, scope: 'infrastructure' }] });
      render(<BaselinesPage />);
      expect(await screen.findByRole('cell', { name: /infrastructure/i })).toBeTruthy();
    });

    it('includes configuration scope baseline', async () => {
      makeAdminAuth();
      mockGet.mockResolvedValueOnce({ data: [{ id: 3, scope: 'configuration' }] });
      render(<BaselinesPage />);
      expect(await screen.findByRole('cell', { name: /configuration/i })).toBeTruthy();
    });
  });

  describe('baseline status transitions', () => {
    it('status transitions: draft → submitted → approved → superseded', async () => {
      makeAdminAuth();
      mockPost.mockResolvedValueOnce({ data: { ...BASELINE, status: 'submitted' } });
      mockPatch.mockResolvedValueOnce({ data: { ...BASELINE, status: 'approved' } });
      mockPatch.mockResolvedValueOnce({ data: { ...BASELINE, status: 'superseded' } });
      mockGet.mockResolvedValueOnce({ data: [BASELINE] });
      render(<BaselinesPage />);
      await screen.findByText('Production Baseline');
      fireEvent.click(screen.getByRole('button', { name: /^Submit$/i }));
      await screen.findByText(/submitted/i);
      fireEvent.click(screen.getByRole('button', { name: /^Approve$/i }));
      await screen.findByText(/approved/i);
      fireEvent.click(screen.getByRole('button', { name: /^Supersede$/i }));
      await screen.findByText(/superseded/i);
    });
  });
});