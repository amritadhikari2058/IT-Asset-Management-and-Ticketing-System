import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({ default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) } }));
vi.mock('./auth', () => ({ useAuth: () => mockAuth() }));

import { TicketBulkCreateModal, AssetBulkCreateModal } from './bulk';

function makeFile(name = 'data.csv') {
  return new File(['a,b'], name, { type: 'text/csv' });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_support' } });
  window.confirm = vi.fn(() => true);
});

afterEach(() => cleanup());

describe('TicketBulkCreateModal workflow', () => {
  it('previews and confirms successfully with same operation token', async () => {
    mockPost.mockImplementation(async (url) => {
      if (url === '/tickets/bulk_create/') return { data: { affected: 2, invalid: [] } };
      return { data: new Blob(['row,outcome\n1,created'], { type: 'text/csv' }) };
    });
    render(<TicketBulkCreateModal onClose={() => {}} onCreated={() => {}} />);
    const input = screen.getByLabelText('Import file');
    fireEvent.change(input, { target: { files: [makeFile()] } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByText(/2 valid/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Confirm create/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2));
    const previewFd = mockPost.mock.calls[0][1];
    const confirmFd = mockPost.mock.calls[1][1];
    expect(previewFd.get('import_token')).toBeTruthy();
    expect(confirmFd.get('import_token')).toBe(previewFd.get('import_token'));
  });

  it('prevents duplicate in-flight confirmation requests', async () => {
    mockPost.mockImplementation(async (url) => {
      if (url === '/tickets/bulk_create/') return { data: { affected: 1, invalid: [] } };
      return { data: new Blob(['r'], { type: 'text/csv' }) };
    });
    render(<TicketBulkCreateModal onClose={() => {}} onCreated={() => {}} />);
    fireEvent.change(screen.getByLabelText('Import file'), { target: { files: [makeFile()] } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Confirm create/ })).toBeTruthy());
    const btn = screen.getByRole('button', { name: /Confirm create/ });
    fireEvent.click(btn);
    fireEvent.click(btn);
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2));
    // Only one confirm request should have been made
    const confirmCalls = mockPost.mock.calls.filter(([u]) => String(u).includes('download=csv'));
    expect(confirmCalls.length).toBe(1);
  });

  it('reuses the same operation token when retrying confirmation after failure', async () => {
    mockPost.mockImplementation(async (url) => {
      if (url === '/tickets/bulk_create/') return { data: { affected: 1, invalid: [] } };
      if (mockPost.mock.calls.filter(([u]) => String(u).includes('download=csv')).length === 1) {
        throw new Error('network down');
      }
      return { data: new Blob(['row,key,outcome,message\n1,1,successful,created'], { type: 'text/csv' }) };
    });
    render(<TicketBulkCreateModal onClose={() => {}} onCreated={() => {}} />);
    fireEvent.change(screen.getByLabelText('Import file'), { target: { files: [makeFile()] } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Confirm create/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Confirm create/ }));
    await waitFor(() => expect(screen.getByText(/Request failed: network down/i)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Confirm create/ }));
    await waitFor(() => expect(screen.getByText(/Create result/)).toBeTruthy());
    const confirmCalls = mockPost.mock.calls.filter(([u]) => String(u).includes('download=csv'));
    expect(confirmCalls.length).toBe(2);
    expect(confirmCalls[0][1].get('import_token')).toBeTruthy();
    expect(confirmCalls[1][1].get('import_token')).toBe(confirmCalls[0][1].get('import_token'));
  });

  it('shows preview failure and allows retry', async () => {
    mockPost
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ data: { affected: 1, invalid: [] } });
    render(<TicketBulkCreateModal onClose={() => {}} onCreated={() => {}} />);
    fireEvent.change(screen.getByLabelText('Import file'), { target: { files: [makeFile()] } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByText(/Request failed: boom/i)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByText(/1 valid/)).toBeTruthy());
  });
});

describe('AssetBulkCreateModal workflow', () => {
  it('previews and confirms successfully', async () => {
    mockPost.mockImplementation(async (url) => {
      if (url === '/assets/bulk_create/') return { data: { preview: [{ asset_tag: 'LT-1' }], errors: [] } };
      return { data: new Blob(['row,outcome\n1,created'], { type: 'text/csv' }) };
    });
    render(<AssetBulkCreateModal onClose={() => {}} onImported={() => {}} />);
    fireEvent.change(screen.getByLabelText('Import file'), { target: { files: [makeFile('assets.csv')] } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByText(/would be created/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Confirm create/ }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2));
  });

  it('clears preview when file changes', async () => {
    mockPost.mockResolvedValue({ data: { preview: [{ asset_tag: 'LT-1' }], errors: [] } });
    render(<AssetBulkCreateModal onClose={() => {}} onImported={() => {}} />);
    fireEvent.change(screen.getByLabelText('Import file'), { target: { files: [makeFile('a.csv')] } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByText(/would be created/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Import file'), { target: { files: [makeFile('b.csv')] } });
    expect(screen.queryByText(/would be created/)).toBeNull();
  });
});
