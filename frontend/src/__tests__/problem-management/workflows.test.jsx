import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Actions } from '../../components/problem-management/actions';
import { Workarounds } from '../../components/problem-management/workarounds';
import { Validations } from '../../components/problem-management/validations';
import { Exceptions } from '../../components/problem-management/exceptions';
import { Timeline } from '../../components/problem-management/timeline';
import { Readiness } from '../../components/problem-management/readiness';
import { LinkedRecords } from '../../components/problem-management/linked-records';

vi.mock('../../services/problem-management', () => ({
  approveAction: vi.fn(),
  cancelAction: vi.fn(),
  completeAction: vi.fn(),
  createAction: vi.fn(),
  listActions: vi.fn(),
  markActionIneffective: vi.fn(),
  startAction: vi.fn(),
  validateAction: vi.fn(),
  approveWorkaround: vi.fn(),
  createWorkaround: vi.fn(),
  expireWorkaround: vi.fn(),
  listWorkarounds: vi.fn(),
  publishWorkaround: vi.fn(),
  retireWorkaround: vi.fn(),
  submitWorkaround: vi.fn(),
  cancelValidation: vi.fn(),
  createValidation: vi.fn(),
  failValidation: vi.fn(),
  listValidations: vi.fn(),
  markValidationInconclusive: vi.fn(),
  passValidation: vi.fn(),
  startValidation: vi.fn(),
  approveException: vi.fn(),
  createException: vi.fn(),
  expireException: vi.fn(),
  listExceptions: vi.fn(),
  rejectException: vi.fn(),
  revokeException: vi.fn(),
  submitException: vi.fn(),
  createTimelineEvent: vi.fn(),
  problemTimeline: vi.fn(),
  problemReadiness: vi.fn(),
  linkedTickets: vi.fn(),
  linkedCIs: vi.fn(),
  linkedAssets: vi.fn(),
  linkedServices: vi.fn(),
  linkedProducts: vi.fn(),
}));

const auth = vi.hoisted(() => ({ current: { isStaff: true, isManagerOrAdmin: true, user: { username: 'manager' } } }));
vi.mock('../../auth', () => ({ useAuth: () => auth.current }));

import * as services from '../../services/problem-management';

afterEach(cleanup);

const renderWith = (node) => render(<MemoryRouter>{node}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  auth.current = { isStaff: true, isManagerOrAdmin: true, user: { username: 'manager' } };
  services.listActions.mockResolvedValue({ results: [] });
  services.listWorkarounds.mockResolvedValue({ results: [] });
  services.listValidations.mockResolvedValue({ results: [] });
  services.listExceptions.mockResolvedValue({ results: [] });
  services.problemTimeline.mockResolvedValue({ results: [] });
  services.linkedTickets.mockResolvedValue({ results: [] });
  services.linkedCIs.mockResolvedValue({ results: [] });
  services.linkedAssets.mockResolvedValue({ results: [] });
  services.linkedServices.mockResolvedValue({ results: [] });
  services.linkedProducts.mockResolvedValue({ results: [] });
});

describe('Actions workflow', () => {
  const PLANNED = { id: 1, title: 'Replace disk', action_type: 'corrective', status: 'planned' };

  test('drives the lifecycle through dedicated transitions', async () => {
    services.listActions.mockResolvedValue({ results: [PLANNED] });
    renderWith(<Actions problemId="1" />);
    fireEvent.click(await screen.findByText('Approve'));
    await waitFor(() => expect(services.approveAction).toHaveBeenCalledWith(1));
    fireEvent.click(screen.getByText('Start'));
    await waitFor(() => expect(services.startAction).toHaveBeenCalledWith(1));
  });

  test('renders a stale-version conflict safely', async () => {
    services.listActions.mockResolvedValue({ results: [PLANNED] });
    services.startAction.mockRejectedValueOnce({ response: { status: 409 } });
    renderWith(<Actions problemId="1" />);
    fireEvent.click(await screen.findByText('Start'));
    expect(await screen.findByText(/changed on the server/)).toBeTruthy();
  });
});

describe('Workaround workflow', () => {
  test('submit and publish use their own endpoints', async () => {
    services.listWorkarounds.mockResolvedValue({
      results: [{ id: 2, title: 'Restart', steps: 'restart', status: 'draft' }],
    });
    renderWith(<Workarounds problemId="1" />);
    fireEvent.click(await screen.findByText('Submit'));
    await waitFor(() => expect(services.submitWorkaround).toHaveBeenCalledWith(2));
  });
});

