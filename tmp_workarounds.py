# ---------------------------------------------------------------------------
# Workaround services
# ---------------------------------------------------------------------------

def create_problem_workaround(*, actor, problem, title, description='',
                              workaround_type='temporary', steps='', **extra):
    _require_staff(actor)

    if not title:
        raise ValidationError({'title': 'Title is required.'})

    if not steps:
        raise ValidationError({'steps': 'Steps are required.'})

    # High/critical risk requires limitations
    risk = extra.get('risk', 'low')
    if risk in ('high', 'critical') and extra.get('limitations') is None:
        raise ValidationError({'limitations': 'High/critical risk requires limitations.'})

    workaround = ProblemWorkaround.objects.create(
        problem=problem,
        title=title.strip(),
        description=(description or '').strip(),
        workaround_type=workaround_type,
        steps=steps.strip(),
        effectiveness_rating=extra.get('effectiveness_rating', 3),
        implemented_at=extra.get('implemented_at'),
        resolved_at=extra.get('resolved_at'),
        implemented_by=actor,
    )

    record_history(
        problem, 'workaround_created', actor,
        detail=f'Workaround \"{workaround.title}\" created.',
        changed_fields=['workaround'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_workaround_created',
        instance=workaround,
        reason=f'workaround={workaround.pk}, title={title[:200]}',
    )

    return workaround


def submit_problem_workaround(*, actor, workaround, **extra):
    _require_staff(actor)

    if workaround.status != 'draft':
        raise ValidationError({'workaround': f'Only draft workarounds can be submitted.'})


def approve_problem_workaround(*, actor, workaround, **extra):
    _require_governance(actor)

    if workaround.status != 'draft':
        raise ValidationError({'workaround': f'Only draft workarounds can be approved.'})


def publish_problem_workaround(*, actor, workaround, **extra):
    _require_governance(actor)

    if workaround.status != 'approved':
        raise ValidationError({'workaround': f'Only approved workarounds can be published.'})


def expire_problem_workaround(*, actor, workaround, **extra):
    _require_staff(actor)

    workaround.status = 'expired'
    workaround.save(update_fields=['status'])

    record_history(
        workaround.problem, 'workaround_expired', actor,
        detail=f'Workaround \"{workaround.title}\" expired.',
        changed_fields=['status'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_workaround_expired',
        instance=workaround,
        reason=f'workaround={workaround.pk} expired',
    )

    return workaround


def retire_problem_workaround(*, actor, workaround, **extra):
    _require_staff(actor)

    workaround.status = 'retired'
    workaround.save(update_fields=['status'])

    record_history(
        workaround.problem, 'workaround_retired', actor,
        detail=f'Workaround \"{workaround.title}\" retired.',
        changed_fields=['status'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_workaround_retired',
        instance=workaround,
        reason=f'workaround={workaround.pk} retired',
    )

    return workaround