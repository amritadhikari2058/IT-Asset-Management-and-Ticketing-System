import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockPatch, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
  },
}));

vi.mock('./auth', () => ({
  useAuth: (...args) => mockAuth(...args),
}));

import { AssetForm } from './assets';

const CREATED = {
  id: 9, asset_tag: 'LT-9', name: 'New box', status: 'available',
  serial_number: 'SN-9', category: 1, category_name: 'Laptop',
};

function route(url) {
  if (url === '/assets/categories/') return { data: { results: [] } };
  if (url === '/accounts/departments/') return { data: { results: [] } };
  throw new Error(`unexpected GET ${url}`);
}

function fillRequiredFields() {
  fireEvent.change(screen.getByPlaceholderText(/LT-0001/), {
    target: { value: 'LT-9' },
  });
  fireEvent.change(screen.getByPlaceholderText(/ThinkPad T14/), {
    target: { value: 'New box' },
  });
}

function chooseFile(name = 'spec.pdf') {
  fireEvent.change(screen.getByLabelText(/attachment/i), {
    target: { files: [new File(['x'], name, { type: 'application/pdf' })] },
  });
}

const createCalls = () =>
  mockPost.mock.calls.filter(([url]) => url === '/assets/');
const uploadCalls = () =>
  mockPost.mock.calls.filter(([url]) => url === '/assets/attachments/');

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '';
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_support' } });
  mockGet.mockImplementation(async (url) => route(url));
  mockPatch.mockResolvedValue({ data: CREATED });
  // Default: an attachment upload succeeds.
  mockPost.mockResolvedValue({ data: { id: 1, original_filename: 'spec.pdf' } });
});

afterEach(() => cleanup());

describe('AssetForm create-then-upload', () => {
  it('creates the asset first, then uploads the file to the new id', async () => {
    mockPost.mockImplementation(async (url) => {
      if (url === '/assets/') return { data: CREATED };
      return { data: { id: 1, original_filename: 'spec.pdf' } };
    });
    render(<AssetForm />);
    await screen.findByText('New asset');
    fillRequiredFields();
    chooseFile();
    fireEvent.click(screen.getByRole('button', { name: 'Create asset' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(2));
    expect(createCalls()).toHaveLength(1);
    expect(createCalls()[0][1].asset_tag).toBe('LT-9');
    const [uploadUrl, fd] = uploadCalls()[0];
    expect(uploadUrl).toBe('/assets/attachments/');
    expect(fd).toBeInstanceOf(FormData);
    expect(fd.get('asset')).toBe('9');
    expect(fd.get('file')).toBeInstanceOf(File);
    await waitFor(() => expect(window.location.hash).toBe('#/assets/9'));
  });

  it('sends JSON with no file when none was chosen', async () => {
    mockPost.mockImplementation(async () => ({ data: CREATED }));
    render(<AssetForm />);
    await screen.findByText('New asset');
    fillRequiredFields();
    fireEvent.click(screen.getByRole('button', { name: 'Create asset' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    expect(createCalls()[0][1]).toBeTypeOf('object');
    expect(uploadCalls()).toHaveLength(0);
    await waitFor(() => expect(window.location.hash).toBe('#/assets/9'));
  });

  it('reports the partial outcome and retries the upload without re-creating', async () => {
    mockPost
      .mockImplementationOnce(async () => ({ data: CREATED }))
      .mockRejectedValueOnce({
        response: { status: 500, data: { detail: 'Storage unavailable.' } },
      });
    render(<AssetForm />);
    await screen.findByText('New asset');
    fillRequiredFields();
    chooseFile();
    fireEvent.click(screen.getByRole('button', { name: 'Create asset' }));

    // Banner explains both halves: asset exists, file does not.
    const banner = await screen.findByText(/was created, but/i);
    expect(banner.textContent).toMatch(/#9/);
    expect(banner.textContent).toMatch(/LT-9/);
    expect(banner.textContent).toMatch(/Storage unavailable\./);
    expect(banner.textContent).toMatch(/will not create a second asset/);
    // Stays on the form; the create button is locked so a resubmit cannot
    // produce a twin asset.
    expect(window.location.hash).toBe('');
    expect(screen.getByRole('button', { name: 'Create asset' }).disabled).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'Retry upload' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(3));
    expect(uploadCalls()).toHaveLength(2);
    expect(createCalls()).toHaveLength(1);
    expect(uploadCalls()[1][1].get('asset')).toBe('9');
    await waitFor(() => expect(window.location.hash).toBe('#/assets/9'));
  });

  it('keeps the banner and the upload-only retry after a second failure', async () => {
    mockPost
      .mockImplementationOnce(async () => ({ data: CREATED }))
      .mockRejectedValueOnce({ response: { status: 400, data: { file: ['Too large.'] } } })
      .mockRejectedValueOnce({ response: { status: 400, data: { file: ['Too large.'] } } });
    render(<AssetForm />);
    await screen.findByText('New asset');
    fillRequiredFields();
    chooseFile('huge.pdf');
    fireEvent.click(screen.getByRole('button', { name: 'Create asset' }));

    fireEvent.click(await screen.findByRole('button', { name: 'Retry upload' }));
    const banner = await screen.findByText(/was created, but/i);
    expect(banner.textContent).toMatch(/Too large\./);
    expect(createCalls()).toHaveLength(1);
    expect(uploadCalls()).toHaveLength(2);
    expect(window.location.hash).toBe('');
  });

  it('rejects a disallowed file type before creating anything', async () => {
    render(<AssetForm />);
    await screen.findByText('New asset');
    fillRequiredFields();
    chooseFile('setup.exe');
    fireEvent.click(screen.getByRole('button', { name: 'Create asset' }));
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toMatch(/not an allowed file type/i);
    });
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('rejects an oversized file before creating anything', async () => {
    render(<AssetForm />);
    await screen.findByText('New asset');
    fillRequiredFields();
    const big = new File(['x'], 'huge.pdf', { type: 'application/pdf' });
    Object.defineProperty(big, 'size', { value: 11 * 1024 * 1024 });
    fireEvent.change(screen.getByLabelText(/attachment/i), {
      target: { files: [big] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create asset' }));
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toMatch(/maximum upload size is 10 MB/i);
    });
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('shows a field-level error when the server rejects the file or serial', async () => {
    mockPost.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { serial_number: ["Serial number 'SN-9' is already used by another asset."] },
      },
      message: 'Request failed with status code 400',
    });
    render(<AssetForm />);
    await screen.findByText('New asset');
    fillRequiredFields();
    chooseFile();
    fireEvent.click(screen.getByRole('button', { name: 'Create asset' }));
    // Nothing was created, so nothing to retry: the error lands on the field.
    expect(await screen.findByText(/already used by another asset/)).toBeTruthy();
    expect(uploadCalls()).toHaveLength(0);
    expect(window.location.hash).toBe('');
  });

  it('shows no attachment input when editing an existing asset', async () => {
    mockGet.mockImplementation(async (url) => {
      if (url === '/assets/3/') return { data: { ...CREATED, id: 3 } };
      return route(url);
    });
    render(<AssetForm id="3" />);
    await screen.findByText('Edit asset #3');
    expect(screen.queryByLabelText(/attachment/i)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    expect(mockPost).not.toHaveBeenCalled();
  });
});
