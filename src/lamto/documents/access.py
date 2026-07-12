import hashlib

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.files.storage import storages

from lamto.accounts.models import OrganizationMembership, ResidentOccupancy
from lamto.audit.services import record_audit

from .models import Document, DocumentVersion


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


def _related_records(version):
    subjects = (version, version.document)
    for subject in subjects:
        yield subject
        for name in (
            "report",
            "proposal",
            "proposal_version",
            "work_order",
            "entry",
            "published_entry",
        ):
            related = getattr(subject, name, None)
            if related is not None:
                yield related
        for relation in subject._meta.related_objects:
            try:
                value = getattr(subject, relation.get_accessor_name())
                values = value.all() if hasattr(value, "all") else (value,)
            except (AttributeError, ObjectDoesNotExist):
                continue
            for related in values:
                yield related
                for name in ("report", "proposal", "proposal_version", "work_order", "entry"):
                    nested = getattr(related, name, None)
                    if nested is not None:
                        yield nested


def _has_published_link(version):
    return any(
        getattr(record, "published", False)
        or getattr(record, "is_published", False)
        or getattr(record, "published_at", None) is not None
        for record in _related_records(version)
    )


def _has_own_report_link(user, version):
    for record in _related_records(version):
        report = getattr(record, "report", record)
        if getattr(report, "reporter_id", None) == user.pk:
            return True
    return False


def _has_proposal_review(membership, version):
    for record in _related_records(version):
        proposal = getattr(record, "proposal", None) or getattr(record, "proposal_version", None)
        if proposal is None:
            continue
        if any(
            getattr(proposal, field, None) == membership.pk
            for field in (
                "reviewer_membership_id",
                "resident_representative_membership_id",
                "representative_membership_id",
            )
        ):
            return True
        decisions = getattr(proposal, "approvaldecision_set", None)
        if decisions is not None and decisions.filter(membership_id=membership.pk).exists():
            return True
    return False


def _has_assigned_work(user, version):
    for record in _related_records(version):
        work_order = getattr(record, "work_order", record)
        if any(
            getattr(work_order, field, None) == user.pk
            for field in ("assignee_id", "assigned_to_id", "maintenance_user_id")
        ):
            return True
    return False


def _resident_occupancy(user, version):
    return ResidentOccupancy.objects.filter(
        user=user, active=True, unit__building_id=version.document.building_id
    ).first()


def _allowed(user, membership, version, occupancy):
    if membership is None:
        return occupancy is not None and (
            version.variant == DocumentVersion.Variant.REDACTED
            and _has_published_link(version)
            or version.document.kind == Document.Kind.REPORT_PHOTO
            and _has_own_report_link(user, version)
        )
    if membership.organization.building_id != version.document.building_id:
        return False
    if membership.role == OrganizationMembership.Role.OPERATOR:
        return True
    if membership.role == OrganizationMembership.Role.AUDITOR:
        return True
    if membership.role == OrganizationMembership.Role.RESIDENT_REP:
        return (
            version.variant == DocumentVersion.Variant.ORIGINAL
            and _has_proposal_review(membership, version)
        )
    if membership.role == OrganizationMembership.Role.MAINTENANCE:
        return (
            version.document.kind
            in {
                Document.Kind.REPORT_PHOTO,
                Document.Kind.BEFORE_PHOTO,
                Document.Kind.AFTER_PHOTO,
            }
            and _has_assigned_work(user, version)
        )
    return False


def _read_stored_version(version):
    storage = storages["private"]
    if version.provider_version_id != version.storage_key and hasattr(storage, "connection"):
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
    occupancy = _resident_occupancy(user, version) if membership is None else None
    audit_metadata = {"occupancy_id": occupancy.id} if occupancy else None
    if not _allowed(user, membership, version, occupancy):
        _audit(user, membership, version, "denied", audit_metadata)
        raise PermissionDenied("Document access denied.")
    try:
        data = b"".join(_read_stored_version(version))
    except Exception as error:
        _audit(
            user,
            membership,
            version,
            "unavailable",
            {"action_item": "document_integrity_check", **(audit_metadata or {})},
        )
        raise DocumentIntegrityError("Document storage is unavailable.") from error
    if hashlib.sha256(data).hexdigest() != version.sha256:
        _audit(
            user,
            membership,
            version,
            "integrity_mismatch",
            {"action_item": "document_integrity_check", **(audit_metadata or {})},
        )
        raise DocumentIntegrityError("Document integrity check failed.")
    _audit(user, membership, version, "allowed", audit_metadata)
    return data
