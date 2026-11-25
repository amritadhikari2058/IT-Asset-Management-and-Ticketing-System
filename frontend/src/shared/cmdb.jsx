/** CMDB Frontend API Contract Table
 * 
 * Maps frontend operations to actual backend endpoints,
 * derived from the verified CMDB Django REST backend.
 * 
 * All requests go through the shared axios instance (./api) so CMDB calls
 * carry the bearer auth header, participate in token refresh, and respect
 * VITE_API_BASE_URL. Axios baseURL is http://127.0.0.1:8000/api by default.
 * All CMDB routes use /cmdb/ prefix → final URL: /api/cmdb/<route>
 */

// ── API Namespace ─────────────────────────────────────────────────────
export const CMDB_API = {
  BASE: '/cmdb',
  DASHBOARD: '/cmdb/dashboard',
  REPORTS: '/cmdb/reports',
  // Router-registered prefixes
  TYPES: '/cmdb/types',
  ITEMS: '/cmdb/items',
  RELATIONSHIPS: '/cmdb/relationships',
  HISTORY: '/cmdb/history',
  BASELINES: '/cmdb/baselines',
  DRIFT: '/cmdb/drift',
  VERIFICATION: '/cmdb/verification',
  // Custom action prefixes (on item detail)
  ITEM_VERIFY: (id) => `/cmdb/items/${id}/verify`,
  ITEM_RETIRE: (id) => `/cmdb/items/${id}/retire`,
  ITEM_DEPENDENCIES: (id) => `/cmdb/items/${id}/dependencies`,
  ITEM_DEPENDENTS: (id) => `/cmdb/items/${id}/dependents`,
  ITEM_HISTORY: (id) => `/cmdb/items/${id}/history`,
  ITEM_TICKETS: (id) => `/cmdb/items/${id}/tickets`,
  ITEM_CHANGES: (id) => `/cmdb/items/${id}/changes`,
  ITEM_IMPACT: (id) => `/cmdb/items/${id}/impact`,
  // Service mapping
  SERVICES: '/cmdb/service-profiles',
  SERVICE_MAP: (id) => `/cmdb/items/${id}/dependencies`,
  SERVICE_PROFILE_MAP: (id) => `/cmdb/service-profiles/${id}`,
};

// ── Role-Permission Contract ──────────────────────────────────────────
export const CMDB_ROLES = {
  SYSTEM_ADMIN: 'system_admin',
  IT_MANAGER: 'it_manager',
  IT_SUPPORT: 'it_support',
  EMPLOYEE: 'employee',
  UNKNOWN: 'unknown',
};

export const CMDB_PERMISSIONS = {
  // Dashboard
  canViewDashboard: (role) => role !== CMDB_ROLES.EMPLOYEE,

  // CI List
  canViewCIList: (role) => role !== CMDB_ROLES.EMPLOYEE,
  canCreateCI: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER,
  canEditCI: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER,
  canVerifyCI: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER || role === CMDB_ROLES.IT_SUPPORT,
  canRetireCI: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER,
  canViewCIDetail: (role) => role !== CMDB_ROLES.EMPLOYEE,

  // CI Types
  canViewCITypes: (role) => role !== CMDB_ROLES.EMPLOYEE,
  canCreateCITypes: (role) => role === CMDB_ROLES.SYSTEM_ADMIN,
  canEditCITypes: (role) => role === CMDB_ROLES.SYSTEM_ADMIN,
  canDeleteCITypes: (role) => role === CMDB_ROLES.SYSTEM_ADMIN,

  // Relationships
  canViewRelationships: (role) => role !== CMDB_ROLES.EMPLOYEE,
  canCreateRelationship: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER,
  canEditRelationship: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER,
  canDeleteRelationship: (role) => role === CMDB_ROLES.SYSTEM_ADMIN,

  // Dependency Map
  canViewDependencyMap: (role) => role !== CMDB_ROLES.EMPLOYEE,

  // Service Mapping
  canViewServiceMapping: (role) => role !== CMDB_ROLES.EMPLOYEE,

  // Impact Analysis
  canViewImpactAnalysis: (role) => role !== CMDB_ROLES.EMPLOYEE,

  // Verification Queue
  canViewVerificationQueue: (role) => role !== CMDB_ROLES.EMPLOYEE,
  canVerifyCIAction: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER || role === CMDB_ROLES.IT_SUPPORT,

  // Retirement
  canRetireCIAction: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER,

  // Baselines
  canViewBaselines: (role) => role !== CMDB_ROLES.EMPLOYEE,
  canCreateBaselines: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER,
  canApproveBaselines: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER,

  // Drift
  canViewDrift: (role) => role !== CMDB_ROLES.EMPLOYEE,
  canAcknowledgeDrift: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER,
  canResolveDrift: (role) => role === CMDB_ROLES.SYSTEM_ADMIN || role === CMDB_ROLES.IT_MANAGER,

  // Reports
  canViewReports: (role) => role !== CMDB_ROLES.EMPLOYEE,
};

