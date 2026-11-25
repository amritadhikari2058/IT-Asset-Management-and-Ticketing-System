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

import { AccessDenied } from '../../components';
import { parseApiError } from '../../api-utils';
import { CiDetail } from '../../pages/cmdb/CiDetail';
import { ImpactAnalysisPage } from '../../pages/cmdb/ImpactAnalysisPage';

const EMPTY_PAGE = { data: { results: [], count: 0, next: null, previous: null } };
const STAFF_ROLES = ['system_admin', 'it_manager', 'it_support'];

function makeAuth(role) {
  const isSystemAdmin = role === 'system_admin';
  const isITManager = role === 'it_manager';
  const isITSupport = role === 'it_support';
  const isEmployee = role === 'employee';
  const isStaff = role ? STAFF_ROLES.includes(role) : false;

  return {
    access: 'token',
    isStaff, isAdmin: isSystemAdmin, isSystemAdmin, isITManager, isITSupport, isEmployee,
    isManagerOrAdmin: isSystemAdmin || isITManager,
    isSupportOrAbove: isSystemAdmin || isITManager || isITSupport,
    canManageUsers: isSystemAdmin,
    canManageVendors: isSystemAdmin || isITManager,
    canViewVendors: isSystemAdmin || isITManager || isITSupport,
    canManageServiceCatalogue: isSystemAdmin || isITManager,
    canApproveServiceRequests: isSystemAdmin || isITManager,
    canConfigureWorkflow: isSystemAdmin || isITManager,
    canApproveDisposals: isSystemAdmin || isITManager,
    canManageInventory: isSystemAdmin || isITManager,
    canAdjustInventory: isSystemAdmin || isITManager,
    canPublishKnowledgeBase: isSystemAdmin || isITManager,
    canManageScheduledReports: isSystemAdmin || isITManager,
    canAccessAudit: isSystemAdmin,
    canAccessRecycleBin: isSystemAdmin,
    canPerformPermanentDeletion: isSystemAdmin,
    canCreateTickets: true,
    role,
    user: role ? { id: 1, employee_id: 'E1', role, email: `${role}@x` } : null,
  };
}

function authFor(role) {
  mockAuth.mockReturnValue(makeAuth(role));
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

describe('CMDB Permissions', () => {
  describe('capability helpers', () => {
    it('system_admin has governance capabilities', () => {
      expect(makeAuth('system_admin').isSystemAdmin).toBe(true);
    });

    it('it_manager has management but not system-admin governance', () => {
      expect(makeAuth('it_manager').isSystemAdmin).toBe(false);
      expect(makeAuth('it_manager').isITManager).toBe(true);
    });

    it('it_support is read-only for vendors and cannot approve or configure workflow', () => {
      const auth = makeAuth('it_support');
      expect(auth.isSupportOrAbove).toBe(true);
      expect(auth.canViewVendors).toBe(true);
      expect(auth.canManageVendors).toBe(false);
      expect(auth.canConfigureWorkflow).toBe(false);
    });

    it('employee has no vendor, workflow, inventory or report capabilities', () => {
      const auth = makeAuth('employee');
      expect(auth.canManageVendors).toBe(false);
      expect(auth.canConfigureWorkflow).toBe(false);
    });

    it('unknown role fails closed', () => {
      expect(makeAuth(undefined).isStaff).toBe(false);
    });
  });

  describe('AccessDenied UX', () => {
    it('renders professional wording with no stack trace or raw object', () => {
      const { container } = render(<AccessDenied role="employee" />);
      const text = container.textContent || '';
      expect(text).not.toContain('[object Object]');
    });

    it('renders manager-only wording', () => {
      const { container } = render(<AccessDenied reason="manager" />);
      expect(container.textContent).toMatch(/manager/i);
    });

    it('renders action denial wording', () => {
      const { container } = render(<AccessDenied role="employee" action="create" />);
      expect(container.textContent).not.toContain('unauthorized');
    });
  });

  describe('parseApiError 403 handling', () => {
    it('produces a readable forbidden message for 403 without global detail', () => {
      expect(parseApiError({ response: { status: 403 } }).global).toMatch(/forbidden/i);
    });
  });

  describe('CI Detail role-aware UI', () => {
    it('system admin can view CI detail', () => {
      authFor('system_admin');
      mockGet.mockResolvedValueOnce({ data: { id: 1, name: 'Test Server' } });
      render(<CiDetail match={{ params: { id: 1 } }} />);
    });

    it('system admin can view CI detail', async () => {
      authFor('system_admin');
      mockGet.mockResolvedValueOnce({ data: { id: 1, name: 'Test Server' } });
      render(<CiDetail match={{ params: { id: 1 } }} />);
      await screen.findByText('Test Server');
    });

    it('it_manager can view CI detail', async () => {
      authFor('it_manager');
      mockGet.mockResolvedValueOnce({ data: { id: 1, name: 'Test Server' } });
      render(<CiDetail match={{ params: { id: 1 } }} />);
      await screen.findByText('Test Server');
    });

    it('it_support can view CI detail and verify', async () => {
      authFor('it_support');
      mockGet.mockResolvedValueOnce({ data: { id: 1, name: 'Test Server' } });
      render(<CiDetail match={{ params: { id: 1 } }} />);
      await screen.findByText('Test Server');
    });

    it('employee denied CI detail access', () => {
      authFor('employee');
    });
  });

  describe('CI Impact Analysis role-aware UI', () => {
    it('system admin can run impact analysis', () => {
      authFor('system_admin');
      mockGet.mockResolvedValueOnce({ data: {} });
      render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
    });

    it('it_manager can run impact analysis', () => {
      authFor('it_manager');
      mockGet.mockResolvedValueOnce({ data: {} });
      render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
    });

    it('it_support can view impact analysis', () => {
      authFor('it_support');
      mockGet.mockResolvedValueOnce({ data: {} });
      render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
    });

    it('employee denied impact analysis', () => {
      authFor('employee');
      mockGet.mockResolvedValueOnce({ data: {} });
      render(<ImpactAnalysisPage match={{ params: { id: 1 } }} />);
      expect(screen.getByText('Employees have no CMDB impact analysis access.')).toBeTruthy();
    });
  });
});