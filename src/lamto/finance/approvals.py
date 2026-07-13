from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from lamto.accounts.capabilities import PROPOSAL_APPROVE
from lamto.accounts.models import Organization
from lamto.accounts.services import require_capability
from lamto.audit.services import record_audit
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import queue_signed_event, utc_rfc3339
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.maintenance.models import WorkOrder

from .models import ApprovalDecision, Proposal, ProposalVersion


PENDING_ANCHORING_LABEL = "Pending blockchain anchoring"
ANCHORED_LABEL = "Blockchain anchored"

STAGE_BY_ORGANIZATION_KIND = {
    Organization.Kind.BOARD: ApprovalDecision.Stage.BOARD,
    Organization.Kind.RESIDENT_REP: ApprovalDecision.Stage.RESIDENT_REP,
}
EVENT_TYPE_BY_STAGE = {
    ApprovalDecision.Stage.BOARD: EvidenceType.BOARD_APPROVAL,
    ApprovalDecision.Stage.RESIDENT_REP: EvidenceType.REPRESENTATIVE_APPROVAL,
}


def _stage_for_membership(membership):
    try:
        return STAGE_BY_ORGANIZATION_KIND[membership.organization.kind]
    except KeyError as exc:
        raise PermissionDenied("Only Board and resident-representative memberships may approve.") from exc


def _decision_timestamp(version, decision_timestamp=None):
    # The version creation time is stable and available to both the signing UI and
    # the authoritative write. The database timestamp below records when the
    # approval was actually committed.
    return decision_timestamp or version.created_at or timezone.now()


def build_approval_evidence_payload(
    version, membership, decision, decision_timestamp=None
):
    """Build the exact public payload signed for a normal approval decision."""
    if decision not in ApprovalDecision.Decision.values:
        raise ValidationError("Approval decision is invalid.")
    _stage_for_membership(membership)
    timestamp = _decision_timestamp(version, decision_timestamp)
    return {
        "proposal_hash": version.snapshot_hash,
        "decision": decision,
        "actor_organization_id": membership.organization_id,
        "decision_timestamp": utc_rfc3339(timestamp),
    }


def build_approval_evidence_typed_data(
    version, membership, decision, event_id, decision_timestamp=None
):
    stage = _stage_for_membership(membership)
    payload = build_approval_evidence_payload(
        version, membership, decision, decision_timestamp
    )
    previous_hash = _approval_previous_hash(version, stage)
    return build_evidence_typed_data(
        event_id,
        EVENT_TYPE_BY_STAGE[stage],
        "0x" + payload_hash(payload),
        previous_hash,
    )


def _approval_previous_hash(version, stage, board_decision=None):
    if stage == ApprovalDecision.Stage.BOARD:
        return "0x" + version.outbox_event.payload_hash
    if board_decision is None:
        board_decision = (
            ApprovalDecision.objects.select_related("outbox_event")
            .filter(version=version, stage=ApprovalDecision.Stage.BOARD)
            .first()
        )
    if board_decision is None:
        raise ValidationError("Board approval is required before resident co-approval.")
    return "0x" + board_decision.outbox_event.payload_hash


def _locked_version(version):
    locked = (
        ProposalVersion.objects.select_for_update()
        .select_related("proposal", "proposal__work_order__case", "outbox_event")
        .filter(pk=getattr(version, "pk", None))
        .first()
    )
    if locked is None:
        raise ValidationError("Proposal version does not exist.")
    proposal = (
        Proposal.objects.select_for_update()
        .select_related("work_order__case")
        .get(pk=locked.proposal_id)
    )
    locked.proposal = proposal
    return locked


