import { useEffect, useState } from 'react';
import { useAuth, AuthProvider } from './auth';
import { Assets, Categories, Departments, EmployeeDetail, Login, Profile, RecycleBin, ResetPassword, SLAConfig, SLAReport, Tickets, Users, VerifyEmail } from './pages';
import {
  KnowledgeBase, KnowledgeBaseCompare, KnowledgeBaseDetail,
  KnowledgeBaseReviewQueue, KnowledgeBaseRevisionDetail,
  KnowledgeBaseRevisions,
} from './kb';
import { AssetForm, AssetDetail } from './assets';
import { AuditLogPage } from './audit';
import { VendorForm, VendorsPage, VendorDetail } from './vendors';
import { TicketForm, TicketDetail } from './tickets';
import { TicketQueuesPage } from './ticket-queues';
import { TicketOperationsDashboard } from './ticket-operations';
import { CannedResponsesPage } from './ticket-canned-responses';
import { TicketTemplatesPage } from './ticket-templates';
import { SavedTicketViews } from './ticket-saved-views';
import { TicketSatisfactionSurvey } from './ticket-satisfaction';
import { TicketMergeDialog } from './ticket-merge';
import { TicketTimeline } from './ticket-timeline';
import { TicketCollaborationPanel } from './ticket-collaboration';
import { TicketRelationsPanel } from './ticket-relations';
import { Notifications, NotifBadge } from './notifications';
import { Maintenance } from './maintenance';
import { Disposals } from './disposals';
import { Dashboard, DepartmentReports } from './dashboard';
import { SelfService } from "./self-service";
import { SavedReports } from './saved-reports';
import { ScheduledReports } from './scheduled-reports';
import { NotificationSettings } from './settings';
import { Privacy } from './privacy';
import { Monitoring } from './monitoring';
import { Retention } from './retention';
import { Backup } from './backup';
import { ServicesCatalogue, MyServiceRequests, ServiceRequestDetail } from './services';
import Inventory, { InventoryItems, StockItemDetail, StockItemForm } from './inventory';
import { ReceiveStock, Reservations, TransactionHistory, FulfilServiceRequest } from './inventory-ops';
import Workflow from './workflow';
import { ApprovalCenter } from './approvals';
import {
  LifecycleDashboard, LifecycleCases, LifecycleForm, LifecycleDetail,
} from './lifecycle';
import { ProcurementRouter } from './procurement';
import { LicensingRouter } from './licensing';

