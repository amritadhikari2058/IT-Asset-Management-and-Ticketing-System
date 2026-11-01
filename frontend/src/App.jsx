import { useEffect, useState } from 'react';
import { useAuth, AuthProvider } from './auth';
import { Assets, Categories, Departments, EmployeeDetail, Login, Profile, RecycleBin, ResetPassword, SLAConfig, SLAReport, Tickets, Users, VerifyEmail } from './pages';
import { AssetForm, AssetDetail } from './assets';
import { AuditLogPage } from './audit';
import { TicketForm, TicketDetail } from './tickets';
import { Notifications, NotifBadge } from './notifications';
import { Maintenance } from './maintenance';
import { Disposals } from './disposals';
import { Dashboard, DepartmentReports } from './dashboard';

const NAV = [
  { section: 'Work' },
{ hash: '#/dashboard', label: 'Dashboard', staffOnly: true },
  { hash: '#/tickets', label: 'Tickets' },
  { hash: '#/self-service', label: 'Self-Service', staffOnly: false },
  { hash: '#/assets', label: 'Assets' },
  { section: 'Operations', staffOnly: true },
  { hash: '#/maintenance', label: 'Maintenance', staffOnly: true },
  { hash: '#/disposals', label: 'Disposals', staffOnly: true },
  { section: 'Reports' },
  { hash: '#/reports/sla', label: 'SLA report', staffOnly: true },
  { hash: '#/reports/departments', label: 'Department reports', staffOnly: true },
  { section: 'Organize' },
  { hash: '#/categories', label: 'Categories' },
  { hash: '#/departments', label: 'Departments' },
  { hash: '#/notifications', label: 'Notifications', badge: true },
  { hash: '#users', label: 'Employees' },
];

/** Drop staff-only entries and any section left with no visible items. */
function visibleNav(nav, isStaff) {
  const kept = nav.filter((n) => n.section || !n.staffOnly || isStaff);
  const out = [];
  for (let i = 0; i < kept.length; i += 1) {
    if (!kept[i].section) {
      out.push(kept[i]);
      continue;
    }
    let j = i + 1;
    while (j < kept.length && !kept[j].section) j += 1;
    if (j > i + 1) out.push(kept[i]);
  }
  return out;
}

const TITLES = {
  '#/dashboard': 'Dashboard',
  '#/tickets': 'Tickets',
  '#/reports/sla': 'SLA report',
  '#/reports/departments': 'Department reports',
  '#/assets': 'Assets',
  '#/maintenance': 'Maintenance',
  '#/disposals': 'Disposals',
  '#/categories': 'Categories',
  '#/departments': 'Departments',
  '#/notifications': 'Notifications',
  '#/recycle': 'Recycle Bin',
  '#/audit': 'Audit Log',
  '#/sla-config': 'SLA config',
  '#/users': 'Employees',
  '#/profile': 'My Profile',
};

/** Sticky-header breadcrumb: parent → record → action, so the header
 *  adds orientation instead of repeating the page title below it. */
