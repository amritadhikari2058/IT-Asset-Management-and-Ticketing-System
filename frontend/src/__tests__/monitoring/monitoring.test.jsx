import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

vi.mock('../../api-utils', () => ({
  parseApiError: vi.fn((e) => ({ fields: {}, global: e?.message || 'Request failed.' })),
}));

import { MonitoringOverview } from '../../features/monitoring/MonitoringOverview';
import { AlertList } from '../../features/monitoring/AlertList';
import { AlertDetail } from '../../features/monitoring/AlertDetail';
import { SourceManagement } from '../../features/monitoring/SourceManagement';
import { PolicyManagement } from '../../features/monitoring/PolicyManagement';
import { LinkedTicketPanel } from '../../features/monitoring/LinkedTicketPanel';
import manifest from '../../features/monitoring/integration-manifest.json';

function ctx(over = {}) {
  return { isAdmin: false, isStaff: false, isSupportOrAbove: false, ...over };
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '#/monitoring/overview';
});

afterEach(() => cleanup());

describe('MonitoringOverview — supported source health', () => {
  it('denies employees', () => {
    mockAuth.mockReturnValue(ctx({}));
    render(<MonitoringOverview />);
    expect(screen.getByText(/do not have permission/)).toBeTruthy();
  });

  it('renders source health from live Sources API', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: [
      { id: 1, name: 'Prometheus', code: 'prom-1', source_type: 'prometheus_alertmanager', status: 'active', health_status: 'healthy', is_active: true },
      { id: 2, name: 'Zabbix', code: 'zabbix-1', source_type: 'zabbix', status: 'disabled', health_status: 'unhealthy', is_active: false },
    ] });
    render(<MonitoringOverview />);
    await screen.findByText('Prometheus');
    await screen.findByText('Sources total');
    await screen.findByText('Sources online');
    await screen.findByText('Sources offline');
    expect(screen.getByText('Zabbix')).toBeTruthy();
  });

  it('labels unavailable dashboard KPIs as unavailable, never zeroes', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: [] });
    render(<MonitoringOverview />);
    await screen.findByText('Active alerts');
    const unavailable = screen.getAllByText('unavailable');
    expect(unavailable.length).toBeGreaterThan(0);
    expect(screen.getAllByText('dashboard API not implemented').length).toBeGreaterThan(0);
  });

  it('does not call the dashboard stub', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: [] });
    render(<MonitoringOverview />);
    await screen.findByText('Active alerts');
    expect(mockGet).not.toHaveBeenCalledWith(expect.stringContaining('/monitoring/dashboard/'));
    expect(mockGet).toHaveBeenCalledWith('/monitoring/sources/?');
  });

  it('handles backend 404 on sources list', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    const err = new Error('Not Found');
    mockGet.mockRejectedValue(err);
    render(<MonitoringOverview />);
    await screen.findByText(/Not Found/);
  });

  it('handles backend 500 safely without stack traces', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    const err = new Error('Internal Server Error');
    mockGet.mockRejectedValue(err);
    render(<MonitoringOverview />);
    await screen.findByText(/Internal Server Error/);
    expect(screen.queryByText(/stack/i)).toBeNull();
    expect(screen.queryByText(/trace/i)).toBeNull();
  });
});

describe('AlertList — unavailable when API absent', () => {
  it('denies non-staff', () => {
    mockAuth.mockReturnValue(ctx({}));
    render(<AlertList />);
    expect(screen.getByText(/do not have permission/)).toBeTruthy();
  });

  it('shows alert list unavailable state, no request to unsupported URL', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: [] });
    render(<AlertList />);
    await screen.findByText(/Alert list API unavailable/);
    expect(mockGet).not.toHaveBeenCalledWith(expect.stringContaining('/monitoring/alerts/'));
  });

  it('retains no fake pagination controls', () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    render(<AlertList />);
    expect(screen.queryByText('Prev')).toBeNull();
    expect(screen.queryByText('Next')).toBeNull();
    expect(screen.queryByText('Page 1')).toBeNull();
  });

  it('retains no filters that imply server filtering', () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    render(<AlertList />);
    expect(screen.queryByText(/Severity/i)).toBeNull();
    expect(screen.queryByText(/Status/i)).toBeNull();
    expect(screen.queryByText(/Search/i)).toBeNull();
  });
});

