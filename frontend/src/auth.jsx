import { createContext, useContext, useCallback, useEffect, useRef, useState } from 'react';
import api from './api';

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx); // eslint-disable-line react/only-export-components

const STAFF_ROLES = ['system_admin', 'it_manager', 'it_support'];

// SECURITY NOTE (frontend token storage).
// Access tokens are kept in React state + localStorage (for page-reload boot);
// refresh tokens are stored in localStorage by default (body-based refresh).
// When the backend is configured with JWT_REFRESH_COOKIE_ENABLED=true, the
// refresh endpoint returns the refresh token as an httpOnly/secure/sameSite
// cookie and omits it from the JSON body, and the api layer switches to
// cookie-based refresh (no localStorage refresh token, no body refresh).
// Either way, the access token is still readable by script, so same-origin
// XSS can still exfiltrate it; short lifetimes (1h) + blacklist-on-logout +
// rate-limited auth + Secure cookies + a strict CSP are the mitigation.
// See backend/docs/KNOWN_LIMITATIONS.md (Authentication / authorization).
//
// Upper bound on the best-effort backend blacklist call. The request has no
// axios timeout, so without this a hung connection would keep the refresh
// token in localStorage and block logout indefinitely.
const LOGOUT_TIMEOUT_MS = 5000;

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Logout request timed out.')), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

