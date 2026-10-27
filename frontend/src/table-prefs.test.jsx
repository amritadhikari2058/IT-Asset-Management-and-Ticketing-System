import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

const { mockGet, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('./auth', () => ({ useAuth: (...args) => mockAuth(...args) }));

vi.mock('./bulk', () => ({
  AssetBulkCreateModal: () => null,
  EmployeeCreateModal: () => null,
  EmployeeImportModal: () => null,
  TicketBulkCreateModal: () => null,
}));

import { useTableColumns } from './components';
import { Tickets, Assets } from './pages';

const PREFIX = 'itdesk.tableprefs.';

/** Hook harness: one toggle button per column + table toggle + reset. */
function PrefsHarness({ tableKey, columns, defaultKeys }) {
  const { visibleColumns, toggleColumn, resetColumns, tableVisible, toggleTable } =
    useTableColumns(tableKey, columns, defaultKeys ?? columns.slice(0, 1));
  return (
    <div>
      <output data-testid="visible">{[...visibleColumns].sort().join(',')}</output>
      <button type="button" onClick={toggleTable}>toggle table</button>
      <button type="button" onClick={resetColumns}>reset</button>
      {columns.map((c) => (
        <button key={c} type="button" onClick={() => toggleColumn(c)}>
          toggle {c}
        </button>
      ))}
      <output data-testid="table-visible">{String(tableVisible)}</output>
    </div>
  );
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  Object.keys(localStorage)
    .filter((k) => k.startsWith(PREFIX))
    .forEach((k) => localStorage.removeItem(k));
});

afterEach(() => cleanup());

describe('useTableColumns persistence', () => {
  it('saves toggles to per-table storage and survives a re-mount (refresh)', () => {
    const cols = ['a-toggle', 'b-tag', 'c-user'];
    const { unmount } = render(<PrefsHarness tableKey="assets" columns={cols} />);
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle');
    fireEvent.click(screen.getByRole('button', { name: 'toggle b-tag' }));
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle,b-tag');
    unmount();
    // Fresh mount = same as loading the page after a refresh.
    render(<PrefsHarness tableKey="assets" columns={cols} />);
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle,b-tag');
    expect(JSON.parse(localStorage.getItem(`${PREFIX}assets`))).toMatchObject({
      v: 1,
      columns: ['a-toggle', 'b-tag'],
      table: true,
    });
  });

  it('keeps tables independent (one storage key per table)', () => {
    const cols = ['a-toggle', 'b-tag'];
    render(<PrefsHarness tableKey="assets" columns={cols} />);
    fireEvent.click(screen.getByRole('button', { name: 'toggle b-tag' }));
    cleanup();
    render(<PrefsHarness tableKey="tickets" columns={cols} />);
    // The tickets table never saw the assets change.
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle');
    localStorage.removeItem(`${PREFIX}tickets`);
    expect(JSON.parse(localStorage.getItem(`${PREFIX}assets`)).columns)
      .toEqual(['a-toggle', 'b-tag']);
  });

  it('resets only the one table to its defaults', () => {
    const cols = ['a-toggle', 'b-tag', 'x-extra'];
    const defaults = ['a-toggle', 'b-tag'];
    render(<PrefsHarness tableKey="assets" columns={cols} defaultKeys={defaults} />);
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle,b-tag');
    fireEvent.click(screen.getByRole('button', { name: 'toggle x-extra' }));
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle,b-tag,x-extra');
    fireEvent.click(screen.getByRole('button', { name: 'reset' }));
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle,b-tag');
    // The reset only wrote this table's preference.
    expect(JSON.parse(localStorage.getItem(`${PREFIX}assets`)))
      .toEqual({ v: 1, columns: ['a-toggle', 'b-tag'], known: cols, table: true });
  });

  it('persists the table show/hide state', () => {
    render(<PrefsHarness tableKey="tickets" columns={['a-toggle', 'b-tag']} />);
    fireEvent.click(screen.getByRole('button', { name: 'toggle table' }));
    expect(screen.getByTestId('table-visible').textContent).toBe('false');
    cleanup();
    render(<PrefsHarness tableKey="tickets" columns={['a-toggle', 'b-tag']} />);
    expect(screen.getByTestId('table-visible').textContent).toBe('false');
  });

  it('recovers safely from malformed saved preferences', () => {
    localStorage.setItem(`${PREFIX}assets`, 'not-json{{');
    const cols = ['a-toggle', 'b-tag'];
    render(<PrefsHarness tableKey="assets" columns={cols} />);
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle');
    expect(screen.getByTestId('table-visible').textContent).toBe('true');
  });

  it('ignores non-object / wrong-schema payloads', () => {
    localStorage.setItem(`${PREFIX}assets`, JSON.stringify([1, 2]));
    const cols = ['a-toggle', 'b-tag'];
    render(<PrefsHarness tableKey="assets" columns={cols} />);
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle');
    expect(screen.getByTestId('table-visible').textContent).toBe('true');
  });

  it('gives newly introduced columns a sensible default visibility', () => {
    // Saved before a future update added `c-new` as a default column: the
    // user's own selection is untouched, and the never-seen column shows
    // because the CURRENT defaults list it as visible.
    localStorage.setItem(`${PREFIX}assets`, JSON.stringify({
      v: 1,
      columns: ['a-toggle'],
      known: ['a-toggle', 'b-tag'],
      table: true,
    }));
    render(<PrefsHarness
      tableKey="assets"
      columns={['a-toggle', 'b-tag', 'c-new']}
      defaultKeys={['a-toggle', 'c-new']}
    />);
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle,c-new');
  });

  it('recovers from an all-false stored set instead of rendering none', () => {
    localStorage.setItem(`${PREFIX}assets`, JSON.stringify({
      v: 1, columns: [], known: ['a-toggle', 'b-tag'], table: true,
    }));
    const cols = ['a-toggle', 'b-tag'];
    // Defaults are the first column: an all-false payload falls back to them.
    render(<PrefsHarness tableKey="assets" columns={cols} />);
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle');
  });

  it('drops stale keys that no longer exist in the current table', () => {
    localStorage.setItem(`${PREFIX}assets`, JSON.stringify({
      v: 1,
      columns: ['a-toggle', 'gone-column'],
      known: ['a-toggle', 'b-tag', 'gone-column'],
      table: false,
    }));
    const cols = ['a-toggle', 'b-tag'];
    render(<PrefsHarness tableKey="assets" columns={cols} />);
    expect(screen.getByTestId('visible').textContent).toBe('a-toggle');
    expect(screen.getByTestId('table-visible').textContent).toBe('false');
  });
});

