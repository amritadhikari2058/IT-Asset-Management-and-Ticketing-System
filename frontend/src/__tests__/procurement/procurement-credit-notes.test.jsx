import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({ default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) } }));
vi.mock('../../auth', () => ({ useAuth: (...a) => mockAuth(...a) }));

import { ProcurementCreditNotesPage, ProcurementCreditNoteForm, ProcurementCreditNoteDetail } from '../../pages/procurement/ProcurementCreditNotes';

function authUser(role, id = 1) {
  return {
    access: 'token',
    role,
    user: { id, role },
    isSystemAdmin: role === 'system_admin',
    isITManager: role === 'it_manager',
    isITSupport: role === 'it_support',
    isSuperuser: false,
  };
}

const creditNote = {
  id: 2, credit_note_number: 'CN-1', vendor_name: 'Acme', invoice_number: 'INV-1', return_number: null,
  status: 'approved', total: '50.00', currency: 'NPR', applied_amount: '0.00', created_by: 2, lines: [], version: 1,
};

function mockCreditLoad(overrides = {}) {
  const cn = { ...creditNote, ...overrides };
  mockGet.mockImplementation((url) => {
    if (url === '/procurement/credit-notes/2/') return Promise.resolve({ data: cn });
    return Promise.resolve({ data: { results: [] } });
  });
}

beforeEach(() => {
  cleanup();
  vi.resetAllMocks();
  window.prompt = vi.fn(() => null);
  mockAuth.mockReturnValue(authUser('it_manager'));
  mockCreditLoad();
  mockPost.mockResolvedValue({ data: {} });
});
afterEach(() => cleanup());

describe('P3 credit notes list', () => {
  it('renders the loading state and rows from the exact endpoint', async () => {
    mockGet.mockImplementation((url) => {
      if (url === '/procurement/credit-notes/?page_size=50') {
        return Promise.resolve({ data: { results: [{ id: 2, credit_note_number: 'CN-1', vendor_name: 'Acme', invoice_number: 'INV-1', status: 'approved', total: '50.00', currency: 'NPR', applied_amount: '0.00' }] } });
      }
      return Promise.resolve({ data: { results: [] } });
    });
    render(<ProcurementCreditNotesPage />);
    expect(screen.getByRole('status').textContent).toMatch(/Loading credit notes/);
    expect(await screen.findByText('CN-1')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'CN-1' }).getAttribute('href')).toBe('#/procurement/credit-notes/2');
    expect(mockGet).toHaveBeenCalledWith('/procurement/credit-notes/?page_size=50');
  });

  it('shows an empty state', async () => {
    render(<ProcurementCreditNotesPage />);
    expect(await screen.findByText('No credit notes.')).toBeTruthy();
  });

  it('shows a standardized error with Retry', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 403, data: {} } });
    render(<ProcurementCreditNotesPage />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/You do not have permission/);
    mockGet.mockResolvedValueOnce({ data: { results: [{ id: 3, credit_note_number: 'CN-3', status: 'draft' }] } });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('CN-3')).toBeTruthy();
  });
});

describe('P3 credit note create', () => {
  async function fillForm() {
    render(<ProcurementCreditNoteForm />);
    fireEvent.change(screen.getByLabelText(/Credit Note Number/i), { target: { value: 'CN-9' } });
    fireEvent.change(screen.getByLabelText(/Vendor ID/i), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText(/Supplier Invoice ID/i), { target: { value: '4' } });
    fireEvent.change(screen.getByLabelText(/Credit Date/i), { target: { value: '2026-11-12' } });
  }

  it('posts the exact payload and uses the returned id', async () => {
    mockPost.mockResolvedValue({ data: { id: 9 } });
    await fillForm();
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/credit-notes/', expect.any(Object)));
    expect(mockPost.mock.calls[0][1]).toMatchObject({
      credit_note_number: 'CN-9', vendor: '2', supplier_invoice: '4', vendor_return: null, currency: 'NPR',
    });
    await waitFor(() => expect(window.location.hash).toBe('#/procurement/credit-notes/9'));
  });

  it('does not navigate when the returned id is missing', async () => {
    window.location.hash = '#/procurement/credit-notes/new';
    mockPost.mockResolvedValue({ data: {} });
    await fillForm();
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/did not return the new credit note id/);
    expect(window.location.hash).toBe('#/procurement/credit-notes/new');
  });

  it('renders 400 vendor/currency/over-credit errors readably', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { vendor: ['Vendor must match invoice.'], detail: 'Credit amount exceeds remaining invoice balance.' } } });
    await fillForm();
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('Vendor must match invoice.')).toBeTruthy();
    expect(screen.getByText('Credit amount exceeds remaining invoice balance.')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).not.toMatch(/[{}]/);
  });
});

