import { createContext, useContext, useCallback, useEffect, useRef, useState } from 'react';
import api from './api';

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

const STAFF_ROLES = ['system_admin', 'it_manager', 'it_support'];

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
    const refresh = localStorage.getItem('refresh');
    // Invalidate in-flight profile/auth work and drop the React session now:
    // the UI must not stay authenticated while the network call runs.
    sessionGen.current += 1;
    sessionActive.current = false;
    setAccess(null);
    setUser(null);
    setProfileLoading(false);
    try {
      if (refresh) {
        // Best-effort: blacklist the refresh token on the backend so it can
        // no longer mint new access tokens, in this tab or any other. The
        // backend tolerates invalid / already-blacklisted tokens, so a
        // failure here must not prevent local logout.
        await withTimeout(api.post('/accounts/logout/', { refresh }), LOGOUT_TIMEOUT_MS);
      }
    } catch {
      // Backend unreachable, timed out or token already invalid: still log
      // out locally so the user cannot keep using a stale session.
    } finally {
      // Do not clobber tokens belonging to a session created while this call
      // was in flight (logout -> login before the request settled).
      if (localStorage.getItem('refresh') === refresh) {
        localStorage.removeItem('access');
        localStorage.removeItem('refresh');
      }
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
  }, []);

  // Cross-tab session sync: if another tab logs out (clears the access token
  // in localStorage), mirror that logout here so this tab's React state does
  // not stay authenticated. localStorage is shared, so the token is already
  // gone by the time the event fires; `sessionActive` records whether this
  // tab was still using it.
  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === 'access' && e.newValue === null && sessionActive.current) {
        logout();
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [logout]);

  const login = async (email, password) => {
    // Backend USERNAME_FIELD is 'email', so SimpleJWT's token endpoint
    // requires {email, password} (not {username, password}).
    const res = await api.post('/token/', { email, password });
    sessionGen.current += 1;
    sessionActive.current = true;
    localStorage.setItem('access', res.data.access);
    localStorage.setItem('refresh', res.data.refresh);
    setAccess(res.data.access);
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
