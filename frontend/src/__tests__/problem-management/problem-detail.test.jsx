import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ProblemDetail } from '../../pages/problem-management/ProblemDetail';
import {
  approveAction, approveException, approveWorkaround, cancelValidation, createAction, createAssetLink,
  createCiLink, createException, createKbLink, createServiceLink, createSoftwareLink,
  createTicketLink, createTimelineEvent, createValidation, createWorkaround, deleteAssetLink,
  deleteCiLink, deleteKbLink, deleteServiceLink, deleteSoftwareLink, deleteTicketLink, expireException,
  expireWorkaround, failValidation, getRCA, linkedAssets, linkedCIs, linkedKBs, linkedProducts,
  linkedServices, linkedTickets, listActions, listExceptions, listTasks, listValidations,
  listWorkarounds, markValidationInconclusive, passValidation, problemDetail, problemRCA,
  problemTimeline, publishWorkaround, rejectException, retireWorkaround, revokeException,
  startValidation, submitException, submitWorkaround, updateProblem,
} from '../../services/problem-management';
import api from '../../api';

afterEach(cleanup);

vi.mock('../../services/problem-management', () => ({
  approveAction: vi.fn(),
  approveException: vi.fn(),
  approveWorkaround: vi.fn(),
  cancelAction: vi.fn(),
  cancelValidation: vi.fn(),
  completeAction: vi.fn(),
  createAction: vi.fn(),
  createException: vi.fn(),
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
  createAssetLink: vi.fn(),
  createCiLink: vi.fn(),
  createKbLink: vi.fn(),
  createServiceLink: vi.fn(),
  createSoftwareLink: vi.fn(),
  createTicketLink: vi.fn(),
  createTimelineEvent: vi.fn(),
  createValidation: vi.fn(),
  createWorkaround: vi.fn(),
  deleteAssetLink: vi.fn(),
  deleteCiLink: vi.fn(),
  deleteKbLink: vi.fn(),
  deleteServiceLink: vi.fn(),
  deleteSoftwareLink: vi.fn(),
  deleteTicketLink: vi.fn(),
  expireException: vi.fn(),
  expireWorkaround: vi.fn(),
  failValidation: vi.fn(),
  listEvidence: vi.fn(),
  listExceptions: vi.fn(),
  listTasks: vi.fn(),
  listValidations: vi.fn(),
  listWorkarounds: vi.fn(),
  markValidationInconclusive: vi.fn(),
  passValidation: vi.fn(),
  problemDetail: vi.fn(),
  problemTimeline: vi.fn(),
  updateProblem: vi.fn(),
  problemHistory: vi.fn(),
  problemRCA: vi.fn(),
  problemReadiness: vi.fn(),
  publishWorkaround: vi.fn(),
  rejectException: vi.fn(),
  retireWorkaround: vi.fn(),
  revokeException: vi.fn(),
  rootCauseFactors: vi.fn(),
  startValidation: vi.fn(),
  submitException: vi.fn(),
  submitWorkaround: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: vi.fn(),
  },
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

const LINKED_TICKET = {
  id: 99,
  problem: 1,
  ticket: 55,
  ticket_display: '#55',
  ticket_title: 'VPN outage',
  ticket_status: 'open',
  ticket_priority: 'critical',
  ticket_category_name: 'Network',
  relationship_type: 'related_incident',
  relevance: 'high',
  is_primary: true,
  note: 'Primary incident',
  linked_by: 4,
  linked_at: '2026-01-01T00:00:00Z',
  is_deleted: false,
};

const ticketSearchResult = {
  id: 55,
  title: 'VPN outage',
  status: 'open',
  priority: 'critical',
  category_name: 'Network',
  requester_email: 'user@example.com',
  assignee: 7,
  department_name: 'IT',
  created_at: '2026-01-01T00:00:00Z',
  is_overdue: false,
  sla_due_at: '2026-01-02T00:00:00Z',
};

const renderDetail = () => render(
  <MemoryRouter>
    <ProblemDetail problemId="1" />
  </MemoryRouter>,
);

const mockTicketSearch = (results) => {
  api.get.mockImplementation((url) => {
    if (url === '/tickets/') {
      return Promise.resolve({
        data: { count: results.length, next: null, previous: null, results },
      });
    }
    return Promise.resolve({ data: { results: [] } });
  });
};

const mockServiceCataloguePages = (pages) => {
  api.get.mockImplementation((url, config) => {
    if (url === '/services/catalogue/') {
      const page = config?.params?.page ?? 1;
      const result = pages[page - 1] ?? { results: [], next: null };
      return Promise.resolve({
        data: { count: result.results.length, next: result.next ?? null, previous: null, results: result.results },
      });
    }
    return Promise.resolve({ data: { results: [] } });
  });
};

const LINKED_SERVICE = {
  id: 51,
  problem: 1,
  service: 12,
  target_display: 'Payroll Service',
  impact_type: 'direct',
  role: 'affected',
  confidence: 'high',
  notes: 'Primary service',
  created_by: 4,
  created_at: '2026-01-01T00:00:00Z',
  is_deleted: false,
};

describe('Problem Detail', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    api.get.mockReset();
    api.get.mockResolvedValue({ data: { results: [] } });
    authMocks.useAuth.mockReturnValue({
      isStaff: true,
      isManagerOrAdmin: true,
      isSupportOrAbove: true,
    });
    problemDetail.mockResolvedValue(PROBLEM);
    updateProblem.mockResolvedValue(PROBLEM);
    const svc = await import('../../services/problem-management');
    svc.linkedServices.mockReset();
    svc.createServiceLink.mockReset();
    svc.deleteServiceLink.mockReset();
    svc.listWorkarounds.mockReset();
    svc.problemTimeline.mockReset();
    svc.createTimelineEvent.mockReset();
    svc.listExceptions.mockReset();
    svc.createException.mockReset();
    svc.submitException.mockReset();
    svc.approveException.mockReset();
    svc.rejectException.mockReset();
    svc.revokeException.mockReset();
    svc.expireException.mockReset();
    ['createException', 'submitException', 'approveException', 'rejectException',
      'revokeException', 'expireException'
    ].forEach((name) => svc[name].mockResolvedValue({}));
    svc.createWorkaround.mockReset();
    svc.submitWorkaround.mockReset();
    svc.approveWorkaround.mockReset();
    svc.publishWorkaround.mockReset();
    svc.expireWorkaround.mockReset();
    svc.retireWorkaround.mockReset();
    ['fiveWhys', 'linkedAssets', 'linkedCIs', 'linkedProducts', 'linkedServices',
      'linkedTickets', 'linkedKBs', 'listActions', 'listRCAs', 'listEvidence',
      'listExceptions', 'listTasks', 'listValidations', 'listWorkarounds', 'problemHistory',
      'problemTimeline', 'rootCauseFactors'
    ].forEach((name) => {
      svc[name].mockResolvedValue({ results: [] });
    });
    svc.createKbLink.mockResolvedValue({});
    svc.deleteKbLink.mockResolvedValue({});
    svc.createAssetLink.mockResolvedValue({});
    svc.deleteAssetLink.mockResolvedValue({});
    svc.createCiLink.mockResolvedValue({});
    svc.deleteCiLink.mockResolvedValue({});
    svc.createServiceLink.mockResolvedValue({});
    svc.deleteServiceLink.mockResolvedValue({});
    svc.createSoftwareLink.mockResolvedValue({});
    svc.deleteSoftwareLink.mockResolvedValue({});
    svc.createTicketLink.mockResolvedValue({});
    svc.deleteTicketLink.mockResolvedValue({});
    svc.createTimelineEvent.mockResolvedValue({});
    svc.createValidation.mockResolvedValue({});
    ['startValidation', 'passValidation', 'failValidation',
      'markValidationInconclusive', 'cancelValidation'
    ].forEach((name) => svc[name].mockResolvedValue({}));
    svc.createWorkaround.mockResolvedValue({});
    svc.submitWorkaround.mockResolvedValue({});
    svc.approveWorkaround.mockResolvedValue({});
    svc.publishWorkaround.mockResolvedValue({});
    svc.expireWorkaround.mockResolvedValue({});
    svc.retireWorkaround.mockResolvedValue({});
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

  test('renders the embedded validation workflow once for the current problem', async () => {
    renderDetail();
    expect(await screen.findByRole('heading', { name: 'Validations' })).toBeTruthy();
    expect(screen.getByPlaceholderText('Validation title')).toBeTruthy();
    await waitFor(() => expect(listValidations).toHaveBeenCalledTimes(1));
    expect(listValidations).toHaveBeenCalledWith('1');
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

  test('renders the integrated Workarounds workflow and loads its list once', async () => {
    listWorkarounds.mockResolvedValue({
      results: [{ id: 7, title: 'Temporary fix', steps: 'Restart service', status: 'draft' }],
    });
    renderDetail();

    expect(await screen.findByRole('heading', { name: 'Workarounds' })).toBeTruthy();
    expect(await screen.findByText('Temporary fix')).toBeTruthy();
    expect(screen.getAllByText('Steps').length).toBeGreaterThan(0);
    expect(listWorkarounds).toHaveBeenCalledWith('1');
    expect(listWorkarounds).toHaveBeenCalledTimes(1);
  });

  test('staff can create a workaround from ProblemDetail and refresh the list', async () => {
    renderDetail();
    fireEvent.change(await screen.findByPlaceholderText('Workaround title'), {
      target: { value: 'Restart payroll service' },
    });
    fireEvent.change(screen.getByPlaceholderText('Steps'), {
      target: { value: 'Restart the payroll worker' },
    });
    const create = screen.getByRole('button', { name: 'Create Workaround' });
    await waitFor(() => expect(create.disabled).toBe(false));
    fireEvent.click(create);

    await waitFor(() => {
      expect(createWorkaround).toHaveBeenCalledWith('1', {
        title: 'Restart payroll service',
        steps: 'Restart the payroll worker',
      });
    });
    await waitFor(() => expect(listWorkarounds).toHaveBeenCalledTimes(2));
  });

  test('non-staff users see no workaround mutation controls', async () => {
    authMocks.useAuth.mockReturnValue({
      isStaff: false,
      isManagerOrAdmin: false,
      isSupportOrAbove: true,
    });
    listWorkarounds.mockResolvedValue({
      results: [{ id: 8, title: 'Temporary fix', steps: 'Restart', status: 'submitted' }],
    });
    renderDetail();

    const row = (await screen.findByText('Temporary fix')).closest('tr');
    expect(row).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create Workaround' })).toBeNull();
    expect(within(row).queryByText('Approve')).toBeNull();
    expect(within(row).queryByText('Retire')).toBeNull();
  });

  test('only governance roles see workaround approval', async () => {
    listWorkarounds.mockResolvedValue({
      results: [{ id: 9, title: 'Submitted fix', steps: 'Restart', status: 'submitted' }],
    });
    renderDetail();

    const row = (await screen.findByText('Submitted fix')).closest('tr');
    expect(within(row).getByText('Approve')).toBeTruthy();
    expect(within(row).queryByText('Submit')).toBeNull();
  });

  test('support staff cannot approve a submitted workaround', async () => {
    authMocks.useAuth.mockReturnValue({
      isStaff: true,
      isManagerOrAdmin: false,
      isSupportOrAbove: true,
    });
    listWorkarounds.mockResolvedValue({
      results: [{ id: 10, title: 'Submitted fix', steps: 'Restart', status: 'submitted' }],
    });
    renderDetail();

    const row = (await screen.findByText('Submitted fix')).closest('tr');
    expect(within(row).queryByText('Approve')).toBeNull();
    expect(within(row).getByText('Retire')).toBeTruthy();
  });

  test('a Workarounds API failure does not break the rest of ProblemDetail', async () => {
    listWorkarounds.mockRejectedValueOnce(new Error('workarounds endpoint down'));
    renderDetail();

    expect(await screen.findByText('Could not load workarounds.')).toBeTruthy();
    expect(screen.getByText('Problem History')).toBeTruthy();
    expect(screen.getByText('PRB-2026-000001')).toBeTruthy();
  });

  test('renders the integrated Timeline workflow and loads its list once', async () => {
    problemTimeline.mockResolvedValue({
      results: [{
        id: 5, event_type: 'milestone', title: 'Kickoff', source: 'manual',
        occurred_at: '2026-01-01T09:00:00Z', recorded_by_username: 'support',
      }],
    });
    renderDetail();

    expect(await screen.findByRole('heading', { name: 'Timeline' })).toBeTruthy();
    expect(await screen.findByText('Kickoff')).toBeTruthy();
    expect(problemTimeline).toHaveBeenCalledWith('1');
    expect(problemTimeline).toHaveBeenCalledTimes(1);
  });

  test('staff can add a timeline event from ProblemDetail and refresh the list', async () => {
    renderDetail();
    fireEvent.change(await screen.findByPlaceholderText('Event title'), {
      target: { value: 'Discovered cause' },
    });
    fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'monitoring' } });
    fireEvent.click(screen.getByText('Add Timeline Event'));

    await waitFor(() => {
      const payload = createTimelineEvent.mock.calls[0][1];
      expect(payload.title).toBe('Discovered cause');
      expect(payload.source).toBe('monitoring');
      expect(payload.event_type).toBe('milestone');
      expect(payload).toHaveProperty('occurred_at');
      expect(payload).not.toHaveProperty('recorded_at');
    });
    await waitFor(() => expect(problemTimeline).toHaveBeenCalledTimes(2));
  });

  test('non-staff users see no timeline mutation controls', async () => {
    authMocks.useAuth.mockReturnValue({
      isStaff: false,
      isManagerOrAdmin: false,
      isSupportOrAbove: true,
    });
    problemTimeline.mockResolvedValue({
      results: [{ id: 6, event_type: 'milestone', title: 'Incident logged', source: 'ticket' }],
    });
    renderDetail();

    expect(await screen.findByText('Incident logged')).toBeTruthy();
    expect(screen.queryByText('Add Timeline Event')).toBeNull();
    expect(screen.queryByPlaceholderText('Event title')).toBeNull();
  });

  test('a Timeline API failure does not break other ProblemDetail sections', async () => {
    problemTimeline.mockRejectedValueOnce(new Error('timeline endpoint down'));
    renderDetail();

    expect(await screen.findByText('Could not load the timeline.')).toBeTruthy();
    expect(screen.getByText('Problem History')).toBeTruthy();
    expect(screen.getByText('PRB-2026-000001')).toBeTruthy();
  });

  test('renders the integrated Exceptions workflow and loads its list once', async () => {
    listExceptions.mockResolvedValue({
      results: [{
        id: 5, title: 'Temporary exception', exception_type: 'operational',
        status: 'active', reason: 'Risk accepted', version: 2,
      }],
    });
    renderDetail();

    expect(await screen.findByRole('heading', { name: 'Exceptions' })).toBeTruthy();
    expect(await screen.findByText('Temporary exception')).toBeTruthy();
    expect(listExceptions).toHaveBeenCalledWith('1');
    expect(listExceptions).toHaveBeenCalledTimes(1);
  });

  test('staff can create an exception from ProblemDetail and refresh the list', async () => {
    renderDetail();
    fireEvent.change(await screen.findByPlaceholderText('Exception title'), {
      target: { value: 'Temporary exception' },
    });
    fireEvent.change(screen.getByLabelText('Exception type'), {
      target: { value: 'unknown_root_cause' },
    });
    fireEvent.change(screen.getByPlaceholderText('Reason'), {
      target: { value: 'Risk accepted' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Exception' }));

    await waitFor(() => {
      expect(createException).toHaveBeenCalledWith('1', {
        title: 'Temporary exception',
        exception_type: 'unknown_root_cause',
        reason: 'Risk accepted',
        conditions: '',
        expires_at: null,
      });
    });
    await waitFor(() => expect(listExceptions).toHaveBeenCalledTimes(2));
  });

  test('governance users can reject an exception from ProblemDetail with a reason', async () => {
    listExceptions.mockResolvedValue({
      results: [{
        id: 6, title: 'Accept risk', exception_type: 'operational',
        status: 'active', version: 4, created_by_username: 'author',
      }],
    });
    renderDetail();

    const row = (await screen.findByText('Accept risk')).closest('tr');
    fireEvent.click(within(row).getByText('Reject'));
    fireEvent.change(await within(row).findByLabelText('Rejection reason'), {
      target: { value: 'Control implemented' },
    });
    fireEvent.click(within(row).getByRole('button', { name: 'Confirm rejection' }));

    await waitFor(() => {
      expect(rejectException).toHaveBeenCalledWith(6, {
        expected_record_version: 4,
        reason: 'Control implemented',
      });
    });
    await waitFor(() => expect(listExceptions).toHaveBeenCalledTimes(2));
  });

  test('non-staff users see no exception mutation controls', async () => {
    authMocks.useAuth.mockReturnValue({
      isStaff: false,
      isManagerOrAdmin: false,
      isSupportOrAbove: true,
    });
    listExceptions.mockResolvedValue({
      results: [{ id: 7, title: 'Read-only exception', status: 'active' }],
    });
    renderDetail();

    expect(await screen.findByText('Read-only exception')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create Exception' })).toBeNull();
    expect(screen.queryByText('Reject')).toBeNull();
    expect(screen.queryByText('Revoke')).toBeNull();
  });

  test('an Exceptions API failure does not break other ProblemDetail sections', async () => {
    listExceptions.mockRejectedValueOnce(new Error('exceptions endpoint down'));
    renderDetail();

    expect(await screen.findByText('Could not load exceptions.')).toBeTruthy();
    expect(screen.getByText('Problem History')).toBeTruthy();
    expect(screen.getByText('PRB-2026-000001')).toBeTruthy();
  });

  test('renders the integrated Actions section with backend data', async () => {
    listActions.mockResolvedValue({
      results: [{
        id: 5, title: 'Replace disk', action_type: 'corrective', status: 'planned',
        version: 1,
      }],
    });
    renderDetail();

    expect(await screen.findByRole('heading', { name: 'Actions', level: 3 })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Actions', level: 1 })).toBeNull();
    expect(screen.queryByText('Corrective and preventive work')).toBeNull();
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
        version: 1,
      }],
    });
    renderDetail();

    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));

    await waitFor(() => {
      expect(approveAction).toHaveBeenCalledWith(5, {
        expected_record_version: 1,
      });
    });
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

  test('renders linked KB articles with metadata and navigation', async () => {
    linkedKBs.mockResolvedValue({
      results: [{
        id: 10,
        article: 55,
        article_title: 'VPN Reset Guide',
        article_status: 'published',
        relation_type: 'reference',
        relevance: 'high',
        note: 'Use before escalation',
      }],
    });

    renderDetail();

    const link = await screen.findByRole('link', { name: 'VPN Reset Guide' });
    expect(link.getAttribute('href')).toBe('#/kb/55');
    expect(screen.getByText(/published/i)).toBeTruthy();
    expect(screen.getByText(/Relation: Reference \| Relevance: High/)).toBeTruthy();
    expect(screen.getByText(/Note: Use before escalation/)).toBeTruthy();
  });

  test('renders empty linked KB state', async () => {
    linkedKBs.mockResolvedValue({ results: [] });
    renderDetail();
    expect(await screen.findByText('No KB articles linked.')).toBeTruthy();
  });

  test('KB search displays selectable results and links selected article', async () => {
    api.get.mockResolvedValue({ data: { results: [{ id: 55, title: 'VPN Reset Guide', status: 'published' }] } });
    linkedKBs
      .mockResolvedValueOnce({ results: [] })
      .mockResolvedValueOnce({
        results: [{
          id: 10, article: 55, article_title: 'VPN Reset Guide', article_status: 'published',
          relation_type: 'reference', relevance: 'medium', note: '',
        }],
      });
    createKbLink.mockResolvedValue({ id: 10 });

    renderDetail();
    await screen.findByText('Linked Records');

    fireEvent.change(screen.getByLabelText('Search KB articles'), { target: { value: 'vpn' } });
    const result = await screen.findByRole('button', { name: /VPN Reset Guide \(published\)/i });
    fireEvent.click(result);

    fireEvent.change(screen.getByLabelText('Relation type'), { target: { value: 'procedure' } });
    fireEvent.change(screen.getByLabelText('Relevance'), { target: { value: 'high' } });
    fireEvent.change(screen.getByLabelText('Note'), { target: { value: 'Runbook' } });

    fireEvent.click(screen.getByRole('button', { name: 'Link KB article' }));

    await waitFor(() => {
      expect(createKbLink).toHaveBeenCalledWith({
        problem: 1,
        article: 55,
        relation_type: 'procedure',
        relevance: 'high',
        note: 'Runbook',
      });
    });
    await waitFor(() => expect(linkedKBs).toHaveBeenCalledTimes(2));
  });

  test('displays duplicate-link validation errors from create API', async () => {
    api.get.mockResolvedValue({ data: { results: [{ id: 55, title: 'VPN Reset Guide', status: 'published' }] } });
    createKbLink.mockRejectedValue({ response: { data: { article: ['This KB article is already linked to the problem.'] } } });

    renderDetail();
    await screen.findByText('Linked Records');
    fireEvent.change(screen.getByLabelText('Search KB articles'), { target: { value: 'vpn' } });
    fireEvent.click(await screen.findByRole('button', { name: /VPN Reset Guide/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Link KB article' }));

    expect((await screen.findByRole('alert')).textContent).toContain('This KB article is already linked to the problem.');
  });

  test('removes KB link with link ID and refreshes list', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    linkedKBs
      .mockResolvedValueOnce({
        results: [{
          id: 10, article: 55, article_title: 'VPN Reset Guide', article_status: 'published',
          relation_type: 'reference', relevance: 'medium', note: '',
        }],
      })
      .mockResolvedValueOnce({ results: [] });
    deleteKbLink.mockResolvedValue({});

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove KB link VPN Reset Guide' }));

    await waitFor(() => expect(deleteKbLink).toHaveBeenCalledWith(10));
    await waitFor(() => expect(linkedKBs).toHaveBeenCalledTimes(2));
    confirmSpy.mockRestore();
  });

  test('hides KB mutation controls for non-staff users but keeps read-only list', async () => {
    authMocks.useAuth.mockReturnValue({ isStaff: false, isManagerOrAdmin: false, isSupportOrAbove: false });
    linkedKBs.mockResolvedValue({
      results: [{
        id: 10, article: 55, article_title: 'VPN Reset Guide', article_status: 'published',
        relation_type: 'reference', relevance: 'medium', note: '',
      }],
    });

    renderDetail();

    expect(await screen.findByRole('link', { name: 'VPN Reset Guide' })).toBeTruthy();
    expect(screen.queryByLabelText('Search KB articles')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Link KB article' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Remove KB link/i })).toBeNull();
  });

  test('KB section error does not break the rest of ProblemDetail', async () => {
    linkedKBs.mockRejectedValue(new Error('kb down'));

    renderDetail();

    expect(await screen.findByText('Unable to load linked KB articles.')).toBeTruthy();
    expect(screen.getByText('Problem History')).toBeTruthy();
    expect(screen.getByText('PRB-2026-000001')).toBeTruthy();
  });

  test('renders linked asset records with metadata and navigation', async () => {
    linkedAssets.mockResolvedValue({
      results: [{
        id: 21,
        asset: 7,
        target_display: 'AST-001 - Laptop',
        impact_type: 'direct',
        role: 'affected',
        confidence: 'high',
        notes: 'Primary device',
      }],
    });

    renderDetail();

    const link = await screen.findByRole('link', { name: 'AST-001 - Laptop' });
    expect(link.getAttribute('href')).toBe('#/assets/7');
    expect(screen.getByText(/Impact: Direct \| Role: Affected \| Confidence: High/)).toBeTruthy();
    expect(screen.getByText(/Notes: Primary device/)).toBeTruthy();
  });

  test('renders empty linked asset state', async () => {
    linkedAssets.mockResolvedValue({ results: [] });
    renderDetail();
    expect(await screen.findByText('No assets linked.')).toBeTruthy();
  });

  test('staff can link selected asset and payload/refresh are correct', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/assets/') return Promise.resolve({ data: { results: [{ id: 7, asset_tag: 'AST-001', name: 'Laptop' }] } });
      return Promise.resolve({ data: { results: [] } });
    });
    linkedAssets
      .mockResolvedValueOnce({ results: [] })
      .mockResolvedValueOnce({
        results: [{
          id: 21, asset: 7, target_display: 'AST-001 - Laptop',
          impact_type: 'direct', role: 'affected', confidence: 'high', notes: 'Primary device',
        }],
      });
    createAssetLink.mockResolvedValue({ id: 21 });

    renderDetail();
    await screen.findByText('No assets linked.');
    const assetForm = screen.getByRole('form', { name: 'Link asset' });
    const assetSelect = within(assetForm).getByLabelText('Related asset (optional)');
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/assets/', expect.any(Object)));
    fireEvent.change(assetSelect, { target: { value: '7' } });
    fireEvent.change(within(assetForm).getByLabelText('Impact type'), { target: { value: 'direct' } });
    fireEvent.change(within(assetForm).getByLabelText('Role'), { target: { value: 'root_cause' } });
    fireEvent.change(within(assetForm).getByLabelText('Confidence'), { target: { value: 'confirmed' } });
    fireEvent.change(within(assetForm).getByLabelText('Notes'), { target: { value: 'Primary device' } });
    fireEvent.click(within(assetForm).getByRole('button', { name: 'Link asset' }));

    await waitFor(() => {
      expect(createAssetLink).toHaveBeenCalledWith({
        problem: 1,
        asset: 7,
        impact_type: 'direct',
        role: 'root_cause',
        confidence: 'confirmed',
        notes: 'Primary device',
      });
    });
    await waitFor(() => expect(linkedAssets).toHaveBeenCalledTimes(2));
  });

  test('displays asset duplicate-link validation errors', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/assets/') return Promise.resolve({ data: { results: [{ id: 7, asset_tag: 'AST-001', name: 'Laptop' }] } });
      return Promise.resolve({ data: { results: [] } });
    });
    createAssetLink.mockRejectedValue({ response: { data: { non_field_errors: ['This object is already linked to the problem.'] } } });

    renderDetail();
    await screen.findByText('No assets linked.');
    const assetForm = screen.getByRole('form', { name: 'Link asset' });
    const assetSelect = within(assetForm).getByLabelText('Related asset (optional)');
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/assets/', expect.any(Object)));
    fireEvent.change(assetSelect, { target: { value: '7' } });
    fireEvent.click(within(assetForm).getByRole('button', { name: 'Link asset' }));

    expect((await screen.findAllByRole('alert')).map((n) => n.textContent).join(' ')).toContain('This object is already linked to the problem.');
  });

  test('removes asset link by link ID and refreshes list', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    linkedAssets
      .mockResolvedValueOnce({
        results: [{
          id: 21, asset: 7, target_display: 'AST-001 - Laptop',
          impact_type: 'direct', role: 'affected', confidence: 'high', notes: '',
        }],
      })
      .mockResolvedValueOnce({ results: [] });
    deleteAssetLink.mockResolvedValue({});

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove asset link AST-001 - Laptop' }));

    await waitFor(() => expect(deleteAssetLink).toHaveBeenCalledWith(21));
    await waitFor(() => expect(linkedAssets).toHaveBeenCalledTimes(2));
    confirmSpy.mockRestore();
  });

  test('failed asset removal preserves displayed relationship and shows error', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    linkedAssets.mockResolvedValue({
      results: [{
        id: 21, asset: 7, target_display: 'AST-001 - Laptop',
        impact_type: 'direct', role: 'affected', confidence: 'high', notes: '',
      }],
    });
    deleteAssetLink.mockRejectedValue({ response: { data: { detail: 'Delete failed' } } });

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove asset link AST-001 - Laptop' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Delete failed');
    expect(screen.getByRole('link', { name: 'AST-001 - Laptop' })).toBeTruthy();
    confirmSpy.mockRestore();
  });

  test('hides asset mutation controls for non-staff users but keeps read-only list', async () => {
    authMocks.useAuth.mockReturnValue({ isStaff: false, isManagerOrAdmin: false, isSupportOrAbove: false });
    linkedAssets.mockResolvedValue({
      results: [{
        id: 21, asset: 7, target_display: 'AST-001 - Laptop',
        impact_type: 'direct', role: 'affected', confidence: 'high', notes: '',
      }],
    });

    renderDetail();

    expect(await screen.findByRole('link', { name: 'AST-001 - Laptop' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Link asset' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Remove asset link/i })).toBeNull();
  });

  test('asset section error does not break the rest of ProblemDetail', async () => {
    linkedAssets.mockRejectedValue(new Error('asset down'));

    renderDetail();

    expect(await screen.findByText('Unable to load linked assets.')).toBeTruthy();
    expect(screen.getByText('Problem History')).toBeTruthy();
    expect(screen.getByText('PRB-2026-000001')).toBeTruthy();
  });

  test('renders linked CI records with metadata and navigation', async () => {
    linkedCIs.mockResolvedValue({
      results: [{
        id: 31,
        configuration_item: 5,
        target_display: 'CI-2026-000001 - App Server',
        impact_type: 'direct',
        role: 'root_cause',
        confidence: 'confirmed',
        notes: 'Primary affected CI',
      }],
    });

    renderDetail();

    const link = await screen.findByRole('link', { name: 'CI-2026-000001 - App Server' });
    expect(link.getAttribute('href')).toBe('#/cmdb/items/5');
    expect(document.body.textContent).toMatch(/Impact: Direct \| Role: Root Cause \| Confidence: Confirmed/i);
    expect(screen.getByText(/Notes: Primary affected CI/)).toBeTruthy();
  });

  test('renders empty linked CI state', async () => {
    linkedCIs.mockResolvedValue({ results: [] });
    renderDetail();
    expect(await screen.findByText('No configuration items linked.')).toBeTruthy();
  });

  test('CI search displays selectable results and links selected CI', async () => {
    api.get.mockImplementation((url, config) => {
      if (url === '/cmdb/items/') {
        expect(config?.params?.search).toBe('App');
        return Promise.resolve({ data: [{ id: 5, ci_number: 'CI-2026-000001', name: 'App Server', status: 'active' }] });
      }
      return Promise.resolve({ data: { results: [] } });
    });
    linkedCIs
      .mockResolvedValueOnce({ results: [] })
      .mockResolvedValueOnce({
        results: [{
          id: 31, configuration_item: 5, target_display: 'CI-2026-000001 - App Server',
          impact_type: 'direct', role: 'root_cause', confidence: 'confirmed', notes: 'Primary affected CI',
        }],
      });
    createCiLink.mockResolvedValue({ id: 31 });

    renderDetail();
    await screen.findByText('No configuration items linked.');
    const ciForm = screen.getByRole('form', { name: 'Link configuration item' });
    fireEvent.change(within(ciForm).getByLabelText('Search configuration items'), { target: { value: 'App' } });

    const searchResult = await screen.findByRole('button', { name: /CI-2026-000001 - App Server \(active\)/i });
    fireEvent.click(searchResult);
    fireEvent.change(within(ciForm).getByLabelText('Role'), { target: { value: 'root_cause' } });
    fireEvent.change(within(ciForm).getByLabelText('Confidence'), { target: { value: 'confirmed' } });
    fireEvent.change(within(ciForm).getByLabelText('Notes'), { target: { value: 'Primary affected CI' } });
    fireEvent.click(within(ciForm).getByRole('button', { name: 'Link configuration item' }));

    await waitFor(() => {
      expect(createCiLink).toHaveBeenCalledWith({
        problem: 1,
        configuration_item: 5,
        impact_type: 'direct',
        role: 'root_cause',
        confidence: 'confirmed',
        notes: 'Primary affected CI',
      });
    });
    await waitFor(() => expect(linkedCIs).toHaveBeenCalledTimes(2));
  });

  test('displays CI duplicate-link validation errors', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/cmdb/items/') return Promise.resolve({ data: { results: [{ id: 5, ci_number: 'CI-2026-000001', name: 'App Server' }] } });
      return Promise.resolve({ data: { results: [] } });
    });
    createCiLink.mockRejectedValue({ response: { data: { non_field_errors: ['This object is already linked to the problem.'] } } });

    renderDetail();
    await screen.findByText('No configuration items linked.');
    const ciForm = screen.getByRole('form', { name: 'Link configuration item' });
    fireEvent.change(within(ciForm).getByLabelText('Search configuration items'), { target: { value: 'App' } });
    fireEvent.click(await screen.findByRole('button', { name: /CI-2026-000001 - App Server/i }));
    fireEvent.click(within(ciForm).getByRole('button', { name: 'Link configuration item' }));

    expect((await screen.findAllByRole('alert')).map((n) => n.textContent).join(' ')).toContain('This object is already linked to the problem.');
  });

  test('removes CI link by link ID and refreshes list', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    linkedCIs
      .mockResolvedValueOnce({
        results: [{
          id: 31, configuration_item: 5, target_display: 'CI-2026-000001 - App Server',
          impact_type: 'direct', role: 'affected', confidence: 'high', notes: '',
        }],
      })
      .mockResolvedValueOnce({ results: [] });
    deleteCiLink.mockResolvedValue({});

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove CI link CI-2026-000001 - App Server' }));

    await waitFor(() => expect(deleteCiLink).toHaveBeenCalledWith(31));
    await waitFor(() => expect(linkedCIs).toHaveBeenCalledTimes(2));
    confirmSpy.mockRestore();
  });

  test('failed CI removal preserves displayed relationship and shows error', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    linkedCIs.mockResolvedValue({
      results: [{
        id: 31, configuration_item: 5, target_display: 'CI-2026-000001 - App Server',
        impact_type: 'direct', role: 'affected', confidence: 'high', notes: '',
      }],
    });
    deleteCiLink.mockRejectedValue({ response: { data: { detail: 'Delete failed' } } });

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove CI link CI-2026-000001 - App Server' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Delete failed');
    expect(screen.getByRole('link', { name: 'CI-2026-000001 - App Server' })).toBeTruthy();
    confirmSpy.mockRestore();
  });

  test('hides CI mutation controls for non-staff users but keeps read-only list', async () => {
    authMocks.useAuth.mockReturnValue({ isStaff: false, isManagerOrAdmin: false, isSupportOrAbove: false });
    linkedCIs.mockResolvedValue({
      results: [{
        id: 31, configuration_item: 5, target_display: 'CI-2026-000001 - App Server',
        impact_type: 'direct', role: 'affected', confidence: 'high', notes: '',
      }],
    });

    renderDetail();

    expect(await screen.findByRole('link', { name: 'CI-2026-000001 - App Server' })).toBeTruthy();
    expect(screen.queryByLabelText('Search configuration items')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Link configuration item' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Remove CI link/i })).toBeNull();
  });

  test('CI section error does not break Asset/KB/History sections', async () => {
    linkedCIs.mockRejectedValue(new Error('ci down'));

    renderDetail();

    expect(await screen.findByText('Unable to load linked configuration items.')).toBeTruthy();
    expect(screen.getByText('Problem History')).toBeTruthy();
    expect(screen.getByText('PRB-2026-000001')).toBeTruthy();
  });

  test('renders linked software product records with metadata and navigation', async () => {
    linkedProducts.mockResolvedValue({
      results: [{
        id: 41,
        software_product: 7,
        target_display: 'SP-001 - Visual Studio',
        impact_type: 'direct',
        role: 'root_cause',
        confidence: 'confirmed',
        notes: 'Installed application involved in the issue',
      }],
    });

    renderDetail();

    const link = await screen.findByRole('link', { name: 'SP-001 - Visual Studio' });
    expect(link.getAttribute('href')).toBe('#/software/products/7');
    expect(document.body.textContent).toMatch(/Impact: Direct \| Role: Root Cause \| Confidence: Confirmed/i);
    expect(screen.getByText(/Notes: Installed application involved in the issue/)).toBeTruthy();
  });

  test('renders linked software products empty state', async () => {
    linkedProducts.mockResolvedValue({ results: [] });
    renderDetail();
    expect(await screen.findByText('No software products linked.')).toBeTruthy();
  });

  test('software product search uses verified endpoint and links selected product', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/licensing/products/') {
        return Promise.resolve({
          data: {
            count: 1, next: null, previous: null,
            results: [{ id: 7, code: 'SP-001', name: 'Visual Studio', publisher: 'Microsoft', version: '2022' }],
          },
        });
      }
      return Promise.resolve({ data: { results: [] } });
    });
    linkedProducts
      .mockResolvedValueOnce({ results: [] })
      .mockResolvedValueOnce({
        results: [{
          id: 41, software_product: 7, target_display: 'SP-001 - Visual Studio',
          impact_type: 'direct', role: 'root_cause', confidence: 'confirmed', notes: 'Installed application involved in the issue',
        }],
      });
    createSoftwareLink.mockResolvedValue({ id: 41 });

    renderDetail();
    await screen.findByText('No software products linked.');
    const productForm = screen.getByRole('form', { name: 'Link software product' });
    fireEvent.change(within(productForm).getByLabelText('Search software products'), { target: { value: 'Visual' } });

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/licensing/products/', expect.objectContaining({
        params: expect.objectContaining({ search: 'Visual' }),
      }));
    });

    fireEvent.click(await screen.findByRole('button', { name: /SP-001 - Visual Studio \(Microsoft • 2022\)/i }));
    fireEvent.change(within(productForm).getByLabelText('Role'), { target: { value: 'root_cause' } });
    fireEvent.change(within(productForm).getByLabelText('Confidence'), { target: { value: 'confirmed' } });
    fireEvent.change(within(productForm).getByLabelText('Notes'), { target: { value: 'Installed application involved in the issue' } });
    fireEvent.click(within(productForm).getByRole('button', { name: 'Link software product' }));

    await waitFor(() => {
      expect(createSoftwareLink).toHaveBeenCalledWith({
        problem: 1,
        software_product: 7,
        impact_type: 'direct',
        role: 'root_cause',
        confidence: 'confirmed',
        notes: 'Installed application involved in the issue',
      });
    });
    await waitFor(() => expect(linkedProducts).toHaveBeenCalledTimes(2));
  });

  test('displays software product duplicate-link validation errors', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/licensing/products/') {
        return Promise.resolve({ data: { count: 1, next: null, previous: null, results: [{ id: 7, code: 'SP-001', name: 'Visual Studio' }] } });
      }
      return Promise.resolve({ data: { results: [] } });
    });
    createSoftwareLink.mockRejectedValue({ response: { data: { non_field_errors: ['This object is already linked to the problem.'] } } });

    renderDetail();
    await screen.findByText('No software products linked.');
    const productForm = screen.getByRole('form', { name: 'Link software product' });
    fireEvent.change(within(productForm).getByLabelText('Search software products'), { target: { value: 'Visual' } });
    fireEvent.click(await screen.findByRole('button', { name: /SP-001 - Visual Studio/i }));
    fireEvent.click(within(productForm).getByRole('button', { name: 'Link software product' }));

    expect((await screen.findAllByRole('alert')).map((n) => n.textContent).join(' ')).toContain('This object is already linked to the problem.');
  });

  test('removes software product link by link ID and refreshes list', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    linkedProducts
      .mockResolvedValueOnce({
        results: [{
          id: 41, software_product: 7, target_display: 'SP-001 - Visual Studio',
          impact_type: 'direct', role: 'affected', confidence: 'high', notes: '',
        }],
      })
      .mockResolvedValueOnce({ results: [] });
    deleteSoftwareLink.mockResolvedValue({});

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove software product link SP-001 - Visual Studio' }));

    await waitFor(() => expect(deleteSoftwareLink).toHaveBeenCalledWith(41));
    await waitFor(() => expect(linkedProducts).toHaveBeenCalledTimes(2));
    confirmSpy.mockRestore();
  });

  test('failed software product removal preserves displayed relationship and shows error', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    linkedProducts.mockResolvedValue({
      results: [{
        id: 41, software_product: 7, target_display: 'SP-001 - Visual Studio',
        impact_type: 'direct', role: 'affected', confidence: 'high', notes: '',
      }],
    });
    deleteSoftwareLink.mockRejectedValue({ response: { data: { detail: 'Delete failed' } } });

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove software product link SP-001 - Visual Studio' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Delete failed');
    expect(screen.getByRole('link', { name: 'SP-001 - Visual Studio' })).toBeTruthy();
    confirmSpy.mockRestore();
  });

  test('hides software product mutation controls for non-staff users but keeps read-only list', async () => {
    authMocks.useAuth.mockReturnValue({ isStaff: false, isManagerOrAdmin: false, isSupportOrAbove: false });
    linkedProducts.mockResolvedValue({
      results: [{
        id: 41, software_product: 7, target_display: 'SP-001 - Visual Studio',
        impact_type: 'direct', role: 'affected', confidence: 'high', notes: '',
      }],
    });

    renderDetail();

    expect(await screen.findByRole('link', { name: 'SP-001 - Visual Studio' })).toBeTruthy();
    expect(screen.queryByLabelText('Search software products')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Link software product' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Remove software product link/i })).toBeNull();
  });

  test('software product section error does not break Asset/CI/KB/History sections', async () => {
    linkedProducts.mockRejectedValue(new Error('products down'));
    linkedCIs.mockResolvedValue({ results: [] });
    linkedAssets.mockResolvedValue({ results: [] });
    linkedKBs.mockResolvedValue({ results: [] });

    renderDetail();

    expect(await screen.findByText('Unable to load linked software products.')).toBeTruthy();
    expect(screen.getByText('No configuration items linked.')).toBeTruthy();
    expect(screen.getByText('No assets linked.')).toBeTruthy();
    expect(screen.getByText('No KB articles linked.')).toBeTruthy();
    expect(screen.getByText('Problem History')).toBeTruthy();
  });

  // --- Ticket <-> Problem relationship workflow ---

  test('renders linked ticket metadata and navigates to the ticket detail route', async () => {
    linkedTickets.mockResolvedValue({ results: [LINKED_TICKET] });

    renderDetail();

    const link = await screen.findByRole('link', { name: 'VPN outage' });
    expect(link.getAttribute('href')).toBe('#/tickets/55');
    expect(screen.getByText('#55')).toBeTruthy();
    expect(screen.getByText(/Status: Open \| Priority: Critical \| Category: Network/)).toBeTruthy();
    expect(document.body.textContent).toMatch(
      /Relationship: Related incident \| Relevance: High \| Primary: Yes/i,
    );
    expect(screen.getByText(/Note: Primary incident/)).toBeTruthy();
  });

  test('renders empty linked ticket state', async () => {
    renderDetail();
    expect(await screen.findByText('No tickets linked.')).toBeTruthy();
  });

  test('ticket search calls /tickets/ with q and normalizes paginated results', async () => {
    api.get.mockImplementation((url, config) => {
      if (url === '/tickets/') {
        expect(config.params.q).toBe('vpn');
        expect(config.params.search).toBeUndefined();
        return Promise.resolve({
          data: {
            count: 2,
            next: null,
            previous: null,
            results: [
              ticketSearchResult,
              { id: 56, title: 'Second VPN report', status: 'open' },
            ],
          },
        });
      }
      return Promise.resolve({ data: { results: [] } });
    });

    renderDetail();
    await screen.findByText('No tickets linked.');
    fireEvent.change(screen.getByLabelText('Search tickets'), { target: { value: 'vpn' } });

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/tickets/', expect.objectContaining({
        params: { q: 'vpn' },
      }));
    });
    expect(await screen.findByRole('button', { name: /VPN outage \(#55\) \(open\)/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Second VPN report \(#56\) \(open\)/i })).toBeTruthy();
    expect(screen.queryByText('2')).toBeNull();
    expect(api.get.mock.calls.filter(([url]) => url === '/tickets/')).toHaveLength(1);
  });

  test('ticket search shows loading and empty result states', async () => {
    let resolveSearch;
    api.get.mockImplementation((url) => {
      if (url === '/tickets/') return new Promise((resolve) => { resolveSearch = resolve; });
      return Promise.resolve({ data: { results: [] } });
    });

    renderDetail();
    await screen.findByText('No tickets linked.');
    fireEvent.change(screen.getByLabelText('Search tickets'), { target: { value: 'vpn' } });

    expect(await screen.findByText('Searching tickets...')).toBeTruthy();
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/tickets/', expect.any(Object));
    });
    resolveSearch({ data: { count: 0, next: null, previous: null, results: [] } });
    expect(await screen.findByText('No tickets found.')).toBeTruthy();
  });

  test('ticket search errors are surfaced without breaking other sections', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/tickets/') return Promise.reject(new Error('search down'));
      return Promise.resolve({ data: { results: [] } });
    });

    renderDetail();
    await screen.findByText('No tickets linked.');
    fireEvent.change(screen.getByLabelText('Search tickets'), { target: { value: 'vpn' } });

    expect((await screen.findByRole('alert')).textContent).toContain('Could not search tickets.');
    expect(screen.getByText('Problem History')).toBeTruthy();
    expect(screen.getByText('No assets linked.')).toBeTruthy();
  });

  test('selecting a ticket keeps its numeric ID and enables submission', async () => {
    mockTicketSearch([ticketSearchResult]);

    renderDetail();
    await screen.findByText('No tickets linked.');
    fireEvent.change(screen.getByLabelText('Search tickets'), { target: { value: 'vpn' } });
    fireEvent.click(await screen.findByRole('button', { name: /VPN outage \(#55\)/i }));

    const form = screen.getByRole('form', { name: 'Link ticket' });
    expect(within(form).getByText(/Selected ticket:/).textContent).toContain('(ID 55)');
    expect(within(form).getByRole('button', { name: 'Link ticket' }).disabled).toBe(false);
  });

  test('staff can link a ticket with verified payload and the list is refreshed', async () => {
    mockTicketSearch([ticketSearchResult]);
    linkedTickets
      .mockResolvedValueOnce({ results: [] })
      .mockResolvedValueOnce({ results: [LINKED_TICKET] });

    renderDetail();
    await screen.findByText('No tickets linked.');
    fireEvent.change(screen.getByLabelText('Search tickets'), { target: { value: 'vpn' } });
    fireEvent.click(await screen.findByRole('button', { name: /VPN outage \(#55\)/i }));

    const form = screen.getByRole('form', { name: 'Link ticket' });
    fireEvent.change(within(form).getByLabelText('Relationship type'), { target: { value: 'caused_by' } });
    fireEvent.change(within(form).getByLabelText('Ticket relevance'), { target: { value: 'high' } });
    fireEvent.click(within(form).getByLabelText('Primary ticket link'));
    fireEvent.change(within(form).getByLabelText('Relationship note'), { target: { value: 'Root cause confirmed' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Link ticket' }));

    await waitFor(() => {
      expect(createTicketLink).toHaveBeenCalledWith({
        problem: 1,
        ticket: 55,
        relationship_type: 'caused_by',
        relevance: 'high',
        is_primary: true,
        note: 'Root cause confirmed',
      });
    });
    await waitFor(() => expect(linkedTickets).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('link', { name: 'VPN outage' })).toBeTruthy();
  });

  test('duplicate ticket link submissions are prevented while create is pending', async () => {
    let resolveCreate;
    createTicketLink.mockImplementation(() => new Promise((resolve) => { resolveCreate = resolve; }));
    mockTicketSearch([ticketSearchResult]);

    renderDetail();
    await screen.findByText('No tickets linked.');
    fireEvent.change(screen.getByLabelText('Search tickets'), { target: { value: 'vpn' } });
    fireEvent.click(await screen.findByRole('button', { name: /VPN outage \(#55\)/i }));

    const submit = within(screen.getByRole('form', { name: 'Link ticket' }))
      .getByRole('button', { name: 'Link ticket' });
    fireEvent.click(submit);
    expect(within(screen.getByRole('form', { name: 'Link ticket' }))
      .getByRole('button', { name: 'Linking...' }).disabled).toBe(true);
    fireEvent.click(submit);

    await waitFor(() => expect(createTicketLink).toHaveBeenCalledTimes(1));
    resolveCreate({ id: 99 });
    await waitFor(() => expect(linkedTickets).toHaveBeenCalledTimes(2));
  });

  test('displays backend duplicate/validation errors from ticket link creation', async () => {
    createTicketLink.mockRejectedValue({
      response: { data: { non_field_errors: ['This ticket is already linked to the problem.'] } },
    });
    mockTicketSearch([ticketSearchResult]);

    renderDetail();
    await screen.findByText('No tickets linked.');
    fireEvent.change(screen.getByLabelText('Search tickets'), { target: { value: 'vpn' } });
    fireEvent.click(await screen.findByRole('button', { name: /VPN outage \(#55\)/i }));
    fireEvent.click(within(screen.getByRole('form', { name: 'Link ticket' }))
      .getByRole('button', { name: 'Link ticket' }));

    expect((await screen.findByRole('alert')).textContent)
      .toContain('This ticket is already linked to the problem.');
    expect(linkedTickets).toHaveBeenCalledTimes(1);
  });

  test('removes ticket link by relationship ID and refreshes the list', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    linkedTickets
      .mockResolvedValueOnce({ results: [LINKED_TICKET] })
      .mockResolvedValueOnce({ results: [] });

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove ticket link VPN outage' }));

    await waitFor(() => expect(deleteTicketLink).toHaveBeenCalledWith(99));
    expect(deleteTicketLink).not.toHaveBeenCalledWith(55);
    await waitFor(() => expect(linkedTickets).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('No tickets linked.')).toBeTruthy();
    confirmSpy.mockRestore();
  });

  test('failed ticket link removal preserves the displayed relationship', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    linkedTickets.mockResolvedValue({ results: [LINKED_TICKET] });
    deleteTicketLink.mockRejectedValue({ response: { data: { detail: 'Delete failed' } } });

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove ticket link VPN outage' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Delete failed');
    expect(screen.getByRole('link', { name: 'VPN outage' })).toBeTruthy();
    expect(linkedTickets).toHaveBeenCalledTimes(1);
    confirmSpy.mockRestore();
  });

  test('duplicate ticket link removals are prevented while delete is pending', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    let resolveDelete;
    linkedTickets.mockResolvedValue({ results: [LINKED_TICKET] });
    deleteTicketLink.mockImplementation(() => new Promise((resolve) => { resolveDelete = resolve; }));

    renderDetail();
    const remove = await screen.findByRole('button', { name: 'Remove ticket link VPN outage' });
    fireEvent.click(remove);
    expect(screen.getByRole('button', { name: 'Remove ticket link VPN outage' }).disabled).toBe(true);
    fireEvent.click(remove);

    await waitFor(() => expect(deleteTicketLink).toHaveBeenCalledTimes(1));
    resolveDelete({});
    await waitFor(() => expect(linkedTickets).toHaveBeenCalledTimes(2));
    confirmSpy.mockRestore();
  });

  test('hides ticket mutation controls for non-staff users but keeps read-only metadata', async () => {
    authMocks.useAuth.mockReturnValue({
      isStaff: false, isManagerOrAdmin: false, isSupportOrAbove: false,
    });
    linkedTickets.mockResolvedValue({ results: [LINKED_TICKET] });

    renderDetail();

    expect(await screen.findByRole('link', { name: 'VPN outage' })).toBeTruthy();
    expect(screen.getByText('#55')).toBeTruthy();
    expect(screen.queryByLabelText('Search tickets')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Link ticket' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Remove ticket link/i })).toBeNull();
  });

  test('ticket section error does not break linked records, readiness, or history', async () => {
    linkedTickets.mockRejectedValue(new Error('tickets down'));
    linkedCIs.mockResolvedValue({ results: [] });
    linkedAssets.mockResolvedValue({ results: [] });
    linkedKBs.mockResolvedValue({ results: [] });
    linkedProducts.mockResolvedValue({ results: [] });

    renderDetail();

    expect(await screen.findByText('Unable to load linked tickets.')).toBeTruthy();
    expect(screen.getByText('No configuration items linked.')).toBeTruthy();
    expect(screen.getByText('No assets linked.')).toBeTruthy();
    expect(screen.getByText('No KB articles linked.')).toBeTruthy();
    expect(screen.getByText('No software products linked.')).toBeTruthy();
    expect(screen.getByText('Open critical tickets: 0')).toBeTruthy();
    expect(screen.getByText('Problem History')).toBeTruthy();
    expect(screen.getByText('PRB-2026-000001')).toBeTruthy();
  });

  test('stale ticket search responses are ignored after a newer query', async () => {
    let resolveFirst;
    let resolveSecond;
    let requestNumber = 0;
    api.get.mockImplementation((url) => {
      if (url === '/tickets/') {
        requestNumber += 1;
        if (requestNumber === 1) return new Promise((resolve) => { resolveFirst = resolve; });
        return new Promise((resolve) => { resolveSecond = resolve; });
      }
      return Promise.resolve({ data: { results: [] } });
    });

    renderDetail();
    await screen.findByText('No tickets linked.');
    const search = screen.getByLabelText('Search tickets');
    fireEvent.change(search, { target: { value: 'vpn' } });
    await waitFor(() => {
      expect(api.get.mock.calls.filter(([url]) => url === '/tickets/')).toHaveLength(1);
    });

    fireEvent.change(search, { target: { value: 'printer' } });
    await waitFor(() => {
      expect(api.get.mock.calls.filter(([url]) => url === '/tickets/')).toHaveLength(2);
    });

    resolveFirst({ data: { results: [{ id: 55, title: 'STALE VPN ticket' }] } });
    resolveSecond({ data: { results: [{ id: 57, title: 'FRESH printer ticket' }] } });

    expect(await screen.findByRole('button', { name: /FRESH printer ticket \(#57\)/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /STALE VPN ticket/i })).toBeNull();
  });

  // --- Service <-> Problem relationship workflow ---

  test('renders linked service metadata and navigates to the catalogue route', async () => {
    linkedServices.mockResolvedValue({ results: [LINKED_SERVICE] });

    renderDetail();

    const link = await screen.findByRole('link', { name: 'Payroll Service' });
    expect(link.getAttribute('href')).toBe('#/services');
    expect(screen.getByText('#12')).toBeTruthy();
    expect(screen.getByText(/Impact: Direct \| Role: Affected \| Confidence: High/)).toBeTruthy();
    expect(screen.getByText(/Notes: Primary service/)).toBeTruthy();
  });

  test('renders empty linked service state', async () => {
    renderDetail();
    expect(await screen.findByText('No services linked.')).toBeTruthy();
  });

  test('service search uses the catalogue endpoint, filters locally, and links the selected service', async () => {
    mockServiceCataloguePages([{
      next: null,
      results: [{
        id: 12,
        name: 'Payroll Service',
        category: 'HR',
        description: 'Payroll processing',
        is_active: false,
      }],
    }]);
    linkedServices
      .mockResolvedValueOnce({ results: [] })
      .mockResolvedValueOnce({ results: [LINKED_SERVICE] });

    renderDetail();
    await screen.findByText('No services linked.');
    const form = screen.getByRole('form', { name: 'Link service' });

    fireEvent.change(within(form).getByLabelText('Search services'), { target: { value: 'payroll' } });
    const result = await screen.findByRole('button', {
      name: /Payroll Service \(#12\) \(HR\) \(inactive\)/i,
    });
    const catalogueCall = api.get.mock.calls.find(([url]) => url === '/services/catalogue/');
    expect(catalogueCall[1].params).toEqual({ page: 1 });
    fireEvent.click(result);

    expect(within(form).getByText(/Selected service:/).textContent).toContain('(ID 12)');
    fireEvent.change(within(form).getByLabelText('Impact type'), { target: { value: 'dependency' } });
    fireEvent.change(within(form).getByLabelText('Service role'), { target: { value: 'root_cause' } });
    fireEvent.change(within(form).getByLabelText('Confidence'), { target: { value: 'confirmed' } });
    fireEvent.change(within(form).getByLabelText('Relationship notes'), {
      target: { value: 'Dependency confirmed' },
    });
    fireEvent.click(within(form).getByRole('button', { name: 'Link service' }));

    await waitFor(() => {
      expect(createServiceLink).toHaveBeenCalledWith({
        problem: 1,
        service: 12,
        impact_type: 'dependency',
        role: 'root_cause',
        confidence: 'confirmed',
        notes: 'Dependency confirmed',
      });
    });
    await waitFor(() => expect(linkedServices).toHaveBeenCalledTimes(2));
  });

  test('service search follows next pages but fetches at most five catalogue pages', async () => {
    mockServiceCataloguePages(Array.from({ length: 6 }, (_, index) => ({
      next: 'next-page',
      results: [{ id: 100 + index, name: `General Service ${index}`, category: 'Operations' }],
    })));

    renderDetail();
    await screen.findByText('No services linked.');
    fireEvent.change(screen.getByLabelText('Search services'), { target: { value: 'general' } });

    expect(await screen.findByRole('button', { name: /General Service 4 \(#104\)/i })).toBeTruthy();
    expect(api.get.mock.calls.filter(([url]) => url === '/services/catalogue/')).toHaveLength(5);
  });

  test('service search errors are surfaced without breaking other sections', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/services/catalogue/') return Promise.reject(new Error('catalogue down'));
      return Promise.resolve({ data: { results: [] } });
    });

    renderDetail();
    await screen.findByText('No services linked.');
    fireEvent.change(screen.getByLabelText('Search services'), { target: { value: 'payroll' } });

    expect((await screen.findByRole('alert')).textContent).toContain('Could not search services.');
    expect(screen.getByText('Problem History')).toBeTruthy();
    expect(screen.getByText('No tickets linked.')).toBeTruthy();
  });

  test('displays backend validation errors from service link creation', async () => {
    mockServiceCataloguePages([{
      next: null,
      results: [{ id: 12, name: 'Payroll Service', category: 'HR' }],
    }]);
    createServiceLink.mockRejectedValue({
      response: { data: { non_field_errors: ['This object is already linked to the problem.'] } },
    });

    renderDetail();
    await screen.findByText('No services linked.');
    const form = screen.getByRole('form', { name: 'Link service' });
    fireEvent.change(within(form).getByLabelText('Search services'), { target: { value: 'payroll' } });
    fireEvent.click(await screen.findByRole('button', { name: /Payroll Service \(#12\)/i }));
    fireEvent.click(within(form).getByRole('button', { name: 'Link service' }));

    expect((await screen.findByRole('alert')).textContent)
      .toContain('This object is already linked to the problem.');
    expect(linkedServices).toHaveBeenCalledTimes(1);
  });

  test('removes service link by relationship ID and refreshes the list', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    linkedServices
      .mockResolvedValueOnce({ results: [LINKED_SERVICE] })
      .mockResolvedValueOnce({ results: [] });

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove service link Payroll Service' }));

    await waitFor(() => expect(deleteServiceLink).toHaveBeenCalledWith(51));
    expect(deleteServiceLink).not.toHaveBeenCalledWith(12);
    await waitFor(() => expect(linkedServices).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('No services linked.')).toBeTruthy();
    confirmSpy.mockRestore();
  });

  test('failed service link removal preserves the displayed relationship', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    linkedServices.mockResolvedValue({ results: [LINKED_SERVICE] });
    deleteServiceLink.mockRejectedValue({ response: { data: { detail: 'Delete failed' } } });

    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove service link Payroll Service' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Delete failed');
    expect(screen.getByRole('link', { name: 'Payroll Service' })).toBeTruthy();
    expect(linkedServices).toHaveBeenCalledTimes(1);
    confirmSpy.mockRestore();
  });

  test('hides service mutation controls for non-staff users but keeps read-only metadata', async () => {
    authMocks.useAuth.mockReturnValue({
      isStaff: false, isManagerOrAdmin: false, isSupportOrAbove: false,
    });
    linkedServices.mockResolvedValue({ results: [LINKED_SERVICE] });

    renderDetail();

    expect(await screen.findByRole('link', { name: 'Payroll Service' })).toBeTruthy();
    expect(screen.queryByLabelText('Search services')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Link service' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Remove service link/i })).toBeNull();
  });

  test('service section error does not break linked records, readiness, or history', async () => {
    linkedServices.mockRejectedValue(new Error('services down'));
    linkedTickets.mockResolvedValue({ results: [] });
    linkedCIs.mockResolvedValue({ results: [] });
    linkedAssets.mockResolvedValue({ results: [] });
    linkedKBs.mockResolvedValue({ results: [] });
    linkedProducts.mockResolvedValue({ results: [] });

    renderDetail();

    expect(await screen.findByText('Unable to load linked services.')).toBeTruthy();
    expect(screen.getByText('No tickets linked.')).toBeTruthy();
    expect(screen.getByText('No configuration items linked.')).toBeTruthy();
    expect(screen.getByText('No assets linked.')).toBeTruthy();
    expect(screen.getByText('No KB articles linked.')).toBeTruthy();
    expect(screen.getByText('No software products linked.')).toBeTruthy();
    expect(screen.getByText('Open critical tickets: 0')).toBeTruthy();
    expect(screen.getByText('Problem History')).toBeTruthy();
  });
});





