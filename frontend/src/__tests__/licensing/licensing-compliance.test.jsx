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

import { LicenseCompliancePage } from '../../pages/licensing/LicenseCompliance';

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

const FINDING = {
  id: 21,
  title: 'Unlicensed Acrobat installation',
  description: 'Acrobat is installed on AST-1 without an assigned seat.',
  finding_type: 'unlicensed_installation',
  severity: 'high',
  product_name: 'Acrobat',
  agreement: 3,
  agreement_number: 'LIC-2026-00001',
  user_email: 'sam@x.io',
  asset_tag: 'AST-1',
  status: 'open',
  detected_at: '2026-02-01T00:00:00Z',
  resolved_at: null,
};

function setupGet(findings = [FINDING]) {
  mockGet.mockImplementation(async () => ({
    data: { results: findings, count: findings.length, next: null, previous: null },
  }));
}

function findingListCalls() {
  return mockGet.mock.calls.filter(([url]) => String(url).startsWith('/licensing/findings/?'));
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockAuth.mockImplementation(() => makeAuth('it_manager'));
  mockPost.mockResolvedValue({ data: { status: 'acknowledged' } });
  setupGet();
});

afterEach(() => cleanup());

describe('License compliance - remediation', () => {
  it('records a remediation note with optional re-evaluation and reports the resulting status', async () => {
    mockPost.mockResolvedValueOnce({ data: { status: 'resolved' } });
    render(<LicenseCompliancePage />);
    await screen.findByText('Unlicensed Acrobat installation');

    fireEvent.click(screen.getByRole('button', { name: 'Remediate' }));

    expect(screen.getByRole('dialog', { name: 'Remediate Finding 21' })).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Remediation notes/i), { target: { value: 'Removed the unlicensed copy' } });
    fireEvent.click(screen.getByLabelText(/Re-evaluate compliance/));
    fireEvent.click(screen.getByRole('button', { name: 'Record Remediation' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/licensing/findings/21/remediate/', {
        remediation_note: 'Removed the unlicensed copy',
        reevaluate: true,
      });
    });
    await screen.findByText(/the finding is now resolved/i);
    await waitFor(() => expect(findingListCalls().length).toBeGreaterThanOrEqual(2));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('requires a remediation note before submitting', async () => {
    render(<LicenseCompliancePage />);
    await screen.findByText('Unlicensed Acrobat installation');

    fireEvent.click(screen.getByRole('button', { name: 'Remediate' }));
    fireEvent.click(screen.getByRole('button', { name: 'Record Remediation' }));

    expect(screen.getByText('A remediation note is required.')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('reports the acknowledged status when no re-evaluation changed the finding', async () => {
    render(<LicenseCompliancePage />);
    await screen.findByText('Unlicensed Acrobat installation');

    fireEvent.click(screen.getByRole('button', { name: 'Remediate' }));
    fireEvent.change(screen.getByLabelText(/Remediation notes/i), { target: { value: 'Documented the workaround' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record Remediation' }));

    await screen.findByText('Remediation recorded. Finding status: Acknowledged.');
  });

  it('prevents duplicate remediation submissions', async () => {
    let resolvePost;
    mockPost.mockImplementationOnce(() => new Promise((res) => { resolvePost = res; }));
    render(<LicenseCompliancePage />);
    await screen.findByText('Unlicensed Acrobat installation');

    fireEvent.click(screen.getByRole('button', { name: 'Remediate' }));
    fireEvent.change(screen.getByLabelText(/Remediation notes/i), { target: { value: 'Patched' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record Remediation' }));

    const pending = await screen.findByRole('button', { name: 'Saving…' });
    expect(pending.disabled).toBe(true);
    fireEvent.click(pending);
    expect(mockPost).toHaveBeenCalledTimes(1);

    resolvePost({ data: { status: 'acknowledged' } });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it('surfaces a permission error when the backend rejects the remediation', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 403 } });
    render(<LicenseCompliancePage />);
    await screen.findByText('Unlicensed Acrobat installation');

    fireEvent.click(screen.getByRole('button', { name: 'Remediate' }));
    fireEvent.change(screen.getByLabelText(/Remediation notes/i), { target: { value: 'Tried to fix' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record Remediation' }));

    await screen.findByText('Forbidden: you lack permission for this action.');
    expect(screen.getByRole('dialog', { name: 'Remediate Finding 21' })).toBeTruthy();
  });
});

describe('License compliance - acknowledge and resolve', () => {
  it('acknowledges a finding and refreshes the list', async () => {
    render(<LicenseCompliancePage />);
    await screen.findByText('Unlicensed Acrobat installation');

    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/licensing/findings/21/acknowledge/');
    });
    await screen.findByText('Finding 21 acknowledged.');
  });

  it('shows the API error when acknowledging fails', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 403 } });
    render(<LicenseCompliancePage />);
    await screen.findByText('Unlicensed Acrobat installation');

    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge' }));
    await screen.findByText('Forbidden: you lack permission for this action.');
  });

  it('requires a note and an explicit confirmation before resolving', async () => {
    render(<LicenseCompliancePage />);
    await screen.findByText('Unlicensed Acrobat installation');

    fireEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    expect(screen.getByRole('dialog', { name: 'Resolve Finding 21' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Resolve finding' }));
    expect(screen.getByText('A resolution note is required.')).toBeTruthy();
    expect(mockPost).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Resolution note/i), { target: { value: 'Reinstalled a licensed copy' } });
    fireEvent.click(screen.getByRole('button', { name: 'Resolve finding' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/licensing/findings/21/resolve/', {
        resolution_note: 'Reinstalled a licensed copy',
      });
    });
    await screen.findByText('Finding 21 resolved.');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('marks a finding as a false positive with a justification', async () => {
    render(<LicenseCompliancePage />);
    await screen.findByText('Unlicensed Acrobat installation');

    fireEvent.click(screen.getByRole('button', { name: 'False Positive' }));
    fireEvent.change(screen.getByLabelText(/Justification/i), { target: { value: 'Approved trial install' } });
    fireEvent.click(screen.getByRole('button', { name: 'Mark false positive' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/licensing/findings/21/false-positive/', {
        resolution_note: 'Approved trial install',
      });
    });
    await screen.findByText('Finding 21 marked as a false positive.');
  });

  it('does not offer actions on closed findings', async () => {
    setupGet([{ ...FINDING, status: 'resolved' }]);
    render(<LicenseCompliancePage />);
    await screen.findByText('Unlicensed Acrobat installation');

    expect(screen.queryByRole('button', { name: 'Acknowledge' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Remediate' })).toBeNull();
    expect(screen.getByText('Closed')).toBeTruthy();
  });
});

describe('License compliance - permissions', () => {
  it('only allows IT Support to acknowledge findings', async () => {
    mockAuth.mockImplementation(() => makeAuth('it_support'));
    render(<LicenseCompliancePage />);
    await screen.findByText('Unlicensed Acrobat installation');

    expect(screen.getByRole('button', { name: 'Acknowledge' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Remediate' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Resolve' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'False Positive' })).toBeNull();
    expect(document.body.textContent).toContain('requires IT Manager or System Admin permission');
  });

  it('denies employees and never requests findings', async () => {
    mockAuth.mockImplementation(() => makeAuth('employee'));
    render(<LicenseCompliancePage />);

    expect(screen.getByText('You do not have permission to access this page.')).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });
});
