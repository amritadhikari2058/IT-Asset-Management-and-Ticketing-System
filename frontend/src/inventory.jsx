import React, { useEffect, useState } from 'react';
import api from './api';

export default function Inventory() {
  const [items, setItems] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true); setError('');
    try {
      const [d, list] = await Promise.all([api.get('/inventory/stock-items/dashboard/'), api.get('/inventory/stock-items/')]);
      setDashboard(d.data); setItems(list.data.results || list.data);
    } catch (e) { setError('Failed to load inventory'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  if (loading) return <div className="p-3">Loading inventory...</div>;
  if (error) return <div className="alert alert-danger">{error}</div>;

  return (
    <div className="container-fluid p-3">
      <h3>Inventory Dashboard</h3>
      {dashboard && (
        <div className="row g-3 mb-3">
          <div className="col-md-3"><div className="card p-3"><div className="text-muted">Total Items</div><h4>{dashboard.total_items}</h4></div></div>
          <div className="col-md-3"><div className="card p-3"><div className="text-muted">Total Units</div><h4>{dashboard.total_units}</h4></div></div>
          <div className="col-md-3"><div className="card p-3"><div className="text-muted">Low Stock</div><h4>{dashboard.low_stock}</h4></div></div>
          <div className="col-md-3"><div className="card p-3"><div className="text-muted">Out of Stock</div><h4>{dashboard.out_of_stock}</h4></div></div>
        </div>
      )}
      <h5>Stock Items</h5>
      <table className="table table-sm">
        <thead><tr><th>SKU</th><th>Name</th><th>Qty</th><th>Available</th><th>Threshold</th></tr></thead>
        <tbody>
          {items.map(i => (
            <tr key={i.id}><td>{i.sku}</td><td>{i.name}</td><td>{i.quantity}</td><td>{i.available}</td><td>{i.reorder_threshold}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
