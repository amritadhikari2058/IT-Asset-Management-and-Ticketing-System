import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { useApi } from '../../services/api-context';
import { Table, TableRow, TableCell, TableHead, TableBody, Pagination, EmptyState, LoadingState, ErrorState } from '../../components';
import { canManageChanges } from '../../components/changes/access';

/** Change List — connects to backend ChangeRequestViewSet at /api/changes/ */
export function ChangeList() {
  const auth = useAuth();
  const { request, loading, error } = useApi();
  const [items] = useState([]);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [filter] = useState('');
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    setLoaded(false);
    try {
      const _resp = await request('GET', `/api/changes/?page=${page}&page_size=${pageSize}&filter=${filter}`); // eslint-disable-line react-hooks/exhaustive-deps
      setLoaded(true);
    } catch {
      setError('Failed to load changes.');
    } finally {
      setLoaded(true);
    }
  }, [request, page, pageSize, filter]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  if (!canManageChanges(auth)) {
    return (
      <div>
        <h3>Changes</h3>
        <p>Access denied. Change management requires appropriate permissions.</p>
      </div>
    );
  }

  if (loading || !loaded) {
    return <LoadingState title="Changes" />;
  }

  if (error) {
    return <ErrorState title="Changes" message={error} onRetry={load} />;
  }

  if (items.length === 0) {
    return (
      <EmptyState title="No Changes">
        <p>No change requests found. Use the create action to add a new change.</p>
      </EmptyState>
    );
  }

  return (
    <div>
      <Table title="Change Requests" aid="changes-table">
        <TableHead>
          <TableRow>
            <TableCell>ID</TableCell>
            <TableCell>Title</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Priority</TableCell>
            <TableCell>Requested</TableCell>
            <TableCell className="actions">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.id}>
              <TableCell>{item.id}</TableCell>
              <TableCell>{item.summary || item.title}</TableCell>
              <TableCell>{item.status}</TableCell>
              <TableCell>{item.priority}</TableCell>
              <TableCell>{item.start_date}</TableCell>
              <TableCell className="actions">
                <a href={`/#/changes/${item.id}`}>Detail</a>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Pagination
        current={page}
        total={items.length > 0 ? items[0].pagination?.count : 0}
        onChange={setPage}
      />
    </div>
  );
}