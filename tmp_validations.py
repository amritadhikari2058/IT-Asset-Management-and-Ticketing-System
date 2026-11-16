# ---------------------------------------------------------------------------
# Validation services
# ---------------------------------------------------------------------------

def create_problem_validation(*, actor, problem, title, description='',
                              validation_type='functional', **extra):
    _require_staff(actor)

    if not title:
        raise ValidationError({'title': 'Title is required.'})

    validation = ProblemValidation.objects.create(
        problem=problem,
        title=title.strip(),
        description=(description or '').strip(),
        validation_type=validation_type,
        test_plan=extra.get('test_plan', ''),
        test_results=extra.get('test_results', ''),
        passed=extra.get('passed', False),
        validated_by=actor,
        validated_at=timezone.now() if extra.get('passed') else None,
    )

    record_history(
        problem, 'validation_created', actor,
        detail=f'Validation \"{validation.title}\" created.',
        changed_fields=['validation'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_validation_created',
        instance=validation,
        reason=f'validation={validation.pk}, title={title[:200]}',
    )

    return validation


def start_problem_validation(*, actor, validation, **extra):
    _require_staff(actor)

    # Valid time window check
    if validation.validated_at and validation.validated_at < timezone.now() - dj_timezone.timedelta(days=30):
        raise ValidationError({'validated_at': 'Validation outside valid time window.'})


def pass_problem_validation(*, actor, validation, **extra):
    _require_staff(actor)

    validation.passed = True
    validation.save(update_fields=['passed'])

    record_history(
        problem, 'validation_passed', actor,
        detail=f'Validation \"{validation.title}\" passed.',
        changed_fields=['passed'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_validation_passed',
        instance=validation,
        reason=f'validation={validation.pk} passed by {actor.id}',
    )

    return validation


def fail_problem_validation(*, actor, validation, **extra):
    _require_staff(actor)

    validation.passed = False
    validation.save(update_fields=['passed'])

    record_history(
        problem, 'validation_failed', actor,
        detail=f'Validation \"{validation.title}\" failed.',
        changed_fields=['passed'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_validation_failed',
        instance=validation,
        reason=f'validation={validation.pk} failed by {actor.id}',
    )

    return validation


def mark_problem_validation_inconclusive(*, actor, validation, **extra):
    _require_staff(actor)

    validation.passed = None  # or a special inconclusive flag
    validation.save(update_fields=['passed'])

    record_history(
        problem, 'validation_inconclusive', actor,
        detail=f'Validation \"{validation.title}\" marked inconclusive.',
        changed_fields=['passed'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_validation_inconclusive',
        instance=validation,
        reason=f'validation={validation.pk} marked inconclusive by {actor.id}',
    )

    return validation


def cancel_problem_validation(*, actor, validation, **extra):
    _require_staff(actor)

    # Final statuses immutable
    if validation.status in ('resolved', 'closed'):
        raise ValidationError({'validation': 'Cannot cancel a resolved/closed validation.'})

    # ... additional logic