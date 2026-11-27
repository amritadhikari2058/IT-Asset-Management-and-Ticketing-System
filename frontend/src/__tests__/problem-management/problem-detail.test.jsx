import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ProblemDetail } from '../../pages/problem-management/ProblemDetail';
import {
  approveAction, createAction, getRCA, listActions, listTasks, problemDetail,
  problemRCA, updateProblem,
} from '../../services/problem-management';

afterEach(cleanup);

vi.mock('../../services/problem-management', () => ({
  approveAction: vi.fn(),
  cancelAction: vi.fn(),
  completeAction: vi.fn(),
  createAction: vi.fn(),
  editAction: vi.fn(),
  listActions: vi.fn(),
  listRCAs: vi.fn(),
  markActionIneffective: vi.fn(),
  startAction: vi.fn(),
  validateAction: vi.fn(),
  fiveWhys: vi.fn(),
  getRCA: vi.fn(),
  linkedAssets: vi.fn(),
  linkedCIs: vi.fn(),
  linkedKBs: vi.fn(),
  linkedProducts: vi.fn(),
  linkedServices: vi.fn(),
  linkedTickets: vi.fn(),
  archiveEvidence: vi.fn(),
  createKbLink: vi.fn(),
  deleteKbLink: vi.fn(),
  listEvidence: vi.fn(),
  listExceptions: vi.fn(),
  listTasks: vi.fn(),
  listValidations: vi.fn(),
  listWorkarounds: vi.fn(),
  problemDetail: vi.fn(),
  updateProblem: vi.fn(),
  problemHistory: vi.fn(),
  problemRCA: vi.fn(),
  problemReadiness: vi.fn(),
  rootCauseFactors: vi.fn(),
}));

const authMocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
}));

vi.mock('../../auth', () => ({
  useAuth: authMocks.useAuth,
}));

