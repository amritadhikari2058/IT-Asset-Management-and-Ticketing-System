import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { useApi } from '../../services/api-context';
import { Table, TableRow, TableCell, TableHead, TableBody, Pagination, EmptyState, LoadingState, ErrorState } from '../../components';
import { canViewCMDB } from '../../components/cmdb/access';

/** CMDB Item List — connects to backend ConfigurationItemViewSet at /api/cmdb/ */
export function CmdbItemList() {
  const auth = useAuth();
  const { request, loading, error } = useApi();
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [filter] = useState('');

  const load = useCallback(async () => {
    try {
      const resp = await request('GET', `/api/cmdb/items/?page=${page}&page_size=${pageSize}&filter=${filter}`); // eslint-disable-line react-hooks/exhaustive-deps
      setItems(resp.data.results ?? resp.data);
    } catch {
      setError('Failed to load CMDB items.');
    }
  }, [request, page, pageSize, filter]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  if (!canViewCMDB(auth)) {
    return (
      <div>
        <h3>CMDB</h3>
        <p>CMDB access requires appropriate permissions.</p>
      </div>
    );
  }

  if (loading) {
    return <LoadingState title="CMDB" />;
  }

  if (error) {
    return <ErrorState title="CMDB" message={error} onRetry={load} />;
  }

  if (items.length === 0) {
    return (
      <EmptyState title="No CMDB Items">
        <p>No configuration items found. Check your CMDB configuration.</p>
      </EmptyState>
    );
  }

  return (
    <div>
      <Table title="Configuration Items" aid="cmdb-items-table">
        <TableHead>
          <TableRow>
            <TableCell>ID</TableCell>
            <TableCell>Name</TableCell>
            <TableCell>Type</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Last Updated</TableCell>
            <TableCell className="actions">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.id}>
              <TableCell>{item.id}</TableCell>
              <TableCell>{item.name}</TableCell>
              <TableCell>{item.configuration_item_type}</TableCell>
              <TableCell>{item.status}</TableCell>
              <TableCell>{item.last_updated}</TableCell>
              <TableCell className="actions">
                <a href={`/#/cmdb/${item.id}`}>Detail</a>
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