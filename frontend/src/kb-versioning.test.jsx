import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';

const { mockGet, mockPatch, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPatch: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    patch: (...args) => mockPatch(...args),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({ useAuth: (...args) => mockAuth(...args) }));

import {
  KnowledgeBase, KnowledgeBaseCompare, KnowledgeBaseDetail,
  KnowledgeBaseReviewQueue, KnowledgeBaseRevisionDetail,
} from './kb';

const ARTICLE = {
  id: 1,
  title: 'VPN reset',
  slug: 'vpn-reset',
  summary: 'How to reset the VPN client',
  content: 'Step one',
  category: { id: 1, code: 'networking', name: 'Networking' },
  category_name: 'Networking',
  tags: [{ id: 1, name: 'VPN', slug: 'vpn' }],
  author: 2,
  author_name: 'Manager',
  status: 'draft',
  version: 3,
  revision_number: 2,
  submitted_at: null,
  reviewed_by: null,
  reviewed_by_name: null,
  reviewed_at: null,
  review_decision: '',
  review_comment: '',
  view_count: 4,
  created_at: '2026-01-01T10:00:00Z',
  updated_at: '2026-01-02T10:00:00Z',
};

const REV2 = {
  id: 2, article: 1, revision_number: 2, title: 'VPN reset',
  slug: 'vpn-reset', summary: 'How to reset the VPN client',
  content: 'Step one\nStep two', category: 1, category_name: 'Networking',
  tags: [{ name: 'VPN', slug: 'vpn' }], status: 'draft', author: 2,
  author_name: 'Manager', editor: 2, editor_name: 'Manager',
  change_note: 'Clarified step two', restored_from_revision: null,
  is_current: true, is_current_published: false,
  created_at: '2026-01-02T10:00:00Z',
};

const REV1 = {
  ...REV2,
  id: 1,
  revision_number: 1,
  content: 'Step one',
  change_note: 'Initial version',
  is_current: false,
  created_at: '2026-01-01T10:00:00Z',
};

function paginated(results) {
  return { data: { results, count: results.length, next: null, previous: null } };
}

function staff() {
  mockAuth.mockReturnValue({
    isStaff: true,
    isAdmin: true,
    user: { id: 9, role: 'system_admin', email: 'admin@x' },
  });
}

function employee() {
  mockAuth.mockReturnValue({
    isStaff: false,
    isAdmin: false,
    user: { id: 3, role: 'employee', email: 'emp@x' },
  });
}

function defaultGet(overrides = {}) {
  mockGet.mockImplementation(async (url, config) => {
    const u = String(url);
    if (overrides[u]) return overrides[u](config);
    if (u === '/assets/knowledge-base/') return paginated([ARTICLE]);
    if (u === '/assets/knowledge-base/1/') return { data: ARTICLE };
    if (u === '/assets/knowledge-base/1/revisions/') {
      return { data: [REV2, REV1] };
    }
    if (u === '/assets/knowledge-base/1/revisions/1/') return { data: REV1 };
    if (u === '/assets/knowledge-base/pending_review/') {
      return { data: [] };
    }
    if (u === '/assets/knowledge-base-categories/') return { data: [] };
    if (u === '/assets/knowledge-base-tags/') return { data: [] };
    return paginated([]);
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '';
  staff();
  defaultGet();
  mockPost.mockResolvedValue({ data: ARTICLE });
  mockPatch.mockResolvedValue({ data: ARTICLE });
});

afterEach(() => cleanup());

describe('KB revision history', () => {
  it('lists revisions with editor, change note and current marker', async () => {
    render(<KnowledgeBaseDetail id="1" />);
    await screen.findByText('Revision history');
    expect(await screen.findByText('Revision 2')).toBeTruthy();
    expect(screen.getByText('Revision 1')).toBeTruthy();
    expect(screen.getByText(/Clarified step two/)).toBeTruthy();
    expect(screen.getAllByText(/Manager/).length).toBeGreaterThan(0);
    expect(screen.getByText('Current')).toBeTruthy();
  });

  it('shows an empty state when no revisions exist', async () => {
    defaultGet({
      '/assets/knowledge-base/1/revisions/': () => ({ data: [] }),
    });
    render(<KnowledgeBaseDetail id="1" />);
    expect(await screen.findByText('No revisions yet.')).toBeTruthy();
  });

  it('opens a historical revision with its full snapshot', async () => {
    window.location.hash = '#/kb/1/revisions/1';
    render(<KnowledgeBaseRevisionDetail id="1" number="1" />);
    expect(await screen.findByText('Revision 1 — VPN reset')).toBeTruthy();
    expect(screen.getByText('Step one')).toBeTruthy();
    expect(screen.getByText('Initial version')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Restore this revision/ })).toBeTruthy();
  });

  it('keeps revision controls hidden from employees', async () => {
    employee();
    mockGet.mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/assets/knowledge-base/1/') return { data: { ...ARTICLE, status: 'published' } };
      return paginated([]);
    });
    render(<KnowledgeBaseDetail id="1" />);
    await screen.findByText('VPN reset');
    expect(screen.queryByTestId('revision-history')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Submit for review' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Publish' })).toBeNull();
  });
});

