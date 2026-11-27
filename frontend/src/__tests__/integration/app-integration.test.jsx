import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

// â”€â”€ Mock useAuth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const { mockAuth } = vi.hoisted(() => ({
  mockAuth: vi.fn(),
}));

vi.mock('../../auth', () => ({
  useAuth: (...args) => mockAuth(...args),
  AuthProvider: ({ children }) => children,
}));

// â”€â”€ Mock every feature component imported by App.jsx â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
vi.mock('../../pages', () => ({
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
vi.mock('../../pages/kb/KnowledgeBase', () => ({
  KnowledgeBase: () => <div data-testid="mock-KnowledgeBase">KnowledgeBase</div>,
  KnowledgeBaseCompare: () => <div data-testid="mock-KnowledgeBaseCompare">KnowledgeBaseCompare</div>,
  KnowledgeBaseDetail: () => <div data-testid="mock-KnowledgeBaseDetail">KnowledgeBaseDetail</div>,
  KnowledgeBaseReviewQueue: () => <div data-testid="mock-KnowledgeBaseReviewQueue">KnowledgeBaseReviewQueue</div>,
  KnowledgeBaseRevisionDetail: () => <div data-testid="mock-KnowledgeBaseRevisionDetail">KnowledgeBaseRevisionDetail</div>,
  KnowledgeBaseRevisions: () => <div data-testid="mock-KnowledgeBaseRevisions">KnowledgeBaseRevisions</div>,
}));
vi.mock('../../pages/assets/Assets', () => ({
  AssetForm: () => <div data-testid="mock-AssetForm">AssetForm</div>,
  AssetDetail: () => <div data-testid="mock-AssetDetail">AssetDetail</div>,
}));
vi.mock('../../pages/audits/AuditLogPage', () => ({
  AuditLogPage: () => <div data-testid="mock-AuditLogPage">AuditLogPage</div>,
}));
vi.mock('../../pages/vendors/VendorsPage', () => ({
  VendorForm: () => <div data-testid="mock-VendorForm">VendorForm</div>,
  VendorsPage: () => <div data-testid="mock-VendorsPage">VendorsPage</div>,
  VendorDetail: () => <div data-testid="mock-VendorDetail">VendorDetail</div>,
}));
vi.mock('../../pages/tickets/Tickets', () => ({
  TicketForm: () => <div data-testid="mock-TicketForm">TicketForm</div>,
  TicketDetail: () => <div data-testid="mock-TicketDetail">TicketDetail</div>,
}));
vi.mock('../../pages/changes/ChangesPage', () => ({
  ChangesPage: () => <div data-testid="mock-ChangesPage">ChangesPage</div>,
}));
vi.mock('../../pages/cmdb/CmdbDashboard', () => ({
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
vi.mock('../../pages/notifications/Notifications', () => ({
  Notifications: () => <div data-testid="mock-Notifications">Notifications</div>,
  NotifBadge: () => <div data-testid="mock-NotifBadge">NotifBadge</div>,
}));
vi.mock('../../pages/maintenance/Maintenance', () => ({
  Maintenance: () => <div data-testid="mock-Maintenance">Maintenance</div>,
}));
vi.mock('../../pages/disposals/Disposals', () => ({
  Disposals: () => <div data-testid="mock-Disposals">Disposals</div>,
}));
vi.mock('../../pages/dashboard/Dashboard', () => ({
  Dashboard: () => <div data-testid="mock-Dashboard">Dashboard</div>,
  DepartmentReports: () => <div data-testid="mock-DepartmentReports">DepartmentReports</div>,
}));
vi.mock('../../pages/self-service/SelfService', () => ({
  SelfService: () => <div data-testid="mock-SelfService">SelfService</div>,
}));
vi.mock('../../pages/reports/SavedReports', () => ({
  SavedReports: () => <div data-testid="mock-SavedReports">SavedReports</div>,
}));
vi.mock('../../pages/reports/ScheduledReports', () => ({
  ScheduledReports: () => <div data-testid="mock-ScheduledReports">ScheduledReports</div>,
}));
vi.mock('../../pages/settings/Settings', () => ({
  NotificationSettings: () => <div data-testid="mock-NotificationSettings">NotificationSettings</div>,
}));
vi.mock('../../pages/privacy/Privacy', () => ({
  Privacy: () => <div data-testid="mock-Privacy">Privacy</div>,
}));
vi.mock('../../pages/monitoring/Monitoring', () => ({
  Monitoring: () => <div data-testid="mock-Monitoring">Monitoring</div>,
}));
vi.mock('../../pages/retention/Retention', () => ({
  Retention: () => <div data-testid="mock-Retention">Retention</div>,
}));
vi.mock('../../pages/backup/Backup', () => ({
  Backup: () => <div data-testid="mock-Backup">Backup</div>,
}));
vi.mock('../../pages/services/ServicesCatalogue', () => ({
  ServicesCatalogue: () => <div data-testid="mock-ServicesCatalogue">ServicesCatalogue</div>,
  MyServiceRequests: () => <div data-testid="mock-MyServiceRequests">MyServiceRequests</div>,
  ServiceRequestDetail: () => <div data-testid="mock-ServiceRequestDetail">ServiceRequestDetail</div>,
}));
vi.mock('../../pages/inventory/Inventory', () => ({
  default: () => <div data-testid="mock-Inventory">Inventory</div>,
  InventoryItems: () => <div data-testid="mock-InventoryItems">InventoryItems</div>,
  StockItemDetail: () => <div data-testid="mock-StockItemDetail">StockItemDetail</div>,
  StockItemForm: () => <div data-testid="mock-StockItemForm">StockItemForm</div>,
}));
vi.mock('../../pages/inventory/ops/InventoryOps', () => ({
  ReceiveStock: () => <div data-testid="mock-ReceiveStock">ReceiveStock</div>,
  Reservations: () => <div data-testid="mock-Reservations">Reservations</div>,
  TransactionHistory: () => <div data-testid="mock-TransactionHistory">TransactionHistory</div>,
  FulfilServiceRequest: () => <div data-testid="mock-FulfilServiceRequest">FulfilServiceRequest</div>,
}));
vi.mock('../../pages/workflow/Workflow', () => ({
  default: () => <div data-testid="mock-Workflow">Workflow</div>,
}));
vi.mock('../../pages/approvals/ApprovalCenter', () => ({
  ApprovalCenter: () => <div data-testid="mock-ApprovalCenter">ApprovalCenter</div>,
}));
vi.mock('../../pages/lifecycle/Lifecycle', () => ({
  LifecycleDashboard: () => <div data-testid="mock-LifecycleDashboard">LifecycleDashboard</div>,
  LifecycleCases: () => <div data-testid="mock-LifecycleCases">LifecycleCases</div>,
  LifecycleForm: () => <div data-testid="mock-LifecycleForm">LifecycleForm</div>,
  LifecycleDetail: () => <div data-testid="mock-LifecycleDetail">LifecycleDetail</div>,
}));
vi.mock('../../pages/procurement', () => ({
  ProcurementRouter: () => <div data-testid="mock-ProcurementRouter">ProcurementRouter</div>,
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

import App from '../../App';

function authCaps(role = 'system_admin', isActive = true) {
  const isStaff = ['system_admin', 'it_manager', 'it_support'].includes(role);
  const isEmployee = role === 'employee';
  const isAdmin = role === 'system_admin';
  const isManagerOrAdmin = isAdmin || role === 'it_manager';

  const canUseMonitoring = isStaff && isActive;
  const canUseProblemManagement = isStaff && isActive;

  return {
    access: true,
    logout: vi.fn(),
    user: { employee_id: 'EMP001', role, is_active: isActive },
    profileLoading: false,
    role,
    isSystemAdmin: isAdmin,
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isEmployee,
    isAdmin,
    isStaff,

    canManageScheduledReports: isManagerOrAdmin,
    canViewVendors: isStaff,
    canManageVendors: isManagerOrAdmin,
    canViewProcurement: isStaff,
    canViewProcurementReports: isManagerOrAdmin,

    canAccessRecycleBin: isAdmin,
    canAccessAudit: isAdmin,
    canManageUsers: isAdmin,

    canManageServiceCatalogue: isManagerOrAdmin,
    canApproveServiceRequests: isManagerOrAdmin,
    canConfigureWorkflow: isManagerOrAdmin,
    canApproveDisposals: isManagerOrAdmin,
    canManageInventory: isManagerOrAdmin,

    canViewLifecycle: isStaff || isEmployee,
    canCreateLifecycleCase: isStaff,

    canViewLicensing: isStaff || isEmployee,
    canManageSoftwareProducts: isManagerOrAdmin,
    canManageLicenseAgreements: isManagerOrAdmin,
    canManageLicenseAllocations: isStaff,
    canManageLicenseInstallations: isStaff,
    canManageLicenseRenewals: isStaff,
    canViewLicenseReports: isManagerOrAdmin,
    canViewMySoftware: isStaff || isEmployee,

    canUseMonitoring,
    canUseProblemManagement,
  };
}

function renderApp(role = 'system_admin', isActive = true) {
  mockAuth.mockReturnValue(authCaps(role, isActive));
  return render(<App />);
}
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('Application sidebar navigation', () => {
  describe('Group ordering', () => {
    it('renders all ten groups in the intended order', () => {
      renderApp('system_admin');

      const sections = Array.from(
        document.querySelectorAll('.sidenav-section-title')
      ).map((el) => (el.textContent || '').trim());

      expect(sections).toEqual([
        'Overview',
        'Change Management',
        'Service Operations',
        'Asset Operations',
        'Inventory',
        'Software & Licensing',
        'Lifecycle Management',
        'Reports',
        'Procurement',
        'Administration',
      ]);
    });
  });
  describe('Concise module labels', () => {
    it('shows concise labels without long legacy names', () => {
      renderApp('system_admin');
      const allLinks = screen.getAllByRole('link');
      const linkTexts = allLinks.map((l) => l.textContent.trim());
      const dashboardLinks = allLinks.filter((l) => l.getAttribute('href') === '#/dashboard' || l.getAttribute('href') === '#/changes/dashboard');
      expect(dashboardLinks).toHaveLength(2); // Overview + Change Management
      const dashboardTexts = dashboardLinks.map((l) => l.textContent.trim());
      expect(dashboardTexts).toContain('Dashboard'); // Overview
      expect(dashboardTexts).toContain('Dashboard'); // Change Management (separate link)
      expect(linkTexts).toContain('Tickets');
      expect(linkTexts).toContain('Canned Responses');
      expect(linkTexts).toContain('Ticket Templates');
      expect(linkTexts).toContain('Monitoring');
      expect(linkTexts).toContain('Problems');
      expect(linkTexts).toContain('Change Management');
      expect(linkTexts).toContain('Services');
      expect(linkTexts).toContain('Assets');
      expect(linkTexts).toContain('CMDB');
      expect(linkTexts).toContain('Inventory');
      expect(linkTexts).toContain('Stock items');
      expect(linkTexts).toContain('Coverage');
      expect(linkTexts).toContain('Procurement');
      expect(linkTexts).toContain('Users');
      expect(linkTexts).toContain('Categories');
      expect(linkTexts).toContain('Departments');
      expect(linkTexts).toContain('SLA');
      expect(linkTexts.some((t) => /Notifications/.test(t))).toBeTruthy();
      // Change Management keeps top-level workflows in the sidebar; record
      // actions live on the change detail page instead of as nav links.
      expect(linkTexts).toContain('New Change');
      expect(linkTexts).toContain('Calendar');
      expect(linkTexts).toContain('Dashboard');
      expect(linkTexts).toContain('Change Templates');
      expect(linkTexts).toContain('Maintenance Windows');
      expect(linkTexts).toContain('Blackout Periods');
      expect(linkTexts).toContain('Scheduling Exceptions');
      expect(linkTexts).toContain('Review Meetings');
      expect(linkTexts).toContain('Outages');
    });

    it('shows restored module links and excludes unimplemented destinations', () => {
      renderApp('system_admin');

      const expectedLinks = [
        'Ticket Queues',
        'Ticket Operations',
        'Workflow',
        'Approvals',
        'Knowledge Base',
        'Knowledge Base Review Queue',
        'Disposals',
        'Vendors',
        'Software Dashboard',
        'Software Products',
        'License Agreements',
        'License Allocations',
        'License Installations',
        'License Renewals',
        'License Compliance',
        'License Calendar',
        'License Utilization',
        'My Software',
        'Lifecycle Dashboard',
        'Onboarding',
        'Offboarding',
        'Transfers',
        'New Lifecycle Case',
        'SLA Reports',
        'Department Reports',
        'Saved Reports',
        'Scheduled Reports',
        'Purchase Requests',
        'Purchase Orders',
        'Goods Receipts',
        'Procurement Reports',
        'Privacy',
        'Retention',
        'Backup & Recovery',
      ];

      expectedLinks.forEach((label) => {
        expect(screen.getByRole('link', { name: label })).toBeTruthy();
      });

      expect(screen.queryByText('Employees')).toBeNull();
      expect(screen.queryByText('Saved Ticket Views')).toBeNull();
      expect(screen.queryByText('Ticket Satisfaction Survey')).toBeNull();
      expect(screen.queryByText('My Work')).toBeNull();
      expect(screen.queryByText('Asset Lifecycle')).toBeNull();
    });
  });

  describe('Role visibility â€” System Admin', () => {
    it('shows operational and administrative groups', () => {
      renderApp('system_admin');
      expect(screen.getAllByRole('link', { name: 'Dashboard' })).toHaveLength(2); // Overview + Change Management (Procurement Financial Dashboard also contains 'Dashboard' text but its href is different)
      expect(screen.getByRole('link', { name: 'Tickets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Monitoring' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Problems' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Change Management' })).toBeTruthy();
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

  describe('Role visibility â€” IT Manager', () => {
    it('shows operational modules and permitted governance modules', () => {
      renderApp('it_manager');
      expect(screen.getAllByRole('link', { name: 'Dashboard' })).toHaveLength(2); // Overview + Change Management (Procurement Financial Dashboard also contains 'Dashboard' text but its href is different)
      expect(screen.getByRole('link', { name: 'Tickets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Monitoring' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Problems' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Change Management' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Services' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Assets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'CMDB' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Procurement' })).toBeTruthy();
      // IT Manager is not system_admin â†’ isAdmin false â†’ no Administration
      expect(screen.queryByRole('link', { name: 'Users' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Categories' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Departments' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'SLA' })).toBeNull();
      expect(screen.queryByRole('link', { name: /Notifications/ })).toBeNull();
    });
  });

  describe('Role visibility â€” IT Support', () => {
    it('shows day-to-day support modules without unauthorized administration', () => {
      renderApp('it_support');
      expect(screen.getAllByRole('link', { name: 'Dashboard' })).toHaveLength(2); // Overview + Change Management (only top-level Dashboard is staff-only; Change Management Dashboard is visible to staff)
      expect(screen.getByRole('link', { name: 'Tickets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Monitoring' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Problems' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Change Management' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Services' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Assets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'CMDB' })).toBeTruthy();
      // Administration is isAdmin only â†’ not visible to IT Support
      expect(screen.queryByRole('link', { name: 'Users' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Categories' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Departments' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'SLA' })).toBeNull();
      expect(screen.queryByRole('link', { name: /Notifications/ })).toBeNull();
    });
  });

  describe('Role visibility â€” Employee', () => {
    it('shows only employee-facing destinations', () => {
      renderApp('employee');
      expect(screen.queryByRole('link', { name: 'Dashboard' })).toBeNull();
      expect(screen.getByRole('link', { name: 'Tickets' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Services' })).toBeTruthy();
      // Employee is not staff â†’ no Monitoring, Problems, Changes, Assets, CMDB, Procurement
      expect(screen.queryByRole('link', { name: 'Monitoring' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Problems' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Change Management' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Assets' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'CMDB' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Procurement' })).toBeNull();
      // Employee is not admin â†’ no Administration
      expect(screen.queryByRole('link', { name: 'Users' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Categories' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'Departments' })).toBeNull();
      expect(screen.queryByRole('link', { name: 'SLA' })).toBeNull();
      expect(screen.queryByRole('link', { name: /Notifications/ })).toBeNull();
    });
  });

  describe('Access control â€” inactive and unknown roles', () => {
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
    it('marks the default Tickets page active at the root route', () => {
      renderApp('system_admin');
      const links = screen.getAllByRole('link', { name: 'Tickets' });
      const navLink = links.find((l) => l.getAttribute('href') === '#/tickets');
      expect(navLink.getAttribute('aria-current')).toBe('page');
    });

    it('marks the matching nav link active for an explicit hash route', () => {
      window.location.hash = '#/assets';
      try {
        renderApp('system_admin');
        const navLink = screen.getByRole('link', { name: 'Assets' });
        expect(navLink.getAttribute('aria-current')).toBe('page');
      } finally {
        window.location.hash = '#/';
      }
    });
    it('activates Stock items instead of Inventory on the items route', () => {
      window.location.hash = '#/inventory/items';
      try {
        renderApp('system_admin');

        const inventory = screen.getByRole('link', { name: 'Inventory' });
        const stockItems = screen.getByRole('link', { name: 'Stock items' });

        expect(inventory.getAttribute('aria-current')).toBeNull();
        expect(stockItems.getAttribute('aria-current')).toBe('page');
      } finally {
        window.location.hash = '#/';
      }
    });

    it('keeps Stock items active on a nested item detail route', () => {
      window.location.hash = '#/inventory/items/15';
      try {
        renderApp('system_admin');

        const inventory = screen.getByRole('link', { name: 'Inventory' });
        const stockItems = screen.getByRole('link', { name: 'Stock items' });

        expect(inventory.getAttribute('aria-current')).toBeNull();
        expect(stockItems.getAttribute('aria-current')).toBe('page');
      } finally {
        window.location.hash = '#/';
      }
    });

    it('activates Purchase Orders instead of Procurement on its route', () => {
      window.location.hash = '#/procurement/orders';
      try {
        renderApp('system_admin');

        const procurement = screen.getByRole('link', { name: 'Procurement' });
        const purchaseOrders = screen.getByRole('link', { name: 'Purchase Orders' });

        expect(procurement.getAttribute('aria-current')).toBeNull();
        expect(purchaseOrders.getAttribute('aria-current')).toBe('page');
      } finally {
        window.location.hash = '#/';
      }
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
    it('has existing Inventory route', () => {
      renderApp('system_admin');
      const links = screen.getAllByRole('link', { name: 'Inventory' });
      expect(links.some((l) => l.getAttribute('href') === '#/inventory')).toBeTruthy();
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
    it('renders Workflow for staff', () => {
      renderApp('system_admin');
      expect(screen.getByRole('link', { name: 'Workflow' })).toBeTruthy();
      expect(screen.getByRole('link', { name: 'Workflow' }).getAttribute('href')).toBe('#/workflow');
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

  describe('Section expand/collapse', () => {
    const getSectionHeader = (name) => {
      const headers = screen.getAllByRole('button', {
        className: 'sidenav-section-header',
      });
      return headers.find((h) => {
        const titleEl = h.querySelector('.sidenav-section-title');
        return titleEl ? titleEl.textContent.trim() === name : false;
      });
    };

    it('expands a collapsed section when its header is clicked', () => {
      renderApp('system_admin');
      // Overview starts collapsed (active route #/tickets is under Service Operations)
      const overviewHeader = getSectionHeader('Overview');
      expect(overviewHeader.getAttribute('aria-expanded')).toBe('false');
      fireEvent.click(overviewHeader);
      expect(overviewHeader.getAttribute('aria-expanded')).toBe('true');
    });

    it('collapses an expanded section when its header is clicked again', () => {
      renderApp('system_admin');
      // All sections start collapsed now
      const svcHeader = getSectionHeader('Service Operations');
      expect(svcHeader.getAttribute('aria-expanded')).toBe('false');
      fireEvent.click(svcHeader);
      expect(svcHeader.getAttribute('aria-expanded')).toBe('true');
      fireEvent.click(svcHeader);
      expect(svcHeader.getAttribute('aria-expanded')).toBe('false');
    });

    it('expanding one section does not affect other sections', () => {
      renderApp('system_admin');
      const overviewHeader = getSectionHeader('Overview');
      const svcHeader = getSectionHeader('Service Operations');
      // Both start collapsed
      fireEvent.click(overviewHeader); // Overview â†’ expanded
      fireEvent.click(svcHeader); // Service Operations -> expanded
      expect(overviewHeader.getAttribute('aria-expanded')).toBe('true');
      expect(svcHeader.getAttribute('aria-expanded')).toBe('true');
      // Each section maintains its own state
    });

    it('aria-expanded matches submenu visibility', () => {
      renderApp('system_admin');
      const overviewHeader = getSectionHeader('Overview');
      expect(overviewHeader.getAttribute('aria-expanded')).toBe('false');
      fireEvent.click(overviewHeader);
      expect(overviewHeader.getAttribute('aria-expanded')).toBe('true');
      fireEvent.click(overviewHeader);
      expect(overviewHeader.getAttribute('aria-expanded')).toBe('false');
    });

    it('collapsed section content has collapsed class', () => {
      renderApp('system_admin');
      const overviewHeader = getSectionHeader('Overview');
      const sectionContent = document.getElementById('sidenav-section-content-0');
      expect(sectionContent).not.toBeNull();
      expect(sectionContent.classList.contains('collapsed')).toBeTruthy();
      fireEvent.click(overviewHeader);
      expect(sectionContent.classList.contains('collapsed')).toBeFalsy();
    });
  });

  describe('User-management route protection', () => {
    it('blocks employees from the user directory route', () => {
      window.location.hash = '#/users';
      try {
        renderApp('employee');
        expect(screen.getByRole('alert').textContent).toMatch(/permission/i);
        expect(screen.queryByTestId('mock-Users')).toBeNull();
      } finally {
        window.location.hash = '#/';
      }
    });

    it('blocks employees from the employee detail route', () => {
      window.location.hash = '#/users/7';
      try {
        renderApp('employee');
        expect(screen.getByRole('alert').textContent).toMatch(/permission/i);
        expect(screen.queryByTestId('mock-EmployeeDetail')).toBeNull();
      } finally {
        window.location.hash = '#/';
      }
    });

    it('still allows system admins into the user directory', () => {
      window.location.hash = '#/users';
      try {
        renderApp('system_admin');
        expect(screen.getByTestId('mock-Users')).toBeTruthy();
      } finally {
        window.location.hash = '#/';
      }
    });
  });
});
