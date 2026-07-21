from django.core.exceptions import PermissionDenied

from .capabilities import ALLOWED_ORGANIZATION_KINDS
from .models import CapabilityGrant, OrganizationMembership


def grant_capability(membership: OrganizationMembership, code: str) -> CapabilityGrant:
    if membership.organization.kind not in ALLOWED_ORGANIZATION_KINDS.get(code, set()):
        raise PermissionDenied(code)
    grant, _ = CapabilityGrant.objects.get_or_create(membership=membership, code=code)
    return grant


def require_capability(user, membership_id: int, code: str) -> OrganizationMembership:
    membership = OrganizationMembership.objects.filter(
        id=membership_id, user=user, active=True
    ).first()
    if (
        membership is None
        or membership.organization.kind not in ALLOWED_ORGANIZATION_KINDS.get(code, set())
        or not CapabilityGrant.objects.filter(membership=membership, code=code).exists()
    ):
        raise PermissionDenied(code)
    return membership


def require_management(user, building_id: int) -> "ManagementMembership":
    from .models import ManagementMembership

    membership = ManagementMembership.objects.filter(
        user=user, building_id=building_id, active=True
    ).first()
    if membership is None:
        raise PermissionDenied("management")
    return membership
