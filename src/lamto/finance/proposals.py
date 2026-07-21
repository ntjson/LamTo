from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from lamto.accounts.services import require_management
from lamto.audit.services import record_audit
from lamto.documents.models import DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType
from lamto.evidence.services import queue_platform_event
from lamto.maintenance.cases import TERMINAL_STATUSES
from lamto.maintenance.models import CaseReport, IssueReport, MaintenanceCase

from .models import Proposal, ProposalDocument, ProposalVersion


def spending_proposal_cases():
    """Cases still on outcome D: public, active, and not already started as outcome C."""
    return (
        MaintenanceCase.objects.filter(active=True, completed_at__isnull=True)
        .exclude(reports__is_private=True)
        .exclude(reports__status=IssueReport.Status.IN_PROGRESS)
        .distinct()
    )


ZERO_HASH = "0x" + "00" * 32


def _quotation_pairs(building_id, quotation_versions, *, lock=False):
    supplied = list(quotation_versions or [])
    ids = [getattr(version, "pk", None) for version in supplied]
    if not ids or any(value is None for value in ids) or len(set(ids)) != len(ids):
        raise ValidationError("At least one distinct quotation original is required.")
    queryset = DocumentVersion.objects.select_related("document").filter(pk__in=ids)
    if lock:
        queryset = queryset.select_for_update()
    versions = {version.pk: version for version in queryset}
    if len(versions) != len(ids):
        raise ValidationError("Every quotation version must still exist.")

    pairs = []
    for version_id in ids:
        original = versions[version_id]
        if (
            original.document.kind != original.document.Kind.QUOTATION
            or original.document.building_id != building_id
            or original.variant != DocumentVersion.Variant.ORIGINAL
            or original.scan_status != DocumentVersion.ScanStatus.CLEAN
            or original.redacts_id is not None
        ):
            raise ValidationError("Quotation originals must be clean, safe, and in the work-order building.")
        redacted_queryset = DocumentVersion.objects.select_related("document").filter(
            document_id=original.document_id,
            redacts_id=original.pk,
            variant=DocumentVersion.Variant.REDACTED,
            scan_status=DocumentVersion.ScanStatus.CLEAN,
        ).order_by("-version")
        if lock:
            redacted_queryset = redacted_queryset.select_for_update()
        redacted = redacted_queryset.first()
        if (
            redacted is None
            or redacted.document.kind != redacted.document.Kind.QUOTATION
            or redacted.document.building_id != building_id
            or redacted.sha256 == original.sha256
        ):
            raise ValidationError("Each quotation original requires a distinct clean redacted copy.")
        pairs.append((original, redacted))
    return pairs


def _submission_snapshot(proposal, amount_vnd, contractor_name, fund_code, purpose,
                         proposed_action, expected_schedule, pairs, number):
    case = proposal.case
    quotation_snapshot = [
        {
            "original_id": original.pk,
            "original_sha256": original.sha256,
            "redacted_id": redacted.pk,
            "redacted_sha256": redacted.sha256,
        }
        for original, redacted in pairs
    ]
    snapshot = {
        "proposal_id": proposal.pk,
        "proposal_version": number,
        "case_id": case.pk if case else None,
        "building_id": proposal.building_id,
        "amount_vnd": amount_vnd,
        "contractor_name": contractor_name,
        "fund_code": fund_code,
        "purpose": purpose,
        "proposed_action": proposed_action,
        "expected_schedule": expected_schedule,
        "quotation_versions": quotation_snapshot,
    }
    evidence_payload = {
        "proposal_id": proposal.pk,
        "proposal_version": number,
        "record_id": proposal.pk,
        "building_id": proposal.building_id,
        "amount_vnd": amount_vnd,
        "proposal_snapshot_hash": payload_hash(snapshot),
        "quotation_original_hash": payload_hash([original.sha256 for original, _ in pairs]),
        "quotation_redacted_hash": payload_hash([redacted.sha256 for _, redacted in pairs]),
    }
    if case:
        evidence_payload.update(
            case_id=case.pk,
            case_snapshot_hash=payload_hash({
                "case_id": case.pk, "category": case.category,
                "department": case.department, "location_id": case.location_id,
            }),
        )
    return snapshot, evidence_payload


def build_proposal_evidence_payload(proposal, amount_vnd, contractor_name, quotation_versions,
                                    fund_code="GENERAL", purpose=None, proposed_action="",
                                    expected_schedule=""):
    """Build the exact signed payload callers must use before submission."""
    if type(amount_vnd) is not int or amount_vnd <= 0:
        raise ValidationError("Proposal amount must be a positive integer.")
    if not isinstance(contractor_name, str) or not contractor_name.strip():
        raise ValidationError("Contractor name is required.")
    purpose = proposal.case.category if purpose is None and proposal.case_id else (purpose or "")
    pairs = _quotation_pairs(proposal.building_id or proposal.case.building_id, quotation_versions)
    number = (ProposalVersion.objects.filter(proposal=proposal).aggregate(Max("number"))["number__max"] or 0) + 1
    _, evidence_payload = _submission_snapshot(
        proposal, amount_vnd, contractor_name.strip(), fund_code, purpose,
        proposed_action, expected_schedule, pairs, number
    )
    return evidence_payload


