import api from '../../api';
import { parseApiError } from '../../api-utils';

/** Mapping constants for the monitoring services layer. Only endpoints
 *  that are registered on the backend are exposed here.
 */
const SUPPORTED_ALERT_ACTIONS = new Set([
  'acknowledge', 'suppress', 'unsuppress', 'resolve', 'close', 'reopen', 'assign',
]);

export const MonitoringEndpoints = {
  sources: '/monitoring/sources/',
  alertList: '/monitoring/alerts/',
  sourceRotate: (id) => `/monitoring/sources/${id}/rotate-secret/`,
  sourceDisable: (id) => `/monitoring/sources/${id}/disable/`,
  sourceEnable: (id) => `/monitoring/sources/${id}/enable/`,
  sourceTest: (id) => `/monitoring/sources/${id}/test/`,
  alertDetail: (id) => `/monitoring/alerts/${id}/`,
  alertActions: (id, action) => `/monitoring/alerts/${id}/${action}/`,
  dashboard: '/monitoring/dashboard/',
};

/**
 * List monitoring sources (GET /monitoring/sources/).
 * Backend: MonitoringSourceViewSet.list — MonitoringSourceListSerializer.
 * Permission: authenticated user; UI restricts this to System Admin.
 */
export async function listSources(params = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== '' && v != null) p.set(k, v);
  }
  const url = `${MonitoringEndpoints.sources}?${p.toString()}`;
  const r = await api.get(url);
  return r.data;
}

/** List monitoring alerts (GET /monitoring/alerts/).
 * Supports the backend's page and page_size pagination parameters.
 */
export async function listAlerts(params = {}) {
  const p = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== '' && value != null) p.set(key, value);
  }
  const query = p.toString();
  const url = `${MonitoringEndpoints.alertList}${query ? `?${query}` : ''}`;
  const response = await api.get(url);
  return response.data;
}

/** Retrieve a single monitoring source (GET /monitoring/sources/<id>/). */
export async function getSource(id) {
  const r = await api.get(`${MonitoringEndpoints.sources}${id}/`);
  return r.data;
}

/** Enable a monitoring source (POST /monitoring/sources/<id>/enable/). */
export async function enableSource(id) {
  const r = await api.post(MonitoringEndpoints.sourceEnable(id));
  return r.data;
}

/** Disable a monitoring source (POST /monitoring/sources/<id>/disable/). */
export async function disableSource(id) {
  const r = await api.post(MonitoringEndpoints.sourceDisable(id));
  return r.data;
}

/** Rotate a source secret (POST /monitoring/sources/<id>/rotate-secret/).
 *  Returns plaintext secret once in the response.
 */
export async function rotateSourceSecret(id) {
  const r = await api.post(MonitoringEndpoints.sourceRotate(id));
  return r.data;
}

/** Test source configuration (POST /monitoring/sources/<id>/test/). */
export async function testSource(id) {
  const r = await api.post(MonitoringEndpoints.sourceTest(id));
  return r.data;
}

/** Retrieve an alert detail (GET /monitoring/alerts/<id>/).
 *  Serializer exposes: alert_number, title, severity, status, source_name,
 *  event_count.
 */
export async function getAlert(id) {
  const r = await api.get(MonitoringEndpoints.alertDetail(id));
  return r.data;
}

/** Post an alert action (POST /monitoring/alerts/<id>/<action>/).
 *  Supported actions: acknowledge, suppress, unsuppress, resolve, close,
 *  reopen, assign.
 */
export async function alertAction(id, action, payload = {}) {
  if (!SUPPORTED_ALERT_ACTIONS.has(action)) {
    throw new Error(`Unsupported alert action: ${action}`);
  }
  const r = await api.post(MonitoringEndpoints.alertActions(id, action), payload);
  return r.data;
}

/** Load monitoring dashboard (GET /monitoring/dashboard/).
 *  Backend returns a stub: { detail: "Dashboard data requires implementation." }
 *  No active caller uses it; any caller must treat the result as unavailable,
 *  never as real metrics.
 */
export async function loadDashboard() {
  const r = await api.get(MonitoringEndpoints.dashboard);
  return r.data;
}

/** Parse a monitoring API error into {fields, global}. */
export function parseMonitoringError(e) {
  return parseApiError(e);
}

export default {
  listSources,
  getSource,
  enableSource,
  disableSource,
  rotateSourceSecret,
  testSource,
  listAlerts,
  getAlert,
  alertAction,
  loadDashboard,
  parseMonitoringError,
  MonitoringEndpoints,
};
