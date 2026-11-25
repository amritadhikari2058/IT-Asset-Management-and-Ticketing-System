import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../auth';
import { useSort } from '../../components';
import { Badge, Field, DataTable, Pager, PageHeader, AccessDenied } from '../../components';
import { fetchPage } from '../../api-utils';
import { licensingCapabilities } from '../../shared/licensing-utils';
import { PRODUCT_APPROVAL_STATUS_LABELS, PLATFORM_LABELS, LICENSE_MODEL_LABELS, PRODUCT_CATEGORY_LABELS, RISK_LEVEL_LABELS, SUPPORT_STATUS_LABELS, buildProductListUrl } from '../../shared/licensing-utils';

function SoftwareProductsPage() {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [next, setNext] = useState(null);
  const [previous, setPrevious] = useState(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [f, setF] = useState({ search: '', category: '', platform: '', license_model: '', approved_status: '', risk_level: '', support_status: '', is_active: '' });
  const [sort, , orderingParam] = useSort();

  const loadUrl = async (url) => {
    setLoading(true); setError('');
    try {
      const pg = await fetchPage(url);
      setItems(pg.items); setCount(pg.count); setNext(pg.next); setPrevious(pg.previous); setPage(1);
    } catch { setError('Could not load products.'); }
    finally { setLoading(false); }
  };
  const builtUrl = useMemo(() => buildProductListUrl(f, orderingParam(sort), page), [f, sort, page]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setTimeout(() => loadUrl(builtUrl), 250); return () => clearTimeout(t); }, [builtUrl]);

  const columns = [
    { key: 'name', label: 'Product', sortable: 'name' },
    { key: 'code', label: 'Code' },
    { key: 'publisher', label: 'Publisher' },
    { key: 'category', label: 'Category', render: (v) => PRODUCT_CATEGORY_LABELS[v.category] || v.category },
    { key: 'platform', label: 'Platform', render: (v) => PLATFORM_LABELS[v.platform] || v.platform },
    { key: 'license_model', label: 'License Model', render: (v) => LICENSE_MODEL_LABELS[v.license_model] || v.license_model },
    { key: 'approved_status', label: 'Approval', render: (v) => <Badge kind="status" value={PRODUCT_APPROVAL_STATUS_LABELS[v.approved_status] || v.approved_status} /> },
    { key: 'risk_level', label: 'Risk', render: (v) => RISK_LEVEL_LABELS[v.risk_level] || v.risk_level },
    { key: 'support_status', label: 'Support', render: (v) => SUPPORT_STATUS_LABELS[v.support_status] || v.support_status },
    { key: 'is_active', label: 'Active', render: (v) => v.is_active ? 'Yes' : 'No' },
  ];
  if (caps.canManageProducts) columns.push({ key: 'actions', label: 'Actions', render: (v) => (
    <div style={{ display: 'flex', gap: 4 }}>
      <a className="btn btn-sm btn-outline" href={`#/software/products/${v.id}`}>View</a>
      <a className="btn btn-sm btn-outline" href={`#/software/products/${v.id}/edit`}>Edit</a>
    </div>
  ) });

  if (!caps.canView) return <AccessDenied />;
  return (
    <div className="software-products-page">
      <PageHeader title="Software Products" />
      <div className="page-toolbar" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <Field label="Search" required={false}><input className="input" value={f.search} onChange={(e) => setF({ ...f, search: e.target.value })} /></Field>
        <Field label="Category" required={false}><select className="input" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}><option value="">All</option>{Object.entries(PRODUCT_CATEGORY_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Platform" required={false}><select className="input" value={f.platform} onChange={(e) => setF({ ...f, platform: e.target.value })}><option value="">All</option>{Object.entries(PLATFORM_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        <Field label="Approval" required={false}><select className="input" value={f.approved_status} onChange={(e) => setF({ ...f, approved_status: e.target.value })}><option value="">All</option>{Object.entries(PRODUCT_APPROVAL_STATUS_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        {caps.canManageProducts && <a className="btn btn-primary" href="#/software/products/new">New Product</a>}
      </div>
      {error && <div className="alert alert-danger">{error}</div>}
      <DataTable columns={columns} rows={items} keyOf={(r) => r.id} loading={loading} emptyTitle="No products found" />
      {count !== null && <Pager count={count} hasNext={!!next} hasPrev={!!previous} busy={loading} onPrev={() => previous && loadUrl(previous)} onNext={() => next && loadUrl(next)} />}
    </div>
  );
}

export { SoftwareProductsPage };
export default SoftwareProductsPage;