describe('KB revision comparison', () => {
  it('renders added and removed content without raw JSON', async () => {
    window.location.hash = '#/kb/1/compare?from=1&to=2';
    const compare = {
      article: { id: 1, title: 'VPN reset', status: 'draft', version: 3, revision_number: 2 },
      older: REV1,
      newer: REV2,
      from_revision: 1,
      to_revision: 2,
      fields: {
        title: { changed: false, old: 'VPN reset', new: 'VPN reset', parts: [{ type: 'same', text: 'VPN reset' }] },
        summary: { changed: false, old: 'How to reset the VPN client', new: 'How to reset the VPN client', parts: [] },
        content: {
          changed: true, old: 'Step one', new: 'Step one\nStep two',
          lines: [
            { type: 'same', text: 'Step one' },
            { type: 'added', text: 'Step two' },
          ],
        },
        category: { changed: false, old: 'Networking', new: 'Networking' },
        tags: { changed: false, old: ['VPN'], new: ['VPN'] },
        status: { changed: false, old: 'draft', new: 'draft' },
      },
    };
    defaultGet({ '/assets/knowledge-base/1/compare/': () => ({ data: compare }) });
    render(<KnowledgeBaseCompare id="1" />);
    expect(await screen.findByText('Compare revisions 1 → 2')).toBeTruthy();
    const added = screen.getAllByTestId('diff-line-added');
    expect(added.some((row) => row.textContent.includes('Step two'))).toBe(true);
    expect(mockGet).toHaveBeenCalledWith(
      '/assets/knowledge-base/1/compare/',
      { params: { from_revision: '1', to_revision: '2' } },
    );
  });
});

describe('KB restore', () => {
  it('asks for confirmation and shows the new revision number', async () => {
    mockPost.mockResolvedValue({
      data: { article: { ...ARTICLE, version: 4, revision_number: 3 }, revision: { revision_number: 3 } },
    });
    render(<KnowledgeBaseDetail id="1" />);
    await screen.findByText('Revision history');
    fireEvent.click(screen.getAllByRole('button', { name: 'Restore' })[0]);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Restore revision 2\?/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Restore revision' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/assets/knowledge-base/1/restore/',
      { revision_number: 2, version: 3 },
    ));
    expect(await screen.findByText(/Restored revision 2 as revision 3/)).toBeTruthy();
  });

  it('shows a conflict message when the article changed meanwhile', async () => {
    mockPost.mockRejectedValue({
      response: { status: 409, data: { detail: 'Another user modified this article after you loaded it.' } },
    });
    render(<KnowledgeBaseDetail id="1" />);
    await screen.findByText('Revision history');
    fireEvent.click(screen.getAllByRole('button', { name: 'Restore' })[0]);
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Restore revision' }));
    expect(await screen.findByText(/Another user modified this article/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reload latest' })).toBeTruthy();
  });
});

