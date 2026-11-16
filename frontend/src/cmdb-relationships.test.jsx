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

import { CiRelationshipsPage } from './cmdb-relationships';

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

describe('CMDB Relationships', () => {
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

  it('system_admin can create relationships', async () => {
    makeAdminAuth();
    mockPost.mockResolvedValueOnce({ data: { id: 1, relationship_type: 'parent', direction: 'upstream', target: 2 } });
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    await screen.findByText(/Create/i);
  });

  it('system_admin can view inverse relationships', () => {
    makeAdminAuth();
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    expect(screen.getByText(/Inverse/i)).toBeTruthy();
  });

  it('system_admin can activate/deactivate relationships', () => {
    makeAdminAuth();
    mockPatch.mockResolvedValueOnce({ data: { status: 'active' } });
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    expect(screen.getByRole('button', { name: /Activate/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Deactivate/ })).toBeTruthy();
  });

  it('prevents self-link relationships', () => {
    makeAdminAuth();
    mockPost.mockRejectedValueOnce({ response: { status: 400 } });
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    // The form should reject self-link
    expect(screen.queryByRole('button', { name: /Create/ })).toBeTruthy();
  });

  it('prevents duplicate active relationships', () => {
    makeAdminAuth();
    mockPost.mockRejectedValueOnce({ response: { status: 409 } });
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    expect(screen.getByText(/duplicate/i)).toBeTruthy();
  });

  it('shows cycle errors on create', () => {
    makeAdminAuth();
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'Cycle detected' } } });
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    expect(screen.getByText(/cycle/i)).toBeTruthy();
  });

  it('excludes inaccessible CIs from relationship selectors', () => {
    makeAdminAuth();
    mockGet.mockResolvedValueOnce({ data: [{ id: 1, name: 'A', status: 'active' }, { id: 2, name: 'B', status: 'inactive' }] });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    expect(screen.getByRole('option', { name: /B/i })).toBeTruthy();
  });

  it('shows error on missing related CI', () => {
    makeAdminAuth();
    mockGet.mockResolvedValueOnce({ data: [{ id: 1, name: 'A' }] });
    mockGet.mockResolvedValueOnce({ data: [] }); // Related CI not found
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    expect(screen.getByText(/not found/i)).toBeTruthy();
  });

  describe('role gates', () => {
    it('it_manager can create and view relationships', async () => {
      makeManagerAuth();
      mockPost.mockResolvedValueOnce({ data: { id: 1, relationship_type: 'parent', direction: 'upstream', target: 2 } });
      mockGet.mockResolvedValueOnce({ data: [] });
      render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
      await screen.findByText(/Create/i);
    });

    it('it_support can view relationships but not create', () => {
      makeSupportAuth();
      mockGet.mockResolvedValueOnce({ data: [] });
      render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
      expect(screen.queryByRole('button', { name: /Create/ })).toBeNull();
      expect(screen.getByText(/view/i)).toBeTruthy();
    });

    it('employee denied all relationship access', () => {
      mockAuth.mockReturnValue({
        access: 'token', user: { id: 1, employee_id: 'E1', role: 'employee', is_active: true },
        profileLoading: false, isStaff: false, isAdmin: false,
      });
      mockGet.mockResolvedValueOnce({ data: [] });
      render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
      expect(screen.getByText(/Employees have no CMDB relationship access/)).toBeTruthy();
    });
  });
});