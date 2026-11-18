const MONITORING_ROLES = new Set(['system_admin', 'it_manager', 'it_support']);
const KNOWN_ROLES = new Set([...MONITORING_ROLES, 'employee']);

function roleOf(auth) {
  if (!auth) return null;
  return auth.role ?? auth.user?.role ?? null;
}

function isInactive(auth) {
  const active = auth?.user?.is_active;
  return active === false || active === 0 || active === 'false' || active === 'inactive';
}

function hasKnownRole(auth, role) {
  return !role || auth?.isSuperuser === true || KNOWN_ROLES.has(role);
}

export function canAccessMonitoring(auth) {
  if (!auth || isInactive(auth)) return false;
  const role = roleOf(auth);
  if (role === 'employee' || !hasKnownRole(auth, role)) return false;
  return Boolean(auth.isSuperuser || auth.isStaff || auth.isAdmin || auth.isSupportOrAbove);
}

export function canAdministerMonitoring(auth) {
  if (!auth || isInactive(auth)) return false;
  const role = roleOf(auth);
  if (role === 'employee' || !hasKnownRole(auth, role)) return false;
  if (role && role !== 'system_admin' && auth.isSuperuser !== true) return false;
  return Boolean(auth.isAdmin || auth.isSuperuser);
}
