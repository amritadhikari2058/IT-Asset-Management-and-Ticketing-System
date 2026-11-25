import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Evidence } from '../../components/problem-management/evidence';
import { archiveEvidence, listEvidence } from '../../services/problem-management';

vi.mock('../../services/problem-management', () => ({
  archiveEvidence: vi.fn(),
  listEvidence: vi.fn(),
  uploadEvidence: vi.fn(),
}));

const auth = vi.hoisted(() => ({ current: { isStaff: true } }));
vi.mock('../../auth', () => ({ useAuth: () => auth.current }));

afterEach(cleanup);

const ACTIVE = {
  id: 11,
  original_filename: 'note_kBtjLl0.txt',
  file_type: 'text/plain',
  file_size: 2048,
  uploaded_at: '2026-01-01T09:00:00Z',
  archived: false,
};

const ARCHIVED = {
  id: 12,
  original_filename: 'old_2Xk9.txt',
  archived: true,
};

const renderEvidence = () => render(
  <MemoryRouter>
    <Evidence problemId="1" />
  </MemoryRouter>,
);

describe('Evidence archive contract', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.current = { isStaff: true };
    listEvidence.mockResolvedValue({ results: [ACTIVE, ARCHIVED] });
  });

  test('archives through the supported endpoint without a version token', async () => {
    renderEvidence();
    fireEvent.click(await screen.findByText('Archive'));
    await waitFor(() => expect(archiveEvidence).toHaveBeenCalledWith(11));
  });

  test('renders an archived item as archived and offers no unarchive action', async () => {
    renderEvidence();
    expect(await screen.findByText('old_2Xk9.txt')).toBeTruthy();
    expect(screen.getAllByText('Archived').length).toBeGreaterThan(0);
    expect(screen.queryByText(/unarchive/i)).toBeNull();
    expect(screen.queryAllByRole('button', { name: /unarchive/i })).toHaveLength(0);
  });

  test('never renders a private storage path and labels the stored basename', async () => {
    renderEvidence();
    expect(await screen.findByText('Stored filename')).toBeTruthy();
    renderEvidence();
    await screen.findByText('old_2Xk9.txt');
    expect(screen.queryByText(/private\//)).toBeNull();
    expect(screen.queryByText(/secret-path/)).toBeNull();
  });

  test('renders an archive permission denial safely', async () => {
    archiveEvidence.mockRejectedValueOnce({ response: { status: 403 } });
    renderEvidence();
    fireEvent.click(await screen.findByText('Archive'));
    expect(await screen.findByText('You do not have permission to archive evidence.')).toBeTruthy();
  });
});


