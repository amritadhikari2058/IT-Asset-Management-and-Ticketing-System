import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

const {
  mockAuth,
  mockListAlerts,
  mockGetAlert,
  mockAlertAction,
  mockParseMonitoringError,
} = vi.hoisted(() => ({
  mockAuth: vi.fn(),
  mockListAlerts: vi.fn(),
  mockGetAlert: vi.fn(),
  mockAlertAction: vi.fn(),
  mockParseMonitoringError: vi.fn(),
}));

vi.mock('../../auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

vi.mock('../../services/monitoring/monitoring-api', () => ({
  listAlerts: (...args) => mockListAlerts(...args),
  getAlert: (...args) => mockGetAlert(...args),
  alertAction: (...args) => mockAlertAction(...args),
  parseMonitoringError: (...args) => mockParseMonitoringError(...args),
}));

vi.mock('../../components', () => ({
  PageHeader: ({ title, sub, actions }) => (
    <header>
      <h1>{title}</h1>
      {sub && <p>{sub}</p>}
      {actions}
    </header>
  ),
  Button: ({ children, onClick, disabled }) => (
    <button type="button" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
}));

vi.mock('../../components/monitoring/MonitoringUI', () => ({
  AccessDeniedPanel: () => <div role="alert">Access restricted</div>,
  ErrorPanel: ({ message, onRetry }) => (
    <div>
      <div role="alert">{message}</div>
      {onRetry && <button onClick={onRetry}>Retry</button>}
    </div>
  ),
  LoadingPanel: ({ label }) => <div role="status">{label}</div>,
  StatusBadge: ({ value }) => <span>{value}</span>,
  SeverityBadge: ({ value }) => <span>{value}</span>,
}));

import { AlertList } from '../../features/monitoring/AlertList';
import { AlertDetail } from '../../features/monitoring/AlertDetail';

function makeAuth(role) {
  const isSystemAdmin = role === 'system_admin';

  return {
    role,
    isAdmin: isSystemAdmin,
    isSuperuser: false,
    isStaff: isSystemAdmin || role === 'it_manager' || role === 'it_support',
    isSupportOrAbove: isSystemAdmin || role === 'it_manager' || role === 'it_support',
    user: role ? { id: 1, role, is_active: true } : null,
  };
}

const ALERT = {
  id: 7,
  alert_number: 'MON-0007',
  title: 'Database connection failure',
  severity: 'critical',
  status: 'open',
  source_name: 'Production DB',
  event_count: 4,
  automation_state: 'failed',
  automation_retry_count: 2,
  automation_error_code: 'CONNECTION_TIMEOUT',
};

function alertPage(overrides = {}) {
  return {
    count: 1,
    next: null,
    previous: null,
    results: [ALERT],
    ...overrides,
  };
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();

  mockAuth.mockReturnValue(makeAuth('system_admin'));
  mockListAlerts.mockResolvedValue(alertPage());
  mockGetAlert.mockResolvedValue({
    alert_number: 'MON-0007',
    title: 'Database connection failure',
    severity: 'critical',
    status: 'open',
    source_name: 'Production DB',
    event_count: 4,
  });
  mockAlertAction.mockResolvedValue({});
  mockParseMonitoringError.mockReturnValue({
    fields: {},
    global: 'Unable to load monitoring alerts.',
  });
});

afterEach(() => cleanup());

describe('Monitoring alert list', () => {
  it('loads and renders the paginated alert collection', async () => {
    render(<AlertList />);

    expect(await screen.findByText('MON-0007')).toBeTruthy();
    expect(screen.getByText('Database connection failure')).toBeTruthy();
    expect(screen.getByText('Production DB')).toBeTruthy();
    expect(screen.getByText(/Error:\s*CONNECTION_TIMEOUT/)).toBeTruthy();

    expect(mockListAlerts).toHaveBeenCalledWith({
      page: 1,
      page_size: 20,
    });
  });

  it('loads the next page and allows returning to the previous page', async () => {
    mockListAlerts.mockImplementation(async ({ page }) => {
      if (page === 1) {
        return alertPage({
          count: 21,
          next: 'https://example.test/alerts/?page=2',
        });
      }

      return alertPage({
        count: 21,
        previous: 'https://example.test/alerts/',
        results: [{
          ...ALERT,
          id: 21,
          alert_number: 'MON-0021',
          title: 'Second page alert',
        }],
      });
    });

    render(<AlertList />);

    expect(await screen.findByText('MON-0007')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    expect(await screen.findByText('MON-0021')).toBeTruthy();

    await waitFor(() => {
      expect(mockListAlerts).toHaveBeenLastCalledWith({
        page: 2,
        page_size: 20,
      });
    });

    fireEvent.click(screen.getByRole('button', { name: 'Previous' }));

    expect(await screen.findByText('MON-0007')).toBeTruthy();

    await waitFor(() => {
      expect(mockListAlerts).toHaveBeenLastCalledWith({
        page: 1,
        page_size: 20,
      });
    });
  });

  it('renders the empty state when the collection has no alerts', async () => {
    mockListAlerts.mockResolvedValue(alertPage({
      count: 0,
      results: [],
    }));

    render(<AlertList />);

    expect(await screen.findByText('No monitoring alerts')).toBeTruthy();
    expect(screen.getByText('No alerts were found on this page.')).toBeTruthy();
  });

  it('shows an error and retries the collection request', async () => {
    mockListAlerts
      .mockRejectedValueOnce(new Error('request failed'))
      .mockResolvedValueOnce(alertPage());

    render(<AlertList />);

    expect(await screen.findByText('Unable to load monitoring alerts.')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('MON-0007')).toBeTruthy();
    expect(mockListAlerts).toHaveBeenCalledTimes(2);
  });

  it.each(['it_manager', 'it_support', 'employee'])(
    'denies %s without requesting the alert collection',
    async (role) => {
      mockAuth.mockReturnValue(makeAuth(role));

      render(<AlertList />);

      expect(screen.getByText('Access restricted')).toBeTruthy();

      await waitFor(() => {
        expect(mockListAlerts).not.toHaveBeenCalled();
      });
    },
  );
});

describe('Monitoring alert detail', () => {
  it('loads and renders the supported alert detail fields for System Admin', async () => {
    render(<AlertDetail alertId="7" />);

    expect(await screen.findByText('MON-0007')).toBeTruthy();
    expect(screen.getAllByText('Database connection failure')).toHaveLength(2);
    expect(screen.getByText('Production DB')).toBeTruthy();
    expect(mockGetAlert).toHaveBeenCalledWith('7');
  });

  it.each(['it_manager', 'it_support', 'employee'])(
    'denies %s without requesting alert details',
    async (role) => {
      mockAuth.mockReturnValue(makeAuth(role));

      render(<AlertDetail alertId="7" />);

      expect(screen.getByText('Access restricted')).toBeTruthy();

      await waitFor(() => {
        expect(mockGetAlert).not.toHaveBeenCalled();
      });
    },
  );
});