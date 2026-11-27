import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPut, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPut: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    put: (...args) => mockPut(...args),
    delete: (...args) => mockDelete(...args),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: () => mockAuth(),
}));

import { TicketTemplatesPage } from '../../pages/tickets/TicketTemplatesPage';

const template = {
  id: 12,
  name: 'New laptop request',
  code: 'LAPTOP-REQ',
  title_template: 'Request for a new laptop',
  description_template: 'Laptop request details',
  category: null,
  category_name: null,
  queue: null,
  queue_name: null,
  priority: 'medium',
  default_assignee: null,
  default_status: 'open',
  required_asset: false,
  note_templates: [],
  custom_fields: {},
  owner: 2,
  owner_email: 'owner@example.com',
  is_shared: false,
  is_active: true,
  version: 1,
};

function setupApi(templates = []) {
  mockGet.mockImplementation(async (url) => {
    if (url === '/tickets/templates/') return { data: { results: templates } };
    if (url === '/tickets/queues/') return { data: { results: [] } };
    if (url === '/tickets/categories/') return { data: { results: [] } };
    if (url === '/accounts/users/') return { data: { results: [] } };
    throw new Error(`Unexpected GET: ${url}`);
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();

  mockAuth.mockReturnValue({
    isStaff: true,
    isManagerOrAdmin: false,
    user: { id: 2, role: 'it_support' },
  });

  setupApi();
  mockPost.mockResolvedValue({ data: { id: 20 } });
  mockPut.mockResolvedValue({ data: template });
  mockDelete.mockResolvedValue({ data: {} });
});

afterEach(() => cleanup());

describe('TicketTemplatesPage', () => {
  it('loads templates and displays their backend-provided details', async () => {
    setupApi([template]);

    render(<TicketTemplatesPage />);

    expect(await screen.findByText('New laptop request')).toBeTruthy();
    expect(screen.getByText('LAPTOP-REQ')).toBeTruthy();
    expect(screen.getByText('Personal')).toBeTruthy();

    expect(mockGet).toHaveBeenCalledWith('/tickets/templates/');
  });

  it('creates a template using the supported backend fields', async () => {
    render(<TicketTemplatesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Create template' }));

    fireEvent.change(screen.getByLabelText('Template name'), {
      target: { value: 'New monitor request' },
    });
    fireEvent.change(screen.getByLabelText('Ticket title template'), {
      target: { value: 'Request for a monitor' },
    });

    const submitButtons = screen.getAllByRole('button', { name: 'Create template' });
    fireEvent.click(submitButtons[submitButtons.length - 1]);

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/tickets/templates/', {
        name: 'New monitor request',
        code: '',
        title_template: 'Request for a monitor',
        description_template: '',
        category: null,
        queue: null,
        priority: 'medium',
        default_assignee: null,
        default_status: 'open',
        required_asset: false,
        note_templates: [],
        custom_fields: {},
        is_shared: false,
      });
    });

    await waitFor(() => {
      const templateListCalls = mockGet.mock.calls.filter(
        ([url]) => url === '/tickets/templates/',
      );
      expect(templateListCalls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it('updates an owned template without resending an unchanged code', async () => {
    setupApi([template]);

    render(<TicketTemplatesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));

    fireEvent.change(screen.getByLabelText('Template name'), {
      target: { value: 'Updated laptop request' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledTimes(1);
    });

    const [url, payload] = mockPut.mock.calls[0];

    expect(url).toBe('/tickets/templates/12/');
    expect(payload.name).toBe('Updated laptop request');
    expect(payload).not.toHaveProperty('code');
  });

  it('deletes an owned template after confirmation', async () => {
    setupApi([template]);

    render(<TicketTemplatesPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete template' }));

    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith('/tickets/templates/12/');
    });
  });

  it('allows IT Support to delete but not edit a shared template they own', async () => {
    const sharedTemplate = { ...template, is_shared: true };
    setupApi([sharedTemplate]);

    render(<TicketTemplatesPage />);

    expect(await screen.findByText('New laptop request')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeTruthy();
  });
  it('filters templates by their name through the search field', async () => {
    const secondTemplate = {
      ...template,
      id: 13,
      name: 'New printer request',
      code: 'PRINTER-REQ',
      owner: 2,
    };
    setupApi([template, secondTemplate]);

    render(<TicketTemplatesPage />);

    expect(await screen.findByText('New laptop request')).toBeTruthy();
    expect(screen.getByText('New printer request')).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText(
      'Search by name, code, title, or category…',
    ), {
      target: { value: 'printer' },
    });

    expect(screen.getByText('New printer request')).toBeTruthy();
    expect(screen.queryByText('New laptop request')).toBeNull();
  });

  it('filters templates by the selected ticket category', async () => {
    const laptopTemplate = {
      ...template,
      category: 5,
      category_name: 'Hardware',
    };
    const softwareTemplate = {
      ...template,
      id: 13,
      name: 'Software access request',
      code: 'SOFTWARE-REQ',
      category: 6,
      category_name: 'Software',
    };

    setupApi([laptopTemplate, softwareTemplate]);

    mockGet.mockImplementation(async (url) => {
      if (url === '/tickets/templates/') {
        return { data: { results: [laptopTemplate, softwareTemplate] } };
      }
      if (url === '/tickets/queues/') {
        return { data: { results: [] } };
      }
      if (url === '/tickets/categories/') {
        return {
          data: {
            results: [
              { id: 5, name: 'Hardware', is_active: true },
              { id: 6, name: 'Software', is_active: true },
            ],
            next: null,
          },
        };
      }
      throw new Error(`Unexpected GET: ${url}`);
    });

    render(<TicketTemplatesPage />);

    expect(await screen.findByText('New laptop request')).toBeTruthy();
    expect(screen.getByText('Software access request')).toBeTruthy();

    fireEvent.change(screen.getByRole('combobox', {
      name: 'Ticket category',
    }), {
      target: { value: '5' },
    });

    expect(screen.getByText('New laptop request')).toBeTruthy();
    expect(screen.queryByText('Software access request')).toBeNull();
  });
  it('blocks non-staff users without making API requests', () => {
    mockAuth.mockReturnValue({
      isStaff: false,
      isManagerOrAdmin: false,
      user: { id: 3, role: 'employee' },
    });

    render(<TicketTemplatesPage />);

    expect(screen.getByRole('alert').textContent).toMatch(/IT staff only/i);
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('shows a useful message when template loading fails', async () => {
    mockGet.mockImplementation(async (url) => {
      if (url === '/tickets/templates/') {
        throw new Error('Network unavailable');
      }
      if (url === '/tickets/queues/' || url === '/tickets/categories/') {
        return { data: { results: [] } };
      }
      throw new Error(`Unexpected GET: ${url}`);
    });

    render(<TicketTemplatesPage />);

    expect(await screen.findByText(/Network unavailable/)).toBeTruthy();
  });
});