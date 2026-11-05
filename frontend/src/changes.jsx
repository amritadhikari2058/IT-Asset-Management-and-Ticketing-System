/*
 * Change Management - Frontend for IT Ticketing & Asset Management System
 * Routes: #/changes, #/changes/new, #/changes/calendar, #/changes/dashboard,
 * #/changes/:id, #/changes/:id/edit, #/changes/:id/risk, #/changes/:id/tasks,
 * #/changes/:id/approvals, #/changes/:id/conflicts, #/changes/:id/implementation,
 * #/changes/:id/pir, #/change-templates, #/maintenance-windows,
 * #/change-review-meetings, #/outages
 *
 * Connected to the real Change Management API at /api/changes/
 */

import { useEffect } from 'react';
import { ChangeList } from './change-list';
import { ChangeForm } from './change-form';
import { ChangeDetail } from './change-detail';
import { ChangeRisk } from './change-risk';
import { ChangeTasks } from './change-tasks';
import { ChangeApprovals } from './change-approvals';
import { ChangeSchedule } from './change-schedule';
import { ChangeConflicts } from './change-conflicts';
import { ChangeImplementation } from './change-implementation';
import { ChangePIR } from './change-pir';
import { ChangeCalendar } from './change-calendar';
import { MaintenanceWindows } from './maintenance-windows';
import { ChangeTemplates } from './change-templates';
import { ReviewMeetings } from './review-meetings';
import { ChangeReports } from './change-reports';
import { EmployeeOutages } from './outages';

export const changeRoutes = [
  { path: '#/changes', component: ChangeList, title: 'Changes', breadcrumbs: ['Change Management'] },
  { path: '#/changes/new', component: ChangeForm, title: 'New Change', breadcrumbs: ['Change Management', 'New Change'] },
  { path: '#/changes/calendar', component: ChangeCalendar, title: 'Change Calendar', breadcrumbs: ['Change Management', 'Calendar'] },
  { path: '#/changes/dashboard', component: () => import('./change-dashboard'), title: 'Change Dashboard', breadcrumbs: ['Change Management', 'Dashboard'] },
  { path: '#/changes/:id', component: ChangeDetail, title: 'Change Detail', breadcrumbs: ['Change Management'] },
  { path: '#/changes/:id/edit', component: ChangeForm, title: 'Edit Change', breadcrumbs: ['Change Management', 'Edit Change'] },
  { path: '#/changes/:id/risk', component: ChangeRisk, title: 'Risk Assessment', breadcrumbs: ['Change Management', 'Risk'] },
  { path: '#/changes/:id/tasks', component: ChangeTasks, title: 'Task Checklist', breadcrumbs: ['Change Management', 'Tasks'] },
  { path: '#/changes/:id/approvals', component: ChangeApprovals, title: 'Approvals', breadcrumbs: ['Change Management', 'Approvals'] },
  { path: '#/changes/:id/conflicts', component: ChangeConflicts, title: 'Conflicts', breadcrumbs: ['Change Management', 'Conflicts'] },
  { path: '#/changes/:id/implementation', component: ChangeImplementation, title: 'Implementation', breadcrumbs: ['Change Management', 'Implementation'] },
  { path: '#/changes/:id/pir', component: ChangePIR, title: 'PIR & Closure', breadcrumbs: ['Change Management', 'PIR'] },
  { path: '#/change-templates', component: ChangeTemplates, title: 'Change Templates', breadcrumbs: ['Change Management', 'Templates'] },
  { path: '#/maintenance-windows', component: MaintenanceWindows, title: 'Maintenance Windows', breadcrumbs: ['Change Management', 'Maintenance'] },
  { path: '#/change-review-meetings', component: ReviewMeetings, title: 'Review Meetings', breadcrumbs: ['Change Management', 'Meetings'] },
  { path: '#/outages', component: EmployeeOutages, title: 'Outages', breadcrumbs: ['Change Management', 'Outages'] },
];

export default function ChangesPage() {
  useEffect(() => {
    // Document title based on route
    const handleHashChange = () => {
      const hash = window.location.hash.replace('#', '') || '/changes';
      const route = changeRoutes.find((r) => hash.startsWith(r.path));
      const title = route ? route.title : 'Changes';
      document.title = `${title} - IT Change Management`;
    };
    window.addEventListener('hashchange', handleHashChange);
    handleHashChange();
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  return null; // Routes are handled by App.jsx hash routing
}