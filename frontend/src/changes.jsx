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
import { ChangeScheduleView } from './change-schedule-view';
import { ChangeDashboard } from './change-dashboard';
import { MaintenanceWindows } from './maintenance-windows';
import { ChangeTemplates } from './change-templates';
import { ChangeReviewMeetings as ReviewMeetings } from './change-review-meetings';
import { ChangeReports } from './change-reports';
import { EmployeeOutages } from './outages';
import { BlackoutPeriods } from './blackout-periods';
import { SchedulingExceptions } from './scheduling-exceptions';

export const changeRoutes = [
  { path: '#/changes', component: ChangeList, title: 'Changes', breadcrumbs: ['Change Management'] },
  { path: '#/changes/new', component: ChangeForm, title: 'New Change', breadcrumbs: ['Change Management', 'New Change'] },
  { path: '#/changes/calendar', component: ChangeCalendar, title: 'Change Calendar', breadcrumbs: ['Change Management', 'Calendar'] },
  { path: '#/changes/schedule', component: ChangeScheduleView, title: 'Change Schedule', breadcrumbs: ['Change Management', 'Schedule'] },
  { path: '#/changes/dashboard', component: ChangeDashboard, title: 'Change Dashboard', breadcrumbs: ['Change Management', 'Dashboard'] },
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
  { path: '#/blackout-periods', component: BlackoutPeriods, title: 'Blackout Periods', breadcrumbs: ['Change Management', 'Blackout'] },
  { path: '#/scheduling-exceptions', component: SchedulingExceptions, title: 'Scheduling Exceptions', breadcrumbs: ['Change Management', 'Exceptions'] },
  { path: '#/change-review-meetings', component: ReviewMeetings, title: 'Review Meetings', breadcrumbs: ['Change Management', 'Meetings'] },
  { path: '#/outages', component: EmployeeOutages, title: 'Outages', breadcrumbs: ['Change Management', 'Outages'] },
];

export function ChangesPage() {
  const hash = window.location.hash || '#/changes';
  const hashNoQuery = hash.split('?')[0];
  let route = null;
  let matchParams = {};

  for (const r of changeRoutes) {
    const regexStr = '^' + r.path
      .replace(/:[^/]+/g, '([^/]+)')
      .replace(/\//g, '\\/')
      + '$';
    const regex = new RegExp(regexStr);
    const m = hashNoQuery.match(regex);
    if (m) {
      route = r;
      const paramNames = r.path.match(/:([^/]+)/g) || [];
      paramNames.forEach((pn, i) => {
        matchParams[pn.slice(1)] = m[i + 1];
      });
      break;
    }
  }

  const Comp = route ? route.component : ChangeList;

  useEffect(() => {
    document.title = `${(route ? route.title : 'Changes')} - IT Change Management`;
  }, [route]);

  return <Comp match={{ params: matchParams }} />;
}