import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import { AccessDenied, EmptyState } from './components';
import { ProcurementAssetsPage } from './procurement-assets';
import { ProcurementDashboard, ProcurementReports } from './procurement-dashboard';
import { GoodsReceiptForm } from './goods-receipt-form';
import { GoodsReceiptsPage } from './goods-receipts';
import { procurementCapabilities } from './procurement-utils';
import { PurchaseOrderDetail } from './purchase-order-detail';
import { PurchaseOrdersPage } from './purchase-orders';
import { PurchaseRequestDetail } from './purchase-request-detail';
import { PurchaseRequestForm } from './purchase-request-form';
import { PurchaseRequestQuotations } from './procurement-quotations';
import { PurchaseRequestsPage } from './purchase-requests';
import { ProcurementInvoicesPage, ProcurementInvoiceExceptionsPage } from './procurement-invoices';
import { ProcurementInvoiceForm } from './procurement-invoice-form';
import { ProcurementInvoiceDetail } from './procurement-invoice-detail';
import { ProcurementMatchingPage } from './procurement-matching';
import { ProcurementReturnsPage, ProcurementReturnForm, ProcurementReturnDetail } from './procurement-returns';
import { ProcurementCreditNotesPage, ProcurementCreditNoteForm, ProcurementCreditNoteDetail } from './procurement-credit-notes';
import { ProcurementFinancialDashboard } from './procurement-financial-dashboard';
import { ProcurementVendorPerformance } from './procurement-vendor-performance.jsx';

function readHash() {
  const raw = String(window.location.hash || '');
  const path = raw.replace(/^#/, '');
  const [route, query = ''] = path.split('?');
  return { route: route || '/procurement', query };
}
const NUMERIC = /^\d+$/;
function NotAvailable({ message }) {
  return (
    <div className="empty-state" role="alert">
      <div className="empty-title">{message}</div>
      <div className="small"><a href="#/procurement">Back to procurement</a></div>
    </div>
  );
}

export function ProcurementRouter({ route: routeProp }) {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const [location, setLocation] = useState(() => {
    if (routeProp) { const [route, query = ''] = String(routeProp).split('?'); return { route: route || '/procurement', query }; }
    return readHash();
  });
  useEffect(() => {
    if (routeProp) { const [route, query = ''] = String(routeProp).split('?'); setLocation({ route: route || '/procurement', query }); return undefined; }
    const onChange = () => setLocation(readHash());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, [routeProp]);

  if (!caps.canViewProcurement) return <AccessDenied reason="access" />;
  const { route } = location;
  const params = new URLSearchParams(location.query);
  const segments = route.split('/').filter(Boolean);
  if (segments[0] !== 'procurement') return <NotAvailable message="This procurement page does not exist." />;
  const rest = segments.slice(1);
  if (rest.length === 0) return <ProcurementDashboard />;
  const [first, second, third] = rest;

  if (first === 'requests') {
    if (!second) return <PurchaseRequestsPage />;
    if (second === 'new') return <PurchaseRequestForm />;
    if (!NUMERIC.test(second)) return <NotAvailable message="This purchase request does not exist." />;
    if (!third) return <PurchaseRequestDetail id={second} />;
    if (third === 'edit') return <PurchaseRequestForm id={second} />;
    if (third === 'quotations') return <PurchaseRequestQuotations id={second} />;
    return <NotAvailable message="This procurement page does not exist." />;
  }
  if (first === 'orders') {
    if (!second) return <PurchaseOrdersPage />;
    if (!NUMERIC.test(second)) return <NotAvailable message="This purchase order does not exist." />;
    return <PurchaseOrderDetail id={second} />;
  }
  if (first === 'receipts') {
    if (!second) return <GoodsReceiptsPage />;
    if (second === 'new') return <GoodsReceiptForm poId={params.get('po')} />;
    if (!NUMERIC.test(second)) return <NotAvailable message="This goods receipt does not exist." />;
    return <GoodsReceiptForm id={second} />;
  }
  if (first === 'invoices') {
    if (!second) return <ProcurementInvoicesPage />;
    if (second === 'new') return <ProcurementInvoiceForm />;
    if (!NUMERIC.test(second)) return <NotAvailable message="This invoice does not exist." />;
    if (!third) return <ProcurementInvoiceDetail id={second} />;
    if (third === 'match') return <ProcurementMatchingPage id={second} />;
    return <NotAvailable message="This procurement page does not exist." />;
  }
  if (first === 'exceptions') return <ProcurementInvoiceExceptionsPage />;
  if (first === 'returns') {
    if (!second) return <ProcurementReturnsPage />;
    if (second === 'new') return <ProcurementReturnForm />;
    if (!NUMERIC.test(second)) return <NotAvailable message="This return does not exist." />;
    return <ProcurementReturnDetail id={second} />;
  }
  if (first === 'credit-notes') {
    if (!second) return <ProcurementCreditNotesPage />;
    if (second === 'new') return <ProcurementCreditNoteForm />;
    if (!NUMERIC.test(second)) return <NotAvailable message="This credit note does not exist." />;
    return <ProcurementCreditNoteDetail id={second} />;
  }
  if (first === 'financial-dashboard') return caps.canViewProcurementReports ? <ProcurementFinancialDashboard /> : <AccessDenied reason="manager" />;
  if (first === 'vendor-performance') return caps.canViewProcurementReports ? <ProcurementVendorPerformance /> : <AccessDenied reason="manager" />;
  if (first === 'assets') return <ProcurementAssetsPage />;
  if (first === 'reports') return caps.canViewProcurementReports ? <ProcurementReports /> : <EmptyState title="Reports are restricted" hint="Procurement reports are available to IT Manager and System Admin users." />;
  return <NotAvailable message="This procurement page does not exist." />;
}

export default ProcurementRouter;
