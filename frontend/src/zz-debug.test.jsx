import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
const { mockAuth } = vi.hoisted(() => ({ mockAuth: vi.fn() }));
vi.mock('./api', () => ({ default: { get: vi.fn(async () => ({ data: { results: [] } })), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
vi.mock('./auth', () => ({ useAuth: (...a) => mockAuth(...a), AuthProvider: ({ children }) => children }));
vi.mock('./pages', () => ({
  Tickets: () => <div id="stub-tickets">STUB TICKETS</div>,
  Assets: () => <div>STUB ASSETS</div>,
  Categories: () => <div>STUB CATS</div>,
  Departments: () => <div>STUB DEPTS</div>,
  Notifications: () => <div>STUB NOTIFS</div>,
  RecycleBin: () => <div>STUB RECYCLE</div>,
  Users: () => <div>STUB USERS</div>,
  Profile: () => <div>STUB PROFILE</div>,
  Login: () => <div>STUB LOGIN</div>,
  ResetPassword: () => <div>STUB RESET</div>,
  VerifyEmail: () => <div>STUB VERIFY</div>,
}));
import App from './App';
describe('debug6', () => {
  it('renders with stubbed pages', async () => {
    mockAuth.mockReturnValue({ access: 'token', user: { email: 'a', role: 'system_admin', employee_id: 'E1' }, profileLoading: false, isStaff: true, isAdmin: true, canCreateTickets: true, login: vi.fn(), logout: vi.fn(), refreshProfile: vi.fn() });
    window.location.hash = '#/tickets';
    const r = render(<App />);
    await new Promise((res) => setTimeout(res, 100));
    process.stdout.write('MAIN=' + (document.querySelector('main')?.innerHTML.slice(0, 200)) + '\n');
    expect(true).toBe(true);
  });
});