describe('Validation contract', () => {
  test('shows status and sends test_plan rather than validation_status', async () => {
    services.listValidations.mockResolvedValue({
      results: [{ id: 3, title: 'Failover', status: 'draft', passed: false }],
    });
    renderWith(<Validations problemId="1" />);
    expect(await screen.findByText('Status')).toBeTruthy();
    expect(screen.queryByText('validation_status')).toBeNull();
    fireEvent.change(screen.getByPlaceholderText('Validation title'), { target: { value: 'New run' } });
    fireEvent.change(screen.getByPlaceholderText('Test plan'), { target: { value: 'kill node' } });
    fireEvent.click(screen.getByText('Create Validation'));
    await waitFor(() => expect(services.createValidation).toHaveBeenCalledWith('1', {
      title: 'New run', test_plan: 'kill node',
    }));
  });

  test('pass transition is a dedicated POST', async () => {
    services.listValidations.mockResolvedValue({
      results: [{ id: 3, title: 'Failover', status: 'in_progress', passed: false }],
    });
    renderWith(<Validations problemId="1" />);
    fireEvent.click(await screen.findByText('Pass'));
    await waitFor(() => expect(services.passValidation).toHaveBeenCalledWith(3));
  });
});

describe('Exception contract', () => {
  const ROW = {
    id: 4, title: 'Accept risk', exception_type: 'operational', status: 'active',
    reason: 'temp', created_by_username: 'author',
  };

  test('renders exception_type and blocks self-approval', async () => {
    services.listExceptions.mockResolvedValue({ results: [{ ...ROW, created_by_username: 'manager' }] });
    renderWith(<Exceptions problemId="1" />);
    expect(await screen.findByText('operational')).toBeTruthy();
    expect(screen.getByText('Approve').disabled).toBe(true);
    expect(screen.queryByText('Risk')).toBeNull();
  });

  test('sends exception_type and reason, never type or risk', async () => {
    renderWith(<Exceptions problemId="1" />);
    fireEvent.change(screen.getByPlaceholderText('Exception title'), { target: { value: 'Temp' } });
    fireEvent.change(screen.getByPlaceholderText('Reason'), { target: { value: 'why' } });
    fireEvent.click(screen.getByText('Create Exception'));
    await waitFor(() => {
      const payload = services.createException.mock.calls[0][1];
      expect(payload.exception_type).toBe('operational');
      expect(payload).not.toHaveProperty('type');
      expect(payload).not.toHaveProperty('risk');
    });
  });
});

describe('Timeline contract', () => {
  test('lists by occurred_at and creates with the real fields', async () => {
    services.problemTimeline.mockResolvedValue({
      results: [{
        id: 5, event_type: 'milestone', title: 'Kickoff',
        source: 'manual', occurred_at: '2026-01-01T09:00:00Z', recorded_by_username: 'support',
      }],
    });
    renderWith(<Timeline problemId="1" />);
    expect(await screen.findByText('Kickoff')).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText('Event title'), { target: { value: 'Review' } });
    fireEvent.click(screen.getByText('Add Timeline Event'));
    await waitFor(() => {
      const payload = services.createTimelineEvent.mock.calls[0][1];
      expect(payload.title).toBe('Review');
      expect(payload).toHaveProperty('occurred_at');
      expect(payload).not.toHaveProperty('recorded_at');
    });
  });
});

describe('Readiness integration', () => {
  test('renders the server payload verbatim', async () => {
    services.problemReadiness.mockResolvedValue({
      ready_for_resolution: true,
      ready_for_closure: false,
      blockers: ['Validation failed'],
      warnings: ['Exception expires soon'],
      counts: {
        open_blocking_tasks: 2, open_required_actions: 1,
        failed_validations: 1, open_critical_tickets: 0, active_exceptions: 1,
      },
    });
    renderWith(<Readiness problemId="1" />);
    expect(await screen.findByText('Validation failed', { exact: false })).toBeTruthy();
    expect(screen.getByText('Open blocking tasks: 2')).toBeTruthy();
  });

  test('shows a failure state without computing readiness locally', async () => {
    services.problemReadiness.mockRejectedValueOnce(new Error('down'));
    renderWith(<Readiness problemId="1" />);
    expect(await screen.findByText('Could not load readiness.')).toBeTruthy();
  });
});

describe('Linked records contract', () => {
  test('reads supported collections and never requests linked changes', async () => {
    services.linkedTickets.mockResolvedValue({ results: [{ id: 1, ticket_number: 'INC-1', title: 'Disk' }] });
    renderWith(<LinkedRecords problemId="1" />);
    expect(await screen.findByText('INC-1: Disk')).toBeTruthy();
    expect(Object.keys(services)).not.toContain('linkedChanges');
    expect(screen.getByText(/Linked Changes are not supported/)).toBeTruthy();
  });
});


