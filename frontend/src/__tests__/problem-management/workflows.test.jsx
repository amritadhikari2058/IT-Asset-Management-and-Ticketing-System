import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
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
  editAction: vi.fn(),
  listActions: vi.fn(),
  listRCAs: vi.fn(),
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
  services.approveAction.mockReset();
  services.cancelAction.mockReset();
  services.completeAction.mockReset();
  services.createAction.mockReset();
  services.editAction.mockReset();
  services.listActions.mockReset();
  services.listRCAs.mockReset();
  services.markActionIneffective.mockReset();
  services.startAction.mockReset();
  services.validateAction.mockReset();
  services.listActions.mockResolvedValue({ results: [] });
  services.listRCAs.mockResolvedValue({ results: [] });
  services.listWorkarounds.mockResolvedValue({ results: [] });
  services.listValidations.mockResolvedValue({ results: [] });
  services.listExceptions.mockResolvedValue({ results: [] });
  services.createValidation.mockReset();
  services.startValidation.mockReset();
  services.passValidation.mockReset();
  services.failValidation.mockReset();
  services.markValidationInconclusive.mockReset();
  services.cancelValidation.mockReset();
  services.createException.mockReset();
  services.submitException.mockReset();
  services.approveException.mockReset();
  services.rejectException.mockReset();
  services.revokeException.mockReset();
  services.expireException.mockReset();
  services.problemTimeline.mockResolvedValue({ results: [] });
  services.linkedTickets.mockResolvedValue({ results: [] });
  services.linkedCIs.mockResolvedValue({ results: [] });
  services.linkedAssets.mockResolvedValue({ results: [] });
  services.linkedServices.mockResolvedValue({ results: [] });
  services.linkedProducts.mockResolvedValue({ results: [] });
});