// ── Success Codes ─────────────────────────────────────────────────────
export const CMDB_SUCCESS = {
  OK: 200,
  CREATED: 201,
  NO_CONTENT: 204,
};

// ── Error Code Mappings (from backend) ─────────────────────────────────
export const CMDB_ERRORS = {
  UNAUTHORIZED: 401,
  FORBIDDEN: 403,
  NOT_FOUND: 404,
  CONFLICT: 409,
  BAD_REQUEST: 400,
};

// ── Response Shapes ────────────────────────────────────────────────

// Dashboard response shapes (derived from backend models)
export const DashboardResponse = {
  total_cis: 0,
  active_cis: 0,
  critical_cis: 0,
  unverified_cis: 0,
  open_drift_findings: 0,
};

// Item list row shape
export const CIListRow = {
  id: 0,
  ci_number: '',
  name: '',
  ci_type: '',
  status: '',
  lifecycle_state: '',
  criticality: '',
  environment: '',
  department: null,
  location: null,
  owner: null,
  technical_owner: null,
  asset: null,
  software_product: null,
  service: null,
  last_verified_at: '',
  updated_at: ''
};

// Item form field types (from serializer)
export const CICreateFields = {
  name: '',
  ci_type: null,
  description: '',
  status: '',
  lifecycle_state: '',
  criticality: '',
  environment: '',
  asset: null,
  software_product: null,
  service_catalogue_item: null,
  department: null,
  location: '',
  owner: null,
  technical_owner: null,
  support_group: null,
  vendor: '',
  manufacturer: '',
  model: '',
  serial_number: '',
  version: '',
  hostname: '',
  ip_address: '',
  dns_name: '',
  external_reference: '',
  attributes: {},
  source: '',
  source_identifier: ''
};

// Item detail header shape
export const CIDetailHeader = {
  ci_number: '',
  name: '',
  ci_type: '',
  status: '',
  lifecycle_state: '',
  criticality: '',
  environment: '',
  last_verified_at: null,
  monitoring_state: '',
  record_version: 0
};

// ── API Contract Table ────────────────────────────────────────────────
/**
 * Every entry maps a frontend operation to:
 * - endpoint: the full path (relative to /api)
 * - method: GET | POST | PUT | DELETE | POST (custom action)
 * - requestPayload: shape of data sent to backend
 * - responseShape: expected shape of backend response
 * - roles: required user role(s)
 * - successCode: expected HTTP status on success
 * - errorCodes: possible error codes
 */

