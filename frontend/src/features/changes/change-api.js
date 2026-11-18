import api from '../../api';

/** Change API endpoints — maps to /api/changes/ backend routes */
export const ChangeEndpoints = {
  list: '/api/changes/',
  detail: (id) => `/api/changes/${id}/`,
  create: '/api/changes/',
  update: (id) => `/api/changes/${id}/`,
  delete: (id) => `/api/changes/${id}/`,
  submit: (id) => `/api/changes/${id}/submit/`,
  accept: (id) => `/api/changes/${id}/accept/`,
  reject: (id) => `/api/changes/${id}/reject/`,
  startInvestigation: (id) => `/api/changes/${id}/start-investigation/`,
  cancel: (id) => `/api/changes/${id}/cancel/`,
  reopen: (id) => `/api/changes/${id}/reopen/`,
  addComment: (id) => `/api/changes/${id}/comments/`,
  addAttachment: (id) => `/api/changes/${id}/attachments/`,
};

export async function listChanges(params = {}) {
  const response = await api.get(ChangeEndpoints.list, { params });
  return response.data;
}

export async function getChange(id) {
  const response = await api.get(ChangeEndpoints.detail(id));
  return response.data;
}

export async function createChange(data) {
  const response = await api.post(ChangeEndpoints.create, data);
  return response.data;
}

export async function updateChange(id, data) {
  const response = await api.patch(ChangeEndpoints.update(id), data);
  return response.data;
}

export async function deleteChange(id) {
  const response = await api.delete(ChangeEndpoints.delete(id));
  return response.data;
}