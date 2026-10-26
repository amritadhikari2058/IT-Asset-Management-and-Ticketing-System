import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    delete: (...args) => mockDelete(...args),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { TicketDetail } from './tickets';

const TICKET = {
  id: 7, title: 'Printer down', status: 'open', priority: 'high',
  category_name: 'Hardware', department_name: 'IT', requester_email: 'e@x',
  assignee_email: null, assignee: null, asset: null,
  created_at: '2024-01-01T00:00:00Z', description: 'No power.',
  on_behalf_reason: '', resolution_notes: '',
};
const ATTS = [
  { id: 11, original_filename: 'spec.pdf', created_at: '2024-01-02T00:00:00Z' },
];

function staff() {
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_support' } });
}

function employee() {
  mockAuth.mockReturnValue({ isStaff: false, user: { role: 'employee' } });
}

function route(url) {
  if (url === '/tickets/7/') return { data: TICKET };
  if (url === '/tickets/7/notes/') return { data: [] };
  if (url === '/tickets/histories/') return { data: [] };
  if (url === '/tickets/attachments/') return { data: [...ATTS] };
  throw new Error(`unexpected GET ${url}`);
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockGet.mockImplementation(async (url) => route(url));
  mockPost.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
  global.URL.createObjectURL = vi.fn(() => 'blob:fake');
  global.URL.revokeObjectURL = vi.fn();
});

describe('TicketDetail attachments', () => {
  it('lists attachments for staff', async () => {
    staff();
    render(<TicketDetail id="7" />);
    expect(await screen.findByText('spec.pdf')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith(
      '/tickets/attachments/', { params: { ticket: '7' } },
    );
  });

  it('shows upload and delete controls only to staff', async () => {
    employee();
    render(<TicketDetail id="7" />);
    expect(await screen.findByText('spec.pdf')).toBeTruthy();
    expect(screen.queryByLabelText('Choose a file to upload')).toBeNull();
    expect(screen.queryByRole('button', { name: /delete/i })).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Download' }),
    ).toBeTruthy();
  });

  it('uploads a file and refreshes the list', async () => {
    staff();
    mockPost.mockResolvedValueOnce({
      data: { id: 12, original_filename: 'a.pdf' },
    });
    render(<TicketDetail id="7" />);
    await screen.findByText('spec.pdf');
    const input = screen.getByLabelText('Choose a file to upload');
    fireEvent.change(input, {
      target: { files: [new File(['x'], 'a.pdf', { type: 'application/pdf' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledTimes(1);
    });
    const [url, body] = mockPost.mock.calls[0];
    expect(url).toBe('/tickets/attachments/');
    expect(body).toBeInstanceOf(FormData);
    expect(await screen.findByText(/Uploaded "a.pdf"/)).toBeTruthy();
  });

  it('shows backend validation errors on rejected upload', async () => {
    staff();
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { file: ['Executable files are blocked.'] } },
    });
    render(<TicketDetail id="7" />);
    await screen.findByText('spec.pdf');
    fireEvent.change(screen.getByLabelText('Choose a file to upload'), {
      target: { files: [new File(['x'], 'a.exe', { type: 'application/octet-stream' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    expect(await screen.findByText('Executable files are blocked.')).toBeTruthy();
  });

  it('deletes an attachment after confirmation', async () => {
    staff();
    render(<TicketDetail id="7" />);
    await screen.findByText('spec.pdf');
    fireEvent.click(
      screen.getByRole('button', { name: 'Delete attachment spec.pdf' }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Delete attachment' }));
    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith('/tickets/attachments/11/');
    });
  });

  it('downloads through the protected endpoint as a blob', async () => {
    staff();
    mockGet.mockImplementation(async (url, cfg) => {
      if (String(url).endsWith('/download/')) {
        return { data: new Blob(['x']), headers: { 'content-disposition': 'attachment; filename="spec.pdf"' } };
      }
      return route(url);
    });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<TicketDetail id="7" />);
    await screen.findByText('spec.pdf');
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(
        '/tickets/attachments/11/download/', { responseType: 'blob' },
      );
    });
    expect(global.URL.createObjectURL).toHaveBeenCalled();
    clickSpy.mockRestore();
  });
});
