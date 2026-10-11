"""Single helper so every mutation writes a protected AuditLog row."""
from common.models import AuditLog


def log_action(*, actor, action, instance, reason="", details=None):
    entity_type = f"{instance._meta.app_label}.{instance._meta.model_name}"
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        entity_type=entity_type,
        object_id=str(instance.pk),
        object_repr=str(instance)[:255],
        reason=reason or "",
        details=details or {},
    )
