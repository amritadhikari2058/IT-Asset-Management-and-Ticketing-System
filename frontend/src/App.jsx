import React, { Suspense, useMemo, useState } from 'react';
import { HashRouter, useLocation } from 'react-router-dom';
import { useAuth, AuthProvider } from './auth';
import {
  Assets, Categories, Departments, EmployeeDetail, Login, Profile, RecycleBin,
  ResetPassword, SLAConfig, SLAReport, Tickets, Users, VerifyEmail,
} from './pages';
import {
  KnowledgeBaseCompare, KnowledgeBaseDetail, KnowledgeBaseReviewQueue,
  KnowledgeBaseRevisionDetail, KnowledgeBaseRevisions,
} from './pages/kb';
import { AssetForm, AssetDetail } from './pages/assets';
import { AuditLogPage } from './pages/audits';
import { VendorForm, VendorsPage, VendorDetail } from './pages/vendors';
import { TicketForm, TicketDetail } from './pages/tickets';
import { ChangesPage } from './pages/changes';
import { CmdbDashboard } from './pages/cmdb';
import { CmdbItemsList } from './pages/cmdb';
import { CiForm } from './pages/cmdb';
import { CiDetail } from './pages/cmdb';
import { CiRelationshipsPage } from './pages/cmdb';
import { BaselinesPage } from './pages/cmdb';
import { DriftFindingsPage } from './pages/cmdb';
import { VerificationQueuePage } from './pages/cmdb';
import { ImpactAnalysisPage } from './pages/cmdb';
import { DependencyMap } from './pages/cmdb';
import { CmdbReports } from './pages/cmdb';
import { CiTypesPage } from './pages/cmdb';
import { ServiceMappingPage } from './pages/cmdb';
import { TicketQueuesPage } from './pages/tickets';
import { TicketOperationsDashboard } from './pages/tickets';
import { TicketBulkImportsPage, TicketBulkImportDetailPage } from './pages/tickets';
import { CannedResponsesPage } from './pages/tickets';
import { TicketTemplatesPage } from './pages/tickets';
import { SavedTicketViews } from './pages/tickets';
import { TicketSatisfactionSurvey } from './pages/tickets';
import { TicketTimeline } from './pages/tickets';
import { TicketMergeDialog } from './pages/tickets';
import { ErrorBoundary } from './ErrorBoundary';
import { Notifications, NotifBadge } from './pages/notifications';
import { Maintenance } from './pages/maintenance';
import { Disposals } from './pages/disposals';
import { Dashboard, DepartmentReports } from './pages/dashboard';
import { AssetReportsPage } from './pages/assets';
import { SelfService } from './pages/self-service';
import { SavedReports } from './pages/reports';
import { ScheduledReports } from './pages/reports';
import { NotificationSettings } from './pages/settings';
import { Privacy } from './pages/privacy';
import { Monitoring } from './pages/monitoring';
import { Retention } from './pages/retention';
import { Backup } from './pages/backup';
import { ServicesCatalogue, MyServiceRequests, ServiceRequestDetail } from './pages/services';
import { Inventory, InventoryItems, StockItemDetail, StockItemForm } from './pages/inventory';
import { ReceiveStock, Reservations, TransactionHistory, FulfilServiceRequest } from './pages/inventory';
import Workflow from './pages/workflow';
import { ApprovalCenter } from './pages/approvals';
import { LifecycleDashboard, LifecycleCases, LifecycleForm, LifecycleDetail } from './pages/lifecycle';
import { ProcurementRouter } from './pages/procurement';
import { LicensingRouter } from './pages/licensing';
import { ProblemList } from './pages/problem-management';
import { ProblemDetail } from './pages/problem-management';
import { MonitoringOverview } from './features/monitoring/MonitoringOverview';
import { SourceManagement } from './features/monitoring/SourceManagement';
import { AlertList } from './features/monitoring/AlertList';
import { AlertDetail } from './features/monitoring/AlertDetail';
import { PolicyManagement } from './features/monitoring/PolicyManagement';
import { ToastProvider, ToastList, useToast } from './toast';
import { DirtyProvider, DirtyBlocker } from './dirty-form';

