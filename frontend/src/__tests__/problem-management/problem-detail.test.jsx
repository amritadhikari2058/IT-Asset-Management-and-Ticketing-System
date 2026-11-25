import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ProblemDetail } from '../../pages/problem-management/ProblemDetail';
import { listTasks, problemDetail } from '../../services/problem-management';

afterEach(cleanup);

vi.mock('../../services/problem-management', () => ({
  fiveWhys: vi.fn(),
  getRCA: vi.fn(),
  linkedAssets: vi.fn(),
  linkedCIs: vi.fn(),
  linkedKBs: vi.fn(),
  linkedProducts: vi.fn(),
  linkedServices: vi.fn(),
  linkedTickets: vi.fn(),
  createKbLink: vi.fn(),
  deleteKbLink: vi.fn(),
  listEvidence: vi.fn(),
  listExceptions: vi.fn(),
  listTasks: vi.fn(),
  listValidations: vi.fn(),
  listWorkarounds: vi.fn(),
  problemDetail: vi.fn(),
  problemHistory: vi.fn(),
  problemReadiness: vi.fn(),
  rootCauseFactors: vi.fn(),
}));

const PROBLEM = {
  id: 1,
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
    problemDetail.mockResolvedValue(PROBLEM);
    const svc = await import('../../services/problem-management');
    ['fiveWhys', 'linkedAssets', 'linkedCIs', 'linkedProducts', 'linkedServices',
      'linkedTickets', 'linkedKBs', 'listEvidence', 'listExceptions', 'listTasks',
      'listValidations', 'listWorkarounds', 'problemHistory', 'rootCauseFactors'
    ].forEach((name) => {
      svc[name].mockResolvedValue({ results: [] });
    });
    svc.createKbLink.mockResolvedValue({});
    svc.deleteKbLink.mockResolvedValue({});
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
});



