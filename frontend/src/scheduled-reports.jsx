import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  Badge, ConfirmDialog, DataTable, EmptyState, Field, Modal, PageHeader, Pager,
  TableControls, useSort, useTableColumns,
} from './components';
import { fetchPage, parseApiError } from './api-utils';

const SCHEDULES = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
];

const FORMATS = [
  { value: 'csv', label: 'CSV' },
  { value: 'xlsx', label: 'Excel (XLSX)' },
  { value: 'pdf', label: 'PDF' },
  { value: 'docx', label: 'Word (DOCX)' },
];

/** Scheduled report management (IT staff / admins).
 *
 * Lists scheduled reports, lets staff create/edit/enable/disable/delete
 * schedules built from saved reports, and shows per-schedule execution
 * history with retry for failed runs.
 */
export function ScheduledReports() {
  const { isStaff } = useAuth();

  // ---------- scheduled reports list ----------
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [f, setF] = useState({ q: '', schedule: '', format: '', enabled: '' });
  const [sort, changeSort, orderingParam] = useSort();

  // ---------- saved reports (for create/edit picker) ----------
  const [savedReports, setSavedReports] = useState([]);
  const [savedLoading, setSavedLoading] = useState(false);

  // ---------- create / edit form ----------
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null); // {id} or null
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState('');
  const [formMsg, setFormMsg] = useState('');
  const [form, setForm] = useState({
    saved_report: '', schedule: 'weekly', recipients: '', format: 'csv', enabled: true,
  });
  const setField = (k) => (e) => setForm((p) => ({ ...p, [k]: e?.target?.value ?? e }));

  // ---------- per-schedule history ----------
  const [historyFor, setHistoryFor] = useState(null); // scheduled report id
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // ---------- enable/disable ----------
  const [toggleBusy, setToggleBusy] = useState(null);

  // ---------- delete ----------
  const [delFor, setDelFor] = useState(null);
  const [delBusy, setDelBusy] = useState(false);

  // ---------- retry ----------
  const [retryBusy, setRetryBusy] = useState(null);

  const [msg, setMsg] = useState('');

  const SR_COLUMNS = [
    { key: 'name', label: 'Report', sortable: 'saved_report_name', render: (r) => <span className="row-title">{r.saved_report_name || r.name}</span> },
    { key: 'type', label: 'Type', sortable: 'saved_report_type', render: (r) => <Badge kind="status" value={r.saved_report_type || 'ticket_category'} label={r.saved_report_type || 'ticket_category'} /> },
    { key: 'schedule', label: 'Schedule', sortable: 'schedule', render: (r) => <span>{r.schedule}</span> },
    { key: 'format', label: 'Format', sortable: 'format', render: (r) => <Badge kind="status" value={r.format} label={r.format.toUpperCase()} /> },
    { key: 'recipients', label: 'Recipients', render: (r) => <span className="ellipsis" title={Array.isArray(r.recipients) ? r.recipients.join(', ') : String(r.recipients)}>{Array.isArray(r.recipients) ? r.recipients.join(', ') : String(r.recipients || '')}</span> },
    { key: 'enabled', label: 'Enabled', sortable: 'enabled', render: (r) => r.enabled ? <Badge kind="status" value="resolved" label="On" /> : <Badge kind="status" value="reopened" label="Off" /> },
    { key: 'next_run', label: 'Next run', sortable: 'next_run_at', render: (r) => r.next_run_at ? new Date(r.next_run_at).toLocaleString() : <span className="cell-muted">—</span> },
    { key: 'actions', label: 'Actions', thClass: 'cell-actions', render: (r) => (
      <div className="cell-actions">
        <button type="button" className="btn-small" onClick={() => openForm(r)} disabled={formBusy}>Edit…</button>
        <button type="button" className="btn-small" onClick={() => toggleEnabled(r)} disabled={toggleBusy === r.id || formBusy}>
          {toggleBusy === r.id ? '…' : (r.enabled ? 'Disable' : 'Enable')}
        </button>
        <button type="button" className="btn-small" onClick={() => openHistory(r)} disabled={historyLoading}>History</button>
        <button type="button" className="btn-small btn-danger" onClick={() => setDelFor(r.id)} disabled={delBusy || delFor === r.id}>Delete…</button>
      </div>
    ) },
  ];

  const { visibleColumns: visibleSrColumns, toggleColumn: toggleSrColumn, resetColumns: resetSrColumns, tableVisible: srTableVisible, toggleTable: toggleSrTable } = useTableColumns(
    'scheduled-reports',
    SR_COLUMNS.map((c) => c.key),
    ['name', 'type', 'schedule', 'format', 'recipients', 'enabled', 'next_run', 'actions'],
  );
  const srColumns = SR_COLUMNS.filter((c) => visibleSrColumns.has(c.key));

  const buildUrl = (over = {}, sortOverride) => {
    const p = new URLSearchParams();
    const merged = { ...f, ...over };
    for (const k of ['q', 'schedule', 'format', 'enabled']) {
      if (merged[k] !== '' && merged[k] != null) p.set(k, merged[k]);
    }
    const ord = orderingParam(sortOverride);
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    return `/api/common/scheduled-reports/${qs ? `?${qs}` : ''}`;
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
      setListError('Could not load scheduled reports.');
    } finally {
      setLoading(false);
    }
  };

  const applyFilters = (patch) => {
    const merged = { ...f, ...patch };
    setF(merged);
    const p = new URLSearchParams();
    for (const k of ['q', 'schedule', 'format', 'enabled']) {
      if (merged[k] !== '' && merged[k] != null) p.set(k, merged[k]);
    }
    const ord = orderingParam();
    if (ord) p.set('ordering', ord);
    const qs = p.toString();
    loadUrl(`/api/common/scheduled-reports/${qs ? `?${qs}` : ''}`);
  };

  const loadSavedReports = async () => {
    setSavedLoading(true);
    try {
      const r = await api.get('/common/saved-reports/');
      const data = r.data;
      const rows = data?.results ?? data ?? [];
      setSavedReports(rows);
    } catch {
      setListError('Could not load saved reports for scheduling.');
    } finally {
      setSavedLoading(false);
    }
  };

  const openForm = (report = null) => {
    setEditing(report ? { id: report.id } : null);
    setForm(report ? {
      saved_report: String(report.saved_report ?? ''),
      schedule: report.schedule ?? 'weekly',
      recipients: Array.isArray(report.recipients) ? report.recipients.join(', ') : String(report.recipients ?? ''),
      format: report.format ?? 'csv',
      enabled: !!report.enabled,
    } : { saved_report: '', schedule: 'weekly', recipients: '', format: 'csv', enabled: true });
    setFormError('');
    setFormMsg('');
    setShowForm(true);
  };

  const closeForm = () => { setShowForm(false); setEditing(null); };

  const saveSchedule = async (ev) => {
    ev.preventDefault();
    if (formBusy) return;
    setFormBusy(true);
    setFormError('');
    setFormMsg('');
    const recipients = form.recipients.split(',').map((e) => e.trim()).filter(Boolean);
    if (!recipients.length) {
      setFormError('Provide at least one recipient email.');
      setFormBusy(false);
      return;
    }
    const url = editing ? `/api/common/scheduled-reports/${editing.id}/` : '/api/common/scheduled-reports/';
    const method = editing ? 'patch' : 'post';
    try {
      const r = await api[method](url, {
        saved_report: Number(form.saved_report),
        schedule: form.schedule,
        recipients,
        format: form.format,
        enabled: form.enabled === true || form.enabled === 'true',
      });
      setFormMsg(`Schedule "${r.data.saved_report_name || r.data.name}" saved.`);
      setEditing(null);
      setShowForm(false);
      await loadUrl(buildUrl());
    } catch (e) {
      setFormError(parseApiError(e).global || 'Could not save schedule.');
    } finally {
      setFormBusy(false);
    }
  };

  const toggleEnabled = async (r) => {
    if (toggleBusy === r.id) return;
    setToggleBusy(r.id);
    try {
      await api.patch(`/api/common/scheduled-reports/${r.id}/`, { enabled: !r.enabled });
      setMsg(`Schedule "${r.saved_report_name || r.name}" ${r.enabled ? 'disabled' : 'enabled'}.`);
      await loadUrl(buildUrl());
    } catch (e) {
      setListError(parseApiError(e).global || 'Could not update schedule.');
    } finally {
      setToggleBusy(null);
    }
  };

  const doDelete = async (report) => {
    setDelFor(report.id);
    setDelBusy(true);
    try {
      await api.delete(`/api/common/scheduled-reports/${report.id}/`);
      setItems(items.filter((r) => r.id !== report.id));
      setCount(Math.max(0, (count ?? 1) - 1));
      setMsg(`Schedule "${report.saved_report_name || report.name}" deleted.`);
    } catch (e) {
      setListError(parseApiError(e).global || 'Could not delete schedule.');
    } finally {
      setDelFor(null);
      setDelBusy(false);
    }
  };

  // ---------- history ----------
  const loadHistory = async (id = historyFor) => {
    if (!id) return;
    setHistoryLoading(true);
    try {
      const r = await api.get('/common/scheduled-report-runs/');
      const data = r.data;
      const all = data?.results ?? data ?? [];
      setHistory(all.filter((run) => run.scheduled_report === id).sort((a, b) => new Date(b.started_at || 0) - new Date(a.started_at || 0)));
    } catch {
      setListError('Could not load run history.');
    } finally {
      setHistoryLoading(false);
    }
  };

  const openHistory = (r) => {
    setHistoryFor(r.id);
    setHistory([]);
    loadHistory(r.id);
  };
  const closeHistory = () => { setHistoryFor(null); setHistory([]); };

  const doRetry = async (run) => {
    if (retryBusy === run.id) return;
    setRetryBusy(run.id);
    try {
      const res = await api.post(`/api/common/scheduled-report-runs/${run.id}/retry/`, {}, { headers: { 'Content-Type': 'application/json' } });
      if (res.data.retried) {
        setMsg(`Retry dispatched for schedule "${run.scheduled_report}".`);
      } else {
        setListError(`Retry failed: ${res.data.error || 'unknown error'}.`);
      }
      loadHistory();
      await loadUrl(buildUrl());
    } catch (e) {
      const p = parseApiError(e);
      setListError(p.global || 'Retry failed.');
    } finally {
      setRetryBusy(null);
    }
  };

  const historyActions = (run) => {
    if (run.status !== 'failed') return '-';
    return (
      <button type="button" className="btn-small" onClick={() => doRetry(run)} disabled={retryBusy === run.id}>
        {retryBusy === run.id ? 'Retrying…' : 'Retry'}
      </button>
    );
  };

  useEffect(() => { loadUrl('/api/common/scheduled-reports/'); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadSavedReports(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const restrictedView = (
    <div>
      <PageHeader title="Scheduled reports" sub="IT staff only." />
      <div className="panel">
        <div className="panel-pad"><div className="error-summary" role="alert">
          Scheduled report management is restricted to IT staff and admins.
        </div></div>
      </div>
    </div>
  );

  if (!isStaff) return restrictedView;

  return (
    <div>
      <PageHeader
        title="Scheduled reports"
        sub={count != null ? `${count} schedule${count === 1 ? '' : 's'}` : undefined}
        actions={<button type="button" className="btn-primary" onClick={() => openForm()} disabled={formBusy || savedLoading}>
          {savedLoading ? 'Loading…' : '+ New schedule'}
        </button>}
      />
      {listError && <div className="error-summary" role="alert">{listError}</div>}
      {msg && <div className="success-summary" role="status">{msg}</div>}
      {formMsg && <div className="success-summary" role="status">{formMsg}</div>}
      {formError && <div className="error-summary" role="alert">{formError}</div>}

      {showForm && (
        <Modal title={editing ? 'Edit schedule' : 'New schedule'} onClose={closeForm} size="wide">
          <form onSubmit={saveSchedule} noValidate>
            <Field label="Saved report" required error={formError}>
              <select className="input" value={form.saved_report} onChange={setField('saved_report')} disabled={formBusy || savedLoading}>
                <option value="">Select a saved report…</option>
                {savedReports.map((sr) => (
                  <option key={sr.id} value={sr.id}>
                    {sr.name} ({sr.report_type})
                  </option>
                ))}
              </select>
              {savedLoading && <span className="muted small"> loading…</span>}
            </Field>
            <Field label="Schedule" required>
              <select className="input" value={form.schedule} onChange={setField('schedule')} disabled={formBusy}>
                {SCHEDULES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </Field>
            <Field label="Recipients" hint="Comma-separated email addresses that will receive the report." required>
              <input className="input" value={form.recipients} onChange={setField('recipients')} placeholder="ops@example.com, it@example.com" disabled={formBusy} />
            </Field>
            <Field label="Format" required>
              <select className="input" value={form.format} onChange={setField('format')} disabled={formBusy}>
                {FORMATS.map((fmt) => <option key={fmt.value} value={fmt.value}>{fmt.label}</option>)}
              </select>
            </Field>
            <Field label="Enabled">
              <label className="check-row">
                <input type="checkbox" checked={form.enabled === true || form.enabled === 'true'} onChange={(e) => setField('enabled')(e.target.checked)} disabled={formBusy} />
                Schedule is active and will run at its next due time.
              </label>
            </Field>
            <div className="row-end">
              <button type="button" className="btn-ghost" onClick={closeForm} disabled={formBusy}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={formBusy || !form.saved_report}>
                {formBusy ? 'Saving…' : (editing ? 'Save changes' : 'Create schedule')}
              </button>
            </div>
          </form>
        </Modal>
      )}

      <div className="filter-bar" role="search">
        <input
          className="input grow" value={f.q} onChange={(e) => applyFilters({ q: e.target.value })}
          placeholder="Search report name…" aria-label="Search scheduled reports"
        />
        <select className="input" value={f.schedule} onChange={(e) => applyFilters({ schedule: e.target.value })} aria-label="Filter by schedule">
          <option value="">All schedules</option>
          {SCHEDULES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select className="input" value={f.format} onChange={(e) => applyFilters({ format: e.target.value })} aria-label="Filter by format">
          <option value="">All formats</option>
          {FORMATS.map((fmt) => <option key={fmt.value} value={fmt.value}>{fmt.label}</option>)}
        </select>
        <select className="input" value={f.enabled} onChange={(e) => applyFilters({ enabled: e.target.value })} aria-label="Filter by enabled">
          <option value="">All</option>
          <option value="true">Enabled</option>
          <option value="false">Disabled</option>
        </select>
        {(f.q || f.schedule || f.format || f.enabled) && (
          <button type="button" className="btn-ghost" onClick={() => setF({ q: '', schedule: '', format: '', enabled: '' })}>Clear filters</button>
        )}
      </div>

      <div className="panel">
        {loading ? <div className="panel-pad"><div className="muted">Loading…</div></div>
          : listError ? <div className="panel-pad"><div className="error-summary" role="alert">{listError} <button type="button" className="btn-small" onClick={() => loadUrl(buildUrl())}>Retry</button></div></div>
          : count === 0 ? <EmptyState title="No scheduled reports yet." hint="Create your first schedule with + New schedule." />
          : (<>
            <TableControls tableVisible={srTableVisible} onToggleTable={toggleSrTable} columns={SR_COLUMNS} visible={visibleSrColumns} onToggleColumn={toggleSrColumn} onReset={resetSrColumns} />
            {srTableVisible ? (
              <DataTable
                columns={srColumns}
                rows={items}
                keyOf={(r) => r.id}
                sort={sort}
                onSort={changeSort}
                emptyTitle="No schedules match."
                emptyHint="Adjust the filters or create a new schedule."
              />
            ) : (
              <p className="muted">Table hidden.</p>
            )}
            <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />
          </>)}
      </div>

      {historyFor && (
        <Modal title="Execution history" onClose={closeHistory} size="wide">
          <div className="panel-pad">
            {historyLoading ? <div className="muted">Loading history…</div>
              : history.length === 0 ? <EmptyState title="No runs yet." hint="Executions for this schedule will appear here." />
              : (
                <DataTable
                  columns={[
                    { key: 'status', label: 'Status', render: (run) => run.status === 'failed' ? <Badge kind="status" value="reopened" label="Failed" /> : (run.status === 'succeeded' ? <Badge kind="status" value="resolved" label="Succeeded" /> : <span>{run.status}</span>) },
                    { key: 'started', label: 'Started', render: (run) => run.started_at ? new Date(run.started_at).toLocaleString() : '—' },
                    { key: 'finished', label: 'Finished', render: (run) => run.finished_at ? new Date(run.finished_at).toLocaleString() : '—' },
                    { key: 'recipients', label: 'Recipients', render: (run) => String(run.recipient_count ?? 0) },
                    { key: 'error', label: 'Error', render: (run) => run.error_summary ? <span className="ellipsis" title={run.error_summary}>{run.error_summary}</span> : <span className="cell-muted">—</span> },
                    { key: 'actions', label: 'Actions', thClass: 'cell-actions', render: historyActions },
                  ]}
                  rows={history}
                  keyOf={(run) => run.id}
                  emptyTitle="No runs."
                  emptyHint="No execution history for this schedule."
                />
              )}
          </div>
        </Modal>
      )}

      {delFor && (
        <ConfirmDialog
          title={`Delete schedule "${items.find((r) => r.id === delFor)?.saved_report_name ?? ''}"?`}
          message="Deleting a schedule stops future deliveries. Execution history is kept."
          confirmLabel="Delete schedule" danger busy={delBusy}
          onConfirm={() => doDelete(items.find((r) => r.id === delFor))}
          onCancel={() => setDelFor(null)}
        />
      )}
    </div>
  );
}

export default ScheduledReports;