describe('P3 credit note actions', () => {
  it('shows apply/reject/cancel to a non-creator manager and no approval on an approved note', async () => {
    render(<ProcurementCreditNoteDetail id={2} />);
    expect(await screen.findByText(/Credit Note CN-1/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Apply' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Submit' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.getByText(/Credit applied to tracked Invoice balance\./)).toBeTruthy();
  });

  it('hides financial actions from IT Support and issues no request', async () => {
    mockAuth.mockReturnValue(authUser('it_support', 3));
    render(<ProcurementCreditNoteDetail id={2} />);
    expect(await screen.findByText(/Credit Note CN-1/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Apply' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('never offers self-approval to the creator, except a System Admin', async () => {
    mockAuth.mockReturnValue(authUser('it_manager', 2));
    mockCreditLoad({ status: 'submitted' });
    render(<ProcurementCreditNoteDetail id={2} />);
    expect(await screen.findByText(/Credit Note CN-1/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    cleanup();

    mockAuth.mockReturnValue(authUser('system_admin', 2));
    mockCreditLoad({ status: 'submitted' });
    render(<ProcurementCreditNoteDetail id={2} />);
    expect(await screen.findByText(/Credit Note CN-1/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
  });

  it('posts submit, approve, apply, reject and cancel to their exact endpoints', async () => {
    mockCreditLoad({ status: 'draft' });
    render(<ProcurementCreditNoteDetail id={2} />);
    await screen.findByText(/Credit Note CN-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/credit-notes/2/submit/', {}));
    cleanup();

    mockCreditLoad({ status: 'submitted' });
    render(<ProcurementCreditNoteDetail id={2} />);
    await screen.findByText(/Credit Note CN-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/credit-notes/2/approve/', {}));
    cleanup();

    mockCreditLoad({ status: 'approved' });
    render(<ProcurementCreditNoteDetail id={2} />);
    await screen.findByText(/Credit Note CN-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/credit-notes/2/apply/', {}));
    cleanup();

    window.prompt = vi.fn(() => 'Not applicable');
    mockCreditLoad({ status: 'submitted' });
    render(<ProcurementCreditNoteDetail id={2} />);
    await screen.findByText(/Credit Note CN-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/credit-notes/2/reject/', { reason: 'Not applicable' }));
    cleanup();

    mockCreditLoad({ status: 'draft' });
    render(<ProcurementCreditNoteDetail id={2} />);
    await screen.findByText(/Credit Note CN-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/procurement/credit-notes/2/cancel/', { reason: 'Not applicable' }));
  });

  it('reloads exactly once on a 409 conflict without retrying the action', async () => {
    mockCreditLoad({ status: 'approved' });
    mockPost.mockRejectedValueOnce({ response: { status: 409, data: {} } });
    render(<ProcurementCreditNoteDetail id={2} />);
    await screen.findByText(/Credit Note CN-1/);
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(await screen.findByText(/This credit note changed while you were working\. The latest version has been loaded\./)).toBeTruthy();
    await waitFor(() => {
      const loads = mockGet.mock.calls.filter(([url]) => url === '/procurement/credit-notes/2/');
      expect(loads.length).toBe(2);
    });
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it('uses credit-balance wording and never claims a refund or accounting post', async () => {
    render(<ProcurementCreditNoteDetail id={2} />);
    await screen.findByText(/Credit Note CN-1/);
    expect(screen.getByText(/Credit applied to tracked Invoice balance\./)).toBeTruthy();
    expect(screen.queryByText(/Refund received|Cash received|Vendor payment received|Accounting entry posted/)).toBeNull();
  });
});
