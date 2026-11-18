/* Employee Lifecycle UI constants and helpers.

All enum values are derived from backend/lifecycle/models.py and the
serializers in backend/lifecycle/serializers.py. The backend remains the
authority; these constants only mirror accepted values for labels and
UI state machine helpers.
*/

export const CASE_TYPE_CHOICES = [
  { value: 'onboarding', label: 'Onboarding' },
  { value: 'offboarding', label: 'Offboarding' },
  { value: 'transfer', label: 'Transfer / Role Change' },
];

export const CASE_TYPE_LABELS = {
  onboarding: 'Onboarding',
  offboarding: 'Offboarding',
  transfer: 'Transfer / Role Change',
};

export const CASE_STATUS_CHOICES = [
  { value: 'draft', label: 'Draft' },
  { value: 'planned', label: 'Planned' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'ready_for_employee', label: 'Ready for Employee' },
  { value: 'employee_started', label: 'Employee Started' },
  { value: 'awaiting_asset_return', label: 'Awaiting Asset Return' },
  { value: 'awaiting_access_revocation', label: 'Awaiting Access Revocation' },
  { value: 'ready_for_closure', label: 'Ready for Closure' },
  { value: 'access_updated', label: 'Access Updated' },
  { value: 'asset_changes_completed', label: 'Asset Changes Completed' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'blocked', label: 'Blocked' },
];

export const CASE_STATUS_LABELS = {
  draft: 'Draft',
  planned: 'Planned',
  in_progress: 'In Progress',
  ready_for_employee: 'Ready for Employee',
  employee_started: 'Employee Started',
  awaiting_asset_return: 'Awaiting Asset Return',
  awaiting_access_revocation: 'Awaiting Access Revocation',
  ready_for_closure: 'Ready for Closure',
  access_updated: 'Access Updated',
  asset_changes_completed: 'Asset Changes Completed',
  completed: 'Completed',
  cancelled: 'Cancelled',
  blocked: 'Blocked',
};

export const TERMINAL_STATUSES = ['completed', 'cancelled'];

export const SOURCE_CHOICES = [
  { value: 'manual', label: 'Manual' },
  { value: 'service_request', label: 'Service Request' },
  { value: 'employee_created', label: 'Employee Created' },
  { value: 'department_transfer', label: 'Department Transfer' },
  { value: 'account_deactivation', label: 'Account Deactivation' },
];

export const PRIORITY_CHOICES = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'urgent', label: 'Urgent' },
];

export const PRIORITY_LABELS = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  urgent: 'Urgent',
};

export const TASK_STATUS_CHOICES = [
  { value: 'pending', label: 'Pending' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'completed', label: 'Completed' },
  { value: 'blocked', label: 'Blocked' },
  { value: 'skipped', label: 'Skipped' },
  { value: 'cancelled', label: 'Cancelled' },
];

export const TASK_STATUS_LABELS = {
  pending: 'Pending',
  in_progress: 'In Progress',
  completed: 'Completed',
  blocked: 'Blocked',
  skipped: 'Skipped',
  cancelled: 'Cancelled',
};

export const AUTOMATION_STATUS_CHOICES = [
  { value: 'not_applicable', label: 'Not Applicable' },
  { value: 'pending', label: 'Pending' },
  { value: 'running', label: 'Running' },
  { value: 'succeeded', label: 'Succeeded' },
  { value: 'failed', label: 'Failed' },
  { value: 'manual_review', label: 'Manual Review' },
];

export const AUTOMATION_STATUS_LABELS = {
  not_applicable: 'Not Applicable',
  pending: 'Pending',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  manual_review: 'Manual Review',
};

export const AUTOMATION_TYPES = [
  { value: 'none', label: 'None' },
  { value: 'create_service_request', label: 'Create Service Request' },
  { value: 'create_ticket', label: 'Create Ticket' },
  { value: 'assign_asset', label: 'Assign Asset' },
  { value: 'return_assets', label: 'Return Assets' },
  { value: 'deactivate_account', label: 'Deactivate Account' },
  { value: 'revoke_tokens', label: 'Revoke Tokens' },
  { value: 'notification', label: 'Notification' },
];

