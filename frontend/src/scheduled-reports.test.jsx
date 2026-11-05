import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
    delete: (...args) => mockDelete(...args),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { ScheduledReports } from './scheduled-reports';

function ctx(over = {}) {
  return { isStaff: false, ...over };
}

const SR = {
  id: 1, saved_report: 5, saved_report_name: 'HW weekly', saved_report_type: 'ticket_category',
  schedule: 'weekly', recipients: ['ops@example.com'], format: 'csv', enabled: true, next_run_at: null,
};

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
});

afterEach(() => cleanup());

describe('Scheduled reports page', () => {
  it('restricts access to non-staff', () => {
    mockAuth.mockReturnValue(ctx({ isStaff: false }));
    mockGet.mockResolvedValue({ data: [] });
    render(<ScheduledReports />);
    expect(screen.getByText('Scheduled report management is restricted to IT staff and admins.')).toBeTruthy();
  });

  it('loads and lists scheduled reports for staff', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockImplementation((url) => {
      if (url.includes('scheduled-reports/')) {
        return Promise.resolve({ data: { results: [SR], count: 1, next: null, previous: null } });
      }
      return Promise.resolve({ data: [] });
    });
    render(<ScheduledReports />);
    await screen.findByText('HW weekly');
    const table = screen.getByRole('table');
    expect(table.textContent).toContain('HW weekly');
    expect(table.textContent).toContain('ticket_category');
    expect(table.textContent).toContain('weekly');
    expect(table.textContent).toContain('CSV');
    expect(table.textContent).toContain('ops@example.com');
    expect(table.textContent).toContain('On');
  });

  it('creates a new schedule', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockImplementation((url) => {
      if (url.includes('saved-reports/')) {
        return Promise.resolve({ data: [{ id: 5, name: 'HW weekly', report_type: 'ticket_category' }] });
      }
      return Promise.resolve({ data: { results: [], count: 0, next: null, previous: null } });
    });
    mockPost.mockResolvedValueOnce({ data: { id: 1, saved_report_name: 'HW weekly' } });
    render(<ScheduledReports />);
    await screen.findByText('No scheduled reports yet.');
    fireEvent.click(screen.getByRole('button', { name: '+ New schedule' }));
    fireEvent.change(screen.getByLabelText(/Saved report/), { target: { value: '5' } });
    fireEvent.change(screen.getByRole('textbox', { name: /Recipients/ }), { target: { value: 'ops@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create schedule' }));
    await screen.findByText('Schedule "HW weekly" saved.');
    expect(mockPost).toHaveBeenCalledWith('/common/scheduled-reports/', {
      saved_report: 5, schedule: 'weekly', recipients: ['ops@example.com'], format: 'csv', enabled: true,
    });
  });

  it('disables a schedule', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockImplementation((url) => {
      if (url.includes('scheduled-reports/')) {
        return Promise.resolve({ data: { results: [{ ...SR }], count: 1, next: null, previous: null } });
      }
      return Promise.resolve({ data: [] });
    });
    mockPatch.mockResolvedValueOnce({ data: {} });
    render(<ScheduledReports />);
    await screen.findByText('HW weekly');
    fireEvent.click(screen.getByRole('button', { name: 'Disable' }));
    await screen.findByText('Schedule "HW weekly" disabled.');
    expect(mockPatch).toHaveBeenCalledWith('/common/scheduled-reports/1/', { enabled: false });
  });

  it('deletes a schedule', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockImplementation((url) => {
      if (url.includes('scheduled-reports/')) {
        return Promise.resolve({ data: { results: [{ ...SR }], count: 1, next: null, previous: null } });
      }
      return Promise.resolve({ data: [] });
    });
    mockDelete.mockResolvedValueOnce({});
    render(<ScheduledReports />);
    await screen.findByText('HW weekly');
    fireEvent.click(screen.getByRole('button', { name: 'Delete…' }));
    // Confirm in the dialog.
    fireEvent.click(screen.getByRole('button', { name: 'Delete schedule' }));
    await screen.findByText('Schedule "HW weekly" deleted.');
    expect(mockDelete).toHaveBeenCalledWith('/common/scheduled-reports/1/');
  });

  it('retries a failed run', async () => {
    mockAuth.mockReturnValue(ctx({ isStaff: true }));
    mockGet.mockImplementation((url) => {
      if (url.includes('scheduled-report-runs/')) {
        return Promise.resolve({
          data: { results: [{ id: 9, scheduled_report: 1, status: 'failed', started_at: '2026-11-02T08:00:00Z', finished_at: '2026-11-02T08:05:00Z', recipient_count: 1, error_summary: 'SMTPRefused' }] },
        });
      }
      if (url.includes('scheduled-reports/')) {
        return Promise.resolve({ data: { results: [{ ...SR }], count: 1, next: null, previous: null } });
      }
      return Promise.resolve({ data: [] });
    });
    mockPost.mockResolvedValueOnce({ data: { retried: true, scheduled_report: 1 } });
    render(<ScheduledReports />);
    await screen.findByText('HW weekly');
    fireEvent.click(screen.getByRole('button', { name: 'History' }));
    await screen.findByText('Failed');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText(/Retry dispatched/);
    expect(mockPost).toHaveBeenCalledWith('/common/scheduled-report-runs/9/retry/', {}, { headers: { 'Content-Type': 'application/json' } });
  });
});
