import { useEffect, useState } from 'react';
import { useAuth } from './auth';
import api from './api';

export function ServicesCatalogue() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/services/catalogue/').then((r) => setItems(r.data.results || r.data)).finally(() => setLoading(false));
  }, []);
  if (loading) return <div className="p-3">Loading...</div>;
  return (
    <div className="p-3">
      <h3>Service Catalogue</h3>
      <div className="row">
        {items.filter((i) => i.is_active).map((i) => (
          <div className="col-md-4 mb-3" key={i.id}>
            <div className="card h-100">
              <div className="card-body">
                <h5>{i.name}</h5>
                <p>{i.description}</p>
                <span className="badge bg-secondary">{i.category}</span>
                {i.requires_approval && <span className="badge bg-warning ms-1">Approval required</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function MyServiceRequests() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/services/requests/').then((r) => setItems(r.data.results || r.data)).finally(() => setLoading(false));
  }, []);
  if (loading) return <div className="p-3">Loading...</div>;
  return (
    <div className="p-3">
      <h3>My Service Requests</h3>
      <table className="table">
        <thead><tr><th>Number</th><th>Service</th><th>Status</th><th>Submitted</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}><td>{r.request_number}</td><td>{r.catalogue_item_name}</td><td>{r.status}</td><td>{r.submitted_at}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ServiceRequestDetail({ id }) {
  const [req, setReq] = useState(null);
  useEffect(() => {
    api.get(`/services/requests/${id}/`).then((r) => setReq(r.data));
  }, [id]);
  if (!req) return <div className="p-3">Loading...</div>;
  return (
    <div className="p-3">
      <h3>{req.request_number}</h3>
      <p>Status: {req.status}</p>
      <p>Service: {req.catalogue_item_name}</p>
      <pre>{JSON.stringify(req.answers, null, 2)}</pre>
    </div>
  );
}