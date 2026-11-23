import axios from 'axios';

const VITE_API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api';
// When true, the refresh token is expected to live in an httpOnly cookie
// (backend JWT_REFRESH_COOKIE_ENABLED=true). The frontend then keeps only the
// access token in localStorage (for page-reload boot) and refreshes via the
// cookie (empty-body POST, browser sends the cookie automatically). When false
// (default, including tests), the body-based refresh path is used.
const USE_REFRESH_COOKIE = !!(import.meta.env.VITE_USE_REFRESH_COOKIE);

const api = axios.create({
  baseURL: VITE_API_BASE_URL,
  timeout: 30000,
});

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

// In-flight refresh promises. In body mode, keyed by the refresh token so
// concurrent 401s sharing the same refresh token do one refresh. In cookie
// mode (no readable refresh token), a single in-flight promise dedupes.
let bodyRefreshPromise = null;
let bodyRefreshToken = null;
let cookieRefreshPromise = null;

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
  bodyRefreshPromise = null;
  bodyRefreshToken = null;
  cookieRefreshPromise = null;
  window.dispatchEvent(new Event('auth-expired'));
}

function refreshFromBody(refresh) {
  if (!refresh) return Promise.reject(new Error('No refresh token to refresh with.'));
  if (bodyRefreshPromise && bodyRefreshToken === refresh) {
    return bodyRefreshPromise;
  }
  bodyRefreshToken = refresh;
  const base = (api.defaults && api.defaults.baseURL) || '';
  bodyRefreshPromise = axios
    .post(`${base}/token/refresh/`, { refresh })
    .then((r) => {
      if (localStorage.getItem('refresh') === refresh) {
        localStorage.setItem('access', r.data.access);
      }
      return r.data.access;
    })
    .finally(() => {
      if (bodyRefreshToken === refresh) {
        bodyRefreshPromise = null;
        bodyRefreshToken = null;
      }
    });
  return bodyRefreshPromise;
}

function refreshFromCookie() {
  if (cookieRefreshPromise) return cookieRefreshPromise;
  const base = (api.defaults && api.defaults.baseURL) || '';
  cookieRefreshPromise = axios
    .post(`${base}/token/refresh/`, {})
    .then((r) => {
      const access = r.data && r.data.access;
      if (access) localStorage.setItem('access', access);
      return access;
    })
    .finally(() => {
      cookieRefreshPromise = null;
    });
  return cookieRefreshPromise;
}

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const { config, response } = error || {};
    const url = (config && config.url) || '';
    if (
      !config ||
      !response ||
      response.status !== 401 ||
      config._retry ||
      isAuthUrl(url)
    ) {
      return Promise.reject(error);
    }
    config._retry = true;
    const refresh = localStorage.getItem('refresh');
    try {
      let token;
      if (USE_REFRESH_COOKIE && !refresh) {
        // Cookie mode: refresh token lives in an httpOnly cookie; refresh with
        // an empty body and let the browser send the cookie.
        token = await refreshFromCookie();
        config.headers = { ...(config.headers || {}), Authorization: `Bearer ${token}` };
        return api(config);
      }
      if (!refresh) {
        if (onApiError) {
          try { onApiError(error, response && response.status); } catch { /* ignore */ }
        }
        clearAuth();
        return Promise.reject(error);
      }
      // Body mode: we have a localStorage refresh token.
      token = await refreshFromBody(refresh);
      if (localStorage.getItem('refresh') !== refresh) {
        // Logged out (or signed in as someone else) while refreshing; never
        // replay the request with a token minted for the previous session.
        return Promise.reject(error);
      }
      config.headers = { ...(config.headers || {}), Authorization: `Bearer ${token}` };
      return api(config);
    } catch {
      if (onApiError) {
        try { onApiError(error, response && response.status); } catch { /* ignore */ }
      }
      if (USE_REFRESH_COOKIE && !refresh) {
        clearAuth();
        return Promise.reject(error);
      }
      if (localStorage.getItem('refresh') !== refresh) {
        return Promise.reject(error);
      }
      clearAuth();
      return Promise.reject(error);
    }
  },
);

export default api;

/** Optional callback set by the UI layer (ToastProvider) so the response
 *  interceptor can surface API errors as toasts. Signature: (error, status). */
let onApiError = null;

export function setApiErrorHandler(handler) {
  onApiError = handler;
}

/** Reset in-flight refresh promises and module state. For test isolation only;
 *  call in test beforeEach so one test's pending refresh never leaks into the
 *  next. Safe to call in production (no-op unless a refresh is mid-flight). */
export function resetApiState() {
  bodyRefreshPromise = null;
  bodyRefreshToken = null;
  cookieRefreshPromise = null;
}