const NAV = [
  { section: 'Overview' },
  { hash: '#/dashboard', label: 'Dashboard' },
  { section: 'Change Management' },
  { hash: '#/changes', label: 'Change Management', staffOnly: true },
  { hash: '#/changes/new', label: 'New Change', staffOnly: true },
  { hash: '#/changes/calendar', label: 'Calendar', staffOnly: true },
  { hash: '#/changes/dashboard', label: 'Dashboard', staffOnly: true },
  { hash: '#/change-templates', label: 'Change Templates', staffOnly: true },
  { hash: '#/maintenance-windows', label: 'Maintenance Windows', staffOnly: true },
  { hash: '#/blackout-periods', label: 'Blackout Periods', staffOnly: true },
  { hash: '#/scheduling-exceptions', label: 'Scheduling Exceptions', staffOnly: true },
  { hash: '#/change-review-meetings', label: 'Review Meetings', staffOnly: true },
  { hash: '#/outages', label: 'Outages', staffOnly: true },
  { section: 'Service Operations' },
  { hash: '#/tickets', label: 'Tickets' },
  { hash: '#/tickets/bulk-imports', label: 'Import Operations', staffOnly: true },
  { hash: '#/monitoring', label: 'Monitoring', cap: 'canUseMonitoring' },
  { hash: '#/problem-management', label: 'Problems', cap: 'canUseProblemManagement' },
  { section: 'Asset Operations' },
  { hash: '#/assets', label: 'Assets', staffOnly: true },
  { hash: '#/assets/reports', label: 'Asset Reports', staffOnly: true },
  { hash: '#/cmdb', label: 'CMDB', staffOnly: true },
  { section: 'Inventory' },
  { hash: '#/inventory', label: 'Inventory', staffOnly: true },
  { hash: '#/inventory/items', label: 'Stock items', staffOnly: true },
  { section: 'Reports' },
  { hash: '#/reports/coverage', label: 'Coverage', staffOnly: true },
  { hash: '#/reports/verification_age', label: 'Verification Age', staffOnly: true },
  { hash: '#/reports/orphans', label: 'Orphans', staffOnly: true },
  { hash: '#/reports/ownership_gaps', label: 'Ownership Gaps', staffOnly: true },
  { hash: '#/reports/relationship_coverage', label: 'Relationship Coverage', staffOnly: true },
  { hash: '#/reports/drift', label: 'Drift', staffOnly: true },
  { hash: '#/reports/critical_deps', label: 'Critical Dependencies', staffOnly: true },
  { hash: '#/reports/asset_sync', label: 'Asset Sync', staffOnly: true },
  { hash: '#/reports/software_sync', label: 'Software Sync', staffOnly: true },
  { hash: '#/verification', label: 'Verification Queue', staffOnly: true },
  { section: 'Procurement' },
  { hash: '#/procurement', label: 'Procurement', staffOnly: true },
  { hash: '#/procurement/invoices', label: 'Supplier Invoices', staffOnly: true },
  { hash: '#/procurement/exceptions', label: 'Invoice Exceptions', staffOnly: true },
  { hash: '#/procurement/returns', label: 'Vendor Returns', staffOnly: true },
  { hash: '#/procurement/credit-notes', label: 'Vendor Credit Notes', staffOnly: true },
  { hash: '#/procurement/financial-dashboard', label: 'Procurement Financial Dashboard', cap: 'canViewProcurementReports' },
  { hash: '#/procurement/vendor-performance', label: 'Vendor Performance', cap: 'canViewProcurementReports' },
  { hash: '#/services', label: 'Services' },
  { hash: '#/service-requests', label: 'Service requests' },
  { section: 'Administration' },
  { hash: '#/users', label: 'Users', cap: 'isAdmin' },
  { hash: '#/categories', label: 'Categories', cap: 'isAdmin' },
  { hash: '#/departments', label: 'Departments', cap: 'isAdmin' },
  { hash: '#/sla-config', label: 'SLA', cap: 'isAdmin' },
  { hash: '#/notifications', label: 'Notifications', badge: true, cap: 'isAdmin' },
  { hash: '#/audit', label: 'Audit Log', cap: 'isAdmin' },
  { hash: '#/recycle', label: 'Recycle Bin', cap: 'canAccessRecycleBin' },
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
  // Collapsible sections stay collapsed on load. The Change Management section
  // is the largest section by far (17 routes) and would otherwise take the
  // entire sidebar; keep it collapsed and let the user expand it.
  return out;
}