export const TEMPLATE_ITEM_CATEGORY_CHOICES = [
  { value: 'account', label: 'Account' },
  { value: 'email', label: 'Email' },
  { value: 'hardware', label: 'Hardware' },
  { value: 'software', label: 'Software' },
  { value: 'access', label: 'Access' },
  { value: 'network', label: 'Network' },
  { value: 'security', label: 'Security' },
  { value: 'training', label: 'Training' },
  { value: 'asset_return', label: 'Asset Return' },
  { value: 'data_transfer', label: 'Data Transfer' },
  { value: 'documentation', label: 'Documentation' },
  { value: 'other', label: 'Other' },
];

export const CATEGORY_LABELS = {
  account: 'Account',
  email: 'Email',
  hardware: 'Hardware',
  software: 'Software',
  access: 'Access',
  network: 'Network',
  security: 'Security',
  training: 'Training',
  asset_return: 'Asset Return',
  data_transfer: 'Data Transfer',
  documentation: 'Documentation',
  other: 'Other',
};

export const RESPONSIBILITY_CHOICES = [
  { value: 'it', label: 'IT' },
  { value: 'manager', label: 'Manager' },
  { value: 'employee', label: 'Employee' },
  { value: 'hr', label: 'HR' },
  { value: 'security', label: 'Security' },
  { value: 'other', label: 'Other' },
];

export const RESPONSIBILITY_LABELS = {
  it: 'IT',
  manager: 'Manager',
  employee: 'Employee',
  hr: 'HR',
  security: 'Security',
  other: 'Other',
};

export const DEFAULT_ASSIGNEE_ROLE_LABELS = {
  system_admin: 'System Admin',
  it_manager: 'IT Manager',
  it_support: 'IT Support',
  employee: 'Employee',
  unassigned: 'Unassigned',
};

export const DEFAULT_ASSIGNEE_ROLE_CHOICES = [
  { value: 'system_admin', label: 'System Admin' },
  { value: 'it_manager', label: 'IT Manager' },
  { value: 'it_support', label: 'IT Support' },
  { value: 'employee', label: 'Employee' },
  { value: 'unassigned', label: 'Unassigned' },
];

export const ASSET_RESOLUTION_CHOICES = [
  { value: 'pending', label: 'Pending' },
  { value: 'returned', label: 'Returned' },
  { value: 'lost', label: 'Lost' },
  { value: 'damaged', label: 'Damaged' },
  { value: 'transferred', label: 'Transferred' },
  { value: 'approved_exception', label: 'Approved Exception' },
];

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

export function formatDate(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
    });
  } catch {
    return String(value);
  }
}

export function formatDateTime(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return String(value);
  }
}

export function formatPercent(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '0%';
  return `${Math.round(n)}%`;
}

// ---------------------------------------------------------------------------
// Badge tone helpers (Bootstrap 5 badge classes via components.Badge)
// ---------------------------------------------------------------------------

export function caseStatusBadgeVariant(status) {
  const map = {
    draft: 'gray',
    planned: 'blue',
    in_progress: 'blue',
    ready_for_employee: 'amber',
    employee_started: 'amber',
    awaiting_asset_return: 'amber',
    awaiting_access_revocation: 'amber',
    ready_for_closure: 'green',
    access_updated: 'blue',
    asset_changes_completed: 'green',
    completed: 'green',
    cancelled: 'gray',
    blocked: 'red',
  };
  return map[status] ?? 'gray';
}

export function taskStatusBadgeVariant(status) {
  const map = {
    pending: 'amber',
    in_progress: 'blue',
    completed: 'green',
    blocked: 'red',
    skipped: 'gray',
    cancelled: 'gray',
  };
  return map[status] ?? 'gray';
}

export function priorityBadgeVariant(priority) {
  const map = { low: 'gray', medium: 'blue', high: 'amber', urgent: 'red' };
  return map[priority] ?? 'gray';
}

// ---------------------------------------------------------------------------
// Safe collection helpers
// ---------------------------------------------------------------------------

