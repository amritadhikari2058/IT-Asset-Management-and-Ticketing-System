import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import api from '../../api';
import {
  DataTable, Field, LoadingRows, PageHeader, Pager,
} from '../../components';
import {
  buildGoodsReceiptListUrl,
  formatDate,
  parseFieldErrors,
  procurementCapabilities,
  receiptSummary,
  safeResults,
} from '../../shared/procurement-utils';

const PAGE_SIZE = 20;

/** Goods receipt list with server-side search, filters and pagination. */
export function GoodsReceiptsPage({ purchaseOrderId }) {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const [receipts, setReceipts] = useState([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    q: '', from: '', to: '', discrepancy: '', ordering: '-received_at',
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await api.get(buildGoodsReceiptListUrl({
        page,
        page_size: PAGE_SIZE,
        search: filters.q,
        received_from: filters.from,
        received_to: filters.to,
        discrepancy: filters.discrepancy,
        purchase_order: purchaseOrderId || '',
        ordering: filters.ordering,
      }));
      setReceipts(safeResults(response.data));
      setCount(Number(response.data?.count ?? safeResults(response.data).length));
    } catch (e) {
      setError(parseFieldErrors(e).global || 'Could not load goods receipts.');
    } finally {
      setLoading(false);
    }
  }, [page, filters, purchaseOrderId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const pageCount = Math.max(1, Math.ceil(count / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const update = (key, value) => { setFilters((f) => ({ ...f, [key]: value })); setPage(1); };

  if (!caps.canViewProcurement) {
    return <div className="empty-state"><div className="empty-title">Access restricted</div><div className="small">Procurement is available to IT staff only.</div></div>;
  }

  return (
    <div>
      <PageHeader
        title={purchaseOrderId ? 'Goods receipts for this order' : 'Goods receipts'}
        sub="Recorded deliveries, accepted quantities and discrepancies."
        actions={(
          <div className="row-gap">
            <a className="btn-ghost" href="#/procurement">Overview</a>
            {caps.canCreateGoodsReceipt ? (
              <a className="btn-primary" href={purchaseOrderId ? `#/procurement/receipts/new?po=${purchaseOrderId}` : '#/procurement/receipts/new'}>
                Record receipt
              </a>
            ) : null}
          </div>
        )}
      />

      <div className="panel">
        <div className="panel-head"><h3>Filters</h3></div>
        <div className="panel-pad">
          <div className="row-gap">
            <Field label="Search">
              <input
                className="input" value={filters.q}
                onChange={(e) => update('q', e.target.value)}
                placeholder="Receipt, PO, delivery note, invoice"
              />
            </Field>
            <Field label="Received from">
              <input type="date" className="input" value={filters.from} onChange={(e) => update('from', e.target.value)} />
            </Field>
            <Field label="Received to">
              <input type="date" className="input" value={filters.to} onChange={(e) => update('to', e.target.value)} />
            </Field>
            <Field label="Discrepancies">
              <select className="input" value={filters.discrepancy} onChange={(e) => update('discrepancy', e.target.value)} aria-label="Discrepancies">
                <option value="">Any</option>
                <option value="true">With rejected or damaged units</option>
                <option value="false">Without discrepancies</option>
              </select>
            </Field>
            <Field label="Order by">
              <select className="input" value={filters.ordering} onChange={(e) => update('ordering', e.target.value)} aria-label="Order by">
                <option value="-received_at">Newest received</option>
                <option value="received_at">Oldest received</option>
                <option value="gr_number">Receipt number</option>
              </select>
            </Field>
          </div>
          <div className="row-gap" style={{ marginTop: 8 }}>
            <span className="small muted">{count} receipt(s)</span>
            <button type="button" className="btn-ghost btn-small" onClick={load} disabled={loading}>Refresh</button>
          </div>
        </div>
      </div>

      {loading ? <LoadingRows /> : null}
      {error ? (
        <div>
          <div className="error-summary" role="alert">{error}</div>
          <button type="button" className="btn-primary" onClick={load}>Retry</button>
        </div>
      ) : null}

      {!loading && !error ? (
        <>
          <DataTable
            columns={[
              { key: 'gr_number', label: 'Receipt', render: (r) => <a className="row-title" href={`#/procurement/receipts/${r.id}`}>{r.gr_number}</a> },
              {
                key: 'po',
                label: 'Purchase order',
                render: (r) => (
                  <a href={`#/procurement/orders/${r.purchase_order}`}>
                    {r.purchase_order_number || `#${r.purchase_order}`}
                  </a>
                ),
              },
              { key: 'vendor', label: 'Vendor', render: (r) => r.vendor_name ?? '—' },
              { key: 'received_at', label: 'Received', render: (r) => formatDate(r.received_at) },
              { key: 'received_by_name', label: 'Received by', render: (r) => r.received_by_name || '—' },
              { key: 'delivery_note_number', label: 'Delivery note', render: (r) => r.delivery_note_number || '—' },
              { key: 'invoice_number', label: 'Invoice', render: (r) => r.invoice_number || '—' },
              { key: 'status', label: 'Status', render: () => <span className="badge badge-green">Recorded</span> },
              { key: 'accepted', label: 'Accepted', render: (r) => receiptSummary(r).accepted },
              { key: 'rejected', label: 'Rejected', render: (r) => receiptSummary(r).rejected },
              { key: 'damaged', label: 'Damaged', render: (r) => receiptSummary(r).damaged },
              {
                key: 'actions',
                label: 'Actions',
                render: (r) => (
                  <div className="row-gap">
                    <a className="btn-ghost btn-small" href={`#/procurement/receipts/${r.id}`}>View</a>
                    <a className="btn-ghost btn-small" href={`#/procurement/orders/${r.purchase_order}`}>Purchase order</a>
                  </div>
                ),
              },
            ]}
            rows={receipts}
            keyOf={(r) => `gr-${r.id}`}
            emptyTitle="No goods receipts recorded."
            emptyHint="Book a delivery against an issued purchase order."
          />
          <Pager
            count={count}
            hasPrev={currentPage > 1}
            hasNext={currentPage < pageCount}
            onPrev={() => setPage((p) => Math.max(1, p - 1))}
            onNext={() => setPage((p) => Math.min(pageCount, p + 1))}
            busy={loading}
            pageLabel={`Page ${currentPage} of ${pageCount}`}
          />
        </>
      ) : null}
    </div>
  );
}

