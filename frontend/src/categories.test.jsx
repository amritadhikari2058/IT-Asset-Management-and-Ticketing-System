import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
    delete: (...args) => mockDelete(...args),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { Categories } from './pages';

const TCATS = [{ id: 1, name: 'Hardware', description: 'Old text', is_active: true }];
const ACATS = [{ id: 2, name: 'Laptop', description: '', is_active: false }];

function staff() {
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_manager' } });
}

function employee() {
  mockAuth.mockReturnValue({ isStaff: false, user: { role: 'employee' } });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.confirm = vi.fn(() => true);
  mockGet.mockImplementation(async (url) => {
    if (url === '/assets/categories/') return { data: { results: [...ACATS] } };
    if (url === '/tickets/categories/') return { data: { results: [...TCATS] } };
    throw new Error(`unexpected GET ${url}`);
  });
  mockPost.mockResolvedValue({ data: { id: 3 } });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('Categories page', () => {
  it('edits a ticket category (prefilled name + description)', async () => {
    staff();
    render(<Categories />);
    await screen.findByText('Hardware');
    const editBtns = screen.getAllByRole('button', { name: 'Edit…' });
    fireEvent.click(editBtns[0]);
    // Form is prefilled with the record's current values.
    const nameInput = screen.getByLabelText(/^Name/);
    const descInput = screen.getByLabelText(/^Description/);
    expect(nameInput.value).toBe('Hardware');
    expect(descInput.value).toBe('Old text');
    fireEvent.change(nameInput, { target: { value: 'Hardware & Network' } });
    fireEvent.change(descInput, { target: { value: 'Fix description.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith('/tickets/categories/1/', {
        name: 'Hardware & Network',
        description: 'Fix description.',
      });
    });
    expect(await screen.findByText('Category "Hardware" updated.')).toBeTruthy();
  });

  it('rejects blank names: disabled save + Enter still hits validation', async () => {
    staff();
    render(<Categories />);
    await screen.findByText('Hardware');
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit…' })[0]);
    const nameInput = screen.getByLabelText(/^Name/);
    fireEvent.change(nameInput, { target: { value: '' } });
    // Primary guard: a blank name disables the primary button.
    expect(screen.getByRole('button', { name: 'Save changes' }).disabled).toBe(true);
    // Secondary guard: a programmatic submit (Enter) shows the field error.
    fireEvent.submit(nameInput.closest('form'));
    expect(screen.getByText('Name is required.')).toBeTruthy();
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('surfaces duplicate-name errors from the API without closing', async () => {
    staff();
    mockPatch.mockRejectedValueOnce({
      response: {
        status: 400, data: { name: ['The category name must be unique.'] },
      },
    });
    render(<Categories />);
    await screen.findByText('Hardware');
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit…' })[0]);
    const input = screen.getByLabelText(/^Name/);
    fireEvent.change(input, { target: { value: 'Duplicate' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText('The category name must be unique.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeTruthy();
  });

  it('deactivates an active category', async () => {
    staff();
    render(<Categories />);
    await screen.findByText('Hardware');
    fireEvent.click(screen.getAllByRole('button', { name: 'Deactivate…' })[0]);
    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith('/tickets/categories/1/', {
        is_active: false,
      });
    });
  });

  it('explains referenced-record conflicts on delete', async () => {
    staff();
    mockDelete.mockRejectedValueOnce({
      response: { status: 409, data: { detail: 'in use', count: 4 } },
    });
    render(<Categories />);
    await screen.findByText('Hardware');
    fireEvent.click(screen.getAllByRole('button', { name: 'Delete…' })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Delete category' }));
    expect(
      await screen.findByText(/still used by 4 record\(s\)/),
    ).toBeTruthy();
  });

  it('hides management actions from employees', async () => {
    employee();
    render(<Categories />);
    await screen.findByText('Hardware');
    expect(screen.queryByRole('button', { name: 'Edit…' })).toBeNull();
    expect(screen.queryByRole('button', { name: /eactivate/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete…' })).toBeNull();
  });
});