export function safeResults(data) {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  return Array.isArray(data.results) ? data.results : [];
}

export function buildLifecycleListUrl(baseParams = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(baseParams)) {
    if (v !== '' && v != null) p.set(k, v);
  }
  const qs = p.toString();
  return qs ? `/lifecycle/cases/?${qs}` : '/lifecycle/cases/';
}

export function parseFieldErrors(error) {
  const { parseApiError } = require('./api-utils');
  return parseApiError(error);
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

export function isTerminalCaseStatus(status) {
  return status === 'completed' || status === 'cancelled';
}

// ---------------------------------------------------------------------------
// Action availability (frontend UX only; backend remains authoritative)
// ---------------------------------------------------------------------------

// Which frontend actions are offered for each (case_type, status) pair.
// Action keys mirror backend lifecycle viewset action names.
const TRANSITION_OFFER = {
  onboarding: {
    draft: ['plan'],
    planned: ['start'],
    in_progress: ['mark_ready', 'block', 'cancel'],
    ready_for_employee: ['confirm_start', 'block', 'cancel'],
    employee_started: ['block', 'cancel'],
    blocked: ['unblock', 'cancel'],
    ready_for_closure: ['complete'],
    // Additional backend-supported statuses
    awaiting_asset_return: ['return_assets', 'cancel'],
    awaiting_access_revocation: ['revoke_access', 'cancel'],
    access_updated: [],
    asset_changes_completed: ['complete', 'cancel'],
  },
  offboarding: {
    draft: ['plan'],
    planned: ['start'],
    in_progress: ['block', 'cancel'],
    blocked: ['unblock', 'cancel'],
    ready_for_closure: ['complete'],
    // Additional backend-supported statuses
    awaiting_asset_return: ['return_assets', 'cancel'],
    awaiting_access_revocation: ['revoke_access', 'cancel'],
    access_updated: [],
    asset_changes_completed: ['complete', 'cancel'],
  },
  transfer: {
    draft: ['plan'],
    planned: ['start'],
    in_progress: ['block', 'cancel'],
    blocked: ['unblock', 'cancel'],
    ready_for_closure: ['complete'],
    // Additional backend-supported statuses
    awaiting_asset_return: ['return_assets', 'cancel'],
    awaiting_access_revocation: ['revoke_access', 'cancel'],
    access_updated: [],
    asset_changes_completed: ['complete', 'cancel'],
  },
};

// Map frontend action keys to backend action labels for display.
const ACTION_LABELS = {
  plan: 'Plan',
  start: 'Start',
  mark_ready: 'Mark Ready',
  confirm_start: 'Confirm Employee Start',
  complete: 'Complete',
  block: 'Block',
  unblock: 'Unblock',
  cancel: 'Cancel',
};

// Map frontend action keys to whether they require a reason.
const ACTION_REASON_REQUIRED = {
  block: true,
  cancel: true,
};

export function actionAvailability(caseType, status, userRole) {
  const isAdmin = userRole === 'system_admin';
  const isManager = userRole === 'it_manager' || isAdmin;
  const isStaff = isManager || userRole === 'it_support';
  const isEmployee = userRole === 'employee';

  const byStatus = TRANSITION_OFFER[caseType] ?? {};
  const offered = byStatus[status] ?? [];

  const out = {};
  for (const action of offered) {
    switch (action) {
      case 'plan':
        out.plan = isManager;
        break;
      case 'start':
        out.start = isStaff;
        break;
      case 'mark_ready':
        out.mark_ready = isStaff && caseType === 'onboarding';
        break;
      case 'confirm_start':
        out.confirm_start = isStaff || isEmployee;
        break;
      case 'complete':
        out.complete = isManager;
        break;
      case 'block':
        out.block = isManager;
        break;
      case 'unblock':
        out.unblock = isManager;
        break;
      case 'cancel':
        out.cancel = isStaff;
        break;
    }
  }
  return out;
}

export function getActionLabel(action) {
  return ACTION_LABELS[action] ?? action;
}

export function isActionReasonRequired(action) {
  return !!ACTION_REASON_REQUIRED[action];
}
