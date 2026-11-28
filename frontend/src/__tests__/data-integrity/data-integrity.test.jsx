import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: { get: (...args) => mockGet(...args) },
}));

vi.mock('../../auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { DataIntegrity } from '../../pages/data-integrity/DataIntegrity';

const REPORT = {
  issues: [
    {
      area: 'asset',
      code: 'asset_assigned_without_holder',
      object: 'Laptop LT-001',
      object_id: 12,
      detail: "Asset status is 'assigned' but no holder is set.",
      suggested_fix: "Clear the stale status or assign a valid holder.",
    },
    {
      area: 'assignment',
      code: 'assignment_duplicate_open',
      object: 'asset #24',
      detail: 'Asset has 2 open assignments.',
      suggested_fix: 'Return the asset(s) before assigning again.',
    },
  ],
  counts: { issues: 2, assets_checked: 50 },
  note: 'Read-only data-integrity report; repairs are explicit and human-driven.',
};

function admin() {
  mockAuth.mockReturnValue({ isAdmin: true });
}

function nonAdmin() {
  mockAuth.mockReturnValue({ isAdmin: false });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockGet.mockResolvedValue({ data: REPORT });
});

afterEach(() => cleanup());

describe('DataIntegrity', () => {
  it('restricts the page for non-admins without calling the API', () => {
    nonAdmin();
    render(<DataIntegrity />);

    expect(screen.getByText('System administrators only.')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('loads and displays the report summary and findings for admins', async () => {
    admin();
    render(<DataIntegrity />);

    expect(await screen.findByText('asset_assigned_without_holder')).toBeTruthy();
    expect(screen.getByText('assignment_duplicate_open')).toBeTruthy();
    expect(screen.getByText('Laptop LT-001')).toBeTruthy();
    expect(screen.getByText('asset #24')).toBeTruthy();
    expect(screen.getByText('50')).toBeTruthy();
    expect(screen.getByText('2 findings')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/common/data-integrity/');
  });

  it('refreshes the report when requested', async () => {
    admin();
    render(<DataIntegrity />);

    await screen.findByText('asset_assigned_without_holder');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh report' }));

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledTimes(2);
    });
  });

  it('shows an empty state when no issues are found', async () => {
    admin();
    mockGet.mockResolvedValueOnce({
      data: {
        issues: [],
        counts: { issues: 0, assets_checked: 12 },
        note: 'Read-only report.',
      },
    });

    render(<DataIntegrity />);

    expect(
      await screen.findByText('No integrity issues were found in the checked assets.'),
    ).toBeTruthy();
    expect(screen.getByText('12')).toBeTruthy();
  });

  it('shows an API error and allows retrying', async () => {
    admin();
    mockGet
      .mockRejectedValueOnce({
        response: { data: { detail: 'System Admin only.' } },
      })
      .mockResolvedValueOnce({ data: REPORT });

    render(<DataIntegrity />);

    expect(await screen.findByText('System Admin only.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('asset_assigned_without_holder')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('does not expose repair actions', async () => {
    admin();
    render(<DataIntegrity />);

    await screen.findByText('asset_assigned_without_holder');

    expect(screen.queryByRole('button', { name: /repair|fix issue/i })).toBeNull();
    expect(screen.getByText(/does not modify asset or assignment records/i)).toBeTruthy();
  });
});