const PROBLEM = {
  id: 1,
  record_version: 3,
  problem_number: 'PRB-2026-000001',
  title: 'Test Problem',
  status: 'identified',
  priority: 'high',
  owner_username: 'testuser',
  service_name: 'Test Service',
  category_name: 'Test Category',
  environment: 'production',
  timeline_events: [],
  root_cause_analysis: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const renderDetail = () => render(
  <MemoryRouter>
    <ProblemDetail problemId="1" />
  </MemoryRouter>,
);

describe('Problem Detail', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    authMocks.useAuth.mockReturnValue({
      isStaff: true,
      isManagerOrAdmin: true,
      isSupportOrAbove: true,
    });
    problemDetail.mockResolvedValue(PROBLEM);
    updateProblem.mockResolvedValue(PROBLEM);;
    const svc = await import('../../services/problem-management');
    ['fiveWhys', 'linkedAssets', 'linkedCIs', 'linkedProducts', 'linkedServices',
      'linkedTickets', 'linkedKBs', 'listActions', 'listRCAs', 'listEvidence',
      'listExceptions', 'listTasks', 'listValidations', 'listWorkarounds', 'problemHistory',
      'rootCauseFactors'
    ].forEach((name) => {
      svc[name].mockResolvedValue({ results: [] });
    });
    svc.createKbLink.mockResolvedValue({});
    svc.deleteKbLink.mockResolvedValue({});
    svc.problemRCA.mockRejectedValue({ response: { status: 404 } });
    svc.problemReadiness.mockResolvedValue({
      ready_for_resolution: false,
      ready_for_closure: false,
      blockers: [],
      warnings: [],
      counts: {
        open_blocking_tasks: 0,
        open_required_actions: 0,
        failed_validations: 0,
        open_critical_tickets: 0,
        active_exceptions: 0,
      },
    });
  });

  test('renders problem detail overview', async () => {
    renderDetail();
    expect(await screen.findByText('PRB-2026-000001')).toBeTruthy();
    expect(screen.getByText('Test Problem')).toBeTruthy();
  });

  test('renders RCA section', async () => {
    renderDetail();
    expect(await screen.findByText('RCA Workflow')).toBeTruthy();
  });

  test('renders Five Whys section', async () => {
    renderDetail();
    expect(await screen.findByText('Five Whys')).toBeTruthy();
  });

  test('loads and displays the latest RCA from the problem-scoped endpoint', async () => {
    const rca = {
      id: 9,
      problem: 1,
      title: 'Latest RCA',
      description: 'Confirmed cause',
      status: 'in_review',
      version: 2,
      created_by_username: 'author',
    };
    problemRCA.mockResolvedValue(rca);
    getRCA.mockResolvedValue(rca);

    renderDetail();

    expect(await screen.findByText('Title: Latest RCA')).toBeTruthy();
    expect(screen.getAllByLabelText('Description').some((el) => el.value === 'Confirmed cause'))
      .toBe(true);
    expect(problemRCA).toHaveBeenCalledWith('1');
    expect(getRCA).toHaveBeenCalledWith(9);
  });

  test('shows the RCA create form when the problem has no RCA', async () => {
    renderDetail();

    expect(await screen.findAllByText('Create RCA')).toBeTruthy();
    expect(problemRCA).toHaveBeenCalledWith('1');
    expect(getRCA).not.toHaveBeenCalled();
  });

  test('renders Readiness section', async () => {
    renderDetail();
    expect(await screen.findByText('Readiness State')).toBeTruthy();
  });

  test('renders History section', async () => {
    renderDetail();
    expect(await screen.findByText('Problem History')).toBeTruthy();
  });

  test('renders Linked Records section', async () => {
    renderDetail();
    expect(await screen.findByText('Linked Records')).toBeTruthy();
  });

  test('isolates a failing section from the rest of the page', async () => {
    listTasks.mockRejectedValue(new Error('tasks endpoint down'));
    renderDetail();
    expect(await screen.findByText('Section unavailable.')).toBeTruthy();
    expect(screen.getByText('Problem History')).toBeTruthy();
    expect(screen.getByText('PRB-2026-000001')).toBeTruthy();
  });

  test('renders the integrated Actions section with backend data', async () => {
    listActions.mockResolvedValue({
      results: [{
        id: 5, title: 'Replace disk', action_type: 'corrective', status: 'planned',
      }],
    });
    renderDetail();

    expect(await screen.findByText('Corrective and preventive work')).toBeTruthy();
    expect(await screen.findByText('Replace disk')).toBeTruthy();
    expect(listActions).toHaveBeenCalledWith('1');
    expect(screen.queryByText(
      'Corrective and preventive actions are tracked as tasks above.',
    )).toBeNull();
  });

  test('creates an action from the detail page and refreshes the list', async () => {
    renderDetail();

    fireEvent.change(await screen.findByLabelText(/Action title/), {
      target: { value: 'Patch server' },
    });
    const actionForm = screen.getByRole('button', { name: 'Create Action' }).closest('form');
    fireEvent.change(within(actionForm).getByLabelText('Description'), {
      target: { value: 'Apply security patch' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Action' }));

    await waitFor(() => {
      expect(createAction).toHaveBeenCalledWith('1', {
        title: 'Patch server',
        description: 'Apply security patch',
        action_type: 'corrective',
        due_at: null,
        root_cause_analysis: null,
      });
    });
    await waitFor(() => expect(listActions).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('PRB-2026-000001')).toBeTruthy();
  });

  test('drives an action lifecycle from the detail page through its transition', async () => {
    listActions.mockResolvedValue({
      results: [{
        id: 5, title: 'Replace disk', action_type: 'corrective', status: 'planned',
      }],
    });
    renderDetail();

    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));

    await waitFor(() => expect(approveAction).toHaveBeenCalledWith(5));
    await waitFor(() => expect(listActions).toHaveBeenCalledTimes(2));
  });

  // --- Problem field editing regression tests ---

  test('edit controls are visible to IT staff', async () => {
    renderDetail();
    expect(await screen.findByRole('button', { name: 'Edit problem fields' })).toBeTruthy();
  });

  test('edit controls are hidden from employees', async () => {
    authMocks.useAuth.mockReturnValue({
      isStaff: false,
      isManagerOrAdmin: false,
      isSupportOrAbove: false,
    });

    renderDetail();

    expect(await screen.findByText('PRB-2026-000001')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Edit problem fields' })).toBeNull();
  });

  test('operational fields are editable by IT Support', async () => {
    authMocks.useAuth.mockReturnValue({
      isStaff: true,
      isManagerOrAdmin: false,
      isSupportOrAbove: true,
    });

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit problem fields' }));

    expect(screen.getByRole('form', { name: 'Edit problem fields' })).toBeTruthy();
    expect(document.querySelector('input[name="title"]').value).toBe('Test Problem');
    expect(screen.queryByLabelText('Target Resolution Date')).toBeNull();
    expect(screen.queryByLabelText('Next Review Date')).toBeNull();
  });

  test('governance fields are available to managers and admins', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit problem fields' }));

    expect(screen.getByLabelText('Target Resolution Date')).toBeTruthy();
    expect(screen.getByLabelText('Next Review Date')).toBeTruthy();
  });

  test('form pre-populates from the loaded Problem', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit problem fields' }));

    expect(document.querySelector('input[name="title"]').value).toBe('Test Problem');
    expect(screen.getByLabelText('Environment').value).toBe('production');
  });

  test('save calls updateProblem with the correct ID, payload, and record version', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit problem fields' }));
    fireEvent.change(document.querySelector('input[name="title"]'), {
      target: { value: 'Updated Problem Title' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(updateProblem).toHaveBeenCalledWith(
        '1',
        expect.objectContaining({
          title: 'Updated Problem Title',
          description: '',
          subcategory: '',
          environment: 'production',
          detection_method: '',
        }),
        PROBLEM.record_version,
      );
    });
  });

  test('successful update refreshes the Overview display', async () => {
    updateProblem.mockResolvedValue({ ...PROBLEM, title: 'Updated Problem Title' });
    problemDetail
      .mockResolvedValueOnce(PROBLEM)
      .mockResolvedValueOnce({ ...PROBLEM, title: 'Updated Problem Title' });

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit problem fields' }));
    fireEvent.change(document.querySelector('input[name="title"]'), {
      target: { value: 'Updated Problem Title' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByText('Updated Problem Title')).toBeTruthy();
    await waitFor(() => expect(updateProblem).toHaveBeenCalledTimes(1));
  });

  test('409 stale-version response reports a conflict and keeps the editor open', async () => {
    updateProblem.mockRejectedValue({ response: { status: 409 } });

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit problem fields' }));
    fireEvent.change(document.querySelector('input[name="title"]'), {
      target: { value: 'My unsaved title' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(document.querySelector('input[name="title"]').value).toBe('My unsaved title');
    expect(screen.getByRole('form', { name: 'Edit problem fields' })).toBeTruthy();
  });

  test('validation errors preserve entered values', async () => {
    updateProblem.mockRejectedValue({ response: { status: 400, data: {} } });

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit problem fields' }));
    fireEvent.change(document.querySelector('input[name="title"]'), {
      target: { value: 'Title awaiting validation' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(document.querySelector('input[name="title"]').value).toBe('Title awaiting validation');
  });

  test('Cancel discards unsaved edits', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit problem fields' }));
    fireEvent.change(document.querySelector('input[name="title"]'), {
      target: { value: 'Unsaved title' },
    });
    fireEvent.click(
      within(screen.getByRole('form', { name: 'Edit problem fields' }))
        .getByRole('button', { name: 'Cancel' }),
    );

    expect(screen.queryByRole('form', { name: 'Edit problem fields' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Edit problem fields' }));
    expect(document.querySelector('input[name="title"]').value).toBe('Test Problem');
    expect(updateProblem).not.toHaveBeenCalled();
  });

  test('duplicate submissions are prevented while a save is pending', async () => {
    let resolveUpdate;
    updateProblem.mockImplementation(() => new Promise((resolve) => {
      resolveUpdate = resolve;
    }));

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit problem fields' }));

    const saveButton = screen.getByRole('button', { name: 'Save changes' });
    fireEvent.click(saveButton);
    fireEvent.click(saveButton);

    await waitFor(() => expect(updateProblem).toHaveBeenCalledTimes(1));

    resolveUpdate(PROBLEM);

    await waitFor(() => {
      expect(screen.queryByRole('form', { name: 'Edit problem fields' })).toBeNull();
    });
  });
});





