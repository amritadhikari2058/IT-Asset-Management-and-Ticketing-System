import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, ExportDialog, Link, LoadingRows, PageHeader,
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

const STATUS_LABELS = {
  available: 'Available',
  assigned: 'Assigned',
  in_repair: 'In maintenance',
  retired: 'Retired',
  lost: 'Lost',
  disposed: 'Disposed',
};

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
      {data.map((row) => {
        const v = Number(row[valueKey]) || 0;
        const pct = Math.round((v / max) * 100);
        return (
          <div key={row.id ?? row[valueKey] ?? Math.random()} className="distro-row">
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

export function AssetReportsPage() {
  const { isStaff } = useAuth();
  if (!isStaff) {
    return (
      <div className="form-wrap">
        <h1>Asset reports</h1>
        <div className="error-summary" role="alert">Only IT staff can view asset reports.</div>
        <p><a className="back-link" href="#/assets">← Back to assets</a></p>
      </div>
    );
  }

  const [route, setRoute] = useState('financial');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);

  // Report-specific filter state
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [resetFilters, setResetFilters] = useState(0);
  const [exportOpen, setExportOpen] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError('');
      try {
        const params = {};
        if (fromDate) params.from_date = fromDate;
        if (toDate) params.to_date = toDate;

        let url;
        if (route === 'financial') {
          url = '/assets/reports/financial/';
        } else if (route === 'maintenance') {
          url = '/assets/reports/maintenance/';
        } else if (route === 'warranty') {
          url = '/assets/reports/warranty/';
        } else if (route === 'utilization') {
          url = '/assets/reports/utilization/';
        } else if (route === 'inventory') {
          url = '/assets/reports/inventory/';
          params.page_size = 100;
        } else {
          setError('Unknown report.');
          setLoading(false);
          return;
        }

        const r = await api.get(url, { params });
        setData(r.data);
      } catch (e) {
        setError('Could not load report.');
      } finally {
        setLoading(false);
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route, resetFilters, fromDate, toDate]);

  const navItems = [
    { key: 'financial', label: 'Financial overview' },
    { key: 'maintenance', label: 'Maintenance analytics' },
    { key: 'warranty', label: 'Warranty monitoring' },
    { key: 'utilization', label: 'Utilization' },
    { key: 'inventory', label: 'Inventory report' },
  ];

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
        sub="Financial, maintenance, warranty, and utilization insights for IT assets."
      />

      <div className="tab-row" role="tablist">
        {navItems.map((n) => (
          <button
            key={n.key}
            type="button"
            className={`tab${route === n.key ? ' active' : ''}`}
            role="tab"
            aria-selected={route === n.key}
            onClick={() => setRoute(n.key)}
          >
            {n.label}
          </button>
        ))}
      </div>

      {fromDate || toDate ? (
        <div className="row-gap small muted" style={{ marginBottom: 'var(--sp-2)' }}>
          Showing: {fromDate || '—'} to {toDate || '—'}
          {' '}
          <button type="button" className="btn-ghost btn-small" onClick={() => setResetFilters((n) => n + 1)}>
            Clear date filters
          </button>
        </div>
      ) : (
        <div style={{ marginBottom: 'var(--sp-2)' }} />
      )}

      {route === 'financial' && <FinancialOverview data={data} />}
      {route === 'maintenance' && <MaintenanceAnalytics data={data} />}
      {route === 'warranty' && <WarrantyMonitoring data={data} fromDate={fromDate} toDate={toDate} setFromDate={setFromDate} setToDate={setToDate} />}
      {route === 'utilization' && <Utilization data={data} />}
      {route === 'inventory' && <InventoryReport data={data} />}
    </div>
  );
}

function FinancialOverview({ data }) {
  if (!data) return null;
  return (
    <div>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="Total purchase cost" value={fmtMoney(data.total_purchase_cost)} sub={`${data.total_assets} assets`} />
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
          {data.by_category.length === 0 ? (
            <p className="muted">No assets with a recorded category.</p>
          ) : (
            <DataTable
              rows={data.by_category.map((r) => ({
                category: r.category,
                "Asset count": r.asset_count,
                "Purchase cost": fmtMoney(r.purchase_cost),
              }))}
              keys={['category', 'Asset count', 'Purchase cost']}
              rowKey="category"
            />
          )}
        </div>
        <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
          <h4 style={{ marginTop: 0 }}>Purchase cost by vendor</h4>
          {data.by_vendor.length === 0 ? (
            <p className="muted">No assets with a recorded vendor.</p>
          ) : (
            <DataTable
              rows={data.by_vendor.map((r) => ({
                vendor: r.vendor,
                "Asset count": r.asset_count,
                "Purchase cost": fmtMoney(r.purchase_cost),
              }))}
              keys={['vendor', 'Asset count', 'Purchase cost']}
              rowKey="vendor"
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
  return (
    <div>
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
          body="No maintenance events match the current filters. Adjust the date range or clear filters."
        />
      ) : (
        <>
          <div className="row-gap" style={{ marginTop: 'var(--sp-3)' }}>
            <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
              <h4 style={{ marginTop: 0 }}>By status</h4>
              <DistributionChart
                data={Object.entries(data.by_status).map(([k, v]) => ({ id: k, status: k, count: v }))}
                valueKey="count"
                labelKey="status"
                color="var(--status-available)"
              />
            </div>
            <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
              <h4 style={{ marginTop: 0 }}>By type</h4>
              <DistributionChart
                data={Object.entries(data.by_type).map(([k, v]) => ({ id: k, type: k, count: v }))}
                valueKey="count"
                labelKey="type"
                color="var(--accent)"
              />
            </div>
          </div>

          <div className="row-gap" style={{ marginTop: 'var(--sp-3)' }}>
            <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
              <h4 style={{ marginTop: 0 }}>Expenditure by category</h4>
              {data.by_category.length === 0 ? (
                <p className="muted">No maintenance records with a category.</p>
              ) : (
                <DataTable
                  rows={data.by_category.map((r) => ({
                    Category: r.category,
                    "Records": r.count,
                    "Cost": fmtMoney(r.cost),
                  }))}
                  keys={['Category', 'Records', 'Cost']}
                  rowKey="Category"
                />
              )}
            </div>
            <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
              <h4 style={{ marginTop: 0 }}>Expenditure by vendor</h4>
              {data.by_vendor.length === 0 ? (
                <p className="muted">No maintenance records with a vendor.</p>
              ) : (
                <DataTable
                  rows={data.by_vendor.map((r) => ({
                    Vendor: r.vendor,
                    "Records": r.count,
                    "Cost": fmtMoney(r.cost),
                  }))}
                  keys={['Vendor', 'Records', 'Cost']}
                  rowKey="Vendor"
                />
              )}
            </div>
          </div>

          <div className="panel panel-pad" style={{ marginTop: 'var(--sp-3)' }}>
            <h4 style={{ marginTop: 0 }}>Frequently maintained assets</h4>
            {data.top_assets.length === 0 ? (
              <p className="muted">No assets with maintenance records.</p>
            ) : (
              <DataTable
                rows={data.top_assets.map((r) => ({
                  "Asset": r.asset_tag,
                  Name: r.name,
                  "Records": r.count,
                  "Cost": fmtMoney(r.cost),
                  Actions: r.asset_id ? (
                    <Link href={`#/assets/${r.asset_id}`} className="btn-ghost btn-small">View</Link>
                  ) : '',
                }))}
                keys={['Asset', 'Name', 'Records', 'Cost', 'Actions']}
                rowKey="Asset"
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
  return (
    <div>
      <div className="kpi-grid" style={{ marginTop: 'var(--sp-3)' }}>
        <Kpi label="Expired" value={data.expired_count} sub="Warranty past expiry" />
        <Kpi label="Expiring within 30 days" value={data.expiring_soon?.[30] ?? 0} sub="Due soon" />
        <Kpi label="Expiring within 90 days" value={data.expiring_soon?.[90] ?? 0} sub="Due in 3 months" />
        <Kpi label="Expiring within 180 days" value={data.expiring_soon?.[180] ?? 0} sub="Due in 6 months" />
        <Kpi label="Without warranty" value={data.without_warranty} sub="No expiry recorded" />
        <Kpi
          label="Total with warranty"
          value={data.total_with_warranty}
          sub="Assets with warranty_expiry"
        />
      </div>

      {data.expired_count > 0 || (data.expiring_soon && (data.expiring_soon[30] || data.expiring_soon[90] || data.expiring_soon[180]) > 0) ? (
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
            ['30', '90', '180'].forEach((days, i) => {
              const n = data.expiring_soon?.[Number(days)] ?? 0;
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
          {data.expiring_list && data.expiring_list.length > 0 ? (
            <DataTable
              rows={data.expiring_list.map((r) => ({
                "Asset": r.asset_tag,
                "Name": r.name,
                Category: r.category,
                Vendor: r.vendor,
                "Expiry": fmtDate(r.expiry),
                "Days left": r.days_left,
                Actions: r.asset_tag ? (
                  <Link href={`#/assets/${r.asset_tag}`} className="btn-ghost btn-small">View</Link>
                ) : '',
              }))}
              keys={['Asset', 'Name', 'Category', 'Vendor', 'Expiry', 'Days left', 'Actions']}
              rowKey="Asset"
            />
          ) : (
            <p className="muted">No warranties expiring in the next 90 days.</p>
          )}
        </div>
        <div className="panel panel-pad" style={{ flex: '1 1 45%' }}>
          <h4 style={{ marginTop: 0 }}>Assets without warranty</h4>
          <p className="muted">
            {data.without_warranty} asset{data.without_warranty !== 1 ? 's' : ''} have no warranty_expiry recorded.
            Use the inventory report to find and update them.
          </p>
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginTop: 'var(--sp-3)' }}>
        <h4 style={{ marginTop: 0 }}>Filter by expiry date</h4>
        <DateRange
          from={fromDate}
          to={toDate}
          onFromChange={setFromDate}
          onToChange={setToDate}
          label="Warranty expiry range"
        />
      </div>
    </div>
  );
}

function Utilization({ data }) {
  if (!data) return null;
  const sc = data.status_counts || {};
  return (
    <div>
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
          {data.assignment_distribution && data.assignment_distribution.length > 0 ? (
            <DataTable
              rows={data.assignment_distribution.map((r, i) => ({
                "#": i + 1,
                Employee: r.employee_name || r.email,
                "Employee ID": r.employee_id,
                Department: r.department,
                "Assets held": r.asset_count,
              }))}
              keys={['#', 'Employee', 'Employee ID', 'Department', 'Assets held']}
              rowKey="Employee"
            />
          ) : (
            <p className="muted">No assigned assets to display.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function InventoryReport({ data }) {
  if (!data) return null;
  return (
    <div>
      <div className="row-gap" style={{ marginTop: 'var(--sp-3)', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <h4 style={{ marginTop: 0 }}>Filtered asset inventory</h4>
          <p className="muted small">{data.count} asset{data.count !== 1 ? 's' : ''} in result set</p>
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

      {data.items && data.items.length > 0 ? (
        <DataTable
          rows={(data.items || []).map((r) => ({
            "Asset tag": r.asset_tag,
            "Name": r.name,
            Category: r.category,
            Status: r.status,
            "Assigned to": r.assigned_to || '—',
            "Purchase cost": r.purchase_cost != null ? fmtMoney(r.purchase_cost) : '—',
            "Warranty expiry": r.warranty_expiry ? fmtDate(r.warranty_expiry) : '—',
            Actions: r.id ? (
              <Link href={`#/assets/${r.id}`} className="btn-ghost btn-small">View</Link>
            ) : '',
          }))}
          keys={['Asset tag', 'Name', 'Category', 'Status', 'Assigned to', 'Purchase cost', 'Warranty expiry', 'Actions']}
          rowKey="Asset tag"
        />
      ) : (
        <EmptyState
          title="No assets match the current filters"
          body="Try widening the date range or clearing filters."
        />
      )}
    </div>
  );
}
