import axios from 'axios';

const api = axios.create({ baseURL: 'http://127.0.0.1:8000/api' });

api.interceptors.request.use((cfg) => {
  const t = localStorage.getItem('access');
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  // axios auto-set `Content-Type: application/json` only when there is no
  // existing Content-Type. FormData needs a multipart boundary, so we must
  // never let the request interceptor stamp JSON on a multipart body.
  if (cfg.data instanceof FormData && cfg.headers['Content-Type'] === undefined) {
    // Remove any inherited JSON content type so axios leaves the boundary
    // alone and the browser sends the correct multipart envelope.
    delete cfg.headers['Content-Type'];
  }
  return cfg;
});

// Shared in-flight refresh so concurrent 401s do one token request. The
// promise is keyed by the refresh token it was started with, so a refresh
// begun in a previous session is never reused after a logout/new login.
let refreshPromise = null;
let refreshPromiseToken = null;

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

function refreshAccessToken(refresh) {
  if (!refresh) return Promise.reject(new Error('No refresh token to refresh with.'));
  if (!refreshPromise || refreshPromiseToken !== refresh) {
    refreshPromiseToken = refresh;
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
        // A newer session may already have replaced this promise.
        if (refreshPromiseToken === refresh) {
          refreshPromise = null;
          refreshPromiseToken = null;
        }
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
    const refresh = localStorage.getItem('refresh');
    if (!refresh) {
      clearAuth();
      return Promise.reject(error);
    }
    config._retry = true;
    try {
      const token = await refreshAccessToken(refresh);
      if (localStorage.getItem('refresh') !== refresh) {
        // Logged out (or signed in as someone else) while refreshing; never
        // replay the request with a token minted for the previous session.
        return Promise.reject(error);
      }
      config.headers = { ...(config.headers || {}), Authorization: `Bearer ${token}` };
      return api(config);
    } catch {
      // Only tear down the session whose refresh actually failed.
      if (localStorage.getItem('refresh') !== refresh) return Promise.reject(error);
      clearAuth();
      return Promise.reject(error);
    }
  },
);

export default api;
