import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import {
  DataTable, PageHeader, LoadingRows, Field, Select, Input,
} from './components';
import { parseApiError } from './api-utils';
import {
  formatDateTime, safeResults, CMDB_API_CONTRACT,
} from './cmdb-utils';

export function VerificationQueuePage() {
  const { role: authRole, user } = useAuth();
  const role = authRole ?? user?.role;
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    ci: null, verification_note: '', expected_record_version: null,
  });

  // Load verification queue
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(CMDB_API_CONTRACT.verificationQueue.endpoint)
      .then((r) => {
        if (cancelled) return;
        const data = r.data;
        setItems(Array.isArray(data) ? data : safeResults(data?.results));
      })
      .catch(() => { if (!cancelled) setError('Could not load verification queue.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Verify a record
  const handleVerify = async () => {
    if (!form.ci) return;
    setError('');
    try {
      await api.post(`/cmdb/items/${form.ci}/verify/`, {
        verification_note: form.verification_note || '',
        expected_record_version: form.expected_record_version ?? undefined,
      });
      setItems((prev) => prev.filter((item) => item.id !== form.ci));
      setForm({ ci: null, verification_note: '', expected_record_version: null });
    } catch (e) {
      const parsed = parseApiError(e);
      setError(parsed.global || 'Could not verify record.');
    }
  };

  // Employees are denied CMDB verification access
  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB verification access.
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Verification Queue" sub="Pending CMDB record verification" />

      {loading && (
        <div className="panel panel-pad">
          <LoadingRows n={4} />
          <p>Loading verification queue...</p>
        </div>
      )}

      {error && <div className="error-summary" role="alert">{error}</div>}

      {/* Verify form */}
      <div className="panel panel-pad" style={{ marginBottom: 20 }}>
        <h4>Verify Record</h4>
        <Form rowGutters={16}>
          <Field label="CI *">
            <Select
              onChange={(e) => setForm({ ...form, ci: e.target.value ? Number(e.target.value) : null })}
              aria-label="CI"
            >
              <option value="">Select CI</option>
              {items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.ci_number || item.name || `CI ${item.id}`}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Expected Record Version">
            <Input
              value={form.expected_record_version ?? ''}
              onChange={(e) => setForm({ ...form, expected_record_version: Number(e.target.value) || null })}
              type="number"
              placeholder="e.g. 5"
            />
          </Field>

          <Field label="Verification Note">
            <Input
              value={form.verification_note || ''}
              onChange={(e) => setForm({ ...form, verification_note: e.target.value })}
            />
          </Field>

          <div className="row-end" style={{ marginTop: 20 }}>
            <button type="button" className="btn-primary" onClick={handleVerify} disabled={!form.ci}>
              Verify
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setForm({ ci: null, verification_note: '', expected_record_version: null })}
            >
              Cancel
            </button>
          </div>
        </Form>
      </div>

      <div className="panel panel-pad">
        <DataTable
          columns={[
            { key: 'id', label: 'ID' },
            { key: 'ci_number', label: 'CI', render: (row) => row.ci_number || row.ci || '—' },
            { key: 'status', label: 'Status', render: (row) => row.status || 'Pending' },
            { key: 'last_verified_at', label: 'Verified At', render: (row) => row.last_verified_at ? formatDateTime(row.last_verified_at) : '—' },
          ]}
          rows={items}
          keyOf={(r) => r.id}
          emptyTitle="No verification items found."
          emptyHint="Records pending verification appear here."
        />
      </div>
    </div>
  );
}

/** Legacy alias kept for existing test compatibility */
export function VerificationQueue() {
  return <VerificationQueuePage />;
}

// Simple form wrapper
const Form = ({ rowGutters, children }) => (
  <form
    style={{ display: 'grid', gap: rowGutters + 'px' }}
    noValidate
  >
    {children}
  </form>
);
