/* 
 * Change Tasks - task checklist for a change
 * Route: #/changes/:id/tasks
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Select, Row, Col } from './components';
import { useAuth } from './auth';
import api from './api';
import { fetchPage, parseApiError } from './changes-utils';

export function ChangeTasks({ match }) {
  useAuth();
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const id = match.params.id;
    if (!id) return;
    fetchPage(`/changes/${id}/tasks/`)
      .then((data) => {
        setTasks(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(parseApiError(e));
        setLoading(false);
      });
  }, [match.params.id]);

  const updateTaskStatus = async (taskId, status) => {
    try {
      await api.patch(`/changes/${match.params.id}/tasks/${taskId}/`, { status });
      setTasks((prev) => prev.map((t) => (t.id === taskId ? { ...t, status } : t)));
    } catch (e) {
      setError(parseApiError(e));
    }
  };

  if (loading) {
    return <div className="mt-3"><p>Loading tasks…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error.global ?? 'Unknown error'}</p></div>;
  }

  return (
    <div>
      <PageHeader title="Task Checklist" subtitle={tasks.length > 0 ? tasks[0].change_number : ''} />
      <div className="mt-3">
        <p><strong>Total Tasks:</strong> {tasks.length}</p>
        <p><strong>Completed:</strong> {tasks.filter(t => t.status === 'completed').length}</p>
        <p><strong>Blocked:</strong> {tasks.filter(t => t.status === 'blocked').length}</p>
        {tasks.length === 0 ? (<p>No tasks found</p>) : (
          <div>
            {tasks.map((t, i) => (
              <div key={t.id || i} className="mt-3 p-2 border rounded">
                <Row>
                  <Col sm={4}><strong>Title:</strong> {t.title}</Col>
                  <Col sm={2}><strong>Status:</strong> {t.status}</Col>
                  <Col sm={4}><strong>Assigned:</strong> {t.assigned_to ? t.assigned_to.employee_id : 'Unassigned'}</Col>
                  <Col sm={2}>
                    {isStaff && (
                      <Select value={t.status} onChange={(e) => updateTaskStatus(t.id, e.target.value)}>
                        <option value="pending">Pending</option>
                        <option value="in_progress">In Progress</option>
                        <option value="completed">Completed</option>
                        <option value="blocked">Blocked</option>
                      </Select>
                    )}
                  </Col>
                </Row>
                <Row className="mt-1">
                  <Col sm={12}><strong>Description:</strong> {t.description || ''}</Col>
                </Row>
                {t.evidence && (
                  <Row className="mt-2">
                    <Col sm={12}><strong>Evidence:</strong> {t.evidence.filename}</Col>
                  </Row>
                )}
                {t.blocks_implementation && (
                  <Row className="mt-2">
                    <Col sm={12}><p className="text-danger"><strong>Blocks implementation</strong></p></Col>
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