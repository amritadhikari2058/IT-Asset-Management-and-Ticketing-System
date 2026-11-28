import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { PageHeader, LoadingRows } from '../../components';
import api from '../../api';

function getErrorMessage(error) {
  const data = error?.response?.data;
  if (typeof data?.detail === 'string') return data.detail;
  if (typeof data?.error === 'string') return data.error;
  return 'Could not load the data-integrity report. Please try again.';
}

function IssueTable({ issues }) {
  if (!issues.length) {
    return (
      <div className="empty-state" role="status">
        No integrity issues were found in the checked assets.
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Area</th>
            <th scope="col">Issue</th>
            <th scope="col">Object</th>
            <th scope="col">Details</th>
            <th scope="col">Suggested action</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, index) => (
            <tr key={`${issue.code}-${issue.object_id ?? issue.object ?? index}`}>
              <td>{issue.area || '—'}</td>
              <td>
                <code>{issue.code || 'unknown_issue'}</code>
              </td>
              <td>
                {issue.object || '—'}
                {issue.object_id != null && (
                  <small className="muted">ID: {issue.object_id}</small>
                )}
              </td>
              <td>{issue.detail || 'No additional details provided.'}</td>
              <td>{issue.suggested_fix || 'Review this record manually.'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DataIntegrity() {
  const { isAdmin } = useAuth();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadReport = useCallback(async () => {
    setLoading(true);
    setError('');

    try {
      const response = await api.get('/common/data-integrity/');
      const data = response?.data ?? {};
      setReport({
        issues: Array.isArray(data.issues) ? data.issues : [],
        counts: data.counts ?? {},
        note: data.note ?? '',
      });
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) loadReport();
  }, [isAdmin, loadReport]);

  if (!isAdmin) {
    return (
      <div>
        <PageHeader title="Data integrity" />
        <div className="error-summary" role="alert">
          System administrators only.
        </div>
      </div>
    );
  }

  const counts = report?.counts ?? {};

  return (
    <div>
      <PageHeader
        title="Data integrity"
        sub="Read-only checks for inconsistencies in asset and assignment records."
        actions={
          <button
            type="button"
            className="btn"
            onClick={loadReport}
            disabled={loading}
          >
            {loading ? 'Refreshing…' : 'Refresh report'}
          </button>
        }
      />

      <div className="panel panel-pad">
        <div className="stats-grid">
          <div className="stat-card">
            <span className="stat-label">Issues found</span>
            <strong>{report ? (counts.issues ?? report.issues.length) : '—'}</strong>
          </div>
          <div className="stat-card">
            <span className="stat-label">Assets checked</span>
            <strong>{report ? (counts.assets_checked ?? '—') : '—'}</strong>
          </div>
        </div>
        <p className="muted">
          The report checks up to 500 assets per run. Review each finding and
          make any correction through the appropriate asset or assignment
          workflow.
        </p>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Integrity findings</h2>
          {report && (
            <span className="muted">
              {report.issues.length} finding{report.issues.length === 1 ? '' : 's'}
            </span>
          )}
        </div>

        {loading ? (
          <div className="panel-pad">
            <LoadingRows n={5} />
          </div>
        ) : error ? (
          <div className="panel-pad">
            <div className="error-summary" role="alert">
              {error}
              <button
                type="button"
                className="btn-small"
                onClick={loadReport}
              >
                Retry
              </button>
            </div>
          </div>
        ) : report ? (
          <IssueTable issues={report.issues} />
        ) : (
          <div className="panel-pad">
            The report has not been loaded yet.
          </div>
        )}
      </div>

      <div className="notice notice-info" role="note">
        {report?.note
          || 'Read-only report. Repairs are explicit and must be performed by an authorized person.'}
        {' '}This page does not modify asset or assignment records.
      </div>
    </div>
  );
}