describe('Actions workflow', () => {
  const PLANNED = {
    id: 1, title: 'Replace disk', action_type: 'corrective', status: 'planned',
    version: 1,
  };
  const TRANSITION_BUTTONS = [
    'Approve', 'Start', 'Complete', 'Validate', 'Ineffective', 'Cancel',
  ];
  const actionRow = () => within(screen.getByText('Replace disk').closest('tr'));
  const waitForActionRow = async () => {
    await screen.findByText('Replace disk');
    return actionRow();
  };

  test('drives the lifecycle through dedicated transitions with version tokens', async () => {
    services.listActions.mockResolvedValue({ results: [PLANNED] });
    renderWith(<Actions problemId="1" />);
    fireEvent.click(await screen.findByText('Approve'));
    await waitFor(() => {
      expect(services.approveAction).toHaveBeenCalledWith(1, {
        expected_record_version: 1,
      });
    });
    fireEvent.click(screen.getByText('Start'));
    await waitFor(() => {
      expect(services.startAction).toHaveBeenCalledWith(1, {
        expected_record_version: 1,
      });
    });
  });

  test('uses a section heading when embedded and keeps the page header standalone', async () => {
    const embedded = renderWith(<Actions problemId="1" embedded />);
    expect(await screen.findByRole('heading', { name: 'Actions', level: 3 })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Actions', level: 1 })).toBeNull();
    expect(screen.queryByText('Corrective and preventive work')).toBeNull();
    embedded.unmount();

    renderWith(<Actions problemId="1" />);
    expect(await screen.findByRole('heading', { name: 'Actions', level: 1 })).toBeTruthy();
    expect(screen.getByText('Corrective and preventive work')).toBeTruthy();
  });

  const REASON_DIALOGS = {
    Ineffective: {
      field: 'Ineffectiveness reason',
      confirm: 'Confirm ineffective',
    },
    Cancel: {
      field: 'Cancellation reason',
      confirm: 'Confirm cancellation',
    },
  };

  test.each([
    ['Approve', 'planned', 'approveAction'],
    ['Start', 'planned', 'startAction'],
    ['Start', 'approved', 'startAction'],
    ['Complete', 'in_progress', 'completeAction'],
    ['Validate', 'completed', 'validateAction'],
    ['Ineffective', 'completed', 'markActionIneffective'],
    ['Cancel', 'planned', 'cancelAction'],
    ['Cancel', 'approved', 'cancelAction'],
    ['Cancel', 'in_progress', 'cancelAction'],
    ['Cancel', 'completed', 'cancelAction'],
  ])('sends expected_record_version for %s from %s', async (button, status, fnName) => {
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, status, version: 4 }],
    });
    renderWith(<Actions problemId="1" />);
    fireEvent.click(await (await waitForActionRow()).findByRole('button', { name: button }));

    const dialog = REASON_DIALOGS[button];
    if (dialog) {
      fireEvent.change(await screen.findByLabelText(dialog.field), {
        target: { value: '  documented reason  ' },
      });
      fireEvent.click(within(screen.getByRole('dialog')).getByRole(
        'button', { name: dialog.confirm },
      ));
    }

    await waitFor(() => {
      expect(services[fnName]).toHaveBeenCalledWith(1, {
        expected_record_version: 4,
        ...(dialog ? { reason: 'documented reason' } : {}),
      });
    });
  });

  test.each([
    ['Cancel', 'planned', 'cancelAction', 'Cancel action', 'Cancellation reason'],
    ['Ineffective', 'completed', 'markActionIneffective',
      'Mark action ineffective', 'Ineffectiveness reason'],
  ])('%s opens a required reason dialog before calling the API', async (
    button, status, fnName, title, fieldLabel,
  ) => {
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, status, version: 4 }],
    });
    renderWith(<Actions problemId="1" />);
    fireEvent.click(await (await waitForActionRow()).findByRole(
      'button', { name: button },
    ));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(title)).toBeTruthy();
    expect(within(dialog).getByLabelText(fieldLabel).value).toBe('');
    expect(services[fnName]).not.toHaveBeenCalled();
  });

  test.each([
    ['Cancel', 'planned', 'cancelAction', 'Cancellation reason',
      'A cancellation reason is required.'],
    ['Ineffective', 'completed', 'markActionIneffective',
      'Ineffectiveness reason', 'An ineffectiveness reason is required.'],
  ])('%s rejects empty and whitespace-only reasons', async (
    button, status, fnName, fieldLabel, missingMessage,
  ) => {
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, status, version: 4 }],
    });
    renderWith(<Actions problemId="1" />);
    fireEvent.click(await (await waitForActionRow()).findByRole(
      'button', { name: button },
    ));

    const dialog = await screen.findByRole('dialog');
    const field = within(dialog).getByLabelText(fieldLabel);
    const confirm = within(dialog).getByRole('button', {
      name: button === 'Cancel' ? 'Confirm cancellation' : 'Confirm ineffective',
    });

    fireEvent.click(confirm);
    expect(await within(dialog).findByText(missingMessage)).toBeTruthy();
    expect(services[fnName]).not.toHaveBeenCalled();

    fireEvent.change(field, { target: { value: '   ' } });
    fireEvent.click(confirm);
    expect(await within(dialog).findByText(missingMessage)).toBeTruthy();
    expect(services[fnName]).not.toHaveBeenCalled();
  });

  test.each([
    ['Cancel', 'planned', 'cancelAction', 'Cancellation reason',
      'Confirm cancellation', 'cancelled'],
    ['Ineffective', 'completed', 'markActionIneffective',
      'Ineffectiveness reason', 'Confirm ineffective', 'ineffective'],
  ])('%s trims the reason, sends its version, and closes only after success', async (
    button, status, fnName, fieldLabel, confirmLabel, targetStatus,
  ) => {
    let resolveTransition;
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, status, version: 4 }],
    });
    services[fnName].mockImplementation(() => new Promise((resolve) => {
      resolveTransition = resolve;
    }));

    renderWith(<Actions problemId="1" />);
    fireEvent.click(await (await waitForActionRow()).findByRole(
      'button', { name: button },
    ));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(fieldLabel), {
      target: { value: '  documented transition reason  ' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: confirmLabel }));

    await waitFor(() => {
      expect(services[fnName]).toHaveBeenCalledWith(1, {
        expected_record_version: 4,
        reason: 'documented transition reason',
      });
    });
    expect(screen.getByRole('dialog')).toBeTruthy();

    resolveTransition({ ...PLANNED, status: targetStatus, version: 5 });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(await screen.findByText(`${button === 'Cancel' ? 'Cancel' : 'Mark ineffective'} succeeded.`)).toBeTruthy();
  });

  test('keeps the reason dialog and text after a 400 reason validation error', async () => {
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, status: 'planned', version: 4 }],
    });
    services.cancelAction.mockRejectedValueOnce({
      response: { status: 400, data: { reason: ['A cancellation reason is required.'] } },
    });

    renderWith(<Actions problemId="1" />);
    fireEvent.click(await (await waitForActionRow()).findByRole(
      'button', { name: 'Cancel' },
    ));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Cancellation reason'), {
      target: { value: '  keep this text  ' },
    });
    fireEvent.click(within(dialog).getByRole(
      'button', { name: 'Confirm cancellation' },
    ));

    expect((await screen.findByRole('alert')).textContent)
      .toContain('reason: A cancellation reason is required.');
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.getByLabelText('Cancellation reason').value).toBe('  keep this text  ');
    expect(services.cancelAction).toHaveBeenCalledTimes(1);
  });

  test('refreshes on a 409 without retrying and keeps the reason for manual review', async () => {
    services.listActions
      .mockResolvedValueOnce({ results: [{ ...PLANNED, status: 'planned', version: 4 }] })
      .mockResolvedValueOnce({ results: [{ ...PLANNED, status: 'planned', version: 5 }] });
    services.cancelAction
      .mockRejectedValueOnce({ response: { status: 409 } })
      .mockResolvedValueOnce({ ...PLANNED, status: 'cancelled', version: 6 });

    renderWith(<Actions problemId="1" />);
    fireEvent.click(await (await waitForActionRow()).findByRole(
      'button', { name: 'Cancel' },
    ));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Cancellation reason'), {
      target: { value: '  superseded  ' },
    });
    fireEvent.click(within(dialog).getByRole(
      'button', { name: 'Confirm cancellation' },
    ));

    expect(await screen.findByText(/changed on the server/)).toBeTruthy();
    await waitFor(() => expect(services.listActions).toHaveBeenCalledTimes(2));
    expect(services.cancelAction).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('Cancellation reason').value).toBe('  superseded  ');

    fireEvent.click(screen.getByRole('button', { name: 'Confirm cancellation' }));
    await waitFor(() => {
      expect(services.cancelAction).toHaveBeenLastCalledWith(1, {
        expected_record_version: 5,
        reason: 'superseded',
      });
    });
  });

  test('prevents duplicate submissions of a required reason transition', async () => {
    let resolveCancel;
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, status: 'planned', version: 4 }],
    });
    services.cancelAction.mockImplementation(() => new Promise((resolve) => {
      resolveCancel = resolve;
    }));

    renderWith(<Actions problemId="1" />);
    fireEvent.click(await (await waitForActionRow()).findByRole(
      'button', { name: 'Cancel' },
    ));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Cancellation reason'), {
      target: { value: 'duplicate check' },
    });
    const confirm = within(dialog).getByRole(
      'button', { name: 'Confirm cancellation' },
    );
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(services.cancelAction).toHaveBeenCalledTimes(1);

    resolveCancel({ ...PLANNED, status: 'cancelled', version: 5 });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  test.each([
    ['Approve', 'planned', 'approveAction'],
    ['Start', 'approved', 'startAction'],
    ['Complete', 'in_progress', 'completeAction'],
    ['Validate', 'completed', 'validateAction'],
  ])('%s still submits without a reason', async (button, status, fnName) => {
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, status, version: 4 }],
    });
    renderWith(<Actions problemId="1" />);
    fireEvent.click(await (await waitForActionRow()).findByRole(
      'button', { name: button },
    ));
    await waitFor(() => {
      expect(services[fnName]).toHaveBeenCalledWith(1, {
        expected_record_version: 4,
      });
    });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('embedded Actions also gate cancellation behind a reason dialog', async () => {
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, status: 'planned', version: 4 }],
    });
    renderWith(<Actions problemId="1" embedded />);
    fireEvent.click(await (await waitForActionRow()).findByRole(
      'button', { name: 'Cancel' },
    ));

    expect(await screen.findByLabelText('Cancellation reason')).toBeTruthy();
    expect(services.cancelAction).not.toHaveBeenCalled();
  });

  test('refreshes and shows the new status and version after a successful transition', async () => {
    services.listActions
      .mockResolvedValueOnce({ results: [PLANNED] })
      .mockResolvedValueOnce({
        results: [{ ...PLANNED, status: 'in_progress', version: 2 }],
      });
    services.startAction.mockResolvedValue({
      ...PLANNED, status: 'in_progress', version: 2,
    });

    renderWith(<Actions problemId="1" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Start' }));

    expect(await screen.findByText('Start succeeded.')).toBeTruthy();
    await waitFor(() => {
      expect(actionRow().getByText('In progress')).toBeTruthy();
      expect(actionRow().getByText('2')).toBeTruthy();
    });
    fireEvent.click(actionRow().getByRole('button', { name: 'Complete' }));
    await waitFor(() => {
      expect(services.completeAction).toHaveBeenCalledWith(1, {
        expected_record_version: 2,
      });
    });
  });

  test('renders a stale-version conflict, refreshes, and never retries', async () => {
    services.listActions
      .mockResolvedValueOnce({ results: [PLANNED] })
      .mockResolvedValueOnce({ results: [{ ...PLANNED, version: 2 }] });
    services.startAction.mockRejectedValueOnce({ response: { status: 409 } });

    renderWith(<Actions problemId="1" />);
    fireEvent.click(await screen.findByText('Start'));

    expect(await screen.findByText(/changed on the server/)).toBeTruthy();
    expect(services.startAction).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(services.listActions).toHaveBeenCalledTimes(2));
    expect(screen.queryByText('Start succeeded.')).toBeNull();
  });

  test('keeps ordinary transition errors distinct from conflicts', async () => {
    services.listActions.mockResolvedValue({ results: [PLANNED] });
    services.startAction.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'Invalid source state.' } },
    });
    renderWith(<Actions problemId="1" />);
    fireEvent.click(await (await waitForActionRow()).findByRole('button', { name: 'Start' }));

    expect(await screen.findByText('Invalid source state.')).toBeTruthy();
    expect(screen.queryByText(/changed on the server/)).toBeNull();
    await waitFor(() => expect(services.listActions).toHaveBeenCalledTimes(1));
  });

  test('prevents duplicate transition submissions while a request is in flight', async () => {
    let resolveStart;
    services.listActions.mockResolvedValue({ results: [PLANNED] });
    services.startAction.mockImplementation(() => new Promise((resolve) => {
      resolveStart = resolve;
    }));
    renderWith(<Actions problemId="1" />);
    fireEvent.click(await (await waitForActionRow()).findByRole('button', { name: 'Start' }));
    expect(services.startAction).toHaveBeenCalledTimes(1);
    fireEvent.click(actionRow().getByRole('button', { name: 'Start' }));
    expect(services.startAction).toHaveBeenCalledTimes(1);

    resolveStart({ ...PLANNED, status: 'in_progress', version: 2 });
    expect(await screen.findByText('Start succeeded.')).toBeTruthy();
  });

  test('matches the backend status and role transition matrix', async () => {
    const expected = {
      planned: ['Approve', 'Start', 'Cancel'],
      approved: ['Start', 'Cancel'],
      in_progress: ['Complete', 'Cancel'],
      completed: ['Validate', 'Ineffective', 'Cancel'],
      verified: [],
      ineffective: [],
      cancelled: [],
      closed: [],
    };
    for (const [status, expectedButtons] of Object.entries(expected)) {
      cleanup();
      services.listActions.mockResolvedValue({
        results: [{ ...PLANNED, status }],
      });
      renderWith(<Actions problemId="1" />);
      await screen.findByText('Replace disk');
      const row = actionRow();
      const visible = TRANSITION_BUTTONS.filter(
        (name) => row.queryByRole('button', { name }),
      );
      expect(visible).toEqual(expectedButtons);
      if (expectedButtons.length === 0) {
        expect(screen.queryByLabelText('RCA for action 1')).toBeNull();
      }
    }
  });

  test('keeps approval limited to governance roles', async () => {
    auth.current = {
      isStaff: true, isManagerOrAdmin: false, user: { username: 'support' },
    };
    services.listActions.mockResolvedValue({ results: [PLANNED] });
    renderWith(<Actions problemId="1" />);

    const row = await waitForActionRow();
    expect(row.getByRole('button', { name: 'Start' })).toBeTruthy();
    expect(row.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(row.getByRole('button', { name: 'Cancel' })).toBeTruthy();
  });

  test('loads RCA options for the current problem and creates an action with one', async () => {
    services.listRCAs.mockResolvedValue({
      results: [{ id: 5, title: 'Disk failure', status: 'approved' }],
    });

    renderWith(<Actions problemId="1" />);

    const rcaSelect = await screen.findByLabelText('Root cause analysis');
    expect(services.listRCAs).toHaveBeenCalledWith('1');
    expect(within(rcaSelect).getByRole('option', { name: 'Disk failure (approved)' }))
      .toBeTruthy();
    expect(within(rcaSelect).queryByRole('option', { name: /Other problem/ })).toBeNull();

    fireEvent.change(rcaSelect, { target: { value: '5' } });
    fireEvent.change(screen.getByLabelText(/Action title/), {
      target: { value: 'Replace disk' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Action' }));

    await waitFor(() => {
      expect(services.createAction).toHaveBeenCalledWith('1', expect.objectContaining({
        title: 'Replace disk',
        root_cause_analysis: 5,
      }));
    });
    await waitFor(() => expect(services.listActions).toHaveBeenCalledTimes(2));
  });

  test('prevents duplicate creation from rapid repeated submission', async () => {
    let resolveCreate;
    services.createAction.mockImplementation(() => new Promise((resolve) => {
      resolveCreate = resolve;
    }));
    renderWith(<Actions problemId="1" />);
    fireEvent.change(await screen.findByLabelText(/Action title/), {
      target: { value: 'Patch server' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Action' }));
    expect(services.createAction).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: /Saving/ }));
    expect(services.createAction).toHaveBeenCalledTimes(1);

    resolveCreate({ ...PLANNED, title: 'Patch server' });
    expect(await screen.findByRole('button', { name: 'Create Action' })).toBeTruthy();
  });

  test('displays the linked RCA title and status in the action row', async () => {
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, root_cause_analysis: 5 }],
    });
    services.listRCAs.mockResolvedValue({
      results: [{ id: 5, title: 'Disk failure', status: 'approved' }],
    });

    renderWith(<Actions problemId="1" />);

    expect(await screen.findByText('Disk failure')).toBeTruthy();
    expect(screen.getByText('Approved')).toBeTruthy();
    expect(screen.getByLabelText('RCA for action 1').value).toBe('5');
  });

  test('associates an existing action with an RCA and refreshes', async () => {
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, root_cause_analysis: null }],
    });
    services.listRCAs.mockResolvedValue({
      results: [{ id: 5, title: 'Disk failure', status: 'approved' }],
    });
    services.editAction.mockResolvedValue({ ...PLANNED, root_cause_analysis: 5 });

    renderWith(<Actions problemId="1" />);

    fireEvent.change(await screen.findByLabelText('RCA for action 1'), {
      target: { value: '5' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save RCA' }));

    await waitFor(() => {
      expect(services.editAction).toHaveBeenCalledWith(1, {
        root_cause_analysis: 5,
      }, 1);
    });
    expect(await screen.findByText('RCA link updated.')).toBeTruthy();
    await waitFor(() => expect(services.listActions).toHaveBeenCalledTimes(2));
  });

  test('clears an RCA link with null and refreshes', async () => {
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, root_cause_analysis: 5 }],
    });
    services.listRCAs.mockResolvedValue({
      results: [{ id: 5, title: 'Disk failure', status: 'approved' }],
    });
    services.editAction.mockResolvedValue({ ...PLANNED, root_cause_analysis: null });

    renderWith(<Actions problemId="1" />);

    fireEvent.change(await screen.findByLabelText('RCA for action 1'), {
      target: { value: '' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save RCA' }));

    await waitFor(() => {
      expect(services.editAction).toHaveBeenCalledWith(1, {
        root_cause_analysis: null,
      }, 1);
    });
    await waitFor(() => expect(services.listActions).toHaveBeenCalledTimes(2));
  });

  test('hides RCA mutation controls from unauthorized users', async () => {
    auth.current = { isStaff: false, isManagerOrAdmin: false, user: { username: 'viewer' } };
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, root_cause_analysis: 5 }],
    });
    services.listRCAs.mockResolvedValue({
      results: [{ id: 5, title: 'Disk failure', status: 'approved' }],
    });

    renderWith(<Actions problemId="1" />);

    expect(await screen.findByText('Disk failure')).toBeTruthy();
    expect(screen.queryByLabelText('RCA for action 1')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Save RCA' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Create Action' })).toBeNull();
    expect(screen.queryByLabelText('Root cause analysis')).toBeNull();
    TRANSITION_BUTTONS.forEach((name) => {
      expect(screen.queryByRole('button', { name })).toBeNull();
    });
  });

  test('shows backend RCA-link validation errors without refreshing', async () => {
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, root_cause_analysis: null }],
    });
    services.listRCAs.mockResolvedValue({
      results: [{ id: 5, title: 'Disk failure', status: 'approved' }],
    });
    services.editAction.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { root_cause_analysis: ['RCA belongs to a different problem.'] },
      },
    });

    renderWith(<Actions problemId="1" />);

    fireEvent.change(await screen.findByLabelText('RCA for action 1'), {
      target: { value: '5' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save RCA' }));

    expect(await screen.findByText('RCA belongs to a different problem.')).toBeTruthy();
    expect(screen.queryByText('RCA link updated.')).toBeNull();
    expect(services.listActions).toHaveBeenCalledTimes(1);
  });

  test('prevents duplicate RCA-link updates while the request is in flight', async () => {
    services.listActions.mockResolvedValue({
      results: [{ ...PLANNED, root_cause_analysis: null }],
    });
    services.listRCAs.mockResolvedValue({
      results: [{ id: 5, title: 'Disk failure', status: 'approved' }],
    });
    let resolveEdit;
    services.editAction.mockImplementation(() => new Promise((resolve) => {
      resolveEdit = resolve;
    }));

    renderWith(<Actions problemId="1" />);

    fireEvent.change(await screen.findByLabelText('RCA for action 1'), {
      target: { value: '5' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save RCA' }));

    expect(services.editAction).toHaveBeenCalledTimes(1);
    const save = screen.getByRole('button', { name: 'Save RCA' });
    expect(save.disabled).toBe(true);
    fireEvent.click(save);
    expect(services.editAction).toHaveBeenCalledTimes(1);

    resolveEdit({ ...PLANNED, root_cause_analysis: 5 });

    expect(await screen.findByText('RCA link updated.')).toBeTruthy();
    await waitFor(() => expect(services.listActions).toHaveBeenCalledTimes(2));
  });
});

describe('Workaround workflow', () => {
  const renderWorkarounds = async () => {
    renderWith(<Workarounds problemId="1" />);
    await screen.findByPlaceholderText('Workaround title');
  };

  test('create is disabled while the title is empty', async () => {
    await renderWorkarounds();
    expect(screen.getByRole('button', { name: 'Create Workaround' }).disabled).toBe(true);
  });

  test('create is disabled while steps are empty or whitespace', async () => {
    await renderWorkarounds();
    fireEvent.change(screen.getByPlaceholderText('Workaround title'), {
      target: { value: 'Restart service' },
    });
    fireEvent.change(screen.getByPlaceholderText('Steps'), {
      target: { value: '   ' },
    });
    expect(screen.getByRole('button', { name: 'Create Workaround' }).disabled).toBe(true);
  });

  test('whitespace-only title and steps are rejected on direct submit', async () => {
    await renderWorkarounds();
    fireEvent.change(screen.getByPlaceholderText('Workaround title'), {
      target: { value: '   ' },
    });
    fireEvent.change(screen.getByPlaceholderText('Steps'), {
      target: { value: '   ' },
    });
    const form = screen.getByRole('button', { name: 'Create Workaround' }).closest('form');
    fireEvent.submit(form);
    expect(services.createWorkaround).not.toHaveBeenCalled();
  });

  test('create becomes available with valid title and steps and sends both fields', async () => {
    await renderWorkarounds();
    fireEvent.change(screen.getByPlaceholderText('Workaround title'), {
      target: { value: '  Restart service  ' },
    });
    fireEvent.change(screen.getByPlaceholderText('Steps'), {
      target: { value: '  1. Restart worker  ' },
    });
    const create = screen.getByRole('button', { name: 'Create Workaround' });
    expect(create.disabled).toBe(false);
    fireEvent.click(create);

    await waitFor(() => {
      expect(services.createWorkaround).toHaveBeenCalledWith('1', {
        title: 'Restart service',
        steps: '1. Restart worker',
      });
    });
    await waitFor(() => expect(services.listWorkarounds).toHaveBeenCalledTimes(2));
  });

  test.each([
    ['Submit', 'draft', 'submitWorkaround', 3],
    ['Approve', 'submitted', 'approveWorkaround', 4],
    ['Publish', 'approved', 'publishWorkaround', 5],
    ['Expire', 'published', 'expireWorkaround', 6],
    ['Retire', 'published', 'retireWorkaround', 6],
  ])('sends expected_record_version for %s', async (label, status, helper, version) => {
    services.listWorkarounds.mockResolvedValue({
      results: [{ id: 11, title: 'Fix', steps: 'do it', status, version }],
    });
    services[helper].mockResolvedValue({ id: 11, title: 'Fix', steps: 'do it', status, version });

    renderWith(<Workarounds problemId="1" />);
    fireEvent.click(await screen.findByText(label));

    await waitFor(() => expect(services[helper]).toHaveBeenCalledWith(11, {
      expected_record_version: version,
    }));
  });

  test('a successful transition supplies the refreshed version to the next transition', async () => {
    services.listWorkarounds
      .mockResolvedValueOnce({
        results: [{ id: 12, title: 'Fix', steps: 'do it', status: 'draft', version: 7 }],
      })
      .mockResolvedValue({
        results: [{ id: 12, title: 'Fix', steps: 'do it', status: 'submitted', version: 8 }],
      });
    services.submitWorkaround.mockResolvedValue({
      id: 12, title: 'Fix', steps: 'do it', status: 'submitted', version: 8,
    });
    services.approveWorkaround.mockResolvedValue({
      id: 12, title: 'Fix', steps: 'do it', status: 'approved', version: 9,
    });

    renderWith(<Workarounds problemId="1" />);
    fireEvent.click(await screen.findByText('Submit'));
    await waitFor(() => expect(services.submitWorkaround).toHaveBeenCalledWith(12, {
      expected_record_version: 7,
    }));

    fireEvent.click(await screen.findByText('Approve'));
    await waitFor(() => expect(services.approveWorkaround).toHaveBeenCalledWith(12, {
      expected_record_version: 8,
    }));
  });

  test('a stale-version conflict refreshes the record without retrying', async () => {
    services.listWorkarounds
      .mockResolvedValueOnce({
        results: [{ id: 13, title: 'Fix', steps: 'do it', status: 'submitted', version: 2 }],
      })
      .mockResolvedValue({
        results: [{ id: 13, title: 'Fix', steps: 'do it', status: 'approved', version: 3 }],
      });
    services.approveWorkaround.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: 'Stale workaround version: sent 2, current is 3.' },
      },
    });

    renderWith(<Workarounds problemId="1" />);
    fireEvent.click(await screen.findByText('Approve'));

    expect(await screen.findByText(/Version conflict/)).toBeTruthy();
    await waitFor(() => expect(services.listWorkarounds).toHaveBeenCalledTimes(2));
    expect(services.approveWorkaround).toHaveBeenCalledTimes(1);
    expect(services.approveWorkaround).toHaveBeenCalledWith(13, {
      expected_record_version: 2,
    });
    expect(screen.queryByText('Approve')).toBeNull();
  });

  test('duplicate lifecycle submissions for one record are prevented', async () => {
    let resolveSubmit;
    services.listWorkarounds.mockResolvedValue({
      results: [{ id: 14, title: 'Fix', steps: 'do it', status: 'draft', version: 1 }],
    });
    services.submitWorkaround.mockImplementation(() => new Promise((resolve) => {
      resolveSubmit = resolve;
    }));

    renderWith(<Workarounds problemId="1" />);
    const submit = await screen.findByText('Submit');
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(services.submitWorkaround).toHaveBeenCalledTimes(1);

    resolveSubmit({ id: 14, title: 'Fix', steps: 'do it', status: 'submitted', version: 2 });
    await waitFor(() => expect(services.listWorkarounds).toHaveBeenCalledTimes(2));
  });
});