describe('AlertDetail — supported retrieve only', () => {
  it('denies non-staff', () => {
    mockAuth.mockReturnValue(ctx({}));
    render(<AlertDetail alertId="1" />);
    expect(screen.getByText(/do not have permission/)).toBeTruthy();
  });

  it('renders only serializer-exposed fields', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: {
      alert_number: 'ALT-000001', title: 'DB down', severity: 'critical',
      status: 'open', source_name: 'prom-prod', event_count: 3,
    } });
    window.location.hash = '#/monitoring/alerts/1';
    render(<AlertDetail alertId="1" />);
    await screen.findByText('ALT-000001');
    expect(screen.getByText('ALT-000001')).toBeTruthy();
    expect(screen.getByText('Critical')).toBeTruthy();
    expect(screen.getByText('Open')).toBeTruthy();
    expect(screen.getByText('prom-prod')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
  });

  it('does not render unsupported fields', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: {
      alert_number: 'ALT-000001', title: 'DB down', severity: 'critical',
      status: 'open', source_name: 'prom-prod', event_count: 3,
    } });
    render(<AlertDetail alertId="1" />);
    await screen.findByText('ALT-000001');
    expect(screen.queryByText('Environment')).toBeNull();
    expect(screen.queryByText('Fingerprint')).toBeNull();
    expect(screen.queryByText('First seen')).toBeNull();
    expect(screen.queryByText('Last seen')).toBeNull();
    expect(screen.queryByText('Metric')).toBeNull();
  });

  it('does not expose sensitive data', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: {
      alert_number: 'ALT-000001', title: 'DB down', severity: 'critical',
      status: 'open', source_name: 'prom-prod', event_count: 3,
    } });
    render(<AlertDetail alertId="1" />);
    await screen.findByText('ALT-000001');
    expect(screen.queryByText(/secret/i)).toBeNull();
    expect(screen.queryByText(/authorization/i)).toBeNull();
    expect(screen.queryByText(/cookie/i)).toBeNull();
    expect(screen.queryByText(/password/i)).toBeNull();
    expect(screen.queryByText(/token/i)).toBeNull();
    expect(screen.queryByText(/raw_payload/i)).toBeNull();
  });

  it('supports acknowledge action', async () => {
    mockAuth.mockReturnValue(ctx({ isSupportOrAbove: true }));
    mockGet.mockResolvedValue({ data: {
      alert_number: 'ALT-000001', title: 'DB down', severity: 'critical',
      status: 'open', source_name: 'prom-prod', event_count: 3,
    } });
    mockPost.mockResolvedValue({ data: { detail: 'Alert acknowledged.' } });
    window.location.hash = '#/monitoring/alerts/1';
    render(<AlertDetail alertId="1" />);
    await screen.findByText('ALT-000001');
    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    expect(mockPost).toHaveBeenCalledWith('/monitoring/alerts/1/acknowledge/', {});
  });

  it('handles backend 403 on alert action', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: {
      alert_number: 'ALT-000001', title: 'DB down', severity: 'critical',
      status: 'open', source_name: 'prom-prod', event_count: 3,
    } });
    const err = new Error('Permission denied.');
    mockPost.mockRejectedValue(err);
    window.location.hash = '#/monitoring/alerts/1';
    render(<AlertDetail alertId="1" />);
    await screen.findByText('ALT-000001');
    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    await screen.findByText(/Permission denied/);
  });

  it('does not call registered-but-unimplemented alert sub-actions', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: {
      alert_number: 'ALT-000001', title: 'DB down', severity: 'critical',
      status: 'open', source_name: 'prom-prod', event_count: 3,
    } });
    render(<AlertDetail alertId="1" />);
    await screen.findByText('ALT-000001');
    for (const suffix of ['/ticket/', '/events/', '/history/', '/create-ticket/', '/update-ticket/']) {
      expect(mockGet).not.toHaveBeenCalledWith(expect.stringContaining(suffix));
      expect(mockPost).not.toHaveBeenCalledWith(expect.stringContaining(suffix), expect.anything());
    }
  });

  it('handles backend 404 on alert retrieve', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    const err = new Error('Not Found');
    mockGet.mockRejectedValue(err);
    window.location.hash = '#/monitoring/alerts/999';
    render(<AlertDetail alertId="999" />);
    await screen.findByText(/Not Found/);
  });
});

