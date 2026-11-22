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
    await screen.findByRole('button', { name: /Add Relationship/i });
  });

  it('system_admin can view inverse relationships', async () => {
    makeAdminAuth();
    mockGet
      .mockResolvedValueOnce({ data: { id: 1, ci_number: 'CI #1', name: 'A' } }) // ci detail
      .mockResolvedValueOnce({ data: [{ id: 5, relationship_type: 'depends_on', source_ci: 2, target_ci: 1, source_ci_number: 'CI #2', status: 'active' }] }) // relationships
      .mockResolvedValueOnce({ data: { results: [{ id: 2, ci_number: 'CI #2', name: 'B' }] } }); // CI options
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    expect(await screen.findByRole('heading', { name: /Incoming Relationships/i })).toBeTruthy();
    expect(await screen.findByRole('heading', { name: /Outgoing Relationships/i })).toBeTruthy();
    expect(await screen.findByRole('link', { name: /CI #2 — B/i })).toBeTruthy();
  });

  it('system_admin can activate/deactivate relationships', async () => {
    makeAdminAuth();
    mockPost.mockResolvedValueOnce({ data: { id: 1, relationship_type: 'parent', direction: 'upstream', target: 2 } });
    mockGet.mockResolvedValue({ data: { results: [{ id: 1, relationship_type: 'parent', direction: 'upstream', source_ci: 1, target_ci: 2, status: 'active' }, { id: 2, relationship_type: 'parent', direction: 'upstream', source_ci: 1, target_ci: 3, status: 'inactive' }] } });
    mockPatch.mockResolvedValueOnce({ data: { status: 'active' } });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    await screen.findByRole('button', { name: /Activate/ });
    await screen.findByRole('button', { name: /Deactivate/ });
  });

  it('prevents self-link relationships', async () => {
    makeAdminAuth();
    mockGet
      .mockResolvedValueOnce({ data: { id: 1, ci_number: 'CI #1', name: 'A' } }) // ci detail
      .mockResolvedValueOnce({ data: [] }) // relationships
      .mockResolvedValueOnce({ data: [{ id: 2, ci_number: 'CI #2', name: 'B' }] }); // CI options
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { detail: 'A CI cannot be related to itself.' } } });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    await screen.findByRole('option', { name: /CI #2/i });
    fireEvent.change(screen.getByLabelText(/Related CI/i), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText(/Relationship Type/i), { target: { value: 'depends_on' } });
    fireEvent.click(screen.getByRole('button', { name: /Add Relationship/i }));
    expect(await screen.findByText(/cannot be related to itself/i)).toBeTruthy();
  });

  it('prevents duplicate active relationships', async () => {
    makeAdminAuth();
    mockGet
      .mockResolvedValueOnce({ data: { id: 1, ci_number: 'CI #1', name: 'A' } }) // ci detail
      .mockResolvedValueOnce({ data: [] }) // relationships
      .mockResolvedValueOnce({ data: [{ id: 2, ci_number: 'CI #2', name: 'B' }] }); // CI options
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'This relationship already exists.' } } });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    await screen.findByRole('option', { name: /CI #2/i });
    fireEvent.change(screen.getByLabelText(/Related CI/i), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText(/Relationship Type/i), { target: { value: 'depends_on' } });
    fireEvent.click(screen.getByRole('button', { name: /Add Relationship/i }));
    expect(await screen.findByText(/This relationship already exists/i)).toBeTruthy();
  });

  it('shows cycle errors on create', async () => {
    makeAdminAuth();
    mockGet
      .mockResolvedValueOnce({ data: { id: 1, ci_number: 'CI #1', name: 'A' } }) // ci detail
      .mockResolvedValueOnce({ data: [] }) // relationships
      .mockResolvedValueOnce({ data: [{ id: 2, ci_number: 'CI #2', name: 'B' }] }); // CI options
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'Cycle detected' } } });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    await screen.findByRole('option', { name: /CI #2/i });
    fireEvent.change(screen.getByLabelText(/Related CI/i), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText(/Relationship Type/i), { target: { value: 'depends_on' } });
    fireEvent.click(screen.getByRole('button', { name: /Add Relationship/i }));
    expect(await screen.findByText(/Cycle detected/i)).toBeTruthy();
  });

  it('excludes inaccessible CIs from relationship selectors', async () => {
    makeAdminAuth();
    mockGet
      .mockResolvedValueOnce({ data: { id: 1, ci_number: 'CI #1', name: 'A' } }) // ci detail
      .mockResolvedValueOnce({ data: [] }) // relationships for this CI
      .mockResolvedValueOnce({ data: { results: [{ id: 1, ci_number: 'CI #1', name: 'A', status: 'active' }, { id: 2, ci_number: 'CI #2', name: 'B', status: 'inactive' }] } }); // related CI choices
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    expect(await screen.findByRole('option', { name: /CI #2/i })).toBeTruthy();
  });

  it('shows error on missing related CI', async () => {
    makeAdminAuth();
    mockGet
      .mockResolvedValueOnce({ data: { id: 1, ci_number: 'CI #1', name: 'A' } }) // ci detail
      .mockResolvedValueOnce({ data: [] }) // relationships for this CI
      .mockResolvedValueOnce({ data: { results: [{ id: 2, ci_number: 'CI #2', name: 'B' }] } }); // related CI choices
    mockPost.mockRejectedValueOnce({ response: { status: 404, data: { detail: 'Related CI not found.' } } });
    render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
    await screen.findByRole('option', { name: /CI #2/i });
    fireEvent.change(screen.getByLabelText(/Related CI/i), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText(/Relationship Type/i), { target: { value: 'depends_on' } });
    fireEvent.click(screen.getByRole('button', { name: /Add Relationship/i }));
    expect(await screen.findByText(/not found/i)).toBeTruthy();
  });

  describe('role gates', () => {
    it('it_manager can create and view relationships', async () => {
      makeManagerAuth();
      mockPost.mockResolvedValueOnce({ data: { id: 1, relationship_type: 'parent', direction: 'upstream', target: 2 } });
      mockGet.mockResolvedValueOnce({ data: [] });
      render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
      await screen.findByRole('button', { name: /Add Relationship/i });
    });

    it('it_support can view relationships but not create', () => {
      makeSupportAuth();
      mockGet.mockResolvedValueOnce({ data: [] });
      render(<CiRelationshipsPage match={{ params: { id: 1 } }} />);
      expect(screen.queryByRole('button', { name: /Add Relationship/i })).toBeNull();
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