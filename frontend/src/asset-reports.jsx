import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, ExportDialog, Link, PageHeader,
} from './components';

function Kpi({ label, value, sub }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub ? <div className="kpi-sub">{sub}</div> : null}
    </div>
  );
}

const DATE_RANGE_IDS = { from: 'ar-from', to: 'ar-to' };

function DateRange({ from, to, onFrom, onTo }) {
  return (
    <div className="date-range">
      <label className="small muted" htmlFor={DATE_RANGE_IDS.from}>From</label>
      <input
        id={DATE_RANGE_IDS.from}
        className="input"
        type="date"
        value={from}
        onChange={(e) => onFrom(e.target.value)}
      />
      <label className="small muted" htmlFor={DATE_RANGE_IDS.to}>To</label>
      <input
        id={DATE_RANGE_IDS.to}
        className="input"
        type="date"
        value={to}
        onChange={(e) => onTo(e.target.value)}
      />
    </div>
  );
}

function fmtDate(d) {
  if (!d) return '—';
  const dt = d instanceof Date ? d : new Date(d + 'T00:00:00');
  return dt.toLocaleDateString();
}
function fmtMoney(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function DistributionChart({ data, valueKey, labelKey, subKey, color }) {
  if (!data || data.length === 0) return null;
  const max = Math.max(...data.map((r) => Number(r[valueKey]) || 0), 1);
  return (
    <div className="distro">
      {data.map((row, i) => {
        const v = Number(row[valueKey]) || 0;
        const pct = Math.round((v / max) * 100);
        return (
          <div key={row.id ?? i} className="distro-row">
            <div className="distro-label">
              {labelKey ? row[labelKey] : row}
              {subKey && row[subKey] != null ? ` · ${row[subKey]}` : ''}
            </div>
            <div className="distro-bar">
              <div
                className="distro-fill"
                style={{ width: `${Math.max(pct, 2)}%`, background: color ?? 'var(--accent)' }}
              />
            </div>
            <div className="distro-value">{valueKey ? row[valueKey] : v}</div>
          </div>
        );
      })}
    </div>
  );
}

const REPORT_DEFS = [
  { key: 'financial', label: 'Financial' },
  { key: 'maintenance', label: 'Maintenance' },
  { key: 'warranty', label: 'Warranty' },
  { key: 'utilization', label: 'Utilization' },
  { key: 'inventory', label: 'Inventory' },
  { key: 'assets_by_department', label: 'Assets by dept.' },
  { key: 'assets_by_location', label: 'Asset locations' },
  { key: 'assets_with_incomplete_info', label: 'Incomplete info' },
  { key: 'warranty_by_department', label: 'Warranty by dept.' },
  { key: 'warranty_by_category', label: 'Warranty by cat.' },
  { key: 'warranty_by_vendor', label: 'Warranty vendors' },
  { key: 'purchase_cost_by_department', label: 'Cost by dept.' },
  { key: 'purchase_cost_trends', label: 'Cost trends' },
];

const REPORT_URLS = Object.fromEntries(
  REPORT_DEFS.map((r) => [r.key, `/assets/reports/?report=${r.key}`]),
);

function readReportFromHash() {
  try {
    const raw = String(window.location.hash || '').split('?')[1] || '';
    return new URLSearchParams(raw).get('report') || 'financial';
  } catch {
    return 'financial';
  }
}

function SectionHeading({ children }) {
  return <h2 style={{ marginTop: 'var(--sp-3)' }}>{children}</h2>;
}

export function AssetReportsPage() {
  const { isStaff } = useAuth();
  const [route, setRoute] = useState(readReportFromHash);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);

  // Report-specific filter state
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [resetFilters, setResetFilters] = useState(0);
  const [exportOpen, setExportOpen] = useState(false);

  useEffect(() => {
    const sync = () => setRoute(readReportFromHash());
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  useEffect(() => {
    if (!isStaff) return undefined;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const url = REPORT_URLS[route];
        if (!url) {
          if (!cancelled) {
            setError('Unknown report.');
            setData(null);
          }
          return;
        }
        const params = {};
        if (fromDate) params.from_date = fromDate;
        if (toDate) params.to_date = toDate;
        if (route === 'inventory') params.page_size = 100;

        const r = await api.get(url, { params });
        if (!cancelled) setData(r.data);
      } catch {
        if (!cancelled) {
          setError('Could not load report.');
          setData(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStaff, route, resetFilters, fromDate, toDate]);

  if (!isStaff) {
    return (
      <div className="form-wrap">
        <h1>Asset reports</h1>
        <div className="error-summary" role="alert">Only IT staff can view asset reports.</div>
        <p><a className="back-link" href="#/assets">← Back to assets</a></p>
      </div>
    );
  }

  const goTo = (key) => {
    setRoute(key);
    window.location.hash = `#/assets/reports?report=${key}`;
  };

  if (loading) {
    return (
      <div className="panel panel-pad">
        <p className="page-loading" role="status">
          <span className="spinner" aria-hidden="true" />Loading report…
        </p>
      </div>
    );
  }
  if (error && !data) {
    return (
      <div className="panel panel-pad">
        <div className="error-summary" role="alert">{error}</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <PageHeader
        title="Asset reports"
        sub="Financial, maintenance, warranty, utilization, inventory, and asset breakdown reports."
      />

      <div className="tab-row" role="tablist">
        {REPORT_DEFS.map((n) => (
          <button
            key={n.key}
            type="button"
            className={`tab${route === n.key ? ' active' : ''}`}
            role="tab"
            aria-selected={route === n.key}
            onClick={() => goTo(n.key)}
          >
            {n.label}
          </button>
        ))}
      </div>

      {fromDate || toDate ? (
        <div className="row-gap small muted" style={{ marginBottom: 'var(--sp-2)' }}>
          Showing: {fromDate || '—'} to {toDate || '—'}
          {' '}
          <button
            type="button"
            className="btn-ghost btn-small"
            onClick={() => { setFromDate(''); setToDate(''); setResetFilters((n) => n + 1); }}
          >
            Clear date filters
          </button>
        </div>
      ) : (
        <div style={{ marginBottom: 'var(--sp-2)' }} />
      )}

      {route === 'financial' && <FinancialOverview data={data} />}
      {route === 'maintenance' && <MaintenanceAnalytics data={data} />}
      {route === 'warranty' && (
        <WarrantyMonitoring
          data={data}
          fromDate={fromDate}
          toDate={toDate}
          setFromDate={setFromDate}
          setToDate={setToDate}
        />
      )}
      {route === 'utilization' && <Utilization data={data} />}
      {route === 'inventory' && (
        <InventoryReport
          data={data}
          fromDate={fromDate}
          toDate={toDate}
          exportOpen={exportOpen}
          setExportOpen={setExportOpen}
        />
      )}
      {route === 'assets_by_department' && <AssetsByDepartment data={data} />}
      {route === 'assets_by_location' && <AssetsByLocation data={data} />}
      {route === 'assets_with_incomplete_info' && <AssetsWithIncompleteInfo data={data} />}
      {route === 'warranty_by_department' && (
        <WarrantyBreakdown data={data} dimension="by_department" label="Department" heading="Warranty by department" />
      )}
      {route === 'warranty_by_category' && (
        <WarrantyBreakdown data={data} dimension="by_category" label="Category" heading="Warranty by category" />
      )}
      {route === 'warranty_by_vendor' && (
        <WarrantyBreakdown data={data} dimension="by_vendor" label="Vendor" heading="Warranty by vendor" />
      )}
      {route === 'purchase_cost_by_department' && <PurchaseCostByDepartment data={data} />}
      {route === 'purchase_cost_trends' && <PurchaseCostTrends data={data} />}
    </div>
  );
}

function FinancialOverview({ data }) {
  if (!data) return null;
  const byCategory = data.by_category || [];
  const byVendor = data.by_vendor || [];
  return (
    <div>
      <SectionHeading>Financial overview</SectionHeading>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="Total assets" value={data.total_assets} sub="All assets" />
        <Kpi label="Total purchase cost" value={fmtMoney(data.total_purchase_cost)} sub="Recorded acquisition cost" />
        <Kpi label="Assets without cost" value={data.assets_without_cost} sub="No purchase cost recorded" />
        <Kpi label="Total maintenance" value={fmtMoney(data.total_maintenance_cost)} sub="All maintenance records" />
        <Kpi
          label="Cost-to-value ratio"
          value={data.cost_to_value_ratio != null ? `${data.cost_to_value_ratio}%` : '—'}
          sub="Maintenance ÷ purchase cost"
        />
      </div>

      <div className="row-gap" style={{ marginTop: 'var(--sp-3)' }}>
        <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
          <h4 style={{ marginTop: 0 }}>Purchase cost by category</h4>
          {byCategory.length === 0 ? (
            <p className="muted">No assets with a recorded category.</p>
          ) : (
            <DataTable
              columns={[
                { key: 'category', label: 'Category' },
                { key: 'asset_count', label: 'Asset count' },
                { key: 'purchase_cost', label: 'Purchase cost', render: (r) => fmtMoney(r.purchase_cost) },
              ]}
              rows={byCategory}
              keyOf={(r) => r.category}
            />
          )}
        </div>
        <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
          <h4 style={{ marginTop: 0 }}>Purchase cost by vendor</h4>
          {byVendor.length === 0 ? (
            <p className="muted">No assets with a recorded vendor.</p>
          ) : (
            <DataTable
              columns={[
                { key: 'vendor', label: 'Vendor' },
                { key: 'asset_count', label: 'Asset count' },
                { key: 'purchase_cost', label: 'Purchase cost', render: (r) => fmtMoney(r.purchase_cost) },
              ]}
              rows={byVendor}
              keyOf={(r) => r.vendor}
            />
          )}
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginTop: 'var(--sp-3)' }}>
        <h4 style={{ marginTop: 0 }}>Note on asset valuation</h4>
        <p className="muted" style={{ marginBottom: 0 }}>
          The figures above show <strong>purchase cost</strong> only — the amount recorded when each asset was acquired.
          Current market value, depreciation, or book value are not tracked by this system and are therefore not shown.
          To add depreciation or valuation reporting, the asset model would need additional fields (e.g. depreciation method,
          useful life, residual value) and business rules to calculate them.
        </p>
      </div>
    </div>
  );
}

function MaintenanceAnalytics({ data }) {
  if (!data) return null;
  const byCategory = data.by_category || [];
  const byVendor = data.by_vendor || [];
  const topAssets = data.top_assets || [];
  return (
    <div>
      <SectionHeading>Maintenance analytics</SectionHeading>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="Total records" value={data.total_records} sub="All maintenance events" />
        <Kpi label="Total spend" value={fmtMoney(data.total_cost)} sub="Total maintenance cost" />
        <Kpi label="Completed spend" value={fmtMoney(data.completed_cost)} sub="Completed maintenance" />
        <Kpi label="Pending / in-progress" value={data.pending_count} sub="Open records" />
        <Kpi label="Overdue" value={data.overdue_count} sub="Overdue maintenance" />
        <Kpi
          label="Most recent"
          value={data.most_recent_maintenance ? fmtDate(data.most_recent_maintenance) : '—'}
          sub="Last maintenance date"
        />
      </div>

      {data.total_records === 0 ? (
        <EmptyState
          title="No maintenance records"
          hint="No maintenance events match the current filters. Adjust the date range or clear filters."
        />
      ) : (
        <>
          <div className="row-gap" style={{ marginTop: 'var(--sp-3)' }}>
            <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
              <h4 style={{ marginTop: 0 }}>By status</h4>
              <DistributionChart
                data={Object.entries(data.by_status || {}).map(([k, v]) => ({ id: k, status: k, count: v }))}
                valueKey="count"
                labelKey="status"
                color="var(--status-available)"
              />
            </div>
            <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
              <h4 style={{ marginTop: 0 }}>By type</h4>
              <DistributionChart
                data={Object.entries(data.by_type || {}).map(([k, v]) => ({ id: k, type: k, count: v }))}
                valueKey="count"
                labelKey="type"
                color="var(--accent)"
              />
            </div>
          </div>

          <div className="row-gap" style={{ marginTop: 'var(--sp-3)' }}>
            <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
              <h4 style={{ marginTop: 0 }}>Expenditure by category</h4>
              {byCategory.length === 0 ? (
                <p className="muted">No maintenance records with a category.</p>
              ) : (
                <DataTable
                  columns={[
                    { key: 'category', label: 'Category' },
                    { key: 'count', label: 'Records' },
                    { key: 'cost', label: 'Cost', render: (r) => fmtMoney(r.cost) },
                  ]}
                  rows={byCategory}
                  keyOf={(r) => r.category}
                />
              )}
            </div>
            <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
              <h4 style={{ marginTop: 0 }}>Expenditure by vendor</h4>
              {byVendor.length === 0 ? (
                <p className="muted">No maintenance records with a vendor.</p>
              ) : (
                <DataTable
                  columns={[
                    { key: 'vendor', label: 'Vendor' },
                    { key: 'count', label: 'Records' },
                    { key: 'cost', label: 'Cost', render: (r) => fmtMoney(r.cost) },
                  ]}
                  rows={byVendor}
                  keyOf={(r) => r.vendor}
                />
              )}
            </div>
          </div>

          <div className="panel panel-pad" style={{ marginTop: 'var(--sp-3)' }}>
            <h4 style={{ marginTop: 0 }}>Frequently maintained assets</h4>
            {topAssets.length === 0 ? (
              <p className="muted">No assets with maintenance records.</p>
            ) : (
              <DataTable
                columns={[
                  { key: 'asset_tag', label: 'Asset' },
                  { key: 'name', label: 'Name' },
                  { key: 'count', label: 'Records' },
                  { key: 'cost', label: 'Cost', render: (r) => fmtMoney(r.cost) },
                  {
                    key: 'actions',
                    label: 'Actions',
                    render: (r) => (r.asset_id
                      ? <Link href={`#/assets/${r.asset_id}`} className="btn-ghost btn-small">View</Link>
                      : ''),
                  },
                ]}
                rows={topAssets}
                keyOf={(r) => r.asset_tag}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}

function WarrantyMonitoring({ data, fromDate, toDate, setFromDate, setToDate }) {
  if (!data) return null;
  const soon = (days) => {
    const v = data.expiring_soon;
    return v && typeof v === 'object' ? (v[days] ?? 0) : 0;
  };
  const expiringList = data.expiring_list || [];
  return (
    <div>
      <SectionHeading>Warranty monitoring</SectionHeading>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="Expired" value={data.expired_count ?? 0} sub="Warranty past expiry" />
        <Kpi label="Expiring within 30 days" value={soon(30)} sub="Due soon" />
        <Kpi label="Expiring within 90 days" value={soon(90)} sub="Due in 3 months" />
        <Kpi label="Expiring within 180 days" value={soon(180)} sub="Due in 6 months" />
        <Kpi label="Without warranty" value={data.without_warranty ?? 0} sub="No expiry recorded" />
        <Kpi
          label="Total with warranty"
          value={data.total_with_warranty ?? 0}
          sub="Assets with warranty_expiry"
        />
      </div>

      {data.expired_count > 0 || soon(30) > 0 || soon(90) > 0 || soon(180) > 0 ? (
        <div className="panel panel-pad" style={{ marginTop: 'var(--sp-3)' }}>
          <h4 style={{ marginTop: 0 }}>Warranty status list</h4>
          {(() => {
            const items = [];
            if (data.expired_count > 0) {
              items.push(
                <div key="expired-header" className="distro-section-title">
                  <Badge kind="status" value="overdue" label={`${data.expired_count} expired`} />
                </div>
              );
            }
            [30, 90, 180].forEach((days) => {
              const n = soon(days);
              if (n > 0) {
                items.push(
                  <div key={`soon-${days}`} className="distro-section-title">
                    <Badge kind="status" value="warning" label={`${n} expiring in ${days} days`} />
                  </div>
                );
              }
            });
            return items;
          })()}
        </div>
      ) : null}

      <div className="row-gap" style={{ marginTop: 'var(--sp-3)' }}>
        <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
          <h4 style={{ marginTop: 0 }}>Expiring soon (next 90 days)</h4>
          {expiringList.length > 0 ? (
            <DataTable
              columns={[
                { key: 'asset_tag', label: 'Asset' },
                { key: 'name', label: 'Name' },
                { key: 'category', label: 'Category' },
                { key: 'vendor', label: 'Vendor' },
                { key: 'expiry', label: 'Expiry', render: (r) => fmtDate(r.expiry) },
                { key: 'days_left', label: 'Days left' },
                {
                  key: 'actions',
                  label: 'Actions',
                  render: (r) => (r.asset_tag
                    ? <Link href={`#/assets/${r.asset_tag}`} className="btn-ghost btn-small">View</Link>
                    : ''),
                },
              ]}
              rows={expiringList}
              keyOf={(r) => r.asset_tag}
            />
          ) : (
            <p className="muted">No warranties expiring in the next 90 days.</p>
          )}
        </div>
        <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
          <h4 style={{ marginTop: 0 }}>Assets without warranty</h4>
          <p className="muted">
            {data.without_warranty ?? 0} asset{(data.without_warranty ?? 0) !== 1 ? 's' : ''} have no warranty_expiry recorded.
            Use the inventory report to find and update them.
          </p>
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginTop: 'var(--sp-3)' }}>
        <h4 style={{ marginTop: 0 }}>Filter by expiry date</h4>
        <DateRange
          from={fromDate}
          to={toDate}
          onFrom={setFromDate}
          onTo={setToDate}
        />
      </div>
    </div>
  );
}

function Utilization({ data }) {
  if (!data) return null;
  const sc = data.status_counts || {};
  const distribution = Array.isArray(data.assignment_distribution) ? data.assignment_distribution : [];
  return (
    <div>
      <SectionHeading>Asset utilization</SectionHeading>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="Total assets" value={data.total_assets} sub="All non-deleted assets" />
        <Kpi label="Available" value={sc.available ?? data.available_count ?? 0} sub="Ready to assign" />
        <Kpi label="Assigned" value={sc.assigned ?? data.assigned_count ?? 0} sub="Currently assigned" />
        <Kpi label="In maintenance" value={sc.in_repair ?? data.maintenance_count ?? 0} sub="Under maintenance" />
        <Kpi label="Retired" value={sc.retired ?? data.retired_count ?? 0} sub="Retired" />
        <Kpi label="Lost" value={sc.lost ?? data.lost_count ?? 0} sub="Marked lost" />
        <Kpi label="Disposed" value={sc.disposed ?? data.disposed_count ?? 0} sub="Disposed" />
      </div>

      <div className="row-gap" style={{ marginTop: 'var(--sp-3)' }}>
        <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
          <h4 style={{ marginTop: 0 }}>Assets by status</h4>
          <DistributionChart
            data={Object.entries(sc).map(([k, v]) => ({ id: k, status: k, count: v }))}
            valueKey="count"
            labelKey="status"
            color="var(--status-available)"
          />
        </div>
        <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
          <h4 style={{ marginTop: 0 }}>Assignment distribution (top holders)</h4>
          {distribution.length > 0 ? (
            <DataTable
              columns={[
                { key: 'employee_name', label: 'Employee', render: (r) => r.employee_name || r.email },
                { key: 'employee_id', label: 'Employee ID' },
                { key: 'department', label: 'Department' },
                { key: 'asset_count', label: 'Assets held' },
              ]}
              rows={distribution}
              keyOf={(r) => r.employee_id || r.email}
            />
          ) : (
            <p className="muted">No assigned assets to display.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function InventoryReport({ data, fromDate, toDate, exportOpen, setExportOpen }) {
  if (!data) return null;
  const items = data.items || [];
  return (
    <div>
      <SectionHeading>Asset inventory</SectionHeading>
      <div className="row-gap" style={{ marginTop: 'var(--sp-3)', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <h4 style={{ marginTop: 0 }}>Inventory results</h4>
          <p className="muted small">{data.count ?? items.length} asset{(data.count ?? items.length) !== 1 ? 's' : ''} in result set</p>
        </div>
        <button type="button" className="btn-secondary" onClick={() => setExportOpen(true)}>
          Export…
        </button>
      </div>
      {exportOpen && (
        <ExportDialog
          dataset="assets"
          open={exportOpen}
          filterParams={{ from_date: fromDate, to_date: toDate }}
          onClose={() => setExportOpen(false)}
        />
      )}

      {items.length > 0 ? (
        <DataTable
          columns={[
            { key: 'asset_tag', label: 'Asset tag' },
            { key: 'name', label: 'Name' },
            { key: 'category', label: 'Category' },
            { key: 'status', label: 'Status' },
            { key: 'assigned_to', label: 'Assigned to', render: (r) => r.assigned_to || '—' },
            { key: 'purchase_cost', label: 'Purchase cost', render: (r) => (r.purchase_cost != null ? fmtMoney(r.purchase_cost) : '—') },
            { key: 'warranty_expiry', label: 'Warranty expiry', render: (r) => (r.warranty_expiry ? fmtDate(r.warranty_expiry) : '—') },
            {
              key: 'actions',
              label: 'Actions',
              render: (r) => (r.id
                ? <Link href={`#/assets/${r.id}`} className="btn-ghost btn-small">View</Link>
                : ''),
            },
          ]}
          rows={items}
          keyOf={(r) => r.id || r.asset_tag}
        />
      ) : (
        <EmptyState
          title="No assets match the current filters"
          hint="Try widening the date range or clearing filters."
        />
      )}
    </div>
  );
}

function AssetsByDepartment({ data }) {
  if (!data) return null;
  const rows = data.by_department || [];
  return (
    <div>
      <SectionHeading>Assets by department</SectionHeading>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="Departments" value={data.total ?? rows.length} sub="Groups with assets" />
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No department data" hint="No assets are grouped by department yet." />
      ) : (
        <DataTable
          columns={[
            { key: 'department', label: 'Department' },
            { key: 'asset_count', label: 'Assets' },
          ]}
          rows={rows}
          keyOf={(r) => r.department}
        />
      )}
    </div>
  );
}

function AssetsByLocation({ data }) {
  if (!data) return null;
  const rows = data.by_location || [];
  return (
    <div>
      <SectionHeading>Assets by location</SectionHeading>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="Locations" value={data.total ?? rows.length} sub="Groups with assets" />
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No location data" hint="No assets are grouped by location yet." />
      ) : (
        <DataTable
          columns={[
            { key: 'location', label: 'Location' },
            { key: 'asset_count', label: 'Assets' },
          ]}
          rows={rows}
          keyOf={(r) => r.location}
        />
      )}
    </div>
  );
}

function AssetsWithIncompleteInfo({ data }) {
  if (!data) return null;
  return (
    <div>
      <SectionHeading>Assets with incomplete info</SectionHeading>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="Assets with missing data" value={data.total ?? 0} sub="At least one field missing" />
        <Kpi label="Missing department" value={data.missing_department ?? 0} sub="No department set" />
        <Kpi label="Missing vendor" value={data.missing_vendor ?? 0} sub="No vendor set" />
        <Kpi label="Missing serial" value={data.missing_serial ?? 0} sub="No serial number" />
        <Kpi label="Missing purchase cost" value={data.missing_purchase_cost ?? 0} sub="No cost recorded" />
      </div>
      <div className="panel panel-pad" style={{ marginTop: 'var(--sp-3)' }}>
        <p className="muted" style={{ marginBottom: 0 }}>
          Use the asset inventory report to find and update records with missing information.
        </p>
      </div>
    </div>
  );
}

function WarrantyBreakdown({ data, dimension, label, heading }) {
  if (!data) return null;
  const rows = data[dimension] || [];
  const key = dimension === 'by_department' ? 'department' : dimension === 'by_category' ? 'category' : 'vendor';
  return (
    <div>
      <SectionHeading>{heading}</SectionHeading>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="With warranty" value={data.total_with_warranty ?? 0} sub="Assets with an expiry date" />
        <Kpi label="Without warranty" value={data.total_without_warranty ?? 0} sub="Assets with no expiry date" />
      </div>
      {rows.length === 0 ? (
        <EmptyState
          title="No warranty data available"
          hint="No warranty records match the current filters."
        />
      ) : (
        <DataTable
          columns={[
            { key, label },
            { key: 'total', label: 'Assets' },
            { key: 'expired', label: 'Expired' },
            { key: 'expiring_30', label: '≤ 30 days' },
            { key: 'expiring_90', label: '≤ 90 days' },
            { key: 'expiring_180', label: '≤ 180 days' },
            { key: 'without', label: 'No warranty' },
          ]}
          rows={rows}
          keyOf={(r) => r[key]}
        />
      )}
    </div>
  );
}

function PurchaseCostByDepartment({ data }) {
  if (!data) return null;
  const rows = data.by_department || [];
  return (
    <div>
      <SectionHeading>Purchase cost by department</SectionHeading>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="Total purchase cost" value={fmtMoney(data.total)} sub="All departments" />
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No purchase cost data" hint="No assets are grouped by department yet." />
      ) : (
        <DataTable
          columns={[
            { key: 'department', label: 'Department' },
            { key: 'asset_count', label: 'Assets' },
            { key: 'purchase_cost', label: 'Purchase cost', render: (r) => fmtMoney(r.purchase_cost) },
          ]}
          rows={rows}
          keyOf={(r) => r.department}
        />
      )}
    </div>
  );
}

function PurchaseCostTrends({ data }) {
  if (!data) return null;
  const rows = data.by_month || [];
  return (
    <div>
      <SectionHeading>Purchase cost trends</SectionHeading>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="Assets with purchase date" value={data.total_assets ?? 0} sub="Across all months" />
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No purchase cost trends" hint="No assets have a purchase date recorded." />
      ) : (
        <DataTable
          columns={[
            {
              key: 'period',
              label: 'Month',
              render: (r) => `${String(r.month).padStart(2, '0')}/${r.year}`,
            },
            { key: 'purchase_cost', label: 'Purchase cost', render: (r) => fmtMoney(r.purchase_cost) },
            { key: 'asset_count', label: 'Assets' },
          ]}
          rows={rows}
          keyOf={(r) => `${r.year}-${r.month}`}
        />
      )}
    </div>
  );
}
