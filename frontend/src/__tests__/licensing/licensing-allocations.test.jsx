import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock('../../auth', () => ({ useAuth: (...a) => mockAuth(...a) }));

import { LicenseAllocationsPage } from '../../pages/licensing/LicenseAllocations';

const STAFF_ROLES = ['system_admin', 'it_manager', 'it_support'];

function makeAuth(role) {
  const isSystemAdmin = role === 'system_admin';
  const isITManager = role === 'it_manager';
  const isITSupport = role === 'it_support';
  const isEmployee = role === 'employee';
  const isStaff = STAFF_ROLES.includes(role);
  return {
    access: 'token', isStaff, isAdmin: isSystemAdmin, isSystemAdmin, isITManager, isITSupport, isEmployee,
    canViewLicensing: isStaff || isEmployee,
    canManageLicenseAllocations: isStaff,
    canManageLicenseCompliance: isSystemAdmin || isITManager,
  };
}

const ALLOCATION = {
  id: 11,
  allocation_reference: 'LIC-2026-00001-SEAT-0001',
  product_name: 'Acrobat',
  agreement: 3,
  agreement_number: 'LIC-2026-00001',
  allocation_type: 'user',
  user_email: 'sam@x.io',
  asset_tag: null,
  status: 'active',
  assigned_at: '2026-01-05T10:00:00Z',
  last_verified_at: null,
};

const HISTORY = [
  {
    id: 501,
    event_type: 'allocation_revoked',
    previous_status: 'active',
    new_status: 'revoked',
    actor_email: 'manager@x.io',
    detail: { reason: 'Returned laptop' },
    created_at: '2026-02-01T09:30:00Z',
  },
];

function setupGet({ allocations = [ALLOCATION], history = HISTORY, historyError = null } = {}) {
  mockGet.mockImplementation(async (url) => {
    if (url.startsWith('/accounts/users/')) {
      return { data: { results: [{ id: 7, employee_id: 'E7', email: 'sam@x.io' }] } };
    }
    if (url.includes('/history/')) {
      if (historyError) throw historyError;
      return { data: history };
    }
    return { data: { results: allocations, count: allocations.length, next: null, previous: null } };
  });
}

function listCalls() {
  return mockGet.mock.calls.filter(([url]) => String(url).startsWith('/licensing/allocations/?'));
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockAuth.mockImplementation(() => makeAuth('it_manager'));
  mockPost.mockResolvedValue({ data: {} });
  setupGet();
});

afterEach(() => cleanup());

