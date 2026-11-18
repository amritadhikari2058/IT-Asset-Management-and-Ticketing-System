import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

// ── Mock useAuth ──────────────────────────────────────────────────────────
const { mockAuth } = vi.hoisted(() => ({
  mockAuth: vi.fn(),
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
  AuthProvider: ({ children }) => children,
}));

// ── Mock every feature component imported by App.jsx ─────────────────────
vi.mock('./pages', () => ({
  Assets: () => <div data-testid="mock-Assets">Assets</div>,
  Categories: () => <div data-testid="mock-Categories">Categories</div>,
  Departments: () => <div data-testid="mock-Departments">Departments</div>,
  EmployeeDetail: () => <div data-testid="mock-EmployeeDetail">EmployeeDetail</div>,
  Login: () => <div data-testid="mock-Login">Login</div>,
  Profile: () => <div data-testid="mock-Profile">Profile</div>,
  RecycleBin: () => <div data-testid="mock-RecycleBin">RecycleBin</div>,
  ResetPassword: () => <div data-testid="mock-ResetPassword">ResetPassword</div>,
  SLAConfig: () => <div data-testid="mock-SLAConfig">SLAConfig</div>,
  SLAReport: () => <div data-testid="mock-SLAReport">SLAReport</div>,
  Tickets: () => <div data-testid="mock-Tickets">Tickets</div>,
  Users: () => <div data-testid="mock-Users">Users</div>,
  VerifyEmail: () => <div data-testid="mock-VerifyEmail">VerifyEmail</div>,
}));
vi.mock('./kb', () => ({
  KnowledgeBase: () => <div data-testid="mock-KnowledgeBase">KnowledgeBase</div>,
  KnowledgeBaseCompare: () => <div data-testid="mock-KnowledgeBaseCompare">KnowledgeBaseCompare</div>,
  KnowledgeBaseDetail: () => <div data-testid="mock-KnowledgeBaseDetail">KnowledgeBaseDetail</div>,
  KnowledgeBaseReviewQueue: () => <div data-testid="mock-KnowledgeBaseReviewQueue">KnowledgeBaseReviewQueue</div>,
  KnowledgeBaseRevisionDetail: () => <div data-testid="mock-KnowledgeBaseRevisionDetail">KnowledgeBaseRevisionDetail</div>,
  KnowledgeBaseRevisions: () => <div data-testid="mock-KnowledgeBaseRevisions">KnowledgeBaseRevisions</div>,
}));
vi.mock('./assets', () => ({
  AssetForm: () => <div data-testid="mock-AssetForm">AssetForm</div>,
  AssetDetail: () => <div data-testid="mock-AssetDetail">AssetDetail</div>,
}));
vi.mock('./audit', () => ({
  AuditLogPage: () => <div data-testid="mock-AuditLogPage">AuditLogPage</div>,
}));
vi.mock('./vendors', () => ({
  VendorForm: () => <div data-testid="mock-VendorForm">VendorForm</div>,
  VendorsPage: () => <div data-testid="mock-VendorsPage">VendorsPage</div>,
  VendorDetail: () => <div data-testid="mock-VendorDetail">VendorDetail</div>,
}));
vi.mock('./tickets', () => ({
  TicketForm: () => <div data-testid="mock-TicketForm">TicketForm</div>,
  TicketDetail: () => <div data-testid="mock-TicketDetail">TicketDetail</div>,
}));
vi.mock('./changes', () => ({
  ChangesPage: () => <div data-testid="mock-ChangesPage">ChangesPage</div>,
}));
vi.mock('./cmdb-dashboard', () => ({
  default: () => <div data-testid="mock-CmdbDashboard">CmdbDashboard</div>,
}));
vi.mock('./ticket-queues', () => ({
  TicketQueuesPage: () => <div data-testid="mock-TicketQueuesPage">TicketQueuesPage</div>,
}));
vi.mock('./ticket-operations', () => ({
  TicketOperationsDashboard: () => <div data-testid="mock-TicketOperationsDashboard">TicketOperationsDashboard</div>,
}));
vi.mock('./ticket-canned-responses', () => ({
  CannedResponsesPage: () => <div data-testid="mock-CannedResponsesPage">CannedResponsesPage</div>,
}));
vi.mock('./ticket-templates', () => ({
  TicketTemplatesPage: () => <div data-testid="mock-TicketTemplatesPage">TicketTemplatesPage</div>,
}));
vi.mock('./ticket-saved-views', () => ({
  SavedTicketViews: () => <div data-testid="mock-SavedTicketViews">SavedTicketViews</div>,
}));
vi.mock('./ticket-satisfaction', () => ({
  TicketSatisfactionSurvey: () => <div data-testid="mock-TicketSatisfactionSurvey">TicketSatisfactionSurvey</div>,
}));
vi.mock('./ticket-merge', () => ({
  TicketMergeDialog: () => <div data-testid="mock-TicketMergeDialog">TicketMergeDialog</div>,
}));
vi.mock('./ticket-timeline', () => ({
  TicketTimeline: () => <div data-testid="mock-TicketTimeline">TicketTimeline</div>,
}));
vi.mock('./ticket-collaboration', () => ({
  TicketCollaborationPanel: () => <div data-testid="mock-TicketCollaborationPanel">TicketCollaborationPanel</div>,
}));
vi.mock('./ticket-relations', () => ({
  TicketRelationsPanel: () => <div data-testid="mock-TicketRelationsPanel">TicketRelationsPanel</div>,
}));
vi.mock('./notifications', () => ({
  Notifications: () => <div data-testid="mock-Notifications">Notifications</div>,
  NotifBadge: () => <div data-testid="mock-NotifBadge">NotifBadge</div>,
}));
vi.mock('./maintenance', () => ({
  Maintenance: () => <div data-testid="mock-Maintenance">Maintenance</div>,
}));
vi.mock('./disposals', () => ({
  Disposals: () => <div data-testid="mock-Disposals">Disposals</div>,
}));
vi.mock('./dashboard', () => ({
  Dashboard: () => <div data-testid="mock-Dashboard">Dashboard</div>,
  DepartmentReports: () => <div data-testid="mock-DepartmentReports">DepartmentReports</div>,
}));
vi.mock('./self-service', () => ({
  SelfService: () => <div data-testid="mock-SelfService">SelfService</div>,
}));
vi.mock('./saved-reports', () => ({
  SavedReports: () => <div data-testid="mock-SavedReports">SavedReports</div>,
}));
vi.mock('./scheduled-reports', () => ({
  ScheduledReports: () => <div data-testid="mock-ScheduledReports">ScheduledReports</div>,
}));
vi.mock('./settings', () => ({
  NotificationSettings: () => <div data-testid="mock-NotificationSettings">NotificationSettings</div>,
}));
vi.mock('./privacy', () => ({
  Privacy: () => <div data-testid="mock-Privacy">Privacy</div>,
}));
vi.mock('./monitoring', () => ({
  Monitoring: () => <div data-testid="mock-Monitoring">Monitoring</div>,
}));
vi.mock('./retention', () => ({
  Retention: () => <div data-testid="mock-Retention">Retention</div>,
}));
vi.mock('./backup', () => ({
  Backup: () => <div data-testid="mock-Backup">Backup</div>,
}));
vi.mock('./services', () => ({
  ServicesCatalogue: () => <div data-testid="mock-ServicesCatalogue">ServicesCatalogue</div>,
  MyServiceRequests: () => <div data-testid="mock-MyServiceRequests">MyServiceRequests</div>,
  ServiceRequestDetail: () => <div data-testid="mock-ServiceRequestDetail">ServiceRequestDetail</div>,
}));
vi.mock('./inventory', () => ({
  default: () => <div data-testid="mock-Inventory">Inventory</div>,
  InventoryItems: () => <div data-testid="mock-InventoryItems">InventoryItems</div>,
  StockItemDetail: () => <div data-testid="mock-StockItemDetail">StockItemDetail</div>,
  StockItemForm: () => <div data-testid="mock-StockItemForm">StockItemForm</div>,
}));
vi.mock('./inventory-ops', () => ({
  ReceiveStock: () => <div data-testid="mock-ReceiveStock">ReceiveStock</div>,
  Reservations: () => <div data-testid="mock-Reservations">Reservations</div>,
  TransactionHistory: () => <div data-testid="mock-TransactionHistory">TransactionHistory</div>,
  FulfilServiceRequest: () => <div data-testid="mock-FulfilServiceRequest">FulfilServiceRequest</div>,
}));
vi.mock('./workflow', () => ({
  default: () => <div data-testid="mock-Workflow">Workflow</div>,
}));
vi.mock('./approvals', () => ({
  ApprovalCenter: () => <div data-testid="mock-ApprovalCenter">ApprovalCenter</div>,
}));
vi.mock('./lifecycle', () => ({
  LifecycleDashboard: () => <div data-testid="mock-LifecycleDashboard">LifecycleDashboard</div>,
  LifecycleCases: () => <div data-testid="mock-LifecycleCases">LifecycleCases</div>,
  LifecycleForm: () => <div data-testid="mock-LifecycleForm">LifecycleForm</div>,
  LifecycleDetail: () => <div data-testid="mock-LifecycleDetail">LifecycleDetail</div>,
}));
vi.mock('./procurement', () => ({
  default: () => <div data-testid="mock-ProcurementRouter">ProcurementRouter</div>,
}));
vi.mock('./licensing', () => ({
  default: () => <div data-testid="mock-LicensingRouter">LicensingRouter</div>,
}));
vi.mock('./components/problem-management/problem-list', () => ({
  ProblemList: () => <div data-testid="mock-ProblemList">ProblemList</div>,
}));
vi.mock('./components/problem-management/problem-detail', () => ({
  ProblemDetail: () => <div data-testid="mock-ProblemDetail">ProblemDetail</div>,
}));
vi.mock('./features/monitoring/MonitoringOverview', () => ({
  MonitoringOverview: () => <div data-testid="mock-MonitoringOverview">MonitoringOverview</div>,
}));
vi.mock('./features/monitoring/SourceManagement', () => ({
  SourceManagement: () => <div data-testid="mock-SourceManagement">SourceManagement</div>,
}));
vi.mock('./features/monitoring/AlertList', () => ({
  AlertList: () => <div data-testid="mock-AlertList">AlertList</div>,
}));
vi.mock('./features/monitoring/AlertDetail', () => ({
  AlertDetail: () => <div data-testid="mock-AlertDetail">AlertDetail</div>,
}));
vi.mock('./features/monitoring/PolicyManagement', () => ({
  PolicyManagement: () => <div data-testid="mock-PolicyManagement">PolicyManagement</div>,
}));

