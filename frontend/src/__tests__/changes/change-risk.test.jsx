import React from 'react';
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

vi.mock('../../shared/changes-utils', () => ({
  parseApiError: (error) => ({
    global:
      error?.response?.data?.detail ||
      error?.response?.data?.message ||
      error?.message ||
      '',
    fields: {},
  }),
}));

import { ChangeRisk } from '../../pages/changes/ChangeRisk';

const change = {
  id: 7,
  change_number: 'CHG-2026-007',
  title: 'Database maintenance',
  status: 'submitted',
  risk_level: 'medium',
  calculated_risk_score: 24,
};

const scores = {
  service_impact_score: 2,
  user_impact_score: 2,
  complexity_score: 3,
  reversibility_score: 2,
  test_coverage_score: 2,
  implementation_experience_score: 3,
  timing_risk_score: 2,
  dependency_risk_score: 2,
  security_risk_score: 2,
  data_integrity_risk_score: 2,
};

const assessment = {
  id: 15,
  change: 7,
  assessment_version: 1,
  ...scores,
  total_score: 22,
  calculated_level: 'medium',
  override_level: '',
  override_reason: '',
  assessed_by_email: 'manager@example.com',
  assessed_at: '2026-11-28T05:00:00Z',
};

function setupRole(role = 'it_manager') {
  mockAuth.mockReturnValue({
    role,
    isManagerOrAdmin: ['it_manager', 'system_admin'].includes(role),
  });
}

function setupInitialLoad({
  changeData = change,
  assessmentData = [],
} = {}) {
  mockGet
    .mockResolvedValueOnce({ data: changeData })
    .mockResolvedValueOnce({ data: { results: assessmentData } });
}

function renderPage() {
  return render(<ChangeRisk match={{ params: { id: '7' } }} />);
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockAuth.mockReset();
  setupRole();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ChangeRisk', () => {
  it('loads the change and its risk assessment history from the real API endpoints', async () => {
    setupInitialLoad({ assessmentData: [assessment] });

    renderPage();

    expect(await screen.findByText('Database maintenance')).toBeTruthy();
    expect(screen.getAllByText('22')).toHaveLength(2);

    expect(mockGet).toHaveBeenNthCalledWith(1, '/changes/7/');
    expect(mockGet).toHaveBeenNthCalledWith(
      2,
      '/changes/risk-assessments/?change=7',
    );
  });

  it('renders all ten backend-defined score factors', async () => {
    setupInitialLoad();
    renderPage();

    expect(await screen.findByText('Risk questionnaire')).toBeTruthy();

    for (const label of [
      'Service impact',
      'User impact',
      'Implementation complexity',
      'Reversibility',
      'Test coverage',
      'Implementation experience',
      'Timing risk',
      'Dependency risk',
      'Security risk',
      'Data integrity risk',
    ]) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }

    expect(screen.queryByLabelText('Affected users')).toBeNull();
  });

  it('requires all ten scores and submits integer values to calculate_risk', async () => {
    setupInitialLoad();
    mockPost.mockResolvedValueOnce({ data: { id: 15 } });

    mockGet
      .mockResolvedValueOnce({ data: change })
      .mockResolvedValueOnce({ data: { results: [assessment] } });

    renderPage();

    await screen.findByText('Database maintenance');

    for (const [key, value] of Object.entries(scores)) {
      fireEvent.change(document.getElementById(key), {
        target: { value: String(value) },
      });
    }

    fireEvent.click(screen.getByRole('button', { name: 'Calculate risk' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledTimes(1);
    });

    expect(mockPost).toHaveBeenCalledWith(
      '/changes/7/calculate_risk/',
      scores,
    );

    expect(
      await screen.findByText('Risk assessment calculated and saved successfully.'),
    ).toBeTruthy();
  });

  it('requires a reason when an override level is selected', async () => {
    setupInitialLoad();
    renderPage();

    await screen.findByText('Database maintenance');

    fireEvent.change(document.getElementById('override-level'), {
      target: { value: 'high' },
    });

    for (const [key, value] of Object.entries(scores)) {
      fireEvent.change(document.getElementById(key), {
        target: { value: String(value) },
      });
    }

    fireEvent.click(screen.getByRole('button', { name: 'Calculate risk' }));

    expect(document.getElementById('override-reason').required).toBe(true);
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('confirms the latest assessment when the change is in risk_assessment status', async () => {
    const riskAssessmentChange = {
      ...change,
      status: 'risk_assessment',
    };

    setupInitialLoad({
      changeData: riskAssessmentChange,
      assessmentData: [assessment],
    });

    mockPost.mockResolvedValueOnce({ data: { id: 15 } });

    mockGet
      .mockResolvedValueOnce({
        data: { ...riskAssessmentChange, status: 'technical_review' },
      })
      .mockResolvedValueOnce({ data: { results: [assessment] } });

    renderPage();

    expect(
      await screen.findByRole('button', { name: 'Confirm risk assessment' }),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByRole('button', { name: 'Confirm risk assessment' }),
    );

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/changes/7/confirm_risk/',
        {},
      );
    });

    expect(
      await screen.findByText(
        'Risk assessment confirmed. The change has moved to Technical Review.',
      ),
    ).toBeTruthy();
  });

  it('keeps support users read-only', async () => {
    setupRole('it_support');
    setupInitialLoad({ assessmentData: [assessment] });

    renderPage();

    expect(await screen.findByText('Database maintenance')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Calculate risk' })).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'Confirm risk assessment' }),
    ).toBeNull();
    expect(screen.getByText('You have read-only access to this risk assessment.')).toBeTruthy();
  });

  it('keeps employees read-only', async () => {
    setupRole('employee');
    setupInitialLoad({ assessmentData: [assessment] });

    renderPage();

    expect(await screen.findByText('Database maintenance')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Calculate risk' })).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'Confirm risk assessment' }),
    ).toBeNull();
  });

  it('shows an empty state when no assessment exists', async () => {
    setupInitialLoad();
    renderPage();

    expect(
      await screen.findByText(
        'No risk assessment has been recorded for this change yet.',
      ),
    ).toBeTruthy();

    expect(screen.getByText('No previous assessments.')).toBeTruthy();
  });

  it('shows the API error when loading the change fails', async () => {
    mockGet.mockRejectedValueOnce({
      response: { data: { detail: 'Change access denied.' } },
    });

    renderPage();

    expect((await screen.findByRole('alert')).textContent).toContain(
      'Change access denied.',
    );
  });
});