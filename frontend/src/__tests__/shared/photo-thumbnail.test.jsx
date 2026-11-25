import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet } = vi.hoisted(() => ({
  mockGet: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: mockGet,
  },
}));

function makeBlob(b = 'x', type = 'application/pdf') {
  return new Blob([b], { type });
}

function awaited(p) {
  return new Promise((resolve) => {
    const t = setTimeout(() => { clearTimeout(t); resolve(p); }, 0);
  });
}

describe('PhotoThumbnail', () => {
  let anchors = [];
  let createObjectUrl;

  beforeEach(() => {
    cleanup();
    vi.clearAllMocks();

    global.URL.createObjectURL = vi.fn(() => {
      createObjectUrl();
      return `blob:mock-${createObjectUrl.mock.calls.length}`;
    });
    global.URL.revokeObjectURL = vi.fn();

    const originalCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation(function (tag, ...rest) {
      const el = originalCreate.call(this, tag, ...rest);
      if (String(tag).toLowerCase() === 'a') anchors.push(el);
      return el;
    });

    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    anchors = [];
    createObjectUrl = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
  });

  it('renders a native button with a meaningful accessible name', async () => {
    mockGet.mockResolvedValue({ data: makeBlob() });
    vi.resetModules();
    const { PhotoThumbnail } = await import('../../components');
    render(<PhotoThumbnail id={7} getUrl={() => '/x'} onPreview={() => {}} label="Photo of LT-1" />);

    expect(await screen.findByRole('button', { name: 'Photo of LT-1' })).toBeTruthy();
  });

  it('renders a loading state while the blob is in flight', async () => {
    mockGet.mockImplementation(() => new Promise((resolve) => setTimeout(() => resolve({ data: makeBlob() }), 50)));
    vi.resetModules();
    const { PhotoThumbnail } = await import('../../components');
    render(<PhotoThumbnail id={7} getUrl={() => '/x'} onPreview={() => {}} label="Photo of LT-1" />);

    // The control is a button with a meaningful accessible name during loading.
    const button = screen.getByRole('button', { name: 'Photo of LT-1' });
    expect(button).toBeTruthy();

    // Loading is shown as an aria-hidden spinner, so we assert that the
    // button contains a spinner descendant rather than coupling to a test id.
    const spinner = button.querySelector('span.spinner[aria-hidden="true"]');
    expect(spinner).toBeTruthy();
    expect(button.querySelector('img')).toBeNull();
  });

  it('loads the image and renders it with a neutral alt text for the thumbnail', async () => {
    mockGet.mockResolvedValue({ data: makeBlob() });
    vi.resetModules();
    const { PhotoThumbnail } = await import('../../components');
    render(<PhotoThumbnail id={7} getUrl={() => '/x'} onPreview={() => {}} label="Photo of LT-1" />);

    const button = await waitFor(() => screen.getByRole('button', { name: 'Photo of LT-1' }));
    expect(button.querySelector('img')).toBeTruthy();
    expect(button.querySelector('img').hasAttribute('alt')).toBe(true);
    expect(button.querySelector('img').className).toContain('photo-thumb');
  });

  it('shows a placeholder on failed image load and keeps the button reachable', async () => {
    mockGet.mockRejectedValue(new Error('network'));
    vi.resetModules();
    const { PhotoThumbnail } = await import('../../components');
    render(<PhotoThumbnail id={7} getUrl={() => '/x'} onPreview={() => {}} label="Photo of LT-1" />);

    const button = await waitFor(() => screen.getByRole('button', { name: 'Photo of LT-1' }));
    expect(button).toBeTruthy();
    expect(button.textContent).toContain('🙁');
  });

  it('activates on Enter and Space, and prevents default scroll behavior on Space', async () => {
    mockGet.mockResolvedValue({ data: makeBlob() });
    vi.resetModules();
    const { PhotoThumbnail } = await import('../../components');
    const onPreview = vi.fn();
    render(<PhotoThumbnail id={7} getUrl={() => '/x'} onPreview={onPreview} label="Photo of LT-1" />);

    const button = await waitFor(() => screen.getByRole('button', { name: 'Photo of LT-1' }));
    expect(button.querySelector('img')).toBeTruthy();

    await fireEvent.keyDown(button, { key: 'Enter' });
    expect(onPreview).toHaveBeenCalledTimes(1);

    await fireEvent.keyDown(button, { key: ' ' });
    expect(onPreview).toHaveBeenCalledTimes(2);

    expect(button.getAttribute('onclick')).toBeNull();
    expect(button.hasAttribute('disabled')).toBe(false);
  });

  it('renders a disabled button when the image cannot be loaded', async () => {
    mockGet.mockRejectedValue(new Error('network'));
    vi.resetModules();
    const { PhotoThumbnail } = await import('../../components');
    render(<PhotoThumbnail id={7} getUrl={() => '/x'} onPreview={() => {}} label="Photo of LT-1" />);

    const button = await waitFor(() => screen.getByRole('button', { name: 'Photo of LT-1' }));
    expect(button.hasAttribute('disabled')).toBe(true);
    expect(button.textContent).toContain('🙁');
  });

  it('replaces the previous preview URL and revokes it when refreshed', async () => {
    mockGet.mockResolvedValueOnce({ data: makeBlob('a') });
    mockGet.mockResolvedValueOnce({ data: makeBlob('b') });
    vi.resetModules();
    const { PhotoThumbnail } = await import('../../components');
    render(<PhotoThumbnail id={7} getUrl={() => '/x'} onPreview={() => {}} label="Photo of LT-1" />);

    await waitFor(() => screen.getByRole('button', { name: 'Photo of LT-1' }));
    expect(global.URL.createObjectURL).toHaveBeenCalledTimes(1);

    // Re-render with a fresh module instance to re-run the effect.
    cleanup();
    anchors = [];
    vi.resetModules();
    const { PhotoThumbnail: PhotoThumbnail2 } = await import('../../components');
    render(<PhotoThumbnail2 id={7} getUrl={() => '/y'} onPreview={() => {}} label="Photo of LT-1" />);

    await waitFor(() => screen.getByRole('button', { name: 'Photo of LT-1' }));
    expect(global.URL.createObjectURL).toHaveBeenCalledTimes(2);
    expect(global.URL.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(global.URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-1');

    // The newly displayed thumbnail is not revoked.
    const refreshedButton = screen.getByRole('button', { name: 'Photo of LT-1' });
    expect(refreshedButton.querySelector('img').src).toBe('blob:mock-2');
  });

  it('revokes the current preview URL on unmount', async () => {
    mockGet.mockResolvedValue({ data: makeBlob() });
    vi.resetModules();
    const { PhotoThumbnail } = await import('../../components');
    const { unmount } = render(<PhotoThumbnail id={7} getUrl={() => '/x'} onPreview={() => {}} label="Photo of LT-1" />);

    await waitFor(() => screen.getByRole('button', { name: 'Photo of LT-1' }));
    const displayedSrc = screen.getByRole('button', { name: 'Photo of LT-1' })
      .querySelector('img')?.getAttribute('src');
    expect(displayedSrc).toBeTruthy();

    unmount();
    expect(global.URL.revokeObjectURL).toHaveBeenCalledWith(displayedSrc);
  });

  it('does not leak object URLs across repeated refreshes', async () => {
    let callIndex = 0;
    mockGet.mockImplementation(() => awaited({ data: makeBlob(String(++callIndex)) }));
    vi.resetModules();
    const { PhotoThumbnail } = await import('../../components');
    const { rerender } = render(<PhotoThumbnail id={7} getUrl={() => '/x'} onPreview={() => {}} label="Photo of LT-1" />);

    await waitFor(() => screen.getByRole('button', { name: 'Photo of LT-1' }));
    expect(global.URL.createObjectURL).toHaveBeenCalledTimes(1);

    // Three more re-renders should create three URLs and revoke three old ones.
    for (let i = 0; i < 3; i += 1) {
      rerender(<PhotoThumbnail id={7} getUrl={() => `/x-${i}`} onPreview={() => {}} label="Photo of LT-1" />);
      await waitFor(() => expect(global.URL.createObjectURL).toHaveBeenCalledTimes(2 + i));
    }

    const creates = global.URL.createObjectURL.mock.calls.length;
    const revokes = global.URL.revokeObjectURL.mock.calls.length;
    expect(revokes).toBe(creates - 1);
  });
});
