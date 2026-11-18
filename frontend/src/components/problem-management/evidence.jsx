import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from '../../auth';
import { Button, DataTable, Field, Input, LoadingRows, PageHeader, Panel, PanelPad } from '../../components';
import { archiveEvidence, listEvidence, uploadEvidence } from '../../services/problem-management';

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.txt,.csv,.log,.docx,.xlsx';
const MAX_BYTES = 10 * 1024 * 1024;

const formatSize = (bytes) => {
  if (!bytes) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

export function Evidence({ problemId: problemIdProp }) {
  const params = useParams();
  const problemId = problemIdProp ?? params.id;
  const { isStaff } = useAuth();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [archivingId, setArchivingId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listEvidence(problemId);
      setRows(Array.isArray(data) ? data : data?.results ?? []);
    } catch {
      setError('Could not load evidence.');
    } finally {
      setLoading(false);
    }
  }, [problemId]);

  useEffect(() => { load(); }, [load]);

  const selectFile = (ev) => {
    const chosen = ev.target.files?.[0] ?? null;
    if (chosen && chosen.size > MAX_BYTES) {
      setError('The file is larger than the 10 MB limit.');
      setFile(null);
      return;
    }
    setError('');
    setFile(chosen);
  };

  const upload = async () => {
    if (!file || uploading) return;
    setUploading(true);
    setError('');
    try {
      await uploadEvidence(problemId, file, null);
      setFile(null);
      await load();
    } catch (e) {
      setError(e?.response?.status === 403
        ? 'You do not have permission to upload evidence.'
        : 'Upload failed.');
    } finally {
      setUploading(false);
    }
  };

  const archive = async (row) => {
    if (archivingId) return;
    setArchivingId(row.id);
    setError('');
    try {
      await archiveEvidence(row.id);
      await load();
    } catch (e) {
      setError(e?.response?.status === 403
        ? 'You do not have permission to archive evidence.'
        : 'Archive failed.');
    } finally {
      setArchivingId(null);
    }
  };

  const columns = useMemo(() => [
    { key: 'original_filename', label: 'Stored filename' },
    { key: 'file_type', label: 'Type', render: (r) => r.file_type || '—' },
    { key: 'file_size', label: 'Size', render: (r) => formatSize(r.file_size) },
    { key: 'uploaded_at', label: 'Uploaded', render: (r) => (r.uploaded_at ? new Date(r.uploaded_at).toLocaleString() : '—') },
    { key: 'status', label: 'Status', render: (r) => (r.archived ? 'Archived' : 'Active') },
    {
      key: 'actions',
      label: 'Actions',
      render: (r) => (r.archived
        ? 'Archived'
        : (
          <Button
            kind="ghost"
            size="small"
            disabled={!isStaff || archivingId === r.id}
            onClick={() => archive(r)}
          >
            {archivingId === r.id ? 'Archiving…' : 'Archive'}
          </Button>
        )),
    },
  ], [isStaff, archivingId]);

  return (
    <div>
      <PageHeader title="Evidence" sub="Files attached to this problem" />
      {error && <div className="error-summary" role="alert">{error}</div>}
      {loading ? <LoadingRows n={3} /> : (
        <Panel>
          <PanelPad>
            <DataTable columns={columns} rows={rows} keyOf={(r) => r.id} emptyTitle="No evidence yet" />
          </PanelPad>
        </Panel>
      )}

      {isStaff && (
        <Panel>
          <PanelPad>
            <Field label="Attach a file" hint="PDF, images, text, CSV, Word or Excel, up to 10 MB.">
              <Input type="file" accept={ACCEPT} onChange={selectFile} />
            </Field>
            {file && <p>Selected: {file.name}</p>}
            <Button onClick={upload} disabled={!file || uploading}>
              {uploading ? 'Uploading…' : 'Upload Evidence'}
            </Button>
          </PanelPad>
        </Panel>
      )}
    </div>
  );
}
