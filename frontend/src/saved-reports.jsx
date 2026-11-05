import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, DataTable, EmptyState, Field, Modal, PageHeader, Pager,
  TableControls, UserSelect, useSort, useTableColumns,
} from './components';
import { fetchPage, parseApiError } from './api-utils';

const REPORT_TYPES = [
  { value: 'ticket_category', label: 'Tickets by category' },
  { value: 'ticket_sla', label: 'SLA health' },
];

const SCHEDULES = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
];

const FORMATS = [
  { value: 'csv', label: 'CSV' },
  { value: 'json', label: 'JSON' },
];

/** Saved report management page.
 *
 * Users can create, edit, duplicate, and delete their own saved reports.
 * IT staff / admins see all reports (including shared ones).
 * Running a saved report redirects to the existing report API with the
 * persisted filters applied.
 */
export function SavedReports() {
  const { isStaff } = useAuth();
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [f, setF] = useState({ q: '', report_type: '' });
  const [sort, changeSort, orderingParam] = useSort();
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null); // {id} or null
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState('');
  const [formMsg, setFormMsg] = useState('');
  const [runBusy, setRunBusy] = useState(null);
  const [delFor, setDelFor] = useState(null);
  const [delBusy, setDelBusy] = useState(false);

  const SR_COLUMNS = [
    { key: 'name', label: 'Name', render: (r) => <span className="row-title">{r.name}</span> },
    { key: 'report_type', label: 'Type', sortable: 'report_type', render: (r) => <Badge kind="status" value={r.report_type} /> },
    { key: 'description', label: 'Description', render: (r) => r.description || <span className="cell-muted">—</span> },
    { key: 'is_shared', label: 'Shared', sortable: 'is_shared', render: (r) => r.is_shared ? <Badge kind="status" value="shared" label="Yes" /> : 'No' },
    { key: 'schedule_count', label: 'Schedules', sortable: 'schedule_count', render: (r) => String(r.schedule_count ?? 0) },
    { key: 'updated', label: 'Updated', sortable: 'updated_at', render: (r) => r.updated_at ? new Date(r.updated_at).toLocaleDateString() : '-' },
  ];

  const { visibleColumns: visibleSrColumns, toggleColumn: toggleSrColumn, resetColumns: resetSrColumns, tableVisible: srTableVisible, toggleTable: toggleSrTable } = useTableColumns(
    'saved-reports',
    SR_COLUMNS.map((c) => c.key),
    ['name', 'report_type', 'description', 'is_shared', 'schedule_count', 'updated'],
  );
  const srColumns = SR_COLUMNS.filter((c) => visibleSrColumns.has(c.key));

  const buildUrl = (over = {}, sortOverride) => {
    const p = new URLSearchParams();
    const merged = { ...f, ...over };
    for (const k of ['q', 'report_type']) {
      if (merged[k] !== '' && merged[k] != null) p.set(k, merged[k]);
    }
    const ord = orderingParam(sortOverride);
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    return `/common/saved-reports/${qs ? `?${qs}` : ''}`;
  };

  const loadUrl = async (url) => {
    setLoading(true);
    setListError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items);
      setCount(pg.count);
      setNext(pg.next);
      setPrevious(pg.previous);
    } catch {
      setListError('Could not load saved reports.');
    } finally {
      setLoading(false);
    }
  };

  const applyFilters = (patch) => {
    const merged = { ...f, ...patch };
    setF(merged);
    const p = new URLSearchParams();
    for (const k of ['q', 'report_type']) {
      if (merged[k] !== '' && merged[k] != null) p.set(k, merged[k]);
    }
    const ord = orderingParam();
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    loadUrl(`/common/saved-reports/${qs ? `?${qs}` : ''}`);
  };

  // ---- Saved report create/edit form ----

  const [form, setForm] = useState({
    report_type: 'ticket_category', name: '', description: '', filters: '{}', is_shared: false,
  });
  const setField = (k) => (e) => setForm((p) => ({ ...p, [k]: e?.target?.value ?? e }));

  const openForm = (report = null) => {
    setEditing(report ? { id: report.id } : null);
    setForm(report ? {
      report_type: report.report_type ?? 'ticket_category',
      name: report.name ?? '',
      description: report.description ?? '',
      filters: typeof report.filters === 'string' ? report.filters : JSON.stringify(report.filters ?? {}),
      is_shared: !!report.is_shared,
    } : { report_type: 'ticket_category', name: '', description: '', filters: '{}', is_shared: false });
    setFormError('');
    setFormMsg('');
    setShowForm(true);
  };

  const closeForm = () => { setShowForm(false); setEditing(null); };

  const saveReport = async (ev) => {
    ev.preventDefault();
    if (formBusy) return;
    setFormBusy(true);
    setFormError('');
    setFormMsg('');
    let parsedFilters = {};
    try {
      parsedFilters = JSON.parse(form.filters || '{}');
    } catch {
      setFormError('Filters must be valid JSON.');
      setFormBusy(false);
      return;
    }
    const url = editing ? `/common/saved-reports/${editing.id}/` : '/common/saved-reports/';
    const method = editing ? 'patch' : 'post';
    try {
      const r = await api[method](url, {
        report_type: form.report_type,
        name: form.name.trim(),
        description: form.description.trim(),
        filters: parsedFilters,
        is_shared: form.is_shared === true || form.is_shared === 'true',
      });
      setFormMsg(`Saved report "${r.data.name}" saved.`);
      setEditing(null);
      setShowForm(false);
      await loadUrl(buildUrl());
    } catch (e) {
      setFormError(parseApiError(e).global || 'Could not save report.');
    } finally {
      setFormBusy(false);
    }
  };

  const doDelete = async (report) => {
    setDelFor(report.id);
    setDelBusy(true);
    try {
      await api.delete(`/common/saved-reports/${report.id}/`);
      setItems(items.filter((r) => r.id !== report.id));
      setCount(Math.max(0, (count ?? 1) - 1));
    } catch (e) {
      setListError(parseApiError(e).global || 'Could not delete saved report.');
    } finally {
      setDelFor(null);
      setDelBusy(false);
    }
  };

  const doRun = async (report) => {
    if (runBusy) return;
    setRunBusy(report.id);
    try {
      const filters = typeof report.filters === 'object' ? report.filters : JSON.parse(report.filters || '{}');
      const p = new URLSearchParams(filters);
      let url = '';
      if (report.report_type === 'ticket_category') {
        url = `/tickets/reports/by-category/${p.toString() ? `?${p.toString()}` : ''}`;
      } else if (report.report_type === 'ticket_sla') {
        url = `/tickets/reports/sla/${p.toString() ? `?${p.toString()}` : ''}`;
      }
      if (!url) {
        setFormError(`Unknown report type: ${report.report_type}`);
        return;
      }
      // Fetch through the axios client so the JWT (and its 401 refresh) is
      // applied — window.open() would hit the protected endpoint without the
      // Authorization header and always 401.
      const r = await api.get(url);
      const data = typeof r.data === 'string' ? r.data : JSON.stringify(r.data, null, 2);
      const blob = new Blob([data], { type: 'application/json' });
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objUrl;
      a.download = `${report.name || report.report_type}-report.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(objUrl), 5000);
      setFormMsg(`Report "${report.name}" downloaded.`);
    } catch (e) {
      setFormError(parseApiError(e).global || 'Could not run report.');
    } finally {
      setRunBusy(null);
    }
  };

  const duplicate = (report) => {
    openForm({
      ...report,
      name: `(Copy) ${report.name}`,
      id: null,
    });
  };

  useEffect(() => { loadUrl('/common/saved-reports/'); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <PageHeader
        title="Saved Reports"
        sub={count != null ? `${count} saved report${count === 1 ? '' : 's'}` : undefined}
        actions={<>
          <button type="button" className="btn-primary" onClick={() => openForm()}>+ New report</button>
        </>}
      />
      {listError && <div className="error-summary" role="alert">{listError}</div>}
      {formMsg && <div className="success-summary" role="status">{formMsg}</div>}
      {formError && <div className="error-summary" role="alert">{formError}</div>}

      {showForm && (
        <Modal title={editing ? 'Edit saved report' : 'New saved report'} onClose={closeForm} size="wide">
          <form onSubmit={saveReport} noValidate>
            <Field label="Name" required error={formError}>
              <input className="input" value={form.name} onChange={setField('name')} placeholder="e.g. Weekly ticket volume" disabled={formBusy} maxLength={200} />
            </Field>
            <Field label="Report type" required>
              <select className="input" value={form.report_type} onChange={setField('report_type')} disabled={formBusy}>
                {REPORT_TYPES.map((rt) => <option key={rt.value} value={rt.value}>{rt.label}</option>)}
              </select>
            </Field>
            <Field label="Description">
              <textarea className="input" rows={3} value={form.description} onChange={setField('description')} placeholder="What this report shows…" disabled={formBusy} />
            </Field>
            <Field label="Filters (JSON)" hint='Filter parameters persisted with the report (valid JSON object).'>
              <textarea className="input" rows={4} value={form.filters} onChange={setField('filters')} placeholder="{}" disabled={formBusy} />
            </Field>
            <Field label="Share with IT staff">
              <label className="check-row">
                <input type="checkbox" checked={form.is_shared === true || form.is_shared === 'true'} onChange={(e) => setField('is_shared')(e.target.checked)} disabled={formBusy} />
                IT staff and admins can see this saved report.
              </label>
            </Field>
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={closeForm} disabled={formBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={formBusy || !form.name.trim()}>
                {formBusy ? 'Saving…' : (editing ? 'Save changes' : 'Create report')}
              </button>
            </div>
          </form>
        </Modal>
      )}

      <div className="filter-bar" role="search">
        <input
          className="input grow" value={f.q} onChange={(e) => applyFilters({ q: e.target.value })}
          placeholder="Search report name or description…" aria-label="Search saved reports"
        />
        <select className="input" value={f.report_type} onChange={(e) => applyFilters({ report_type: e.target.value })} aria-label="Filter by report type">
          <option value="">All types</option>
          {REPORT_TYPES.map((rt) => <option key={rt.value} value={rt.value}>{rt.label}</option>)}
        </select>
        {filtersActive() && (
          <button type="button" className="btn-ghost" onClick={() => setF({ q: '', report_type: '' })}>Clear filters</button>
        )}
      </div>

      <div className="panel">
        {loading ? <div className="panel-pad"><div className="muted">Loading…</div></div>
          : listError ? <div className="panel-pad"><div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={() => loadUrl(buildUrl())}>Retry</button></div></div>
          : count === 0 ? <EmptyState title="No saved reports yet." hint="Create your first saved report with + New report." />
          : (<>
            <TableControls tableVisible={srTableVisible} onToggleTable={toggleSrTable} columns={SR_COLUMNS} visible={visibleSrColumns} onToggleColumn={toggleSrColumn} onReset={resetSrColumns} />
            {srTableVisible ? (
              <DataTable
                columns={srColumns}
                rows={items}
                keyOf={(r) => r.id}
                sort={sort}
                onSort={changeSort}
                emptyTitle="No reports match."
                emptyHint="Adjust the search or type filter."
              />
            ) : (
              <p className="muted">Table hidden.</p>
            )}
            <div className="row-gap" style={{ marginTop: 'var(--sp-2)' }}>
              {items.map((r) => (
                <div key={r.id} className="report-card">
                  <div className="report-card-head">
                    <div>
                      <strong>{r.name}</strong>
                      <span className="muted small"> · {r.report_type}</span>
                      {r.is_shared && <span className="badge badge-gray" style={{ marginLeft: 6 }}>Shared</span>}
                    </div>
                    <div className="row-end">
                      <button type="button" className="btn-small" onClick={() => doRun(r)} disabled={runBusy === r.id}>
                        {runBusy === r.id ? 'Running…' : 'Run'}
                      </button>
                      <button type="button" className="btn-ghost btn-small" onClick={() => openForm(r)}>Edit</button>
                      <button type="button" className="btn-ghost btn-small" onClick={() => duplicate(r)}>Duplicate</button>
                      <button type="button" className="btn-small btn-danger" onClick={() => doDelete(r)} disabled={delBusy || delFor === r.id}>
                        {delFor === r.id ? 'Deleting…' : 'Delete'}
                      </button>
                    </div>
                  </div>
                  <div className="report-card-body">
                    <p className="muted">{r.description || 'No description.'}</p>
                    <div className="muted small" style={{ fontFamily: 'monospace', fontSize: '0.85rem', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                      {JSON.stringify(r.filters ?? {}, null, 2) || '{}'}
                    </div>
                    <div className="muted small" style={{ marginTop: 'var(--sp-1)' }}>
                      Updated {r.updated_at ? new Date(r.updated_at).toLocaleString() : '—'} · {r.schedule_count ?? 0} schedule{(r.schedule_count ?? 0) !== 1 ? 's' : ''}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />
          </>)}
      </div>
    </div>
  );

  function filtersActive() {
    return !!(f.q || f.report_type);
  }
}

export default SavedReports;