const TITLES = {
  '#/dashboard': 'Dashboard',
  '#/tickets': 'Tickets',
  '#/tickets/bulk-imports': 'Import Operations',
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
  '#/assets/reports': 'Asset Reports',
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
  '#/monitoring/overview': 'Monitoring',
  '#/monitoring/sources': 'Sources',
  '#/monitoring/alerts': 'Alerts',
  '#/monitoring/policies': 'Policies',
  '#/problem-management': 'Problems',
  '#/backup': 'Backup &amp; DR',
  '#/sla-config': 'SLA config',
  '#/users': 'Employees',
  '#/profile': 'My Profile',
  '#/cmdb': 'CMDB',
  '#/cmdb/items': 'Configuration Items',
  '#/cmdb/items/new': 'New Configuration Item',
  '#/cmdb/types': 'CI Types',
  '#/cmdb/relationships': 'CI Relationships',
  '#/cmdb/baselines': 'Baselines',
  '#/cmdb/drift': 'Drift Findings',
  '#/cmdb/verification': 'Verification Queue',
  '#/cmdb/reports': 'CMDB Reports',
  '#/cmdb/services': 'Service Mapping',
  '#/lifecycle': 'Lifecycle Dashboard',
  '#/lifecycle/onboarding': 'Onboarding Cases',
  '#/lifecycle/offboarding': 'Offboarding Cases',
  '#/lifecycle/transfers': 'Transfers',
  '#/lifecycle/new': 'New Lifecycle Case',
  '#/procurement': 'Procurement',
  '#/procurement/requests': 'Purchase Requests',
  '#/procurement/orders': 'Purchase Orders',
  '#/procurement/receipts': 'Goods Receipts',
  '#/procurement/invoices': 'Supplier Invoices',
  '#/procurement/invoices/new': 'New Supplier Invoice',
  '#/procurement/exceptions': 'Invoice Exceptions',
  '#/procurement/returns': 'Vendor Returns',
  '#/procurement/returns/new': 'New Vendor Return',
  '#/procurement/credit-notes': 'Vendor Credit Notes',
  '#/procurement/credit-notes/new': 'New Vendor Credit Note',
  '#/procurement/financial-dashboard': 'Procurement Financial Dashboard',
  '#/procurement/vendor-performance': 'Vendor Performance',
  '#/procurement/assets': 'Asset registration',
  '#/procurement/reports': 'Procurement reports',
};

