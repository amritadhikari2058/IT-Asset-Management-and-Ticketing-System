import { useCallback, useEffect, useState } from 'react';
import api from './api';
import {
  DataTable, Field, LoadingRows,
} from './components';
import {
  ATTACHMENT_DOCUMENT_TYPES,
  buildAttachmentListUrl,
  filenameFromContentDisposition,
  formatDateTime,
  parseFieldErrors,
  safeResults,
} from './procurement-utils';

/**
 * Protected attachment panel for one procurement record.
 *
 * Downloads go through the authenticated API as a blob; the object URL is
 * always revoked, and no token is ever placed in a query string.
 */
export function ProcurementAttachments({
  parentType, parentId, canUpload = false, title = 'Attachments',
}) {
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
      const response = await api.get(buildAttachmentListUrl(parentType, parentId));
      setRows(safeResults(response.data));
    } catch (e) {
      setError(parseFieldErrors(e).global || 'Could not load attachments.');
    } finally {
      setLoading(false);
    }
  }, [parentType, parentId]);

  useEffect(() => { load(); }, [load]); // eslint-disable-line react/set-state-in-effect

  const upload = async (event) => {
    event.preventDefault();
    if (!file) {
      setError('Choose a file to upload.');
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    const formData = new FormData();
    formData.append(parentType, String(parentId));
    formData.append('document_type', documentType);
    formData.append('description', description.trim());
    formData.append('file', file);
    try {
      await api.post('/procurement/attachments/', formData);
      setNotice('Attachment uploaded.');
      setFile(null);
      setDescription('');
      setDocumentType('other');
      await load();
    } catch (e) {
      const parsed = parseFieldErrors(e);
      setError(parsed.global || Object.values(parsed.fields)[0] || 'Upload failed.');
    } finally {
      setBusy(false);
    }
  };

  const download = async (row) => {
    setDownloading(row.id);
    setError('');
    try {
      const response = await api.get(
        `/procurement/attachments/${row.id}/download/`, { responseType: 'blob' },
      );
      const filename = filenameFromContentDisposition(
        response.headers?.['content-disposition'], row.original_filename || 'download',
      );
      const url = window.URL.createObjectURL(response.data);
      try {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        window.URL.revokeObjectURL(url);
      }
    } catch (e) {
      const status = e?.response?.status;
      if (status === 404) {
        setError('This attachment is unavailable or you no longer have access.');
      } else {
        setError(parseFieldErrors(e).global || 'Could not download the attachment.');
      }
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <div className="panel-head"><h3>{title}</h3></div>
      <div className="panel-pad">
        {error ? <div className="field-error" role="alert">{error}</div> : null}
        {notice ? <div className="success-summary" role="status">{notice}</div> : null}
        {loading ? <LoadingRows /> : (
          <DataTable
            columns={[
              { key: 'original_filename', label: 'File' },
              { key: 'document_type', label: 'Type', render: (r) => String(r.document_type || '').replace(/_/g, ' ') },
              { key: 'description', label: 'Description', render: (r) => r.description || '—' },
              { key: 'uploaded_by_name', label: 'Uploaded by', render: (r) => r.uploaded_by_name || '—' },
              { key: 'created_at', label: 'Uploaded', render: (r) => formatDateTime(r.created_at) },
              { key: 'status', label: 'Status', render: (r) => r.status || 'active' },
              {
                key: 'actions',
                label: 'Actions',
                render: (r) => (
                  <button
                    type="button" className="btn-ghost btn-small"
                    onClick={() => download(r)}
                    disabled={downloading === r.id || r.status === 'archived'}
                  >
                    {downloading === r.id ? 'Downloading…' : 'Download'}
                  </button>
                ),
              },
            ]}
            rows={rows}
            keyOf={(r) => `attachment-${r.id}`}
            emptyTitle="No attachments."
            emptyHint="Supporting documents appear here."
          />
        )}

        {canUpload ? (
          <form onSubmit={upload} style={{ marginTop: 12 }}>
            <div className="row-gap">
              <Field label="Document type">
                <select
                  className="input" value={documentType}
                  onChange={(e) => setDocumentType(e.target.value)}
                  aria-label="Document type"
                >
                  {ATTACHMENT_DOCUMENT_TYPES.map((type) => (
                    <option key={type} value={type}>{type.replace(/_/g, ' ')}</option>
                  ))}
                </select>
              </Field>
              <Field label="File">
                <input
                  type="file" className="input" aria-label="Attachment file"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
              </Field>
            </div>
            <Field label="Description">
              <input
                className="input" value={description}
                onChange={(e) => setDescription(e.target.value)}
                aria-label="Attachment description"
              />
            </Field>
            <button type="submit" className="btn-primary" disabled={busy || !file}>
              {busy ? 'Uploading…' : 'Upload attachment'}
            </button>
          </form>
        ) : null}
      </div>
    </div>
  );
}
