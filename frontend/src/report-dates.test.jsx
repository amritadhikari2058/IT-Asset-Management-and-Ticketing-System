import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

const { mockGet, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

vi.mock('./bulk', () => ({
  TicketBulkCreateModal: () => null,
}));

import { Tickets } from './pages';

function staff() {
  mockAuth.mockReturnValue({ canCreateTickets: true, isStaff: true });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockGet.mockImplementation(async (url) => {
    if (String(url).startsWith('/tickets/')) {
      return { data: { results: [], count: 0, next: null, previous: null } };
    }
    if (String(url).startsWith('/accounts/departments/')) {
      return { data: { results: [] } };
    }
    if (String(url).startsWith('/tickets/categories/')) {
      return { data: { results: [] } };
    }
    throw new Error(`unexpected GET ${url}`);
  });
});

afterEach(() => cleanup());

describe('Tickets report date filters', () => {
  it('passes exact date_from/date_to params on apply', async () => {
    staff();
    render(<Tickets />);
    fireEvent.click(screen.getByRole('button', { name: 'Category report' }));
    fireEvent.change(screen.getByLabelText('Report start date'), {
      target: { value: '2024-01-01' },
    });
    fireEvent.change(screen.getByLabelText('Report end date'), {
      target: { value: '2024-02-01' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }));
    expect(mockGet).toHaveBeenLastCalledWith(
      '/tickets/reports/by-category/?date_from=2024-01-01&date_to=2024-02-01',
    );
  });

  it('rejects an end date before the start date without calling the API', async () => {
    staff();
    render(<Tickets />);
    fireEvent.click(screen.getByRole('button', { name: 'Category report' }));
    const calls = mockGet.mock.calls.length;
    fireEvent.change(screen.getByLabelText('Report start date'), {
      target: { value: '2024-02-01' },
    });
    fireEvent.change(screen.getByLabelText('Report end date'), {
      target: { value: '2024-01-01' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }));
    expect(
      await screen.findByText('Report end date cannot be earlier than start date.'),
    ).toBeTruthy();
    expect(mockGet.mock.calls.length).toBe(calls);
  });

  it('reset clears the dates', async () => {
    staff();
    render(<Tickets />);
    fireEvent.click(screen.getByRole('button', { name: 'Category report' }));
    fireEvent.change(screen.getByLabelText('Report start date'), {
      target: { value: '2024-01-01' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(mockGet).toHaveBeenLastCalledWith('/tickets/reports/by-category/');
  });
});