describe('Validation contract', () => {
  const ACTION_LABELS = ['Start', 'Pass', 'Fail', 'Inconclusive', 'Cancel'];

  const row = (overrides = {}) => ({
    id: 3, title: 'Failover', status: 'draft', passed: false, version: 3,
    ...overrides,
  });

  test('renders an embedded section heading without duplicating the page header', async () => {
    services.listValidations.mockResolvedValue({ results: [] });
    renderWith(<Validations problemId="1" embedded />);
    expect(await screen.findByRole('heading', { name: 'Validations' })).toBeTruthy();
    expect(screen.queryByText('Validation runs recorded against this problem')).toBeNull();
    expect(screen.getByPlaceholderText('Validation title')).toBeTruthy();
  });

  test('shows status and sends trimmed test_plan rather than validation_status', async () => {
    services.listValidations.mockResolvedValue({ results: [row()] });
    renderWith(<Validations problemId="1" embedded />);
    expect(await screen.findByText('Status')).toBeTruthy();
    expect(screen.queryByText('validation_status')).toBeNull();
    fireEvent.change(screen.getByPlaceholderText('Validation title'), {
      target: { value: '  New run  ' },
    });
    fireEvent.change(screen.getByPlaceholderText('Test plan'), {
      target: { value: '  kill node  ' },
    });
    fireEvent.click(screen.getByText('Create Validation'));
    await waitFor(() => expect(services.createValidation).toHaveBeenCalledWith('1', {
      title: 'New run', test_plan: 'kill node',
    }));
    await waitFor(() => expect(services.listValidations).toHaveBeenCalledTimes(2));
  });

  test('rejects a whitespace-only title without calling the API', async () => {
    services.listValidations.mockResolvedValue({ results: [] });
    renderWith(<Validations problemId="1" embedded />);
    fireEvent.change(await screen.findByPlaceholderText('Validation title'), {
      target: { value: '   ' },
    });
    const create = screen.getByRole('button', { name: 'Create Validation' });
    expect(create.disabled).toBe(true);
    fireEvent.submit(create.closest('form'));
    expect(services.createValidation).not.toHaveBeenCalled();
  });

  test.each([
    ['Start', 'draft', 'startValidation', 3, 4],
    ['Pass', 'draft', 'passValidation', 3, 4],
    ['Fail', 'draft', 'failValidation', 3, 4],
    ['Inconclusive', 'draft', 'markValidationInconclusive', 3, 4],
    ['Cancel', 'draft', 'cancelValidation', 3, 4],
  ])('sends the current version for %s', async (
    label, status, helper, version, nextVersion,
  ) => {
    services.listValidations.mockResolvedValue({
      results: [row({ status, version })],
    });
    services[helper].mockResolvedValue(row({ version: nextVersion }));
    renderWith(<Validations problemId="1" embedded />);
    const table = await screen.findByRole('table');
    fireEvent.click(within(table).getByRole('button', { name: label }));
    await waitFor(() => expect(services[helper]).toHaveBeenCalledWith(3, {
      expected_record_version: version,
    }));
    await waitFor(() => expect(services.listValidations).toHaveBeenCalledTimes(2));
  });

  test.each([
    ['draft', ['Start', 'Pass', 'Fail', 'Inconclusive', 'Cancel']],
    ['in_progress', ['Pass', 'Fail', 'Inconclusive', 'Cancel']],
    ['verified', []],
    ['failed', []],
    ['inconclusive', []],
    ['cancelled', []],
  ])('shows only valid controls for %s', async (status, allowed) => {
    services.listValidations.mockResolvedValue({
      results: [row({ status, passed: status === 'verified', version: 2 })],
    });
    renderWith(<Validations problemId="1" embedded />);
    await screen.findByText('Failover');
    const table = within(screen.getByRole('table'));
    for (const label of ACTION_LABELS) {
      const button = table.queryByRole('button', { name: label });
      if (allowed.includes(label)) expect(button).toBeTruthy();
      else expect(button).toBeNull();
    }
  });

  test('hides all mutation controls from non-staff users', async () => {
    auth.current = { isStaff: false };
    services.listValidations.mockResolvedValue({ results: [row()] });
    renderWith(<Validations problemId="1" embedded />);
    expect(await screen.findByText('Failover')).toBeTruthy();
    expect(screen.queryByPlaceholderText('Validation title')).toBeNull();
    const table = within(screen.getByRole('table'));
    for (const label of ACTION_LABELS) {
      expect(table.queryByRole('button', { name: label })).toBeNull();
    }
  });

  test('uses the refreshed version for the next transition', async () => {
    services.listValidations
      .mockResolvedValueOnce({ results: [row({ version: 7 })] })
      .mockResolvedValue({ results: [row({ status: 'in_progress', version: 8 })] });
    services.startValidation.mockResolvedValue(row({ status: 'in_progress', version: 8 }));
    services.passValidation.mockResolvedValue(row({
      status: 'verified', passed: true, version: 9,
    }));
    renderWith(<Validations problemId="1" embedded />);
    fireEvent.click(within(await screen.findByRole('table')).getByRole('button', { name: 'Start' }));
    await waitFor(() => expect(services.startValidation).toHaveBeenCalledWith(3, {
      expected_record_version: 7,
    }));
    fireEvent.click(within(screen.getByRole('table')).getByRole('button', { name: 'Pass' }));
    await waitFor(() => expect(services.passValidation).toHaveBeenCalledWith(3, {
      expected_record_version: 8,
    }));
  });

  test('a stale-version conflict refreshes the list without retrying', async () => {
    services.listValidations
      .mockResolvedValueOnce({ results: [row({ version: 2 })] })
      .mockResolvedValue({ results: [row({ status: 'in_progress', version: 3 })] });
    services.startValidation.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: 'Stale validation version: sent 2, current is 3.' },
      },
    });
    renderWith(<Validations problemId="1" embedded />);
    fireEvent.click(within(await screen.findByRole('table')).getByRole('button', { name: 'Start' }));
    expect(await screen.findByText(/Version conflict/)).toBeTruthy();
    expect(screen.getByText(/Stale validation version/)).toBeTruthy();
    await waitFor(() => expect(services.listValidations).toHaveBeenCalledTimes(2));
    expect(services.startValidation).toHaveBeenCalledTimes(1);
    expect(services.startValidation).toHaveBeenCalledWith(3, {
      expected_record_version: 2,
    });
    expect(within(screen.getByRole('table')).queryByRole('button', { name: 'Start' })).toBeNull();
  });

  test('keeps ordinary API errors distinct from version conflicts', async () => {
    services.listValidations.mockResolvedValue({ results: [row()] });
    services.passValidation.mockRejectedValue({
      response: { data: { detail: 'Backend refused this validation.' } },
    });
    renderWith(<Validations problemId="1" embedded />);
    fireEvent.click(within(await screen.findByRole('table')).getByRole('button', { name: 'Pass' }));
    expect(await screen.findByText('Backend refused this validation.')).toBeTruthy();
    expect(screen.queryByText(/Version conflict/)).toBeNull();
    expect(services.listValidations).toHaveBeenCalledTimes(1);
  });

  test('duplicate lifecycle submissions for one record are prevented', async () => {
    let resolveStart;
    services.listValidations.mockResolvedValue({ results: [row()] });
    services.startValidation.mockImplementation(() => new Promise((resolve) => {
      resolveStart = resolve;
    }));
    renderWith(<Validations problemId="1" embedded />);
    const start = within(await screen.findByRole('table')).getByRole('button', { name: 'Start' });
    fireEvent.click(start);
    fireEvent.click(start);
    expect(services.startValidation).toHaveBeenCalledTimes(1);
    resolveStart(row({ status: 'in_progress', version: 4 }));
    await waitFor(() => expect(services.listValidations).toHaveBeenCalledTimes(2));
  });
});