export const CMDB_API_CONTRACT = {
  // Dashboard
  dashboard: {
    endpoint: CMDB_API.DASHBOARD,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.UNAUTHORIZED],
  },

  // CI List
  ciList: {
    endpoint: CMDB_API.ITEMS,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN],
  },

  ciCreate: {
    endpoint: CMDB_API.ITEMS,
    method: 'POST',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER],
    successCode: CMDB_SUCCESS.CREATED,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST, CMDB_ERRORS.CONFLICT],
  },

  ciEdit: {
    endpoint: (id) => `${CMDB_API.ITEMS}/${id}`,
    method: 'PATCH',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST, CMDB_ERRORS.CONFLICT],
  },

  ciVerify: {
    endpoint: (id) => CMDB_API.ITEM_VERIFY(id),
    method: 'POST',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST, CMDB_ERRORS.CONFLICT],
  },

  ciRetire: {
    endpoint: (id) => CMDB_API.ITEM_RETIRE(id),
    method: 'POST',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST, CMDB_ERRORS.CONFLICT],
  },

  ciDetail: {
    endpoint: (id) => `${CMDB_API.ITEMS}/${id}`,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.NOT_FOUND, CMDB_ERRORS.CONFLICT],
  },

  // CI Types
  typesList: {
    endpoint: CMDB_API.TYPES,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN],
  },

  typeCreate: {
    endpoint: CMDB_API.TYPES,
    method: 'POST',
    roles: [CMDB_ROLES.SYSTEM_ADMIN],
    successCode: CMDB_SUCCESS.CREATED,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST],
  },

  typeEdit: {
    endpoint: (id) => `${CMDB_API.TYPES}/${id}`,
    method: 'PATCH',
    roles: [CMDB_ROLES.SYSTEM_ADMIN],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.NOT_FOUND],
  },

  // Relationships
  relationshipsList: {
    endpoint: CMDB_API.RELATIONSHIPS,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN],
  },

  relationshipCreate: {
    endpoint: CMDB_API.RELATIONSHIPS,
    method: 'POST',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER],
    successCode: CMDB_SUCCESS.CREATED,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST, CMDB_ERRORS.CONFLICT],
  },

  // Dependency Map
  dependencyMap: {
    endpoint: (id) => `${CMDB_API.ITEMS}/${id}/dependencies`,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.NOT_FOUND],
  },

  // Service Mapping
  serviceMapping: {
    endpoint: CMDB_API.SERVICES,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN],
  },

  // Impact Analysis
  impactAnalysis: {
    endpoint: (id) => `${CMDB_API.ITEM_IMPACT(id)}`,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.CONFLICT],
  },

  // Verification Queue
  verificationQueue: {
    endpoint: CMDB_API.VERIFICATION,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN],
  },

  ciVerifyAction: {
    endpoint: (id) => `${CMDB_API.ITEM_VERIFY(id)}`,
    method: 'POST',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST, CMDB_ERRORS.CONFLICT],
  },

  // Retirement
  ciRetireAction: {
    endpoint: (id) => CMDB_API.ITEM_RETIRE(id),
    method: 'POST',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST, CMDB_ERRORS.CONFLICT],
  },

  // Baselines
  baselinesList: {
    endpoint: CMDB_API.BASELINES,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN],
  },

  baselineCreate: {
    endpoint: CMDB_API.BASELINES,
    method: 'POST',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER],
    successCode: CMDB_SUCCESS.CREATED,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST],
  },

  baselineApprove: {
    endpoint: (id) => `${CMDB_API.BASELINES}/${id}/approve`,
    method: 'POST',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST],
  },

  // Drift
  driftList: {
    endpoint: CMDB_API.DRIFT,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN],
  },

  driftAcknowledge: {
    endpoint: (id) => `${CMDB_API.DRIFT}/${id}/acknowledge`,
    method: 'POST',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST],
  },

  driftResolve: {
    endpoint: (id) => `${CMDB_API.DRIFT}/${id}/resolve`,
    method: 'POST',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN, CMDB_ERRORS.BAD_REQUEST],
  },

  // Reports
  reports: {
    endpoint: CMDB_API.REPORTS,
    method: 'GET',
    roles: [CMDB_ROLES.SYSTEM_ADMIN, CMDB_ROLES.IT_MANAGER, CMDB_ROLES.IT_SUPPORT],
    successCode: CMDB_SUCCESS.OK,
    errorCodes: [CMDB_ERRORS.FORBIDDEN],
  },
};