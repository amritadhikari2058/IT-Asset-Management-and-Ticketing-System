import { createContext, useContext, useEffect, useState } from 'react';
import api from './api';

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

const STAFF_ROLES = ['system_admin', 'it_manager', 'it_support'];

export function AuthProvider({ children }) {
  const [access, setAccess] = useState(localStorage.getItem('access'));
  const [user, setUser] = useState(null);
  const [profileLoading, setProfileLoading] = useState(!!localStorage.getItem('access'));

  const fetchProfile = async () => {
    try {
      const res = await api.get('/accounts/me/');
      setUser(res.data);
    } catch {
      localStorage.removeItem('access');
      localStorage.removeItem('refresh');
      setAccess(null);
      setUser(null);
    } finally {
      setProfileLoading(false);
    }
  };

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

  const login = async (email, password) => {
    // Backend USERNAME_FIELD is 'email', so SimpleJWT's token endpoint
    // requires {email, password} (not {username, password}).
    const res = await api.post('/token/', { email, password });
    localStorage.setItem('access', res.data.access);
    localStorage.setItem('refresh', res.data.refresh);
    setAccess(res.data.access);
    setProfileLoading(true);
    await fetchProfile();
  };
  const logout = () => {
    localStorage.removeItem('access');
    localStorage.removeItem('refresh');
    setAccess(null);
    setUser(null);
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
