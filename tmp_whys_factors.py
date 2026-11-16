# ---------------------------------------------------------------------------
# Five Whys and Factor services
# ---------------------------------------------------------------------------

def create_root_cause_why(*, actor, analysis, question_text, answer, **extra):
    _require_staff(actor)

    if analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Whys can only be created/modified when RCA is draft or in_review, got '{analysis.status}'."
        })

    if RootCauseWhy.objects.filter(analysis=analysis, sequence=extra.get("sequence")).exists():
        raise ValidationError({"analysis": f"Why with sequence {extra.get('sequence')} already exists."})

    why = RootCauseWhy.objects.create(
        analysis=analysis,
        question_text=question_text.strip(),
        answer=answer.strip(),
        sequence=extra.get("sequence", 1),
    )

    record_history(
        analysis.problem, "why_created", actor,
        detail=f"Why #{why.sequence} added to RCA '{analysis.pk}'.",
        changed_fields=["why"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_why_created",
        instance=why,
        reason=f"rca={analysis.pk}, why_sequence={why.sequence}",
    )

    return why


def update_root_cause_why(*, actor, why, question_text=None, answer=None, **extra):
    _require_staff(actor)

    if why.analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Whys cannot be modified when RCA is '{why.analysis.status}'."
        })

    updated = False
    if question_text is not None:
        why.question_text = question_text.strip()
        updated = True
    if answer is not None:
        why.answer = answer.strip()
        updated = True
    if updated:
        why.save(update_fields=["question_text", "answer"])

    if updated:
        record_history(
            why.analysis.problem, "why_updated", actor,
            detail=f"Why #{why.sequence} updated in RCA '{why.analysis.pk}'.",
            changed_fields=["question_text", "answer"],
        )

        from common.audit import log_action
        log_action(
            actor=actor, action="problem_why_updated",
            instance=why,
            reason=f"rca={why.analysis.pk}, why_sequence={why.sequence}",
        )

    return why


def delete_root_cause_why(*, actor, why, **extra):
    _require_staff(actor)

    if why.analysis.status not in ("draft",):
        raise ValidationError({
            "analysis": f"Whys cannot be deleted when RCA is '{why.analysis.status}'."
        })

    if why.analysis.status not in ("draft",):
        raise ValidationError({
            "analysis": "Cannot delete Why after RCA has been approved or superseded."
        })

    sequence = why.sequence
    why.delete()

    record_history(
        why.analysis.problem, "why_deleted", actor,
        detail=f"Why #{sequence} deleted from RCA '{why.analysis.pk}'.",
        changed_fields=["why"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_why_deleted",
        reason=f"rca={why.analysis.pk}, why_sequence={sequence}",
    )

    return {"deleted": True}


def create_root_cause_factor(*, actor, analysis, category, factor, confidence="medium", **extra):
    _require_staff(actor)

    if analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Factors can only be created/modified when RCA is draft or in_review, got '{analysis.status}'."
        })

    if RootCauseFactor.objects.filter(analysis=analysis, category=category).exists():
        raise ValidationError({
            "analysis": f"A factor with category '{category}' already exists."
        })

    factor_rec = RootCauseFactor.objects.create(
        analysis=analysis,
        category=category,
        factor=factor.strip(),
        confidence=confidence,
    )

    record_history(
        analysis.problem, "factor_created", actor,
        detail=f"Factor added to RCA '{analysis.pk}': {factor[:100]}..",
        changed_fields=["factor"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_factor_created",
        instance=factor_rec,
        reason=f"rca={analysis.pk}, category={category}",
    )

    return factor_rec


def update_root_cause_factor(*, actor, factor, category=None, factor_text=None, confidence=None, **extra):
    _require_staff(actor)

    if factor.analysis.status not in ("draft", "in_review"):
        raise ValidationError({
            "analysis": f"Factors cannot be modified when RCA is '{factor.analysis.status}'."
        })

    updated = False
    if category is not None:
        factor.category = category
        updated = True
    if factor_text is not None:
        factor.factor = factor_text.strip()
        updated = True
    if confidence is not None:
        factor.confidence = confidence
        updated = True
    if updated:
        factor.save(update_fields=["category", "factor", "confidence"])

    if updated:
        record_history(
            factor.analysis.problem, "factor_updated", actor,
            detail=f"Factor updated in RCA '{factor.analysis.pk}'.",
            changed_fields=["category", "factor", "confidence"],
        )

        from common.audit import log_action
        log_action(
            actor=actor, action="problem_factor_updated",
            instance=factor,
            reason=f"rca={factor.analysis.pk}",
        )

    return factor


def delete_root_cause_factor(*, actor, factor, **extra):
    _require_staff(actor)

    if factor.analysis.status not in ("draft",):
        raise ValidationError({
            "analysis": f"Factors cannot be deleted when RCA is '{factor.analysis.status}'."
        })

    category = factor.category
    factor.delete()

    record_history(
        factor.analysis.problem, "factor_deleted", actor,
        detail=f"Factor '{category}' deleted from RCA '{factor.analysis.pk}'.",
        changed_fields=["factor"],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action="problem_factor_deleted",
        reason=f"rca={factor.analysis.pk}, category={category}",
    )

    return {"deleted": True}