describe('SourceManagement — supported actions only', () => {
  it('denies non-staff', () => {
    mockAuth.mockReturnValue(ctx({}));
    render(<SourceManagement />);
    expect(screen.getByText(/do not have permission/)).toBeTruthy();
  });

  it('lists sources from supported API', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true, isStaff: true }));
    mockGet.mockResolvedValue({ data: [
      { id: 1, name: 'Prometheus', code: 'prom-1', source_type: 'prometheus_alertmanager', status: 'active', health_status: 'healthy', is_active: true },
    ] });
    render(<SourceManagement />);
    await screen.findByText('Prometheus');
    expect(screen.getByText('Sources')).toBeTruthy();
  });

  it('shows explicit create/edit unsupported state, no create form', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: [] });
    render(<SourceManagement />);
    expect(screen.getByText(/Source creation and editing are not available/)).toBeTruthy();
    expect(screen.queryByText(/Add source/i)).toBeNull();
  });

  it('renders only source serializer fields in detail', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    const source = { id: 1, name: 'Prometheus', code: 'prom-1', source_type: 'prometheus_alertmanager', status: 'active', health_status: 'healthy', is_active: true };
    mockGet
      .mockResolvedValueOnce({ data: [source] })
      .mockResolvedValueOnce({ data: { ...source, secret_hash: 'hash-value', previous_secret_valid_until: '2026-01-01T00:00:00Z', allowed_ip_networks: ['10.0.0.0/8'] } });
    render(<SourceManagement />);
    fireEvent.click(await screen.findByText('Prometheus'));
    await screen.findByText('Read-only fields returned by the source serializer.');
    expect(screen.queryByText('Grace period until')).toBeNull();
    expect(screen.queryByText('Allowlist (config)')).toBeNull();
    expect(screen.queryByText('hash-value')).toBeNull();
  });

  it('does not issue source create or edit requests', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: [] });
    render(<SourceManagement />);
    await screen.findByText(/Source creation and editing are not available/);
    expect(mockPost).not.toHaveBeenCalledWith('/monitoring/sources/', expect.anything());
    expect(mockGet).not.toHaveBeenCalledWith(expect.stringContaining('/monitoring/sources/1/'));
  });

  it('enables/disables source via supported endpoints', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: [
      { id: 1, name: 'Prometheus', code: 'prom-1', source_type: 'prometheus_alertmanager', status: 'active', health_status: 'healthy', is_active: true },
    ] });
    mockPost.mockResolvedValue({ data: { detail: 'Source disabled.' } });
    render(<SourceManagement />);
    await screen.findByText('Prometheus');
    fireEvent.click(screen.getByRole('button', { name: 'Disable' }));
    expect(mockPost).toHaveBeenCalledWith('/monitoring/sources/1/disable/');
  });

  it('shows rotated secret once in memory, dismiss removes it', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: [
      { id: 1, name: 'Prometheus', code: 'prom-1', source_type: 'prometheus_alertmanager', status: 'active', health_status: 'healthy', is_active: true },
    ] });
    mockPost.mockResolvedValue({ data: { detail: 'Secret rotated.', secret: 'abc123secret' } });
    render(<SourceManagement />);
    await screen.findByText('Prometheus');
    fireEvent.click(screen.getByRole('button', { name: 'Rotate secret' }));
    await screen.findByText('abc123secret');
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByText('abc123secret')).toBeNull();
  });
});

describe('PolicyManagement — unsupported CRUD, preview only', () => {
  it('denies non-admin', () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true, isAdmin: false }));
    render(<PolicyManagement />);
    expect(screen.getByText(/permission/)).toBeTruthy();
  });

  it('shows policy administration API not available state', () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    render(<PolicyManagement />);
    expect(screen.getByText(/Policy administration API not available/)).toBeTruthy();
    expect(screen.getByText(/not registered on the backend/)).toBeTruthy();
  });

  it('disables save and delete actions', () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    render(<PolicyManagement />);
    const save = screen.getByRole('button', { name: /Save \(backend API missing\)/ });
    const del = screen.getByRole('button', { name: /Delete \(backend API missing\)/ });
    expect(save.disabled).toBe(true);
    expect(del.disabled).toBe(true);
  });

  it('does not issue policy CRUD requests', () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    render(<PolicyManagement />);
    expect(mockGet).not.toHaveBeenCalled();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('does not store policy state in local storage', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    render(<PolicyManagement />);
    expect(setItem).not.toHaveBeenCalledWith(expect.stringContaining('policy'), expect.anything());
    setItem.mockRestore();
  });
});

