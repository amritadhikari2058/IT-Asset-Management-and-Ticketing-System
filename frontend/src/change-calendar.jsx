/* 
 * Change Calendar - bounded calendar of changes
 * Route: #/changes/calendar
 * Uses native Date, no calendar dependency
 */

import React, { useEffect, useState } from 'react';
import { PageHeader, Badge } from './components';
import { useAuth } from './auth';
import { fetchPage } from './changes-utils';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
];

export function ChangeCalendar() {
  const { isStaff, role } = useAuth();
  const [month, setMonth] = useState(new Date());
  const [changes, setChanges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const selectedMonth = month.getMonth();
  const selectedYear = month.getFullYear();

  useEffect(() => {
    if (!isStaff) {
      setChanges([]);
      setLoading(false);
      return;
    }
    fetchPage(`/changes/calendar?start=${selectedYear}-${selectedMonth + 1}-01&end=${selectedYear}-${selectedMonth + 1}-31`)
      .then((data) => {
        setChanges(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(e);
        setLoading(false);
      });
  }, [selectedMonth, selectedYear, isStaff]);

  if (loading) {
    return <div className="mt-3"><p>Loading calendar…</p></div>;
  }

  if (error) {
    return <div className="mt-3"><p className="text-danger">Error: {error?.global ?? 'Unknown error'}</p></div>;
  }

  // Generate month grid
  const firstDay = new Date(selectedYear, selectedMonth, 1);
  const lastDay = new Date(selectedYear, selectedMonth + 1, 0);
  const prevMonthLastDay = new Date(selectedYear, selectedMonth, 0).getDate();
  const prevMonth = selectedMonth === 0 ? 11 : selectedMonth - 1;
  const prevYear = selectedMonth === 0 ? selectedYear - 1 : selectedYear;
  const daysInMonth = lastDay.getDate();
  const firstDayIndex = firstDay.getDay();
  const lastDayIndex = lastDay.getDay();

  const totalCells = 42; // 6 weeks
  const dayCells = [];

  // Previous month days
  for (let i = 0; i < firstDayIndex; i++) {
    dayCells.push({
      day: prevMonthLastDay - firstDayIndex + 1 + i,
      month: prevMonth,
      year: prevYear,
      isOtherMonth: true,
      changeCount: 0
    });
  }

  // Current month days
  for (let i = 1; i <= daysInMonth; i++) {
    const date = new Date(selectedYear, selectedMonth, i);
    const changeCount = changes.filter(c => {
      const planned = new Date(c.planned_start);
      return planned.getMonth() === selectedMonth && planned.getFullYear() === selectedYear;
    }).length;
    dayCells.push({
      day: i,
      month: selectedMonth,
      year: selectedYear,
      isOtherMonth: false,
      changeCount
    });
  }

  // Next month days
  const totalShown = dayCells.length;
  const remaining = 42 - totalShown;
  for (let i = 1; i <= remaining; i++) {
    const date = new Date(selectedYear, selectedMonth + 1, i);
    dayCells.push({
      day: i,
      month: selectedMonth + 1 > 11 ? 0 : selectedMonth + 1,
      year: selectedMonth + 1 > 11 ? selectedYear + 1 : selectedYear,
      isOtherMonth: true,
      changeCount: 0
    });
  }

  return (
    <div>
      <PageHeader title="Change Calendar" />
      <div className="mt-3">
        <div className="d-flex justify-content-between align-items-center mb-3">
          <button onClick={() => setMonth(new Date(selectedYear, selectedMonth - 1, 1))} disabled={selectedMonth === 0} className="btn btn-link">
            Previous
          </button>
          <span>{MONTHS[selectedMonth]} {selectedYear}</span>
          <button onClick={() => setMonth(new Date(selectedYear, selectedMonth + 1, 1))} className="btn btn-link">
            Next
          </button>
        </div>
        <button onClick={() => setMonth(new Date())} className="btn btn-sm btn-outline-secondary mt-2">Today</button>
        <div className="table-responsive mt-3">
          <table className="table table-sm mb-0">
            <thead>
              <tr>
                <th>Sun</th>
                <th>Mon</th>
                <th>Tue</th>
                <th>Wed</th>
                <th>Thu</th>
                <th>Fri</th>
                <th>Sat</th>
              </tr>
            </thead>
            <tbody>
              {dayCells.map((cell, i) => (
                <tr key={i}>
                  <td className={cell.isOtherMonth ? 'text-secondary' : ''}>
                    {cell.isOtherMonth ? '' : cell.day}
                    {cell.changeCount > 0 && (
                      <Badge variant="secondary" className="ms-1 small">
                        {cell.changeCount}+
                      </Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 small text-secondary">
          <p>Filters: department • service • Asset • type • risk • status • implementation lead • maintenance window</p>
          <p>Event fields: Change number • title • type • status • risk • planned start • planned end • downtime • department • conflict count</p>
          <p>Requirements: accessible labels • status text • mobile agenda • loading • empty • retry • no drag-and-drop rescheduling • explicit link to Change detail</p>
        </div>
      </div>
    </div>
  );
}