# ---------------------------------------------------------------------------
# Action services
# ---------------------------------------------------------------------------

def create_problem_action(*, actor, problem, title, description='', due_date=None,
                          related_task=None, **extra):
    from django.utils import timezone as dj_timezone
    _require_staff(actor)

    if not title:
        raise ValidationError({'title': 'Title is required.'})

    if due_date and due_date < dj_timezone.now():
        raise ValidationError({'due_date': 'Due date must be in the future.'})

    action = ProblemAction.objects.create(
        problem=problem,
        title=title.strip(),
        description=(description or '').strip(),
        action_type=extra.get('action_type', 'corrective'),
        status='planned',
        due_at=due_date,
        assigned_to=extra.get('assigned_to'),
        root_cause_analysis=extra.get('root_cause_analysis'),
        validation_status=extra.get('validation_status'),
        created_by=actor,
    )

    record_history(
        problem, 'action_created', actor,
        detail=f'Action \"{action.pk}\" created: {title[:200]}.',
        changed_fields=['action'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_action_created',
        instance=action,
        reason=f'action={action.pk}, title={title[:200]}',
    )

    return action


def approve_problem_action(*, actor, action, **extra):
    _require_governance(actor)

    if action.status not in ('planned',):
        raise ValidationError({'action': f'Action can only be approved from planned state, got \"{action.status}\".'})


def start_problem_action(*, actor, action, **extra):
    _require_staff(actor)


def complete_problem_action(*, actor, action, **extra):
    _require_staff(actor)

    action.status = 'completed'
    action.completed_at = timezone.now()
    action.completed_by = actor
    action.save(update_fields=['status', 'completed_at', 'completed_by'])

    record_history(
        action.problem, 'action_completed', actor,
        detail=f'Action \"{action.title}\" completed.',
        changed_fields=['status', 'completed_at'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_action_completed',
        instance=action,
        reason=f'action={action.pk} completed by {actor.id}',
    )

    return action


def validate_problem_action(*, actor, action, **extra):
    _require_staff(actor)

    action.status = 'verified'
    action.save(update_fields=['status'])

    record_history(
        action.problem, 'action_validated', actor,
        detail=f'Action \"{action.title}\" validated.',
        changed_fields=['status'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_action_validated',
        instance=action,
        reason=f'action={action.pk} validated by {actor.id}',
    )

    return action


def mark_problem_action_ineffective(*, actor, action, **extra):
    _require_staff(actor)

    action.status = 'ineffective'
    action.save(update_fields=['status'])

    record_history(
        action.problem, 'action_ineffective', actor,
        detail=f'Action \"{action.title}\" marked ineffective.',
        changed_fields=['status'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_action_ineffective',
        instance=action,
        reason=f'action={action.pk} marked ineffective',
    )

    return action


def cancel_problem_action(*, actor, action, **extra):
    _require_staff(actor)

    action.status = 'cancelled'
    action.save(update_fields=['status'])

    record_history(
        action.problem, 'action_cancelled', actor,
        detail=f'Action \"{action.title}\" cancelled.',
        changed_fields=['status'],
    )

    from common.audit import log_action
    log_action(
        actor=actor, action='problem_action_cancelled',
        instance=action,
        reason=f'action={action.pk} cancelled by {actor.id}',
    )

    return action