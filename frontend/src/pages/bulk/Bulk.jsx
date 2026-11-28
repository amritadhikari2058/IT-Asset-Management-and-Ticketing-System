import { useState } from 'react';
import api from '../../api';
import { useAuth } from '../../auth';
import { DepartmentSelect, Field, Modal } from '../../components';
import {
  blobErrorMessage, downloadBlob, fieldMsg, parseApiError, parseCSV,
} from '../../api-utils';

const ALL_ROLES = [
  ['system_admin', 'System Admin'],
  ['it_manager', 'IT Manager'],
  ['it_support', 'IT Support'],
  ['employee', 'Employee'],
];

/** Bulk ticket creation: CSV/XLSX import, preview, confirm, report. */
export function TicketBulkCreateModal({ onClose, onCreated }) {
  const [file, , pickFile] = useCsvFile();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState(null);
  const [report, setReport] = useState(null);
  const [reportBlob, setReportBlob] = useState(null);
  const [importToken, setImportToken] = useState('');

  const newImportToken = () => {
    try {
      if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    } catch {
      // ignore
    }
    return `bulk-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  };

  const pick = (e) => {
    pickFile(e);
    setPreview(null);
    setReport(null);
    setReportBlob(null);
    setError('');
    setImportToken('');
  };

  const doPreview = async () => {
    if (!file || busy) return;
    const token = importToken || newImportToken();
    if (!importToken) setImportToken(token);
    setBusy(true);
    setError('');
    setPreview(null);
    setReport(null);
    setReportBlob(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('preview', 'true');
      fd.append('import_token', token);
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
    const token = importToken || newImportToken();
    if (!importToken) setImportToken(token);
    setBusy(true);
    setError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('preview', 'false');
      fd.append('confirm', 'true');
      fd.append('import_token', token);
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
    const employeeId = form.employee_id.trim();
    const email = form.email.trim();
    const password = form.password;
    if (!employeeId) {
      setFieldErrors((prev) => ({ ...prev, employee_id: ['Employee ID is required.'] }));
      return;
    }
    if (!email) {
      setFieldErrors((prev) => ({ ...prev, email: ['Email is required.'] }));
      return;
    }
    if (String(password ?? '').length < 8) {
      setFieldErrors((prev) => ({ ...prev, password: ['Password must be at least 8 characters.'] }));
      return;
    }
    const payload = {
      employee_id: employeeId,
      username: form.username.trim() || email,
      email,
      password,
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
  const [file, , pick] = useCsvFile();
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

/** CSV-based employee updates keyed by employee_id. */
export function EmployeeBulkUpdateModal({ onClose, onUpdated }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [rows, setRows] = useState([]);
  const [preview, setPreview] = useState(null);
  const [report, setReport] = useState(null);

  const allowed = [
    'employee_id',
    'email',
    'first_name',
    'last_name',
    'phone',
    'job_title',
    'home_department',
    'is_active',
  ];

  const pickFile = (event) => {
    setFile(event.target.files?.[0] ?? null);
    setRows([]);
    setPreview(null);
    setReport(null);
    setError('');
  };

  const parseFile = async () => {
    if (!file) throw new Error('Choose a CSV file first.');

    if (!file.name.toLowerCase().endsWith('.csv')) {
      throw new Error('Please select a CSV file. Excel files are not supported by this workflow.');
    }

    const text = (await file.text()).replace(/^\uFEFF/, '');
    const parsed = parseCSV(text);

    if (parsed.length < 2) {
      throw new Error('The CSV must contain a header and at least one employee row.');
    }

    const headers = parsed[0].map((value) =>
      String(value ?? '').trim().toLowerCase()
    );

    if (headers.some((header) => !header)) {
      throw new Error('The CSV contains an empty column header.');
    }

    if (new Set(headers).size !== headers.length) {
      throw new Error('The CSV contains duplicate column headers.');
    }

    if (!headers.includes('employee_id')) {
      throw new Error('The CSV must include an employee_id column.');
    }

    const unsupported = headers.filter((header) => !allowed.includes(header));

    if (unsupported.length) {
      throw new Error(
        `Unsupported column(s): ${unsupported.join(', ')}. Roles and ticket-creation permissions cannot be bulk-updated.`
      );
    }

    const result = [];
    const seen = new Set();

    for (let index = 1; index < parsed.length; index += 1) {
      const cells = parsed[index];

      if (!cells.some((cell) => String(cell ?? '').trim() !== '')) {
        continue;
      }

      if (
        cells.length > headers.length &&
        cells.slice(headers.length).some((cell) => String(cell ?? '').trim())
      ) {
        throw new Error(`CSV row ${index + 1} contains more values than the header.`);
      }

      const raw = {};

      headers.forEach((header, column) => {
        raw[header] = String(cells[column] ?? '').trim();
      });

      const employeeId = raw.employee_id;

      if (!employeeId) {
        throw new Error(`CSV row ${index + 1} is missing employee_id.`);
      }

      if (seen.has(employeeId)) {
        throw new Error(`Duplicate employee_id "${employeeId}" in the CSV.`);
      }

      seen.add(employeeId);

      const update = { employee_id: employeeId };

      for (const field of allowed) {
        if (field === 'employee_id' || raw[field] == null || raw[field] === '') continue;

        if (field === 'is_active') {
          const value = raw[field].toLowerCase();

          if (value !== 'true' && value !== 'false') {
            throw new Error(
              `CSV row ${index + 1}: is_active must be true or false.`
            );
          }

          update.is_active = value === 'true';
        } else {
          update[field] = raw[field];
        }
      }

      if (Object.keys(update).length === 1) {
        throw new Error(
          `CSV row ${index + 1} has no update values besides employee_id.`
        );
      }

      result.push(update);
    }

    if (!result.length) {
      throw new Error('No employee update rows were found.');
    }

    return result;
  };

  const doPreview = async () => {
    if (!file || busy) return;

    setBusy(true);
    setError('');
    setPreview(null);
    setReport(null);

    try {
      const parsedRows = await parseFile();
      setRows(parsedRows);

      const response = await api.post('/accounts/users/bulk_update/', {
        rows: parsedRows,
        preview: true,
      });

      setPreview(response.data);
    } catch (e) {
      setError(
        e?.message ||
        parseApiError(e).global ||
        'Bulk update preview failed.'
      );
    } finally {
      setBusy(false);
    }
  };

  const doConfirm = async () => {
    if (!rows.length || !preview || busy) return;

    if (!window.confirm(
      `Submit ${rows.length} employee update row(s)? The preview checks existence only; individual updates may still be skipped or fail.`
    )) return;

    setBusy(true);
    setError('');

    try {
      const response = await api.post('/accounts/users/bulk_update/', {
        rows,
        preview: false,
        confirm: true,
      });

      const data = response.data ?? {};
      const successful = Array.isArray(data.successful) ? data.successful : [];
      const skipped = Array.isArray(data.skipped) ? data.skipped : [];
      const failed = Array.isArray(data.failed) ? data.failed : [];

      setReport([
        ...successful.map((employeeId) => ({
          row: '',
          key: employeeId,
          outcome: 'successful',
          message: '',
        })),
        ...skipped.map((item) => ({
          row: '',
          key: item.employee_id ?? '',
          outcome: 'skipped',
          message: item.reason ?? 'Skipped',
        })),
        ...failed.map((item) => ({
          row: '',
          key: item.employee_id ?? '',
          outcome: 'failed',
          message: typeof item.errors === 'string'
            ? item.errors
            : JSON.stringify(item.errors ?? 'Update failed'),
        })),
      ]);

      setPreview(null);
      onUpdated?.();
    } catch (e) {
      setError(
        parseApiError(e).global || 'Bulk update could not be completed.'
      );
    } finally {
      setBusy(false);
    }
  };

  const previewRows = Array.isArray(preview?.preview)
    ? preview.preview
    : [];

  const existingCount = previewRows.filter(
    (item) => item.exists && !item.is_deleted
  ).length;

  const missingCount = previewRows.filter(
    (item) => !item.exists
  ).length;

  const deletedCount = previewRows.filter(
    (item) => item.exists && item.is_deleted
  ).length;

  return (
    <Modal
      title="Bulk update employees"
      size="lg"
      onClose={() => { if (!busy) onClose(); }}
    >
      <p className="muted small modal-intro">
        Upload a CSV using employee_id to match existing accounts.
        Blank cells are left unchanged. Department values must be department
        codes. Only email, names, phone, job title, department and active
        status can be updated. Roles and ticket-creation permissions are
        never changed.
      </p>

      <div className="row-gap" style={{ marginBottom: 'var(--sp-3)' }}>
        <button
          type="button"
          className="btn-ghost"
          disabled={busy}
          onClick={() => downloadBlob(
            new Blob(
              [
                'employee_id,email,first_name,last_name,phone,job_title,home_department,is_active\nE001,,,,,,IT,true\n',
              ],
              { type: 'text/csv;charset=utf-8' }
            ),
            'employee_bulk_update_template.csv'
          )}
        >
          Download CSV template
        </button>

        <input
          type="file"
          accept=".csv,text/csv"
          onChange={pickFile}
          disabled={busy}
          aria-label="Employee update CSV"
        />
      </div>

      {file && (
        <p className="muted small">Selected: {file.name}</p>
      )}

      {error && (
        <div className="error-summary" role="alert">{error}</div>
      )}

      <div className="row-gap">
        <button
          type="button"
          className="btn-secondary"
          onClick={doPreview}
          disabled={busy || !file}
        >
          {busy ? 'Working…' : 'Preview updates'}
        </button>

        {preview && (
          <button
            type="button"
            className="btn-primary"
            onClick={doConfirm}
            disabled={busy}
          >
            {busy ? 'Working…' : `Confirm ${rows.length} update(s)`}
          </button>
        )}
      </div>

      {preview && (
        <div className="modal-block">
          <b>Preview - {preview.affected ?? previewRows.length} row(s)</b>

          <p className="muted small">
            {existingCount} existing and active · {missingCount} not found ·
            {` ${deletedCount} deleted.`}
            {' '}This is an existence check only, not full field validation.
            The execution result may contain skipped or failed rows.
          </p>

          <ReportTable
            rows={previewRows.map((item) => ({
              row: '',
              key: item.employee_id ?? '',
              outcome: !item.exists
                ? 'not found'
                : item.is_deleted
                  ? 'deleted'
                  : 'exists',
              message: item.is_deleted
                ? 'Deleted accounts cannot be updated.'
                : '',
            }))}
          />
        </div>
      )}

      {report && (
        <div className="modal-block">
          <b>Bulk update result</b>

          <p className="muted small">
            {report.filter((item) => item.outcome === 'successful').length}
            {' '}successful ·
            {' '}{report.filter((item) => item.outcome === 'skipped').length}
            {' '}skipped ·
            {' '}{report.filter((item) => item.outcome === 'failed').length}
            {' '}failed.
          </p>

          <ReportTable rows={report} />
        </div>
      )}

      <div className="row-end">
        <button
          type="button"
          className="btn-ghost"
          onClick={onClose}
          disabled={busy}
        >
          Close
        </button>
      </div>
    </Modal>
  );
}

/** Bulk asset creation: template → upload → preview → confirm → report. */
export function AssetBulkCreateModal({ onClose, onImported }) {
  const [file, setFile] = useState(null);
  const pick = (e) => {
    setFile(e.target.files?.[0] ?? null);
    setPreview(null);
    setReport(null);
    setReportBlob(null);
    setError('');
  };
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

