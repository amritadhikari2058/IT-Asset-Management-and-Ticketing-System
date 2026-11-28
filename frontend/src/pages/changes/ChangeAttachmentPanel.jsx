import React, { useCallback, useEffect, useState } from 'react';
import api from '../../api';

const DOCUMENT_TYPES = [
  ['implementation_plan', 'Implementation Plan'],
  ['test_evidence', 'Test Evidence'],
  ['rollback_plan', 'Rollback Plan'],
  ['approval_evidence', 'Approval Evidence'],
  ['backup_evidence', 'Backup Evidence'],
  ['communication', 'Communication'],
  ['validation_evidence', 'Validation Evidence'],
  ['pir_evidence', 'PIR Evidence'],
  ['vendor_document', 'Vendor Document'],
  ['other', 'Other'],
];

function responseRows(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  return [];
}

function getDownloadFilename(header, fallback) {
  if (!header) return fallback;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  if (!match) return fallback;

  try {
    return decodeURIComponent(match[1].trim());
  } catch {
    return match[1].trim() || fallback;
  }
}

function formatSize(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size < 0) return '—';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatUploadedAt(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

export function ChangeAttachmentPanel({ changeId }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [documentType, setDocumentType] = useState('other');
  const [description, setDescription] = useState('');
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');

    try {
      const response = await api.get('/changes/attachments/');
      const allRows = responseRows(response.data);
      setRows(allRows.filter((row) => String(row.change) === String(changeId)));
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load change attachments.');
    } finally {
      setLoading(false);
    }
  }, [changeId]);

  useEffect(() => {
    load();
  }, [load]);

  const upload = async (event) => {
    event.preventDefault();

    // Capture the form before awaiting; React may clear currentTarget afterwards.
    const form = event.currentTarget;

    if (!file) {
      setError('Choose a file to upload.');
      return;
    }

    setBusy(true);
    setError('');
    setNotice('');

    const formData = new FormData();
    formData.append('change', String(changeId));
    formData.append('document_type', documentType);
    formData.append('description', description.trim());
    formData.append('file', file);

    try {
      await api.post('/changes/attachments/', formData);

      setNotice('Attachment uploaded successfully.');
      setFile(null);
      setDescription('');
      setDocumentType('other');

      const fileInput = form.querySelector('input[type="file"]');
      if (fileInput) fileInput.value = '';

      await load();
    } catch (err) {
      const data = err?.response?.data;
      const detail = data?.detail
        || Object.values(data || {}).flat().filter(Boolean).join(' ');

      setError(detail || 'Could not upload the attachment.');
    } finally {
      setBusy(false);
    }
  };

  const download = async (row) => {
    setDownloading(row.id);
    setError('');

    try {
      const response = await api.get(
        `/changes/attachments/${row.id}/download/`,
        { responseType: 'blob' },
      );

      const filename = getDownloadFilename(
        response.headers?.['content-disposition'],
        row.original_filename || 'download',
      );

      const objectUrl = window.URL.createObjectURL(response.data);

      try {
        const anchor = document.createElement('a');
        anchor.href = objectUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        window.URL.revokeObjectURL(objectUrl);
      }
    } catch (err) {
      const status = err?.response?.status;
      setError(
        status === 404 || status === 410
          ? 'This attachment is unavailable or you no longer have access.'
          : 'Could not download the attachment.',
      );
    } finally {
      setDownloading(null);
    }
  };

  return (
    <section className="mt-3" aria-label="Change attachments">
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h3>Attachments</h3>
        <span>Total: {rows.length}</span>
      </div>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      {loading ? (
        <p role="status">Loading attachments…</p>
      ) : rows.length === 0 ? (
        <p>No attachments have been uploaded for this change.</p>
      ) : (
        <div className="table-responsive">
          <table className="table table-striped">
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Document Type</th>
                <th scope="col">Description</th>
                <th scope="col">Uploaded By</th>
                <th scope="col">Size</th>
                <th scope="col">Uploaded</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.original_filename || 'Unnamed file'}</td>
                  <td>{String(row.document_type || '').replace(/_/g, ' ')}</td>
                  <td>{row.description || '—'}</td>
                  <td>{row.uploaded_by_email || '—'}</td>
                  <td>{formatSize(row.size)}</td>
                  <td>{formatUploadedAt(row.created_at)}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-sm btn-secondary"
                      onClick={() => download(row)}
                      disabled={downloading === row.id}
                    >
                      {downloading === row.id ? 'Downloading…' : 'Download'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-4">
        <h4>Upload Attachment</h4>
        <form onSubmit={upload}>
          <div className="mb-3">
            <label className="form-label" htmlFor="change-attachment-type">
              Document type
            </label>
            <select
              id="change-attachment-type"
              className="form-select"
              value={documentType}
              onChange={(event) => setDocumentType(event.target.value)}
            >
              {DOCUMENT_TYPES.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>

          <div className="mb-3">
            <label className="form-label" htmlFor="change-attachment-file">File</label>
            <input
              id="change-attachment-file"
              className="form-control"
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
          </div>

          <div className="mb-3">
            <label className="form-label" htmlFor="change-attachment-description">
              Description
            </label>
            <textarea
              id="change-attachment-description"
              className="form-control"
              rows="2"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>

          <button type="submit" className="btn btn-primary" disabled={busy || !file}>
            {busy ? 'Uploading…' : 'Upload attachment'}
          </button>
        </form>
      </div>
    </section>
  );
}