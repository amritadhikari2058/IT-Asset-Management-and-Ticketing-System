import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import { AccessDenied } from './components';
import { licensingCapabilities } from './licensing-utils';
import { LicensingDashboard } from './licensing-dashboard';
import { SoftwareProductsPage } from './software-products';
import { SoftwareProductForm } from './software-product-form';
import { SoftwareProductDetail } from './software-product-detail';
import { LicenseAgreementsPage } from './license-agreements';
import { LicenseAgreementForm } from './license-agreement-form';
import { LicenseAgreementDetail } from './license-agreement-detail';
import { LicenseAllocationsPage } from './license-allocations';
import { LicenseInstallationsPage } from './license-installations';
import { LicenseRenewalsPage } from './license-renewals';
import { LicenseCalendarPage } from './license-calendar';
import { LicenseCompliancePage } from './license-compliance';
import { LicenseSecretsPage } from './license-secrets';
import { LicenseDocumentsPage } from './license-documents';
import { LicenseUtilizationPage } from './license-utilization';
import { MySoftwarePage } from './my-software';

function readHash() {
  const raw = String(window.location.hash || '');
  const path = raw.replace(/^#/, '');
  const [route, query = ''] = path.split('?');
  return { route: route || '/software', query };
}

function NotAvailable({ message }) {
  return <div className="empty-state" role="alert"><div className="empty-title">{message}</div><div className="small"><a href="#/software">Back to licensing</a></div></div>;
}

export function LicensingRouter({ route: routeProp }) {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [location, setLocation] = useState(() => routeProp ? (() => { const [r, q = ''] = String(routeProp).split('?'); return { route: r || '/software', query: q }; })() : readHash());
  useEffect(() => {
    if (routeProp) { const [r, q = ''] = String(routeProp).split('?'); setLocation({ route: r || '/software', query: q }); return; } // eslint-disable-line react/set-state-in-effect
    const onChange = () => setLocation(readHash());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, [routeProp]);

  if (!caps.canView) return <AccessDenied reason="access" />;

  const { route } = location;
  const segments = route.split('/').filter(Boolean);
  const first = segments[0];

  // /software...
  if (first === 'software') {
    if (segments.length === 1) return <LicensingDashboard />;
    if (segments[1] === 'products') {
      if (segments[2] === 'new') return <SoftwareProductForm />;
      if (segments[2] && segments[3] === 'edit') return <SoftwareProductForm productId={segments[2]} />;
      if (segments[2]) return <SoftwareProductDetail id={segments[2]} />;
      return <SoftwareProductsPage />;
    }
    return <LicensingDashboard />;
  }

  // /licenses...
  if (first === 'licenses') {
    if (segments.length === 1) return <LicenseAgreementsPage />;
    if (segments[1] === 'new') return <LicenseAgreementForm />;
    if (segments[1] && segments[2] === 'edit') return <LicenseAgreementForm agreementId={segments[1]} />;
    if (segments[1] && segments[2] === 'allocations') return <LicenseAllocationsPage />;
    if (segments[1] && segments[2] === 'installations') return <LicenseInstallationsPage />;
    if (segments[1] && segments[2] === 'documents') return <LicenseDocumentsPage agreementId={segments[1]} />;
    if (segments[1] && segments[2] === 'history') return <LicenseAgreementDetail id={segments[1]} />;
    if (segments[1] && segments[2] === 'renewal') return <LicenseRenewalsPage />;
    if (segments[1] && segments[2] === 'secrets') return <LicenseSecretsPage agreementId={segments[1]} />;
    if (segments[1]) return <LicenseAgreementDetail id={segments[1]} />;
    return <LicenseAgreementsPage />;
  }

  if (first === 'license-allocations') return <LicenseAllocationsPage />;
  if (first === 'license-installations') return <LicenseInstallationsPage />;
  if (first === 'license-renewals') return <LicenseRenewalsPage />;
  if (first === 'license-compliance') return <LicenseCompliancePage />;
  if (first === 'license-calendar') return <LicenseCalendarPage />;
  if (first === 'license-utilization') return <LicenseUtilizationPage />;
  if (first === 'my-software') return <MySoftwarePage />;

  return <NotAvailable message="This licensing page does not exist." />;
}

export default LicensingRouter;