function crumbs(hash) {
  const h = hash.split('?')[0];
  let m;
  if ((m = h.match(/^#\/(tickets|assets)\/(\d+)(?:\/(edit))?$/))) {
    const trail = [m[1] === 'tickets' ? 'Tickets' : 'Assets', `#${m[2]}`];
    if (m[3]) trail.push('Edit');
    return trail;
  }
  if (h === '#/tickets/new') return ['Tickets', 'New'];
  if (h === '#/assets/new') return ['Assets', 'New'];
  if (h === '#/recycle' || h === '#/audit') return ['Administration', TITLES[h]];
  if (h.startsWith('#/reports/')) return ['Reports', TITLES[h]];
  if ((m = h.match(/^#\/users\/(\d+)$/))) return ['Employees', `Employee #${m[1]}`];
  return [TITLES[h] ?? 'Tickets'];
}

function matchRoute(hash) {
  const route = hash.split('?')[0];
  let m;
  if ((m = route.match(/^#\/tickets\/(\d+)\/edit$/))) return <TicketForm id={m[1]} />;
  if (route === '#/tickets/new') return <TicketForm />;
  if ((m = route.match(/^#\/tickets\/(\d+)$/))) return <TicketDetail id={m[1]} />;
  if ((m = route.match(/^#\/assets\/(\d+)\/edit$/))) return <AssetForm id={m[1]} />;
  if (route === '#/assets/new') return <AssetForm />;
  if ((m = route.match(/^#\/assets\/(\d+)$/))) return <AssetDetail id={m[1]} />;
  if ((m = route.match(/^#\/users\/(\d+)\/?$/))) return <EmployeeDetail id={m[1]} />;
  const routes = {
    '#/dashboard': <Dashboard />,
    '#/tickets': <Tickets />,
    '#/reports/sla': <SLAReport />,
    '#/reports/departments': <DepartmentReports />,
'#/assets': <Assets />,
    '#/maintenance': <Maintenance />,
    '#/disposals': <Disposals />,
    '#/categories': <Categories />,
    '#/departments': <Departments />,
    '#/notifications': <Notifications />,
    '#/recycle': <RecycleBin />,
    '#/audit': <AuditLogPage />,
    '#/sla-config': <SLAConfig />,
    '#/users': <Users />,
    '#/profile': <Profile />,
    '#verify-email': <VerifyEmail />,
    '#reset-password': <ResetPassword />,
    '#self-service': <SelfService />,
  };
  return routes[route] ?? <Tickets />;
}

function isActive(hash, h) {
  return h === hash || (h !== '#/tickets' && hash.startsWith(h + '/'));
}

function Shell() {
  const { access, logout, user, profileLoading, isAdmin, isStaff } = useAuth();
  const [hash, setHash] = useState(location.hash || '#/tickets');
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => {
    const fn = () => { setHash(location.hash || '#/tickets'); setNavOpen(false); };
    addEventListener('hashchange', fn);
    return () => removeEventListener('hashchange', fn);
  }, []);
  if (!access) {
    if (hash.startsWith('#/verify-email')) return <VerifyEmail />;
    if (hash.startsWith('#/reset-password')) return <ResetPassword />;
    return <Login />;
  }
  if (profileLoading) {
    return (
      <p className="page-loading" role="status">
        <span className="spinner" aria-hidden="true" />Loading your workspace…
      </p>
    );
  }
  const el = matchRoute(hash);
  const active = (h) => isActive(hash, h) ? 'active' : '';
  const nav = visibleNav(NAV, isStaff);
  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className={`sidebar${navOpen ? ' nav-open' : ''}`}>
        <a className="brand" href="#/tickets">
          <span className="brand-mark">IT</span>
          <span className="brand-name">Service Desk<small>Ticket &amp; Asset</small></span>
        </a>
        <nav className="sidenav" aria-label="Primary">
          {nav.map((n, i) => n.section
            ? <div key={i} className="sidenav-section">{n.section}</div>
            : (
              <a key={n.hash} href={n.hash} className={active(n.hash)} aria-current={isActive(hash, n.hash) ? 'page' : undefined}>
                <span className="nav-label">{n.label}</span>
                {n.badge && <NotifBadge />}
              </a>
            ))}
          {isAdmin && (
            <>
              <div className="sidenav-section">Administration</div>
              <a href="#/recycle" className={active('#/recycle')} aria-current={isActive(hash, '#/recycle') ? 'page' : undefined}>
                <span className="nav-label">Recycle Bin</span>
              </a>
              <a href="#/audit" className={active('#/audit')} aria-current={isActive(hash, '#/audit') ? 'page' : undefined}>
                <span className="nav-label">Audit Log</span>
              </a>
              <a href="#/sla-config" className={active('#/sla-config')} aria-current={isActive(hash, '#/sla-config') ? 'page' : undefined}>
                <span className="nav-label">SLA config</span>
              </a>
            </>
          )}
        </nav>
        <div className="sidebar-foot">
          <span className="user-chip">
            {user ? <a href="#/profile">{user.employee_id}</a> : ''}
            <small>{user ? user.role.replace('_', ' ') : ''}</small>
          </span>
          <button className="btn-ghost btn-block" onClick={logout}>Log out</button>
        </div>
      </aside>
      <div className={`sidebar-scrim${navOpen ? ' nav-open' : ''}`} onClick={() => setNavOpen(false)} aria-hidden="true" />
      <div className="main-col">
        <div className="topbar">
          <button type="button" className="nav-toggle" onClick={() => setNavOpen((v) => !v)} aria-label={navOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={navOpen}>☰</button>
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs(hash).map((c, i, arr) => (
              <span key={i}>
                {i > 0 && <span className="crumb-sep" aria-hidden="true">/</span>}
                <span className={i === arr.length - 1 ? 'crumb-current' : undefined}>{c}</span>
              </span>
            ))}
          </nav>
        </div>
        <main className="content" id="main-content">{el}</main>
      </div>
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
