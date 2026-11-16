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

import { AccessDenied } from './components';
import { VendorsPage, VendorForm } from './vendors';
import { LifecycleDashboard } from './lifecycle-dashboard';
import { LifecycleCases } from './lifecycle-cases';
import { LifecycleForm } from './lifecycle-form';
import { ServicesCatalogue, ServiceRequestDetail } from './services';
import { RulesList, RuleDetail, ApprovalDetail } from './workflow';
import { ScheduledReports } from './scheduled-reports';
import { KnowledgeBaseDetail } from './kb';
import { parseApiError } from './api-utils';

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

describe('capability helpers', () => {
  it('system_admin has governance capabilities', () => {
    const a = makeAuth('system_admin');
    expect(a.canManageVendors).toBe(true);
    expect(a.canConfigureWorkflow).toBe(true);
    expect(a.canAccessAudit).toBe(true);
    expect(a.canAccessRecycleBin).toBe(true);
    expect(a.canPerformPermanentDeletion).toBe(true);
    expect(a.canManageUsers).toBe(true);
  });

  it('it_manager has management but not system-admin governance', () => {
    const m = makeAuth('it_manager');
    expect(m.canManageVendors).toBe(true);
    expect(m.canConfigureWorkflow).toBe(true);
    expect(m.canApproveServiceRequests).toBe(true);
    expect(m.canAccessAudit).toBe(false);
    expect(m.canAccessRecycleBin).toBe(false);
    expect(m.canPerformPermanentDeletion).toBe(false);
    expect(m.canManageUsers).toBe(false);
  });

  it('it_support is read-only for vendors and cannot approve or configure workflow', () => {
    const s = makeAuth('it_support');
    expect(s.canViewVendors).toBe(true);
    expect(s.canManageVendors).toBe(false);
    expect(s.canManageServiceCatalogue).toBe(false);
    expect(s.canApproveServiceRequests).toBe(false);
    expect(s.canConfigureWorkflow).toBe(false);
    expect(s.canApproveDisposals).toBe(false);
    expect(s.isStaff).toBe(true);
  });

  it('employee has no vendor, workflow, inventory or report capabilities', () => {
    const e = makeAuth('employee');
    expect(e.canViewVendors).toBe(false);
    expect(e.canManageVendors).toBe(false);
    expect(e.canConfigureWorkflow).toBe(false);
    expect(e.canManageInventory).toBe(false);
    expect(e.canManageScheduledReports).toBe(false);
    expect(e.isStaff).toBe(false);
  });

  it('unknown role fails closed', () => {
    const u = makeAuth(undefined);
    expect(u.user).toBeNull();
    expect(u.canManageVendors).toBe(false);
    expect(u.canConfigureWorkflow).toBe(false);
    expect(u.canApproveServiceRequests).toBe(false);
    expect(u.isStaff).toBe(false);
  });
});

describe('AccessDenied UX', () => {
  it('renders professional wording with no stack trace or raw object', () => {
    render(<AccessDenied reason="access" />);
    expect(screen.getByText('You do not have permission to access this page.')).toBeTruthy();
    expect(screen.queryByText(/Error/gi)).toBeNull();
    expect(screen.getByRole('link', { name: 'Go to Dashboard' })).toBeTruthy();
  });

  it('renders manager-only wording', () => {
    render(<AccessDenied reason="manager" />);
    expect(screen.getByText('This action requires IT Manager or System Admin permission.')).toBeTruthy();
  });

  it('renders action denial wording', () => {
    render(<AccessDenied reason="action" />);
    expect(screen.getByText('You do not have permission to perform this action.')).toBeTruthy();
  });
});

describe('parseApiError 403 handling', () => {
  it('produces a readable forbidden message for 403 without global detail', () => {
    const out = parseApiError({ response: { status: 403, data: {} } });
    expect(out.global).toBe('Forbidden: you lack permission for this action.');
  });
});

