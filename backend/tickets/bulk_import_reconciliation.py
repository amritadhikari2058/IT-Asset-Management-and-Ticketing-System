"""Eligibility assessment, preview, and safe finalization for ticket bulk imports.

All recovery decisions are derived from durable row-outcome evidence. Aggregate
operation counters are observational and must agree with evidence before a
state-changing finalization is allowed.

This module is read-only during assessment/preview. Finalization is performed
in a dedicated, locked transaction and never creates tickets, replays rows,
fabricates outcomes, or repairs evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, Min
from datetime import timedelta

from django.utils import timezone

from tickets.models import Ticket, TicketBulkImportOperation, TicketBulkImportRowOutcome


class BulkImportReconciliationError(Exception):
    """Base error for reconciliation/finalization failures."""

    status_code = 400
    code = "reconciliation_error"


class BulkImportNotEligible(BulkImportReconciliationError):
    status_code = 409
    code = "not_eligible"


class BulkImportStaleEvidence(BulkImportReconciliationError):
    status_code = 409
    code = "stale_evidence"


class BulkImportConflict(BulkImportReconciliationError):
    status_code = 409
    code = "conflict"


_SENSITIVE_DIAGNOSTIC_RE = None


def sanitize_import_diagnostic(text: str | None) -> str:
    """Redact secrets/internal details from bulk-import diagnostics.

    Preserves human-readable validation feedback while removing common secret
    patterns, tracebacks, and internal filesystem paths.
    """
    import re

    global _SENSITIVE_DIAGNOSTIC_RE
    if not text:
        return ""
    value = str(text)
    # Drop traceback-like content.
    value = re.sub(r"Traceback \(most recent call last\):[\s\S]*", "[redacted traceback]", value)
    value = re.sub(r"File \"[^\"]+\", line \d+[^\n]*", "[redacted traceback]", value)
    # Redact common secrets/tokens/fingerprints.
    value = re.sub(r"\b[A-Fa-f0-9]{32,}\b", "[redacted]", value)
    value = re.sub(r"(?i)\bBearer\s+\S+", "[redacted]", value)
    value = re.sub(r"(?i)\b(?:token|secret|password|api[_-]?key|authorization)\s*[:=]\s*\S+", "[redacted]", value)
    # Redact internal absolute paths (Windows/Unix) but keep filename-like hints.
    value = re.sub(r"[A-Za-z]:\\[^\s\"'<>]+", "[redacted-path]", value)
    value = re.sub(r"(?<!\w)/(?:var|srv|app|home|usr|etc|tmp|opt)/[^\s\"'<>]+", "[redacted-path]", value)
    return " ".join(value.split())[:1000]


@dataclass
class ReconciliationAssessment:
    operation_id: int
    current_status: str
    expected_row_count: int
    actual_outcome_count: int
    succeeded_outcome_count: int
    failed_outcome_count: int
    unprocessed_row_count: int
    duplicate_or_inconsistent_evidence: list[str] = field(default_factory=list)
    missing_ticket_references: list[dict[str, Any]] = field(default_factory=list)
    counter_inconsistencies: list[str] = field(default_factory=list)
    legacy_or_ambiguous_indicators: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    eligible_for_finalization: bool = False
    proposed_status: str | None = None
    proposed_result_status_code: int | None = None
    evidence_digest: str = ""
    result_stored: bool = False
    result_conflicts: list[str] = field(default_factory=list)
    has_row_level_evidence: bool = False
    is_stale_processing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_stale_processing(op: TicketBulkImportOperation) -> bool:
    if op.status != TicketBulkImportOperation.STATUS_PROCESSING or not op.started_at:
        return False
    stale_after = int(getattr(
        settings, "TICKET_BULK_IMPORT_PROCESSING_STALE_SECONDS", 300) or 300)
    return timezone.now() - op.started_at > timedelta(seconds=stale_after)


def _result_stored(op: TicketBulkImportOperation) -> bool:
    return bool(
        op.status == TicketBulkImportOperation.STATUS_COMPLETED
        and op.result_format
        and (op.result_json is not None or op.result_csv))


def _expected_rows_value(op: TicketBulkImportOperation) -> int | None:
    # total_rows defaults to 0; for pre-tracking/legacy ops this may be unknown.
    # Treat 0 as unknown/unset unless there is durable evidence or explicit
    # processing context that establishes an expected count.
    return op.total_rows if op.total_rows is not None else None


def _compute_evidence_digest(op: TicketBulkImportOperation,
                             outcomes: list[dict[str, Any]]) -> str:
    payload = {
        "operation_id": op.pk,
        "user_id": op.user_id,
        "status": op.status,
        "total_rows": op.total_rows,
        "processed_count": op.processed_count,
        "successful_count": op.successful_count,
        "failed_count": op.failed_count,
        "result_format": op.result_format,
        "result_status_code": op.result_status_code,
        "result_json_present": op.result_json is not None,
        "result_csv_present": bool(op.result_csv),
        "error_detail_present": bool(op.error_detail),
        "started_at": op.started_at.isoformat() if op.started_at else None,
        "completed_at": op.completed_at.isoformat() if op.completed_at else None,
        "updated_at": op.updated_at.isoformat() if op.updated_at else None,
        "outcomes": outcomes,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _canonical_outcome_rows(op: TicketBulkImportOperation) -> list[dict[str, Any]]:
    rows = list(TicketBulkImportRowOutcome.objects.filter(operation=op)
                .order_by("row_index")
                .values("id", "row_index", "row_number", "row_fingerprint",
                        "outcome", "ticket_id", "error_message",
                        "created_at", "updated_at"))
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "row_index": r["row_index"],
            "row_number": r["row_number"],
            "row_fingerprint": r["row_fingerprint"] or "",
            "outcome": r["outcome"],
            "ticket_id": r["ticket_id"],
            "has_error_message": bool(r.get("error_message")),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        })
    return out


def _build_reconstructed_result(op: TicketBulkImportOperation) -> dict[str, Any]:
    """Reconstruct the JSON confirmation result from durable row outcomes.

    Only for fully accounted, finalizable operations. The structure matches the
    normal bulk_create JSON payload: successful rows carry id/title; failed rows
    carry row/errors; skipped is empty for tracked imports.
    """
    outcomes = list(TicketBulkImportRowOutcome.objects.filter(operation=op)
                    .select_related("ticket")
                    .order_by("row_index"))
    successful = []
    failed = []
    for o in outcomes:
        if o.outcome == TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED:
            title = ""
            if o.ticket_id:
                # ticket relation may be null only in integrity-broken cases; caller
                # must have validated. Use select_related value when available.
                t = getattr(o, "ticket", None)
                title = getattr(t, "title", "") if t is not None else ""
            successful.append({
                "row": o.row_number,
                "id": o.ticket_id,
                "title": title,
            })
        elif o.outcome == TicketBulkImportRowOutcome.OUTCOME_FAILED:
            failed.append({
                "row": o.row_number,
                "errors": sanitize_import_diagnostic(o.error_message) or "Import row failed.",
            })
    return {
        "successful": successful,
        "skipped": [],
        "failed": failed,
        "summary": {
            "ok": len(successful),
            "skipped": 0,
            "failed": len(failed),
        },
    }


def assess_operation(op: TicketBulkImportOperation) -> ReconciliationAssessment:
    """Read-only evidence assessment for reconciliation/finalization preview."""
    outcomes_qs = TicketBulkImportRowOutcome.objects.filter(operation=op)
    outcome_rows = _canonical_outcome_rows(op)
    succeeded = [o for o in outcome_rows if o["outcome"] == TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED]
    failed = [o for o in outcome_rows if o["outcome"] == TicketBulkImportRowOutcome.OUTCOME_FAILED]
    actual = len(outcome_rows)
    has_evidence = actual > 0
    expected = op.total_rows
    # Determine whether expected row count is meaningfully established.
    # total_rows defaults to 0; 0 with evidence/processing-final states may mean
    # unknown legacy unless proven otherwise.
    expected_known = bool(expected and expected > 0)
    if not expected_known and has_evidence:
        # Evidence exists but expected may be unset/legacy; treat as not safely known
        # unless it exactly matches and operation is not obviously legacy-ambiguous.
        expected_known = False

    assessment = ReconciliationAssessment(
        operation_id=op.pk,
        current_status=op.status,
        expected_row_count=expected or 0,
        actual_outcome_count=actual,
        succeeded_outcome_count=len(succeeded),
        failed_outcome_count=len(failed),
        unprocessed_row_count=max((expected or 0) - actual, 0) if expected_known else 0,
        has_row_level_evidence=has_evidence,
        is_stale_processing=_is_stale_processing(op),
        result_stored=_result_stored(op),
        evidence_digest=_compute_evidence_digest(op, outcome_rows),
    )

    reasons = assessment.reasons
    legacy = assessment.legacy_or_ambiguous_indicators
    dupes = assessment.duplicate_or_inconsistent_evidence
    missing_tickets = assessment.missing_ticket_references
    counter_issues = assessment.counter_inconsistencies
    result_conflicts = assessment.result_conflicts

    # Recognized outcome statuses.
    valid_outcomes = {TicketBulkImportRowOutcome.OUTCOME_SUCCEEDED,
                      TicketBulkImportRowOutcome.OUTCOME_FAILED}
    invalid_status_rows = [o["row_index"] for o in outcome_rows
                           if o["outcome"] not in valid_outcomes]
    if invalid_status_rows:
        dupes.append(f"invalid_outcome_status_rows:{invalid_status_rows}")
        reasons.append("invalid_outcome_status")

    # Duplicate/inconsistent evidence at DB level should be prevented by unique
    # constraint; detect defensively from observed rows.
    if actual != len({o["row_index"] for o in outcome_rows}):
        dupes.append("duplicate_row_index_outcomes")
        reasons.append("duplicate_or_inconsistent_evidence")

    # Extra outcomes / expected range checks require known expected count.
    if has_evidence:
        row_indexes = [o["row_index"] for o in outcome_rows]
        min_idx = min(row_indexes) if row_indexes else None
        max_idx = max(row_indexes) if row_indexes else None
        if min_idx is not None and min_idx < 0:
            dupes.append("negative_row_index")
            reasons.append("duplicate_or_inconsistent_evidence")
        if expected_known:
            if max_idx is not None and max_idx >= expected:
                dupes.append(f"outcome_row_index_out_of_range:max={max_idx},expected={expected}")
                reasons.append("unexpected_extra_outcomes")
            if actual > expected:
                dupes.append(f"extra_outcomes:actual={actual},expected={expected}")
                reasons.append("unexpected_extra_outcomes")
            expected_set = set(range(expected))
            actual_set = set(row_indexes)
            missing_indexes = sorted(expected_set - actual_set)
            extra_indexes = sorted(actual_set - expected_set)
            if missing_indexes:
                assessment.unprocessed_row_count = len(missing_indexes)
                reasons.append("unprocessed_or_unrecorded_rows")
            if extra_indexes and "unexpected_extra_outcomes" not in reasons:
                dupes.append(f"unexpected_row_indexes:{extra_indexes}")
                reasons.append("unexpected_extra_outcomes")
            if not missing_indexes and not extra_indexes and actual == expected:
                assessment.unprocessed_row_count = 0
        else:
            # Expected count not safely established: cannot prove full coverage.
            legacy.append("expected_row_count_unknown")
            reasons.append("legacy_or_ambiguous_evidence")
            # still compute best-effort unprocessed as unknown.
            assessment.unprocessed_row_count = 0
    else:
        # No row-level outcomes.
        if op.status == TicketBulkImportOperation.STATUS_PREVIEWED and op.processed_count == 0:
            legacy.append("previewed_without_processing")
            reasons.append("not_processed")
        elif op.status in (TicketBulkImportOperation.STATUS_PROCESSING,
                           TicketBulkImportOperation.STATUS_FAILED,
                           TicketBulkImportOperation.STATUS_COMPLETED):
            legacy.append("no_durable_row_outcomes")
            reasons.append("legacy_or_ambiguous_evidence")
            # Unprocessed/unrecorded is all expected rows if known-ish, else unknown.
            if expected and expected > 0:
                assessment.unprocessed_row_count = expected
            else:
                assessment.unprocessed_row_count = 0
        else:
            legacy.append("no_durable_row_outcomes")
            reasons.append("legacy_or_ambiguous_evidence")

    # Missing ticket references for succeeded outcomes.
    for o in succeeded:
        tid = o.get("ticket_id")
        if tid is None:
            missing_tickets.append({
                "row_index": o["row_index"],
                "outcome_id": o["id"],
                "ticket_id": None,
                "issue": "succeeded_outcome_missing_ticket_reference",
            })
    if missing_tickets:
        reasons.append("missing_ticket_reference")

    # Failed outcomes should have failure evidence.
    failed_missing_evidence = [o["row_index"] for o in failed if not o.get("has_error_message")]
    if failed_missing_evidence:
        dupes.append(f"failed_outcomes_missing_error_evidence_rows:{failed_missing_evidence}")
        reasons.append("invalid_failure_evidence")

    # Counter consistency with durable outcomes.
    if expected_known:
        if op.successful_count != len(succeeded):
            counter_issues.append(
                f"successful_count_mismatch:stored={op.successful_count},actual={len(succeeded)}")
        if op.failed_count != len(failed):
            counter_issues.append(
                f"failed_count_mismatch:stored={op.failed_count},actual={len(failed)}")
        if op.processed_count != actual:
            counter_issues.append(
                f"processed_count_mismatch:stored={op.processed_count},actual={actual}")
        if op.total_rows != expected:
            counter_issues.append(
                f"total_rows_mismatch:stored={op.total_rows},expected={expected}")
    else:
        if has_evidence:
            if op.successful_count != len(succeeded):
                counter_issues.append(
                    f"successful_count_mismatch:stored={op.successful_count},actual={len(succeeded)}")
            if op.failed_count != len(failed):
                counter_issues.append(
                    f"failed_count_mismatch:stored={op.failed_count},actual={len(failed)}")
            if op.processed_count != actual:
                counter_issues.append(
                    f"processed_count_mismatch:stored={op.processed_count},actual={actual}")
    # Counters are reported as evidence issues but, when durable row evidence is
    # complete and consistent, explicit audited finalization may set them to the
    # evidence-derived values. Do not treat mismatch alone as a hard blocker.

    # Existing final result conflicts.
    if op.status == TicketBulkImportOperation.STATUS_COMPLETED:
        if not assessment.result_stored:
            result_conflicts.append("completed_without_stored_result")
            reasons.append("result_conflict")
        else:
            if op.result_format == "json" and isinstance(op.result_json, dict):
                summary = op.result_json.get("summary") or {}
                if (summary.get("ok") != len(succeeded)
                        or summary.get("failed") != len(failed)):
                    result_conflicts.append(
                        "stored_result_summary_conflicts_with_outcomes")
                    reasons.append("result_conflict")
                expected_success_ids = [o["ticket_id"] for o in succeeded]
                stored_success_ids = [s.get("id") for s in op.result_json.get("successful", [])]
                if stored_success_ids != expected_success_ids:
                    result_conflicts.append(
                        "stored_result_success_rows_conflict_with_outcomes")
                    if "result_conflict" not in reasons:
                        reasons.append("result_conflict")
            elif op.result_format not in ("json", "csv"):
                result_conflicts.append("unsupported_stored_result_format")
                reasons.append("result_conflict")
    elif assessment.result_stored:
        result_conflicts.append("stored_result_with_non_completed_status")
        reasons.append("result_conflict")

    # Legacy/pre-tracking ambiguity indicators.
    if not expected_known and (has_evidence or op.status != TicketBulkImportOperation.STATUS_PREVIEWED):
        if "legacy_or_ambiguous_evidence" not in reasons:
            legacy.append("expected_row_count_unknown_or_unreliable")
            reasons.append("legacy_or_ambiguous_evidence")
    if (op.status in (TicketBulkImportOperation.STATUS_FAILED,
                      TicketBulkImportOperation.STATUS_PROCESSING,
                      TicketBulkImportOperation.STATUS_COMPLETED)
            and not has_evidence):
        if "legacy_or_ambiguous_evidence" not in reasons:
            legacy.append("no_durable_row_outcomes")
            reasons.append("legacy_or_ambiguous_evidence")

    # Operation state compatibility for finalization.
    if (op.status == TicketBulkImportOperation.STATUS_COMPLETED
            and assessment.result_stored
            and not result_conflicts
            and expected_known
            and has_evidence
            and actual == expected
            and assessment.unprocessed_row_count == 0
            and not missing_tickets
            and not invalid_status_rows
            and not failed_missing_evidence):
        reasons.append("already_finalized")

    # Hard blockers.
    hard_blockers = {
        "invalid_outcome_status",
        "duplicate_or_inconsistent_evidence",
        "unexpected_extra_outcomes",
        "unprocessed_or_unrecorded_rows",
        "missing_ticket_reference",
        "invalid_failure_evidence",
        "result_conflict",
        "legacy_or_ambiguous_evidence",
        "not_processed",
        "already_finalized",
    }
    blocking = [r for r in reasons if r in hard_blockers]

    can_propose = (
        expected_known
        and expected > 0
        and has_evidence
        and actual == expected
        and assessment.unprocessed_row_count == 0
        and not missing_tickets
        and not invalid_status_rows
        and not failed_missing_evidence
        and not dupes
        and not result_conflicts
        and "legacy_or_ambiguous_evidence" not in reasons
        and "not_processed" not in reasons
        and "already_finalized" not in reasons
        and not blocking
    )
    if can_propose:
        assessment.proposed_status = TicketBulkImportOperation.STATUS_COMPLETED
        assessment.proposed_result_status_code = 200
        assessment.eligible_for_finalization = True
    else:
        assessment.eligible_for_finalization = False
        assessment.proposed_status = None
        assessment.proposed_result_status_code = None

    # Normalize reason ordering/uniqueness while preserving meaning.
    assessment.reasons = list(dict.fromkeys(reasons))
    assessment.legacy_or_ambiguous_indicators = list(dict.fromkeys(legacy))
    assessment.duplicate_or_inconsistent_evidence = list(dict.fromkeys(dupes))
    assessment.counter_inconsistencies = list(dict.fromkeys(counter_issues))
    assessment.result_conflicts = list(dict.fromkeys(result_conflicts))
    return assessment


def build_preview_payload(op: TicketBulkImportOperation) -> dict[str, Any]:
    assessment = assess_operation(op)
    payload = assessment.to_dict()
    payload.update({
        "confirmation_required": assessment.eligible_for_finalization,
        "confirmation_fields": {
            "evidence_digest": assessment.evidence_digest,
            "expected_status": assessment.current_status,
            "proposed_status": assessment.proposed_status,
        } if assessment.eligible_for_finalization else None,
        "sensitive_data_redacted": True,
        "state_changing": False,
    })
    return payload


def _build_finalization_audit_details(*, assessment: ReconciliationAssessment,
                                      previous_status: str,
                                      resulting_status: str,
                                      outcome: str,
                                      reason: str) -> dict[str, Any]:
    return {
        "operation_id": assessment.operation_id,
        "action_type": "finalize",
        "previous_operation_state": previous_status,
        "resulting_operation_state": resulting_status,
        "expected_row_count": assessment.expected_row_count,
        "succeeded_row_count": assessment.succeeded_outcome_count,
        "failed_row_count": assessment.failed_outcome_count,
        "actual_outcome_count": assessment.actual_outcome_count,
        "unprocessed_row_count": assessment.unprocessed_row_count,
        "evidence_digest": assessment.evidence_digest,
        "finalization_outcome": outcome,
        "reason": reason,
        "counter_inconsistencies": list(assessment.counter_inconsistencies),
        "missing_ticket_references": list(assessment.missing_ticket_references),
        "result_conflicts": list(assessment.result_conflicts),
        "integrity_assessment": {
            "eligible": assessment.eligible_for_finalization,
            "reasons": list(assessment.reasons),
            "legacy_or_ambiguous_indicators": list(assessment.legacy_or_ambiguous_indicators),
            "duplicate_or_inconsistent_evidence": list(assessment.duplicate_or_inconsistent_evidence),
        },
    }


@transaction.atomic
def finalize_operation(*, operation_id: int, user_id: int, actor,
                       reason: str, evidence_digest: str,
                       expected_status: str | None = None) -> dict[str, Any]:
    """Safely finalize an eligible bulk import operation.

    Locks the operation row, re-evaluates durable evidence, rejects stale or
    ineligible requests, persists the consistent final state/result, and writes
    an audit record. Returns a structured result for idempotent or successful
    finalization.
    """
    from common.audit import log_action

    reason = (reason or "").strip()
    if not reason:
        raise BulkImportReconciliationError("A reason is required for finalization.")
    reason = sanitize_import_diagnostic(reason)

    locked = (TicketBulkImportOperation.objects
              .select_for_update()
              .get(pk=operation_id, user_id=user_id))

    assessment = assess_operation(locked)

    # Idempotent: operation already finalized consistently. A repeated identical
    # confirmation after success must not create a second logical finalization.
    if (locked.status == TicketBulkImportOperation.STATUS_COMPLETED
            and assessment.result_stored
            and not assessment.result_conflicts
            and "already_finalized" in assessment.reasons):
        return {
            "idempotent": True,
            "finalized": True,
            "operation_id": locked.pk,
            "status": locked.status,
            "evidence_digest": assessment.evidence_digest,
            "message": "Operation is already finalized.",
            "assessment": assessment.to_dict(),
        }

    # Validate preview confirmation binding.
    if not evidence_digest:
        raise BulkImportStaleEvidence("Evidence digest is required.")
    if evidence_digest != assessment.evidence_digest:
        raise BulkImportStaleEvidence(
            "The reconciliation preview is stale or does not match current evidence.")
    if expected_status and expected_status != locked.status:
        raise BulkImportStaleEvidence(
            "The operation status changed since the reconciliation preview.")

    if not assessment.eligible_for_finalization:
        raise BulkImportNotEligible({
            "detail": "Operation is not eligible for safe finalization.",
            "reasons": assessment.reasons,
            "assessment": assessment.to_dict(),
        })

    proposed_status = assessment.proposed_status
    if proposed_status != TicketBulkImportOperation.STATUS_COMPLETED:
        raise BulkImportNotEligible(
            "No safe finalization transition is available for this operation.")

    if assessment.result_conflicts:
        raise BulkImportNotEligible({
            "detail": "Stored result conflicts with durable evidence.",
            "reasons": assessment.reasons,
            "assessment": assessment.to_dict(),
        })

    previous_status = locked.status
    now = timezone.now()
    result_json = _build_reconstructed_result(locked)

    locked.status = proposed_status
    locked.result_format = "json"
    locked.result_json = result_json
    locked.result_csv = ""
    locked.result_status_code = assessment.proposed_result_status_code or 200
    locked.total_rows = assessment.expected_row_count
    locked.processed_count = assessment.actual_outcome_count
    locked.successful_count = assessment.succeeded_outcome_count
    locked.failed_count = assessment.failed_outcome_count
    locked.completed_at = now
    locked.error_detail = ""
    locked.save(update_fields=[
        "status", "result_format", "result_json", "result_csv",
        "result_status_code", "total_rows", "processed_count",
        "successful_count", "failed_count", "completed_at",
        "error_detail", "updated_at",
    ])

    details = _build_finalization_audit_details(
        assessment=assessment,
        previous_status=previous_status,
        resulting_status=locked.status,
        outcome="finalized",
        reason=reason,
    )
    log_action(actor=actor, action="update", instance=locked,
               reason=reason, details=details)

    # Recompute digest as-of committed state for response clarity.
    post_assessment = assess_operation(locked)
    return {
        "idempotent": False,
        "finalized": True,
        "operation_id": locked.pk,
        "status": locked.status,
        "previous_status": previous_status,
        "evidence_digest": post_assessment.evidence_digest,
        "pre_finalization_evidence_digest": assessment.evidence_digest,
        "message": "Operation finalized from durable row-outcome evidence.",
        "assessment": post_assessment.to_dict(),
    }
