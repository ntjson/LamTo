import hashlib

from django.core.exceptions import PermissionDenied
from django.core.files.storage import storages

from lamto.accounts.models import OrganizationMembership, ResidentOccupancy
from lamto.audit.services import record_audit

from .models import DocumentVersion


class DocumentIntegrityError(PermissionDenied):
    pass


def _audit(user, membership, version, result, metadata=None):
    record_audit(
        actor=user,
        membership=membership,
        action="document.download",
        target_type="DocumentVersion",
        target_id=str(version.pk),
        result=result,
        metadata=metadata,
    )


def _resident_occupancy(user, version):
    return ResidentOccupancy.objects.filter(
        user=user, active=True, unit__building_id=version.document.building_id
    ).first()


def _allowed(user, membership, version, occupancy):
    if membership is None:
        return False
    if membership.organization.building_id != version.document.building_id:
        return False
    return membership.role == OrganizationMembership.Role.AUDITOR


def _read_stored_version(version):
    storage = storages["private"]
    if hasattr(storage, "bucket_name") and hasattr(storage, "connection"):
        if not version.provider_version_id:
            raise ValueError("S3 document version ID is missing.")
        response = storage.connection.meta.client.get_object(
            Bucket=storage.bucket_name,
            Key=version.storage_key,
            VersionId=version.provider_version_id,
        )
        stream = response["Body"]
        return iter(lambda: stream.read(8192), b"")
    return storage.open(version.storage_key, "rb").chunks()


def authorize_download(user, membership_id, version) -> bytes:
    membership = (
        OrganizationMembership.objects.select_related("organization")
        .filter(pk=membership_id, user=user, active=True)
        .first()
    )
    audit_membership = membership or OrganizationMembership.objects.filter(
        user=user, active=True
    ).first()
    occupancy = _resident_occupancy(user, version) if audit_membership is None else None
    if audit_membership is None and occupancy is None:
        occupancy = ResidentOccupancy.objects.filter(user=user, active=True).first()
    audit_metadata = {"occupancy_id": occupancy.id} if occupancy else None
    if not _allowed(user, membership, version, occupancy):
        _audit(user, audit_membership, version, "denied", audit_metadata)
        raise PermissionDenied("Document access denied.")
    try:
        data = b"".join(_read_stored_version(version))
    except Exception as error:
        _audit(
            user,
            audit_membership,
            version,
            "unavailable",
            {"action_item": "document_integrity_check", **(audit_metadata or {})},
        )
        raise DocumentIntegrityError("Document storage is unavailable.") from error
    if hashlib.sha256(data).hexdigest() != version.sha256:
        _audit(
            user,
            audit_membership,
            version,
            "integrity_mismatch",
            {"action_item": "document_integrity_check", **(audit_metadata or {})},
        )
        raise DocumentIntegrityError("Document integrity check failed.")
    _audit(user, audit_membership, version, "allowed", audit_metadata)
    return data
