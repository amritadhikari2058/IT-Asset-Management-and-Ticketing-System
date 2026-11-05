/*
 * Change Tests - Utility tests only
 */

import { describe, it, expect } from 'vitest';
import { ChangeUtils } from './changes-utils';

describe('Change Tests: STATUS_LABELS', () => {
  it('has draft label', () => {
    expect(ChangeUtils.STATUS_LABELS.draft).toBe('Draft');
  });

  it('has submitted label', () => {
    expect(ChangeUtils.STATUS_LABELS.submitted).toBe('Submitted');
  });

  it('has approved label', () => {
    expect(ChangeUtils.STATUS_LABELS.approved).toBe('Approved');
  });

  it('has completed label', () => {
    expect(ChangeUtils.STATUS_LABELS.completed).toBe('Completed');
  });
});

describe('Change Tests: RISK_LEVEL_LABELS', () => {
  it('has low label', () => {
    expect(ChangeUtils.RISK_LEVEL_LABELS.low).toBe('Low');
  });

  it('has critical label', () => {
    expect(ChangeUtils.RISK_LEVEL_LABELS.critical).toBe('Critical');
  });
});

describe('Change Tests: PRIORITY_LABELS', () => {
  it('has high label', () => {
    expect(ChangeUtils.PRIORITY_LABELS.high).toBe('High');
  });
});

describe('Change Tests: CHANGE_TYPE_LABELS', () => {
  it('has emergency label', () => {
    expect(ChangeUtils.CHANGE_TYPE_LABELS.emergency).toBe('Emergency');
  });
});

describe('Change Tests: formatDate', () => {
  it('formats a date', () => {
    expect(ChangeUtils.formatDate('2024-01-15')).toBeDefined();
  });

  it('returns empty for null', () => {
    expect(ChangeUtils.formatDate(null)).toBe('');
  });
});

describe('Change Tests: formatDuration', () => {
  it('formats 60 minutes', () => {
    expect(ChangeUtils.formatDuration(60)).toBe('1 hours');
  });

  it('returns empty for null', () => {
    expect(ChangeUtils.formatDuration(null)).toBe('');
  });
});

describe('Change Tests: statusBadgeVariant', () => {
  it('returns danger for completed', () => {
    expect(ChangeUtils.statusBadgeVariant('completed')).toBe('danger');
  });

  it('returns warning for in_progress', () => {
    expect(ChangeUtils.statusBadgeVariant('in_progress')).toBe('warning');
  });
});

describe('Change Tests: riskBadgeVariant', () => {
  it('returns success for low', () => {
    expect(ChangeUtils.riskBadgeVariant('low')).toBe('success');
  });
});

describe('Change Tests: priorityBadgeVariant', () => {
  it('returns secondary for low', () => {
    expect(ChangeUtils.priorityBadgeVariant('low')).toBe('secondary');
  });
});

describe('Change Tests: isTerminalStatus', () => {
  it('completed is terminal', () => {
    expect(ChangeUtils.isTerminalStatus('completed')).toBe(true);
  });

  it('draft is not terminal', () => {
    expect(ChangeUtils.isTerminalStatus('draft')).toBe(false);
  });
});

describe('Change Tests: isEditableStatus', () => {
  it('draft is editable', () => {
    expect(ChangeUtils.isEditableStatus('draft')).toBe(true);
  });

  it('completed is not editable', () => {
    expect(ChangeUtils.isEditableStatus('completed')).toBe(false);
  });
});

describe('Change Tests: safeResults', () => {
  it('returns empty for null', () => {
    expect(ChangeUtils.safeResults(null)).toEqual([]);
  });

  it('returns array as-is', () => {
    expect(ChangeUtils.safeResults([1, 2])).toEqual([1, 2]);
  });
});

describe('Change Tests: buildChangeListUrl', () => {
  it('empty with no filters', () => {
    expect(ChangeUtils.buildChangeListUrl({})).toBe('');
  });

  it('with type filter', () => {
    expect(ChangeUtils.buildChangeListUrl({ type: 'emergency' })).toBe('?type=emergency');
  });
});

describe('Change Tests: parseFieldErrors', () => {
  it('empty for null', () => {
    expect(ChangeUtils.parseFieldErrors(null)).toEqual({});
  });

  it('extracts field errors', () => {
    const e = { response: { data: { title: ['Required'] } } };
    expect(ChangeUtils.parseFieldErrors(e).title).toBe('Required');
  });
});

describe('Change Tests: actionAvailability', () => {
  it('admin can create', () => {
    expect(ChangeUtils.actionAvailability('system_admin', 'draft', 'create')).toBe(true);
  });

  it('support can create draft', () => {
    expect(ChangeUtils.actionAvailability('it_support', 'draft', 'create_draft')).toBe(true);
  });

  it('employee cannot approve', () => {
    expect(ChangeUtils.actionAvailability('employee', 'draft', 'approve')).toBe(false);
  });

  it('unknown role fails', () => {
    expect(ChangeUtils.actionAvailability(undefined, 'draft', 'view')).toBe(false);
  });
});