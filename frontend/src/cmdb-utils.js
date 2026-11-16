/** Derived from the actual CMDB backend models/serializers/views.
 * Do not guess enum values — keep them in sync with backend.
 */

// ── CI Type Category Labels ──────────────────────────────────────────
export const CI_TYPE_CATEGORY_LABELS = {
  hardware: 'Hardware',
  software: 'Software',
  network: 'Network',
  other: 'Other',
};

// ── CI Status Labels ──────────────────────────────────────────────────
export const CI_STATUS_LABELS = {
  planned: 'Planned',
  active: 'Active',
  inactive: 'Inactive',
  maintenance: 'Maintenance',
  degraded: 'Degraded',
  failed: 'Failed',
  retired: 'Retired',
  disposed: 'Disposed',
  unknown: 'Unknown',
};

// ── CI Lifecycle State Labels ─────────────────────────────────────────
export const CI_LIFECYCLE_LABELS = {
  proposed: 'Proposed',
  ordered: 'Ordered',
  received: 'Received',
  installed: 'Installed',
  operational: 'Operational',
  under_change: 'Under Change',
  retired: 'Retired',
  disposed: 'Disposed',
};

// ── Criticality Labels ────────────────────────────────────────────────
export const CRITICALITY_LABELS = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
};

// ── Environment Labels ────────────────────────────────────────────────
export const ENVIRONMENT_LABELS = {
  development: 'Development',
  test: 'Test',
  staging: 'Staging',
  production: 'Production',
  disaster_recovery: 'Disaster Recovery',
  office: 'Office',
  other: 'Other',
};

// ── Source Labels ─────────────────────────────────────────────────────
export const SOURCE_LABELS = {
  manual: 'Manual',
  asset_sync: 'Asset Sync',
  licensing_sync: 'Licensing Sync',
  discovery: 'Discovery',
  import: 'Import',
  integration: 'Integration',
};

// ── Monitoring State Labels ───────────────────────────────────────────
export const MONITORING_STATE_LABELS = {
  monitored: 'Monitored',
  not_monitored: 'Not Monitored',
  not_applicable: 'Not Applicable',
  unknown: 'Unknown',
};

// ── Data Classification Labels ────────────────────────────────────────
export const DATA_CLASSIFICATION_LABELS = {
  public: 'Public',
  internal: 'Internal',
  confidential: 'Confidential',
  restricted: 'Restricted',
  unknown: 'Unknown',
};

// ── Validated-System Impact Labels ────────────────────────────────────
export const VALIDATED_SYSTEM_IMPACT_LABELS = {
  none: 'None',
  documentation_only: 'Documentation Only',
  configuration: 'Configuration',
  data_integrity_impact: 'Data Integrity Impact',
};

// ── Relationship Type Labels ──────────────────────────────────────────
export const RELATIONSHIP_TYPE_LABELS = {
  depends_on: 'Depends On',
  required_by: 'Required By',
  hosted_on: 'Hosted On',
  hosts: 'Hosts',
  runs_on: 'Runs On',
  runs: 'Runs',
  connects_to: 'Connects To',
  connected_from: 'Connected From',
  uses: 'Uses',
  used_by: 'Used By',
  contains: 'Contains',
  contained_by: 'Contained By',
  part_of: 'Part Of',
  has_part: 'Has Part',
  backs_up: 'Backs Up',
  backed_up_by: 'Backed Up By',
  replicates_to: 'Replicates To',
  replicated_from: 'Replicated From',
  monitors: 'Monitors',
  monitored_by: 'Monitored By',
  managed_by: 'Managed By',
  manages: 'Manages',
  supports: 'Supports',
  supported_by: 'Supported By',
  located_in: 'Located In',
  related_to: 'Related To',
  replaces: 'Replaces',
  replaced_by: 'Replaced By',
};

// ── Relationship Status Labels ────────────────────────────────────────
export const RELATIONSHIP_STATUS_LABELS = {
  active: 'Active',
  inactive: 'Inactive',
  proposed: 'Proposed',
  rejected: 'Rejected',
};

