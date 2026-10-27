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

import { Departments } from './pages';

const DEPTS = [
  { id: 1, name: 'Eng', code: 'ENG', head_email: null, member_count: 4, is_active: true },
];

function staff() {
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_manager' } });
}

function employee() {
  mockAuth.mockReturnValue({ isStaff: false, user: { role: 'employee' } });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockGet.mockImplementation(async (url) => {
    if (String(url).startsWith('/accounts/departments/')) {
      return { data: { results: [...DEPTS], count: 1, next: null, previous: null } };
    }
    if (String(url).startsWith('/accounts/users/')) {
      return { data: { results: [], count: 0, next: null, previous: null } };
    }
    throw new Error(`unexpected GET ${url}`);
  });
  mockPost.mockResolvedValue({ data: { id: 2 } });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('Departments page', () => {
  it('lists departments', async () => {
    staff();
    render(<Departments />);
    expect(await screen.findByText('Eng')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/accounts/departments/');
  });

  it('creates a department and refreshes', async () => {
    staff();
    render(<Departments />);
    await screen.findByText('Eng');
    fireEvent.click(screen.getByRole('button', { name: '+ New department' }));
    fireEvent.change(screen.getByLabelText(/^Name/), {
      target: { value: 'Support' },
    });
    fireEvent.change(screen.getByLabelText(/Code/), {
      target: { value: 'SUP' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create department' }));
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/accounts/departments/',
        expect.objectContaining({ name: 'Support', code: 'SUP' }),
      );
    });
    expect(await screen.findByText('Department created.')).toBeTruthy();
  });

  it('shows validation errors without closing', async () => {
    staff();
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { code: ['Department with this code already exists.'] } },
    });
    render(<Departments />);
    await screen.findByText('Eng');
    fireEvent.click(screen.getByRole('button', { name: '+ New department' }));
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'X' } });
    fireEvent.change(screen.getByLabelText(/Code/), { target: { value: 'ENG' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create department' }));
    expect(
      await screen.findByText('Department with this code already exists.'),
    ).toBeTruthy();
  });

  it('edits a department with the prefilled modal and refreshes', async () => {
    staff();
    render(<Departments />);
    await screen.findByText('Eng');
    fireEvent.click(screen.getByRole('button', { name: 'Edit…' }));
    expect(screen.getByLabelText(/^Name/).value).toBe('Eng');
    expect(screen.getByLabelText(/Code/).value).toBe('ENG');
    fireEvent.change(screen.getByLabelText(/^Name/), {
      target: { value: 'Engineering & Ops' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith('/accounts/departments/1/', {
        name: 'Engineering & Ops', code: 'ENG',
        description: '', is_active: true,
      });
    });
    expect(await screen.findByText('Department updated.')).toBeTruthy();
  });

  it('surfaces edit validation errors without closing', async () => {
    staff();
    mockPatch.mockRejectedValueOnce({
      response: {
        status: 400, data: { code: ['Department with this code already exists.'] },
      },
    });
    render(<Departments />);
    await screen.findByText('Eng');
    fireEvent.click(screen.getByRole('button', { name: 'Edit…' }));
    fireEvent.change(screen.getByLabelText(/^Name/), {
      target: { value: 'Eng' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(
      await screen.findByText('Department with this code already exists.'),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeTruthy();
  });

  it('explains referenced-record conflicts on delete', async () => {
    staff();
    mockDelete.mockRejectedValueOnce({
      response: {
        status: 409,
        data: { detail: 'x', references: { members: 2, tickets: 1 } },
      },
    });
    render(<Departments />);
    await screen.findByText('Eng');
    fireEvent.click(screen.getByRole('button', { name: 'Delete…' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete department' }));
    expect(await screen.findByText(/still referenced/)).toBeTruthy();
    expect(screen.getByText(/members: 2, tickets: 1/)).toBeTruthy();
  });

  it('hides management actions from employees', async () => {
    employee();
    render(<Departments />);
    await screen.findByText('Eng');
    expect(screen.queryByRole('button', { name: '+ New department' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Edit/ })).toBeNull();
  });
});
