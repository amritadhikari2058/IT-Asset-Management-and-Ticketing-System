import { useCallback, useEffect, useState } from 'react';
import api from './api';
import { safeResults, formatMoney, statusLabel, procurementErrorText } from './procurement-utils';

function Table({ columns, rows, empty = 'No records.' }) {
  if (!rows?.length) return <div className="empty-state"><div className="empty-title">{empty}</div></div>;
  return <div className="table-wrap"><table className="table"><thead><tr>{columns.map(c => <th key={c.key || c.label}>{c.label}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={row.id ?? i}>{columns.map(c => <td key={c.key || c.label}>{typeof c.render === 'function' ? c.render(row) : row[c.key]}</td>)}</tr>)}</tbody></table></div>;
}

export function ProcurementInvoicesPage() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    return api.get('/procurement/supplier-invoices/?page_size=50')
      .then(r => setRows(safeResults(r.data)))
      .catch(e => setError(procurementErrorText(e, 'Failed to load invoices.')))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <p className="page-loading" role="status">Loading invoices…</p>;
  if (error) return <div role="alert" className="error">{error} <button className="btn" onClick={load}>Retry</button></div>;
  return (
    <div>
      <div className="page-header"><h1>Supplier Invoices</h1><a className="btn" href="#/procurement/invoices/new">New Invoice</a></div>
      <Table
        columns={[
          { label: 'Invoice Number', render: r => <a href={`#/procurement/invoices/${r.id}`}>{r.invoice_number}</a> },
          { label: 'Vendor', render: r => r.vendor_name || r.vendor },
          { label: 'Purchase Order', render: r => r.po_number || r.purchase_order },
          { label: 'Invoice Date', key: 'invoice_date' },
          { label: 'Due Date', key: 'due_date' },
          { label: 'Status', render: r => statusLabel(r.status) },
          { label: 'Match Status', render: r => statusLabel(r.latest_match?.overall_status || 'unmatched') },
          { label: 'Payment Status', render: r => statusLabel(r.payment_status) },
          { label: 'Total', render: r => formatMoney(r.grand_total, r.currency) },
          { label: 'Currency', key: 'currency' },
          { label: 'Variance', render: r => formatMoney(r.variance_total, r.currency) },
        ]}
        rows={rows}
        empty="No supplier invoices."
      />
    </div>
  );
}

export function ProcurementInvoiceExceptionsPage() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    return api.get('/procurement/invoice-exceptions/?page_size=50')
      .then(r => setRows(safeResults(r.data)))
      .catch(e => setError(procurementErrorText(e, 'Failed to load invoice exceptions.')))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <p className="page-loading" role="status">Loading invoice exceptions…</p>;
  if (error) return <div role="alert" className="error">{error} <button className="btn" onClick={load}>Retry</button></div>;
  return (
    <div>
      <div className="page-header"><h1>Invoice Exceptions</h1></div>
      <Table
        columns={[
          { label: 'Invoice', render: r => r.invoice_number || r.invoice },
          { label: 'Type', key: 'exception_type' },
          { label: 'Severity', key: 'severity' },
          { label: 'Status', render: r => statusLabel(r.status) },
          { label: 'Expected', key: 'expected_value' },
          { label: 'Actual', key: 'actual_value' },
          { label: 'Variance', key: 'variance' },
          { label: 'Reason', key: 'reason' },
        ]}
        rows={rows}
        empty="No invoice exceptions."
      />
    </div>
  );
}

export default ProcurementInvoicesPage;
