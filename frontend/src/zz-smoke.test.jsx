import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

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
  AuthProvider: ({ children }) => children,
}));

import App from './App';

const TICKET = {
  id: 12, title: 'Laptop will not boot', description: 'Black screen on power-on',
  category: 1, category_name: 'Hardware', priority: 'high', status: 'open',
  requester: 3, requester_email: 'a@x.io', assignee: 4, assignee_email: 'b@x.io',
  department: 2, department_name: 'Engineering', on_behalf_reason: '', asset: 7,
  resolution_notes: '', created_at: '2026-01-02T10:00:00Z', updated_at: '2026-01-03T10:00:00Z',
};
const ASSET = {
  id: 7, asset_tag: 'LT-0007', name: 'ThinkPad T14', description: 'Fleet laptop',
  category: 1, category_name: 'Laptop', serial_number: 'SN-1', status: 'assigned',
  assigned_to: 4, assigned_to_email: 'b@x.io', location: 'HQ Lab',
  purchase_date: '2025-05-01', warranty_expiry: '2028-05-01', purchase_cost: '1500.00',
};

function paginated(results, count = results.length) {
  return { data: { results, count, next: null, previous: null } };
}

function setupApi() {
  mockGet.mockImplementation(async (url) => {
    const u = String(url);
    if (u.startsWith('/accounts/me/')) return { data: { id: 1, email: 'admin@local', employee_id: 'E1', role: 'system_admin', is_active: true, email_verified: true, can_create_tickets: true, home_department: 2 } };
    if (u.startsWith('/tickets/categories/') || u.startsWith('/assets/categories/')) return paginated([{ id: 1, name: 'Hardware', is_active: true }]);
    if (u.startsWith('/accounts/departments/')) return paginated([{ id: 2, name: 'Engineering', code: 'ENG', is_active: true, member_count: 3, head_email: 'm@x.io' }]);
    if (u.startsWith('/accounts/users/')) return paginated([{ id: 1, employee_id: 'E1', email: 'admin@local', role: 'system_admin', is_active: true, home_department_name: 'Engineering', can_create_tickets: true }]);
    if (u.startsWith('/tickets/attachments/')) return paginated([{ id: 5, ticket: 12, original_filename: 'spec.pdf', created_at: '2026-01-02T11:00:00Z' }]);
    if (u.startsWith('/assets/attachments/')) return paginated([{ id: 6, asset: 7, original_filename: 'invoice.pdf', created_at: '2026-01-02T11:00:00Z' }]);
    if (u.startsWith('/tickets/histories/')) return paginated([{ id: 9, actor_email: 'a@x.io', action: 'status_change', timestamp: '2026-01-02T12:00:00Z', note: 'triaged' }]);
    if (u.startsWith('/assets/histories/')) return paginated([{ id: 9, actor_email: 'a@x.io', action: 'assignment', timestamp: '2026-01-02T12:00:00Z', note: '' }]);
    if (u.startsWith('/assets/assignments/')) return paginated([{ id: 3, assigned_to: 4, assigned_by: 1, assigned_at: '2026-01-02T12:00:00Z', returned_at: null, note: 'onboarding' }]);
    if (u.startsWith('/tickets/reports/')) return { data: { results: [{ id: 1, name: 'Hardware', total: 4, open_count: 2, closed_count: 2, high_count: 1, critical_count: 0 }] } };
    if (u.startsWith('/common/notifications/')) return paginated([{ id: 8, title: 'Ticket assigned', body: 'You own #12', is_read: false, created_at: '2026-01-02T12:00:00Z', entity_type: 'tickets.Ticket', object_id: 12 }]);
    if (u.startsWith('/common/audit-logs/')) return paginated([{ id: 4, timestamp: '2026-01-02T12:00:00Z', actor_email: 'a@x.io', action: 'update', entity_type: 'tickets.Ticket', object_id: 12, object_repr: 'Ticket #12' }]);
    if (u.startsWith('/recycle-bin/')) return { data: [{ entity_type: 'tickets.Ticket', object_id: '12', repr: 'Ticket #12', deleted_by: 'a@x.io' }] };
    if (u === '/tickets/12/') return { data: TICKET };
    if (u === '/tickets/12/notes/') return { data: [{ id: 2, author_email: 'a@x.io', body: 'looking', is_internal: false, created_at: '2026-01-02T13:00:00Z' }] };
    if (u === '/assets/7/') return { data: ASSET };
    if (u.startsWith('/tickets/')) return paginated([TICKET]);
    if (u.startsWith('/assets/')) return paginated([ASSET]);
    return paginated([]);
  });
  mockPost.mockResolvedValue({ data: { id: 1, detail: 'ok' } });
  mockPatch.mockResolvedValue({ data: {} });
  mockDelete.mockResolvedValue({ data: {} });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  setupApi();
  mockAuth.mockReturnValue({
    access: 'token', user: { id: 1, email: 'admin@local', employee_id: 'E1', role: 'system_admin', is_active: true, email_verified: true, can_create_tickets: true, home_department: 2 },
    profileLoading: false, isStaff: true, isAdmin: true, canCreateTickets: true,
    login: vi.fn(), logout: vi.fn(), refreshProfile: vi.fn(),
  });
});

afterEach(() => cleanup());

const ROUTES = [
  '#/tickets', '#/tickets/new', '#/tickets/12', '#/tickets/12/edit',
  '#/assets', '#/assets/new', '#/assets/7', '#/assets/7/edit',
  '#/categories', '#/departments', '#/notifications', '#/users', '#/profile',
  '#/recycle', '#/audit',
];

describe('route smoke', () => {
  for (const route of ROUTES) {
    it(`renders ${route} without console errors`, async () => {
      const errors = [];
      const orig = console.error;
      console.error = (...args) => { errors.push(args.join(' ')); };
      try {
        window.location.hash = route;
        render(<App />);
        await waitFor(() => expect(document.querySelector('.page-loading, h1, .login-card')).toBeTruthy());
        await new Promise((r) => setTimeout(r, 300));
      } finally {
        console.error = orig;
      }
      const outline = [...document.querySelectorAll('h1,h2,h3,h4')].map((h) => `${h.tagName}:${h.textContent.trim().slice(0, 40)}`);
      const inlined = [...document.querySelectorAll('[style]')].map((n) => `${n.tagName}.${n.className}{${n.getAttribute('style')}}`);
      expect(errors, `${route} -> ${errors.join('\n')}`).toEqual([]);
      if (process.env.SMOKE_OUTLINE) {
        orig(`\n${route}\n  ${outline.join('\n  ')}`);
        if (inlined.length) orig(`  INLINE: ${[...new Set(inlined)].join(' | ')}`);
      }
    });
  }
});