describe('Tables use persisted prefs (page level)', () => {
  function staff() {
    mockAuth.mockReturnValue({
      isStaff: true, isAdmin: true, canCreateTickets: true,
      user: { id: 1, role: 'system_admin' },
    });
  }

  beforeEach(() => {
    staff();
    mockGet.mockImplementation(async (url) => {
      const u = String(url);
      if (u.startsWith('/assets/')) {
        return {
          data: {
            results: [{
              id: 1, asset_tag: 'LT-1', name: 'ThinkPad', status: 'available',
              category_name: 'Laptop', department_name: null,
              assigned_to_email: null, serial_number: '', location: 'HQ',
              description: '', purchase_date: null, warranty_expiry: null,
              purchase_cost: null, photo_attachment_id: null, created_at: null,
            }],
            count: 1, next: null, previous: null,
          },
        };
      }
      if (u.startsWith('/tickets/')) {
        return {
          data: {
            results: [{
              id: 2, title: 'T', status: 'open', priority: 'low',
              category_name: 'C', assignee_email: null, requester_email: null,
              department_name: null, asset_tag: null, asset: null,
              description: '', on_behalf_reason: '', resolution_notes: '',
              created_at: null, updated_at: null, resolved_at: null,
              closed_at: null,
            }],
            count: 1, next: null, previous: null,
          },
        };
      }
      return { data: { results: [], count: 0, next: null, previous: null } };
    });
  });

  it('restores hidden columns after a remount and keeps tables separate', async () => {
    const { unmount } = render(<Assets />);
    await screen.findByText('LT-1');
    fireEvent.click(screen.getByRole('button', { name: 'Columns' }));
    fireEvent.click(screen.getByLabelText('Show Name column'));
    expect(
      JSON.parse(localStorage.getItem(`${PREFIX}assets`)).columns,
    ).not.toContain('name');
    expect(screen.queryByRole('columnheader', { name: 'Name' })).toBeNull();
    unmount();

    render(<Tickets />);
    await screen.findByText('T');
    expect(screen.getByRole('columnheader', { name: 'Subject' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Columns' }));
    fireEvent.click(screen.getByLabelText('Show Subject column'));
    expect(
      JSON.parse(localStorage.getItem(`${PREFIX}tickets`)).columns,
    ).not.toContain('title');
    cleanup();

    // Closing the browser / returning to the page: prefs load again.
    render(<Assets />);
    await screen.findByText('LT-1');
    fireEvent.click(screen.getByRole('button', { name: 'Columns' }));
    expect(screen.getByLabelText('Show Name column').checked).toBe(false);
    expect(
      JSON.parse(localStorage.getItem(`${PREFIX}tickets`)).columns,
    ).not.toContain('title');
  });

  it('resets only the assets table to its defaults', async () => {
    const ticketsSaved = JSON.stringify({
      v: 1, columns: ['subject-only'], known: ['title'], table: true,
    });
    localStorage.setItem(`${PREFIX}tickets`, ticketsSaved);
    render(<Assets />);
    await screen.findByText('LT-1');
    fireEvent.click(screen.getByRole('button', { name: 'Columns' }));
    fireEvent.click(screen.getByLabelText('Show Name column'));
    fireEvent.click(screen.getByRole('button', { name: 'Reset columns' }));
    expect(screen.getByLabelText('Show Tag column').checked).toBe(true);
    expect(screen.getByLabelText('Show Name column').checked).toBe(true);
    // Reset did not disturb the tickets preference.
    expect(localStorage.getItem(`${PREFIX}tickets`)).toBe(ticketsSaved);
  });
});