@transaction.atomic
def create_proposal(case, creator_membership) -> Proposal:
    locked_case = (
        MaintenanceCase.objects.select_for_update()
        .filter(pk=getattr(case, "pk", None))
        .first()
    )
    if (
        locked_case is None
        or not locked_case.active
        or locked_case.completed_at is not None
    ):
        raise ValidationError("An active uncompleted case is required.")
    membership = require_management(creator_membership.user, locked_case.building_id)
    links = CaseReport.objects.filter(case=locked_case).select_related("report")
    if any(link.report.is_private for link in links):
        raise ValidationError("Private requests cannot become community proposals.")
    if any(link.report.status == IssueReport.Status.IN_PROGRESS for link in links):
        raise ValidationError("Cases already proceeding without spending cannot add a proposal.")
    try:
        proposal = Proposal.objects.create(
            case=locked_case,
            building=locked_case.building,
            creator_membership=membership,
        )
    except IntegrityError as exc:
        raise ValidationError("A proposal already exists for this case.") from exc
    IssueReport.objects.filter(case_reports__case=locked_case).exclude(
        status__in=TERMINAL_STATUSES
    ).update(status=IssueReport.Status.PROPOSED)
    record_audit(
        membership.user,
        membership,
        "proposal.create",
        "Proposal",
        str(proposal.pk),
        "accepted",
        {"case_id": locked_case.pk},
    )
    return proposal


@transaction.atomic
def create_standalone_proposal(building, creator_membership) -> Proposal:
    membership = require_management(creator_membership.user, getattr(building, "pk", None))
    proposal = Proposal.objects.create(building=building, creator_membership=membership)
    record_audit(membership.user, membership, "proposal.create", "Proposal", str(proposal.pk),
                 "accepted", {"case_id": None})
    return proposal


@transaction.atomic
def decide_proposal(proposal, manager, proceed: bool, note="") -> Proposal:
    locked = Proposal.objects.select_for_update().get(pk=getattr(proposal, "pk", None))
    membership = require_management(manager, locked.building_id)
    if locked.status != Proposal.Status.PUBLISHED:
        raise ValidationError("Only published proposals can be decided.")
    if type(proceed) is not bool:
        raise ValidationError("Proceed must be a boolean.")
    now = timezone.now()
    locked.status = Proposal.Status.IN_PROGRESS if proceed else Proposal.Status.NOT_PROCEEDING
    locked.decided_by = membership
    locked.decided_at = now
    locked.decision_note = (note or "").strip()
    locked.closed_at = None if proceed else now
    locked.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "closed_at"])
    record_audit(manager, membership, "proposal.decided", "Proposal", str(locked.pk), "accepted",
                 {"proceed": proceed})
    return locked


@transaction.atomic
def publish_proposal_version(
    proposal, creator_membership, *, amount_vnd, contractor_name, fund_code, purpose,
    proposed_action, expected_schedule, quotation_versions, event_id
) -> ProposalVersion:
    locked_proposal = (
        Proposal.objects.select_for_update()
        .select_related("creator_membership__user", "building")
        .get(pk=getattr(proposal, "pk", None))
    )
    membership = require_management(creator_membership.user, locked_proposal.building_id)
    if type(amount_vnd) is not int or amount_vnd <= 0:
        raise ValidationError("Proposal amount must be a positive integer.")
    if not isinstance(contractor_name, str) or not contractor_name.strip():
        raise ValidationError("Contractor name is required.")
    if locked_proposal.status not in {Proposal.Status.DRAFT, Proposal.Status.PUBLISHED, Proposal.Status.IN_PROGRESS}:
        raise ValidationError("This proposal cannot receive another version.")
    for value, message in ((fund_code, "Funding source is required."), (purpose, "Problem or need is required."),
                           (proposed_action, "Proposed action is required."),
                           (expected_schedule, "Expected schedule is required.")):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(message)

    pairs = _quotation_pairs(locked_proposal.building_id, quotation_versions, lock=True)
    previous = locked_proposal.versions.order_by("-number").first()
    number = (previous.number if previous else 0) + 1
    snapshot, evidence_payload = _submission_snapshot(
        locked_proposal, amount_vnd, contractor_name.strip(), fund_code.strip(), purpose.strip(),
        proposed_action.strip(), expected_schedule.strip(), pairs, number
    )
    previous_hash = "0x" + previous.outbox_event.payload_hash if previous else ZERO_HASH
    event = queue_platform_event(
        event_id,
        EvidenceType.PROPOSAL_CREATED,
        evidence_payload,
        previous_hash,
        locked_proposal.building,
    )
    version = ProposalVersion.objects.create(
        proposal=locked_proposal,
        number=number,
        amount_vnd=amount_vnd,
        contractor_name=contractor_name.strip(),
        fund_code=fund_code.strip(),
        purpose=purpose.strip(),
        proposed_action=proposed_action.strip(),
        expected_schedule=expected_schedule.strip(),
        snapshot=snapshot,
        snapshot_hash=payload_hash(snapshot),
        creator_membership=membership,
        creator_signature="",
        outbox_event=event,
    )
    ProposalDocument.objects.bulk_create(
        [
            ProposalDocument(proposal_version=version, document_version=document)
            for pair in pairs
            for document in pair
        ]
    )
    locked_proposal.current_version = version
    locked_proposal.status = Proposal.Status.PUBLISHED
    locked_proposal.save(update_fields=["current_version", "status"])
    record_audit(
        membership.user,
        membership,
        "proposal.version.publish",
        "ProposalVersion",
        str(version.pk),
        "accepted",
        {"proposal_id": locked_proposal.pk, "number": number, "event_id": event.event_id},
    )
    return version