// ── Relationship Confidence Labels ────────────────────────────────────
export const RELATIONSHIP_CONFIDENCE_LABELS = {
  confirmed: 'Confirmed',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  unknown: 'Unknown',
};

// ── Baseline Scope Labels ─────────────────────────────────────────────
export const BASELINE_SCOPE_LABELS = {
  single_ci: 'Single CI',
  ci_group: 'CI Group',
  service: 'Service',
  environment: 'Environment',
  department: 'Department',
};

// ── Baseline Status Labels ─────────────────────────────────────────────
export const BASELINE_STATUS_LABELS = {
  draft: 'Draft',
  pending_approval: 'Pending Approval',
  approved: 'Approved',
  superseded: 'Superseded',
  retired: 'Retired',
};

// ── Drift Type Labels ─────────────────────────────────────────────────
export const DRIFT_TYPE_LABELS = {
  field_changed: 'Field Changed',
  relationship_added: 'Relationship Added',
  relationship_removed: 'Relationship Removed',
  relationship_changed: 'Relationship Changed',
  status_changed: 'Status Changed',
  owner_changed: 'Owner Changed',
  software_version_changed: 'Software Version Changed',
  unverified_ci: 'Unverified CI',
  orphan_ci: 'Orphan CI',
  duplicate_ci: 'Duplicate CI',
  missing_required_attribute: 'Missing Required Attribute',
  unexpected_attribute: 'Unexpected Attribute',
  other: 'Other',
};

// ── Drift Severity Labels ─────────────────────────────────────────────
export const DRIFT_SEVERITY_LABELS = {
  info: 'Info',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
};

// ── Drift Status Labels ───────────────────────────────────────────────
export const DRIFT_STATUS_LABELS = {
  open: 'Open',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
  accepted: 'Accepted',
  false_positive: 'False Positive',
};

// ── Verification Status Labels ────────────────────────────────────────
export const VERIFICATION_STATUS_LABELS = {
  never_verified: 'Never Verified',
  verified: 'Verified',
};

// ── Format helpers ─────────────────────────────────────────────────────

export function formatDate(dateString) {
  if (!dateString) return '—';
  return new Date(dateString).toLocaleDateString();
}

export function formatDateTime(dateString) {
  if (!dateString) return '—';
  return new Date(dateString).toLocaleString();
}

export function formatPercent(value) {
  if (value == null) return '—';
  const pct = Number(value);
  if (isNaN(pct)) return '—';
  return `${pct.toFixed(1)}%`;
}

// ── Badge variant functions ────────────────────────────────────────────

export function ciStatusBadgeVariant(status) {
  const map = {
    active: 'green',
    degraded: 'amber',
    failed: 'red',
    retired: 'gray',
    disposed: 'purple',
    maintenance: 'amber',
    planned: 'gray',
    inactive: 'gray',
  };
  return map[status] ?? 'gray';
}

export function criticalityBadgeVariant(criticality) {
  const map = {
    critical: 'red',
    high: 'red',
    medium: 'amber',
    low: 'green',
  };
  return map[criticality] ?? 'gray';
}

export function driftSeverityBadgeVariant(severity) {
  const map = {
    critical: 'red',
    high: 'red',
    medium: 'amber',
    low: 'green',
    info: 'gray',
  };
  return map[severity] ?? 'gray';
}

export function driftStatusBadgeVariant(status) {
  const map = {
    resolved: 'green',
    acknowledged: 'amber',
    accepted: 'green',
    open: 'red',
    false_positive: 'gray',
  };
  return map[status] ?? 'gray';
}

export function baselineStatusBadgeVariant(status) {
  const map = {
    approved: 'green',
    pending_approval: 'amber',
    draft: 'blue',
    superseded: 'gray',
    retired: 'gray',
  };
  return map[status] ?? 'gray';
}

// ── safeResults: filter null/undefined from array-like results ──────────
export function safeResults(arr) {
  if (!arr) return [];
  if (Array.isArray(arr)) return arr.filter((x) => x != null);
  return [arr].filter((x) => x != null);
}

// ── URL builder helpers ────────────────────────────────────────────────

