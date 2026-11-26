import { useEffect, useState } from 'react';
import { useAuth } from '../../auth';
import { PageHeader } from '../../components';
import api from '../../api';
import { licensingCapabilities } from '../../shared/licensing-utils';
import { PRODUCT_APPROVAL_STATUS_LABELS, RISK_LEVEL_LABELS, SUPPORT_STATUS_LABELS } from '../../shared/licensing-utils';

function SoftwareProductDetail({ id, productId }) {
  const auth = useAuth();
  const caps = licensingCapabilities(auth);
  const pid = id || productId;
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!pid) return;
    setLoading(true); // eslint-disable-line react/set-state-in-effect
    api.get(`/licensing/products/${pid}/`).then((r) => setProduct(r.data)).catch((e) => setError(e.response?.data?.detail || 'Could not load product.')).finally(() => setLoading(false));
  }, [pid]);
  const doAction = async (action) => {
    try { await api.post(`/licensing/products/${pid}/${action}/`); const r = await api.get(`/licensing/products/${pid}/`); setProduct(r.data); } catch (e) { setError(e.response?.data?.detail || 'Action failed.'); }
  };
  if (loading) return <div className="panel-pad">Loading product…</div>;
  if (error) return <div className="alert alert-danger">{error}</div>;
  if (!product) return null;
  return (
    <div className="software-product-detail">
      <PageHeader title={product.name} />
      <div className="card mb-3"><div className="card-body">
        <div><strong>Publisher:</strong> {product.publisher}</div>
        <div><strong>Version:</strong> {product.version}</div>
        <div><strong>Platform:</strong> {product.platform}</div>
        <div><strong>Approval:</strong> {PRODUCT_APPROVAL_STATUS_LABELS[product.approved_status]}</div>
        <div><strong>Risk:</strong> {RISK_LEVEL_LABELS[product.risk_level]}</div>
        <div><strong>Support:</strong> {SUPPORT_STATUS_LABELS[product.support_status]}</div>
        <div><strong>Active:</strong> {product.is_active ? 'Yes' : 'No'}</div>
        <div>{product.description}</div>
      </div></div>
      {caps.canManageProducts && (
        <div style={{ display: 'flex', gap: 8 }}>
          <a className="btn-secondary" href={`#/software/products/${pid}/edit`}>Edit</a>
          <button className="btn-secondary" onClick={() => doAction('approve')}>Approve</button>
          <button className="btn-secondary" onClick={() => doAction('restrict')}>Restrict</button>
          <button className="btn-danger" onClick={() => doAction('prohibit')}>Prohibit</button>
        </div>
      )}
    </div>
  );
}
export { SoftwareProductDetail };
export default SoftwareProductDetail;

