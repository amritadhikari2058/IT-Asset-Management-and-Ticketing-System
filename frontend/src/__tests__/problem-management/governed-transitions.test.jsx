import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GovernedTransitions } from '../../components/problem-management/governed-transitions';
import { problemDetail, submitProblem } from '../../services/problem-management';

afterEach(cleanup);

vi.mock('../../services/problem-management', () => ({
  problemDetail: vi.fn(),
  submitProblem: vi.fn(),
  acceptProblem: vi.fn(),
  rejectProblem: vi.fn(),
  startInvestigation: vi.fn(),
  cancelProblem: vi.fn(),
  reopenProblem: vi.fn(),
}));

const auth = vi.hoisted(() => ({ current: { isStaff: true, isManagerOrAdmin: true } }));
vi.mock('../../auth', () => ({ useAuth: () => auth.current }));

const PROBLEM = {
  id: 1,
  problem_number: 'PRB-2026-000001',
  title: 'Test Problem',
  status: 'triage',
  version: 2,
};

const renderTransitions = () => render(
  <MemoryRouter>
    <GovernedTransitions problemId="1" />
  </MemoryRouter>,
);

describe('Governed Transitions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.current = { isStaff: true, isManagerOrAdmin: true };
    problemDetail.mockResolvedValue(PROBLEM);
    submitProblem.mockResolvedValue({ ...PROBLEM, status: 'investigating', version: 3 });
  });

  test('renders transition buttons for staff', async () => {
    renderTransitions();
    expect(await screen.findByText('Submit')).toBeTruthy();
    expect(screen.getByText('Accept')).toBeTruthy();
    expect(screen.getByText('Reject')).toBeTruthy();
  });

  test('renders manager buttons', async () => {
    renderTransitions();
    expect(await screen.findByText('Start Investigation')).toBeTruthy();
  });

  test('handles transition clicks with the loaded record version', async () => {
    renderTransitions();
    fireEvent.click(await screen.findByText('Submit'));
    await waitFor(() => expect(submitProblem).toHaveBeenCalledWith('1', { expected_record_version: 2 }));
  });

  test('surfaces a stale-version rejection without pretending it succeeded', async () => {
    submitProblem.mockRejectedValueOnce({
      response: { status: 409, data: { detail: 'This problem changed since you loaded it.' } },
    });
    renderTransitions();
    fireEvent.click(await screen.findByText('Submit'));
    expect(await screen.findByText('This problem changed since you loaded it.')).toBeTruthy();
  });

  test('hides every transition control from employees', async () => {
    auth.current = { isStaff: false, isManagerOrAdmin: false };
    renderTransitions();
    expect(await screen.findByText(/PRB-2026-000001/)).toBeTruthy();
    expect(screen.queryByText('Submit')).toBeNull();
    expect(screen.queryByText('Start Investigation')).toBeNull();
  });
});



