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

  const login = async (email, password) => {
    const res = await api.post('/token/', { username: email, password });
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
  const isStaff = !!user && (STAFF_ROLES.includes(user.role) || !!user.is_superuser);
  const isAdmin = !!user && (user.role === 'system_admin' || !!user.is_superuser);
  const canCreateTickets =
    !!user && (isStaff || user.role === 'system_admin' || !!user.can_create_tickets || !!user.is_superuser);
  return (
    <AuthCtx.Provider value={{ access, user, profileLoading, login, logout, isStaff, isAdmin, canCreateTickets, refreshProfile: fetchProfile }}>
      {children}
    </AuthCtx.Provider>
  );
}
