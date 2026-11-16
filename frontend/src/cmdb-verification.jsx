import { useEffect, useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { Badge, DataTable, EmptyState, PageHeader, LoadingRows, Field, Select, Input, ConfirmDialog, Modal } from './components';
import { safeResults, formatVerificationAge, CMDB_API_CONTRACT, CMDB_ROLES, CMDB_PERMISSIONS } from './cmdb-utils';

export function VerificationQueuePage() {
  const { role } = useAuth();

/** Legacy alias kept for existing test compatibility */
export function VerificationQueue() {
  return <VerificationQueuePage />;
}

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState({ ci: null, verification_note: '', expected_record_version: null });

  // Load verification queue
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(CMDB_API_CONTRACT.verificationList.endpoint)
      .then((r) => { if (!cancelled) setItems(r.data); })
      .catch((e) => { setError('Could not load verification queue.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Verify a record
  const handleVerify = async (id) => {
    setError('');
    try {
      await api.post(`/cmdb/verification/${id}/verify`, {
        expected_record_version: form.expected_record_version
      });
      setItems(prev => prev.filter((item) => item.id !== id));
      setItems([...items, { ...form, id }]); // refresh
    } catch (e) {
      const parsed = parseApiError(e);
      setError(parsed.global || 'Could not verify record.');
    }
  };

  // Employee denied
  if (role === 'employee') {
    return (
      <div className="error-summary" role="alert">
        Employees have no CMDB verification access.
      </div>
    );
  }

  if (loading && !items.length) {
    return (
      <div className="panel panel-pad">
        <LoadingRows n={4} />
        <p>Loading verification queue...</p>
      </div>
    );
  }

  if (error && !items.length) {
    return (
      <div className="error-summary" role="alert">{error}</div>
    );
  }

  return (
    <div>
      <PageHeader title="Verification Queue" sub="Pending CMDB record verification" />

      {error && <div className="error-summary" role="alert">{error}</div>}

      {/* Form */ }
      <div className="panel panel-pad" style={{ marginBottom: 20 }}>
        <h4>Verify Record</h4>
        <Form rowGutters={16}>
          <Field label="CI *">
            <Select
              onChange={(e) => setForm({ ...form, ci: e.target.value ? Number(e.target.value) : null })}
              aria-label="CI"
            >
              <option value="">Select CI</option>
              {/* Options would be populated dynamically */}
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
            <button type="button" className="btn-primary" onClick={() => handleVerify(0)} disabled={!form.ci}>
              Verify
            </button>
            <button type="button" className="btn-ghost" onClick={() => setForm({ ci: null, verification_note: '', expected_record_version: null })} disabled={false}>
              Cancel
            </button>
          </div>
        </Form>
      </div>

      /*
      <div className="panel panel-pad">
        <DataTable
          columns={[
            { key: 'id', label: 'ID' },
            { key: 'ci_id', label: 'CI' },
            { key: 'status', label: 'Status', render: (v) => v ? '<span className="badge badge-green">Verified</span>' : '<span className="badge badge-gray">Pending</span>' },
            { key: 'verified_at', label: 'Verified At' },
            { key: 'actions', label: 'Actions', render: (v, item) => (
              <div>
                <button>View</button>
              </div>
            ) }
          ]}
          rows={items}
          keyOf={(r) => r.id}
          emptyTitle="No verification items found."
          emptyHint="Add or refresh the verification queue to get started."
        />
      </div>
    </div>
  );
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