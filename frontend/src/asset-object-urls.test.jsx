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
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
    delete: (...a) => mockDelete(...a),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...a) => mockAuth(...a),
}));

import { AssetDetail } from './assets';

const ASSET = {
  id: 3, asset_tag: 'LT-1', name: 'ThinkPad', status: 'available',
  category: 1, category_name: 'Laptop', assigned_to: null,
  assigned_to_email: null, serial_number: '', location: '',
  purchase_date: null, warranty_expiry: null, purchase_cost: null,
  description: '',
};

const ATTACHMENTS = [
  { id: 11, original_filename: 'photo.png', created_at: '2026-01-01T09:00:00Z' },
  { id: 12, original_filename: 'photo2.png', created_at: '2026-01-02T09:00:00Z' },
];

let blobCounter = 0;
let createdUrls = [];
let revokeMock;

function route(url) {
  if (url === '/assets/3/') return { data: ASSET };
  if (url === '/assets/assignments/history/') return { data: [] };
  if (url === '/assets/attachments/') return { data: { results: ATTACHMENTS } };
  if (url === '/assets/histories/') return { data: [] };
  if (url === '/assets/maintenance/') return { data: { results: [] } };
  if (url === '/assets/disposals/') return { data: { results: [] } };
  if (/^\/assets\/attachments\/1[12]\/download\/$/.test(url)) {
    return {
      data: new Blob([url], { type: 'image/png' }),
      headers: { 'content-disposition': `attachment; filename="${url.includes('11') ? 'photo.png' : 'photo2.png'}"` },
    };
  }
  throw new Error(`unexpected GET ${url}`);
}

/** Record the delayed-revocation callbacks so tests can fire them in any order. */
let delayedCallbacks = [];
let realSetTimeout;

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_support' } });
  mockGet.mockImplementation(async (url) => route(url));
  mockPost.mockResolvedValue({ data: {} });
  mockPatch.mockResolvedValue({ data: ASSET });
  mockDelete.mockResolvedValue({ data: {} });

  blobCounter = 0;
  createdUrls = [];
  delayedCallbacks = [];
  URL.createObjectURL = vi.fn(() => {
    blobCounter += 1;
    const url = `blob:test-${blobCounter}`;
    createdUrls.push(url);
    return url;
  });
  revokeMock = vi.fn();
  URL.revokeObjectURL = revokeMock;

  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

  realSetTimeout = globalThis.setTimeout;
  vi.spyOn(globalThis, 'setTimeout').mockImplementation((cb, delay, ...rest) => {
    if (delay === 5000) {
      delayedCallbacks.push(cb);
      return 0;
    }
    return realSetTimeout(cb, delay, ...rest);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

async function renderDetail() {
  render(<AssetDetail id="3" />);
  await screen.findByText('ThinkPad');
  await screen.findByText('photo.png');
}

describe('AssetDetail object URL lifecycle', () => {
  it('revokes a download URL exactly once after the delayed cleanup runs', async () => {
    await renderDetail();
    fireEvent.click(screen.getAllByRole('button', { name: 'Download' })[0]);

    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
    const url = createdUrls[0];
    expect(revokeMock).not.toHaveBeenCalled();

    delayedCallbacks[0]();
    expect(revokeMock.mock.calls.filter(([u]) => u === url)).toHaveLength(1);
  });

  it('does not let a previous download cleanup revoke a newer active download URL', async () => {
    await renderDetail();

    // Download A, then B before A's delayed cleanup fires.
    fireEvent.click(screen.getAllByRole('button', { name: 'Download' })[0]);
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getAllByRole('button', { name: 'Download' })[1]);
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(2));

    const [urlA, urlB] = createdUrls;
    expect(urlA).not.toBe(urlB);

    // A's stale timer must not touch B's live URL.
    delayedCallbacks[0]();
    expect(revokeMock.mock.calls.filter(([u]) => u === urlB)).toHaveLength(0);

    // A's own URL is reclaimed (at most once per timer).
    expect(revokeMock.mock.calls.filter(([u]) => u === urlA).length).toBeGreaterThanOrEqual(1);
  });

  it('revokes the preview URL when the preview is closed', async () => {
    await renderDetail();
    fireEvent.click(screen.getByRole('button', { name: 'Preview photo.png' }));

    await waitFor(() => expect(document.querySelector('.preview-media img')).toBeTruthy());
    const url = document.querySelector('.preview-media img').getAttribute('src');
    expect(revokeMock.mock.calls.filter(([u]) => u === url)).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(revokeMock.mock.calls.filter(([u]) => u === url)).toHaveLength(1);
    expect(document.querySelector('.preview-media img')).toBeNull();
  });

  it('replaces a preview URL and keeps the currently displayed image on a live URL', async () => {
    await renderDetail();
    fireEvent.click(screen.getByRole('button', { name: 'Preview photo.png' }));
    await waitFor(() => expect(document.querySelector('.preview-media img')).toBeTruthy());
    const firstUrl = document.querySelector('.preview-media img').getAttribute('src');

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    fireEvent.click(screen.getByRole('button', { name: 'Preview photo2.png' }));
    await waitFor(() => {
      const el = document.querySelector('.preview-media img');
      expect(el).toBeTruthy();
      expect(el.getAttribute('src')).not.toBe(firstUrl);
    });
    const secondUrl = document.querySelector('.preview-media img').getAttribute('src');
    expect(revokeMock.mock.calls.filter(([u]) => u === secondUrl)).toHaveLength(0);
  });

  it('revokes the open preview URL when the component unmounts', async () => {
    render(<AssetDetail id="3" />);
    await screen.findByText('ThinkPad');
    await screen.findByText('photo.png');
    fireEvent.click(screen.getByRole('button', { name: 'Preview photo.png' }));

    await waitFor(() => expect(document.querySelector('.preview-media img')).toBeTruthy());
    const url = document.querySelector('.preview-media img').getAttribute('src');

    cleanup();
    expect(revokeMock.mock.calls.filter(([u]) => u === url)).toHaveLength(1);
  });

  it('revokes the pending download URL when the component unmounts before the timer fires', async () => {
    await renderDetail();
    fireEvent.click(screen.getAllByRole('button', { name: 'Download' })[0]);
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
    const url = createdUrls[0];

    cleanup();
    expect(revokeMock.mock.calls.filter(([u]) => u === url)).toHaveLength(1);
  });

  it('does not leave a stale busy state after a failed download', async () => {
    mockGet.mockImplementation(async (url) => {
      if (url === '/assets/attachments/11/download/') {
        throw { response: { status: 410, data: new Blob(['{}']) } };
      }
      return route(url);
    });
    await renderDetail();
    const buttons = screen.getAllByRole('button', { name: 'Download' });
    fireEvent.click(buttons[0]);

    expect(await screen.findByText('File is missing from storage.')).toBeTruthy();
    const after = screen.getAllByRole('button', { name: 'Download' });
    expect(after[0].disabled).toBe(false);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('does not leave broken object URL state after a failed preview', async () => {
    mockGet.mockImplementation(async (url) => {
      if (url === '/assets/attachments/11/download/') {
        throw { response: { status: 403, data: new Blob(['{}']) } };
      }
      return route(url);
    });
    await renderDetail();
    fireEvent.click(screen.getByRole('button', { name: 'Preview photo.png' }));

    expect(await screen.findByText('You do not have permission to preview this file.')).toBeTruthy();
    expect(document.querySelector('.preview-media img')).toBeNull();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
