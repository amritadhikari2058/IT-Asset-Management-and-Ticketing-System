import { useCallback, useEffect, useState } from 'react';
import api from '../../api';
import { safeResults, procurementErrorText } from '../../shared/procurement-utils';

function Table({ columns, rows, empty = 'No records.' }) {
  if (!rows?.length) return <div className="empty-state"><div className="empty-title">{empty}</div></div>;
  return <div className="table-wrap"><table className="table"><thead><tr>{columns.map(c => <th key={c.key || c.label}>{c.label}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={row.id ?? row.vendor_id ?? i}>{columns.map(c => <td key={c.key || c.label}>{typeof c.render === 'function' ? c.render(row) : row[c.key]}</td>)}</tr>)}</tbody></table></div>;
}

function valueOrDash(value) {
  return value === null || value === undefined || value === '' ? '—' : value;
}

export function ProcurementVendorPerformance() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true); setError('');
    return api.get('/procurement/reports/vendor-performance/')
      .then(r => setRows(safeResults(r.data)))
      .catch(e => setError(procurementErrorText(e, 'Failed to load vendor performance.')))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  if (loading) return <p className="page-loading" role="status">Loading vendor performance…</p>;
  if (error) return <div role="alert" className="error">{error} <button className="btn" onClick={load}>Retry</button></div>;
  return (
    <div>
      <h1>Vendor Performance</h1>
      <p className="small">Operational metrics are shown separately. No composite vendor score is calculated.</p>
      <Table
        columns={[
          { label: 'Vendor', key: 'vendor_name' },
          { label: 'POs', render: r => valueOrDash(r.purchase_orders) },
          { label: 'On-Time Delivery %', render: r => valueOrDash(r.on_time_delivery_rate) },
          { label: 'Complete Delivery %', render: r => valueOrDash(r.complete_delivery_rate) },
          { label: 'Rejected Qty %', render: r => valueOrDash(r.rejected_quantity_rate) },
          { label: 'Damaged Qty %', render: r => valueOrDash(r.damaged_quantity_rate) },
          { label: 'Invoice Match %', render: r => valueOrDash(r.invoice_match_rate) },
          { label: 'Avg Price Variance', render: r => valueOrDash(r.average_price_variance) },
          { label: 'Open Returns', render: r => valueOrDash(r.open_returns) },
          { label: 'Sample', render: r => r.sample_note || '—' },
        ]}
        rows={rows}
        empty="No vendor performance data."
      />
    </div>
  );
}

export default ProcurementVendorPerformance;