export function AuthProvider({ children }) {
  const [access, setAccess] = useState(localStorage.getItem('access'));
  const [user, setUser] = useState(null);
  const [profileLoading, setProfileLoading] = useState(!!localStorage.getItem('access'));

  // Bumped on every session change (login/logout). Async work that started
  // for an older session must not write state into the newer one.
  const sessionGen = useRef(0);
  // Whether this tab currently believes it has a session. localStorage is
  // shared by all tabs of this origin, so by the time a "storage" event fires
  // the token is already gone and cannot be used to detect that here.
  const sessionActive = useRef(!!localStorage.getItem('access'));

  const fetchProfile = async () => {
    const generation = sessionGen.current;
    try {
      const res = await api.get('/accounts/me/');
      if (sessionGen.current !== generation) return;
      setUser(res.data);
    } catch {
      if (sessionGen.current !== generation) return;
      localStorage.removeItem('access');
      localStorage.removeItem('refresh');
      sessionActive.current = false;
      setAccess(null);
      setUser(null);
    } finally {
      if (sessionGen.current === generation) setProfileLoading(false);
    }
  };

  const logout = useCallback(async () => {
    // Invalidate in-flight profile/auth work and drop the React session now:
    // the UI must not stay authenticated while the network call runs.
    sessionGen.current += 1;
    sessionActive.current = false;
    setAccess(null);
    setUser(null);
    setProfileLoading(false);
    // Body-based path: send the localStorage refresh so the backend can
    // blacklist it and (in cookie mode) clear the refresh cookie.
    const refresh = localStorage.getItem('refresh');
    if (refresh) {
      try {
        await withTimeout(api.post('/accounts/logout/', { refresh }), LOGOUT_TIMEOUT_MS);
      } catch {
        // Backend unreachable, timed out or token already invalid: still log
        // out locally so the user cannot keep using a stale session.
      }
    }
    // Clear local artifacts. Do not clobber tokens belonging to a session
    // created while this call was in flight (logout -> login before the
    // request settled).
    if (localStorage.getItem('refresh') === refresh) {
      localStorage.removeItem('access');
      localStorage.removeItem('refresh');
    }
  }, []);

  useEffect(() => {
    if (access) fetchProfile();
    else setProfileLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // Session recovery: the API layer dispatches this when a refresh
    // fails; follow the same path as an explicit logout.
    const onExpired = () => logout();
    window.addEventListener('auth-expired', onExpired);
    return () => window.removeEventListener('auth-expired', onExpired);
  }, [logout]);

  // Cross-tab session sync: if another tab logs out (clears the access token
  // in localStorage), mirror that logout here so this tab's React state does
  // not stay authenticated. localStorage is shared, so the token is already
  // gone by the time the event fires; `sessionActive` records whether this
  // tab was still using it.
  useEffect(() => {
    // Cross-tab session sync: localStorage is shared across tabs, so when
    // another tab logs out (clears the access token) or logs in as a different
    // user (replaces the access token), mirror that here. This tab's React
    // state must never stay authenticated with a token that no longer belongs
    // to this session.
    const onStorage = (e) => {
      if (e.key !== 'access' || !sessionActive.current) return;
      const next = e.newValue;
      if (next === null) {
        // Another tab logged out. Mirror locally (best-effort backend
        // blacklist already attempted by the other tab).
        logout(); // eslint-disable-line react-hooks/exhaustive-deps
      } else if (next !== access) {
        // Another tab logged in as a different user. Invalidate this session
        // without hitting the backend (the other tab owns its own session).
        sessionGen.current += 1;
        sessionActive.current = false;
        setAccess(null);
        setUser(null);
        setProfileLoading(false);
        localStorage.removeItem('refresh');
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [logout, access]);

  const login = async (email, password) => {
    // Backend USERNAME_FIELD is 'email', so SimpleJWT's token endpoint
    // requires {email, password} (not {username, password}).
    const res = await api.post('/token/', { email, password });
    sessionGen.current += 1;
    sessionActive.current = true;
    // Access token: keep in memory + localStorage (so a page reload boots
    // authenticated without needing a refresh round-trip).
    localStorage.setItem('access', res.data.access);
    setAccess(res.data.access);
    // Refresh token: store in localStorage only when the backend returned it
    // in the body. When JWT_REFRESH_COOKIE_ENABLED is on, the refresh token
    // is served as an httpOnly cookie and omitted from the body, so we must
    // not store it here (the api layer will refresh from the cookie instead).
    if (res.data.refresh !== undefined) {
      localStorage.setItem('refresh', res.data.refresh);
    } else {
      localStorage.removeItem('refresh');
    }
    setProfileLoading(true);
    await fetchProfile();
  };
  const role = user?.role;
  const isSuperuser = !!user?.is_superuser;
  const isSystemAdmin = role === 'system_admin' || isSuperuser;
  const isITManager = role === 'it_manager';
  const isITSupport = role === 'it_support';
  const isEmployee = role === 'employee';
  const isStaff = !!user && (STAFF_ROLES.includes(role) || isSuperuser);
  const isAdmin = isSystemAdmin;
  // NOTE: IT Manager and IT Support currently share the same capability
  // surface in most areas (the backend IsITStaff permission treats them
  // identically). The it_support role exists for future segregation but is not
  // yet assigned distinct capabilities. Until that changes, IT Manager-only
  // gates below intentionally include IT Support as well — splitting them is a
  // backend permission + frontend-capability change, not a one-line rename.
  const isManagerOrAdmin = isSystemAdmin || isITManager;
  const isSupportOrAbove = isSystemAdmin || isITManager || isITSupport;
  const canCreateTickets =
    !!user && (isStaff || role === 'system_admin' || !!user.can_create_tickets || isSuperuser);
  const canManageUsers = isSystemAdmin;
  const canManageVendors = isSystemAdmin || isITManager;
  const canViewVendors = isSupportOrAbove;
  const canManageServiceCatalogue = isSystemAdmin || isITManager;
  const canApproveServiceRequests = isSystemAdmin || isITManager;
  const canConfigureWorkflow = isSystemAdmin || isITManager;
  const canApproveDisposals = isSystemAdmin || isITManager;
  const canManageInventory = isSystemAdmin || isITManager;
  const canAdjustInventory = isSystemAdmin || isITManager;
  const canPublishKnowledgeBase = isSystemAdmin || isITManager;
  const canManageScheduledReports = isSystemAdmin || isITManager;
  const canAccessAudit = isSystemAdmin;
  const canAccessRecycleBin = isSystemAdmin;
  const canPerformPermanentDeletion = isSystemAdmin;
  const canViewLifecycle = isAdmin || isManagerOrAdmin || isStaff || isEmployee;
  const canCreateLifecycleCase = isStaff;
  const canManageLifecycleCase = isManagerOrAdmin;
  const canManageLifecycleTemplates = isManagerOrAdmin;
  const canManageLifecycleTasks = isStaff;
  const canCompleteLifecycleCase = isManagerOrAdmin;
  const canViewLifecycleDashboard = isAdmin || isManagerOrAdmin || isStaff || isEmployee;
  const canViewProcurement = isStaff;
  const canCreatePurchaseRequest = isStaff;
  const canApprovePurchaseRequest = isManagerOrAdmin;
  const canManageQuotations = isStaff;
  const canSelectProcurementVendor = isManagerOrAdmin;
  const canCreatePurchaseOrder = isManagerOrAdmin;
  const canApprovePurchaseOrder = isManagerOrAdmin;
  const canIssuePurchaseOrder = isManagerOrAdmin;
  const canCreateGoodsReceipt = isStaff;
  const canPostGoodsReceipt = isStaff;
  const canRegisterProcurementAssets = isStaff;
  const canViewProcurementReports = isManagerOrAdmin;
  const canViewLicensing = isStaff || isEmployee; // My Software for employees
  const canManageSoftwareProducts = isManagerOrAdmin;
  const canManageLicenseAgreements = isManagerOrAdmin;
  const canViewLicenseCosts = isManagerOrAdmin;
  const canManageLicenseAllocations = isStaff;
  const canManageLicenseInstallations = isStaff;
  const canManageLicenseRenewals = isStaff;
  const canApproveLicenseRenewals = isManagerOrAdmin;
  const canViewLicenseSecrets = isSupportOrAbove;
  const canRevealLicenseSecrets = isSystemAdmin;
  const canManageLicenseDocuments = isStaff;
  const canManageLicenseCompliance = isManagerOrAdmin;
  const canViewLicenseReports = isManagerOrAdmin;
  const canViewMySoftware = isEmployee || isStaff;
  return (
    <AuthCtx.Provider value={{ access, user, profileLoading, login, logout, isStaff, isAdmin, canCreateTickets, refreshProfile: fetchProfile, role, isSuperuser, isSystemAdmin, isITManager, isITSupport, isEmployee, isManagerOrAdmin, isSupportOrAbove, canManageUsers, canManageVendors, canViewVendors, canManageServiceCatalogue, canApproveServiceRequests, canConfigureWorkflow, canApproveDisposals, canManageInventory, canAdjustInventory, canPublishKnowledgeBase, canManageScheduledReports, canAccessAudit, canAccessRecycleBin, canPerformPermanentDeletion, canViewLifecycle, canCreateLifecycleCase, canManageLifecycleCase, canManageLifecycleTemplates, canManageLifecycleTasks, canCompleteLifecycleCase, canViewLifecycleDashboard, canViewProcurement, canCreatePurchaseRequest, canApprovePurchaseRequest, canManageQuotations, canSelectProcurementVendor, canCreatePurchaseOrder, canApprovePurchaseOrder, canIssuePurchaseOrder, canCreateGoodsReceipt, canPostGoodsReceipt, canRegisterProcurementAssets, canViewProcurementReports, canViewLicensing, canManageSoftwareProducts, canManageLicenseAgreements, canViewLicenseCosts, canManageLicenseAllocations, canManageLicenseInstallations, canManageLicenseRenewals, canApproveLicenseRenewals, canViewLicenseSecrets, canRevealLicenseSecrets, canManageLicenseDocuments, canManageLicenseCompliance, canViewLicenseReports, canViewMySoftware }}>
      {children}
    </AuthCtx.Provider>
  );
}
