import { formatDateTime, HISTORY_EVENT_LABELS, historyDetailText, historyTransition } from '../../shared/licensing-utils';

/**
 * Read-only license history table shared by the allocation history modal and
 * the agreement detail page. Both backends return a plain array of
 * LicenseHistorySerializer rows (newest first, capped at 100).
 */
export function HistoryList({ items, loading, error, emptyText = 'No history recorded.' }) {
  if (loading) return <p className="muted" role="status">Loading history…</p>;
  if (error) return <div className="alert alert-danger" role="alert">{error}</div>;
  if (!items || items.length === 0) return <p className="text-muted" role="status">{emptyText}</p>;
  return (
    <div className="table-wrap">
      <table className="table table-sm grid license-history">
        <thead>
          <tr>
            <th>When</th>
            <th>Event</th>
            <th>Status change</th>
            <th>Actor</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {items.map((entry) => (
            <tr key={entry.id}>
              <td>{formatDateTime(entry.created_at)}</td>
              <td>{HISTORY_EVENT_LABELS[entry.event_type] || entry.event_type}</td>
              <td>{historyTransition(entry)}</td>
              <td>{entry.actor_email || 'System'}</td>
              <td>{historyDetailText(entry.detail) || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default HistoryList;

