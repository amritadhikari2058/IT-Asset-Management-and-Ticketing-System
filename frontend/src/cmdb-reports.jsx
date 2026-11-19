import { useEffect, useMemo, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { DataTable, EmptyState, Field, Input, LoadingRows, PageHeader, Select } from './components';
import { CMDB_API_CONTRACT, CMDB_PERMISSIONS, buildCIListUrl, formatDateTime, safeResults } from './cmdb-utils';

const REPORT_KINDS = [
  ['coverage', 'Coverage / Distribution'],
  ['verification_age', 'Verification Age / Coverage'],
  ['orphans', 'Orphan CIs'],
  ['ownership_gaps', 'Ownership Gaps'],
  ['relationship_coverage', 'Relationship Coverage'],
  ['drift', 'Drift Summary'],
  ['critical_deps', 'Critical Dependencies / SPOFs'],
  ['asset_sync', 'Asset Sync'],
  ['software_sync', 'Software Sync'],
];

export function CmdbReports() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [kind, setKind] = useState('coverage');
  const [filters, setFilters] = useState({ date_from: '', date_to: '', ci_type: '', status: '', criticality: '', environment: '', department: '' });
  const [report, setReport] = useState(null);
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const canView = CMDB_PERMISSIONS.canViewReports(role);

  useEffect(() => {
    let cancelled = false;
    api.get('/cmdb/types/').then((r) => { if (!cancelled) setTypes(safeResults(r.data?.results ?? r.data)); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const load = async () => {
    if (!canView) return;
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ kind });
      Object.entries(filters).forEach(([k, v]) => { if (v !== '' && v != null) params.set(k, String(v)); });
      const res = await api.get(`${CMDB_API_CONTRACT.reports.endpoint}?${params.toString()}`);
      setReport(res.data || null);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load CMDB report.');
      setReport(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const summaryEntries = useMemo(() => Object.entries(report?.summary || {}), [report]);
  const rows = safeResults(report?.rows);
  const columns = useMemo(() => {
    const cols = safeResults(report?.columns);
    if (cols.length) {
      return cols.map((c) => ({
        key: c.key || c.field || c.label,
        label: c.label || c.key || c.field || 'Value',
        render: (row) => {
          const val = row[c.key || c.field];
          if (val == null || val === '') return '—';
          return typeof val === 'object' ? JSON.stringify(val) : String(val);
        },
      }));
    }
    if (!rows.length) return [];
    return Object.keys(rows[0]).slice(0, 8).map((k) => ({
      key: k,
      label: k.replace(/_/g, ' '),
      render: (row) => {
        const val = row[k];
        if (val == null || val === '') return '—';
        if (typeof val === 'object') return JSON.stringify(val);
        return String(val);
      },
    }));
  }, [report, rows]);

  const quickLinks = useMemo(() => {
    const links = [];
    links.push({ href: '#/cmdb/items', label: 'All Configuration Items' });
    if (filters.status) links.push({ href: buildCIListUrl({ status: filters.status }), label: `CIs with status ${filters.status}` });
    if (filters.criticality) links.push({ href: buildCIListUrl({ criticality: filters.criticality }), label: `CIs with criticality ${filters.criticality}` });
    if (filters.ci_type) links.push({ href: buildCIListUrl({ ci_type: filters.ci_type }), label: 'CIs of selected type' });
    if (kind === 'drift') links.push({ href: '#/cmdb/drift', label: 'Drift Findings' });
    if (kind === 'verification_age') links.push({ href: '#/cmdb/verification', label: 'Verification Queue' });
    if (kind === 'relationship_coverage' || kind === 'orphans') links.push({ href: '#/cmdb/relationships', label: 'Relationship Browser' });
    return links;
  }, [filters, kind]);

  if (role === 'employee') {
    return <div className="error-summary" role="alert">Employees have no CMDB report access.</div>;
  }

  return (
    <div>
      <PageHeader title="CMDB Reports" sub="Backend-backed configuration, verification, relationship, drift, and sync summaries" />

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <div className="split-grid split-4">
          <Field label="Report Kind">
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              {REPORT_KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </Select>
          </Field>
          <Field label="CI Type">
            <Select value={filters.ci_type} onChange={(e) => setFilters((f) => ({ ...f, ci_type: e.target.value }))}>
              <option value="">All types</option>
              {types.map((t) => <option key={t.id} value={String(t.id)}>{t.name || t.code || `Type #${t.id}`}</option>)}
            </Select>
          </Field>
          <Field label="Status">
            <Input value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))} placeholder="e.g. active" />
          </Field>
          <Field label="Criticality">
            <Input value={filters.criticality} onChange={(e) => setFilters((f) => ({ ...f, criticality: e.target.value }))} placeholder="e.g. critical" />
          </Field>
        </div>
        <div className="split-grid split-4" style={{ marginTop: 12 }}>
          <Field label="Environment">
            <Input value={filters.environment} onChange={(e) => setFilters((f) => ({ ...f, environment: e.target.value }))} placeholder="e.g. production" />
          </Field>
          <Field label="Department ID">
            <Input value={filters.department} onChange={(e) => setFilters((f) => ({ ...f, department: e.target.value }))} placeholder="Department id" />
          </Field>
          <Field label="Date From">
            <Input type="date" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
          </Field>
          <Field label="Date To">
            <Input type="date" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
          </Field>
        </div>
        <div className="row-end" style={{ marginTop: 12 }}>
          <button type="button" className="btn-primary" onClick={load} disabled={loading}>{loading ? 'Loading…' : 'Run Report'}</button>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>Filters are sent to backend report endpoints where supported. If a specific breakdown is not provided by the backend for this kind, the UI shows available authoritative rows/summary only (no fabricated metrics).</p>
      </div>

      {error && <div className="error-summary" role="alert">{error}</div>}

      {loading ? (
        <div className="panel panel-pad"><LoadingRows n={6} /></div>
      ) : !report ? (
        <div className="panel panel-pad"><EmptyState title="No report data." hint="Run a report to view backend-backed CMDB metrics." /></div>
      ) : (
        <>
          <div className="panel panel-pad" style={{ marginBottom: 16 }}>
            <h2 style={{ marginTop: 0 }}>Summary</h2>
            <p className="muted">Kind: <strong>{report.kind || kind}</strong> · Generated: {formatDateTime(report.generated_at) || '—'}</p>
            {summaryEntries.length === 0 ? <p className="muted">No summary metrics returned for this report.</p> : (
              <div className="kpi-grid">
                {summaryEntries.map(([k, v]) => (
                  <div className="kpi" key={k}>
                    <div className="kpi-label">{k.replace(/_/g, ' ')}</div>
                    <div className="kpi-value">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</div>
                  </div>
                ))}
              </div>
            )}
            <div className="table-actions" style={{ marginTop: 12, flexWrap: 'wrap' }}>
              {quickLinks.map((l) => <a key={l.href + l.label} className="btn-small" href={l.href}>{l.label}</a>)}
            </div>
          </div>

          <div className="panel panel-pad">
            <h2 style={{ marginTop: 0 }}>Report Rows</h2>
            {rows.length === 0 ? (
              <EmptyState title="No rows returned." hint="No matching records for this report/filter combination, or this report kind provides summary-only data." />
            ) : (
              <DataTable
                columns={columns}
                rows={rows}
                keyOf={(row, i) => row.id || row.ci_id || row.label || i}
                emptyTitle="No rows."
                emptyHint="No data."
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
