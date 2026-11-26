/* 
 * Change Attachments - file attachments for a change
 * Route: #/changes/:id/attachments
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Row, Col } from '../../components';
import { useAuth } from '../../auth';
import { fetchPage, parseApiError } from '../../shared/changes-utils';

export function ChangeAttachments({ match }) {
  useAuth();
  const [attachments, setAttachments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const id = match.params.id;
    if (!id) return;
    fetchPage(`/changes/${id}/attachments/`)
      .then((data) => {
        setAttachments(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [match.params.id]);

  if (loading) {
    return <div className="mt-3"><p>Loading attachments…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  return (
    <div>
      <PageHeader title="Attachments" subtitle={attachments.length > 0 ? attachments[0].change_number : ''} />
      <div className="mt-3">
        <p><strong>Total Attachments:</strong> {attachments.length}</p>
        {attachments.length === 0 ? (
          <p>No attachments found</p>
        ) : (
          <div>
            {attachments.map((a, i) => (
              <div key={a.id || i} className="mt-3 p-2 border rounded">
                <Row>
                  <Col sm={4}><strong>Document Type:</strong> {a.document_type}</Col>
                  <Col sm={4}><strong>Filename:</strong> {a.filename}</Col>
                  <Col sm={4}><strong>Uploader:</strong> {a.uploader?.employee_id || '—'}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}>
                    {a.checksum && (
                      <p><strong>Checksum:</strong> {a.checksum}</p>
                    )}
                    <a href={a.download_url} className="btn-small btn-secondary w-100">
                      Download
                    </a>
                  </Col>
                </Row>
                {a.task_association && (
                  <Row className="mt-2">
                    <Col sm={12}><small>Task: {a.task_association}</small></Col>
                  </Row>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
