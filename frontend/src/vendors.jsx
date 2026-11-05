import { useEffect, useMemo, useState } from 'react';
import { useAuth } from './auth';
import { useTableColumns, useSort } from './components';
import { Badge, Field, ErrorSummary, LoadingRows, EmptyState, DataTable, Pager, PageHeader, ConfirmDialog, Modal, AccessDenied } from './components';
import { parseApiError, fieldMsg } from './api-utils';
import api from './api';

/** Vendor list page with server-side data, search, filter, sorting, pagination. */
function VendorsPage() {
  const { isStaff, isAdmin, canManageVendors } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [sel, setSel] = useState(new Set());
  const [f, setF] = useState({ q: '', is_active: '', is_deleted: '' });
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [rowActionBusy, setRowActionBusy] = useState(false);
  const [sort, changeSort, orderingParam] = useSort();
  const [lastUrl, setLastUrl] = useState('/api/assets/vendors/');
  const [exportOpen, setExportOpen] = useState(false);

  // Column definitions
  const VENDOR_COLUMNS = [
    { key: 'name', label: 'Name', sortable: 'name', render: (v) => (
      <a className="row-title" href={`#/vendors/${v.id}`}>{v.name || '<span className="cell-muted">—</span>'}</a>
    ) },
    { key: 'code', label: 'Code', sortable: 'code', render: (v) => v.code || '<span className="cell-muted">—</span>' },
    { key: 'contact_person', label: 'Contact', sortable: 'contact_person', render: (v) => v.contact_person || '<span className="cell-muted">—</span>' },
    { key: 'email', label: 'Email', sortable: 'email', render: (v) => v.email || '<span className="cell-muted">—</span>' },
    { key: 'phone', label: 'Phone', sortable: 'phone', render: (v) => v.phone || '<span className="cell-muted">—</span>' },
    { key: 'is_active', label: 'Active', sortable: 'is_active', render: (v) => (
      <Badge kind="status" value={v.is_active ? 'Active' : 'Inactive'} />
    ) },
    { key: 'asset_count', label: 'Assets', sortable: 'asset_count', render: (v) => v.asset_count || 0 },
    { key: 'stock_item_count', label: 'Stock Items', sortable: 'stock_item_count', render: (v) => v.stock_item_count || 0 },
    { key: 'updated_at', label: 'Updated', sortable: 'updated_at', render: (v) => v.updated_at ? new Date(v.updated_at).toLocaleDateString() : '<span className="cell-muted">—</span>' },
    ...(isStaff ? [
      { key: 'actions', label: 'Actions', thClass: 'table-actions', render: (v) => (
        <div style={{ display: 'flex', gap: '4px' }}>
          <button className="btn btn-sm btn-outline secondary" onClick={() => openDetail(v.id)} title="View">
            View
          </button>
          {isAdmin ? (
            <button className="btn btn-sm btn-outline" onClick={() => setDeleteTarget(v.id)} title="Delete">
              Delete
            </button>
          ) : null}
          {isAdmin ? (
            <button className="btn btn-sm btn-outline" onClick={() => openActivateForm(v.id)} title={v.is_active ? 'Deactivate' : 'Activate'}>
              {v.is_active ? 'Deactivate' : 'Activate'}
            </button>
          ) : null}
        </div>
      ) }
    ] : [])
  ];

  const { visibleColumns: visibleVendorColumns, toggleColumn: toggleVendorColumn, resetColumns: resetVendorColumns, tableVisible: vendorTableVisible, toggleTable: vendorToggleTable } = useTableColumns(
    'vendors',
    VENDOR_COLUMNS.map((c) => c.key),
    isStaff
      ? ['name', 'code', 'contact_person', 'email', 'phone', 'is_active', 'asset_count', 'stock_item_count', 'actions']
      : ['name', 'code', 'contact_person', 'email', 'phone', 'is_active']
  );
  const vendorColumns = VENDOR_COLUMNS.filter((c) => visibleVendorColumns.has(c.key));

  const loadUrl = async (url) => {
    setLoading(true);
    setListError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
      setLastUrl(url);
      setPage(pageFromUrl(url));
    } catch {
      setListError('Could not load vendors.');
    } finally {
      setLoading(false);
    }
  };

  // Search and filter
  const qsKey = JSON.stringify([f, orderingParam(sort)]);
  const builtUrl = useMemo(() => buildVendorListUrl(f, orderingParam(sort)), [qsKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(async () => {
      if (cancelled) return;
      setSel(new Set());
      await loadUrl(builtUrl);
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [builtUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const handleDelete = async (id) => {
    setDeleteBusy(true);
    setActionError('');
    try {
      await api.delete(`/api/assets/vendors/${id}/`);
      setSel(new Set());
      await loadUrl(lastUrl);
      setShowDeleteConfirm(false);
      setActionError('Vendor soft-deleted successfully.');
    } catch (e) {
      setActionError('Could not delete vendor. ' + (e.response?.data?.global || e.response?.data?.detail || String(e)));
    } finally {
      setDeleteBusy(false);
    }
  };

  const openDeleteConfirm = (id) => {
    setDeleteTarget(id);
    setShowDeleteConfirm(true);
  };

  const handleActivate = async (id) => {
    setRowActionBusy(true);
    setActionError('');
    try {
      await api.post(`/api/assets/vendors/${id}/activate/`);
      await loadUrl(lastUrl);
      setActionError('Vendor activated.');
    } catch (e) {
      setActionError('Could not activate vendor. ' + (e.response?.data?.global || e.response?.data?.detail || String(e)));
    } finally {
      setRowActionBusy(false);
    }
  };

  const handleDeactivate = async (id) => {
    setRowActionBusy(true);
    setActionError('');
    try {
      await api.post(`/api/assets/vendors/${id}/deactivate/`);
      await loadUrl(lastUrl);
      setActionError('Vendor deactivated.');
    } catch (e) {
      setActionError('Could not deactivate vendor. ' + (e.response?.data?.global || e.response?.data?.detail || String(e)));
    } finally {
      setRowActionBusy(false);
    }
  };

  const handleSearchChange = (e) => {
    setF({ ...f, q: e.target.value });
  };

  const handleFilterChange = (e) => {
    const { name, value } = e.target;
    setF({ ...f, [name]: value });
  };

  return (
    <div className="vendors-page">
      <PageHeader
        title="Vendors"
        sub={isStaff ? 'Manage vendors and suppliers' : 'View vendors on assigned assets'}
      />

      {/* Toolbar */}
      <div className="page-toolbar" style={{ display: 'flex', gap: '16px', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap' }}>
        <Field
          label="Search"
          required={false}
          hint="Search by name, code, contact, email, or phone"
          onChange={handleSearchChange}
        />
        <Field
          label="Active"
          required={false}
          hint="Filter by active status"
          component="select"
          onChange={handleFilterChange}
          disabled={!isStaff}
          options={[
            { label: 'All', value: '' },
            { label: 'Active', value: 'is_active=true' },
            { label: 'Inactive', value: 'is_active=false' },
          ]}
        />
        {canManageVendors ? (
          <>
            <button
              className="btn btn-primary"
              onClick={() => openDeleteConfirm(null)}
              disabled={deleteBusy}
              style={{ marginRight: '8px' }}
            >
              {deleteBusy ? 'Deleting…' : 'New Vendor'}
            </button>
            {exportOpen && (
              <button className="btn btn-outline" onClick={() => setExportOpen(false)} title="Close export">
                ✕
              </button>
            )}
          </>
        ) : null}
      </div>

      {/* Error state */}
      {listError && (
        <div className="alert alert-danger" role="alert">
          {listError}
        </div>
      )}

      {/* Table */}
      <div style={{ marginTop: '24px' }}>
        <DataTable
          title="Vendors"
          columns={vendorColumns}
          rows={items}
          keyOf="id"
          emptyTitle="No vendors found"
          emptyHint={isStaff
            ? 'Create a new vendor to get started.'
            : 'Vendors are displayed on assigned assets.'}
          loading={loading}
          pagination={count !== null ? { page, next, previous, count } : undefined}
          onPageChange={async (newPage) => {
            // Rebuild URL for the new page
            const newUrl = buildVendorListUrl(f, orderingParam(sort), newPage);
            await loadUrl(newUrl);
          }}
        />
      </div>

      {/* Confirmation dialogs */}
      <ConfirmDialog
        title="Confirm Deletion"
        message={`Are you sure you want to soft-delete this vendor? Existing records (assets, stock items) will remain linked, but the vendor will be removed from new selections.`}
        confirmLabel="Delete"
        danger={true}
        busy={deleteBusy}
        onConfirm={() => { if (deleteTarget) handleDelete(deleteTarget); setShowDeleteConfirm(false);}}
        onCancel={() => setShowDeleteConfirm(false)}
      />

      {isStaff && exportOpen && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3>Export Vendors</h3>
            <p>Export functionality coming soon.</p>
            <button className="btn btn-primary" onClick={() => setExportOpen(false)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Vendor form for create and edit. */
function VendorForm({ onSave, onClose, vendorId }) {
  const { canManageVendors } = useAuth();
  const [form, setForm] = useState({
    name: '',
    code: '',
    contact_person: '',
    email: '',
    phone: '',
    website: '',
    address: '',
    tax_registration: '',
    notes: '',
    is_active: true,
  });
  const [vendor, setVendor] = useState(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');

  // Load existing vendor for edit
  useEffect(() => {
    if (vendorId) {
      api.get(`/api/assets/vendors/${vendorId}/`)
        .then((r) => setVendor(r.data))
        .then((d) => {
          setForm({
            name: d.name || '',
            code: d.code || '',
            contact_person: d.contact_person || '',
            email: d.email || '',
            phone: d.phone || '',
            website: d.website || '',
            address: d.address || '',
            tax_registration: d.tax_registration || '',
            notes: d.notes || '',
            is_active: d.is_active !== false,
          });
        })
        .catch((e) => {
          setFormError('Could not load vendor data. ' + (e.response?.data?.global || e.response?.data?.detail || String(e)));
        });
    } else {
      setVendor(null);
    }
  }, [vendorId]);

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setForm({
      ...form,
      [name]: type === 'checkbox' ? checked : value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setFormError('');

    try {
      if (vendorId) {
        // Edit
        await api.patch(`/api/assets/vendors/${vendorId}/`, form);
      } else {
        // Create
        await api.post(`/api/assets/vendors/`, form);
      }
      setSaving(false);
      onSave && onSave();
    } catch (e) {
      setSaving(false);
      const apiErr = parseApiError(e);
      const fieldErrors = Object.entries(apiErr.fields || {}).reduce((acc, [k, v]) => {
        acc[k] = Array.isArray(v) ? v.join(' ') : String(v);
        return acc;
      }, {});
      setFormError(
        (apiErr.global || '') +
        (Object.keys(fieldErrors).length ? ' • ' + Object.entries(fieldErrors).map(([k, v]) => `${k}: ${v}`).join(' • ') : '')
      );
    }
  };

  if (!canManageVendors) {
    return (
      <div className="panel-pad">
        <AccessDenied reason="manager" backLabel="Go to Vendors" />
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <PageHeader title={vendorId ? 'Edit Vendor' : 'New Vendor'}>

        {formError && (
          <div className="alert alert-danger" role="alert">
            {formError}
          </div>
        )}

        <Field label="Name*" name="name" component="input" required={true} onChange={handleChange} value={form.name} />
        <Field label="Code*" name="code" component="input" required={true} onChange={handleChange} value={form.code} />
        <Field label="Contact Person" name="contact_person" component="input" onChange={handleChange} value={form.contact_person} />
        <Field label="Email*" name="email" component="input" required={true} type="email" onChange={handleChange} value={form.email} />
        <Field label="Phone" name="phone" component="input" onChange={handleChange} value={form.phone} />
        <Field label="Website" name="website" component="input" onChange={handleChange} value={form.website} />
        <Field label="Address" name="address" component="textarea" onChange={handleChange} value={form.address} />
        <Field label="Tax/Registration" name="tax_registration" component="input" onChange={handleChange} value={form.tax_registration} />
        <Field label="Notes" name="notes" component="textarea" onChange={handleChange} value={form.notes} />
        <Field
          label="Active"
          name="is_active"
          component="switch"
          type="checkbox"
          checked={form.is_active}
          onChange={handleChange}
        />

        <div className="modal-foot" style={{ marginTop: '16px', display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
          <button type="button" onClick={onClose} className="btn btn-outline">Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? 'Saving…' : vendorId ? 'Update' : 'Create'}
          </button>
        </div>
      </PageHeader>
    </form>
  );
}

/** Vendor detail page with summary and usage information. */
function VendorDetail({ match }) {
  const { isStaff, isAdmin } = useAuth();
  const [vendor, setVendor] = useState(null);
  const [assets, setAssets] = useState([]);
  const [stockItems, setStockItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [detailError, setDetailError] = useState('');
  const [activateBusy, setActivateBusy] = useState(false);
  const [deactivateBusy, setDeactivateBusy] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [actionError, setActionError] = useState('');

  // Load vendor detail
  useEffect(() => {
    const id = match?.params?.id;
    if (id) {
      api.get(`/api/assets/vendors/${id}/`)
        .then((r) => setVendor(r.data))
        .then(() => {
          // Load related assets
          return api.get(`/api/assets/vendors/${id}/assets/`);
        })
        .then((r) => setAssets(r.data.results || r.data))
        .catch((e) => {
          setDetailError('Could not load vendor detail. ' + (e.response?.data?.global || e.response?.data?.detail || String(e)));
        })
        .finally(() => setLoading(false));

      // Load related stock items
      api.get(`/api/assets/vendors/${id}/stock-items/`)
        .then((r) => setStockItems(r.data.results || r.data))
        .catch(() => { /* ignore */ });
    }
  }, [match]);

  // Activate vendor
  const handleActivate = async () => {
    setActivateBusy(true);
    setActionError('');
    try {
      await api.post(`/api/assets/vendors/${vendor?.id}/activate/`);
      setActionError('Vendor activated.');
      setActivateBusy(false);
      if (vendor) setVendor({ ...vendor, is_active: true });
    } catch (e) {
      setActionError('Could not activate vendor. ' + (e.response?.data?.global || e.response?.data?.detail || String(e)));
      setActivateBusy(false);
    }
  };

  // Deactivate vendor
  const handleDeactivate = async () => {
    setDeactivateBusy(true);
    setActionError('');
    try {
      await api.post(`/api/assets/vendors/${vendor?.id}/deactivate/`);
      setActionError('Vendor deactivated.');
      setDeactivateBusy(false);
      if (vendor) setVendor({ ...vendor, is_active: false });
    } catch (e) {
      setActionError('Could not deactivate vendor. ' + (e.response?.data?.global || e.response?.data?.detail || String(e)));
      setDeactivateBusy(false);
    }
  };

  // Soft-delete vendor
  const handleDelete = async () => {
    setDeleteBusy(true);
    setActionError('');
    try {
      await api.delete(`/api/assets/vendors/${vendor?.id}/`);
      setActionError('Vendor soft-deleted.');
      setDeleteBusy(false);
      // Navigate back
      // window.history.back();
    } catch (e) {
      setActionError('Could not delete vendor. ' + (e.response?.data?.global || e.response?.data?.detail || String(e)));
      setDeleteBusy(false);
    }
  };

  if (loading || !vendor) {
    return (
      <div className="detail-loading">
        <p>Loading vendor detail…</p>
      </div>
    );
  }

  const assetCount = vendor.asset_count || assets.length;
  const stockItemCount = vendor.stock_item_count || stockItems.length;

  return (
    <div className="vendor-detail-page">
      <PageHeader title={vendor.name}>

        {/* Vendor summary section */}
        <div className="vendor-summary">
          <div className="row">
            <div className="col-6">
              <strong>Name:</strong> {vendor.name}
            </div>
            <div className="col-6">
              <strong>Code:</strong> {vendor.code || '-'}
            </div>
          </div>
          <div className="row">
            <div className="col-6">
              <strong>Status:</strong>
              <Badge kind="status" value={vendor.is_active ? 'Active' : 'Inactive'} />
            </div>
            <div className="col-6">
              <strong>Type:</strong> {vendor.is_deleted ? 'Soft-deleted' : 'Normal'}
            </div>
          </div>
          <hr />
          <div className="row">
            <div className="col-4">
              <strong>Contact Person:</strong> {vendor.contact_person || '-'}
            </div>
            <div className="col-4">
              <strong>Email:</strong> {vendor.email || '-'}
            </div>
            <div className="col-4">
              <strong>Phone:</strong> {vendor.phone || '-'}
            </div>
          </div>
          {vendor.website && (
            <div className="row">
              <div className="col-4">
                <strong>Website:</strong> <a href={vendor.website} target="_blank" rel="noopener noreferrer">{vendor.website}</a>
              </div>
            </div>
          )}
          {vendor.address && (
            <div className="row">
              <div className="col-12">
                <strong>Address:</strong> {vendor.address}
              </div>
            </div>
          )}
          {vendor.tax_registration && isAdmin && (
            <div className="row">
              <div className="col-12">
                <strong>Tax Registration:</strong> {vendor.tax_registration}
              </div>
            </div>
          )}
          {vendor.notes && (
            <div className="row">
              <div className="col-12">
                <strong>Notes:</strong> {vendor.notes}
              </div>
            </div>
          )}
          <div className="row">
            <div className="col-4">
              <strong>Created:</strong> {vendor.created_at ? new Date(vendor.created_at).toLocaleDateString() : '-'}
            </div>
            <div className="col-4">
              <strong>Updated:</strong> {vendor.updated_at ? new Date(vendor.updated_at).toLocaleDateString() : '-'}
            </div>
            <div className="col-4">
              <strong>Created By:</strong> {vendor.created_by ? vendor.created_by : '-'}
            </div>
          </div>
        </div>

        {/* Usage summary section */}
        {isStaff && (
          <div className="vendor-usage">
            <h4>Usage</h4>
            <div className="row">
              <div className="col-4">
                <strong>Related Assets:</strong> {assetCount}
              </div>
              <div className="col-4">
                <strong>Preferred Stock Items:</strong> {stockItemCount}
              </div>
              {isAdmin && (
                <div className="col-4">
                  <button
                    className="btn btn-sm btn-outline"
                    onClick={() => handleActivate()}
                    disabled={activateBusy}
                    style={{ marginRight: '8px' }}>
                    {activateBusy ? 'Activating…' : 'Activate'}
                  </button>
                  <button
                    className="btn btn-sm btn-outline danger"
                    onClick={() => handleDeactivate()}
                    disabled={deactivateBusy}
                  >
                    {deactivateBusy ? 'Deactivating…' : 'Deactivate'}
                  </button>
                  {vendor.asset_count > 0 || vendor.stock_item_count > 0 && (
                    <span className="text-muted">
                      {vendor.asset_count > 0 && `${vendor.asset_count} asset(s), `}{vendor.stock_item_count > 0 && `${vendor.stock_item_count} stock item(s)`} reference this vendor. Deactivation will block new selections but preserve historical links.
                    </span>
                  )}
                  {isAdmin && (
                    <button
                      className="btn btn-sm btn-outline secondary"
                      onClick={() => handleDelete()}
                      disabled={deleteBusy}
                      style={{ marginLeft: '8px' }}>
                      {deleteBusy ? 'Deleting…' : 'Delete'}
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Related Assets */}
        {isStaff && (
          <div className="vendor-related">
            <h4>Related Assets ({assetCount})</h4>
            <div style={{ marginTop: '8px' }}>
              {assets.length > 0 ? (
                <DataTable
                  title="Assets"
                  columns={[
                    { key: 'asset_tag', label: 'Tag', render: (a) => <a className="row-title" href={`#/assets/${a.id}`}>{a.asset_tag}</a> },
                    { key: 'name', label: 'Name', render: (a) => a.name || '<span className="cell-muted">—</span>' },
                    { key: 'status', label: 'Status', render: (a) => <Badge kind="status" value={a.status} /> },
                    { key: 'purchase_cost', label: 'Cost', render: (a) => a.purchase_cost != null ? `<span className="cell-wrap">$${a.purchase_cost}</span>` : '<span className="cell-muted">—</span>' },
                  ]}
                  rows={assets}
                  keyOf="id"
                  emptyHint="No assets found"
                />
              ) : (
                '<p className="cell-muted">No assets</p>'
              )}
            </div>
          </div>
        )}

        {/* Related Stock Items */}
        {isStaff && stockItems.length > 0 && (
          <div className="vendor-related">
            <h4>Preferred Stock Items ({stockItemCount})</h4>
            <div style={{ marginTop: '8px' }}>
              {stockItems.map((si) => (
                <div key={si.id} style={{ marginBottom: '8px', paddingBottom: '8px', borderBottom: '1px solid #eaecef' }}>
                  <strong>SKU:</strong> {si.sku || '-'} • <strong>Name:</strong> {si.name || '-'}
                  <span className="text-muted">Qty: {si.quantity || 0} • Available: {si.available_quantity || 0}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Actions */}
        {isStaff && (
          <div className="vendor-actions">
            <button className="btn btn-outline" onClick={() => /* navigate back */ history.back()}>
              Back to Vendors
            </button>
            {isAdmin ? (
              <div style={{ marginLeft: '16px', display: 'flex', gap: '8px' }}>
                <button className="btn btn-outline" onClick={() => handleActivate()}>
                  {activateBusy ? 'Activating…' : 'Activate'}
                </button>
                <button className="btn btn-outline danger" onClick={() => handleDeactivate()}>
                  {deactivateBusy ? 'Deactivating…' : 'Deactivate'}
                </button>
                <button className="btn btn-outline secondary" onClick={() => handleDelete()}>
                  {deleteBusy ? 'Deleting…' : 'Delete'}
                </button>
              </div>
            ) : null}
          </div>
        )}
      </PageHeader>
    </div>
  );
}

/** Build vendor list URL with filters, ordering, and pagination. */
function buildVendorListUrl(filters, ordering, page) {
  const params = new URLSearchParams();
  if (filters.q) params.append('q', filters.q);
  if (filters.is_active !== undefined) params.append('is_active', filters.is_active);
  if (filters.is_deleted !== undefined) params.append('is_deleted', filters.is_deleted);
  if (ordering) params.append('ordering', ordering);
  if (page && page > 1) params.append('page', page);
  return `/api/assets/vendors/?${params.toString()}`;
}

/** Page number from URL. */
function pageFromUrl(url) {
  try {
    const search = new URLSearchParams(new URL(url).searchParams);
    return parseInt(search.get('page') || '1', 10);
  } catch {
    return 1;
  }
}

export { VendorsPage, VendorForm, VendorDetail };