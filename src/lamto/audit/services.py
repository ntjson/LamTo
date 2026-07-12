from django.core.exceptions import PermissionDenied

from lamto.accounts.models import OrganizationMembership, ResidentOccupancy

from .models import AuditEvent


def record_audit(actor, membership, action, target_type, target_id, result, metadata=None) -> AuditEvent:
    if membership is None:
        occupancy_id = (metadata or {}).get("occupancy_id")
        if (
            action != "document.download"
            or target_type != "DocumentVersion"
            or not occupancy_id
            or OrganizationMembership.objects.filter(user_id=getattr(actor, "pk", None), active=True).exists()
            or not ResidentOccupancy.objects.filter(
                pk=occupancy_id, user_id=getattr(actor, "pk", None), active=True
            ).exists()
        ):
            raise PermissionDenied("Audit membership attribution is invalid.")
    elif not OrganizationMembership.objects.filter(
        pk=membership.pk, user_id=getattr(actor, "pk", None), active=True
    ).exists():
        raise PermissionDenied("Audit membership attribution is invalid.")
    return AuditEvent.objects.create(
        actor=actor,
        membership=membership,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        metadata={} if metadata is None else metadata,
    )