describe('Vendors role-aware UI', () => {
  it('system admin sees New Vendor', () => {
    authFor('system_admin');
    mockGet.mockResolvedValue(EMPTY_PAGE);
    render(<VendorsPage />);
    expect(screen.getByRole('button', { name: /New Vendor/ })).toBeTruthy();
  });

  it('it_manager sees New Vendor', () => {
    authFor('it_manager');
    mockGet.mockResolvedValue(EMPTY_PAGE);
    render(<VendorsPage />);
    expect(screen.getByRole('button', { name: /New Vendor/ })).toBeTruthy();
  });

  it('it_support sees vendors list but no New Vendor button', () => {
    authFor('it_support');
    mockGet.mockResolvedValue(EMPTY_PAGE);
    render(<VendorsPage />);
    expect(screen.queryByRole('button', { name: /New Vendor/ })).toBeNull();
  });

  it('vendor form is access-denied for it_support', () => {
    authFor('it_support');
    render(<VendorForm onSave={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText(/System Admin permission/)).toBeTruthy();
  });

  it('vendor form is accessible for it_manager', () => {
    authFor('it_manager');
    render(<VendorForm onSave={vi.fn()} onClose={vi.fn()} />);
    expect(screen.queryByText(/System Admin permission/)).toBeNull();
  });
});

const REQUEST = {
  id: 10, request_number: 'SR-1', catalogue_item_name: 'Laptop', status: 'pending_approval',
  priority: 'medium', requester: 3, requester_name: 'emp@x', department: 2,
  assigned_to: null, assigned_to_name: null, approval_required: true, approver: null,
  approval_decision: '', approval_reason: '', approved_at: null, fulfilment_ticket: null,
  fulfilment_details: '', description: 'Need laptop', answers: {},
  submitted_at: '2026-11-04T10:00:00Z', updated_at: '2026-11-04T10:00:00Z',
  comments: [], history: [], attachments: [],
};

describe('Services catalogue and requests role-aware UI', () => {
  it('catalogue management controls hidden from it_support', async () => {
    authFor('it_support');
    mockGet.mockResolvedValueOnce({
      data: { results: [
        { id: 1, name: 'Laptop', description: 'd', category: 'hardware', is_active: true, requires_approval: false, creates_ticket: false, estimated_fulfilment_hours: null, instructions: '', form_fields: [] },
      ], count: 1, next: null, previous: null },
    });
    render(<ServicesCatalogue />);
    await screen.findByText('Laptop');
    expect(screen.queryByRole('button', { name: /Edit…/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Delete…/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /\+ New service/ })).toBeNull();
  });

  it('catalogue management controls visible to it_manager', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce({
      data: { results: [
        { id: 1, name: 'Laptop', description: 'd', category: 'hardware', is_active: true, requires_approval: false, creates_ticket: false, estimated_fulfilment_hours: null, instructions: '', form_fields: [] },
      ], count: 1, next: null, previous: null },
    });
    render(<ServicesCatalogue />);
    await screen.findByText('Laptop');
    expect(screen.getByRole('button', { name: /Edit…/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /\+ New service/ })).toBeTruthy();
  });

  it('it_support cannot approve or reject a service request', async () => {
    authFor('it_support');
    mockGet.mockResolvedValueOnce({ data: REQUEST });
    render(<ServiceRequestDetail id="10" />);
    await screen.findByText('SR-1');
    expect(screen.queryByRole('button', { name: /Approve…/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Reject…/ })).toBeNull();
    expect(screen.getByRole('button', { name: /Assign…/ })).toBeTruthy();
  });

  it('it_manager can approve and reject a service request', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce({ data: REQUEST });
    render(<ServiceRequestDetail id="10" />);
    await screen.findByText('SR-1');
    expect(screen.getByRole('button', { name: /Approve…/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Reject…/ })).toBeTruthy();
  });

  it('employee has no internal-comment control', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce({ data: { ...REQUEST, status: 'submitted' } });
    render(<ServiceRequestDetail id="10" />);
    await screen.findByText('SR-1');
    expect(screen.queryByLabelText(/Internal note/)).toBeNull();
  });
});

describe('Workflow role-aware UI', () => {
  const RULE = { id: 1, name: 'Rule 1', trigger: 'ticket_created', is_enabled: true, conditions: {}, actions: [], trigger_display: 'Ticket Created', created_at: null, updated_at: null, created_by_email: 'a@x', updated_by_email: 'b@x', description: '' };

  it('rule create form hidden from it_support', async () => {
    authFor('it_support');
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    render(<RulesList canConfigureWorkflow={false} />);
    expect(await screen.findByText(/View-only: only System Admins can create, edit or toggle automation rules./)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Create rule/ })).toBeNull();
  });

  it('rule create form visible to it_manager', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    render(<RulesList canConfigureWorkflow={true} />);
    expect(screen.getByRole('button', { name: /Create rule/ })).toBeTruthy();
    expect(screen.queryByText(/View-only/)).toBeNull();
  });

  it('rule edit controls hidden from it_support', async () => {
    authFor('it_support');
    mockGet.mockResolvedValueOnce({ data: RULE });
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0 } });
    render(<RuleDetail id="1" canConfigureWorkflow={false} />);
    await screen.findByText('Rule 1');
    expect(screen.queryByRole('link', { name: /Edit rule/ })).toBeNull();
  });

  it('rule edit controls visible to it_manager', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce({ data: RULE });
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0 } });
    render(<RuleDetail id="1" canConfigureWorkflow={true} />);
    await screen.findByText('Rule 1');
    expect(screen.getByRole('link', { name: /Edit rule/ })).toBeTruthy();
  });

  it('approval decision hidden from it_support', async () => {
    authFor('it_support');
    mockGet.mockResolvedValueOnce({ data: {
      id: 1, ticket: 5, ticket_title: 'Broken monitor', operation: 'change_status',
      operation_display: 'Change status', requested_by: 3, requested_by_email: 'emp@x',
      approver: null, approver_email: null, status: 'pending', reason: 'x', context: {},
      decision_comment: '', decided_at: null, decided_by: null, decided_by_email: null,
      created_at: '2026-11-04T10:00:00Z', updated_at: '2026-11-04T10:00:00Z',
    } });
    render(<ApprovalDetail id="1" />);
    await screen.findByText(/Broken monitor/);
    expect(screen.queryByRole('button', { name: /Approve…/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Reject…/ })).toBeNull();
  });

  it('approval decision visible to it_manager', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce({ data: {
      id: 1, ticket: 5, ticket_title: 'Broken monitor', operation: 'change_status',
      operation_display: 'Change status', requested_by: 3, requested_by_email: 'emp@x',
      approver: null, approver_email: null, status: 'pending', reason: 'x', context: {},
      decision_comment: '', decided_at: null, decided_by: null, decided_by_email: null,
      created_at: '2026-11-04T10:00:00Z', updated_at: '2026-11-04T10:00:00Z',
    } });
    render(<ApprovalDetail id="1" />);
    await screen.findByText(/Broken monitor/);
    expect(screen.getByRole('button', { name: /Approve…/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Reject…/ })).toBeTruthy();
  });
});

