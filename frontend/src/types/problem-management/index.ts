/* Problem Management Type Definitions - Gate 1 & Gate 2 */

// Problem list item
export interface ProblemListItem {
  id: number;
  problem_number: string;
  title: string;
  status: string;
  priority: string;
  severity?: string;
  urgency?: string;
  criticality?: string;
  owner?: number | null;
  owner_username?: string;
  problem_manager?: number | null;
  problem_manager_username?: string;
  service?: number | null;
  service_name?: string;
  category?: number | null;
  category_name?: string;
  environment?: string;
  linked_ticket_count: number;
  open_task_count: number;
  rc_state?: string | null;
  readiness_state?: string | null;
  created_at: string;
  updated_at: string;
}

// Problem filters
export interface ProblemFilters {
  status?: string;
  priority?: string;
  problem_type?: string;
  owner?: number;
  service?: number;
  category?: number;
  search?: string;
  is_open?: boolean;
  ordering?: string;
}

// Problem lookup
export interface ProblemLookup {
  id: number;
  problem_number: string;
  title: string;
}

// Severity choices (mirror backend)
export const SEVERITY_CHOICES = ['low', 'medium', 'high', 'critical'] as const;
export type Severity = typeof SEVERITY_CHOICES[number];

// Priority choices (mirror backend)
export const PRIORITY_CHOICES = ['low', 'medium', 'high', 'critical'] as const;
export type Priority = typeof PRIORITY_CHOICES[number];

// Problem type choices (mirror backend)
export const PROBLEM_TYPE_CHOICES = [
  'reactive',
  'proactive',
  'major_problem',
  'recurring_incident',
  'monitoring_pattern',
  'risk_reduction',
  'supplier_problem',
  'software_problem',
  'infrastructure_problem',
  'process_problem',
  'other',
] as const;
export type ProblemType = typeof PROBLEM_TYPE_CHOICES[number];

// Source choices (mirror backend)
export const SOURCE_CHOICES = [
  'manual',
  'ticket',
  'major_incident',
  'monitoring',
  'trend_analysis',
  'cmdb',
] as const;
export type Source = typeof SOURCE_CHOICES[number];

// Problem status values (mirror backend)
export const PROBLEM_STATUS_CHOICES = [
  'identified',
  'triage',
  'investigating',
  'resolving',
  'resolved',
  'closed',
  'rejected',
  'cancelled',
] as const;
export type ProblemStatus = typeof PROBLEM_STATUS_CHOICES[number];

// Problem timeline event
export interface ProblemTimelineEvent {
  id: number;
  event_type: string;
  title: string;
  description?: string;
  occurred_at: string;
  source?: string;
  recorded_at: string;
  actor_username?: string;
}

// Problem task
export interface ProblemTask {
  id: number;
  title: string;
  description?: string;
  status: string;
  action_type?: string;
  assigned_to?: number | null;
  assigned_group?: string | null;
  due_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  completed_by_username?: string | null;
  required?: boolean;
  blocks_resolution?: boolean;
  evidence_required?: boolean;
  version: number;
}

// Root Cause Analysis
export interface RootCauseAnalysis {
  id: number;
  problem: number;
  title: string;
  description?: string;
  analysis_method?: string;
  findings?: string;
  concluded_at?: string | null;
  status: 'draft' | 'submitted' | 'approved' | 'rejected' | 'superseded';
  version: number;
  created_at: string;
  updated_at?: string;
  created_by_username?: string;
  approved_by_username?: string;
  approved_by?: number | null;
  approved_at?: string | null;
  rejection_reason?: string | null;
}

// Root Cause Factor
export interface RootCauseFactor {
  id: number;
  analysis: number;
  category: string;
  factor: string;
  contribution?: string;
  identified_by?: number | null;
  identified_by_username?: string;
  identified_at?: string;
}

// Five Why
export interface RootCauseWhy {
  id: number;
  analysis: number;
  question_number: number;
  question_text: string;
  answer?: string;
  answered_by?: number | null;
  answered_by_username?: string;
  answered_at?: string;
}

// Evidence (original_filename is a storage-safe randomized basename, not the local upload name)
export interface EvidenceItem {
  id: number;
  problem?: number;
  title?: string;
  description?: string;
  evidence_type?: string;
  source?: string;
  checksum?: string | null;
  content_type?: string;
  file_type?: string;
  size?: number;
  file_size?: number;
  original_filename: string;
  uploaded_at: string;
  archived?: boolean;
  created_by?: number | null;
  created_by_username?: string;
  created_at?: string;
}

// Action types
export interface ProblemAction {
  id: number;
  problem: number;
  title: string;
  description?: string;
  action_type: 'corrective' | 'preventive' | 'root_cause' | 'validation' | 'exception';
  status: 'planned' | 'in_progress' | 'completed' | 'verified' | 'closed';
  assigned_to?: number | null;
  due_at?: string | null;
  completed_at?: string | null;
  root_cause_analysis?: number | null;
  validation_status?: string | null;
  version: number;
}

// Readiness state (mirroring backend Python dict)
export interface ProblemReadiness {
  ready_for_resolution: boolean;
  ready_for_closure: boolean;
  blockers: string[];
  warnings: string[];
  counts: {
    open_blocking_tasks: number;
    open_required_actions: number;
    failed_validations: number;
    open_critical_tickets: number;
    active_exceptions: number;
  };
}

// Linked record types
export interface LinkedTicket {
  id: number;
  ticket_number: string;
  title: string;
  status: string;
}

export interface LinkedCI {
  id: number;
  ci_number: string;
  name: string;
  type?: string;
}

export interface LinkedAsset {
  id: number;
  asset_tag: string;
  name: string;
  type?: string;
}

export interface LinkedService {
  id: number;
  name: string;
}

export interface LinkedProduct {
  id: number;
  product_code: string;
  name: string;
}

// History event
export interface ProblemHistoryEvent {
  id: number;
  event_type: string;
  actor_username?: string;
  previous_status?: string;
  new_status?: string;
  detail?: string;
  changed_fields?: string[];
  created_at: string;
}