@transaction.atomic
def decide_proposal(
    version, membership, decision, reason, signature, event_id, decision_timestamp=None
) -> ApprovalDecision:
    version = _locked_version(version)
    proposal = version.proposal
    work_order = proposal.work_order
    if proposal.mode != Proposal.Mode.NORMAL:
        raise ValidationError("Only normal proposals use fixed approvals.")
    if proposal.current_version_id != version.pk:
        raise ValidationError("Approval must target the current proposal version.")
    if payload_hash(version.snapshot) != version.snapshot_hash:
        raise ValidationError("Proposal snapshot hash is invalid.")

    membership = require_capability(membership.user, membership.pk, PROPOSAL_APPROVE)
    if membership.organization.building_id != work_order.case.building_id:
        raise PermissionDenied("Approver must belong to the work-order building.")
    stage = _stage_for_membership(membership)
    if decision not in ApprovalDecision.Decision.values:
        raise ValidationError("Approval decision is invalid.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("Approval reason is required.")
    if ApprovalDecision.objects.filter(version=version, stage=stage).exists():
        raise ValidationError("This approval stage has already been decided.")

    board_decision = None
    if stage == ApprovalDecision.Stage.RESIDENT_REP:
        board_decision = (
            ApprovalDecision.objects.select_for_update()
            .select_related("outbox_event")
            .filter(version=version, stage=ApprovalDecision.Stage.BOARD)
            .first()
        )
        if board_decision is None or board_decision.decision != ApprovalDecision.Decision.APPROVE:
            raise ValidationError("A Board approval is required before resident co-approval.")

    payload = build_approval_evidence_payload(
        version, membership, decision, decision_timestamp
    )
    event = queue_signed_event(
        event_id,
        EVENT_TYPE_BY_STAGE[stage],
        payload,
        _approval_previous_hash(version, stage, board_decision),
        membership,
        signature,
    )
    approval = ApprovalDecision.objects.create(
        version=version,
        stage=stage,
        decision=decision,
        reason=reason.strip(),
        membership=membership,
        wallet=event.signer_wallet,
        signature=event.signature,
        outbox_event=event,
        decided_at=timezone.now(),
    )

    proposal.status = (
        Proposal.Status.REJECTED
        if decision == ApprovalDecision.Decision.REJECT
        else Proposal.Status.IN_REVIEW
    )
    approvals = {
        row.stage: row.decision
        for row in ApprovalDecision.objects.filter(version=version)
    }
    if approvals.get(ApprovalDecision.Stage.BOARD) == ApprovalDecision.Decision.APPROVE and approvals.get(
        ApprovalDecision.Stage.RESIDENT_REP
    ) == ApprovalDecision.Decision.APPROVE:
        proposal.status = Proposal.Status.NORMAL_AUTHORIZED
        if work_order.requires_spending:
            work_order.authorization_status = WorkOrder.AuthorizationStatus.AUTHORIZED
            work_order.save(update_fields=["authorization_status"])
    proposal.save(update_fields=["status"])
    record_audit(
        membership.user,
        membership,
        "proposal.approve" if decision == ApprovalDecision.Decision.APPROVE else "proposal.reject",
        "ApprovalDecision",
        str(approval.pk),
        "accepted" if decision == ApprovalDecision.Decision.APPROVE else "rejected",
        {
            "proposal_version_id": version.pk,
            "stage": stage,
            "decision": decision,
            "event_id": event.event_id,
            "reason": approval.reason,
        },
    )
    return approval


def proposal_is_locally_authorized(version) -> bool:
    version = (
        ProposalVersion.objects.select_related("proposal__work_order")
        .filter(pk=getattr(version, "pk", None))
        .first()
    )
    if version is None or payload_hash(version.snapshot) != version.snapshot_hash:
        return False
    proposal = version.proposal
    if (
        proposal.mode != Proposal.Mode.NORMAL
        or proposal.current_version_id != version.pk
        or proposal.status != Proposal.Status.NORMAL_AUTHORIZED
    ):
        return False
    decisions = {
        row.stage: row.decision
        for row in ApprovalDecision.objects.filter(version=version)
    }
    if any(
        decisions.get(stage) != ApprovalDecision.Decision.APPROVE
        for stage in ApprovalDecision.Stage.values
    ):
        return False
    return (
        not version.proposal.work_order.requires_spending
        or version.proposal.work_order.authorization_status
        == WorkOrder.AuthorizationStatus.AUTHORIZED
    )


def proposal_verification_label(version):
    if not proposal_is_locally_authorized(version):
        return None
    version = ProposalVersion.objects.get(pk=version.pk)
    events = [version.outbox_event]
    events.extend(
        BlockchainOutboxEvent.objects.filter(
            approval_decision__version=version
        )
    )
    if any(event.status != BlockchainOutboxEvent.Status.CONFIRMED for event in events):
        return PENDING_ANCHORING_LABEL
    return ANCHORED_LABEL
