import { useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { DataTable, EmptyState, Field, Input, LoadingRows, PageHeader, Pager, Select } from './components';
import { parseApiError } from './api-utils';
import {
  DRIFT_SEVERITY_LABELS,
  DRIFT_STATUS_LABELS,
  DRIFT_TYPE_LABELS,
  formatDateTime,
  safeResults,
} from './cmdb-utils';
import { CMDB_API_CONTRACT, CMDB_PERMISSIONS } from './cmdb';

const DEFAULT_FILTERS = { status: 'open', severity: '', type: '', ci: '', search: '', date_from: '', date_to: '' };

function stringifyValue(v) {
  if (v == null || v === '') return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export function DriftFindingsPage() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [rows, setRows] = useState([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [applied, setApplied] = useState(DEFAULT_FILTERS);
  const pageSize = 25;

  const canView = CMDB_PERMISSIONS.canViewDrift(role);
  const canManage = CMDB_PERMISSIONS.canAcknowledgeDrift(role) || CMDB_PERMISSIONS.canResolveDrift(role);

  const load = async () => {
    if (!canView) return;
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      params.set('page', String(page));
      if (applied.status) params.set('status', applied.status);
      if (applied.severity) params.set('severity', applied.severity);
      if (applied.type) params.set('type', applied.type);
      if (applied.ci) params.set('ci', applied.ci);
      if (applied.search) params.set('search', applied.search);
      if (applied.date_from) params.set('date_from', applied.date_from);
      if (applied.date_to) params.set('date_to', applied.date_to);
      const res = await api.get(`${CMDB_API_CONTRACT.driftList.endpoint}?${params.toString()}`);
      const data = res.data;
      if (Array.isArray(data)) {
        setRows(data);
        setCount(data.length);
      } else {
        setRows(safeResults(data?.results));
        setCount(data?.count ?? safeResults(data?.results).length);
      }
    } catch (e) {
      setError(parseApiError(e).global || 'Could not load drift findings.');
      setRows([]);
      setCount(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [applied, page]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setPage(1); }, [applied]);

  const runAction = async (row, action) => {
    const needsNote = ['resolve', 'accept', 'false-positive'].includes(action);
    const note = needsNote ? window.prompt(`Enter a note for ${action.replace('-', ' ')} (required):`, '') : '';
    if (needsNote && !String(note || '').trim()) return;
    setBusyId(row.id);
    setError('');
    setMsg('');
    try {
      await api.post(`/cmdb/drift/${row.id}/${action}/`, note ? { note, resolution_note: note } : {});
      setMsg(`Drift finding ${row.id} ${action.replace('-', ' ')} completed.`);
      await load();
    } catch (e) {
      setError(parseApiError(e).global || `Could not ${action.replace('-', ' ')} drift finding.`);
    } finally {
      setBusyId(null);
    }
  };

  if (role === 'employee') {
    return <div className="error-summary" role="alert">Employees have no CMDB drift access.</div>;
  }

  const totalPages = Math.max(1, Math.ceil((count || 0) / pageSize));

  return (
    <div>
      <PageHeader title="Drift Findings" sub="Review configuration drift, filter by severity/status/source, and take permitted remediation actions" />

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <form onSubmit={(e) => { e.preventDefault(); setApplied({ ...filters }); }} noValidate>
          <div className="split-grid split-4">
            <Field label="Status">
              <Select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}>
                <option value="">All statuses</option>
                {Object.entries(DRIFT_STATUS_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </Select>
            </Field>
            <Field label="Severity">
              <Select value={filters.severity} onChange={(e) => setFilters((f) => ({ ...f, severity: e.target.value }))}>
                <option value="">All severities</option>
                {Object.entries(DRIFT_SEVERITY_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </Select>
            </Field>
            <Field label="Finding Type">
              <Select value={filters.type} onChange={(e) => setFilters((f) => ({ ...f, type: e.target.value }))}>
                <option value="">All types</option>
                {Object.entries(DRIFT_TYPE_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </Select>
            </Field>
            <Field label="CI ID">
              <Input value={filters.ci} onChange={(e) => setFilters((f) => ({ ...f, ci: e.target.value }))} placeholder="Configuration item id" />
            </Field>
          </div>
          <div className="split-grid split-4" style={{ marginTop: 12 }}>
            <Field label="Search">
              <Input value={filters.search} onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))} placeholder="Field, CI name/number…" />
            </Field>
            <Field label="Detected From">
              <Input type="date" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
            </Field>
            <Field label="Detected To">
              <Input type="date" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
            </Field>
            <div className="row-end" style={{ alignItems: 'flex-end' }}>
              <button type="submit" className="btn-primary">Apply</button>
              <button type="button" className="btn-small" onClick={() => { setFilters(DEFAULT_FILTERS); setApplied(DEFAULT_FILTERS); }}>Reset</button>
            </div>
          </div>
        </form>
        <p className="muted" style={{ marginBottom: 0 }}>Actions use backend permissions and immutable finding records. Resolve/accept/false-positive require a note; navigation links go to the affected CI.</p>
      </div>

      {error && <div className="error-summary" role="alert">{error}</div>}
      {msg && <div className="success-banner" role="status">{msg}</div>}

      <div className="panel panel-pad">
        {loading ? (
          <LoadingRows n={6} />
        ) : rows.length === 0 ? (
          <EmptyState title="No drift findings found." hint="Adjust filters or run baseline comparisons to detect drift." />
        ) : (
          <>
            <p className="muted" style={{ marginTop: 0 }}>Showing {rows.length} of {count} finding(s), page {page} of {totalPages}.</p>
            <DataTable
              columns={[
                { key: 'id', label: 'ID', render: (row) => row.id },
                {
                  key: 'ci',
                  label: 'Affected CI',
                  render: (row) => {
                    const cid = row.configuration_item || row.ci || row.ci_id;
                    const label = row.ci_number ? `${row.ci_number}${row.ci_name ? ` — ${row.ci_name}` : ''}` : (cid ? `CI #${cid}` : '—');
                    return cid ? <a href={`#/cmdb/items/${cid}`}>{label}</a> : label;
                  },
                },
                { key: 'field_name', label: 'Field', render: (row) => row.field_name || '—' },
                { key: 'expected', label: 'Expected', render: (row) => stringifyValue(row.expected_value) },
                { key: 'actual', label: 'Current', render: (row) => stringifyValue(row.actual_value) },
                { key: 'severity', label: 'Severity', render: (row) => DRIFT_SEVERITY_LABELS[row.severity] || row.severity || '—' },
                { key: 'status', label: 'Status', render: (row) => DRIFT_STATUS_LABELS[row.status] || row.status || '—' },
                { key: 'finding_type', label: 'Type', render: (row) => DRIFT_TYPE_LABELS[row.finding_type] || row.finding_type || '—' },
                { key: 'source', label: 'Source', render: (row) => row.source || '—' },
                { key: 'detected_at', label: 'Detected', render: (row) => formatDateTime(row.detected_at || row.created_at) },
                { key: 'resolution_note', label: 'Resolution Note', render: (row) => row.resolution_note || '—' },
                {
                  key: 'actions',
                  label: 'Actions',
                  render: (row) => (
                    <div className="table-actions">
                      {(row.configuration_item || row.ci || row.ci_id) && <a className="btn-small" href={`#/cmdb/items/${row.configuration_item || row.ci || row.ci_id}`}>Open CI</a>}
                      {canManage && row.status === 'open' && <button type="button" className="btn-small" disabled={busyId === row.id} onClick={() => runAction(row, 'acknowledge')}>Acknowledge</button>}
                      {canManage && (row.status === 'open' || row.status === 'acknowledged') && <button type="button" className="btn-small" disabled={busyId === row.id} onClick={() => runAction(row, 'resolve')}>Resolve</button>}
                      {canManage && row.status !== 'accepted' && <button type="button" className="btn-small" disabled={busyId === row.id} onClick={() => runAction(row, 'accept')}>Accept</button>}
                      {canManage && row.status !== 'false_positive' && <button type="button" className="btn-small" disabled={busyId === row.id} onClick={() => runAction(row, 'false-positive')}>False Positive</button>}
                    </div>
                  ),
                },
              ]}
              rows={rows}
              keyOf={(row) => row.id}
              emptyTitle="No drift findings."
              emptyHint="No findings match filters."
            />
            <Pager page={page} total={totalPages} count={count} pageSize={pageSize} onPage={setPage} />
          </>
        )}
      </div>
    </div>
  );
}