describe('Exception contract', () => {
  const ROW = {
    id: 4, title: 'Accept risk', exception_type: 'operational', status: 'active',
    reason: 'temp', created_by_username: 'author', version: 3,
  };
  const futureDate = () => {
    const date = new Date();
    date.setDate(date.getDate() + 30);
    return [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, '0'),
      String(date.getDate()).padStart(2, '0'),
    ].join('-');
  };
  const expectedExpiry = (value) => new Date(`${value}T23:59:59`).toISOString();

  test('exposes the supported exception types and loads the problem-scoped list', async () => {
    renderWith(<Exceptions problemId="1" />);
    expect(await screen.findByText('No exceptions yet')).toBeTruthy();
    expect(services.listExceptions).toHaveBeenCalledWith('1');
    expect(Array.from(screen.getByLabelText('Exception type').options).map((o) => o.value))
      .toEqual(['operational', 'unknown_root_cause', 'critical']);
  });

  test('renders exception metadata and blocks self-approval', async () => {
    services.listExceptions.mockResolvedValue({
      results: [{ ...ROW, created_by_username: 'manager', approved_by_username: 'admin' }],
    });
    renderWith(<Exceptions problemId="1" />);

    expect(await screen.findByText('Accept risk')).toBeTruthy();
    expect(screen.getByText('operational')).toBeTruthy();
    expect(screen.getByText('admin')).toBeTruthy();
    expect(screen.getByText('Approve').disabled).toBe(true);
    expect(screen.queryByText('Risk')).toBeNull();
  });

  test('creates with verified fields, trimmed text, and no legacy field names', async () => {
    const expiryDate = futureDate();
    renderWith(<Exceptions problemId="1" />);
    fireEvent.change(screen.getByPlaceholderText('Exception title'), { target: { value: '  Temp  ' } });
    fireEvent.change(screen.getByLabelText('Exception type'), { target: { value: 'critical' } });
    fireEvent.change(screen.getByPlaceholderText('Reason'), { target: { value: '  why  ' } });
    fireEvent.change(screen.getByPlaceholderText('Conditions'), { target: { value: '  peak hours  ' } });
    fireEvent.change(screen.getByLabelText('Expires at'), { target: { value: expiryDate } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Exception' }));

    await waitFor(() => {
      expect(services.createException).toHaveBeenCalledWith('1', {
        title: 'Temp',
        exception_type: 'critical',
        reason: 'why',
        conditions: 'peak hours',
        expires_at: expectedExpiry(expiryDate),
      });
    });
    expect(services.createException.mock.calls[0][1].expires_at)
      .toMatch(/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/);
    expect(await screen.findByText('Exception created.')).toBeTruthy();
    await waitFor(() => expect(services.listExceptions).toHaveBeenCalledTimes(2));
  });

  test('does not submit a whitespace-only title', async () => {
    renderWith(<Exceptions problemId="1" />);
    fireEvent.change(screen.getByPlaceholderText('Exception title'), { target: { value: '   ' } });
    const form = screen.getByRole('button', { name: 'Create Exception' }).closest('form');
    fireEvent.submit(form);

    expect(services.createException).not.toHaveBeenCalled();
  });

  test.each([
    ['Submit', 'draft', 'submitException'],
    ['Approve', 'active', 'approveException'],
    ['Expire', 'active', 'expireException'],
  ])('sends %s with the current version token', async (label, status, helper) => {
    services.listExceptions.mockResolvedValue({
      results: [{ ...ROW, status, version: 7 }],
    });
    services[helper].mockResolvedValue({ ...ROW, status, version: 8 });

    renderWith(<Exceptions problemId="1" />);
    fireEvent.click(await screen.findByText(label));

    await waitFor(() => {
      expect(services[helper]).toHaveBeenCalledWith(4, { expected_record_version: 7 });
    });
    expect(await screen.findByText(`${label} succeeded.`)).toBeTruthy();
    await waitFor(() => expect(services.listExceptions).toHaveBeenCalledTimes(2));
  });

  test.each([
    ['Reject', 'reject', 'rejection', 'rejectException', 'A rejection reason is required.'],
    ['Revoke', 'revoke', 'revocation', 'revokeException', 'A revocation reason is required.'],
  ])('validates and sends a trimmed %s reason', async (
    button, action, reasonLabel, helper, missingMessage,
  ) => {
    services.listExceptions.mockResolvedValue({
      results: [{ ...ROW, status: 'active', version: 9 }],
    });
    services[helper].mockResolvedValue({
      ...ROW,
      status: action === 'reject' ? 'rejected' : 'revoked',
      version: 10,
    });

    renderWith(<Exceptions problemId="1" />);
    fireEvent.click(await screen.findByText(button));

    const field = screen.getByLabelText(`${reasonLabel[0].toUpperCase()}${reasonLabel.slice(1)} reason`);
    const confirm = screen.getByRole('button', { name: `Confirm ${reasonLabel}` });
    expect(confirm.disabled).toBe(false);
    fireEvent.change(field, { target: { value: '   ' } });
    fireEvent.click(confirm);
    expect(await screen.findByText(missingMessage)).toBeTruthy();
    expect(services[helper]).not.toHaveBeenCalled();

    fireEvent.change(field, { target: { value: '  documented risk  ' } });
    fireEvent.click(confirm);

    await waitFor(() => {
      expect(services[helper]).toHaveBeenCalledWith(4, {
        expected_record_version: 9,
        reason: 'documented risk',
      });
    });
    expect(await screen.findByText(`${button} succeeded.`)).toBeTruthy();
  });

  test('shows backend reason validation errors and keeps the reason form open', async () => {
    services.listExceptions.mockResolvedValue({ results: [ROW] });
    services.rejectException.mockRejectedValue({
      response: { data: { reason: ['A rejection reason is required.'] } },
    });

    renderWith(<Exceptions problemId="1" />);
    fireEvent.click(await screen.findByText('Reject'));
    fireEvent.change(screen.getByLabelText('Rejection reason'), {
      target: { value: 'not blank' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm rejection' }));

    expect((await screen.findByRole('alert')).textContent)
      .toContain('reason: A rejection reason is required.');
    expect(screen.getByLabelText('Rejection reason')).toBeTruthy();
  });

  test('hides all mutation controls from non-staff users', async () => {
    auth.current = {
      isStaff: false, isManagerOrAdmin: false, user: { username: 'employee' },
    };
    services.listExceptions.mockResolvedValue({ results: [ROW] });

    renderWith(<Exceptions problemId="1" />);
    expect(await screen.findByText('Accept risk')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create Exception' })).toBeNull();
    ['Submit', 'Approve', 'Reject', 'Revoke', 'Expire'].forEach((label) => {
      expect(screen.queryByText(label)).toBeNull();
    });
  });

  test('support staff cannot approve or reject but can use staff transitions', async () => {
    auth.current = {
      isStaff: true, isManagerOrAdmin: false, user: { username: 'support' },
    };
    services.listExceptions.mockResolvedValue({ results: [ROW] });

    renderWith(<Exceptions problemId="1" />);
    expect(await screen.findByText('Accept risk')).toBeTruthy();
    expect(screen.getByText('Revoke')).toBeTruthy();
    expect(screen.getByText('Expire')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Create Exception' })).toBeTruthy();
    expect(screen.queryByText('Approve')).toBeNull();
    expect(screen.queryByText('Reject')).toBeNull();
  });

  test('prevents duplicate lifecycle submissions', async () => {
    let resolveSubmit;
    services.listExceptions.mockResolvedValue({
      results: [{ ...ROW, status: 'draft', version: 2 }],
    });
    services.submitException.mockImplementation(() => new Promise((resolve) => {
      resolveSubmit = resolve;
    }));

    renderWith(<Exceptions problemId="1" />);
    const submit = await screen.findByText('Submit');
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(services.submitException).toHaveBeenCalledTimes(1);

    resolveSubmit({ ...ROW, status: 'active', version: 3 });
    await waitFor(() => expect(services.listExceptions).toHaveBeenCalledTimes(2));
  });

  test('refreshes on a stale-version conflict without retrying', async () => {
    services.listExceptions
      .mockResolvedValueOnce({ results: [{ ...ROW, status: 'active', version: 2 }] })
      .mockResolvedValue({ results: [{ ...ROW, status: 'approved', version: 3 }] });
    services.approveException.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: 'Stale exception version: sent 2, current is 3.' },
      },
    });

    renderWith(<Exceptions problemId="1" />);
    fireEvent.click(await screen.findByText('Approve'));

    expect(await screen.findByText(/Version conflict/)).toBeTruthy();
    await waitFor(() => expect(services.listExceptions).toHaveBeenCalledTimes(2));
    expect(services.approveException).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Approve')).toBeNull();
  });

  test('surfaces a load error without hiding the create form', async () => {
    services.listExceptions.mockRejectedValueOnce(new Error('exceptions endpoint down'));

    renderWith(<Exceptions problemId="1" />);
    expect(await screen.findByText('Could not load exceptions.')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Exceptions' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Create Exception' })).toBeTruthy();
  });
});

