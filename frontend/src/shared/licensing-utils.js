export const PRODUCT_CATEGORY_LABELS = { office: 'Office', design: 'Design', development: 'Development', security: 'Security', infrastructure: 'Infrastructure', analytics: 'Analytics', communication: 'Communication', other: 'Other' };
export const PLATFORM_LABELS = { windows: 'Windows', macos: 'macOS', linux: 'Linux', web: 'Web', ios: 'iOS', android: 'Android', cross_platform: 'Cross-platform' };
export const LICENSE_MODEL_LABELS = { perpetual: 'Perpetual', subscription: 'Subscription', concurrent: 'Concurrent', named_user: 'Named User', device: 'Device', site: 'Site', enterprise: 'Enterprise', volume: 'Volume', oem: 'OEM', freeware: 'Freeware', open_source: 'Open Source', trial: 'Trial', other: 'Other' };
export const PRODUCT_APPROVAL_STATUS_LABELS = { pending: 'Pending', approved: 'Approved', restricted: 'Restricted', prohibited: 'Prohibited', retired: 'Retired' };
export const RISK_LEVEL_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' };
export const SUPPORT_STATUS_LABELS = { supported: 'Supported', extended: 'Extended', end_of_life: 'End of Life', unsupported: 'Unsupported' };
export const AGREEMENT_TYPE_LABELS = { purchase: 'Purchase', subscription: 'Subscription', enterprise: 'Enterprise', volume: 'Volume', site: 'Site', oem: 'OEM', trial: 'Trial', freeware: 'Freeware', open_source: 'Open Source' };
export const AGREEMENT_STATUS_LABELS = { draft: 'Draft', active: 'Active', expiring: 'Expiring', suspended: 'Suspended', expired: 'Expired', terminated: 'Terminated', retired: 'Retired' };
export const BILLING_FREQUENCY_LABELS = { one_time: 'One-time', monthly: 'Monthly', quarterly: 'Quarterly', semi_annual: 'Semi-annual', annual: 'Annual', multi_year: 'Multi-year' };
export const ALLOCATION_TYPE_LABELS = { user: 'User', device: 'Device', department: 'Department', site: 'Site', concurrent_reservation: 'Concurrent' };
export const ALLOCATION_STATUS_LABELS = { reserved: 'Reserved', assigned: 'Assigned', active: 'Active', suspended: 'Suspended', revoked: 'Revoked', expired: 'Expired' };
export const INSTALLATION_STATUS_LABELS = { installed: 'Installed', removed: 'Removed', detected: 'Detected', unauthorized: 'Unauthorized' };
export const COMPLIANCE_STATUS_LABELS = { compliant: 'Compliant', non_compliant: 'Non-compliant', unknown: 'Unknown' };
export const RENEWAL_STATUS_LABELS = { draft: 'Draft', submitted: 'Submitted', approved: 'Approved', rejected: 'Rejected', applied: 'Applied', cancelled: 'Cancelled' };
export const FINDING_TYPE_LABELS = { over_allocated: 'Over-allocated', unlicensed_installation: 'Unlicensed Installation', expired_agreement: 'Expired Agreement', expiring_agreement: 'Expiring Agreement', unused_license: 'Unused Verification Gap', unused_verification_gap: 'Unused Verification Gap', duplicate_user_allocation: 'Duplicate User Allocation', duplicate_device_allocation: 'Duplicate Device Allocation', prohibited_software: 'Prohibited Software', unsupported_version: 'Unsupported Version', missing_documentation: 'Missing Documentation', missing_entitlement_quantity: 'Missing Entitlement Quantity', renewal_overdue: 'Renewal Overdue', allocation_to_inactive_user: 'Allocation to Inactive User', allocation_inactive_user: 'Allocation to Inactive User', allocation_to_retired_asset: 'Allocation to Retired Asset', allocation_retired_asset: 'Allocation to Retired Asset', terminated_agreement_allocation: 'Allocation on Terminated Agreement', expired_agreement_allocation: 'Allocation on Expired Agreement', inconsistent_allocation_state: 'Inconsistent Allocation State' };
export const FINDING_SEVERITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' };
export const FINDING_STATUS_LABELS = { open: 'Open', acknowledged: 'Acknowledged', resolved: 'Resolved', false_positive: 'False Positive' };
export const SECRET_TYPE_LABELS = { license_key: 'License Key', activation_code: 'Activation Code', serial_number: 'Serial Number', api_token: 'API Token', certificate: 'Certificate', credential: 'Credential', other: 'Other' };
export const SECRET_STATUS_LABELS = { active: 'Active', rotated: 'Rotated', revoked: 'Revoked' };
// Mirrors licensing.models.HISTORY_EVENT_CHOICES (backend is the source of truth).
export const HISTORY_EVENT_LABELS = {
  agreement_created: 'Agreement Created',
  agreement_activated: 'Agreement Activated',
  agreement_updated: 'Agreement Updated',
  agreement_renewed: 'Agreement Renewed',
  agreement_expiring: 'Agreement Expiring',
  agreement_expired: 'Agreement Expired',
  agreement_suspended: 'Agreement Suspended',
  agreement_terminated: 'Agreement Terminated',
  agreement_retired: 'Agreement Retired',
  secret_added: 'Secret Added',
  secret_revealed: 'Secret Revealed',
  secret_rotated: 'Secret Rotated',
  secret_revoked: 'Secret Revoked',
  allocation_reserved: 'Allocation Reserved',
  allocation_assigned: 'Allocation Assigned',
  allocation_activated: 'Allocation Activated',
  allocation_suspended: 'Allocation Suspended',
  allocation_revoked: 'Allocation Revoked',
  allocation_verified: 'Allocation Verified',
  installation_recorded: 'Installation Recorded',
  installation_removed: 'Installation Removed',
  compliance_changed: 'Compliance Changed',
  renewal_review_started: 'Renewal Review Started',
  renewal_approved: 'Renewal Approved',
  renewal_rejected: 'Renewal Rejected',
  renewal_applied: 'Renewal Applied',
  renewal_cancelled: 'Renewal Cancelled',
};

