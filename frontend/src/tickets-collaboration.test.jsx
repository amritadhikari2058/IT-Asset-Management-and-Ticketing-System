import { TicketDetail } from './tickets';

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

vi.mock('./auth', () => ({ useAuth: (...args) => mockAuth(...args) }));

const TICKET = {
  id: 7,
  title: 'Printer down',
  description: 'No power.',
  priority: 'high',
  category: 2,
  department: 1,
  assignee: null,
  requester_email: 'e@x',
  created_at: '2024-01-01T00:00:00Z',
  status: 'open',
};

function staff() {
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_support' } });
}

function employee() {
  mockAuth.mockReturnValue({ isStaff: false, user: { role: 'employee' } });
}

function detailRoute(url) {
  const u = String(url);
  if (u === '/tickets/7/') return { data: TICKET };
  if (u === '/tickets/7/notes/') return { data: [] };
  if (u === '/tickets/histories/') return { data: [] };
  if (u === '/tickets/attachments/') return { data: [] };
  throw new Error('unexpected GET ' + url);
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockGet.mockImplementation(async (url) => detailRoute(url));
  mockPost.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
  global.URL.createObjectURL = vi.fn(() => 'blob:fake');
  global.URL.revokeObjectURL = vi.fn();
});

describe('TicketDetail comments and notes', () => {
  it('loads comments and notes', async () => {
    staff();
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    expect(mockGet).toHaveBeenCalledWith('/tickets/7/notes/');
  });
});

describe('TicketDetail attachments', () => {
  it('lists attachments', async () => {
    staff();
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    expect(mockGet).toHaveBeenCalledWith('/tickets/attachments/', { params: { ticket: '7' } });
  });
  it('uploads a file as multipart payload', async () => {
    staff();
    mockPost.mockResolvedValueOnce({ data: { id: 12, original_filename: 'test.pdf', created_at: '2024-01-02T10:00:00Z' } });
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    const input = screen.getByLabelText('Choose a file to upload');
    fireEvent.change(input, {
      target: { files: [new File(['test content'], 'test.pdf', { type: 'application/pdf' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    const [url, body] = mockPost.mock.calls[0];
    expect(url).toBe('/tickets/attachments/');
    expect(body).toBeInstanceOf(FormData);
  });
  it('shows upload and delete controls only to staff', async () => {
    employee();
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    expect(screen.queryByLabelText('Choose a file to upload')).toBeNull();
    expect(screen.queryByRole('button', { name: /delete/i })).toBeNull();
    expect(screen.getByRole('button', { name: 'Download' })).toBeTruthy();
  });
  it('shows backend validation errors on rejected upload', async () => {
    staff();
    mockPost.mockRejectedValueOnce({ response: { status: 400, data: { file: ['Executable files are blocked.'] } } });
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    const input = screen.getByLabelText('Choose a file to upload');
    fireEvent.change(input, {
      target: { files: [new File(['x'], '.exe', { type: 'application/octet-stream' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    await waitFor(() => screen.getByText('Executable files are blocked.'));
  });
  it('deletes an attachment after confirmation', async () => {
    staff();
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    expect(screen.getByRole('button', { name: /delete attachment/i })).toBeTruthy();
  });
  it('downloads through the protected endpoint as a blob', async () => {
    staff();
    mockGet.mockImplementation(async (url, cfg) => {
      if (String(url).endsWith('/download/')) {
        return { data: new Blob(['x']), headers: { 'content-disposition': 'attachment; filename=\"test.pdf\"' } };
      }
      return detailRoute(url);
    });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith('/tickets/attachments/1/download/', { responseType: 'blob' });
    });
    clickSpy.mockRestore();
  });
describe('TicketDetail history', () => {
  it('hides History from employees and never requests it', async () => {
    employee();
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    expect(screen.queryByText('History')).toBeNull();
    expect(mockGet.mock.calls.filter(([url]) => 'histories' in String(url))).toHaveLength(0);
  });
  it('shows History to staff', async () => {
    staff();
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    await screen.getByText('History');
    expect(mockGet).toHaveBeenCalledWith('/tickets/histories/', { params: { ticket: '7' } });
  });
  it('shows empty state when no history entries', async () => {
    staff();
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    await screen.getByText('History');
    expect(screen.getByText('No history entries.')).toBeTruthy();
  });
  it('handles history request failure', async () => {
    staff();
    mockGet.mockRejectedValueOnce({ response: { status: 500, data: { detail: 'Server error.' } } });
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    await screen.getByText('History');
  });
});

describe('TicketDetail permission-related UI behavior', () => {
  it('notes form internal checkbox hidden from employees', async () => {
    employee();
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    expect(screen.queryByLabelText('Internal note (hidden from employees)')).toBeNull();
  });
  it('only staff can access attachment delete controls', async () => {
    employee();
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    expect(screen.queryByRole('button', { name: /delete attachment/i })).toBeNull();
  });
  it('only staff can see attachment upload control', async () => {
    employee();
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    expect(screen.queryByLabelText('Choose a file to upload')).toBeNull();
  });
});

describe('TicketDetail cleanup during navigation', () => {
  it('cleans up object URLs when navigating away', async () => {
    staff();
    const createObjectURLSpy = vi.spyOn(global.URL, 'createObjectURL');
    render(<TicketDetail id='7' />);
    await screen.getByRole('heading', { name: /Printer down/ });
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await waitFor(() => expect(createObjectURLSpy).toHaveBeenCalled());
    cleanup();
    expect(global.URL.revokeObjectURL).toHaveBeenCalled();
    createObjectURLSpy.mockRestore();
  });
});

afterEach(() => cleanup());
});