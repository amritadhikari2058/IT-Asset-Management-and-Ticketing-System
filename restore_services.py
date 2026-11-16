#!/usr/bin/env python
import os

# Read current services.py
with open('backend/problem_management/services.py', 'r') as f:
    content = f.read()

# Find the line where retire_problem_workaround starts
idx = content.find('def retire_problem_workaround')
if idx >= 0:
    # Insert Evidence services before retire_problem_workaround
    evidence_services = '''
# ---------------------------------------------------------------------------
# Evidence services
# ---------------------------------------------------------------------------

def create_problem_evidence(*, actor, problem, title, evidence_type,
                            description="", file=None, **extra):
    _require_staff(actor)
    from django.utils.crypto import get_random_string
    from datetime import datetime
    
    # Derive original filename safely
    original_name = ""
    if file:
        original_name = getattr(file, 'name', '') or ''
        original_name = original_name.split('/')[-1].split('\\\\')[-1]
    
    # Derive content type safely
    content_type = ""
    if file:
        content_type = getattr(file, 'content_type', '') or ''
    
    # Calculate size
    size = 0
    if file:
        size = getattr(file, 'size', 0) or 0
    
    # Calculate SHA-256 checksum server-side
    checksum = ""
    if file:
        import hashlib
        content_bytes = file.read()
        checksum = hashlib.sha256(content_bytes).hexdigest()
        file.seek(0)
    
    # Generate secure randomized upload path
    import os
    upload_path = f"problem_evidence/{datetime.now().strftime('%Y/%m/%d')}/{get_random_string(12)}_{os.path.basename(original_name)}" if original_name else f"problem_evidence/{get_random_string(20)}"
    
    evidence = ProblemEvidence.objects.create(
        problem=problem,
        title=title.strip(),
        evidence_type=evidence_type,
        description=(description or "").strip(),
        file=file,
        uploaded_by=actor,
        created_at=datetime.now(),
    )
    
    record_history(
        problem, "evidence_added", actor,
        detail=f"Evidence '{evidence.pk}' added: {title[:100]}.",
        changed_fields=["evidence"],
    )
    
    from common.audit import log_action
    log_action(
        actor=actor, action="problem_evidence_created",
        instance=evidence,
        reason=f"evidence={evidence.pk}, title={title[:200]}",
    )
    
    return evidence


def archive_problem_evidence(*, actor, evidence, reason=""):
    _require_staff(actor)
    if evidence.is_archived:
        raise ValidationError({"detail": "Evidence is already archived."})
    evidence.is_archived = True
    evidence.save(update_fields=["is_archived", "archived_at"])
    record_history(
        evidence.problem, "evidence_archived", actor,
        detail=f"Evidence '{evidence.pk}' archived: {reason or 'no reason given'}.",
        changed_fields=["is_archived"],
    )
    return evidence
'''
    
    new_content = content[:idx] + evidence_services + content[idx:]
    with open('backend/problem_management/services.py', 'w') as f:
        f.write(new_content)
    print('Added Evidence services')
else:
    print('Could not find retire_problem_workaround')