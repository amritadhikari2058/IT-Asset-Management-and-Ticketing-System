import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { HashRouter } from 'react-router-dom';
import { AuthProvider } from '../auth';
import { Dashboard } from '../pages/dashboard/Dashboard';
import { Tickets } from '../pages';
import { Assets } from '../pages';
import { Users } from '../pages';
import { ProblemList } from '../pages/problem-management/ProblemList';
import { CmdbItemList } from '../features/cmdb/cmdb-item-list';
import { ChangeList } from '../features/changes/change-list';
import { LifecycleDashboard } from '../pages/lifecycle/LifecycleDashboard';
import { LicensingDashboard } from '../pages/licensing/LicensingDashboard';

const { mockGet, mockRequest } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockRequest: vi.fn(),
}));

vi.mock('../api', () => ({
  default: {
    get: mockGet,
    request: mockRequest,
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

const profile = {
  id: 1,
  email: 'admin@local',
  role: 'system_admin',
  is_superuser: true,
  is_active: true,
};

const emptyList = { data: { count: 0, results: [] } };

const dashboardData = {
  data: {
    generated_at: '2026-01-01T00:00:00Z',
    employees: { active: 0, total: 0, departments: 0 },
    assets: { total: 0, under_maintenance: 0, with_open_maintenance: 0, by_status: {} },
    tickets: {
      open: 0,
      total: 0,
      overdue: 0,
      sla: { compliance_pct: null, resolved_on_time: 0, resolved_with_sla: 0 },
      by_status: {},
      by_priority: {},
      avg_resolution_hours: 0,
    },
    maintenance: { open: 0, overdue: 0, upcoming: [] },
    disposals: { pending_approval: 0, approved_not_completed: 0, recent: [] },
  },
};

function renderRoute(component) {
  return render(
    <HashRouter>
      <AuthProvider>{component}</AuthProvider>
    </HashRouter>
  );
}

const headingRoutes = [
  { name: 'dashboard', component: <Dashboard />, heading: 'Dashboard' },
  { name: 'tickets', component: <Tickets />, heading: 'Tickets' },
  { name: 'assets', component: <Assets />, heading: 'Assets' },
  { name: 'problem management', component: <ProblemList />, heading: 'Problems' },
  { name: 'lifecycle', component: <LifecycleDashboard />, heading: 'Lifecycle Dashboard' },
  { name: 'licensing', component: <LicensingDashboard />, heading: 'Software Licensing Dashboard' },
  { name: 'employees', component: <Users />, heading: 'Employees' },
];

describe('Frontend Route Integration Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem('access', 'test-token');
    window.location.hash = '#/';
    mockGet.mockImplementation((url = '') => {
      if (url.includes('/accounts/me/')) return Promise.resolve({ data: profile });
      if (url.includes('/common/dashboard/')) return Promise.resolve(dashboardData);
      if (url.includes('/lifecycle/dashboard/')) return Promise.resolve({ data: {} });
      if (url.includes('/licensing/dashboard/')) return Promise.resolve({ data: {} });
      return Promise.resolve(emptyList);
    });
    mockRequest.mockResolvedValue(emptyList);
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
    window.location.hash = '#/';
  });

  headingRoutes.forEach(({ name, component, heading }) => {
    it(`renders the ${name} route component`, async () => {
      renderRoute(component);
      expect(await screen.findByRole('heading', { name: heading, level: 1 })).toBeTruthy();
    });
  });

  it('renders the CMDB route component', async () => {
    renderRoute(<CmdbItemList />);
    expect(await screen.findByText(/no cmdb items/i)).toBeTruthy();
  });

  it('renders the changes route component', async () => {
    renderRoute(<ChangeList />);
    expect(await screen.findByText(/no changes/i)).toBeTruthy();
  });
});
