import { useCallback, useEffect, useState } from 'react';
import api from './api';
import { safeResults, formatMoney, formatDateTime, statusLabel, procurementErrorText } from './procurement-utils';

function Table({ columns, rows, empty = 'No records.' }) {
  if (!rows?.length) return <div className="empty-state"><div className="empty-title">{empty}</div></div>;
  return <div className="table-wrap"><table className="table"><thead><tr>{columns.map(c => <th key={c.key || c.label}>{c.label}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={row.id ?? i}>{columns.map(c => <td key={c.key || c.label}>{typeof c.render === 'function' ? c.render(row) : row[c.key]}</td>)}</tr>)}</tbody></table></div>;
}

export function ProcurementMatchingPage({ id }) {
  const [inv, setInv] = useState(null);
  const [history, setHistory] = useState([]);
  const [exceptions, setExceptions] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [a, b, c] = await Promise.all([
        api.get(`/procurement/supplier-invoices/${id}/`),
        api.get(`/procurement/supplier-invoices/${id}/match-history/`),
        api.get(`/procurement/supplier-invoices/${id}/exceptions/`),
      ]);
      setInv(a.data); setHistory(safeResults(b.data)); setExceptions(safeResults(c.data));
    } catch (e) { setError(procurementErrorText(e, 'Failed to load match data.')); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  async function runMatch() {
    setBusy(true); setError('');
    try { await api.post(`/procurement/supplier-invoices/${id}/match/`, {}); await load(); }
    catch (e) { setError(procurementErrorText(e, 'Match failed.')); }
    finally { setBusy(false); }
  }

  if (!inv) return <p className="page-loading">{error ? <span role="alert">{error}</span> : 'Loading…'}</p>;
  const latest = history[0];
  return (
    <div>
      <div className="page-header"><h1>Three-Way Match: {inv.invoice_number}</h1><div><button className="btn" onClick={runMatch} disabled={busy}>{busy ? 'Matching…' : 'Run Match'}</button> <a className="btn" href={`#/procurement/invoices/${id}`}>Back to Invoice</a></div></div>
      {error && <div role="alert" className="error">{error}</div>}
      {latest && (
        <div className="card">
          <strong>Latest Overall Status:</strong> {statusLabel(latest.overall_status)} (version {latest.match_version}) |
          {' '}<strong>Invoice Total:</strong> {formatMoney(latest.invoice_total_snapshot, inv.currency)} |
          {' '}<strong>PO Total:</strong> {formatMoney(latest.po_total_snapshot, inv.currency)} |
          {' '}<strong>Accepted Receipt Total:</strong> {formatMoney(latest.accepted_receipt_total_snapshot, inv.currency)} |
          {' '}<strong>Total Variance:</strong> {formatMoney(latest.total_variance, inv.currency)}
          <div className="small">
            Quantity variance {formatMoney(latest.quantity_variance_total, inv.currency)} ·
            {' '}Price variance {formatMoney(latest.price_variance_total, inv.currency)} ·
            {' '}Tax variance {formatMoney(latest.tax_variance_total, inv.currency)} ·
            {' '}Tolerance {latest.tolerance_snapshot && Object.keys(latest.tolerance_snapshot).length ? JSON.stringify(latest.tolerance_snapshot) : '—'} ·
            {' '}Checksum {latest.checksum || '—'} ·
            {' '}Matched {formatDateTime(latest.matched_at)} by {latest.matched_by_name || '—'}
          </div>
        </div>
      )}
      <h2>Side-by-side Line Comparison</h2>
      <Table
        columns={[
          { label: 'PO Line', render: r => r.po_item_name || r.purchase_order_item },
          { label: 'Invoiced Qty', key: 'invoiced_quantity' },
          { label: 'Accepted Received (snapshot)', key: 'accepted_quantity_snapshot' },
          { label: 'Matched Qty', key: 'matched_quantity' },
          { label: 'Invoice Unit Price', key: 'unit_price' },
          { label: 'Invoice Tax', key: 'tax_amount' },
          { label: 'Line Total', key: 'line_total' },
          { label: 'Qty Variance', key: 'quantity_variance' },
          { label: 'Price Variance', key: 'price_variance' },
          { label: 'Tax Variance', key: 'tax_variance' },
          { label: 'Total Variance', key: 'total_variance' },
          { label: 'Match Status', render: r => statusLabel(r.match_status) },
          { label: 'Exception Reason', render: r => r.exception_reason || '—' },
        ]}
        rows={inv.lines || []}
        empty="No invoice lines."
      />
      <h2>Exceptions</h2>
      <Table
        columns={[
          { label: 'Type', key: 'exception_type' },
          { label: 'Severity', key: 'severity' },
          { label: 'Status', render: r => statusLabel(r.status) },
          { label: 'Expected', key: 'expected_value' },
          { label: 'Actual', key: 'actual_value' },
          { label: 'Variance', key: 'variance' },
          { label: 'Reason', key: 'reason' },
        ]}
        rows={exceptions}
        empty="No exceptions."
      />
      <h2>Match History</h2>
      <Table
        columns={[
          { label: 'Version', key: 'match_version' },
          { label: 'Overall Status', render: r => statusLabel(r.overall_status) },
          { label: 'PO Total', key: 'po_total_snapshot' },
          { label: 'Accepted Receipt Total', key: 'accepted_receipt_total_snapshot' },
          { label: 'Invoice Total', key: 'invoice_total_snapshot' },
          { label: 'Total Variance', key: 'total_variance' },
          { label: 'Checksum', key: 'checksum' },
          { label: 'Matched By', render: r => r.matched_by_name || '—' },
          { label: 'Matched At', render: r => formatDateTime(r.matched_at) },
        ]}
        rows={history}
        empty="No match results."
      />
      <p className="small">Matching is performed by the backend and is authoritative. Frontend does not infer payment readiness or match results.</p>
    </div>
  );
}

export default ProcurementMatchingPage;
