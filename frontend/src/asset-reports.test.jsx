import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { HashRouter } from 'react-router-dom';

// Mock global objects for jsdom environment
vi.stubGlobal('localStorage', {
  _storage: {},
  getItem: function(key) { return this._storage[key] || null; },
  setItem: function(key, value) { this._storage[key] = value; },
  removeItem: function(key) { delete this._storage[key]; },
  clear: function() { this._storage = {}; }
});

const { mockGet, mockAuth } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('./api', () => ({
  default: { get: (...args) => mockGet(...args), request: vi.fn() },
}));

vi.mock('./auth', () => ({ useAuth: () => mockAuth() }));

import { AssetReportsPage } from './asset-reports';

const staff = () => {
  mockAuth.mockReturnValue({ isStaff: true, isAdmin: true, user: { id: 1, employee_id: 'E1', role: 'it_manager', email: 'admin@x' } });
};

const financialData = {
  total_assets: 120,
  total_purchase_cost: 250000,
  assets_without_cost: 3,
  total_maintenance_cost: 20000,
  cost_to_value_ratio: 0.08,
  by_category: [{ category: 'Laptop', asset_count: 45, purchase_cost: 180000 }],
  by_vendor: [{ vendor: 'Dell', asset_count: 30, purchase_cost: 120000 }],
};
const warrantyData = {
  expired_count: 10,
  expiring_soon: 5,
  without_warranty: 20,
  total_with_warranty: 60,
  expiring_list: [{ asset_tag: 'LT-1', warranty_expiry: '2026-12-01' }],
  most_recent_warranty_expiry: '2026-06-15',
  by_category: [],
};

const utilizationData = {
  status_counts: { available: 40, assigned: 50, in_repair: 5, retired: 10, lost: 3, disposed: 12 },
  total_assets: 120,
  assigned_count: 50,
  available_count: 40,
  maintenance_count: 5,
  retired_count: 10,
  disposed_count: 12,
  lost_count: 3,
  assignment_distribution: { available: 40, assigned: 50 },
  by_category: [],
};

const inventoryData = { items: [], count: 0, page: 1, page_size: 100, has_next: false, has_prev: false, by_category: [] };

const byDeptData = { total: 120, by_department: [{ department: 'No department', asset_count: 7 }, { department: 'Engineering', asset_count: 30 }], by_category: [] };
const byLocData = { total: 120, by_location: [{ location: 'Unassigned', asset_count: 7 }, { location: 'HQ', asset_count: 40 }], by_category: [] };
const incompleteData = {
  total: 120,
  missing_department: 7,
  missing_vendor: 6,
  missing_serial: 7,
  missing_purchase_cost: 3,
  by_category: [],
};
const warrantyByDeptData = { by_department: [], total_with_warranty: 60, total_without_warranty: 20, by_category: [] };
const warrantyByCatData = { by_category: [{ category: 'Laptop', total: 45, expired: 2, expiring_30: 3, expiring_90: 10, expiring_180: 20, without: 10 }], total_with_warranty: 60, total_without_warranty: 20 };
const warrantyByVendorData = { by_vendor: [], total_with_warranty: 60, total_without_warranty: 20, by_category: [] };
const purchaseCostData = {
  by_department: [{ department: 'No department', asset_count: 7, purchase_cost: 4000 }, { department: 'Engineering', asset_count: 30, purchase_cost: 50000 }],
  total: 54000,
  by_category: [],
};
const purchaseCostTrendsData = { total_assets: 120, by_month: [{ month: 1, year: 2026, purchase_cost: 5000, asset_count: 20 }, { month: 2, year: 2026, purchase_cost: 6000, asset_count: 25 }], by_category: [] };

function mockRoutes(report, data) {
  window.location.hash = `#/assets/reports?report=${report}`;
  mockGet.mockResolvedValueOnce({ data });
}
describe('AssetReportsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem('access', 'test-token');
    window.location.hash = '#/assets/reports';
  });
  afterEach(() => {
    cleanup();
    localStorage.removeItem('access');
    window.location.hash = '#/';
  });

  it('renders financial report', async () => {
    staff();
    mockRoutes('financial', financialData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Total assets/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=financial', { params: {} });
    expect(screen.getByText('120')).toBeTruthy();
  });

  it('renders warranty report', async () => {
    staff();
    mockRoutes('warranty', warrantyData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Warranty monitoring/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=warranty', { params: {} });
  });

  it('renders utilization report', async () => {
    staff();
    mockRoutes('utilization', utilizationData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Asset utilization/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=utilization', { params: {} });
  });

  it('renders inventory report', async () => {
    staff();
    mockRoutes('inventory', inventoryData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Asset inventory/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=inventory', { params: { page_size: 100 } });
  });

  it('renders assets by department', async () => {
    staff();
    mockRoutes('assets_by_department', byDeptData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Assets by department/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=assets_by_department', { params: {} });
    expect(screen.getByText(/120/)).toBeTruthy();
  });

  it('renders assets by location', async () => {
    staff();
    mockRoutes('assets_by_location', byLocData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Assets by location/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=assets_by_location', { params: {} });
  });

  it('renders assets with incomplete info', async () => {
    staff();
    mockRoutes('assets_with_incomplete_info', incompleteData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Assets with incomplete info/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=assets_with_incomplete_info', { params: {} });
  });

  it('renders warranty by department', async () => {
    staff();
    mockRoutes('warranty_by_department', warrantyByDeptData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Warranty by department/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=warranty_by_department', { params: {} });
  });

  it('renders warranty by category', async () => {
    staff();
    mockRoutes('warranty_by_category', warrantyByCatData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Warranty by category/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=warranty_by_category', { params: {} });
  });

  it('renders warranty by vendor', async () => {
    staff();
    mockRoutes('warranty_by_vendor', warrantyByVendorData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Warranty by vendor/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=warranty_by_vendor', { params: {} });
  });

  it('renders purchase cost by department', async () => {
    staff();
    mockRoutes('purchase_cost_by_department', purchaseCostData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Purchase cost by department/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=purchase_cost_by_department', { params: {} });
    expect(screen.getByText(/54,000/)).toBeTruthy();
  });

  it('renders purchase cost trends', async () => {
    staff();
    mockRoutes('purchase_cost_trends', purchaseCostTrendsData);
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Purchase cost trends/i);
    expect(mockGet).toHaveBeenCalledWith('/assets/reports/?report=purchase_cost_trends', { params: {} });
    expect(screen.getByText(/120/)).toBeTruthy();
  });

  it('shows error state on API failure', async () => {
    staff();
    mockGet.mockRejectedValue(new Error('Network Error'));
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Could not load report/i);
    expect(screen.getByText(/Could not load report/i)).toBeTruthy();
  });

  it('shows empty state when report returns no data', async () => {
    staff();
    mockRoutes('warranty_by_department', { by_department: [], total_with_warranty: 0, total_without_warranty: 0 });
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Warranty by department/i);
    expect(screen.getByText(/No warranty data available/i)).toBeTruthy();
  });

  it('handles unknown report route', async () => {
    staff();
    window.location.hash = '#/assets/reports?report=does_not_exist';
    mockGet.mockResolvedValueOnce({ data: { error: 'bad' } });
    render(<HashRouter><AssetReportsPage /></HashRouter>);
    await screen.findByText(/Unknown report/i);
    expect(screen.getByText(/Unknown report/i)).toBeTruthy();
  });
});