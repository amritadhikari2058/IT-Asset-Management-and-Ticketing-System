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
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({ useAuth: (...args) => mockAuth(...args) }));

import { SelfService } from './self-service';

function employee() {
  mockAuth.mockReturnValue({
    isStaff: false,
    isAdmin: false,
    user: { id: 3, employee_id: 'E1', role: 'employee', email: 'emp@x' },
  });
}

const KB_RESULTS = {
  data: {
    results: [
      {
        id: 1, title: 'VPN reset', slug: 'vpn-reset',
        summary: 'How to reset the VPN client', content: 'Step one',
        category: { id: 1, name: 'Networking', code: 'networking' },
        tags: [{ name: 'VPN', slug: 'vpn' }],
        status: 'published', author: 2, author_name: 'Manager',
        created_at: '2026-01-01T10:00:00Z',
        updated_at: '2026-01-02T10:00:00Z', revision_number: 1,
      },
      {
        id: 2, title: 'Database backup', slug: 'db-backup',
        summary: 'Run pg_dump nightly.', content: 'pg_dump -F db',
        category: { id: 1, name: 'Networking', code: 'networking' },
        tags: [], status: 'published', author: 2,
        author_name: 'Manager', created_at: '2026-01-03T10:00:00Z',
        updated_at: '2026-01-03T11:00:00Z', revision_number: 1,
      },
    ],
    count: 2, next: null, previous: null,
  },
};

const EMPTY_RESULTS = {
  data: { results: [], count: 0, next: null, previous: null },
};

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.location.hash = '';
  employee();
  mockGet.mockImplementation(async (url) => {
    const u = String(url);
    if (u === '/common/knowledge-base/') return KB_RESULTS;
    if (u === '/tickets/') return EMPTY_RESULTS;
    if (u === '/assets/') return EMPTY_RESULTS;
    return EMPTY_RESULTS;
  });
});

afterEach(() => cleanup());

describe('Self-service Knowledge Base search', () => {
  it('searches published articles and renders results', async () => {
    render(<SelfService />);
    const input = screen.getByPlaceholderText(/Search articles/);
    fireEvent.change(input, { target: { value: 'vpn' } });
    await waitFor(() =>
      expect(mockGet).toHaveBeenCalledWith(
        '/common/knowledge-base/',
        expect.objectContaining({ params: { q: 'vpn' } }),
      ),
    );
    expect(await screen.findByText('VPN reset')).toBeTruthy();
    expect(screen.getAllByText('Category: Networking').length).toBeGreaterThanOrEqual(1);
  });

  it('renders an empty state when nothing matches', async () => {
    mockGet.mockImplementation(async (url) => {
      if (url === '/common/knowledge-base/') return EMPTY_RESULTS;
      return EMPTY_RESULTS;
    });
    render(<SelfService />);
    const input = screen.getByPlaceholderText(/Search articles/);
    fireEvent.change(input, { target: { value: 'zzz-no-match' } });
    await waitFor(() =>
      expect(screen.getByText(/No articles found/)).toBeTruthy(),
    );
  });

  it('links each article to its detail page', async () => {
    render(<SelfService />);
    const input = screen.getByPlaceholderText(/Search articles/);
    fireEvent.change(input, { target: { value: 'vpn' } });
    await screen.findByText('VPN reset');
    const articleLinks = Array.from(
      document.querySelectorAll('a[href^="#/kb/"]'),
    ).map((a) => a.getAttribute('href'));
    expect(new Set(articleLinks)).toEqual(new Set(['#/kb/1', '#/kb/2']));
  });
});
