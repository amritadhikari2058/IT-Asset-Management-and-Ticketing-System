// Change Management utilities and constants
// Derived from backend models, serializers, views, risk, permissions

// Status Labels (from backend STATUS_CHOICES)
export const STATUS_LABELS = {
  draft: 'Draft',
  submitted: 'Submitted',
  risk_assessment: 'Risk Assessment',
  technical_review: 'Technical Review',
  pending_approval: 'Pending Approval',
  approved: 'Approved',
  scheduled: 'Scheduled',
  in_progress: 'Implementation In Progress',
  validation: 'Validation',
  completed: 'Completed',
  pir_required: 'Post-Implementation Review Required',
  closed: 'Closed',
  on_hold: 'On Hold',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
  failed: 'Failed',
  rolled_back: 'Rolled Back',
};

// Change Type Labels (from backend CHANGE_TYPE_CHOICES)
export const CHANGE_TYPE_LABELS = {
  standard: 'Standard',
  normal: 'Normal',
  emergency: 'Emergency',
};

// Category Labels (from backend CATEGORY_CHOICES)
export const CATEGORY_LABELS = {
  application: 'Application',
  infrastructure: 'Infrastructure',
  network: 'Network',
  security: 'Security',
  database: 'Database',
  hardware: 'Hardware',
  software: 'Software',
  access: 'Access',
  configuration: 'Configuration',
  maintenance: 'Maintenance',
  deployment: 'Deployment',
  other: 'Other',
};

// Priority Labels (from backend PRIORITY_CHOICES)
export const PRIORITY_LABELS = {
  low: 'Low',
  normal: 'Normal',
  high: 'High',
  urgent: 'Urgent',
  emergency: 'Emergency',
};

// Risk Level Labels (from backend RISK_LEVEL_CHOICES)
export const RISK_LEVEL_LABELS = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
};
export function formatDate(date) {
  if (!date) return '';
  const d = new Date(date);
  if (isNaN(d)) return String(date);
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function formatDateTime(dateTime) {
  if (!dateTime) return '';
  const d = new Date(dateTime);
  if (isNaN(d)) return String(dateTime);
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatDuration(minutes) {
  if (minutes === null || minutes === undefined || isNaN(minutes)) return '';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h > 0 && m > 0) return `${h} hours ${m} minutes`;
  if (h > 0) return `${h} hours`;
  return `${m} minutes`;
}

export function statusBadgeVariant(status) {
  const terminal = ['completed', 'closed', 'rejected', 'cancelled', 'failed', 'rolled_back'];
  const inprogress = ['in_progress', 'validation'];
  const approvedish = ['approved', 'scheduled'];
  if (terminal.includes(status)) return 'danger';
  if (inprogress.includes(status)) return 'warning';
  if (approvedish.includes(status)) return 'success';
  return 'secondary';
}

export function riskBadgeVariant(riskLevel) {
  const riskMap = { low: 'success', medium: 'info', high: 'warning', critical: 'danger' };
  return riskMap[riskLevel] || 'secondary';
}

export function priorityBadgeVariant(priority) {
  const priorityMap = { low: 'secondary', normal: 'info', high: 'warning', urgent: 'danger', emergency: 'danger' };
  return priorityMap[priority] || 'secondary';
}

export function isTerminalStatus(status) {
  const terminal = ['completed', 'closed', 'rejected', 'cancelled', 'failed', 'rolled_back'];
  return terminal.includes(status);
}

export function isEditableStatus(status) {
  const editable = ['draft', 'submitted'];
  return editable.includes(status);
}

export function safeResults(arr) {
  if (!arr) return [];
  return arr;
}

export function buildChangeListUrl(filters = {}, pageSize, page) {
  const params = new URLSearchParams();
  const orderedKeys = [
    'type', 'category', 'status', 'priority', 'risk', 'department',
    'implementation_lead', 'owner', 'emergency', 'pir_required',
    'approval_state', 'overdue', 'upcoming',
  ];
  for (const key of orderedKeys) {
    if (filters[key] !== undefined && filters[key] !== null) {
      params.append(key, String(filters[key]));
    }
  }
  if (pageSize !== undefined) params.append('page_size', pageSize);
  if (page !== undefined) params.append('page', page);
  return params.toString() ? `?${params.toString()}` : '';
}

export function parseFieldErrors(errorResponse) {
  if (!errorResponse) return {};
  const data = errorResponse.response?.data;
  if (!data) return {};
  const out = {};
  for (const [k, v] of Object.entries(data)) {
    let msg = Array.isArray(v) ? v.join(' ') : (typeof v === 'object' ? JSON.stringify(v) : String(v));
    out[k] = msg;
  }
  return out;
}

export function actionAvailability(role, status, action) {
  if (!role) return false;

  const isAdmin = role === 'system_admin';
  const isManager = role === 'it_manager';
  const isSupport = role === 'it_support';
  const isEmployee = role === 'employee';

  if (isAdmin) return true;
  if (isEmployee) {
    return ['view', 'detail'].includes(action);
  }

  if (isSupport) {
    const supportActions = {
      create_draft: status === 'draft' || status === 'submitted',
      edit_own_draft: status === 'draft',
      view: true,
      detail: true,
      risk: status !== 'completed' && status !== 'closed' && status !== 'rolled_back' && status !== 'cancelled',
      tasks: status !== 'completed' && status !== 'closed' && status !== 'rolled_back' && status !== 'cancelled',
      implementation: false,
      approvals: false,
      schedule: false,
      pir: false,
      close: false,
      cancel: status === 'draft' || status === 'submitted' || status === 'on_hold',
      view_conflicts: true,
    };
    return supportActions[action] ?? false;
  }

  if (isManager) {
    const managerActions = {
      create: true,
      edit: true,
      submit: !isTerminalStatus(status),
      submit_draft: status === 'draft',
      risk: true,
      confirm_risk: status === 'risk_assessment' || status === 'submitted',
      start_technical_review: status === 'submitted',
      complete_technical_review: status === 'risk_assessment',
      request_approval: status === 'technical_review',
      approve: status === 'pending_approval',
      reject: status === 'pending_approval',
      return_correction: status === 'pending_approval',
      schedule: status === 'approved',
      reschedule: status === 'scheduled',
      hold: status !== 'closed' && status !== 'cancelled' && status !== 'failed' && status !== 'rolled_back',
      resume: status === 'on_hold',
      convert_emergency: status === 'normal' || status === 'standard',
      start_implementation: status === 'scheduled',
      begin_validation: status === 'in_progress',
      complete: status === 'validation',
      fail: status !== 'closed' && status !== 'cancelled' && status !== 'rolled_back',
      start_rollback: status === 'failed',
      complete_rollback: status === 'rolled_back',
      request_pir: status === 'completed',
      close: status === 'completed',
      cancel: !isTerminalStatus(status),
      view_conflicts: true,
      templates: true,
      maintenance_windows: true,
    };
    return managerActions[action] ?? false;
  }

  return false;
}

// Export all constants and helpers
export const ChangeUtils = {
  STATUS_LABELS,
  CHANGE_TYPE_LABELS,
  CATEGORY_LABELS,
  PRIORITY_LABELS,
  RISK_LEVEL_LABELS,
  formatDate,
  formatDateTime,
  formatDuration,
  statusBadgeVariant,
  riskBadgeVariant,
  priorityBadgeVariant,
  isTerminalStatus,
  isEditableStatus,
  safeResults,
  buildChangeListUrl,
  parseFieldErrors,
  actionAvailability,
};

export default ChangeUtils;
// Shared API helpers used by change-management components
export { fetchPage, parseApiError } from '../api-utils';
