import { useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { PageHeader } from '../../components';
import { AccessDeniedPanel } from '../../components/monitoring/MonitoringUI';
import { canAdministerMonitoring } from '../../components/monitoring/access';
import { listAlerts, parseMonitoringError } from '../../services/monitoring/monitoring-api';

const PAGE_SIZE = 20;

export function AlertList() {
  const auth = useAuth();
  const canAdminister = canAdministerMonitoring(auth);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!canAdminister) {
      setLoading(false);
      return undefined;
    }

    let cancelled = false;

    async function load() {
      setLoading(true);
      setError('');

      try {
        const result = await listAlerts({ page, page_size: PAGE_SIZE });
        if (!cancelled) setData(result);
      } catch (requestError) {
        if (!cancelled) {
          setError(
            parseMonitoringError(requestError).global ||
            'Failed to load monitoring alerts.'
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [page, refreshKey, canAdminister]);

  if (!canAdminister) {
    return (
      <div>
        <PageHeader title="Alerts" sub="Correlated operational alerts." />
        <AccessDeniedPanel reason="access" />
      </div>
    );
  }

  const alerts = Array.isArray(data?.results) ? data.results : [];
  const count = Number(data?.count) || 0;

  return (
    <div>
      <PageHeader
        title="Alerts"
        sub="Correlated operational alerts from monitoring sources."
      />

      {loading ? (
        <div className="panel panel-pad" role="status" aria-label="Loading alerts">
          <span className="spinner" aria-hidden="true" /> Loading alerts…
        </div>
      ) : error ? (
        <div className="panel panel-pad">
          <div className="error-summary" role="alert">{error}</div>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setRefreshKey((value) => value + 1)}
          >
            Retry
          </button>
        </div>
      ) : alerts.length === 0 ? (
        <div className="panel panel-pad" role="status">
          <div className="empty-title">No monitoring alerts</div>
          <p className="small cell-muted">
            No alerts were found on this page.
          </p>
        </div>
      ) : (
        <>
          <div className="panel">
            <div className="panel-head">
              <h3>Monitoring alerts</h3>
              <span className="small cell-muted">{count} total</span>
            </div>
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Alert</th>
                    <th>Title</th>
                    <th>Severity</th>
                    <th>Status</th>
                    <th>Source</th>
                    <th>Events</th>
                    <th>Automation</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.map((alert) => (
                    <tr key={alert.id}>
                      <td>
                        <a href={`/#/monitoring/alerts/${alert.id}`}>
                          {alert.alert_number || `#${alert.id}`}
                        </a>
                      </td>
                      <td>{alert.title || '—'}</td>
                      <td>{alert.severity || '—'}</td>
                      <td>{alert.status || '—'}</td>
                      <td>{alert.source_name || '—'}</td>
                      <td>{alert.event_count ?? 0}</td>
                      <td>
                        <div>{alert.automation_state || '—'}</div>
                        {alert.automation_retry_count != null && (
                          <div className="small cell-muted">
                            Retries: {alert.automation_retry_count}
                          </div>
                        )}
                        {alert.automation_error_code && (
                          <div className="small cell-muted">
                            Error: {alert.automation_error_code}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="row-gap" style={{ justifyContent: 'space-between', marginTop: 12 }}>
            <span className="small cell-muted">
              Page {page} · {count} alerts
            </span>
            <div className="row-gap">
              <button
                type="button"
                className="btn-secondary"
                disabled={!data?.previous || loading}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn-secondary"
                disabled={!data?.next || loading}
                onClick={() => setPage((value) => value + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default AlertList;