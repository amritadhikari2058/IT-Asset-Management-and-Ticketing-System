import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
vi.mock('../../auth', () => ({ useAuth: () => ({ access: 't', isStaff: true, isAdmin: true, canUseMonitoring: true, canUseProblemManagement: true, canViewProcurement: true, canViewProcurementReports: true, canManageScheduledReports: true, canViewVendors: true }), AuthProvider: ({children}) => children }));
import App from '../../App';
beforeEach(() => { window.location.hash = '#/tickets'; });
describe('sidebar initial', () => {
  it('sections collapsed', () => {
    render(<App />);
    const content = document.getElementById('sidenav-section-content-0');
    console.log('CLASS:', content?.className);
    expect(content?.classList.contains('collapsed')).toBe(true);
  });
});
