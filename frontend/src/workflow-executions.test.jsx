import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({ useAuth: (...args) => mockAuth(...args) }));

import Workflow from './workflow';

const RULE = {
  id: 1,
  name: 'Auto note',
  trigger: 'ticket_created',
  trigger_display: 'Ticket Created',
  is_enabled: true,
  conditions: { priority: 'high' },
  actions: [{ type: 'note', text: 'Auto triage' }],
};

const EXECUTION = {
  id: 9,
  rule: 1,
  rule_name: 'Auto note',
  ticket: 7,
  ticket_title: 'Broken laptop',
  success: false,
  detail: 'ValueError: user #99 not found or inactive',
  created_at: '2024-01-03T10:00:00Z',
};

const PAGE_1 = {
  results: [EXECUTION],
  count: 2,
  next: '/workflow/rule-executions/?page=2',
  previous: null,
};
const PAGE_2 = {
  results: [{ ...EXECUTION, id: 10, success: true, detail: 'note #2 created' }],
  count: 2,
  next: null,
  previous: '/workflow/rule-executions/',
};

function staff() {
  mockAuth.mockReturnValue({
    isStaff: true, isAdmin: true, user: { id: 1, role: 'system_admin' },
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  staff();
  mockGet.mockImplementation(async (url) => {
    const u = String(url);
    if (u === '/workflow/automation-rules/') {
      return { data: { results: [RULE], count: 1, next: null, previous: null } };
    }
    if (u === '/workflow/automation-rules/1/') return { data: RULE };
    if (u === '/workflow/rule-executions/9/') return { data: EXECUTION };
    if (u.includes('page=2')) return { data: PAGE_2 };
    if (u.startsWith('/workflow/rule-executions/')) return { data: PAGE_1 };
    return { data: { results: [], count: 0, next: null, previous: null } };
  });
});

afterEach(() => cleanup());

describe('execution history', () => {
  it('filters by rule and status using the API query parameters', async () => {
    render(<Workflow tab="executions" />);
    await screen.findByRole('link', { name: 'Auto note' });

    fireEvent.change(screen.getByLabelText('Filter executions by rule'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('Filter executions by status'), { target: { value: 'failure' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));

    await waitFor(() => {
      const urls = mockGet.mock.calls.map(([url]) => String(url));
      expect(urls.some((u) => u.includes('rule=1') && u.includes('status=failure'))).toBe(true);
    });
  });

  it('sends an inclusive date range (end date covers the whole day)', async () => {
    render(<Workflow tab="executions" />);
    await screen.findByRole('link', { name: 'Auto note' });

    fireEvent.change(screen.getByLabelText('Execution start date'), { target: { value: '2024-01-01' } });
    fireEvent.change(screen.getByLabelText('Execution end date'), { target: { value: '2024-01-31' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));

    await waitFor(() => {
      const urls = mockGet.mock.calls.map(([url]) => decodeURIComponent(String(url)));
      expect(urls.some((u) => u.includes('date_from=2024-01-01')
        && u.includes('date_to=2024-01-31T23:59:59'))).toBe(true);
    });
  });

  it('paginates through next and previous links', async () => {
    render(<Workflow tab="executions" />);
    await screen.findByText('ValueError: user #99 not found or inactive');

    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    await waitFor(() => expect(
      mockGet.mock.calls.some(([url]) => String(url).includes('page=2')),
    ).toBe(true));
    expect(await screen.findByText('note #2 created')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /Prev/ }));
    await waitFor(() => expect(
      mockGet.mock.calls.some(([url]) => String(url) === '/workflow/rule-executions/'),
    ).toBe(true));
  });

  it('shows execution details with rule, trigger, result and failure information', async () => {
    render(<Workflow executionId="9" />);
    await screen.findByRole('heading', { name: 'Execution #9' });

    expect(screen.getByText('#7 Broken laptop')).toBeTruthy();
    expect(screen.getByText('Ticket Created')).toBeTruthy();
    expect(screen.getAllByText('Failed').length).toBeGreaterThan(0);
    expect(screen.getByText('Failure information')).toBeTruthy();
    expect(screen.getByText(/user #99 not found or inactive/)).toBeTruthy();
    expect(screen.getByText('Priority = High')).toBeTruthy();
    expect(screen.getByText('Add internal note: “Auto triage”')).toBeTruthy();
  });

  it('shows an empty state when filters match nothing', async () => {
    mockGet.mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/workflow/automation-rules/') return { data: { results: [RULE] } };
      if (u.startsWith('/workflow/rule-executions/')) {
        return { data: { results: [], count: 0, next: null, previous: null } };
      }
      return { data: { results: [] } };
    });
    render(<Workflow tab="executions" />);
    expect(await screen.findByText('No executions match.')).toBeTruthy();
  });

  it('shows an error state with retry when history cannot load', async () => {
    mockGet.mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/workflow/automation-rules/') return { data: { results: [RULE] } };
      throw { response: { status: 500, data: { detail: 'Server exploded' } } };
    });
    render(<Workflow tab="executions" />);
    expect(await screen.findByText('Server exploded')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  });
});
