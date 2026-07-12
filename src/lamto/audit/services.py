from .models import AuditEvent


def record_audit(actor, membership, action, target_type, target_id, result, metadata=None) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor,
        membership=membership,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        metadata={} if metadata is None else metadata,
    )