export function buildCIListUrl(filters = {}) {
  const params = new URLSearchParams();
  const allowed = [
    'type', 'category', 'status', 'lifecycle_state', 'criticality',
    'environment', 'department', 'location', 'owner', 'technical_owner',
    'vendor', 'source', 'verified', 'monitoring_state',
    'data_classification', 'validated_system_impact',
    'created_date_range', 'updated_date_range', 'search',
  ];
  for (const [key, value] of Object.entries(filters)) {
    if (allowed.includes(key) && value) {
      params.append(key, String(value));
    }
  }
  return params.toString() ? `?${params.toString()}` : '';
}

export function buildRelationshipListUrl(filters = {}) {
  const params = new URLSearchParams();
  const allowed = ['source_ci', 'target_ci', 'relationship_type', 'status'];
  for (const [key, value] of Object.entries(filters)) {
    if (allowed.includes(key) && value !== undefined) {
      params.append(key, String(value));
    }
  }
  return params.toString() ? `?${params.toString()}` : '';
}

export function buildDriftListUrl(filters = {}) {
  const params = new URLSearchParams();
  const allowed = ['status', 'severity', 'type', 'ci', 'baseline', 'detected_date', 'search'];
  for (const [key, value] of Object.entries(filters)) {
    if (allowed.includes(key) && value !== undefined) {
      params.append(key, String(value));
    }
  }
  return params.toString() ? `?${params.toString()}` : '';
}

// ── parseFieldErrors ───────────────────────────────────────────────────
export function parseFieldErrors(errorResponse) {
  const parsed = typeof errorResponse === 'object' && errorResponse !== null
    ? errorResponse
    : { fields: {}, global: String(errorResponse) };
  return parsed.fields || {};
}

// ── actionAvailability ─────────────────────────────────────────────────
export function actionAvailability(userRole, action) {
  // Policy-driven availability based on role
  const isAdmin = userRole === 'system_admin';
  const isManager = userRole === 'it_manager';
  const isSupport = userRole === 'it_support';
  const isEmployee = userRole === 'employee';

  const rules = {
    view: !isEmployee,
    create: isAdmin || isManager,
    edit: isAdmin || isManager,
    verify: isAdmin || isManager || isSupport,
    retire: isAdmin || isManager,
    manage_types: isAdmin,
    manage_relationships: isAdmin || isManager,
    verify_ci: isAdmin || isManager || isSupport,
    retire_ci: isAdmin || isManager,
    manage_baselines: isAdmin || isManager,
    approve_baselines: isAdmin || isManager,
    manage_drift: isAdmin || isManager,
    view_impact: isAdmin || isManager || isSupport,
    view_reports: isAdmin || isManager || isSupport,
  };

  return rules[action] ?? false;
}

// ── normalizeGraphResponse ─────────────────────────────────────────────
export function normalizeGraphResponse(raw) {
  if (!raw) return { nodes: [], edges: [], metadata: {} };
  const nodes = safeResults(raw.nodes || raw.configuration_items || []);
  const edges = safeResults(raw.relationships || raw.edges || []);
  return {
    nodes,
    edges,
    metadata: {
      nodeCount: nodes.length,
      edgeCount: edges.length,
      hasCycles: !!raw.metadata?.hasCycles,
      truncated: !!raw.metadata?.truncated,
    },
  };
}

// ── API Contract Re-exports ───────────────────────────────────────────
export { CMDB_API_CONTRACT } from './cmdb';

export { CMDB_ROLES, CMDB_PERMISSIONS } from './cmdb';
// ── formatVerificationAge ──────────────────────────────────────────────
export function formatVerificationAge(lastVerifiedAt) {
  if (!lastVerifiedAt) return 'Never verified';
  const diffMs = Date.now() - new Date(lastVerifiedAt).getTime();
  const diffDays = diffMs / (1000 * 60 * 60 * 24);
  if (diffDays < 1) return 'Today';
  if (diffDays < 7) return `${Math.floor(diffDays)} day${Math.floor(diffDays) !== 1 ? 's' : ''} ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} week${Math.floor(diffDays / 7) !== 1 ? 's' : ''} ago`;
  return `${Math.floor(diffDays / 30)} month${Math.floor(diffDays / 30) !== 1 ? 's' : ''} ago`;
}