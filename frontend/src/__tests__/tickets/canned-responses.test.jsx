import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPut, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPut: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    put: (...args) => mockPut(...args),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: () => mockAuth(),
}));

import { CannedResponsesPage } from '../../pages/tickets/CannedResponsesPage';

const activeQueue = {
  id: 5,
  name: 'IT Support',
  is_active: true,
};

const cannedResponse = {
  id: 15,
  title: 'Password reset',
  code: 'PASSWORD-RESET',
  body: 'Please follow the password reset instructions.',
  visibility: 'internal_note',
  category: 'account',
  queue: 5,
  queue_name: 'IT Support',
  is_shared: false,
  usage_count: 3,
};

function setupApi(responses = [], queues = [activeQueue]) {
  mockGet.mockImplementation(async (url) => {
    if (url === '/tickets/canned-responses/') {
      return { data: { results: responses } };
    }

    if (url === '/tickets/queues/') {
      return { data: { results: queues } };
    }

    throw new Error(`Unexpected GET: ${url}`);
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();

  mockAuth.mockReturnValue({
    isEmployee: false,
    isManagerOrAdmin: true,
    isStaff: true,
    user: { id: 1, role: 'it_manager' },
  });

  setupApi();
  mockPost.mockResolvedValue({ data: { id: 20 } });
  mockPut.mockResolvedValue({ data: cannedResponse });
});

afterEach(() => cleanup());

describe('CannedResponsesPage queue support', () => {
  it('loads and displays the queue associated with a canned response', async () => {
    setupApi([cannedResponse]);

    render(<CannedResponsesPage />);

    expect(await screen.findByText('Password reset')).toBeTruthy();
    expect(screen.getByText('IT Support')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/tickets/queues/');
  });

  it('creates a canned response with the selected queue ID', async () => {
    render(<CannedResponsesPage />);

    fireEvent.click(
      await screen.findByRole('button', { name: 'Create Canned Response' }),
    );

    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Network troubleshooting' },
    });

    fireEvent.change(screen.getByLabelText('Response Body'), {
      target: { value: 'Please restart the network connection.' },
    });

    fireEvent.change(screen.getByLabelText('Queue'), {
      target: { value: '5' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save Response' }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/tickets/canned-responses/', {
        title: 'Network troubleshooting',
        code: '',
        body: 'Please restart the network connection.',
        visibility: 'internal_note',
        category: '',
        queue: 5,
        is_shared: false,
      });
    });
  });

  it('preserves an existing inactive queue when editing a response', async () => {
    const responseWithInactiveQueue = {
      ...cannedResponse,
      queue: 99,
      queue_name: 'Legacy Support Queue',
    };

    setupApi([responseWithInactiveQueue], [activeQueue]);

    render(<CannedResponsesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));

    const queueSelect = screen.getByLabelText('Queue');

    expect(queueSelect.value).toBe('99');
    expect(
      screen.getByRole('option', {
        name: 'Legacy Support Queue (inactive or unavailable)',
      }),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Update Response' }));

    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledTimes(1);
    });

    const [url, payload] = mockPut.mock.calls[0];

    expect(url).toBe('/tickets/canned-responses/15/');
    expect(payload.queue).toBe(99);
  });
});