#!/usr/bin/env python
import os

# Read current services.py
with open('backend/problem_management/services.py', 'r') as f:
    content = f.read()

# Find where to insert RCA services
idx = content.find('def retire_problem_workaround')
if idx >= 0:
    rca_services = """
# ---------------------------------------------------------------------------
# RCA services
# ---------------------------------------------------------------------------

def create_root_cause_analysis(*, actor, problem, title, description="",
                               analysis_type="five_whys", **extra):
    _require_staff(actor)
    if problem.status not in ("accepted", "investigating"):
        raise ValidationError({"problem": f"Problem must be accepted or investigating."})
    analysis = RootCauseAnalysis.objects.create(
        problem=problem, title=title.strip(), description=(description or "").strip(),
        analysis_type=analysis_type, status="draft", created_by=actor, version=1,
    )
    record_history(problem, "rca_created", actor,
        detail=f"RCA '{analysis.pk}' created: {title[:100]}.",
        changed_fields=["rca"])
    from common.audit import log_action
    log_action(actor=actor, action="problem_rca_created",
        instance=analysis, reason=f"rca={analysis.pk}, problem={problem.pk}")
    return analysis


def submit_root_cause_analysis(*, actor, analysis, **extra):
    _require_staff(actor)
    if analysis.status != "draft":
        raise ValidationError({"analysis": f"Only draft RCA can be submitted."})
    analysis.status = "in_review"
    analysis.save(update_fields=["status"])
    record_history(analysis.problem, "rca_submitted", actor,
        detail=f"RCA '{analysis.pk}' submitted for review.",
        changed_fields=["status"])
    from common.audit import log_action
    log_action(actor=actor, action="problem_rca_submitted",
        instance=analysis, reason=f"rca={analysis.pk} submitted by {actor.id}")
    return analysis


def approve_root_cause_analysis(*, actor, analysis, **extra):
    _require_governance(actor)
    if analysis.status != "in_review":
        raise ValidationError({"analysis": f"Only in_review RCA can be approved."})
    if analysis.created_by_id == actor.id:
        raise ValidationError({"analysis": "Creator cannot approve own RCA."})
    analysis.status = "approved"
    analysis.approved_by = actor
    analysis.approved_at = datetime.now()
    analysis.save(update_fields=["status", "approved_by", "approved_at"])
    record_history(analysis.problem, "rca_approved", actor,
        detail=f"RCA '{analysis.pk}' approved.",
        changed_fields=["status", "root_cause"])
    from common.audit import log_action
    log_action(actor=actor, action="problem_rca_approved",
        instance=analysis, reason=f"rca={analysis.pk} approved by {actor.id}")
    return analysis


def reject_root_cause_analysis(*, actor, analysis, reason="", **extra):
    _require_governance(actor)
    if analysis.status not in ("in_review", "approved"):
        raise ValidationError({"analysis": f"Cannot reject RCA in '{analysis.status}' state."})
    if not reason:
        raise ValidationError({"reason": "A rejection reason is required."})
    analysis.status = "rejected"
    analysis.save(update_fields=["status"])
    record_history(analysis.problem, "rca_rejected", actor,
        detail=f"RCA '{analysis.pk}' rejected: {reason[:200]}.",
        changed_fields=["status", "rejection_reason"])
    from common.audit import log_action
    log_action(actor=actor, action="problem_rca_rejected",
        instance=analysis, reason=f"rca={analysis.pk} rejected by {actor.id}, reason={reason[:200]}")
    return analysis
"""

    new_content = content[:idx] + rca_services + content[idx:]
    with open('backend/problem_management/services.py', 'w') as f:
        f.write(new_content)
    print('Added RCA services before retire_problem_workaround')
else:
    print('Could not find retire_problem_workaround')