const NAV = [
  { section: 'Work' },
{ hash: '#/dashboard', label: 'Dashboard', staffOnly: true },
  { hash: '#/tickets', label: 'Tickets' },
  { hash: '#/services', label: 'Services', staffOnly: false },
  { hash: '#/service-requests', label: 'Service requests', staffOnly: false },
  { hash: '#/kb', label: 'Knowledge Base', staffOnly: false },
  { hash: '#/tickets/queues', label: 'Ticket Queues', staffOnly: true },
  { hash: '#/tickets/operations', label: 'Operations', staffOnly: true },
  { hash: '#/tickets/canned-responses', label: 'Canned Responses', staffOnly: true },
  { hash: '#/tickets/templates', label: 'Ticket Templates', staffOnly: true },
  { hash: '#/self-service', label: 'Self-Service', staffOnly: false },
  { hash: '#/lifecycle', label: 'Lifecycle', staffOnly: false },
  { hash: '#/lifecycle/onboarding', label: 'Onboarding Cases', staffOnly: true },
  { hash: '#/lifecycle/offboarding', label: 'Offboarding Cases', staffOnly: true },
  { hash: '#/lifecycle/transfers', label: 'Transfers', staffOnly: true },
  { hash: '#/lifecycle/new', label: 'New Case', staffOnly: true },
   { hash: '#/assets', label: 'Assets' },
  { section: 'Software' },
  { hash: '#/software', label: 'Software Dashboard', staffOnly: true },
  { hash: '#/software/products', label: 'Software Products', staffOnly: true },
  { hash: '#/licenses', label: 'License Agreements', staffOnly: true },
  { hash: '#/license-allocations', label: 'License Allocations', staffOnly: true },
  { hash: '#/license-installations', label: 'Software Installations', staffOnly: true },
  { hash: '#/license-renewals', label: 'License Renewals', staffOnly: true },
  { hash: '#/license-compliance', label: 'License Compliance', staffOnly: true },
  { hash: '#/license-calendar', label: 'Renewal Calendar', staffOnly: true },
  { hash: '#/license-utilization', label: 'License Utilization', staffOnly: true },
  { hash: '#/my-software', label: 'My Software', staffOnly: false },
  { section: 'Operations', staffOnly: true },
  { hash: '#/workflow', label: 'Workflow', staffOnly: true },
  { hash: '#/monitoring', label: 'Monitoring', staffOnly: true },
  { hash: '#/backup', label: 'Backup &amp; DR', staffOnly: true },
  { hash: '#/maintenance', label: 'Maintenance', staffOnly: true },
  { hash: '#/disposals', label: 'Disposals', staffOnly: true },
  { hash: '#/inventory', label: 'Inventory', staffOnly: true },
  { hash: '#/procurement', label: 'Procurement', staffOnly: true },
  { hash: '#/procurement/requests', label: 'Purchase Requests', staffOnly: true },
  { hash: '#/procurement/orders', label: 'Purchase Orders', staffOnly: true },
  { hash: '#/procurement/receipts', label: 'Goods Receipts', staffOnly: true },
  { section: 'Reports' },  { hash: '#/reports/sla', label: 'SLA report', staffOnly: true },
  { hash: '#/reports/departments', label: 'Department reports', staffOnly: true },
  { hash: '#/reports/saved', label: 'Saved reports', staffOnly: false },
  { hash: '#/reports/schedules', label: 'Scheduled reports', cap: 'canManageScheduledReports' },
  { hash: '#/procurement/reports', label: 'Procurement reports', cap: 'canViewProcurementReports' },
  { section: 'Approvals' },
  { hash: '#/approvals', label: 'Approvals', staffOnly: true },
  { section: 'Organize' },
  { hash: '#/vendors', label: 'Vendors', cap: 'canViewVendors' },
  { hash: '#/categories', label: 'Categories' },
  { hash: '#/departments', label: 'Departments' },
  { hash: '#/notifications', label: 'Notifications', badge: true },
  { hash: '#/settings/notifications', label: 'Notification settings', staffOnly: false },
  { hash: '#/users', label: 'Employees' },
];

/** Drop staff-only entries, capability-gated entries, and any section left
 *  with no visible items. `caps` is the set of boolean capability helpers
 *  from `useAuth()` (isStaff, canManageVendors, ...). Unknown capabilities
 *  fail closed (entry hidden). */
function visibleNav(nav, caps) {
  const kept = nav.filter((n) => {
    if (n.section) return true;
    if (n.staffOnly) return !!caps.isStaff;
    if (n.cap) return !!caps[n.cap];
    return true;
  });
  const out = [];
  for (let i = 0; i < kept.length; i += 1) {
    if (!kept[i].section) {
      out.push(kept[i]);
      continue;
    }
    let j = i + 1;
    while (j < kept.length && !kept[j].section) j += 1;
    if (j > i + 1) out.push(kept[i]);
  }
  return out;
}