const DETAIL_FIELD_LABELS = {
  reason: 'Reason', action: 'Action', notes: 'Notes', note: 'Note',
  reference: 'Reference', type: 'Type', target: 'Target',
  finding_id: 'Finding', product: 'Product', asset: 'Asset',
  status: 'Status', quantity: 'Quantity', new_expiry: 'New expiry',
  total_cost: 'Total cost', revoked_allocations: 'Revoked allocations',
};

function humanizeValue(value) {
  return String(value ?? '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Human label for a status value that may come from any licensing model. */
export function historyStatusText(value) {
  if (!value) return '—';
  return ALLOCATION_STATUS_LABELS[value]
    || AGREEMENT_STATUS_LABELS[value]
    || FINDING_STATUS_LABELS[value]
    || RENEWAL_STATUS_LABELS[value]
    || humanizeValue(value);
}

/** "Active → Revoked" style transition for a history row. */
export function historyTransition(entry) {
  const prev = entry?.previous_status;
  const next = entry?.new_status;
  if (prev && next) return `${historyStatusText(prev)} → ${historyStatusText(next)}`;
  if (next) return historyStatusText(next);
  if (prev) return historyStatusText(prev);
  return '—';
}

/** Readable summary of a history detail payload (never raw JSON in the UI). */
export function historyDetailText(detail) {
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return '';
  return Object.entries(detail)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${DETAIL_FIELD_LABELS[k] || humanizeValue(k)}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join(' · ');
}

export function formatDate(v) { if (!v) return '—'; try { return new Date(v).toLocaleDateString(); } catch { return String(v); } }
export function formatDateTime(v) { if (!v) return '—'; try { return new Date(v).toLocaleString(); } catch { return String(v); } }
export function formatMoney(v, currency) { if (v === null || v === undefined || v === '') return '—'; return `${currency ? currency + ' ' : ''}${v}`; }
export function formatQuantity(v) { if (v === null || v === undefined) return '—'; if (v === true) return 'Unlimited'; return String(v); }
export function formatPercent(v) { if (v === null || v === undefined) return '—'; return `${Number(v).toFixed(1)}%`; }
export function formatUtilization(row) {
  if (!row) return '—';
  if (row.utilization_calculable === false || row.utilization_percent === null || row.utilization_percent === undefined) {
    return row.utilization_note ? 'Not calculable' : '—';
  }
  return formatPercent(row.utilization_percent);
}
export function agreementStatusBadgeVariant(s) { return s === 'active' ? 'success' : s === 'expired' ? 'danger' : 'secondary'; }
export function findingSeverityBadgeVariant(s) { return s === 'critical' ? 'danger' : s === 'high' ? 'warning' : 'secondary'; }
export function findingStatusBadgeVariant(s) { return s === 'resolved' ? 'success' : s === 'false_positive' ? 'secondary' : 'warning'; }
export function allocationStatusBadgeVariant(s) { return s === 'active' ? 'success' : s === 'revoked' ? 'danger' : 'secondary'; }
export function productApprovalBadgeVariant(s) { return s === 'approved' ? 'success' : s === 'prohibited' ? 'danger' : 'secondary'; }
export function safeResults(d) { if (Array.isArray(d)) return d; return d?.results || []; }
export function buildProductListUrl(f = {}, ordering, page) {
  const p = new URLSearchParams();
  if (f.search || f.q) p.append('search', f.search || f.q);
  if (f.category) p.append('category', f.category);
  if (f.platform) p.append('platform', f.platform);
  if (f.license_model) p.append('license_model', f.license_model);
  if (f.approved_status) p.append('status', f.approved_status);
  if (f.risk_level) p.append('risk_level', f.risk_level);
  if (f.support_status) p.append('support_status', f.support_status);
  if (f.is_active !== undefined && f.is_active !== '') p.append('is_active', f.is_active);
  if (ordering) p.append('ordering', ordering);
  if (page && page > 1) p.append('page', page);
  return `/licensing/products/?${p.toString()}`;
}
export function buildAgreementListUrl(f = {}, ordering, page) {
  const p = new URLSearchParams();
  if (f.search || f.q) p.append('search', f.search || f.q);
  if (f.status) p.append('status', f.status);
  if (f.agreement_type) p.append('agreement_type', f.agreement_type);
  if (f.license_model) p.append('license_model', f.license_model);
  if (f.vendor) p.append('vendor', f.vendor);
  if (f.department) p.append('department', f.department);
  if (ordering) p.append('ordering', ordering);
  if (page && page > 1) p.append('page', page);
  return `/licensing/agreements/?${p.toString()}`;
}
export function buildAllocationListUrl(f = {}, ordering, page, pageSize) {
  const p = new URLSearchParams();
  if (f.search || f.q) p.append('search', f.search || f.q);
  if (f.status) p.append('status', f.status);
  if (f.allocation_type) p.append('allocation_type', f.allocation_type);
  if (f.agreement) p.append('agreement', f.agreement);
  if (f.product) p.append('product', f.product);
  if (ordering) p.append('ordering', ordering);
  if (page && page > 1) p.append('page', page);
  p.append('page_size', pageSize);
  return `/licensing/allocations/?${p.toString()}`;
}
export function buildFindingListUrl(f = {}, ordering, page) {
  const p = new URLSearchParams();
  if (f.search || f.q) p.append('search', f.search || f.q);
  if (f.finding_type) p.append('finding_type', f.finding_type);
  if (f.severity) p.append('severity', f.severity);
  if (f.status) p.append('status', f.status);
  if (ordering) p.append('ordering', ordering);
  if (page && page > 1) p.append('page', page);
  return `/licensing/findings/?${p.toString()}`;
}
export function parseFieldErrors(err) {
  const data = err?.response?.data;
  if (!data) return {};
  const out = {};
  Object.entries(data).forEach(([k, v]) => { out[k] = Array.isArray(v) ? v.join(' ') : String(v); });
  return out;
}
export function actionAvailability() { return true; }
export function groupMoneyByCurrency(items) {
  const groups = {};
  (items || []).forEach((it) => {
    const c = it.currency || 'N/A';
    groups[c] = (groups[c] || 0) + Number(it.total_cost || 0);
  });
  return groups;
}
export function licensingCapabilities(auth) {
  return {
    canView: !!auth.canViewLicensing,
    // Backend LicenseCompliancePermission / LicenseAllocationPermission are
    // staff-only, so page-level gates use the staff flag, not canViewLicensing
    // (which is also true for employees viewing My Software).
    canViewCompliance: !!auth.isStaff,
    canViewAllocations: !!auth.isStaff,
    canManageProducts: !!auth.canManageSoftwareProducts,
    canManageAgreements: !!auth.canManageLicenseAgreements,
    canViewCosts: !!auth.canViewLicenseCosts,
    canManageAllocations: !!auth.canManageLicenseAllocations,
    canManageInstallations: !!auth.canManageLicenseInstallations,
    canManageRenewals: !!auth.canManageLicenseRenewals,
    canApproveRenewals: !!auth.canApproveLicenseRenewals,
    canViewSecrets: !!auth.canViewLicenseSecrets,
    canRevealSecrets: !!auth.canRevealLicenseSecrets,
    canManageDocuments: !!auth.canManageLicenseDocuments,
    canManageCompliance: !!auth.canManageLicenseCompliance,
    canViewReports: !!auth.canViewLicenseReports,
    canViewMySoftware: !!auth.canViewMySoftware,
  };
}
