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

const TCATS = [{ id: 1, name: 'Hardware', is_active: true }];
const ACATS = [{ id: 2, name: 'Laptop', is_active: false }];

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
  it('renames a ticket category', async () => {
    staff();
    render(<Categories />);
    await screen.findByText('Hardware');
    const renameBtns = screen.getAllByRole('button', { name: 'Rename…' });
    fireEvent.click(renameBtns[0]);
    const input = screen.getByLabelText(/^Name/);
    fireEvent.change(input, { target: { value: 'Hardware & Network' } });
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith('/tickets/categories/1/', {
        name: 'Hardware & Network',
      });
    });
    expect(await screen.findByText('Category renamed.')).toBeTruthy();
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
    expect(screen.queryByRole('button', { name: 'Rename…' })).toBeNull();
    expect(screen.queryByRole('button', { name: /eactivate/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete…' })).toBeNull();
  });
});
