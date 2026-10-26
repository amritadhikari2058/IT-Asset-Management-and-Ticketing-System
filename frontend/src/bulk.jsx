import { useState } from 'react';
import api from './api';
import { useAuth } from './auth';
import { DepartmentSelect, Field, Modal } from './components';
import {
  blobErrorMessage, downloadBlob, fieldMsg, parseApiError, parseCSV,
} from './api-utils';

const ALL_ROLES = [
  ['system_admin', 'System Admin'],
  ['it_manager', 'IT Manager'],
  ['it_support', 'IT Support'],
  ['employee', 'Employee'],
];

/** Bulk ticket creation: CSV/XLSX import, preview, confirm, report. */
export function TicketBulkCreateModal({ onClose, onCreated }) {
  const [file, setFile, pick] = useCsvFile();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState(null);
  const [report, setReport] = useState(null);
  const [reportBlob, setReportBlob] = useState(null);

  const doPreview = async () => {
    if (!file || busy) return;
    setBusy(true);
    setError('');
    setPreview(null);
    setReport(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('preview', 'true');
      const r = await api.post('/tickets/bulk_create/', fd);
      setPreview(r.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Preview failed.');
    } finally {
      setBusy(false);
    }
  };

  const doConfirm = async () => {
    if (!file || busy) return;
    if (!confirm(`Create ${preview?.affected ?? 0} ticket(s)? Invalid rows will be skipped.`)) return;
    setBusy(true);
    setError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('preview', 'false');
      fd.append('confirm', 'true');
      const r = await api.post('/tickets/bulk_create/?download=csv', fd, { responseType: 'blob' });
      const text = await r.data.text();
      const rows = parseCSV(text);
      const [, ...body] = rows;
      setReport(body.map(([row, key, outcome, message]) => ({ row, key, outcome, message })));
      setReportBlob(r.data);
      onCreated();
    } catch (e) {
      setError(await blobErrorMessage(e, 'Bulk create failed.'));
    } finally {
      setBusy(false);
    }
  };

  const okCount = preview?.affected ?? 0;
  return (
    <Modal title="Bulk create tickets" size="lg" onClose={() => { if (!busy) onClose(); }}>
      <p className="muted small modal-intro">
        1. Download the template. 2. Upload the filled CSV/XLSX. 3. Preview. 4. Confirm.
        You are recorded as the requester of every ticket.
      </p>
      <div className="row-gap" style={{ marginBottom: 'var(--sp-3)' }}>
        <button
          type="button" className="btn-ghost" disabled={busy}
          onClick={() => downloadTemplate('/tickets/bulk_create/?download=csv', 'ticket_import_template.csv', setError)}
        >
          Download template
        </button>
        <input type="file" accept=".csv,.xlsx,.xlsm" onChange={pick} disabled={busy} aria-label="Import file" />
      </div>
      {error && <div className="error-summary" role="alert">{error}</div>}
      <div className="row-gap">
        <button type="button" className="btn-secondary" onClick={doPreview} disabled={busy || !file}>
          {busy ? 'Working...' : 'Preview'}
        </button>
        {preview && (
          <button type="button" className="btn-primary" onClick={doConfirm} disabled={busy}>
            {busy ? 'Working...' : `Confirm create (${okCount})`}
          </button>
        )}
      </div>
      {preview && (
        <div className="modal-block">
          <p className="muted small">
            {okCount} valid, {(preview.invalid?.length ?? 0)} invalid rows.
          </p>
          {(preview.invalid?.length ?? 0) > 0 && (
            <ReportTable rows={preview.invalid.map((e) => ({
              row: e.row ?? '',
              key: '',
              outcome: 'invalid',
              message: typeof e.errors === 'string' ? e.errors : JSON.stringify(e.errors),
            }))} />
          )}
        </div>
      )}
      {report && (
        <div className="modal-block">
          <div className="row-gap" style={{ marginBottom: 'var(--sp-2)' }}>
            <b>Create result</b>
            <button
              type="button" className="btn-small"
              onClick={() => reportBlob && downloadBlob(reportBlob, 'ticket_import_report.csv')}
            >
              Download report (CSV)
            </button>
          </div>
          <ReportTable rows={report} />
        </div>
      )}
      <div className="row-end">
        <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>Close</button>
      </div>
    </Modal>
  );
}

