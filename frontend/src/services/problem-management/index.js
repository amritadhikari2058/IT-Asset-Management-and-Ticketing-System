import api from '../../api';

// Every helper returns the decoded response body so components never have to
// know whether an endpoint answers with a page, a list, or a bare object.

export const problemList = async (params = {}) => {
  const response = await api.get('/problems/', { params });
  return response.data;
};
export const problemDetail = async (id) => {
  const response = await api.get(`/problems/${id}/`);
  return response.data;
};
export const createProblem = async (data) => {
  const response = await api.post('/problems/', data);
  return response.data;
};
export const updateProblem = async (id, data, expectedVersion) => {
  const response = await api.patch(`/problems/${id}/`, {
    ...data,
    expected_record_version: expectedVersion,
  });
  return response.data;
};
export const deleteProblem = async (id) => {
  const response = await api.delete(`/problems/${id}/`);
  return response.data;
};
export const submitProblem = async (id, data = {}) => {
  const response = await api.post(`/problems/${id}/submit/`, data);
  return response.data;
};
export const acceptProblem = async (id, data = {}) => {
  const response = await api.post(`/problems/${id}/accept/`, data);
  return response.data;
};
export const rejectProblem = async (id, data = {}) => {
  const response = await api.post(`/problems/${id}/reject/`, data);
  return response.data;
};
export const startInvestigation = async (id, data = {}) => {
  const response = await api.post(`/problems/${id}/start-investigation/`, data);
  return response.data;
};
export const cancelProblem = async (id, data = {}) => {
  const response = await api.post(`/problems/${id}/cancel/`, data);
  return response.data;
};
export const reopenProblem = async (id, data = {}) => {
  const response = await api.post(`/problems/${id}/reopen/`, data);
  return response.data;
};

// Root-cause analysis: writes carry the version the operator loaded, so a
// stale editor is rejected instead of silently overwriting a newer record.
export const createRCA = async (data) => {
  const response = await api.post('/root-cause-analyses/', data);
  return response.data;
};
export const getRCA = async (id) => {
  const response = await api.get(`/root-cause-analyses/${id}/`);
  return response.data;
};
export const problemRCA = async (problemId) => {
  const response = await api.get(`/problems/${problemId}/root-cause-analysis/`);
  return response.data;
};
export const listRCAs = async (problemId, page = 1) => {
  const params = { problem: problemId };
  if (Number.isInteger(page) && page > 1) params.page = page;
  const response = await api.get('/root-cause-analyses/', { params });
  return response.data;
};
export const editRCA = async (id, data, expectedVersion) => {
  const response = await api.patch(`/root-cause-analyses/${id}/`, {
    ...data,
    expected_record_version: expectedVersion,
  });
  return response.data;
};
export const submitRCA = async (id, data = {}) => {
  const response = await api.post(`/root-cause-analyses/${id}/submit/`, data);
  return response.data;
};
export const approveRCA = async (id, data = {}) => {
  const response = await api.post(`/root-cause-analyses/${id}/approve/`, data);
  return response.data;
};
export const rejectRCA = async (id, data = {}) => {
  const response = await api.post(`/root-cause-analyses/${id}/reject/`, data);
  return response.data;
};
export const supersedeRCA = async (id, data = {}) => {
  const response = await api.post(`/root-cause-analyses/${id}/supersede/`, data);
  return response.data;
};

// Five Whys and root-cause factors.
export const fiveWhys = async (problemId) => {
  const response = await api.get(`/problems/${problemId}/five-whys/`);
  return response.data;
};
export const createFiveWhy = async (data) => {
  const response = await api.post('/root-cause-whys/', data);
  return response.data;
};
// Whys and factors have no version column: no optimistic token is sent.
export const editFiveWhy = async (id, data) => {
  const response = await api.patch(`/root-cause-whys/${id}/`, data);
  return response.data;
};
export const deleteFiveWhy = async (id) => {
  const response = await api.delete(`/root-cause-whys/${id}/`);
  return response.data;
};
export const rootCauseFactors = async (problemId) => {
  const response = await api.get(`/problems/${problemId}/root-cause-factors/`);
  return response.data;
};
export const createFactor = async (data) => {
  const response = await api.post('/root-cause-factors/', data);
  return response.data;
};
export const editFactor = async (id, data) => {
  const response = await api.patch(`/root-cause-factors/${id}/`, data);
  return response.data;
};
export const deleteFactor = async (id) => {
  const response = await api.delete(`/root-cause-factors/${id}/`);
  return response.data;
};

// Evidence: list, upload and archive only; archiving is terminal.
export const listEvidence = async (problemId) => {
  const response = await api.get(`/problems/${problemId}/evidence/`);
  return response.data;
};
export const uploadEvidence = async (problemId, file, onProgress) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post(`/problems/${problemId}/evidence/`, formData, {
    onProgress,
  });
  return response.data;
};
export const archiveEvidence = async (evidenceId, data = {}) => {
  const response = await api.post(`/evidence/${evidenceId}/archive/`, data);
  return response.data;
};
export const deleteEvidence = async (id) => {
  const response = await api.delete(`/evidence/${id}/`);
  return response.data;
};

