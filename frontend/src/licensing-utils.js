export const PRODUCT_CATEGORY_LABELS = { office: 'Office', design: 'Design', development: 'Development', security: 'Security', infrastructure: 'Infrastructure', analytics: 'Analytics', communication: 'Communication', other: 'Other' };
export const PLATFORM_LABELS = { windows: 'Windows', macos: 'macOS', linux: 'Linux', web: 'Web', ios: 'iOS', android: 'Android', cross_platform: 'Cross-platform' };
export const LICENSE_MODEL_LABELS = { perpetual: 'Perpetual', subscription: 'Subscription', concurrent: 'Concurrent', named_user: 'Named User', device: 'Device', site: 'Site', enterprise: 'Enterprise', freeware: 'Freeware', open_source: 'Open Source' };
export const PRODUCT_APPROVAL_STATUS_LABELS = { pending: 'Pending', approved: 'Approved', restricted: 'Restricted', prohibited: 'Prohibited', retired: 'Retired' };
export const RISK_LEVEL_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' };
export const SUPPORT_STATUS_LABELS = { supported: 'Supported', extended: 'Extended', end_of_life: 'End of Life', unsupported: 'Unsupported' };
export const AGREEMENT_TYPE_LABELS = { purchase: 'Purchase', subscription: 'Subscription', enterprise: 'Enterprise', volume: 'Volume', site: 'Site', oem: 'OEM', trial: 'Trial', freeware: 'Freeware', open_source: 'Open Source' };
export const AGREEMENT_STATUS_LABELS = { draft: 'Draft', active: 'Active', suspended: 'Suspended', expired: 'Expired', terminated: 'Terminated', retired: 'Retired' };
export const BILLING_FREQUENCY_LABELS = { one_time: 'One-time', monthly: 'Monthly', quarterly: 'Quarterly', semi_annual: 'Semi-annual', annual: 'Annual', multi_year: 'Multi-year' };
export const ALLOCATION_TYPE_LABELS = { user: 'User', device: 'Device', department: 'Department', concurrent_reservation: 'Concurrent' };
export const ALLOCATION_STATUS_LABELS = { pending: 'Pending', active: 'Active', suspended: 'Suspended', revoked: 'Revoked', expired: 'Expired' };
export const INSTALLATION_STATUS_LABELS = { installed: 'Installed', removed: 'Removed', detected: 'Detected', unauthorized: 'Unauthorized' };
export const COMPLIANCE_STATUS_LABELS = { compliant: 'Compliant', non_compliant: 'Non-compliant', unknown: 'Unknown' };
export const RENEWAL_STATUS_LABELS = { draft: 'Draft', submitted: 'Submitted', approved: 'Approved', rejected: 'Rejected', applied: 'Applied', cancelled: 'Cancelled' };
export const FINDING_TYPE_LABELS = { over_allocated: 'Over-allocated', unlicensed_installation: 'Unlicensed Installation', expired_agreement: 'Expired Agreement', expiring_agreement: 'Expiring Agreement', unused_verification_gap: 'Unused Verification Gap', duplicate_user_allocation: 'Duplicate User Allocation', duplicate_device_allocation: 'Duplicate Device Allocation', prohibited_software: 'Prohibited Software', unsupported_version: 'Unsupported Version', missing_documentation: 'Missing Documentation', renewal_overdue: 'Renewal Overdue', allocation_inactive_user: 'Allocation to Inactive User', allocation_retired_asset: 'Allocation to Retired Asset' };
export const FINDING_SEVERITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' };
export const FINDING_STATUS_LABELS = { open: 'Open', acknowledged: 'Acknowledged', resolved: 'Resolved', false_positive: 'False Positive' };
export const SECRET_TYPE_LABELS = { license_key: 'License Key', activation_code: 'Activation Code', serial_number: 'Serial Number', api_token: 'API Token', certificate: 'Certificate', credential: 'Credential', other: 'Other' };
export const SECRET_STATUS_LABELS = { active: 'Active', rotated: 'Rotated', revoked: 'Revoked' };

export function formatDate(v) { if (!v) return '—'; try { return new Date(v).toLocaleDateString(); } catch { return String(v); } }
export function formatDateTime(v) { if (!v) return '—'; try { return new Date(v).toLocaleString(); } catch { return String(v); } }
export function formatMoney(v, currency) { if (v === null || v === undefined || v === '') return '—'; return `${currency ? currency + ' ' : ''}${v}`; }
export function formatQuantity(v) { if (v === null || v === undefined) return '—'; if (v === true) return 'Unlimited'; return String(v); }
export function formatPercent(v) { if (v === null || v === undefined) return '—'; return `${Number(v).toFixed(1)}%`; }
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
export function buildAllocationListUrl(f = {}, ordering, page) {
  const p = new URLSearchParams();
  if (f.search || f.q) p.append('search', f.search || f.q);
  if (f.status) p.append('status', f.status);
  if (f.allocation_type) p.append('allocation_type', f.allocation_type);
  if (f.agreement) p.append('agreement', f.agreement);
  if (f.product) p.append('product', f.product);
  if (ordering) p.append('ordering', ordering);
  if (page && page > 1) p.append('page', page);
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
