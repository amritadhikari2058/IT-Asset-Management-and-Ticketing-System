import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
  },
}));

vi.mock('../../auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { AssetDetail, AssetForm } from '../../pages/assets/Assets';

const ASSET = {
  id: 3, asset_tag: 'LT-1', name: 'ThinkPad', status: 'available',
  category: 1, category_name: 'Laptop', assigned_to: null,
  assigned_to_email: null, serial_number: '', location: '',
  purchase_date: null, warranty_expiry: null, purchase_cost: null,
  description: '',
};

function staff() {
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_support' } });
}

function route(url) {
  if (url === '/assets/3/') return { data: ASSET };
  if (url === '/assets/assignments/history/') return { data: [] };
  if (url === '/assets/attachments/') return { data: [] };
  if (url === '/assets/histories/') return { data: [] };
  if (url === '/assets/categories/') return { data: { results: [] } };
  throw new Error(`unexpected GET ${url}`);
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockGet.mockImplementation(async (url) => route(url));
  mockPost.mockResolvedValue({ data: ASSET });
  mockPatch.mockResolvedValue({ data: ASSET });
});

afterEach(() => cleanup());

describe('Asset mark-lost workflow', () => {
  it('opens the dialog, requires a reason, and posts it', async () => {
    staff();
    render(<AssetDetail id="3" />);
    expect(await screen.findByText('ThinkPad')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Mark lost…' }));
    const submit = screen.getByRole('button', { name: 'Mark lost' });
    // Required reason: blank stays disabled.
    expect(submit.disabled).toBe(true);
    fireEvent.change(screen.getByPlaceholderText(/last seen/i), {
      target: { value: 'Vanished from desk.' },
    });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/assets/3/mark_lost/', {
        reason: 'Vanished from desk.',
      });
    });
  });

  it('shows backend errors without closing the dialog', async () => {
    staff();
    mockPost.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'A reason is required.' } },
    });
    render(<AssetDetail id="3" />);
    await screen.findByText('ThinkPad');
    fireEvent.click(screen.getByRole('button', { name: 'Mark lost…' }));
    fireEvent.change(screen.getByPlaceholderText(/last seen/i), {
      target: { value: 'x' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Mark lost' }));
    expect(await screen.findByText('A reason is required.')).toBeTruthy();
  });
});

describe('AssetForm status dropdown', () => {
  // NOTE: Field labels are not htmlFor-associated, so selects are found
  // by role order: category select first, status select second.
  const statusSelect = () => screen.getAllByRole('combobox')[1];

  it('disables dedicated-workflow statuses on edit', async () => {
    staff();
    render(<AssetForm id="3" />);
    await screen.findByText('Edit asset #3');
    const options = [...statusSelect().querySelectorAll('option')];
    const byValue = Object.fromEntries(options.map((o) => [o.value, o.disabled]));
    expect(byValue.available).toBe(false);
    expect(byValue.in_repair).toBe(false);
    expect(byValue.assigned).toBe(true);
    expect(byValue.retired).toBe(true);
    expect(byValue.lost).toBe(true);
  });

  it('keeps the current status selectable when resubmitting', async () => {
    staff();
    mockGet.mockImplementation(async (url) => {
      if (url === '/assets/3/') {
        return { data: { ...ASSET, status: 'retired' } };
      }
      return route(url);
    });
    render(<AssetForm id="3" />);
    await screen.findByText('Edit asset #3');
    const select = statusSelect();
    const options = [...select.querySelectorAll('option')];
    const byValue = Object.fromEntries(options.map((o) => [o.value, o.disabled]));
    expect(select.value).toBe('retired');
    expect(byValue.retired).toBe(false);
    expect(byValue.assigned).toBe(true);
    expect(byValue.lost).toBe(true);
  });
});

const ATTACHMENTS = [
  { id: 11, original_filename: 'report.pdf', created_at: '2026-01-01T09:00:00Z' },
  { id: 12, original_filename: 'specs.docx', created_at: '2026-01-02T09:00:00Z' },
];

describe('AssetDetail attachment download', () => {
  let anchors;
  let clickSpy;

  const detailRoute = (url) => {
    if (url === '/assets/3/') return { data: ASSET };
    if (url === '/assets/assignments/history/') return { data: [] };
    if (url === '/assets/attachments/') return { data: { results: ATTACHMENTS } };
    if (url === '/assets/histories/') return { data: [] };
    if (url === '/assets/maintenance/') return { data: { results: [] } };
    if (url === '/assets/disposals/') return { data: { results: [] } };
    if (url === '/assets/attachments/11/download/') {
      return {
        data: new Blob(['%PDF-1.4'], { type: 'application/pdf' }),
        headers: { 'content-disposition': 'attachment; filename="report.pdf"' },
      };
    }
    throw new Error(`unexpected GET ${url}`);
  };

  const clickingDownload = async () => {
    render(<AssetDetail id="3" />);
    await screen.findByText('report.pdf');
    fireEvent.click(screen.getAllByRole('button', { name: 'Download' })[0]);
  };

  beforeEach(() => {
    staff();
    mockGet.mockImplementation(async (url) => detailRoute(url));
    anchors = [];
    const createElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag, ...rest) => {
      const el = createElement(tag, ...rest);
      if (String(tag).toLowerCase() === 'a') anchors.push(el);
      return el;
    });
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    URL.createObjectURL = vi.fn(() => 'blob:mock');
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
  });

  it('fetches the protected blob, clicks a temporary anchor, and revokes the object URL', async () => {
    const timeouts = vi.spyOn(globalThis, 'setTimeout');
    await clickingDownload();

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(
      '/assets/attachments/11/download/', { responseType: 'blob' },
    ));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));

    const anchor = anchors.find((a) => a.download === 'report.pdf');
    expect(anchor).toBeTruthy();
    expect(anchor.href).toBe('blob:mock');
    expect(clickSpy).toHaveBeenCalledTimes(1);
    // The anchor is removed from the document straight after the click.
    expect(anchor.isConnected).toBe(false);

    const revoke = timeouts.mock.calls.find(([, delay]) => delay === 5000)?.[0];
    expect(typeof revoke).toBe('function');
    revoke();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock');
  });

  it.each([
    [410, 'File is missing from storage.'],
    [404, 'Attachment not available (deleted or no access).'],
    [403, 'You do not have permission to download this file.'],
  ])('shows a safe message for a %s download failure', async (status, message) => {
    mockGet.mockImplementation(async (url) => {
      if (url === '/assets/attachments/11/download/') {
        throw { response: { status, data: new Blob(['{"detail":"nope"}']) } };
      }
      return detailRoute(url);
    });
    await clickingDownload();
    expect(await screen.findByText(message)).toBeTruthy();
    // No object URL or anchor is produced for a failed download.
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(anchors.some((a) => a.download === 'report.pdf')).toBe(false);
  });
});