/** Single employee creation (POST /api/accounts/users/). */
export function EmployeeCreateModal({ onClose, onCreated }) {
  const { isAdmin } = useAuth();
  const [form, setForm] = useState({
    employee_id: '', username: '', email: '', password: '',
    first_name: '', last_name: '', role: 'employee', home_department: '',
    phone: '', job_title: '', can_create_tickets: true,
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const [globalError, setGlobalError] = useState('');
  const [saving, setSaving] = useState(false);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const roles = isAdmin ? ALL_ROLES : ALL_ROLES.filter(([v]) => v !== 'system_admin');

  const submit = async (ev) => {
    ev.preventDefault();
    if (saving) return;
    setFieldErrors({});
    setGlobalError('');
    const payload = {
      employee_id: form.employee_id.trim(),
      username: form.username.trim() || form.email.trim(),
      email: form.email.trim(),
      password: form.password,
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      role: form.role,
      phone: form.phone.trim(),
      job_title: form.job_title.trim(),
      can_create_tickets: form.can_create_tickets,
    };
    if (form.home_department !== '') payload.home_department = Number(form.home_department);
    setSaving(true);
    try {
      const r = await api.post('/accounts/users/', payload);
      onCreated(r.data);
      onClose();
    } catch (e) {
      const p = parseApiError(e);
      setFieldErrors(p.fields);
      setGlobalError(p.global);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="Add employee" size="lg" onClose={() => { if (!saving) onClose(); }}>
      <form onSubmit={submit} noValidate>
        {globalError && <div className="error-summary" role="alert">{globalError}</div>}
        <div className="form-grid">
          <Field label="Employee ID" required error={fieldMsg(fieldErrors, 'employee_id')}>
            <input className="input" value={form.employee_id} onChange={(e) => set('employee_id')(e.target.value)} disabled={saving} maxLength={30} />
          </Field>
          <Field label="Email" required error={fieldMsg(fieldErrors, 'email')}>
            <input className="input" type="email" value={form.email} onChange={(e) => set('email')(e.target.value)} disabled={saving} />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Username" error={fieldMsg(fieldErrors, 'username')} hint="Defaults to the email address.">
            <input className="input" value={form.username} onChange={(e) => set('username')(e.target.value)} disabled={saving} maxLength={150} />
          </Field>
          <Field label="Password" required error={fieldMsg(fieldErrors, 'password')} hint="Minimum 8 characters.">
            <input className="input" type="password" value={form.password} onChange={(e) => set('password')(e.target.value)} disabled={saving} autoComplete="new-password" />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="First name" error={fieldMsg(fieldErrors, 'first_name')}>
            <input className="input" value={form.first_name} onChange={(e) => set('first_name')(e.target.value)} disabled={saving} />
          </Field>
          <Field label="Last name" error={fieldMsg(fieldErrors, 'last_name')}>
            <input className="input" value={form.last_name} onChange={(e) => set('last_name')(e.target.value)} disabled={saving} />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Role" error={fieldMsg(fieldErrors, 'role')} hint={!isAdmin ? 'IT Support accounts are always created as employees.' : undefined}>
            <select className="input" value={form.role} onChange={(e) => set('role')(e.target.value)} disabled={saving}>
              {roles.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          </Field>
          <Field label="Department" error={fieldMsg(fieldErrors, 'home_department')}>
            <DepartmentSelect value={form.home_department} onChange={set('home_department')} disabled={saving} />
          </Field>
        </div>
        <div className="form-grid">
          <Field label="Phone" error={fieldMsg(fieldErrors, 'phone')}>
            <input className="input" value={form.phone} onChange={(e) => set('phone')(e.target.value)} disabled={saving} maxLength={30} />
          </Field>
          <Field label="Job title" error={fieldMsg(fieldErrors, 'job_title')}>
            <input className="input" value={form.job_title} onChange={(e) => set('job_title')(e.target.value)} disabled={saving} maxLength={100} />
          </Field>
        </div>
        <label className="check-row">
          <input type="checkbox" checked={form.can_create_tickets} onChange={(e) => set('can_create_tickets')(e.target.checked)} disabled={saving} />
          Can create tickets
        </label>
        <div className="row-end">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? 'Creating…' : 'Create employee'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** Per-row outcome table shared by import/bulk-create reports. */
export function ReportTable({ rows }) {
  if (!rows.length) return <p className="muted">No rows to show.</p>;
  return (
    <div className="table-wrap">
      <table className="grid">
        <thead>
          <tr><th>Row</th><th>Key</th><th>Outcome</th><th>Message</th></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.row ?? ''}</td>
              <td>{r.key ?? ''}</td>
              <td>{r.outcome ?? ''}</td>
              <td>{r.message ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function useCsvFile() {
  const [file, setFile] = useState(null);
  const pick = (e) => setFile(e.target.files?.[0] ?? null);
  return [file, setFile, pick];
}

async function downloadTemplate(url, filename, setError) {
  try {
    const r = await api.get(url, { responseType: 'blob' });
    downloadBlob(r.data, filename);
    return true;
  } catch {
    setError('Could not download the template.');
    return false;
  }
}

/** Bulk employee import: template → upload → preview → confirm → report. */
export function EmployeeImportModal({ onClose, onImported }) {
  const [file, setFile, pick] = useCsvFile();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState(null);
  const [report, setReport] = useState(null);
  const [reportBlob, setReportBlob] = useState(null);

  const doPreview = async () => {
    if (!file || busy) return;
    setBusy(true);
    setError('');
    setPreview(null);
    setReport(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('preview', 'true');
      const r = await api.post('/accounts/users/bulk_import/', fd);
      setPreview(r.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Preview failed.');
    } finally {
      setBusy(false);
    }
  };

  const doConfirm = async () => {
    if (!file || busy) return;
    if (!confirm('Create the previewed employees? Existing IDs will be skipped.')) return;
    setBusy(true);
    setError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('preview', 'false');
      fd.append('confirm', 'true');
      const r = await api.post('/accounts/users/bulk_import/?download=csv', fd, { responseType: 'blob' });
      const text = await r.data.text();
      const rows = parseCSV(text);
      const [, ...body] = rows;
      setReport(body.map(([row, key, outcome, message]) => ({ row, key, outcome, message })));
      setReportBlob(r.data);
      onImported();
    } catch (e) {
      setError(await blobErrorMessage(e, 'Import failed.'));
    } finally {
      setBusy(false);
    }
  };

  const counts = preview?.counts;
  return (
    <Modal title="Bulk import employees" size="lg" onClose={() => { if (!busy) onClose(); }}>
      <p className="muted small modal-intro">
        1. Download the template. 2. Upload the filled CSV/XLSX. 3. Preview. 4. Confirm.
        Roles and ticket-creation rights are never changed by import.
      </p>
      <div className="row-gap" style={{ marginBottom: 'var(--sp-3)' }}>
        <button
          type="button" className="btn-ghost" disabled={busy}
          onClick={() => downloadTemplate('/accounts/users/bulk_import/?download=csv', 'employee_import_template.csv', setError)}
        >
          Download template
        </button>
        <input type="file" accept=".csv,.xlsx,.xlsm" onChange={pick} disabled={busy} aria-label="Import file" />
      </div>
      {error && <div className="error-summary" role="alert">{error}</div>}
      <div className="row-gap">
        <button type="button" className="btn-secondary" onClick={doPreview} disabled={busy || !file}>
          {busy ? 'Working…' : 'Preview'}
        </button>
        {preview && (
          <button type="button" className="btn-primary" onClick={doConfirm} disabled={busy}>
            {busy ? 'Working…' : `Confirm import (${counts?.ok ?? 0} new)`}
          </button>
        )}
      </div>
      {preview && (
        <div className="modal-block">
          <p className="muted small">
            {counts?.ok ?? 0} would be created · {counts?.failed ?? 0} invalid rows.
          </p>
          {(preview.errors?.length ?? 0) > 0 && (
            <ReportTable rows={preview.errors.map((e) => ({
              row: e.row ?? '',
              key: e.data?.employee_id ?? '',
              outcome: 'failed',
              message: typeof e.errors === 'string' ? e.errors : JSON.stringify(e.errors),
            }))} />
          )}
        </div>
      )}
      {report && (
        <div className="modal-block">
          <div className="row-gap" style={{ marginBottom: 'var(--sp-2)' }}>
            <b>Import result</b>
            <button
              type="button" className="btn-small"
              onClick={() => reportBlob && downloadBlob(reportBlob, 'employee_import_report.csv')}
            >
              Download report (CSV)
            </button>
          </div>
          <ReportTable rows={report} />
        </div>
      )}
      <div className="row-end">
        <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>Close</button>
      </div>
    </Modal>
  );
}

/** Bulk asset creation: template → upload → preview → confirm → report. */
export function AssetBulkCreateModal({ onClose, onImported }) {
  const [file, setFile, pick] = useCsvFile();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState(null);
  const [report, setReport] = useState(null);
  const [reportBlob, setReportBlob] = useState(null);

  const doPreview = async () => {
    if (!file || busy) return;
    setBusy(true);
    setError('');
    setPreview(null);
    setReport(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('preview', 'true');
      const r = await api.post('/assets/bulk_create/', fd);
      setPreview(r.data);
    } catch (e) {
      setError(parseApiError(e).global || 'Preview failed.');
    } finally {
      setBusy(false);
    }
  };

  const doConfirm = async () => {
    if (!file || busy) return;
    if (!confirm('Create the previewed assets? Existing tags will be skipped.')) return;
    setBusy(true);
    setError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('preview', 'false');
      fd.append('confirm', 'true');
      const r = await api.post('/assets/bulk_create/?download=csv', fd, { responseType: 'blob' });
      const text = await r.data.text();
      const rows = parseCSV(text);
      const [, ...body] = rows;
      setReport(body.map(([row, key, outcome, message]) => ({ row, key, outcome, message })));
      setReportBlob(r.data);
      onImported();
    } catch (e) {
      setError(await blobErrorMessage(e, 'Bulk create failed.'));
    } finally {
      setBusy(false);
    }
  };

  const okCount = preview?.preview?.length ?? 0;
  const errCount = preview?.errors?.length ?? 0;
  return (
    <Modal title="Bulk create assets" size="lg" onClose={() => { if (!busy) onClose(); }}>
      <p className="muted small modal-intro">
        1. Download the template. 2. Upload the filled CSV/XLSX. 3. Preview. 4. Confirm.
        Assignment is never set by bulk create — use Assign afterwards.
      </p>
      <div className="row-gap" style={{ marginBottom: 'var(--sp-3)' }}>
        <button
          type="button" className="btn-ghost" disabled={busy}
          onClick={() => downloadTemplate('/assets/bulk_create/?download=csv', 'asset_import_template.csv', setError)}
        >
          Download template
        </button>
        <input type="file" accept=".csv,.xlsx,.xlsm" onChange={pick} disabled={busy} aria-label="Import file" />
      </div>
      {error && <div className="error-summary" role="alert">{error}</div>}
      <div className="row-gap">
        <button type="button" className="btn-secondary" onClick={doPreview} disabled={busy || !file}>
          {busy ? 'Working…' : 'Preview'}
        </button>
        {preview && (
          <button type="button" className="btn-primary" onClick={doConfirm} disabled={busy}>
            {busy ? 'Working…' : `Confirm create (${okCount} new)`}
          </button>
        )}
      </div>
      {preview && (
        <div className="modal-block">
          <p className="muted small">{okCount} would be created · {errCount} invalid rows.</p>
          {errCount > 0 && (
            <ReportTable rows={preview.errors.map((e) => ({
              row: e.row ?? '',
              key: e.asset_tag ?? '',
              outcome: 'failed',
              message: typeof e.errors === 'string' ? e.errors : JSON.stringify(e.errors),
            }))} />
          )}
        </div>
      )}
      {report && (
        <div className="modal-block">
          <div className="row-gap" style={{ marginBottom: 'var(--sp-2)' }}>
            <b>Create result</b>
            <button
              type="button" className="btn-small"
              onClick={() => reportBlob && downloadBlob(reportBlob, 'asset_import_report.csv')}
            >
              Download report (CSV)
            </button>
          </div>
          <ReportTable rows={report} />
        </div>
      )}
      <div className="row-end">
        <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>Close</button>
      </div>
    </Modal>
  );
}
