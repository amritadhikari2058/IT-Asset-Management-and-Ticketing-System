import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
    delete: (...args) => mockDelete(...args),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { Monitoring } from '../../pages/monitoring/Monitoring';

function ctx(over = {}) {
  return { isAdmin: false, isStaff: false, ...over };
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '#/monitoring';
});

afterEach(() => cleanup());

describe('Monitoring page', () => {
  it('denies access to employees', () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: false, isStaff: false }));
    render(<Monitoring />);
    expect(screen.getByText('Access restricted')).toBeTruthy();
  });

  it('renders the health dashboard for IT staff', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: false, isStaff: true }));
    mockGet.mockResolvedValue({ data: {
      overall: 'degraded',
      components: {
        backend: { state: 'healthy', diagnostic: 'Django application is responding.', evaluated_at: '2026-01-01T08:00:00Z' },
        database: { state: 'healthy', diagnostic: 'Database reachable.', evaluated_at: '2026-01-01T08:00:00Z' },
        redis: { state: 'not_configured', diagnostic: 'Redis/cache not configured.', evaluated_at: '2026-01-01T08:00:00Z' },
      },
    } });
    render(<Monitoring />);
    await screen.findByText('System Health');
    await screen.findByText('Degraded');
    await screen.findByText('database', { timeout: 5000 });
    await screen.findByText('Not configured', { timeout: 5000 });
  });

  it('shows component health history', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: [{ id: 1, component: 'database', state: 'healthy', diagnostic: 'ok', evaluated_at: '2026-01-01T08:00:00Z', last_successful_at: '2026-01-01T08:00:00Z', last_failure_at: null }] });
    window.location.hash = '#/monitoring/health';
    render(<Monitoring />);
    await screen.findByText('Component health history');
    await screen.findByText('database');
    await screen.findByText('Healthy');
  });

  it('lists background tasks', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: [{ id: 1, task_name: 'common.tasks.run_scheduled_reports', status: 'succeeded', started_at: '2026-01-01T08:00:00Z', finished_at: '2026-01-01T08:01:00Z', success: true, error_summary: '' }] });
    window.location.hash = '#/monitoring/tasks';
    render(<Monitoring />);
    await screen.findByText('Background tasks');
    expect(screen.getByText('common.tasks.run_scheduled_reports')).toBeTruthy();
    expect(screen.getByText('Succeeded')).toBeTruthy();
  });

  it('retries a failed task', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: [{ id: 1, task_name: 'common.tasks.run_scheduled_reports', status: 'failed', started_at: '2026-01-01T08:00:00Z', finished_at: '2026-01-01T08:01:00Z', success: false, error_summary: 'boom' }] });
    mockPost.mockResolvedValue({ data: { retried: true, task_name: 'common.tasks.run_scheduled_reports' } });
    window.location.hash = '#/monitoring/tasks';
    render(<Monitoring />);
    await screen.findByText('Background tasks');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('Background tasks');
    expect(mockPost).toHaveBeenCalledWith('/common/tasks/retry_task/', { task_name: 'common.tasks.run_scheduled_reports' });
  });

  it('lists application errors', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: [{ id: 1, title: 'boom', component: 'api', severity: 'high', occurrence_count: 2, last_occurred: '2026-01-01T08:00:00Z', resolved: false }] });
    window.location.hash = '#/monitoring/errors';
    render(<Monitoring />);
    await screen.findByText('Application errors');
    expect(screen.getByText('boom')).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();
  });

  it('resolves an error', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: [{ id: 9, title: 'boom', component: 'api', severity: 'high', occurrence_count: 1, last_occurred: '2026-01-01T08:00:00Z', resolved: false }] });
    mockPost.mockResolvedValue({ data: { id: 9, resolved: true } });
    window.location.hash = '#/monitoring/errors';
    render(<Monitoring />);
    await screen.findByText('Application errors');
    fireEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    expect(mockPost).toHaveBeenCalledWith('/common/errors/9/resolve/');
  });

  it('lists alerts and acknowledges', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: [{ id: 4, title: 'DB down', severity: 'critical', status: 'open', occurrence_count: 1, last_occurred: '2026-01-01T08:00:00Z', acknowledged: false, resolved: false }] });
    mockPost.mockResolvedValue({ data: { id: 4, acknowledged: true, status: 'acknowledged' } });
    window.location.hash = '#/monitoring/alerts';
    render(<Monitoring />);
    await screen.findByText('Operational alerts');
    expect(screen.getByText('DB down')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    expect(mockPost).toHaveBeenCalledWith('/common/alerts/4/acknowledge/');
  });

  it('creates an incident', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true }));
    mockGet.mockResolvedValue({ data: [] });
    mockPost.mockResolvedValue({ data: { id: 2, title: 'Outage', status: 'open' } });
    window.location.hash = '#/monitoring/incidents';
    render(<Monitoring />);
    await screen.findByText('Operational incidents');
    fireEvent.click(screen.getByRole('button', { name: '+ New incident' }));
    fireEvent.change(screen.getByLabelText(/Title/), { target: { value: 'Outage' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(mockPost).toHaveBeenCalledWith('/common/incidents/', {
      title: 'Outage', description: '', severity: 'warning', affected_component: '', assigned_to: null, internal_notes: '',
    });
  });

  it('shows API performance', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: { minutes: 60, endpoints: [{ endpoint: '/tickets/', request_count: 10, error_count: 0, error_rate: 0, avg_response_ms: 45, max_response_ms: 120, slow_request_count: 0 }] } });
    window.location.hash = '#/monitoring/performance';
    render(<Monitoring />);
    await screen.findByText('API performance');
    expect(screen.getByText('/tickets/')).toBeTruthy();
    expect(screen.getByText('10')).toBeTruthy();
  });

  it('shows email and storage health', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: { components: {
      email: { state: 'healthy', diagnostic: 'SMTP configured.', evaluated_at: '2026-01-01T08:00:00Z' },
      storage: { state: 'healthy', diagnostic: 'Storage probe succeeded.', evaluated_at: '2026-01-01T08:00:00Z', details: { storage_total_bytes: 1073741824, storage_used_bytes: 500000000, storage_free_bytes: 573741824 } },
    } } });
    window.location.hash = '#/monitoring/email-storage';
    render(<Monitoring />);
    await screen.findByText('Email & storage health');
    await screen.findByText('Email');
    const healthy = await screen.findAllByText('Healthy');
    expect(healthy.length).toBeGreaterThanOrEqual(1);
  });
  it('shows notification outbox statistics and events to IT staff', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockResolvedValue({ data: {
      stats: { total: 3, pending: 1, retry: 0, processing: 0, delivered: 1, failed: 1, cancelled: 0, expired_claims: 0, delivered_last_24h: 1, failed_last_24h: 1, oldest_pending_age_seconds: 120 },
      events: [{ id: 'event-1', event_type: 'ticket.created', channel: 'email', recipient_email: 'employee@example.com', status: 'failed', attempts: 2, max_attempts: 3, created_at: '2026-01-01T08:00:00Z', last_error: 'SMTP unavailable' }],
    } });
    window.location.hash = '#/monitoring/notification-outbox';
    render(<Monitoring />);

    await screen.findByText('Notification Outbox');
    expect(screen.getByText('employee@example.com')).toBeTruthy();
    expect(screen.getByText('ticket.created')).toBeTruthy();
    expect(screen.getByText('SMTP unavailable')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Inspect' })).toBeNull();
    expect(mockGet).toHaveBeenCalledWith('/common/notification-outbox/', { params: { limit: 50 } });
  });

  it('allows System Admin to inspect an event payload on demand', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true, isStaff: true }));
    mockGet
      .mockResolvedValueOnce({ data: {
        stats: { total: 1 },
        events: [{ id: 'event-2', event_type: 'ticket.created', channel: 'email', recipient_email: 'employee@example.com', status: 'delivered', attempts: 1, max_attempts: 3 }],
      } })
      .mockResolvedValueOnce({ data: {
        id: 'event-2', event_type: 'ticket.created', channel: 'email',
        recipient_email: 'employee@example.com', status: 'delivered',
        attempts: 1, max_attempts: 3, payload: { subject: 'Ticket created' },
      } });
    window.location.hash = '#/monitoring/notification-outbox';
    render(<Monitoring />);

    fireEvent.click(await screen.findByRole('button', { name: 'Inspect' }));
    await screen.findByText('Notification event inspection');
    expect(screen.getByText(/Ticket created/)).toBeTruthy();
    expect(mockGet).toHaveBeenLastCalledWith('/common/notification-outbox/event-2/inspect/');
  });

  it('allows System Admin to retry a failed notification event', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true, isStaff: true }));
    mockGet.mockResolvedValue({ data: {
      stats: { total: 1, failed: 1 },
      events: [{ id: 'event-3', event_type: 'ticket.created', channel: 'email', status: 'failed', attempts: 3, max_attempts: 3 }],
    } });
    mockPost.mockResolvedValue({ data: { retried: true, id: 'event-3', status: 'pending' } });
    window.location.hash = '#/monitoring/notification-outbox';
    render(<Monitoring />);

    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    expect(mockPost).toHaveBeenCalledWith('/common/notification-outbox/event-3/retry/');
  });

  it('requires a reason when System Admin cancels a pending event', async () => {
    mockAuth.mockReturnValue(ctx({ isAdmin: true, isStaff: true }));
    mockGet.mockResolvedValue({ data: {
      stats: { total: 1, pending: 1 },
      events: [{ id: 'event-4', event_type: 'ticket.created', channel: 'email', status: 'pending', attempts: 0, max_attempts: 3 }],
    } });
    mockPost.mockResolvedValue({ data: { cancelled: true, id: 'event-4', status: 'cancelled' } });
    window.location.hash = '#/monitoring/notification-outbox';
    render(<Monitoring />);

    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    const confirmButton = screen.getByRole('button', { name: 'Confirm cancellation' });
    expect(confirmButton.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText('Explain why this notification is being cancelled.'), {
      target: { value: 'Duplicate notification' },
    });
    expect(confirmButton.disabled).toBe(false);
    fireEvent.click(confirmButton);

    expect(mockPost).toHaveBeenCalledWith('/common/notification-outbox/event-4/cancel/', {
      reason: 'Duplicate notification',
    });
  });
});
