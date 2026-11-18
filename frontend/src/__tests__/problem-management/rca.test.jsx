import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { RCA } from '../../components/problem-management/rca';
import { editRCA, getRCA } from '../../services/problem-management';

afterEach(cleanup);

vi.mock('../../services/problem-management', () => ({
  approveRCA: vi.fn(),
  createFactor: vi.fn(),
  createFiveWhy: vi.fn(),
  createRCA: vi.fn(),
  deleteFactor: vi.fn(),
  deleteFiveWhy: vi.fn(),
  editFactor: vi.fn(),
  editFiveWhy: vi.fn(),
  editRCA: vi.fn(),
  fiveWhys: vi.fn(),
  getRCA: vi.fn(),
  problemDetail: vi.fn(),
  rejectRCA: vi.fn(),
  rootCauseFactors: vi.fn(),
  submitRCA: vi.fn(),
  supersedeRCA: vi.fn(),
}));

const auth = vi.hoisted(() => ({ current: { isManagerOrAdmin: true, user: { username: 'manager' } } }));
vi.mock('../../auth', () => ({ useAuth: () => auth.current }));

const RCA_RECORD = {
  id: 1,
  problem: 1,
  title: 'Test RCA',
  description: 'Test description',
  status: 'draft',
  version: 3,
  created_by_username: 'author',
};

const renderRca = (props = {}) => render(
  <MemoryRouter>
    <RCA problemId="1" {...props} />
  </MemoryRouter>,
);

describe('RCA', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.current = { isManagerOrAdmin: true, user: { username: 'manager' } };
    getRCA.mockResolvedValue(RCA_RECORD);
    editRCA.mockResolvedValue({ ...RCA_RECORD, version: 4 });
  });

  test('renders RCA create form', async () => {
    renderRca();
    expect((await screen.findAllByText('Create RCA')).length).toBeGreaterThan(0);
  });

  test('renders RCA edit form', async () => {
    renderRca({ rcaId: '1' });
    expect(await screen.findByText('Title: Test RCA')).toBeTruthy();
  });

  test('renders submit/approve/reject buttons for manager', async () => {
    renderRca({ rcaId: '1' });
    expect(await screen.findByText('Submit RCA')).toBeTruthy();
    expect(screen.getByText('Approve RCA')).toBeTruthy();
    expect(screen.getByText('Reject RCA')).toBeTruthy();
  });

  test('sends the loaded version when updating', async () => {
    renderRca({ rcaId: '1' });
    fireEvent.click(await screen.findByText('Update RCA'));
    await waitFor(() => expect(editRCA).toHaveBeenCalledWith(
      '1',
      expect.objectContaining({ title: 'Test RCA', description: 'Test description' }),
      3,
    ));
  });

  test('blocks self-approval', async () => {
    getRCA.mockResolvedValue({ ...RCA_RECORD, created_by_username: 'manager' });
    renderRca({ rcaId: '1' });
    expect(await screen.findByText('You cannot approve your own RCA.')).toBeTruthy();
    const approve = await screen.findByText('Approve RCA');
    expect(approve.disabled).toBe(true);
  });

  test('keeps a final state immutable', async () => {
    getRCA.mockResolvedValue({ ...RCA_RECORD, status: 'approved' });
    renderRca({ rcaId: '1' });
    expect(await screen.findByText(/can no longer be edited/)).toBeTruthy();
    expect(screen.queryByText('Update RCA')).toBeNull();
    expect(screen.queryByText('Approve RCA')).toBeNull();
  });
});