describe('LinkedTicketPanel — read-only, unsupported lookup', () => {
  it('shows linked ticket unavailable state', () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    render(<LinkedTicketPanel alertId="1" />);
    expect(screen.getByText(/Linked ticket lookup is not available/)).toBeTruthy();
  });

  it('does not call ticket endpoint', () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    render(<LinkedTicketPanel alertId="1" />);
    expect(mockGet).not.toHaveBeenCalledWith(expect.stringContaining('/ticket/'));
  });

  it('links to existing ticket route when id known externally', () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    render(<LinkedTicketPanel alertId="1" ticketId="42" />);
    const link = screen.getByRole('link', { name: /Ticket #42/ });
    expect(link).toBeTruthy();
    expect(link.getAttribute('href')).toBe('#/tickets/42');
  });
});

describe('Permission verification — all roles', () => {
  it('System Admin accesses supported views', () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true, isStaff: true, isSupportOrAbove: true }));
    render(<SourceManagement />);
    expect(screen.queryByText(/do not have permission/)).toBeNull();
  });

  it('IT Manager can view alerts', () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true, isSupportOrAbove: true, isAdmin: false }));
    render(<AlertList />);
    expect(screen.queryByText(/do not have permission/)).toBeNull();
  });

  it('IT Support can view alert detail and act', () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true, isSupportOrAbove: true, isAdmin: false }));
    mockGet.mockResolvedValue({ data: {
      alert_number: 'ALT-000001', title: 'DB down', severity: 'critical',
      status: 'open', source_name: 'prom-prod', event_count: 3,
    } });
    render(<AlertDetail alertId="1" />);
    expect(screen.queryByText(/do not have permission/)).toBeNull();
  });

  it('Employee denied', () => {
    mockAuth.mockReturnValue(ctx({ isStaff: false, isAdmin: false, isSupportOrAbove: false }));
    render(<MonitoringOverview />);
    expect(screen.getByText(/do not have permission/)).toBeTruthy();
  });

  it('Inactive/unknown role fails closed', () => {
    mockAuth.mockReturnValue(ctx({}));
    render(<MonitoringOverview />);
    expect(screen.getByText(/permission/)).toBeTruthy();
    cleanup();
    render(<SourceManagement />);
    expect(screen.getByText(/permission/)).toBeTruthy();
    cleanup();
    render(<PolicyManagement />);
    expect(screen.getByText(/permission/)).toBeTruthy();
  });

  it('Employee role fails closed even when route flags are set', () => {
    mockAuth.mockReturnValue({ ...ctx({}), role: 'employee', isAdmin: true, isStaff: true, isSupportOrAbove: true });
    render(<MonitoringOverview />);
    expect(screen.getByText(/permission/)).toBeTruthy();
    cleanup();
    render(<SourceManagement />);
    expect(screen.getByText(/permission/)).toBeTruthy();
    cleanup();
    render(<PolicyManagement />);
    expect(screen.getByText(/permission/)).toBeTruthy();
  });

  it('Inactive admin fails closed', () => {
    mockAuth.mockReturnValue({ ...ctx({}), role: 'system_admin', user: { is_active: false }, isAdmin: true, isStaff: true, isSupportOrAbove: true });
    render(<SourceManagement />);
    expect(screen.getByText(/permission/)).toBeTruthy();
    cleanup();
    render(<PolicyManagement />);
    expect(screen.getByText(/permission/)).toBeTruthy();
  });

  it('Unknown role fails closed even when route flags are set', () => {
    mockAuth.mockReturnValue({ ...ctx({}), role: 'contractor', isAdmin: true, isStaff: true, isSupportOrAbove: true });
    render(<MonitoringOverview />);
    expect(screen.getByText(/permission/)).toBeTruthy();
    cleanup();
    render(<AlertDetail alertId="1" />);
    expect(screen.getByText(/permission/)).toBeTruthy();
  });
});

describe('Integration manifest consistency', () => {
  it('manifest lists only supported or gap-documented routes', () => {
    expect(manifest.version).toBe(2);
    expect(Array.isArray(manifest.routes)).toBe(true);
    for (const route of manifest.routes) {
      expect(route.path).toBeDefined();
      expect(route.permissionGuard).toBeDefined();
      expect(route.supportStatus).toBeDefined();
      expect(Array.isArray(route.backendEndpoints)).toBe(true);
    }
    const missing = manifest.routes.filter((r) => r.supportStatus === 'backend-api-missing');
    expect(missing.length).toBeGreaterThan(0);
  });
});
