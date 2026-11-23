/* 
 * Change Review Meetings - change review meetings
 * Route: #/change-review-meetings
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Row, Col } from './components';
import { useAuth } from './auth';
import { fetchPage, parseApiError } from './changes-utils';

export function ChangeReviewMeetings() {
  const { isStaff, role } = useAuth();
  const [meetings, setMeetings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isStaff && role !== 'it_manager') {
      setMeetings([]); // eslint-disable-line react/set-state-in-effect
      setLoading(false); // eslint-disable-line react/set-state-in-effect
      return;
    }
    fetchPage(`/change-review-meetings/`)
      .then((data) => {
        setMeetings(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [isStaff, role]);

  if (loading) {
    return <div className="mt-3"><p>Loading meetings…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  return (
    <div>
      <PageHeader title="Review Meetings" />
      <div className="mt-3">
        <p><strong>Total Meetings:</strong> {meetings.length}</p>
        {meetings.length === 0 ? (
          <p>No meetings found</p>
        ) : (
          <div>
            {meetings.map((m, i) => (
              <div key={m.id || i} className="mt-3 p-2 border rounded">
                <Row>
                  <Col sm={6}><strong>Meeting Date:</strong> {m.meeting_date}</Col>
                  <Col sm={6}><strong>Change:</strong> {m.change?.change_number}</Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}>
                    <strong>Agenda:</strong> {m.agenda}
                  </Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={6}><strong>Attendees:</strong> {m.attendees || '—'}</Col>
                  <Col sm={6}>
                    {m.recommendation && (
                      <p><strong>Recommendation:</strong> {m.recommendation}</p>
                    )}
                  </Col>
                </Row>
                {m.defer && (
                  <Row className="mt-2">
                    <Col sm={12}><small>Deferred</small></Col>
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