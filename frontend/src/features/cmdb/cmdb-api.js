import api from '../../api';

/** CMDB API endpoints — maps to /api/cmdb/ backend routes */
export const CmdbEndpoints = {
  list: '/api/cmdb/',
  detail: (id) => `/api/cmdb/${id}/`,
  typeList: '/api/cmdb/types/',
  itemType: (id) => `/api/cmdb/${id}/`,
  relationships: (id) => `/api/cmdb/${id}/relationships/`,
  history: (id) => `/api/cmdb/${id}/history/`,
  baselines: (id) => `/api/cmdb/${id}/baselines/`,
  drift: (id) => `/api/cmdb/${id}/drift/`,
  services: (id) => `/api/cmdb/${id}/services/`,
  impacts: (id) => `/api/cmdb/${id}/impacts/`,
};

export async function listCmdbItems(params = {}) {
  const response = await api.get(CmdbEndpoints.list, { params });
  return response.data;
}

export async function getCmdbItem(id) {
  const response = await api.get(CmdbEndpoints.detail(id));
  return response.data;
}