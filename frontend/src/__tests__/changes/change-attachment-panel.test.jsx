import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const { mockGet, mockPost } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
  },
}));

import { ChangeAttachmentPanel } from '../../pages/changes/ChangeAttachmentPanel';

const attachment = {
  id: 31,
  change: 7,
  document_type: 'implementation_plan',
  original_filename: 'implementation-plan.pdf',
  uploaded_by_email: 'manager@example.com',
  description: 'Approved plan',
  size: 2048,
  created_at: '2026-11-28T05:00:00Z',
};

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ChangeAttachmentPanel', () => {
  it('displays only attachments belonging to the current change', async () => {
    mockGet.mockResolvedValueOnce({
      data: [
        attachment,
        { ...attachment, id: 32, change: 8, original_filename: 'other-change.pdf' },
      ],
    });

    render(<ChangeAttachmentPanel changeId="7" />);

    expect(await screen.findByText('implementation-plan.pdf')).toBeTruthy();
    expect(screen.queryByText('other-change.pdf')).toBeNull();
    expect(screen.getByText('manager@example.com')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith('/changes/attachments/');
  });

  it('shows the empty state', async () => {
    mockGet.mockResolvedValueOnce({ data: [] });
    render(<ChangeAttachmentPanel changeId="7" />);

    expect(
      await screen.findByText('No attachments have been uploaded for this change.'),
    ).toBeTruthy();
  });

  it('uploads the expected multipart fields and reloads attachments', async () => {
    mockGet
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({ data: [attachment] });
    mockPost.mockResolvedValueOnce({ data: attachment });

    render(<ChangeAttachmentPanel changeId="7" />);
    await screen.findByText('No attachments have been uploaded for this change.');

    const file = new File(['plan contents'], 'plan.pdf', { type: 'application/pdf' });
    fireEvent.change(screen.getByLabelText('File'), {
      target: { files: [file] },
    });
    fireEvent.change(screen.getByLabelText('Document type'), {
      target: { value: 'implementation_plan' },
    });
    fireEvent.change(screen.getByLabelText('Description'), {
      target: { value: ' Approved plan ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Upload attachment' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));

    const [url, body] = mockPost.mock.calls[0];
    expect(url).toBe('/changes/attachments/');
    expect(body).toBeInstanceOf(FormData);
    expect(body.get('change')).toBe('7');
    expect(body.get('document_type')).toBe('implementation_plan');
    expect(body.get('description')).toBe('Approved plan');
    expect(body.get('file').name).toBe('plan.pdf');

    expect(await screen.findByText('Attachment uploaded successfully.')).toBeTruthy();
    expect(await screen.findByText('implementation-plan.pdf')).toBeTruthy();
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('downloads through the authenticated API and revokes the object URL', async () => {
    mockGet
      .mockResolvedValueOnce({ data: [attachment] })
      .mockResolvedValueOnce({
        data: new Blob(['file contents'], { type: 'application/pdf' }),
        headers: {
          'content-disposition': 'attachment; filename="implementation-plan.pdf"',
        },
      });

    const createObjectURL = vi.fn(() => 'blob:test-download');
    const revokeObjectURL = vi.fn();

    Object.defineProperty(window.URL, 'createObjectURL', {
      configurable: true,
      value: createObjectURL,
    });
    Object.defineProperty(window.URL, 'revokeObjectURL', {
      configurable: true,
      value: revokeObjectURL,
    });

    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});

    render(<ChangeAttachmentPanel changeId="7" />);
    await screen.findByText('implementation-plan.pdf');
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));

    await waitFor(() => {
      expect(mockGet).toHaveBeenLastCalledWith(
        '/changes/attachments/31/download/',
        { responseType: 'blob' },
      );
    });

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:test-download');
  });

  it('shows the API error when loading fails', async () => {
    mockGet.mockRejectedValueOnce({
      response: { data: { detail: 'Attachment access denied.' } },
    });

    render(<ChangeAttachmentPanel changeId="7" />);
    expect((await screen.findByRole('alert')).textContent).toContain(
      'Attachment access denied.',
    );
  });

  it('shows the API error when upload fails', async () => {
    mockGet.mockResolvedValueOnce({ data: [] });
    mockPost.mockRejectedValueOnce({
      response: { data: { detail: 'File type is not allowed.' } },
    });

    render(<ChangeAttachmentPanel changeId="7" />);
    await screen.findByText('No attachments have been uploaded for this change.');

    fireEvent.change(screen.getByLabelText('File'), {
      target: {
        files: [new File(['bad'], 'bad.exe', { type: 'application/octet-stream' })],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Upload attachment' }));

    expect((await screen.findByRole('alert')).textContent).toContain(
      'File type is not allowed.',
    );
  });
});