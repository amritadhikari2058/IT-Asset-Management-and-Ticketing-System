import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import { AccessDenied, EmptyState } from './components';
import { ProcurementAssetsPage } from './procurement-assets';
import { ProcurementDashboard, ProcurementReports } from './procurement-dashboard';
import { GoodsReceiptForm } from './goods-receipt-form';
import { GoodsReceiptsPage } from './goods-receipts';
import {
  procurementCapabilities,
} from './procurement-utils';
import { PurchaseOrderDetail } from './purchase-order-detail';
import { PurchaseOrdersPage } from './purchase-orders';
import { PurchaseRequestDetail } from './purchase-request-detail';
import { PurchaseRequestForm } from './purchase-request-form';
import { PurchaseRequestQuotations } from './procurement-quotations';
import { PurchaseRequestsPage } from './purchase-requests';

/** Procurement hash path, including any `?query` string. */
function readHash() {
  const raw = String(window.location.hash || '');
  const path = raw.replace(/^#/, '');
  const [route, query = ''] = path.split('?');
  return { route: route || '/procurement', query };
}

const NUMERIC = /^\d+$/;

/** Renders the not-found state for unknown or invalid procurement routes. */
function NotAvailable({ message }) {
  return (
    <div className="empty-state" role="alert">
      <div className="empty-title">{message}</div>
      <div className="small">
        <a href="#/procurement">Back to procurement</a>
      </div>
    </div>
  );
}

/**
 * Procurement route table. Route integration in App.jsx is supplied as a
 * separate minimal patch, so this module also listens to hash changes on its
 * own and works when mounted for any `#/procurement...` path.
 */
export function ProcurementRouter({ route: routeProp }) {
  const auth = useAuth();
  const caps = procurementCapabilities(auth);
  const [location, setLocation] = useState(() => {
    if (routeProp) {
      const [route, query = ''] = String(routeProp).split('?');
      return { route: route || '/procurement', query };
    }
    return readHash();
  });

  useEffect(() => {
    if (routeProp) {
      const [route, query = ''] = String(routeProp).split('?');
      setLocation({ route: route || '/procurement', query });
      return undefined;
    }
    const onChange = () => setLocation(readHash());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, [routeProp]);

  if (!caps.canViewProcurement) {
    return <AccessDenied reason="access" />;
  }

  const { route } = location;
  const params = new URLSearchParams(location.query);
  const segments = route.split('/').filter(Boolean);
  // Expect ["procurement", ...rest]
  if (segments[0] !== 'procurement') {
    return <NotAvailable message="This procurement page does not exist." />;
  }
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

  if (first === 'assets') return <ProcurementAssetsPage />;
  if (first === 'reports') return caps.canViewProcurementReports
    ? <ProcurementReports />
    : <EmptyState title="Reports are restricted" hint="Procurement reports are available to IT Manager and System Admin users." />;

  return <NotAvailable message="This procurement page does not exist." />;
}

export default ProcurementRouter;