describe('KB review workflow', () => {
  it('submits a draft for review', async () => {
    mockPost.mockResolvedValue({ data: { ...ARTICLE, status: 'pending_review', review_decision: 'pending' } });
    render(<KnowledgeBaseDetail id="1" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Submit for review' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/assets/knowledge-base/1/submit_review/',
      { version: 3 },
    ));
    expect(await screen.findByText('Article submitted for review.')).toBeTruthy();
  });

  it('approves with a review comment', async () => {
    mockGet.mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/assets/knowledge-base/1/') {
        return { data: { ...ARTICLE, status: 'pending_review', review_decision: 'pending', submitted_at: '2026-01-02T10:00:00Z' } };
      }
      if (u === '/assets/knowledge-base/1/revisions/') return { data: [REV2, REV1] };
      return paginated([]);
    });
    mockPost.mockResolvedValue({ data: { ...ARTICLE, status: 'approved', review_decision: 'approved', reviewed_by_name: 'Admin' } });
    render(<KnowledgeBaseDetail id="1" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Approval comment'), { target: { value: 'Looks accurate' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/assets/knowledge-base/1/approve/',
      { comment: 'Looks accurate', version: 3 },
    ));
    expect(await screen.findByText('Article approved.')).toBeTruthy();
    expect(await screen.findByTestId('review-summary')).toBeTruthy();
  });

  it('requires a reason before rejecting', async () => {
    mockGet.mockImplementation(async (url) => {
      const u = String(url);
      if (u === '/assets/knowledge-base/1/') {
        return { data: { ...ARTICLE, status: 'pending_review', review_decision: 'pending' } };
      }
      if (u === '/assets/knowledge-base/1/revisions/') return { data: [REV2, REV1] };
      return paginated([]);
    });
    mockPost.mockResolvedValue({ data: { ...ARTICLE, status: 'draft', review_decision: 'rejected', review_comment: 'Add screenshots' } });
    render(<KnowledgeBaseDetail id="1" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }));
    const dialog = await screen.findByRole('dialog');
    const rejectButton = within(dialog).getByRole('button', { name: 'Reject' });
    expect(rejectButton.disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText('Rejection reason'), { target: { value: 'Add screenshots' } });
    fireEvent.click(rejectButton);
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/assets/knowledge-base/1/reject/',
      { comment: 'Add screenshots', version: 3 },
    ));
    expect(await screen.findByText(/Article rejected/)).toBeTruthy();
  });

  it('renders the pending review queue and its empty state', async () => {
    defaultGet({
      '/assets/knowledge-base/pending_review/': () => ({ data: [{ ...ARTICLE, title: 'Queued article', status: 'pending_review', submitted_at: '2026-01-02T10:00:00Z' }] }),
    });
    render(<KnowledgeBaseReviewQueue />);
    expect(await screen.findByText('Queued article')).toBeTruthy();
    expect(screen.getByText(/1 article awaiting review/)).toBeTruthy();

    cleanup();
    defaultGet({ '/assets/knowledge-base/pending_review/': () => ({ data: [] }) });
    render(<KnowledgeBaseReviewQueue />);
    expect(await screen.findByText('Nothing pending review.')).toBeTruthy();
  });

  it('blocks the queue for non-staff users', async () => {
    employee();
    render(<KnowledgeBaseReviewQueue />);
    expect(await screen.findByText(/do not have permission to review/)).toBeTruthy();
  });
});

describe('KB management states and conflicts', () => {
  it('shows a conflict when a stale edit is saved and offers reload', async () => {
    render(<KnowledgeBase />);
    await screen.findByText('VPN reset');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    await screen.findByRole('dialog');
    mockPatch.mockRejectedValue({
      response: { status: 409, data: { detail: 'Another user modified this article after you loaded it.' } },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText(/Another user modified this article/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reload latest' })).toBeTruthy();
    expect(mockPatch).toHaveBeenCalledWith(
      '/assets/knowledge-base/1/',
      expect.objectContaining({ version: 3 }),
    );
  });

  it('shows loading and error states for the article detail', async () => {
    mockGet.mockImplementation(async (url) => {
      if (String(url) === '/assets/knowledge-base/1/') {
        throw { response: { status: 500, data: { detail: 'Server exploded' } } };
      }
      return paginated([]);
    });
    render(<KnowledgeBaseDetail id="1" />);
    expect(await screen.findByText(/Server exploded/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  });
});