import App from './App';

function authCaps(role = 'system_admin', isActive = true) {
  const isStaff = ['system_admin', 'it_manager', 'it_support'].includes(role);
  const isAdmin = role === 'system_admin';
  const canUseMonitoring = !!isStaff && isActive;
  const canUseProblemManagement = !!isStaff && isActive;
  return {
    access: true,
    logout: vi.fn(),
    user: { employee_id: 'EMP001', role },
    profileLoading: false,
    role,
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isAdmin,
    isStaff,
    canManageScheduledReports: role === 'system_admin',
    canViewVendors: role !== 'employee',
    canViewProcurement: isStaff,
    canViewProcurementReports: role === 'system_admin' || role === 'it_manager',
    canManageUsers: role === 'system_admin' || role === 'it_manager',
    canManageServiceCatalogue: role === 'system_admin',
    canUseMonitoring,
    canUseProblemManagement,
  };
}

function renderApp(role = 'system_admin', isActive = true) {
  const isStaff = ['system_admin', 'it_manager', 'it_support'].includes(role);
  const isAdmin = role === 'system_admin';
  const canUseMonitoring = !!isStaff && isActive;
  const canUseProblemManagement = !!isStaff && isActive;
  mockAuth.mockReturnValue({
    access: true,
    logout: vi.fn(),
    user: { employee_id: 'EMP001', role },
    profileLoading: false,
    role,
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isAdmin,
    isStaff,
    canManageScheduledReports: role === 'system_admin',
    canViewVendors: role !== 'employee',
    canViewProcurement: isStaff,
    canViewProcurementReports: role === 'system_admin' || role === 'it_manager',
    canManageUsers: role === 'system_admin' || role === 'it_manager',
    canManageServiceCatalogue: role === 'system_admin',
    canUseMonitoring,
    canUseProblemManagement,
  });
  return render(<App />);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('Application sidebar navigation', () => {
  describe('Group ordering', () => {
    it('renders groups in the intended order', () => {
      renderApp('system_admin');
      const sections = Array.from(
        document.querySelectorAll('.sidenav-section')
      ).map((el) => (el.textContent || '').trim());
      expect(sections[0]).toBe('Overview');
      expect(sections[1]).toBe('Service Operations');
      expect(sections[2]).toBe('Asset Operations');
      expect(sections[3]).toBe('Procurement');
      expect(sections[4]).toBe('Administration');
    });
  });

  describe('Concise module labels', () => {
    it('shows concise labels without long legacy names', () => {
      renderApp('system_admin');
      expect(screen.getByRole('link', { name: 'Dashboard' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Tickets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Monitoring' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Problems' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Changes' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Services' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Assets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'CMDB' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Procurement' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Users' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Categories' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Departments' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'SLA' })).toBeTruthy();
      expect(screen.getByRole('link', { name: /Notifications/ })).toBeTruthy();
    });

    it('does not show long legacy labels', () => {
      renderApp('system_admin');
      expect(screen.queryByText('Ticket Queues')).toBeNull();
      expect(screen.queryByText('Operations')).toBeNull();
      expect(screen.queryByText('Lifecycle')).toBeNull();
      expect(screen.queryByText('Workflow')).toBeNull();
      expect(screen.queryByText('Inventory')).toBeNull();
      expect(screen.queryByText('Disposals')).toBeNull();
      expect(screen.queryByText('Software Dashboard')).toBeNull();
      expect(screen.queryByText('Vendors')).toBeNull();
      expect(screen.queryByText('Employees')).toBeNull();
    });
  });

  describe('Role visibility — System Admin', () => {
    it('shows operational and administrative groups', () => {
      renderApp('system_admin');
      expect(screen.getByRole('link', { name: 'Dashboard' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Tickets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Monitoring' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Problems' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Changes' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Services' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Assets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'CMDB' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Procurement' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Users' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Categories' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Departments' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'SLA' })).toBeTruthy();
      expect(screen.getByRole('link', { name: /Notifications/ })).toBeTruthy();
    });
  });

  describe('Role visibility — IT Manager', () => {
    it('shows operational modules and permitted governance modules', () => {
      renderApp('it_manager');
      expect(screen.getByRole('link', { name: 'Dashboard' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Tickets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Monitoring' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Problems' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Changes' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Services' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Assets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'CMDB' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Procurement' })).toBeTruthy();
      // IT Manager is not system_admin → isAdmin false → no Administration
      expect(screen.queryByRole('link', { name: 'Users' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Categories' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Departments' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'SLA' })).toBeNull();
      expect(screen.queryByRole('link', { name: /Notifications/ })).toBeNull();
    });
  });

  describe('Role visibility — IT Support', () => {
    it('shows day-to-day support modules without unauthorized administration', () => {
      renderApp('it_support');
      expect(screen.getByRole('link', { name: 'Dashboard' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Tickets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Monitoring' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Problems' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Changes' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Services' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Assets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'CMDB' })).toBeTruthy();
      // Administration is isAdmin only → not visible to IT Support
      expect(screen.queryByRole('link', { name: 'Users' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Categories' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Departments' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'SLA' })).toBeNull();
      expect(screen.queryByRole('link', { name: /Notifications/ })).toBeNull();
    });
  });

  describe('Role visibility — Employee', () => {
    it('shows only employee-facing destinations', () => {
      renderApp('employee');
      expect(screen.getByRole('link', { name: 'Dashboard' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Tickets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Services' })).toBeTruthy();
      // Employee is not staff → no Monitoring, Problems, Changes, Assets, CMDB, Procurement
      expect(screen.queryByRole('link', { name: 'Monitoring' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Problems' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Changes' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Assets' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'CMDB' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Procurement' })).toBeNull();
      // Employee is not admin → no Administration
      expect(screen.queryByRole('link', { name: 'Users' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Categories' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Departments' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'SLA' })).toBeNull();
      expect(screen.queryByRole('link', { name: /Notifications/ })).toBeNull();
    });
  });

  describe('Access control — inactive and unknown roles', () => {
    it('inactive user loses monitoring/problem capabilities', () => {
      const auth = authCaps('system_admin', false);
      expect(auth.isStaff).toBe(true);
      expect(auth.isAdmin).toBe(true);
      expect(auth.canUseMonitoring).toBe(false);
      expect(auth.canUseProblemManagement).toBe(false);
    });

    it('unknown role has no staff or admin privileges', () => {
      const auth = authCaps('unknown-role', true);
      expect(auth.isAdmin).toBe(false);
      expect(auth.isStaff).toBe(false);
      expect(auth.canUseMonitoring).toBe(false);
      expect(auth.canUseProblemManagement).toBe(false);
    });
  });

  describe('Account area', () => {
    it('shows Profile link in the sidebar footer', () => {
      renderApp('system_admin');
      const profileLink = screen.getByRole('link', { name: 'EMP001' });
      expect(profileLink.getAttribute('href')).toBe('#/profile');
    });

    it('shows Sign out button in the sidebar footer', () => {
      renderApp('system_admin');
      const signout = screen.getByRole('button', { name: /Log out/i });
      expect(signout).toBeTruthy();
    });
  });

  describe('Active state', () => {
    it('marks active route with aria-current="page"', () => {
      renderApp('system_admin');
      const links = screen.getAllByRole('link', { name: 'Tickets' });
      const navLink = links.find((l) => l.getAttribute('href') === '#/tickets');
      expect(navLink.getAttribute('aria-current')).toBe('page');
    });
  });

  describe('Route availability', () => {
    it('has existing Assets route', () => {
      renderApp('system_admin');
      expect(screen.getByRole('link', { name: 'Assets' }).getAttribute('href')).toBe('#/assets');
    });
    it('has existing Monitoring route', () => {
      renderApp('system_admin');
      expect(screen.getByRole('link', { name: 'Monitoring' }).getAttribute('href')).toBe('#/monitoring');
    });
    it('has existing Problems route', () => {
      renderApp('system_admin');
      expect(screen.getByRole('link', { name: 'Problems' }).getAttribute('href')).toBe('#/problem-management');
    });
    it('has existing Tickets route', () => {
      renderApp('system_admin');
      const links = screen.getAllByRole('link', { name: 'Tickets' });
      const navLink = links.find((l) => l.getAttribute('href') === '#/tickets');
      expect(navLink).toBeTruthy();
    });
  });

  describe('Unsupported destinations absent', () => {
    it('does not render My Work', () => {
      renderApp('system_admin');
      expect(screen.queryByText('My Work')).toBeNull();
    });
    it('does not render Asset Lifecycle', () => {
      renderApp('system_admin');
      expect(screen.queryByText('Asset Lifecycle')).toBeNull();
    });
    it('does not render Workflow', () => {
      renderApp('system_admin');
      expect(screen.queryByText('Workflow')).toBeNull();
    });
    it('does not render Inventory', () => {
      renderApp('system_admin');
      expect(screen.queryByText('Inventory')).toBeNull();
    });
    it('does not render Profile in Administration section', () => {
      renderApp('system_admin');
      const profileLinks = screen.queryAllByText('My Profile');
      expect(profileLinks.length).toBe(0);
    });
  });

  describe('Mobile menu', () => {
    it('opens mobile menu on toggle', () => {
      renderApp('system_admin');
      const toggle = screen.getByRole('button', { name: 'Open navigation' });
      expect(toggle).toBeTruthy();
      fireEvent.click(toggle);
      expect(screen.getByRole('button', { name: 'Close navigation' })).toBeTruthy();
    });

    it('closes mobile menu on toggle', () => {
      renderApp('system_admin');
      const toggle = screen.getByRole('button', { name: 'Open navigation' });
      fireEvent.click(toggle);
      const closeToggle = screen.getByRole('button', { name: 'Close navigation' });
      fireEvent.click(closeToggle);
      expect(screen.getByRole('button', { name: 'Open navigation' })).toBeTruthy();
    });

    it('closes mobile menu when selecting a destination', () => {
      renderApp('system_admin');
      const toggle = screen.getByRole('button', { name: 'Open navigation' });
      fireEvent.click(toggle);
      expect(screen.getByRole('button', { name: 'Close navigation' })).toBeTruthy();
      const links = screen.getAllByRole('link', { name: 'Tickets' });
      const ticketsLink = links.find((l) => l.getAttribute('href') === '#/tickets');
      fireEvent.click(ticketsLink);
      // After navigation, menu should close
      expect(screen.queryByRole('button', { name: 'Close navigation' })).toBeNull();
    });
  });
});
