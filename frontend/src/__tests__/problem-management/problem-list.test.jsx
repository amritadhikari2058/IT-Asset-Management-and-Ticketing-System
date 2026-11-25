import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ProblemList } from '../../pages/problem-management/ProblemList';
import { problemList } from '../../services/problem-management';

afterEach(cleanup);

vi.mock('../../services/problem-management', () => ({ problemList: vi.fn() }));

const auth = vi.hoisted(() => ({ current: { isStaff: true } }));
vi.mock('../../auth', () => ({ useAuth: () => auth.current }));

const PAGE = {
  results: [{
    id: 1,
    problem_number: 'PRB-1',
    title: 'Printer keeps failing',
    status: 'investigating',
    priority: 'high',
    problem_type: 'reactive',
    owner_username: 'owner',
    service_name: 'Printing',
    category_name: 'Hardware',
  }],
  count: 1,
  next: null,
  previous: null,
};

const renderList = () => render(
  <MemoryRouter>
    <ProblemList />
  </MemoryRouter>,
);

describe('Problem List', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.current = { isStaff: true };
    problemList.mockResolvedValue(PAGE);
  });

  test('renders with loading state', () => {
    problemList.mockReturnValue(new Promise(() => {}));
    renderList();
    expect(screen.getByText('Loading problems…')).toBeTruthy();
  });

  test('renders empty state when no problems', async () => {
    problemList.mockResolvedValue({ results: [], count: 0, next: null, previous: null });
    renderList();
    expect(await screen.findByText('No problems found')).toBeTruthy();
  });

  test('renders rows returned by the API', async () => {
    renderList();
    expect(await screen.findByText('Printer keeps failing')).toBeTruthy();
    expect(screen.getByText('PRB-1')).toBeTruthy();
  });

  test('applies status filter', async () => {
    renderList();
    const select = await screen.findByLabelText('Status');
    fireEvent.change(select, { target: { value: 'investigating' } });
    await waitFor(() => expect(problemList).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'investigating', page: 1, page_size: 20 }),
    ));
  });

  test('applies priority filter', async () => {
    renderList();
    fireEvent.change(await screen.findByLabelText('Priority'), { target: { value: 'critical' } });
    await waitFor(() => expect(problemList).toHaveBeenLastCalledWith(
      expect.objectContaining({ priority: 'critical' }),
    ));
  });

  test('applies problem type filter', async () => {
    renderList();
    fireEvent.change(await screen.findByLabelText('Problem type'), { target: { value: 'major_problem' } });
    await waitFor(() => expect(problemList).toHaveBeenLastCalledWith(
      expect.objectContaining({ problem_type: 'major_problem' }),
    ));
  });

  test('applies owner filter', async () => {
    renderList();
    fireEvent.change(await screen.findByLabelText('Owner'), { target: { value: '7' } });
    await waitFor(() => expect(problemList).toHaveBeenLastCalledWith(
      expect.objectContaining({ owner: '7' }),
    ));
  });

  test('applies service filter', async () => {
    renderList();
    fireEvent.change(await screen.findByLabelText('Service'), { target: { value: '3' } });
    await waitFor(() => expect(problemList).toHaveBeenLastCalledWith(
      expect.objectContaining({ service: '3' }),
    ));
  });

  test('applies category filter', async () => {
    renderList();
    fireEvent.change(await screen.findByLabelText('Category'), { target: { value: '2' } });
    await waitFor(() => expect(problemList).toHaveBeenLastCalledWith(
      expect.objectContaining({ category: '2' }),
    ));
  });

  test('applies search input', async () => {
    renderList();
    fireEvent.change(screen.getByPlaceholderText('Search…'), { target: { value: 'test problem' } });
    await waitFor(() => expect(problemList).toHaveBeenLastCalledWith(
      expect.objectContaining({ search: 'test problem' }),
    ));
  });

  test('applies open/closed filter', async () => {
    renderList();
    fireEvent.click(await screen.findByLabelText('Open only'));
    await waitFor(() => expect(problemList).toHaveBeenLastCalledWith(
      expect.objectContaining({ is_open: true }),
    ));
  });

  test('shows create problem button for staff', async () => {
    renderList();
    expect(await screen.findByText('Create Problem')).toBeTruthy();
  });

  test('pages forward through DRF next links', async () => {
    problemList.mockResolvedValue({ ...PAGE, next: 'http://api/problems/?page=2' });
    renderList();
    fireEvent.click(await screen.findByRole('button', { name: /next/i }));
    await waitFor(() => expect(problemList).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2 }),
    ));
  });

  test('surfaces a load failure as an alert', async () => {
    problemList.mockRejectedValue(new Error('boom'));
    renderList();
    expect(await screen.findByText('Could not load problems.')).toBeTruthy();
  });

  test('hides the create control from employees', async () => {
    auth.current = { isStaff: false };
    renderList();
    expect(await screen.findByText('Printer keeps failing')).toBeTruthy();
    expect(screen.queryByText('Create Problem')).toBeNull();
  });
});