const TITLES = {
  '#/dashboard': 'Dashboard',
  '#/tickets': 'Tickets',
  '#/tickets/queues': 'Ticket Queues',
  '#/tickets/operations': 'Operations Dashboard',
  '#/tickets/canned-responses': 'Canned Responses',
  '#/tickets/templates': 'Ticket Templates',
  '#/services': 'Services',
  '#/service-requests': 'Service requests',
  '#/kb': 'Knowledge Base',
  '#/reports/sla': 'SLA report',
  '#/reports/departments': 'Department reports',
  '#/reports/saved': 'Saved reports',
  '#/reports/schedules': 'Scheduled reports',
  '#/vendors': 'Vendors',
  '#/approvals': 'Approvals',
  '#/assets': 'Assets',
  '#/workflow': 'Workflow',
  '#/maintenance': 'Maintenance',
  '#/disposals': 'Disposals',
  '#/inventory': 'Inventory',
  '#/categories': 'Categories',
  '#/departments': 'Departments',
  '#/notifications': 'Notifications',
  '#/settings/notifications': 'Notification settings',
  '#/recycle': 'Recycle Bin',
  '#/audit': 'Audit Log',
  '#/privacy': 'Privacy erasure',
  '#/retention': 'Data retention',
  '#/monitoring': 'Monitoring',
  '#/backup': 'Backup &amp; DR',
  '#/sla-config': 'SLA config',
  '#/kb': 'Knowledge Base',
  '#/users': 'Employees',
  '#/profile': 'My Profile',
  '#/lifecycle': 'Lifecycle Dashboard',
  '#/lifecycle/onboarding': 'Onboarding Cases',
  '#/lifecycle/offboarding': 'Offboarding Cases',
  '#/lifecycle/transfers': 'Transfers',
  '#/lifecycle/new': 'New Lifecycle Case',
  '#/procurement': 'Procurement',
  '#/procurement/requests': 'Purchase Requests',
  '#/procurement/orders': 'Purchase Orders',
  '#/procurement/receipts': 'Goods Receipts',
  '#/procurement/assets': 'Asset registration',
  '#/procurement/reports': 'Procurement reports',
};

/** Sticky-header breadcrumb: parent → record → action, so the header
 *  adds orientation instead of repeating the page title below it. */
