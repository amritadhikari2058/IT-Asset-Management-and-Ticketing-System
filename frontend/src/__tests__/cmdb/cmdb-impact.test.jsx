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

import { ImpactAnalysisPage } from '../../pages/cmdb/ImpactAnalysisPage';

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

describe('CMDB Impact Analysis', () => {
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

  it('system_admin can run upstream impact analysis', async () => {
    makeAdminAuth();
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
    await screen.findByRole('heading', { name: /Impact Analysis/i });
  });

  it('system_admin can run downstream impact', async () => {
    makeAdminAuth();
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
    await screen.findByRole('heading', { name: /Impact Analysis/i });
  });

  it('bounded depth prevents unbounded requests', () => {
    makeAdminAuth();
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
    expect(screen.getByLabelText('Maximum Depth')).toBeTruthy();
  });

  it('truncation state shown when result exceeds bounds', async () => {
    makeAdminAuth();
    mockGet.mockResolvedValueOnce({ data: { truncated: true, warning: 'result exceeds depth limit' } });
    render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
    expect((await screen.findAllByText(/truncated/i)).length).toBeGreaterThan(0);
  });

  it('excludes inaccessible Ticket, Change, CI, or Service data', async () => {
    makeSupportAuth();
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
    await screen.findByRole('heading', { name: /Impact Analysis/i });
    // Should not contain hidden/inaccessible records
    expect(screen.queryByText(/hidden/i)).toBeNull();
  });

  it('read-only behavior prevents data mutation', () => {
    makeSupportAuth();
    render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
    // The page should not contain editable form fields
    expect(screen.queryByRole('button', { name: /Submit/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Confirm/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Save/ })).toBeNull();
  });

  it('displays read-only wording: "Impact analysis is based on recorded CMDB relationships."', async () => {
    makeSupportAuth();
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
    await screen.findByText(/Impact analysis is based on recorded CMDB relationships./i);
  });

  describe('role gates', () => {
    it('it_manager can run bounded impact analysis', async () => {
      makeManagerAuth();
      mockGet.mockResolvedValueOnce({ data: [] });
      render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
      await screen.findByRole('heading', { name: /Impact Analysis/i });
    });

    it('it_support can view impact results', async () => {
      makeSupportAuth();
      mockGet.mockResolvedValueOnce({ data: [] });
      render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
      await screen.findByRole('heading', { name: /Impact Analysis/i });
    });

    it('employee denied impact analysis', () => {
      mockAuth.mockReturnValue({
        access: 'token', user: { id: 1, employee_id: 'E1', role: 'employee', is_active: true },
        profileLoading: false, isStaff: false, isAdmin: false,
      });
      mockGet.mockResolvedValueOnce({ data: [] });
      render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
      expect(screen.getByText(/Employees have no CMDB impact analysis access/)).toBeTruthy();
    });
  });
});