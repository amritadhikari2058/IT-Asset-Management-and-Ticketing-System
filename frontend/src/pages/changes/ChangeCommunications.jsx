/* 
 * Change Communications - communications for a change
 * Route: #/changes/:id/communications
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Row, Col } from '../../components';
import { useAuth } from '../../auth';
import { fetchPage, parseApiError } from '../../shared/changes-utils';

export function ChangeCommunications({ match }) {
  useAuth();
  const [communications, setCommunications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const id = match.params.id;
    if (!id) return;
    fetchPage(`/changes/${id}/communications/`)
      .then((data) => {
        setCommunications(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [match.params.id]);

  if (loading) {
    return <div className="mt-3"><p>Loading communications…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  return (
    <div>
      <PageHeader title="Communications" subtitle={communications.length > 0 ? communications[0].change_number : ''} />
      <div className="mt-3">
        <p><strong>Total Communications:</strong> {communications.length}</p>
        {communications.length === 0 ? (
          <p>No communications found</p>
        ) : (
          <div>
            {communications.map((c, i) => (
              <div key={c.id || i} className="mt-3 p-2 border rounded">
                <Row>
                  <Col sm={3}><strong>Type:</strong> {c.type}</Col>
                  <Col sm={3}><strong>Audience:</strong> {c.audience}</Col>
                  <Col sm={3}><strong>Subject:</strong> {c.subject}</Col>
                  <Col sm={3}><strong>Status:</strong> {c.status}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}>
                    {c.schedule && <p><strong>Scheduled:</strong> {c.schedule}</p>}
                    {c.sent_date && <p><strong>Sent:</strong> {c.sent_date}</p>}
                  </Col>
                </Row>
                {c.message && (
                  <Row className="mt-2">
                    <Col sm={12}><strong>Message:</strong> {c.message}</Col>
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