function crumbs(hash) {
  const h = hash.split('?')[0];
  let m;
  if ((m = h.match(/^#\/(tickets|assets)\/(\d+)(?:\/(edit))?$/))) {
    const trail = [m[1] === 'tickets' ? 'Tickets' : 'Assets', `#${m[2]}`];
    if (m[3]) trail.push('Edit');
    return trail;
  }
  if (h === '#/tickets/new') return ['Tickets', 'New'];
  if (h === '#/assets/new') return ['Assets', 'New'];
  if (h === '#/vendors/new') return ['Vendors', 'New'];
  if (h === '#/recycle' || h === '#/audit') return ['Administration', TITLES[h]];
  if (h === '#/privacy') return ['Administration', 'Privacy erasure'];
  if (h.startsWith('#/privacy/')) return ['Administration', 'Privacy erasure'];
  if (h === '#/monitoring') return ['Administration', 'Monitoring'];
  if (h.startsWith('#/monitoring/')) return ['Administration', 'Monitoring'];
  if (h === '#/backup') return ['Administration', 'Backup & DR'];
  if (h.startsWith('#/backup/')) return ['Administration', 'Backup & DR'];
  if (h === '#/retention') return ['Administration', 'Data retention'];
  if (h.startsWith('#/retention/')) return ['Administration', 'Data retention'];
  if (h.startsWith('#/workflow')) return ['Workflow'];
  if (h.startsWith('#/reports/')) return ['Reports', TITLES[h]];
  if (h.startsWith('#/settings/')) return ['Settings', TITLES[h]];
  if ((m = h.match(/^#\/users\/(\d+)$/))) return ['Employees', `Employee #${m[1]}`];
  if (h === '#/services') return ['Services'];
  if (h === '#/service-requests') return ['Service requests'];
  if ((m = h.match(/^#\/service-requests\/(\d+)$/))) return ['Service requests', `Request #${m[1]}`];
  if (h === '#/approvals') return ['Approvals'];
  if (h === '#/inventory' || h === '#/inventory/items') return ['Inventory'];
  if ((m = h.match(/^#\/inventory\/items\/(\d+)(?:\/(edit))?$/))) return ['Inventory', `Item #${m[1]}`, m[3] ? 'Edit' : null].filter(Boolean);
  if (h.startsWith('#/inventory/receive')) return ['Inventory', 'Receive stock'];
  if (h.startsWith('#/inventory/reservations')) return ['Inventory', 'Reservations'];
  if (h.startsWith('#/inventory/transactions')) return ['Inventory', 'Transaction history'];
  if (h.startsWith('#/inventory/fulfil')) return ['Inventory', 'Fulfil request'];
  if (h === '#/kb/pending') return ['Knowledge Base', 'Pending review'];
  if (h.startsWith('#/kb/')) return ['Knowledge Base', 'Article'];
  if (h === '#/lifecycle') return ['Lifecycle', 'Dashboard'];
  if (h === '#/lifecycle/onboarding') return ['Lifecycle', 'Onboarding'];
  if (h === '#/lifecycle/offboarding') return ['Lifecycle', 'Offboarding'];
  if (h === '#/lifecycle/transfers') return ['Lifecycle', 'Transfers'];
  if (h === '#/lifecycle/new') return ['Lifecycle', 'New Case'];
  if (h.startsWith('#/lifecycle/') && h.match(/\/(\d+)$/)) return ['Lifecycle', 'Case'];
  if (h === '#/procurement') return ['Procurement', 'Dashboard'];
  if (h.startsWith('#/procurement/requests')) return ['Procurement', 'Purchase Requests'];
  if (h.startsWith('#/procurement/orders')) return ['Procurement', 'Purchase Orders'];
  if (h.startsWith('#/procurement/receipts')) return ['Procurement', 'Goods Receipts'];
  if (h.startsWith('#/procurement/assets')) return ['Procurement', 'Asset registration'];
  if (h.startsWith('#/procurement/reports')) return ['Procurement', 'Reports'];
  return [TITLES[h] ?? 'Tickets'];
}

function matchRoute(hash) {
  const route = hash.split('?')[0];
  let m;
  if ((m = route.match(/^#\/tickets\/(\d+)\/edit$/))) return <TicketForm id={m[1]} />;
  if (route === '#/tickets/new') return <TicketForm />;
  if ((m = route.match(/^#\/tickets\/(\d+)$/))) return <TicketDetail id={m[1]} />;
  if ((m = route.match(/^#\/tickets\/(\d+)\/timeline$/))) return <TicketTimeline id={m[1]} />;
  if (route === '#/tickets/queues') return <TicketQueuesPage />;
  if (route === '#/tickets/operations') return <TicketOperationsDashboard />;
  if (route === '#/tickets/canned-responses') return <CannedResponsesPage />;
  if (route === '#/tickets/templates') return <TicketTemplatesPage />;
  if (route === '#/tickets/saved-views') return <SavedTicketViews />;
  if (route === '#/tickets/satisfaction') return <TicketSatisfactionSurvey />;
  if ((m = route.match(/^#\/tickets\/(\d+)\/merge$/))) return <TicketMergeDialog id={m[1]} />;
  if ((m = route.match(/^#\/assets\/(\d+)\/edit$/))) return <AssetForm id={m[1]} />;
  if (route === '#/assets/new') return <AssetForm />;
  if ((m = route.match(/^#\/assets\/(\d+)$/))) return <AssetDetail id={m[1]} />;
  if ((m = route.match(/^#\/vendors\/(\d+)\/edit$/))) return <VendorForm vendorId={m[1]} />;
  if (route === '#/vendors/new') return <VendorForm />;
  if ((m = route.match(/^#\/vendors\/(\d+)$/))) return <VendorDetail id={m[1]} />;
  if ((m = route.match(/^#\/users\/(\d+)\/?$/))) return <EmployeeDetail id={m[1]} />;
  if (route === '#/kb/pending') return <KnowledgeBaseReviewQueue />;
  if ((m = route.match(/^#\/kb\/(\d+)\/revisions\/(\d+)$/))) return <KnowledgeBaseRevisionDetail id={m[1]} number={m[2]} />;
  if ((m = route.match(/^#\/kb\/(\d+)\/revisions$/))) return <KnowledgeBaseRevisions id={m[1]} />;
  if ((m = route.match(/^#\/kb\/(\d+)\/compare$/))) return <KnowledgeBaseCompare id={m[1]} />;
  if ((m = route.match(/^#\/kb\/(\d+)$/))) return <KnowledgeBaseDetail id={m[1]} />;
  if ((m = route.match(/^#\/workflow\/rules\/(\d+)\/edit$/))) return <Workflow ruleId={m[1]} ruleEdit />;
  if ((m = route.match(/^#\/workflow\/rules\/(\d+)$/))) return <Workflow ruleId={m[1]} />;
  if ((m = route.match(/^#\/workflow\/approvals\/(\d+)$/))) return <Workflow approvalId={m[1]} />;
  if ((m = route.match(/^#\/workflow\/executions\/(\d+)$/))) return <Workflow executionId={m[1]} />;
  if (route === '#/workflow/rules') return <Workflow tab="rules" />;
  if (route === '#/workflow/approvals') return <Workflow tab="approvals" />;
  if (route === '#/workflow/executions') return <Workflow tab="executions" />;
  if (route === '#/privacy' || route.startsWith('#/privacy/')) return <Privacy />;
  if (route === '#/retention' || route.startsWith('#/retention/')) return <Retention />;
  if (route === '#/monitoring' || route.startsWith('#/monitoring/')) return <Monitoring />;
  if (route === '#/backup' || route.startsWith('#/backup/')) return <Backup />;
  if ((m = route.match(/^#\/service-requests\/(\d+)$/))) return <ServiceRequestDetail id={m[1]} />;
  if ((m = route.match(/^#\/inventory\/items\/(\d+)\/edit$/))) return <StockItemForm id={m[1]} />;
  if ((m = route.match(/^#\/inventory\/items\/(\d+)$/))) return <StockItemDetail id={m[1]} />;
  if (route === '#/lifecycle') return <LifecycleDashboard />;
  if (route === '#/lifecycle/onboarding') return <LifecycleCases caseType="onboarding" />;
  if (route === '#/lifecycle/offboarding') return <LifecycleCases caseType="offboarding" />;
  if (route === '#/lifecycle/transfers') return <LifecycleCases caseType="transfer" />;
  if (route === '#/lifecycle/new') return <LifecycleForm />;
  if ((m = route.match(/^#\/lifecycle\/(\d+)$/))) return <LifecycleDetail id={m[1]} />;
  if (route === '#/procurement' || route.startsWith('#/procurement/')) {
    return <ProcurementRouter route={hash} />;
  }
  if (route === '#/software' || route.startsWith('#/software/') || route === '#/licenses' || route.startsWith('#/licenses/') || route === '#/license-allocations' || route.startsWith('#/license-allocations/') || route === '#/license-installations' || route.startsWith('#/license-installations/') || route === '#/license-renewals' || route.startsWith('#/license-renewals/') || route === '#/license-compliance' || route.startsWith('#/license-compliance/') || route === '#/license-calendar' || route === '#/license-utilization' || route === '#/my-software') {
    return <LicensingRouter route={hash} />;
  }
  const routes = {
    '#/dashboard': <Dashboard />,
    '#/tickets': <Tickets />,
    '#/inventory': <Inventory />,
    '#/inventory/items': <InventoryItems />,
    '#/inventory/items/new': <StockItemForm />,
    '#/inventory/receive': <ReceiveStock />,
    '#/inventory/reservations': <Reservations />,
    '#/inventory/transactions': <TransactionHistory />,
    '#/inventory/fulfil': <FulfilServiceRequest />,
    '#/services': <ServicesCatalogue />,
    '#/workflow': <Workflow />,
    '#/service-requests': <MyServiceRequests />,
    '#/reports/sla': <SLAReport />,
    '#/reports/departments': <DepartmentReports />,
    '#/reports/saved': <SavedReports />,
    '#/reports/schedules': <ScheduledReports />,
    '#/assets': <Assets />,
    '#/vendors': <VendorsPage />,
    '#/vendors/new': <VendorForm />,
    '#/vendors/:id': <VendorDetail />,
    '#/vendors/:id/edit': <VendorForm />,
    '#/approvals': <ApprovalCenter />,
    '#/maintenance': <Maintenance />,
    '#/disposals': <Disposals />,
    '#/categories': <Categories />,
    '#/departments': <Departments />,
    '#/notifications': <Notifications />,
    '#/settings/notifications': <NotificationSettings />,
    '#/recycle': <RecycleBin />,
    '#/audit': <AuditLogPage />,
    '#/sla-config': <SLAConfig />,
    '#/users': <Users />,
    '#/profile': <Profile />,
    '#verify-email': <VerifyEmail />,
    '#reset-password': <ResetPassword />,
    '#/self-service': <SelfService />,
  };
  return routes[route] ?? <Tickets />;
}

function isActive(hash, h) {
  return h === hash || (h !== '#/tickets' && hash.startsWith(h + '/'));
}

function Shell() {
  const { access, logout, user, profileLoading, isAdmin, isStaff, canManageScheduledReports, canViewVendors } = useAuth();
  const caps = { isStaff, isAdmin, canManageScheduledReports, canViewVendors };
  const [hash, setHash] = useState(location.hash || '#/tickets');
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => {
    const fn = () => { setHash(location.hash || '#/tickets'); setNavOpen(false); };
    addEventListener('hashchange', fn);
    return () => removeEventListener('hashchange', fn);
  }, []);
  if (!access) {
    if (hash.startsWith('#/verify-email')) return <VerifyEmail />;
    if (hash.startsWith('#/reset-password')) return <ResetPassword />;
    return <Login />;
  }
  if (profileLoading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading your workspace…
      </p>
    );
  }
  const el = matchRoute(hash);
  const active = (h) => isActive(hash, h) ? 'active' : '';
  const nav = visibleNav(NAV, caps);
  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className={`sidebar${navOpen ? ' nav-open' : ''}`}>
        <a className="brand" href="#/tickets">
          <span className="brand-mark">IT</span>
          <span className="brand-name">Service Desk<small>Ticket &amp; Asset</small></span>
        </a>
        <nav className="sidenav" aria-label="Primary">
          {nav.map((n, i) => n.section
            ? <div key={i} className="sidenav-section">{n.section}</div>
            : (
              <a key={n.hash} href={n.hash} className={active(n.hash)} aria-current={isActive(hash, n.hash) ? 'page' : undefined}>
                <span className="nav-label">{n.label}</span>
                {n.badge && <NotifBadge />}
              </a>
            ))}
          {isAdmin && (
            <>
              <div className="sidenav-section">Administration</div>
              <a href="#/recycle" className={active('#/recycle')} aria-current={isActive(hash, '#/recycle') ? 'page' : undefined}>
                <span className="nav-label">Recycle Bin</span>
              </a>
              <a href="#/audit" className={active('#/audit')} aria-current={isActive(hash, '#/audit') ? 'page' : undefined}>
                <span className="nav-label">Audit Log</span>
              </a>
              <a href="#/privacy" className={active('#/privacy')} aria-current={isActive(hash, '#/privacy') ? 'page' : undefined}>
                <span className="nav-label">Privacy erasure</span>
              </a>
              <a href="#/retention" className={active('#/retention')} aria-current={isActive(hash, '#/retention') ? 'page' : undefined}>
                <span className="nav-label">Data retention</span>
              </a>
              <a href="#/sla-config" className={active('#/sla-config')} aria-current={isActive(hash, '#/sla-config') ? 'page' : undefined}>
                <span className="nav-label">SLA config</span>
              </a>
            </>
          )}
        </nav>
        <div className="sidebar-foot">
          <span className="user-chip">
            {user ? <a href="#/profile">{user.employee_id}</a> : ''}
            <small>{user ? user.role.replace('_', ' ') : ''}</small>
          </span>
          <button className="btn-ghost btn-block" onClick={logout}>Log out</button>
        </div>
      </aside>
      <div className={`sidebar-scrim${navOpen ? ' nav-open' : ''}`} onClick={() => setNavOpen(false)} aria-hidden="true" />
      <div className="main-col">
        <div className="topbar">
          <button type="button" className="nav-toggle" onClick={() => setNavOpen((v) => !v)} aria-label={navOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={navOpen}>☰</button>
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs(hash).map((c, i, arr) => (
              <span key={i}>
                {i > 0 && <span className="crumb-sep" aria-hidden="true">/</span>}
                <span className={i === arr.length - 1 ? 'crumb-current' : undefined}>{c}</span>
              </span>
            ))}
          </nav>
        </div>
        <main className="content" id="main-content">{el}</main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}
