import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

const { mockGet, mockPost, mockDelete, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockDelete: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    delete: (...a) => mockDelete(...a),
  },
}));
vi.mock('../../auth', () => ({ useAuth: () => mockAuth() }));

import { AssetDetail } from '../../pages/assets/Assets';

function baseAsset(id, tag) {
  return { id, asset_tag: tag, name: `Asset ${tag}`, status: 'available' };
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_support' } });
});

afterEach(() => cleanup());

describe('AssetDetail attachment navigation', () => {
  it('loads and displays asset A own attachment', async () => {
    const dA = deferred();
    mockGet.mockImplementation((url, cfg) => {
      if (url === '/assets/1/') return Promise.resolve({ data: baseAsset(1, 'A1') });
      if (url === '/assets/attachments/' && cfg?.params?.asset == 1) return dA.promise;
      return Promise.resolve({ data: { results: [] } });
    });
    render(<AssetDetail id="1" />);
    dA.resolve({ data: { results: [{ id: 11, original_filename: 'file-a.pdf' }] } });
    expect(await screen.findByText('file-a.pdf')).toBeTruthy();
  });

  it('clears asset A attachment when navigating to asset B', async () => {
    const dA = deferred();
    const dB = deferred();
    mockGet.mockImplementation((url, cfg) => {
      if (url === '/assets/1/') return Promise.resolve({ data: baseAsset(1, 'A1') });
      if (url === '/assets/2/') return Promise.resolve({ data: baseAsset(2, 'A2') });
      if (url === '/assets/attachments/' && cfg?.params?.asset == 1) return dA.promise;
      if (url === '/assets/attachments/' && cfg?.params?.asset == 2) return dB.promise;
      return Promise.resolve({ data: { results: [] } });
    });
    const { rerender } = render(<AssetDetail id="1" />);
    dA.resolve({ data: { results: [{ id: 11, original_filename: 'file-a.pdf' }] } });
    expect(await screen.findByText('file-a.pdf')).toBeTruthy();

    rerender(<AssetDetail id="2" />);
    expect(screen.queryByText('file-a.pdf')).toBeNull();

    dB.resolve({ data: { results: [{ id: 22, original_filename: 'file-b.pdf' }] } });
    expect(await screen.findByText('file-b.pdf')).toBeTruthy();
    expect(screen.queryByText('file-a.pdf')).toBeNull();
  });

  it('shows no attachments for an asset with none', async () => {
    mockGet.mockImplementation((url, cfg) => {
      if (url === '/assets/1/') return Promise.resolve({ data: baseAsset(1, 'A1') });
      if (url === '/assets/2/') return Promise.resolve({ data: baseAsset(2, 'A2') });
      if (url === '/assets/attachments/' && cfg?.params?.asset == 1) {
        return Promise.resolve({ data: { results: [{ id: 11, original_filename: 'file-a.pdf' }] } });
      }
      return Promise.resolve({ data: { results: [] } });
    });
    const { rerender } = render(<AssetDetail id="1" />);
    expect(await screen.findByText('file-a.pdf')).toBeTruthy();

    rerender(<AssetDetail id="2" />);
    await waitFor(() => expect(screen.queryByText('file-a.pdf')).toBeNull());
    expect(screen.getByText('No attachments.')).toBeTruthy();
  });

  it('prevents a late asset A response from overwriting asset B', async () => {
    const dA = deferred();
    const dB = deferred();
    mockGet.mockImplementation((url, cfg) => {
      if (url === '/assets/1/') return Promise.resolve({ data: baseAsset(1, 'A1') });
      if (url === '/assets/2/') return Promise.resolve({ data: baseAsset(2, 'A2') });
      if (url === '/assets/attachments/' && cfg?.params?.asset == 1) return dA.promise;
      if (url === '/assets/attachments/' && cfg?.params?.asset == 2) return dB.promise;
      return Promise.resolve({ data: { results: [] } });
    });
    const { rerender } = render(<AssetDetail id="1" />);
    rerender(<AssetDetail id="2" />);
    dB.resolve({ data: { results: [{ id: 22, original_filename: 'file-b.pdf' }] } });
    expect(await screen.findByText('file-b.pdf')).toBeTruthy();

    dA.resolve({ data: { results: [{ id: 11, original_filename: 'file-a.pdf' }] } });
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText('file-a.pdf')).toBeNull();
    expect(screen.getByText('file-b.pdf')).toBeTruthy();
  });

  it('clears attachments when the request fails', async () => {
    mockGet.mockImplementation((url, cfg) => {
      if (url === '/assets/1/') return Promise.resolve({ data: baseAsset(1, 'A1') });
      if (url === '/assets/attachments/' && cfg?.params?.asset == 1) {
        return Promise.reject(new Error('boom'));
      }
      return Promise.resolve({ data: { results: [] } });
    });
    render(<AssetDetail id="1" />);
    await waitFor(() => expect(screen.getByText('No attachments.')).toBeTruthy());
    expect(screen.queryByText('file-a.pdf')).toBeNull();
  });
});