/** Sticky-header breadcrumb: parent -> record -> action. */
function crumbs(hash) {
  const h = hash.split('?')[0];
  let m;
  if ((m = h.match(/^#\/(tickets|assets)\/(\d+)(?:\/(edit))?$/))) {
    const trail = [m[1] === 'tickets' ? 'Tickets' : 'Assets', `#${m[2]}`];
    if (m[3]) trail.push('Edit');
    return trail;
  }
  if (h === '#/tickets/bulk-imports') return ['Tickets', 'Import operations'];
  if ((m = h.match(/^#\/tickets\/bulk-imports\/(\d+)$/))) return ['Tickets', 'Import operations', `#${m[1]}`];
  if (h === '#/tickets/new') return ['Tickets', 'New'];
  if (h === '#/assets/new') return ['Assets', 'New'];
  if (h === '#/assets/reports' || h.startsWith('#/assets/reports?')) return ['Assets', 'Asset Reports'];
  if (h === '#/vendors/new') return ['Vendors', 'New'];
  if (h === '#/recycle' || h === '#/audit') return ['Administration', TITLES[h]];
  if (h === '#/privacy') return ['Administration', 'Privacy erasure'];
  if (h.startsWith('#/privacy/')) return ['Administration', 'Privacy erasure'];
  if (h === '#/monitoring') return ['Administration', 'Monitoring'];
  if (h.startsWith('#/monitoring/')) return ['Administration', 'Monitoring'];
  if (h === '#/problem-management') return ['Service Operations', 'Problems'];
  if (h.startsWith('#/problem-management/')) return ['Service Operations', 'Problems', 'Problem'];
  if (h === '#/backup') return ['Administration', 'Backup & DR'];
  if (h.startsWith('#/backup/')) return ['Administration', 'Backup & DR'];
  if (h === '#/retention') return ['Administration', 'Data retention'];
  if (h.startsWith('#/retention/')) return ['Administration', 'Data retention'];
  if (h.startsWith('#/workflow')) return ['Workflow'];
  if (h.startsWith('#/reports/')) return ['Reports', TITLES[h]];
  if (h.startsWith('#/settings/')) return ['Settings', TITLES[h]];
  if ((m = h.match(/^#\/users\/(\d+)$/))) return ['Employees', `Employee #${m[1]}`];
  if (h === '#/cmdb') return ['CMDB'];
  if (h.startsWith('#/cmdb/items/new')) return ['CMDB', 'Configuration Items', 'New'];
  if ((m = h.match(/^#\/cmdb\/items\/(\d+)\/edit$/))) return ['CMDB', 'Configuration Items', `CI #${m[1]}`, 'Edit'];
  if ((m = h.match(/^#\/cmdb\/items\/(\d+)\/impact$/))) return ['CMDB', 'Configuration Items', `CI #${m[1]}`, 'Impact'];
  if ((m = h.match(/^#\/cmdb\/items\/(\d+)\/dependencies$/))) return ['CMDB', 'Configuration Items', `CI #${m[1]}`, 'Dependencies'];
  if ((m = h.match(/^#\/cmdb\/items\/(\d+)\/relationships$/))) return ['CMDB', 'Configuration Items', `CI #${m[1]}`, 'Relationships'];
  if ((m = h.match(/^#\/cmdb\/items\/(\d+)$/))) return ['CMDB', 'Configuration Items', `CI #${m[1]}`];
  if (h.startsWith('#/cmdb/items')) return ['CMDB', 'Configuration Items'];
  if (h.startsWith('#/cmdb/types')) return ['CMDB', 'CI Types'];
  if (h.startsWith('#/cmdb/baselines')) return ['CMDB', 'Baselines'];
  if (h.startsWith('#/cmdb/drift')) return ['CMDB', 'Drift Findings'];
  if (h.startsWith('#/cmdb/verification')) return ['CMDB', 'Verification Queue'];
  if (h.startsWith('#/cmdb/reports')) return ['CMDB', 'Reports'];
  if (h.startsWith('#/cmdb/services')) return ['CMDB', 'Service Mapping'];
  if (h.startsWith('#/cmdb/relationships')) return ['CMDB', 'Relationships'];
  if (h.startsWith('#/cmdb')) return ['CMDB'];
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
  if (h === '#/procurement/invoices/new') return ['Procurement', 'Supplier Invoices', 'New Supplier Invoice'];
  if ((m = h.match(/^#\/procurement\/invoices\/(\d+)\/match$/))) return ['Procurement', 'Supplier Invoices', 'Supplier Invoice', 'Matching'];
  if ((m = h.match(/^#\/procurement\/invoices\/(\d+)$/))) return ['Procurement', 'Supplier Invoices', 'Supplier Invoice'];
  if (h === '#/procurement/invoices') return ['Procurement', 'Supplier Invoices'];
  if (h === '#/procurement/exceptions') return ['Procurement', 'Invoice Exceptions'];
  if (h === '#/procurement/returns/new') return ['Procurement', 'Vendor Returns', 'New Vendor Return'];
  if ((m = h.match(/^#\/procurement\/returns\/(\d+)$/))) return ['Procurement', 'Vendor Returns', 'Vendor Return'];
  if (h === '#/procurement/returns') return ['Procurement', 'Vendor Returns'];
  if (h === '#/procurement/credit-notes/new') return ['Procurement', 'Vendor Credit Notes', 'New Vendor Credit Note'];
  if ((m = h.match(/^#\/procurement\/credit-notes\/(\d+)$/))) return ['Procurement', 'Vendor Credit Notes', 'Vendor Credit Note'];
  if (h === '#/procurement/credit-notes') return ['Procurement', 'Vendor Credit Notes'];
  if (h === '#/procurement/financial-dashboard') return ['Procurement', 'Financial Dashboard'];
  if (h === '#/procurement/vendor-performance') return ['Procurement', 'Vendor Performance'];
  if (h === '#/procurement') return ['Procurement', 'Dashboard'];
  if (h.startsWith('#/procurement/requests')) return ['Procurement', 'Purchase Requests'];
  if (h.startsWith('#/procurement/orders')) return ['Procurement', 'Purchase Orders'];
  if (h.startsWith('#/procurement/receipts')) return ['Procurement', 'Goods Receipts'];
  if (h.startsWith('#/procurement/assets')) return ['Procurement', 'Asset registration'];
  if (h.startsWith('#/procurement/reports')) return ['Procurement', 'Reports'];
  // Change Management breadcrumbs
  if (h === '#/changes') return ['Change Management', 'Changes'];
  if (h === '#/changes/new') return ['Change Management', 'New Change'];
  if (h === '#/changes/calendar') return ['Change Management', 'Calendar'];
  if (h === '#/changes/schedule') return ['Change Management', 'Schedule'];
  if (h === '#/changes/dashboard') return ['Change Management', 'Dashboard'];

  if ((m = h.match(/^#\/changes\/(\d+)(?:\/(edit|risk|tasks|approvals|conflicts|implementation|pir))?$/))) {
    const labels = {
      edit: 'Edit',
      risk: 'Risk Assessment',
      tasks: 'Tasks',
      approvals: 'Approvals',
      conflicts: 'Conflicts',
      implementation: 'Implementation',
      pir: 'Post-Implementation Review',
    };
    return ['Change Management', `Change #${m[1]}`, ...(m[2] ? [labels[m[2]]] : [])];
  }

  if (h === '#/change-templates') return ['Change Management', 'Templates'];
  if (h === '#/maintenance-windows') return ['Change Management', 'Maintenance Windows'];
  if (h === '#/blackout-periods') return ['Change Management', 'Blackout Periods'];
  if (h === '#/scheduling-exceptions') return ['Change Management', 'Scheduling Exceptions'];
  if (h === '#/change-review-meetings') return ['Change Management', 'Review Meetings'];
  if (h === '#/outages') return ['Change Management', 'Outages'];
  return [TITLES[h] ?? 'Tickets'];
}

function AccessDenied() {
  return <div className="access-denied" role="alert">You do not have permission to access this page.</div>;
}

function matchRoute(hash, auth) {
  let route = hash.split('?')[0];
  let m;
  if (route.startsWith('#/monitoring')) {
    if (!auth.canUseMonitoring) return <AccessDenied />;
    if (route === '#/monitoring') return <Monitoring />;
    if (route === '#/monitoring/overview') return <MonitoringOverview />;
    if (route === '#/monitoring/sources') return auth.isAdmin ? <SourceManagement /> : <AccessDenied />;
    if (route === '#/monitoring/alerts') return <AlertList />;
    if ((m = route.match(/^#\/monitoring\/alerts\/(\d+)$/))) return <AlertDetail alertId={m[1]} />;
    if (route === '#/monitoring/policies') return auth.canUseMonitoring ? <PolicyManagement /> : <AccessDenied />;
  }
  if (route === '#/reports/coverage') return <AssetReportsPage />;
  if (route === '#/reports/verification_age') return <VerificationQueuePage />;
  if (route === '#/reports/orphans') return <AssetReportsPage />;
  if (route === '#/reports/ownership_gaps') return <AssetReportsPage />;
  if (route === '#/reports/relationship_coverage') return <AssetReportsPage />;
  if (route === '#/reports/drift') return <DriftFindingsPage />;
  if (route === '#/reports/critical_deps') return <AssetReportsPage />;
  if (route === '#/reports/asset_sync') return <AssetReportsPage />;
  if (route === '#/reports/software_sync') return <AssetReportsPage />;
  if (route === '#/verification') return <VerificationQueuePage />;

  // --- Service detail routes ---


  // --- CMDB dashboard and items ---
  if (route === '#/cmdb') return <CmdbDashboard />;
  if (route === '#/cmdb/items') return <CmdbItemsList />;
  if (route === '#/cmdb/items/new') return <CiForm />;
  if ((m = route.match(/^#\/cmdb\/items\/(\d+)$/))) return <CiDetail id={m[1]} />;
  if ((m = route.match(/^#\/cmdb\/items\/(\d+)\/edit$/))) return <CiForm id={m[1]} />;
  if ((m = route.match(/^#\/cmdb\/items\/(\d+)\/impact$/))) return <ImpactAnalysisPage id={m[1]} />;
  if ((m = route.match(/^#\/cmdb\/items\/(\d+)\/dependencies$/))) return <DependencyMap id={m[1]} />;
  if ((m = route.match(/^#\/cmdb\/items\/(\d+)\/relationships$/))) return <CiRelationshipsPage id={m[1]} />;
  if (route === '#/cmdb/types') return <CiTypesPage />;
  if (route === '#/cmdb/baselines') return <BaselinesPage />;
  if (route === '#/cmdb/drift') return <DriftFindingsPage />;
  if (route === '#/cmdb/verification') return <VerificationQueuePage />;
  if (route === '#/cmdb/reports') return <CmdbReports />;
  if (route === '#/cmdb/services') return <ServiceMappingPage />;
  if (route === '#/cmdb/relationships') return <CmdbItemsList />;

  if (route.startsWith('#/problem-management')) {
    if (!auth.canUseProblemManagement) return <AccessDenied />;
    if (route === '#/problem-management') return <ProblemList />;
    if ((m = route.match(/^#\/problem-management\/(\d+)$/))) return <ProblemDetail problemId={m[1]} />;
  }
  if (route === '#/tickets/bulk-imports') return auth.isStaff ? <TicketBulkImportsPage /> : <AccessDenied />;
  if ((m = route.match(/^#\/tickets\/bulk-imports\/(\d+)$/))) return auth.isStaff ? <TicketBulkImportDetailPage id={m[1]} /> : <AccessDenied />;
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
  if ((m = route.match(/^#\/users\/(\d+)\/?$/))) return auth.isAdmin ? <EmployeeDetail id={m[1]} /> : <AccessDenied />;
  if (route === '#/kb') return <KnowledgeBase />;
  const changeManagementRoutes = [
    '#/change-templates',
    '#/maintenance-windows',
    '#/blackout-periods',
    '#/scheduling-exceptions',
    '#/change-review-meetings',
    '#/outages',
  ];
  if (
    route === '#/changes' ||
    route.startsWith('#/changes/') ||
    changeManagementRoutes.includes(route)
  ) return <ChangesPage />;
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
    '#/reports/coverage': <AssetReportsPage />,
    '#/reports/verification_age': <VerificationQueuePage />,
    '#/reports/orphans': <AssetReportsPage />,
    '#/reports/ownership_gaps': <AssetReportsPage />,
    '#/reports/relationship_coverage': <AssetReportsPage />,
    '#/reports/drift': <DriftFindingsPage />,
    '#/reports/critical_deps': <AssetReportsPage />,
    '#/reports/asset_sync': <AssetReportsPage />,
    '#/reports/software_sync': <AssetReportsPage />,
    '#/verification': <VerificationQueuePage />,
    '#/assets': <Assets />,
    '#/assets/reports': <AssetReportsPage />,
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
    '#/users': auth.isAdmin ? <Users /> : <AccessDenied />,
    '#/profile': <Profile />,
    '#/verify-email': <VerifyEmail />,
    '#/reset-password': <ResetPassword />,
    '#/self-service': <SelfService />,
    '#/changes': <ChangesPage />,
    '#/cmdb': <CmdbDashboard />,
  };
  // Explicit route handlers above take precedence; routes object is fallback
  return routes[route] ?? <Tickets />;
}

function isActive(hash, h) {
  return h === hash || (h !== '#/tickets' && hash.startsWith(h + '/'));
}

function Shell() {
  const { access, logout, user, profileLoading, isAdmin, isStaff, canManageScheduledReports, canViewVendors, canViewProcurement, canViewProcurementReports, canAccessRecycleBin } = useAuth();
  const canUseMonitoring = !!isStaff && user?.is_active !== false;
  const canUseProblemManagement = !!isStaff && user?.is_active !== false;
  const caps = useMemo(() => ({
    isStaff, isAdmin, canManageScheduledReports, canViewVendors,
    canViewProcurement, canViewProcurementReports, canUseMonitoring,
    canUseProblemManagement, canAccessRecycleBin,
  }), [isStaff, isAdmin, canManageScheduledReports, canViewVendors,
    canViewProcurement, canViewProcurementReports, canUseMonitoring,
    canUseProblemManagement, canAccessRecycleBin]);
  const routerLocation = useLocation();
  // HashRouter reports the default root as pathname '/'. Keep the historical
  // default (Tickets) so the rendered page and the highlighted nav item agree.
  const hash = routerLocation.pathname === '/'
    ? '#/tickets'
    : '#' + routerLocation.pathname + routerLocation.search;
  const nav = useMemo(() => visibleNav(NAV, caps), [caps]);
  const [navOpen, setNavOpen] = useState(false);
  // Collapsible sections are collapsed by default. Only sections the user has
  // explicitly expanded are tracked here, so late-loading navigation data
  // cannot accidentally leave sections open.
  const [expandedSections, setExpandedSections] = useState(() => new Set());

  // Toggle a module section open/closed. Clicking one section never affects others.
  const toggleSection = (sectionName) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sectionName)) next.delete(sectionName);
      else next.add(sectionName);
      return next;
    });
  };

  const isSectionCollapsed = (sectionName) => !expandedSections.has(sectionName);
  if (!access) {
    if (hash.startsWith('#/verify-email')) return <VerifyEmail />;
    if (hash.startsWith('#/reset-password')) return <ResetPassword />;
    return <Login />;
  }
  if (profileLoading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading your workspace{'\u2026'}
      </p>
    );
  }
  const el = matchRoute(hash, { isStaff, isAdmin, canUseMonitoring, canUseProblemManagement });
  const active = (h) => isActive(hash, h) ? 'active' : '';
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
            ? (
              <React.Fragment key={i}>
                <button
                  className="sidenav-section-header"
                  type="button"
                  aria-expanded={!isSectionCollapsed(n.section)}
                  aria-controls={`sidenav-section-content-${i}`}
                  onClick={() => toggleSection(n.section)}
                >
                  <span className="sidenav-section-title">{n.section}</span>
                  <span
                    className="sidenav-section-chevron"
                    aria-hidden="true"
                  >
                    {isSectionCollapsed(n.section) ? '\u25B6' : '\u25BC'}
                  </span>
                </button>
                <div
                  id={`sidenav-section-content-${i}`}
                  className={`sidenav-section-content${
                    isSectionCollapsed(n.section) ? ' collapsed' : ''
                  }`}
                >
                  {(() => {
                    const items = [];
                    let j = i + 1;
                    while (j < nav.length && !nav[j].section) {
                      items.push(nav[j]);
                      j += 1;
                    }
                    return items.map((item) => (
                      <a
                        key={item.hash}
                        href={item.hash}
                        className={active(item.hash)}
                        aria-current={isActive(hash, item.hash) ? 'page' : undefined}
                        onClick={() => setNavOpen(false)}
                      >
                        <span className="nav-label">{item.label}</span>
                        {item.badge && <NotifBadge />}
                      </a>
                    ));
                  })()}
                </div>
              </React.Fragment>
            )
            : null
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
          <button type="button" className="nav-toggle" onClick={() => setNavOpen((v) => !v)} aria-label={navOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={navOpen}>{'\u2630'}</button>
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs(hash).map((c, i, arr) => (
              <span key={i}>
                {i > 0 && <span className="crumb-sep" aria-hidden="true">/</span>}
                <span className={i === arr.length - 1 ? 'crumb-current' : undefined}>{c}</span>
              </span>
            ))}
          </nav>
        </div>
        <main className="content" id="main-content">
          <ErrorBoundary
            fallback={
              <div className="panel panel-pad" role="alert">
                <h2>Something went wrong</h2>
                <p>This page encountered an error and could not render.</p>
              </div>
            }
          >
            <Suspense fallback={<p className="page-loading" role="status"><span className="spinner" aria-hidden="true" />Loading page{'\u2026'}</p>}>
              {el}
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const { push } = useToast();
  // Surface unhandled API errors (4xx/5xx that reach the interceptor catch) as toasts.
  React.useEffect(() => {
    import('./api').then(({ setApiErrorHandler }) => {
      setApiErrorHandler((err, status) => {
        const msg = err?.message || 'Request failed';
        push(`${status ? `${status} - ` : ''}${msg}`, 'error');
      });
    });
    // Give ErrorBoundary access to the toast push function.
    import('./ErrorBoundary').then(({ setToastContext }) => {
      setToastContext({ push });
    });
  }, [push]);

  return (
    <HashRouter>
      <AuthProvider>
        <ToastProvider>
          <DirtyProvider>
            <Shell />
            <ToastList />
            <DirtyBlocker />
          </DirtyProvider>
        </ToastProvider>
      </AuthProvider>
    </HashRouter>
  );
}