describe('License allocations - release workflow', () => {
  it('requires confirmation and posts the release reason to the release endpoint', async () => {
    render(<LicenseAllocationsPage />);
    await screen.findByText('Acrobat');

    fireEvent.click(screen.getByRole('button', { name: 'Release' }));

    expect(screen.getByRole('dialog', { name: /Release allocation LIC-2026-00001-SEAT-0001/ })).toBeTruthy();
    expect(screen.getByText(/marks the allocation/i)).toBeTruthy();
    expect(screen.getByText(/cannot be undone/i)).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Release reason/i), { target: { value: 'Returned laptop' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm release' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/licensing/allocations/11/release/', { reason: 'Returned laptop' });
    });
    await waitFor(() => {
      expect(screen.getByText(/Allocation LIC-2026-00001-SEAT-0001 released/)).toBeTruthy();
    });
    await waitFor(() => expect(listCalls().length).toBeGreaterThanOrEqual(2));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('sends an empty reason when none is provided so the backend default applies', async () => {
    render(<LicenseAllocationsPage />);
    await screen.findByText('Acrobat');

    fireEvent.click(screen.getByRole('button', { name: 'Release' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm release' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/licensing/allocations/11/release/', { reason: '' });
    });
  });

  it('prevents duplicate submissions while a release is in flight', async () => {
    let resolvePost;
    mockPost.mockImplementationOnce(() => new Promise((res) => { resolvePost = res; }));

    render(<LicenseAllocationsPage />);
    await screen.findByText('Acrobat');
    fireEvent.click(screen.getByRole('button', { name: 'Release' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm release' }));

    const pending = await screen.findByRole('button', { name: 'Releasing…' });
    expect(pending.disabled).toBe(true);
    fireEvent.click(pending);
    expect(mockPost).toHaveBeenCalledTimes(1);

    resolvePost({ data: {} });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it('shows the backend error and keeps the dialog open when release fails', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { detail: 'Allocation is already revoked.' } } });

    render(<LicenseAllocationsPage />);
    await screen.findByText('Acrobat');
    fireEvent.click(screen.getByRole('button', { name: 'Release' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm release' }));

    await waitFor(() => expect(screen.getByText('Allocation is already revoked.')).toBeTruthy());
    expect(screen.getByRole('dialog', { name: /Release allocation/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Confirm release' }).disabled).toBe(false);
  });

  it('shows a permission error for a forbidden release', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 403 } });

    render(<LicenseAllocationsPage />);
    await screen.findByText('Acrobat');
    fireEvent.click(screen.getByRole('button', { name: 'Release' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm release' }));

    await waitFor(() => {
      expect(screen.getByText('Forbidden: you lack permission for this action.')).toBeTruthy();
    });
  });
});

describe('License allocations - allocation history', () => {
  it('loads and renders history for the selected allocation', async () => {
    render(<LicenseAllocationsPage />);
    await screen.findByText('Acrobat');

    fireEvent.click(screen.getByRole('button', { name: 'History' }));

    await screen.findByText('Allocation Revoked');
    expect(mockGet).toHaveBeenCalledWith('/licensing/allocations/11/history/');
    expect(screen.getByText('Active → Revoked')).toBeTruthy();
    expect(screen.getByText('manager@x.io')).toBeTruthy();
    expect(screen.getByText('Reason: Returned laptop')).toBeTruthy();
  });

  it('shows an empty state when the allocation has no history', async () => {
    setupGet({ history: [] });
    render(<LicenseAllocationsPage />);
    await screen.findByText('Acrobat');

    fireEvent.click(screen.getByRole('button', { name: 'History' }));

    await screen.findByText('No history recorded for this allocation.');
  });

  it('shows a permission message when history is forbidden', async () => {
    setupGet({ historyError: { response: { status: 403 } } });
    render(<LicenseAllocationsPage />);
    await screen.findByText('Acrobat');

    fireEvent.click(screen.getByRole('button', { name: 'History' }));

    await screen.findByText('You do not have permission to view this allocation history.');
  });

  it('shows an error message when history fails to load', async () => {
    setupGet({ historyError: { response: { status: 500, data: { detail: 'History unavailable.' } } } });
    render(<LicenseAllocationsPage />);
    await screen.findByText('Acrobat');

    fireEvent.click(screen.getByRole('button', { name: 'History' }));

    await screen.findByText('History unavailable.');
  });
});

describe('License allocations - employee offboarding', () => {
  const PREVIEW = {
    data: {
      user_id: 7,
      count: 2,
      allocations: [
        {
          id: 11, product_name: 'Acrobat', agreement_number: 'LIC-2026-00001',
          allocation_reference: 'LIC-2026-00001-SEAT-0001', allocation_type: 'user', status: 'active',
        },
        {
          id: 12, product_name: 'Photoshop', agreement_number: 'LIC-2026-00002',
          allocation_reference: 'LIC-2026-00002-DEV-0001', allocation_type: 'device', status: 'assigned',
        },
      ],
    },
  };
  const RESULT = {
    data: {
      user_id: 7,
      revoked_count: 1,
      total_active: 2,
      results: [
        { allocation_id: 11, product: 'Acrobat', reference: 'LIC-2026-00001-SEAT-0001', success: true },
        { allocation_id: 12, product: 'Photoshop', reference: 'LIC-2026-00002-DEV-0001', success: false, error: 'Agreement is terminated.' },
      ],
    },
  };

  async function selectEmployee() {
    render(<LicenseAllocationsPage />);
    await screen.findByText('Acrobat');
    await screen.findByRole('option', { name: /E7/ });
    fireEvent.change(screen.getByLabelText('Employee'), { target: { value: '7' } });
  }

  it('previews affected seats without revoking anything', async () => {
    mockGet.mockImplementation(async (url) => {
      if (url.startsWith('/accounts/users/')) return { data: { results: [{ id: 7, employee_id: 'E7', email: 'sam@x.io' }] } };
      if (url.startsWith('/licensing/allocations/offboarding-preview/')) return PREVIEW;
      return { data: { results: [ALLOCATION], count: 1, next: null, previous: null } };
    });

    await selectEmployee();
    fireEvent.click(screen.getByRole('button', { name: 'Preview affected seats' }));

    await screen.findByText(/2 active or reserved allocation\(s\) would be revoked/);
    expect(mockGet).toHaveBeenCalledWith('/licensing/allocations/offboarding-preview/?user=7');
    expect(screen.getByText('Photoshop')).toBeTruthy();
    expect(screen.getByText('LIC-2026-00002')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('only revokes after explicit confirmation and reports per-allocation failures', async () => {
    mockGet.mockImplementation(async (url) => {
      if (url.startsWith('/accounts/users/')) return { data: { results: [{ id: 7, employee_id: 'E7', email: 'sam@x.io' }] } };
      if (url.startsWith('/licensing/allocations/offboarding-preview/')) return PREVIEW;
      return { data: { results: [ALLOCATION], count: 1, next: null, previous: null } };
    });
    mockPost.mockResolvedValueOnce(RESULT);

    await selectEmployee();
    fireEvent.click(screen.getByRole('button', { name: 'Preview affected seats' }));
    await screen.findByText(/would be revoked/);

    fireEvent.click(screen.getByRole('button', { name: 'Execute offboarding…' }));
    expect(screen.getByRole('dialog', { name: 'Confirm employee offboarding' })).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Revoke seats' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/licensing/allocations/offboard/', { user_id: 7 });
    });
    await waitFor(() => expect(document.body.textContent).toContain('Revoked 1 of 2 allocation(s).'));
    expect(document.body.textContent).toContain('Photoshop (LIC-2026-00002-DEV-0001): Agreement is terminated.');
    // Preview is cleared so the execution cannot be repeated with stale data.
    expect(screen.queryByRole('button', { name: 'Execute offboarding…' })).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('includes the offboarding reason in the execute request when provided', async () => {
    mockGet.mockImplementation(async (url) => {
      if (url.startsWith('/accounts/users/')) return { data: { results: [{ id: 7, employee_id: 'E7', email: 'sam@x.io' }] } };
      if (url.startsWith('/licensing/allocations/offboarding-preview/')) return PREVIEW;
      return { data: { results: [ALLOCATION], count: 1, next: null, previous: null } };
    });
    mockPost.mockResolvedValueOnce({ data: { revoked_count: 0, total_active: 0, results: [] } });

    await selectEmployee();
    fireEvent.click(screen.getByRole('button', { name: 'Preview affected seats' }));
    await screen.findByText(/would be revoked/);

    fireEvent.change(screen.getByLabelText(/Offboarding reason/i), { target: { value: 'Left the company' } });
    fireEvent.click(screen.getByRole('button', { name: 'Execute offboarding…' }));
    fireEvent.click(screen.getByRole('button', { name: 'Revoke seats' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/licensing/allocations/offboard/', {
        user_id: 7,
        reason: 'Left the company',
      });
    });
  });

  it('shows a preview error without enabling execution', async () => {
    mockGet.mockImplementation(async (url) => {
      if (url.startsWith('/accounts/users/')) return { data: { results: [{ id: 7, employee_id: 'E7', email: 'sam@x.io' }] } };
      if (url.startsWith('/licensing/allocations/offboarding-preview/')) {
        throw { response: { status: 404, data: { detail: 'User not found.' } } };
      }
      return { data: { results: [ALLOCATION], count: 1, next: null, previous: null } };
    });

    await selectEmployee();
    fireEvent.click(screen.getByRole('button', { name: 'Preview affected seats' }));

    await screen.findByText('User not found.');
    expect(screen.queryByRole('button', { name: 'Execute offboarding…' })).toBeNull();
    expect(mockPost).not.toHaveBeenCalled();
  });
});

describe('License allocations - access control', () => {
  it('denies the page to employees and does not request allocation data', async () => {
    mockAuth.mockImplementation(() => makeAuth('employee'));
    render(<LicenseAllocationsPage />);

    expect(screen.getByText('You do not have permission to access this page.')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });
});