// Tasks / actions.
export const listTasks = async (problemId, params = {}) => {
  const response = await api.get(`/problems/${problemId}/tasks/`, { params });
  return response.data;
};
export const createProblemTask = async (problemId, data) => {
  const response = await api.post('/tasks/', { problem: Number(problemId), ...data });
  return response.data;
};
export const updateTask = async (id, data, expectedVersion) => {
  const response = await api.patch(`/tasks/${id}/`, {
    ...data,
    expected_record_version: expectedVersion,
  });
  return response.data;
};
export const deleteTask = async (id) => {
  const response = await api.delete(`/tasks/${id}/`);
  return response.data;
};

// Validations, exceptions and workarounds hang off the problem.
export const listValidations = async (problemId) => {
  const response = await api.get(`/problems/${problemId}/validations/`);
  return response.data;
};
export const createValidation = async (problemId, data) => {
  const response = await api.post(`/problems/${problemId}/validations/`, data);
  return response.data;
};
export const listExceptions = async (problemId) => {
  const response = await api.get(`/problems/${problemId}/exceptions/`);
  return response.data;
};
export const createException = async (problemId, data) => {
  const response = await api.post(`/problems/${problemId}/exceptions/`, data);
  return response.data;
};
export const listWorkarounds = async (problemId) => {
  const response = await api.get(`/problems/${problemId}/workarounds/`);
  return response.data;
};
export const createWorkaround = async (problemId, data) => {
  const response = await api.post(`/problems/${problemId}/workarounds/`, data);
  return response.data;
};

// Timeline events (problem-scoped collection).
export const problemTimeline = async (problemId, params = {}) => {
  const response = await api.get(`/problems/${problemId}/timeline/`, { params });
  return response.data;
};
export const createTimelineEvent = async (problemId, data) => {
  const response = await api.post(`/problems/${problemId}/timeline/`, data);
  return response.data;
};

// Actions: lifecycles only move through dedicated transition endpoints.
export const listActions = async (problemId, params = {}) => {
  const response = await api.get(`/problems/${problemId}/actions/`, { params });
  return response.data;
};
export const createAction = async (problemId, data) => {
  const response = await api.post(`/problems/${problemId}/actions/`, data);
  return response.data;
};
export const editAction = async (id, data, expectedVersion) => {
  const response = await api.patch(`/actions/${id}/`, {
    ...data,
    expected_record_version: expectedVersion,
  });
  return response.data;
};

// One factory keeps every transition URL identical to the backend regex
// (/<resource>/<id>/<transition>/) with no generic status PATCH.
const transition = (resource, action) => async (id, data = {}) => {
  const response = await api.post(`/${resource}/${id}/${action}/`, data);
  return response.data;
};

export const approveAction = transition('actions', 'approve');
export const startAction = transition('actions', 'start');
export const completeAction = transition('actions', 'complete');
export const validateAction = transition('actions', 'validate');
export const markActionIneffective = transition('actions', 'ineffective');
export const cancelAction = transition('actions', 'cancel');

export const submitWorkaround = transition('workarounds', 'submit');
export const approveWorkaround = transition('workarounds', 'approve');
export const publishWorkaround = transition('workarounds', 'publish');
export const expireWorkaround = transition('workarounds', 'expire');
export const retireWorkaround = transition('workarounds', 'retire');

export const startValidation = transition('validations', 'start');
export const passValidation = transition('validations', 'pass');
export const failValidation = transition('validations', 'fail');
export const markValidationInconclusive = transition('validations', 'inconclusive');
export const cancelValidation = transition('validations', 'cancel');

export const submitException = transition('exceptions', 'submit');
export const approveException = transition('exceptions', 'approve');
export const rejectException = transition('exceptions', 'reject');
export const revokeException = transition('exceptions', 'revoke');
export const expireException = transition('exceptions', 'expire');

export const problemHistory = async (problemId, params = {}) => {
  const response = await api.get(`/problems/${problemId}/history/`, { params });
  return response.data;
};
export const linkedTickets = async (problemId, params = {}) => {
  const response = await api.get(`/problems/${problemId}/linked-tickets/`, { params });
  return response.data;
};
export const linkedCIs = async (problemId, params = {}) => {
  const response = await api.get(`/problems/${problemId}/linked-cis/`, { params });
  return response.data;
};
export const linkedAssets = async (problemId, params = {}) => {
  const response = await api.get(`/problems/${problemId}/linked-assets/`, { params });
  return response.data;
};
export const linkedServices = async (problemId, params = {}) => {
  const response = await api.get(`/problems/${problemId}/linked-services/`, { params });
  return response.data;
};
export const linkedProducts = async (problemId, params = {}) => {
  const response = await api.get(`/problems/${problemId}/linked-products/`, { params });
  return response.data;
};
export const linkedKBs = async (problemId, params = {}) => {
  const response = await api.get(`/problems/${problemId}/linked-kbs/`, { params });
  return response.data;
};
export const createKbLink = async (data) => {
  const response = await api.post('/kb-links/', data);
  return response.data;
};
export const deleteKbLink = async (linkId) => {
  const response = await api.delete(`/kb-links/${linkId}/`);
  return response.data;
};
export const problemReadiness = async (problemId) => {
  const response = await api.get(`/problems/${problemId}/readiness/`);
  return response.data;
};
