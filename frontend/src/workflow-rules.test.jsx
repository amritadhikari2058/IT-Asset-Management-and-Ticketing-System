import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPatch, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPatch: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({ useAuth: (...args) => mockAuth(...args) }));

import Workflow from './workflow';

const RULE = {
  id: 3,
  name: 'Auto assign hardware',
  description: 'Route hardware tickets to support',
  trigger: 'ticket_created',
  trigger_display: 'Ticket Created',
  is_enabled: true,
  conditions: { priority: 'high', category_id: 4 },
  actions: [{ type: 'note', text: 'Auto triage started' }],
  created_by: 1,
  created_by_email: 'admin@x',
  updated_by: 1,
  updated_by_email: 'admin@x',
  created_at: '2024-01-01T10:00:00Z',
  updated_at: '2024-01-02T10:00:00Z',
};

const EXECUTION = {
  id: 9,
  rule: 3,
  rule_name: 'Auto assign hardware',
  ticket: 7,
  ticket_title: 'Broken laptop',
  success: true,
  detail: 'note #1 created',
  created_at: '2024-01-03T10:00:00Z',
};

function paginated(results, count = results.length, next = null, previous = null) {
  return { data: { results, count, next, previous } };
}

function admin() {
  mockAuth.mockReturnValue({
    isStaff: true, isAdmin: true, user: { id: 1, role: 'system_admin' },
  });
}

function support() {
  mockAuth.mockReturnValue({
    isStaff: true, isAdmin: false, user: { id: 2, role: 'it_support' },
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  admin();
  mockGet.mockImplementation(async (url) => {
    const u = String(url);
    if (u === '/workflow/automation-rules/') return paginated([RULE]);
    if (u === '/workflow/automation-rules/3/') return { data: RULE };
    if (u === '/workflow/rule-executions/') return paginated([EXECUTION]);
    return paginated([]);
  });
  mockPatch.mockResolvedValue({ data: { ...RULE, name: 'Renamed rule' } });
  mockPost.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('automation rule editing', () => {
  it('populates every supported field from the existing rule', async () => {
    render(<Workflow ruleId="3" ruleEdit />);
    await screen.findByText('Edit Auto assign hardware');

    expect(screen.getByLabelText(/Rule name/).value).toBe('Auto assign hardware');
    expect(screen.getByLabelText('Description').value).toBe('Route hardware tickets to support');
    expect(screen.getByLabelText(/Trigger/).value).toBe('ticket_created');
    expect(screen.getByLabelText(/Enabled/).checked).toBe(true);
    expect(screen.getByLabelText('Category id').value).toBe('4');
    expect(screen.getByLabelText('Priority').value).toBe('high');
    expect(screen.getByLabelText('Status').value).toBe('');
    expect(screen.getByLabelText('Action 1 type').value).toBe('note');
    expect(screen.getByLabelText('Action 1 text').value).toBe('Auto triage started');
  });

  it('submits all edited trigger, condition and action fields', async () => {
    render(<Workflow ruleId="3" ruleEdit />);
    await screen.findByText('Edit Auto assign hardware');

    fireEvent.change(screen.getByLabelText(/Rule name/), { target: { value: 'Renamed rule' } });
    fireEvent.change(screen.getByLabelText(/Trigger/), { target: { value: 'status_changed' } });
    fireEvent.change(screen.getByLabelText('Priority'), { target: { value: 'critical' } });
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'in_progress' } });
    fireEvent.change(screen.getByLabelText('Category id'), { target: { value: '5' } });

    fireEvent.click(screen.getByRole('button', { name: '+ Add action' }));
    fireEvent.change(screen.getByLabelText('Action 2 type'), { target: { value: 'priority' } });
    fireEvent.change(screen.getByLabelText('Action 2 value'), { target: { value: 'high' } });

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    expect(mockPatch).toHaveBeenCalledWith('/workflow/automation-rules/3/', {
      name: 'Renamed rule',
      description: 'Route hardware tickets to support',
      trigger: 'status_changed',
      is_enabled: true,
      conditions: { category_id: 5, priority: 'critical', status: 'in_progress' },
      actions: [
        { type: 'note', text: 'Auto triage started' },
        { type: 'priority', value: 'high' },
      ],
    });
  });

  it('blocks submission on client-side validation errors', async () => {
    render(<Workflow ruleId="3" ruleEdit />);
    await screen.findByText('Edit Auto assign hardware');

    fireEvent.change(screen.getByLabelText(/Rule name/), { target: { value: '   ' } });
    fireEvent.change(screen.getByLabelText('Action 1 text'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByText('Rule name is required.')).toBeTruthy();
    expect(screen.getByText('Note text is required.')).toBeTruthy();
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('displays backend field validation errors', async () => {
    mockPatch.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { name: ['A rule with this name already exists.'] },
      },
    });
    render(<Workflow ruleId="3" ruleEdit />);
    await screen.findByText('Edit Auto assign hardware');

    fireEvent.change(screen.getByLabelText(/Rule name/), { target: { value: 'Duplicate' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByText('A rule with this name already exists.')).toBeTruthy();
  });

  it('maps nested condition and action validation errors to the form', async () => {
    mockPatch.mockRejectedValueOnce({
      response: {
        status: 400,
        data: {
          conditions: { priority: ['Value must be one of: low, medium.'] },
          actions: { 0: ['note text is required.'] },
        },
      },
    });
    render(<Workflow ruleId="3" ruleEdit />);
    await screen.findByText('Edit Auto assign hardware');

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByText('Value must be one of: low, medium.')).toBeTruthy();
    expect(screen.getByText('note text is required.')).toBeTruthy();
  });
});

describe('automation rule detail', () => {
  it('shows configuration, status and related execution history', async () => {
    render(<Workflow ruleId="3" />);
    await screen.findByRole('heading', { name: 'Auto assign hardware' });

    expect(screen.getAllByText('Enabled').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Ticket Created').length).toBeGreaterThan(0);
    expect(screen.getByText('Priority = High')).toBeTruthy();
    expect(screen.getByText('Category Id = 4')).toBeTruthy();
    expect(screen.getByText('Add internal note: “Auto triage started”')).toBeTruthy();
    expect(screen.getByRole('link', { name: /Broken laptop/ }).getAttribute('href')).toBe('#/tickets/7');
    expect(screen.getAllByText('Success').length).toBeGreaterThan(0);
  });

  it('shows empty execution history without failing the page', async () => {
    mockGet.mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/workflow/automation-rules/3/') return { data: RULE };
      if (u === '/workflow/rule-executions/') return paginated([]);
      return paginated([]);
    });
    render(<Workflow ruleId="3" />);
    expect(await screen.findByText('No executions for this rule yet.')).toBeTruthy();
  });

  it('offers editing only to system admins', async () => {
    support();
    render(<Workflow ruleId="3" />);
    await screen.findByRole('heading', { name: 'Auto assign hardware' });
    expect(screen.queryByRole('link', { name: 'Edit rule' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Disable|Enable/ })).toBeNull();
  });
});
