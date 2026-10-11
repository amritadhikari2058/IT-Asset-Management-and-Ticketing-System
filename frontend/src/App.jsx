import { useEffect, useState } from 'react';
import { THEME } from './theme';
import { AuthProvider, useAuth } from './auth';
import { Assets, Categories, Login, Profile, RecycleBin, ResetPassword, Tickets, Users, VerifyEmail } from './pages';
import { AssetForm, AssetDetail } from './assets';
import { TicketForm, TicketDetail } from './tickets';
import { Notifications, NotifBadge } from './notifications';

function matchRoute(hash) {
  let m;
  if ((m = hash.match(/^#\/tickets\/(\d+)\/edit$/))) return <TicketForm id={m[1]} />;
  if (hash === '#/tickets/new') return <TicketForm />;
  if ((m = hash.match(/^#\/tickets\/(\d+)$/))) return <TicketDetail id={m[1]} />;
  if ((m = hash.match(/^#\/assets\/(\d+)\/edit$/))) return <AssetForm id={m[1]} />;
  if (hash === '#/assets/new') return <AssetForm />;
  if ((m = hash.match(/^#\/assets\/(\d+)$/))) return <AssetDetail id={m[1]} />;
  const routes = {
    '#/tickets': <Tickets />,
    '#/assets': <Assets />,
    '#/categories': <Categories />,
    '#/notifications': <Notifications />,
    '#/recycle': <RecycleBin />,
    '#/users': <Users />,
    '#/profile': <Profile />,
    '#/verify-email': <VerifyEmail />,
    '#/reset-password': <ResetPassword />,
  };
  return routes[hash] ?? <Tickets />;
}

function Shell() {
  const { access, logout, user, profileLoading, isAdmin } = useAuth();
  const [hash, setHash] = useState(location.hash || '#/tickets');
  useEffect(() => {
    const fn = () => setHash(location.hash || '#/tickets');
    addEventListener('hashchange', fn);
    return () => removeEventListener('hashchange', fn);
  }, []);
  if (!access) {
    if (hash.startsWith('#/verify-email')) return <VerifyEmail />;
    if (hash.startsWith('#/reset-password')) return <ResetPassword />;
    return <Login />;
  }
  if (profileLoading) return <p style={{ padding: 24 }}>Loading…</p>;
  const nav = ['#/tickets', '#/assets', '#/categories', '#/notifications', '#/users'];
  if (isAdmin) nav.push('#/recycle');
  return (
    <div style={{ background: THEME.supportingBackground, minHeight: '100vh', color: THEME.mainText }}>
      <header style={{ background: THEME.mainBackground, borderBottom: `1px solid ${THEME.borders}`,
        padding: '10px 16px', display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <b style={{ color: THEME.primaryDarkRed }}>Ticket &amp; Asset</b>
        {nav.map((h) => (
          <a key={h} href={h} style={{ color: h === hash || (h !== '#/tickets' && hash.startsWith(h + '/')) ? THEME.primaryDarkRed : THEME.secondaryIndigo,
            fontWeight: h === hash ? 700 : 400 }}>{h.replace('#/', '')}{h === '#/notifications' && <NotifBadge />}</a>))}
        <span style={{ marginLeft: 'auto', fontSize: 13 }}>
          {user ? <a href="#/profile">{`${user.employee_id} (${user.role})`}</a> : ''}
        </span>
        <button onClick={logout}>Logout</button>
      </header>
      <main style={{ background: THEME.mainBackground, margin: 16, padding: 16,
        border: `1px solid ${THEME.borders}`, borderRadius: 8 }}>
        {matchRoute(hash)}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}