describe('Scheduled Reports role-aware UI', () => {
  it('it_support is denied scheduled report management', () => {
    authFor('it_support');
    render(<ScheduledReports />);
    expect(screen.getByText(/Scheduled report management is restricted/)).toBeTruthy();
  });

  it('employee is denied scheduled report management', () => {
    authFor('employee');
    render(<ScheduledReports />);
    expect(screen.getByText(/Scheduled report management is restricted/)).toBeTruthy();
  });

  it('it_manager can access scheduled report management', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0 } });
    render(<ScheduledReports />);
    await screen.findByRole('button', { name: /\+ New schedule/ });
    expect(screen.queryByText(/restricted/)).toBeNull();
  });
});

const ARTICLE = (status) => ({
  id: 1, title: `Article ${status}`, status, version: 1, revision_number: 1,
  summary: '', content: '', category: null, tags: [], created_at: null, updated_at: null,
  view_count: 0, author_name: 'emp@x', review_decision: null, reviewed_by_name: null,
  reviewed_at: null, submitted_at: null,
});

describe('Knowledge Base role-aware UI', () => {
  it('it_support can submit for review but not publish', async () => {
    authFor('it_support');
    mockGet.mockResolvedValueOnce({ data: ARTICLE('draft') });
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0 } });
    render(<KnowledgeBaseDetail id="1" />);
    await screen.findByText('Article draft');
    expect(screen.getByRole('button', { name: /Submit for review/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Publish/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Approve/ })).toBeNull();
  });

  it('it_manager can approve and publish', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce({ data: ARTICLE('approved') });
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0 } });
    render(<KnowledgeBaseDetail id="1" />);
    await screen.findByText('Article approved');
    expect(screen.getByRole('button', { name: /Publish/ })).toBeTruthy();
  });

  it('employee sees no knowledge-base governance actions', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce({ data: ARTICLE('published') });
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0 } });
    render(<KnowledgeBaseDetail id="1" />);
    await screen.findByText('Article published');
    expect(screen.queryByRole('button', { name: /Archive/ })).toBeNull();
  });
});

describe('Lifecycle role-aware UI', () => {
  const LIFECYCLE_DASHBOARD = {
    onboarding_in_progress: 2, onboarding_due_7d: 0, onboarding_blocked: 0,
    offboarding_in_progress: 1, offboarding_effective_7d: 0,
    offboarding_unresolved_assets: 0, offboarding_awaiting_deactivation: 0,
    transfers_in_progress: 0, overdue_tasks: 3, failed_automations: 0,
  };

  it('system_admin sees lifecycle dashboard', async () => {
    authFor('system_admin');
    mockGet.mockResolvedValueOnce({ data: LIFECYCLE_DASHBOARD });
    render(<LifecycleDashboard />);
    await screen.findByText('Management KPIs');
  });

  it('employee sees own lifecycle dashboard, not management KPIs', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce({ data: { ...LIFECYCLE_DASHBOARD, onboarding_in_progress: 1 } });
    render(<LifecycleDashboard />);
    await screen.findByText('Your Lifecycle Case');
    expect(screen.queryByText('Management KPIs')).toBeNull();
  });

  it('it_manager sees onboarding case list with Create Case button', async () => {
    authFor('it_manager');
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    render(<LifecycleCases caseType="onboarding" />);
    await screen.findByText('Onboarding');
    expect(screen.getByRole('link', { name: /Create Case/i }) || screen.getByText(/Create Case/i)).toBeTruthy();
  });

  it('employee sees no Create Case button on lifecycle list', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce({ data: { results: [], count: 0, next: null, previous: null } });
    render(<LifecycleCases caseType="onboarding" />);
    await screen.findByText('No cases');
    expect(screen.queryByRole('button', { name: /Create Case/ })).toBeNull();
  });

  it('employee cannot access case creation form', async () => {
    authFor('employee');
    mockGet.mockResolvedValueOnce(EMPTY_PAGE);
    mockGet.mockResolvedValueOnce(EMPTY_PAGE);
    mockGet.mockResolvedValueOnce(EMPTY_PAGE);
    render(<LifecycleForm />);
    await screen.findByText(/Employees cannot create lifecycle cases/);
  });
});
