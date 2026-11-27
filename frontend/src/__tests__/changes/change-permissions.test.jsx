/*
 * Change Permission Tests
 */

import { describe, it, expect } from 'vitest';
import { ChangeUtils } from '../../shared/changes-utils';

describe('Change Permissions - Utilities', () => {
  describe('STATUS_LABELS', () => {
    it('has draft label', () => {
      expect(ChangeUtils.STATUS_LABELS.draft).toBe('Draft');
    });

    it('has submitted label', () => {
      expect(ChangeUtils.STATUS_LABELS.submitted).toBe('Submitted');
    });
  });

  describe('RISK_LEVEL_LABELS', () => {
    it('has low label', () => {
      expect(ChangeUtils.RISK_LEVEL_LABELS.low).toBe('Low');
    });
  });

  describe('PRIORITY_LABELS', () => {
    it('has low label', () => {
      expect(ChangeUtils.PRIORITY_LABELS.low).toBe('Low');
    });
  });

  describe('CHANGE_TYPE_LABELS', () => {
    it('has standard label', () => {
      expect(ChangeUtils.CHANGE_TYPE_LABELS.standard).toBe('Standard');
    });
  });

  describe('formatDate', () => {
    it('formats a valid date', () => {
      expect(ChangeUtils.formatDate('2024-01-15')).toBeDefined();
    });

    it('returns empty string for null', () => {
      expect(ChangeUtils.formatDate(null)).toBe('');
    });
  });

  describe('formatDuration', () => {
    it('formats 60 minutes as 1 hours', () => {
      expect(ChangeUtils.formatDuration(60)).toBe('1 hours');
    });

    it('returns empty string for null', () => {
      expect(ChangeUtils.formatDuration(null)).toBe('');
    });
  });

  describe('statusBadgeVariant', () => {
    it('returns danger for completed', () => {
      expect(ChangeUtils.statusBadgeVariant('completed')).toBe('danger');
    });

    it('returns warning for in_progress', () => {
      expect(ChangeUtils.statusBadgeVariant('in_progress')).toBe('warning');
    });
  });

  describe('riskBadgeVariant', () => {
    it('returns success for low', () => {
      expect(ChangeUtils.riskBadgeVariant('low')).toBe('success');
    });
  });

  describe('priorityBadgeVariant', () => {
    it('returns secondary for low', () => {
      expect(ChangeUtils.priorityBadgeVariant('low')).toBe('secondary');
    });
  });

  describe('isTerminalStatus', () => {
    it('completed is terminal', () => {
      expect(ChangeUtils.isTerminalStatus('completed')).toBe(true);
    });

    it('draft is not terminal', () => {
      expect(ChangeUtils.isTerminalStatus('draft')).toBe(false);
    });
  });

  describe('isEditableStatus', () => {
    it('draft is editable', () => {
      expect(ChangeUtils.isEditableStatus('draft')).toBe(true);
    });

    it('completed is not editable', () => {
      expect(ChangeUtils.isEditableStatus('completed')).toBe(false);
    });
  });

  describe('safeResults', () => {
    it('returns empty array for null', () => {
      expect(ChangeUtils.safeResults(null)).toEqual([]);
    });

    it('returns array as-is', () => {
      expect(ChangeUtils.safeResults([1, 2])).toEqual([1, 2]);
    });
  });

  describe('buildChangeListUrl', () => {
    it('returns empty string with no filters', () => {
      expect(ChangeUtils.buildChangeListUrl({})).toBe('');
    });

    it('adds type filter', () => {
      expect(ChangeUtils.buildChangeListUrl({ type: 'emergency' })).toBe('?type=emergency');
    });
  });

  describe('parseFieldErrors', () => {
    it('returns empty object for null', () => {
      expect(ChangeUtils.parseFieldErrors(null)).toEqual({});
    });

    it('extracts field errors', () => {
      const mockError = { response: { data: { title: ['Required'] } } };
      const errors = ChangeUtils.parseFieldErrors(mockError);
      expect(errors.title).toBe('Required');
    });
  });

  describe('actionAvailability', () => {
    it('System Admin has create action', () => {
      expect(ChangeUtils.actionAvailability('system_admin', 'draft', 'create')).toBe(true);
    });

    it('IT Support can create draft', () => {
      expect(ChangeUtils.actionAvailability('it_support', 'draft', 'create_draft')).toBe(true);
    });

    it('Employee cannot approve', () => {
      expect(ChangeUtils.actionAvailability('employee', 'draft', 'approve')).toBe(false);
    });

    it('unknown role fails closed', () => {
      expect(ChangeUtils.actionAvailability(undefined, 'draft', 'view')).toBe(false);
    });

    it('Manager starts rollback only from failed', () => {
      expect(ChangeUtils.actionAvailability('it_manager', 'failed', 'start_rollback')).toBe(true);
      expect(ChangeUtils.actionAvailability('it_manager', 'in_progress', 'start_rollback')).toBe(false);
      expect(ChangeUtils.actionAvailability('it_manager', 'validation', 'start_rollback')).toBe(false);
    });

    it('Manager completes rollback only from rolled_back', () => {
      expect(ChangeUtils.actionAvailability('it_manager', 'rolled_back', 'complete_rollback')).toBe(true);
      expect(ChangeUtils.actionAvailability('it_manager', 'in_progress', 'complete_rollback')).toBe(false);
      expect(ChangeUtils.actionAvailability('it_manager', 'validation', 'complete_rollback')).toBe(false);
      expect(ChangeUtils.actionAvailability('it_manager', 'failed', 'complete_rollback')).toBe(false);
    });

    it('IT Support has no rollback actions', () => {
      expect(ChangeUtils.actionAvailability('it_support', 'failed', 'start_rollback')).toBe(false);
      expect(ChangeUtils.actionAvailability('it_support', 'rolled_back', 'complete_rollback')).toBe(false);
    });
  });
});