describe('Timeline contract', () => {
  const EVENT_TYPES = [
    'milestone', 'investigation_start', 'root_cause_found',
    'workaround_implemented', 'action_taken', 'validation_completed',
    'fix_implemented', 'problem_resolved', 'problem_closed',
    'exception_granted', 'exception_denied',
  ];
  const SOURCES = [
    'manual', 'ticket', 'major_incident', 'change_review',
    'knowledge', 'monitoring', 'cmdb',
  ];

  test('exposes exactly the backend event-type and source choices', async () => {
    services.problemTimeline.mockResolvedValue({ results: [] });
    renderWith(<Timeline problemId="1" />);
    expect(await screen.findByText('No timeline events yet')).toBeTruthy();

    expect(Array.from(screen.getByLabelText('Type').options).map((o) => o.value))
      .toEqual(EVENT_TYPES);
    expect(Array.from(screen.getByLabelText('Source').options).map((o) => o.value))
      .toEqual(SOURCES);
  });

  test('shows loading and then the empty state', async () => {
    let resolveList;
    services.problemTimeline.mockImplementation(() => new Promise((resolve) => {
      resolveList = resolve;
    }));
    renderWith(<Timeline problemId="1" />);

    expect(screen.getByRole('status', { name: 'Loading' })).toBeTruthy();
    resolveList({ results: [] });
    expect(await screen.findByText('No timeline events yet')).toBeTruthy();
  });

  test('lists by occurred_at and creates with the real fields', async () => {
    services.problemTimeline.mockResolvedValue({
      results: [{
        id: 5, event_type: 'milestone', title: 'Kickoff',
        source: 'manual', occurred_at: '2026-01-01T09:00:00Z', recorded_by_username: 'support',
      }],
    });
    services.createTimelineEvent.mockResolvedValue({});
    renderWith(<Timeline problemId="1" />);
    expect(await screen.findByText('Kickoff')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'root_cause_found' } });
    fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'ticket' } });
    fireEvent.change(screen.getByPlaceholderText('Event title'), { target: { value: 'Review' } });
    fireEvent.click(screen.getByText('Add Timeline Event'));

    await waitFor(() => {
      const payload = services.createTimelineEvent.mock.calls[0][1];
      expect(payload.title).toBe('Review');
      expect(payload.event_type).toBe('root_cause_found');
      expect(payload.source).toBe('ticket');
      expect(payload).toHaveProperty('occurred_at');
      expect(payload).not.toHaveProperty('recorded_at');
    });
    expect(await screen.findByText('Timeline event added.')).toBeTruthy();
    await waitFor(() => expect(services.problemTimeline).toHaveBeenCalledTimes(2));
  });

  test('hides mutation controls from non-staff users', async () => {
    auth.current = {
      isStaff: false,
      isManagerOrAdmin: false,
      user: { username: 'employee' },
    };
    services.problemTimeline.mockResolvedValue({
      results: [{ id: 5, event_type: 'milestone', title: 'Kickoff', source: 'manual' }],
    });
    renderWith(<Timeline problemId="1" />);

    expect(await screen.findByText('Kickoff')).toBeTruthy();
    expect(screen.queryByText('Add Timeline Event')).toBeNull();
    expect(screen.queryByPlaceholderText('Event title')).toBeNull();
  });

  test('surfaces a load error without hiding the timeline', async () => {
    services.problemTimeline.mockRejectedValueOnce(new Error('timeline endpoint down'));
    renderWith(<Timeline problemId="1" />);

    expect(await screen.findByText('Could not load the timeline.')).toBeTruthy();
    expect(screen.getByText('Timeline')).toBeTruthy();
    expect(screen.getByPlaceholderText('Event title')).toBeTruthy();
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


