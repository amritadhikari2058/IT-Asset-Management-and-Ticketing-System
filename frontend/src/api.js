import axios from 'axios';

const api = axios.create({ baseURL: 'http://127.0.0.1:8000/api' });

api.interceptors.request.use((cfg) => {
  const t = localStorage.getItem('access');
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

// Shared in-flight refresh so concurrent 401s do one token request.
let refreshPromise = null;

function isAuthUrl(url = '') {
  return (
    url.includes('/token/')
    || url.includes('/password-reset/')
    || url.includes('/verify-email/')
  );
}

function clearAuth() {
  localStorage.removeItem('access');
  localStorage.removeItem('refresh');
  window.dispatchEvent(new Event('auth-expired'));
}

function refreshAccessToken() {
  if (!refreshPromise) {
    const refresh = localStorage.getItem('refresh');
    const base = (api.defaults && api.defaults.baseURL) || '';
    refreshPromise = axios
      .post(`${base}/token/refresh/`, { refresh })
      .then((r) => {
        // Logout race: only store when our refresh token is still current.
        if (localStorage.getItem('refresh') === refresh) {
          localStorage.setItem('access', r.data.access);
        }
        return r.data.access;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const { config, response } = error || {};
    const url = (config && config.url) || '';
    if (
      !config
      || !response
      || response.status !== 401
      || config._retry
      || isAuthUrl(url)
    ) {
      return Promise.reject(error);
    }
    if (!localStorage.getItem('refresh')) {
      clearAuth();
      return Promise.reject(error);
    }
    config._retry = true;
    try {
      const token = await refreshAccessToken();
      if (!localStorage.getItem('refresh')) {
        // Logged out while refreshing; do not replay the request.
        return Promise.reject(error);
      }
      config.headers = { ...(config.headers || {}), Authorization: `Bearer ${token}` };
      return api(config);
    } catch {
      clearAuth();
      return Promise.reject(error);
    }
  },
);

export default api;
