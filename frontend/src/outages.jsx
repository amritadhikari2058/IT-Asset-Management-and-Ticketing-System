/* 
 * Employee Outages - safe outage display for employees
 * Route: #/outages
 */

import React, { useEffect } from 'react';
import { PageHeader } from './components';
import { useAuth } from './auth';

export function EmployeeOutages() {
  const { role } = useAuth();

  useEffect(() => {
    // Employees should only see safe outage data, not internal change data
  }, [role]);

  return (
    <div>
      <PageHeader title="Outages" />
      <div className="mt-3">
        <p>Outages view for employees - only public information displayed</p>
        <hr />
        <div>
          <p><strong>Service:</strong> —</p>
          <p><strong>Public Title:</strong> —</p>
          <p><strong>Public Summary:</strong> —</p>
          <p><strong>Planned Start:</strong> —</p>
          <p><strong>Planned End:</strong> —</p>
          <p><strong>Status:</strong> —</p>
          <p><strong>Expected Impact:</strong> —</p>
          <p><strong>Last Update:</strong> —</p>
        </div>
      </div>
    </div>
  );
}