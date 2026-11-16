# ---------------------------------------------------------------------------
# Timeline service
# ---------------------------------------------------------------------------

def create_problem_timeline_event(*, actor, problem, occurred_at, source,
                                  event_type, title, description='', **extra):
    from datetime import timezone as dt_timezone
    from django.utils import timezone as dj_timezone

    _require_staff(actor)

    # Validate source allowlist
    allowed_sources = ('manual', 'ticket', 'major_incident', 'change_review',
                       'knowledge', 'monitoring', 'cmdb')
    if source not in allowed_sources:
        raise ValidationError({'source': f'Source {source} not in allowlist.'})

    # occurred_at must be timezone-aware
    if isinstance(occurred_at, dj_timezone.datetime) and dj_timezone.is_naive(occurred_at):
        raise ValidationError({'occurred_at': 'occurred_at must be timezone-aware.'})

    # Server-set recorded_at
    recorded_at = dj_timezone.now()

    timeline = ProblemTimelineEvent.objects.create(
        problem=problem,
        occurred_at=occurred_at,
        source=source,
        event_type=event_type,
        title=title,
        description=(description or '')[:4000],
        recorded_by=actor,
        recorded_at=recorded_at,
        **extra,
    )

    return timeline