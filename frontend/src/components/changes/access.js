const CHANGE_STAFF_ROLES = new Set(['system_admin', 'it_manager', 'it_support']);

export function canManageChanges(auth) {
  if (!auth || auth.user?.is_active === false) return false;
  if (auth.isStaff || auth.isAdmin) return true;
  const role = auth.role || auth.user?.role;
  return typeof role === 'string' && CHANGE_STAFF_ROLES.has(role);
}

export default canManageChanges;
