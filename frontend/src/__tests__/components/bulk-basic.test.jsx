import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

const { mockGet, mockPost, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('../../api', () => ({ default: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) } }));
vi.mock('../../auth', () => ({ useAuth: () => mockAuth() }));

import { TicketBulkCreateModal, AssetBulkCreateModal } from '../../pages/bulk/Bulk';

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockAuth.mockReturnValue({ isStaff: true, user: { role: 'it_support' } });
});

describe('bulk modals smoke', () => {
  it('renders ticket bulk modal', () => {
    render(<TicketBulkCreateModal onClose={() => {}} onCreated={() => {}} />);
    expect(screen.getByText('Bulk create tickets')).toBeTruthy();
  });
  it('renders asset bulk modal', () => {
    render(<AssetBulkCreateModal onClose={() => {}} onImported={() => {}} />);
    expect(screen.getByText('Bulk create assets')).toBeTruthy();
  });
});
