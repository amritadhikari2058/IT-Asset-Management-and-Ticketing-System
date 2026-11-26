/*
 * Change List - displays paginated, filterable change list
 * Route: #/changes
 */

import React, { useEffect, useState } from 'react';
import { Pager, EmptyState, Badge, PageSizeSelector } from '../../components';
import { useAuth } from '../../auth';
import { fetchPage, parseApiError, statusBadgeVariant, priorityBadgeVariant, riskBadgeVariant, buildChangeListUrl, formatDate, STATUS_LABELS, CHANGE_TYPE_LABELS, CATEGORY_LABELS, PRIORITY_LABELS, RISK_LEVEL_LABELS } from '../../shared/changes-utils';

const CHANGE_LIST_API = '/changes/';

export function ChangeList({ initialFilters = {} }) {
  const { isStaff, role } = useAuth();
  // Page-size preference persisted in localStorage; fall back to DRF default 20.
  const [pageSize, setPageSize] = useState(() => {
    if (typeof window === 'undefined') return 20;
    try {
      const saved = window.localStorage.getItem('itdesk.pageSize');
      const n = Number(saved);
      return saved && Number.isFinite(n) && n > 0 && n <= 100 ? n : 20;
    } catch {
      return 20;
    }
  });
  const [changes, setChanges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters] = useState({ ...initialFilters });
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);

  // Persist page-size preference without unnecessary writes
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      if (window.localStorage.getItem('itdesk.pageSize') !== String(pageSize)) {
        window.localStorage.setItem('itdesk.pageSize', String(pageSize));
      }
    } catch {
      // ignore storage failures
    }
  }, [pageSize]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); // eslint-disable-line react/set-state-in-effect
    setError(null); // eslint-disable-line react/set-state-in-effect
    const run = async () => {
      try {
        const url = buildChangeListUrl(filters, pageSize, page);
        const fullUrl = url ? `${CHANGE_LIST_API}${url}` : CHANGE_LIST_API;
        const response = await fetchPage(fullUrl);
        if (cancelled) return;
        setChanges(response.items ?? []);
      } catch (e) {
        if (cancelled) return;
        setError(parseApiError(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [filters, pageSize, page, refreshKey]);

  if (isStaff === false || role === 'employee') {
    return null;
  }

  return (
    <div>
      {loading ? (
        <div className="mt-3"><p>Loading changes…</p></div>
      ) : error ? (
        <div className="mt-3">
          <p className="text-danger">Error: {error.global ?? 'Unknown error'}</p>
          <button className="btn-small btn-ghost mt-1" onClick={() => setRefreshKey(prev => prev + 1)}>Retry</button>
        </div>
      ) : changes.length === 0 ? (
        <EmptyState
          icon="info-circle"
          title="No Changes Found"
          text="No changes match the current filters. Adjust the filters above to see changes."
        />
      ) : (
        <table className="table">
          <tbody>
            {changes.map((change) => (
              <tr key={change.id} className="align-middle">
                <td><strong>{change.change_number}</strong></td>
                <td>
                  <a href={`#/changes/${change.id}`} className="text-primary">
                    {change.title}
                  </a>
                </td>
                <td>
                  <Badge kind="status" value={change.change_type || 'standard'}>
                    {CHANGE_TYPE_LABELS[change.change_type] || change.change_type}
                  </Badge>
                </td>
                <td>
                  <Badge kind="status" value={change.category || 'other'}>
                    {CATEGORY_LABELS[change.category] || change.category}
                  </Badge>
                </td>
                <td>
                  <Badge kind={statusBadgeVariant(change.status)}>
                    {STATUS_LABELS[change.status] || change.status}
                  </Badge>
                </td>
                <td>
                  <Badge kind={riskBadgeVariant(change.risk_level)}>
                    {RISK_LEVEL_LABELS[change.risk_level] || change.risk_level}
                  </Badge>
                </td>
                <td>
                  <Badge kind={priorityBadgeVariant(change.priority)}>
                    {PRIORITY_LABELS[change.priority] || change.priority}
                  </Badge>
                </td>
                <td>
                  {change.change_owner_email || change.change_owner?.email || change.change_owner?.employee_id || (
                    change.change_owner ? <span>{change.change_owner}</span> : <span>Unassigned</span>
                  )}
                </td>
                <td>
                  {change.implementation_lead_email || change.implementation_lead?.email || change.implementation_lead?.employee_id || (
                    change.implementation_lead ? <span>{change.implementation_lead}</span> : <span>Unassigned</span>
                  )}
                </td>
                <td>{formatDate(change.planned_start)}</td>
                <td>{formatDate(change.planned_end)}</td>
                <td>
                  {change.conflicts_count !== undefined ? (
                    <Badge kind="low">{change.conflicts_count}</Badge>
                  ) : (
                    '-'
                  )}
                </td>
                <td>
                  {isStaff ? (
                    <div className="btn-group btn-group-sm">
                      <a href={`#/changes/${change.id}`} className="btn btn-link text-primary" title="View">View</a>
                    </div>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {changes.length > 0 && (
        <>
          <PageSizeSelector value={pageSize} onChange={setPageSize} />
          <Pager
            count={changes.length}
            page={page}
            pageSize={pageSize}
            onPageChange={(newPage) => setPage(newPage)}
            onPageSizeChange={(newSize) => {
              setPageSize(newSize);
              setPage(1);
              setRefreshKey(prev => prev + 1);
            }}
          />
        </>
      )}
    </div>
  );
}
