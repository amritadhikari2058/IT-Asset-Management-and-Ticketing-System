import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { PageHeader } from '../../components';
import { listSources, parseMonitoringError } from '../../services/monitoring/monitoring-api';
import {
  AccessDeniedPanel, ErrorPanel, KpiCard, LoadingPanel, SourceStatusBadge,
  SourceHealthBadge,
} from '../../components/monitoring/MonitoringUI';
import { canAccessMonitoring } from '../../components/monitoring/access';

/** Monitoring Overview — operations KPI dashboard. */
export function MonitoringOverview() {
  const auth = useAuth();
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const s = await listSources();
      const items = Array.isArray(s) ? s : (s?.results ?? []);
      setSources(items);
    } catch (e) {
      setError(parseMonitoringError(e).global || 'Failed to load monitoring sources.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (!canAccessMonitoring(auth)) {
    return (
      <div>
        <PageHeader title="Monitoring Operations" sub="Alert, source and automation overview." />
        <AccessDeniedPanel reason="access" />
      </div>
    );
  }

  if (loading) {
    return (
      <div>
        <PageHeader title="Monitoring Operations" sub="Alert, source and automation overview." />
        <LoadingPanel label="Loading monitoring overview…" />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <PageHeader title="Monitoring Operations" sub="Alert, source and automation overview." />
        <ErrorPanel message={error} onRetry={load} />
      </div>
    );
  }

  const online = sources.filter((s) => s.is_active && s.health_status !== 'unhealthy').length;
  const offline = sources.filter((s) => !s.is_active || s.health_status === 'unhealthy').length;

  return (
    <div>
      <PageHeader
        title="Monitoring Operations"
        sub="Alert, source and automation overview."
        actions={<button type="button" className="btn-secondary" onClick={load}>Refresh</button>}
      />

      <div className="panel panel-pad">
        <div className="error-summary" role="alert">
          Aggregate alert/automation KPIs are unavailable: the dashboard API
          (GET /monitoring/dashboard/) is not implemented on the backend and is
          not called. Source health below is loaded from the live Sources API.
        </div>
      </div>

      <div className="kpi-grid" aria-label="Source health KPIs">
        <KpiCard title="Sources total" tone="blue" value={sources.length} />
        <KpiCard title="Sources online" tone="green" value={online} sub={`${sources.length} total`} />
        <KpiCard title="Sources offline" tone="red" value={offline} sub={`${sources.length} total`} />
        <KpiCard title="Active alerts" tone="gray" value="unavailable" sub="dashboard API not implemented" />
        <KpiCard title="Critical / High alerts" tone="gray" value="unavailable" sub="dashboard API not implemented" />
        <KpiCard title="Recovered alerts" tone="gray" value="unavailable" sub="dashboard API not implemented" />
        <KpiCard title="Acknowledged alerts" tone="gray" value="unavailable" sub="dashboard API not implemented" />
        <KpiCard title="Suppressed alerts" tone="gray" value="unavailable" sub="dashboard API not implemented" />
        <KpiCard title="Automation failures" tone="gray" value="unavailable" sub="dashboard API not implemented" />
        <KpiCard title="Retry pending alerts" tone="gray" value="unavailable" sub="dashboard API not implemented" />
      </div>

      <div className="panel">
        <div className="panel-head"><h3>Source health</h3></div>
        <div className="panel-pad">
          {sources.length === 0 ? (
            <div className="empty-state">
              <div className="empty-title">No monitoring sources configured.</div>
              <div className="small">Source creation requires backend support (POST /monitoring/sources/).</div>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Source</th><th>Code</th><th>Status</th><th>Health</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map((s) => (
                    <tr key={s.id}>
                      <td className="row-title">{s.name}</td>
                      <td className="cell-muted small">{s.code}</td>
                      <td><SourceStatusBadge value={s.status} /></td>
                      <td><SourceHealthBadge value={s.health_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default MonitoringOverview;
