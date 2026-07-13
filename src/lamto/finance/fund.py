from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, models, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from lamto.accounts.capabilities import FUND_RECORD, FUND_VERIFY
from lamto.accounts.models import Building, Organization
from lamto.accounts.services import require_capability
from lamto.audit.services import record_audit
from lamto.documents.models import DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import queue_signed_event, utc_rfc3339
from lamto.evidence.signatures import build_evidence_typed_data

from .models import (
    FundEntryVerification,
    MaintenanceFund,
    MaintenanceFundEntry,
    PublishedLedgerEntry,
)

EVIDENCE_ENTRY_TYPE = {
    MaintenanceFundEntry.EntryType.OPENING_BALANCE: "OPENING",
    MaintenanceFundEntry.EntryType.INFLOW: "INFLOW",
}

SOURCE_ENTRY_TYPES = frozenset(
    {
        MaintenanceFundEntry.EntryType.OPENING_BALANCE,
        MaintenanceFundEntry.EntryType.INFLOW,
    }
)

FINALIZED_ENTRY_TYPES = frozenset(
    {
        MaintenanceFundEntry.EntryType.OUTFLOW,
        MaintenanceFundEntry.EntryType.REVERSAL,
        MaintenanceFundEntry.EntryType.REPLACEMENT,
    }
)


def _allocate_pk(model):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT nextval(pg_get_serial_sequence(%s, 'id'))",
            [model._meta.db_table],
        )
        return cursor.fetchone()[0]


def allocate_fund_entry_id() -> int:
    """Reserve a MaintenanceFundEntry primary key for sign-before-write."""
    return int(_allocate_pk(MaintenanceFundEntry))


def get_or_create_fund(building) -> MaintenanceFund:
    building_id = getattr(building, "pk", building)
    fund, _ = MaintenanceFund.objects.get_or_create(building_id=building_id)
    return fund


def _require_evidence_pair(original, redacted, building_id, *, lock=False):
    original_id = getattr(original, "pk", None)
    redacted_id = getattr(redacted, "pk", None)
    if original_id is None or redacted_id is None:
        raise ValidationError("Fund source evidence documents are required.")
    queryset = DocumentVersion.objects.select_related("document").filter(
        pk__in={original_id, redacted_id}
    )
    if lock:
        queryset = queryset.select_for_update()
    versions = {version.pk: version for version in queryset}
    if original_id not in versions or redacted_id not in versions:
        raise ValidationError("Fund source evidence versions must still exist.")
    original = versions[original_id]
    redacted = versions[redacted_id]
    if (
        original.document.building_id != building_id
        or original.variant != DocumentVersion.Variant.ORIGINAL
        or original.scan_status != DocumentVersion.ScanStatus.CLEAN
        or original.redacts_id is not None
    ):
        raise ValidationError(
            "Fund evidence originals must be clean, safe, and in the fund building."
        )
    if (
        redacted.document_id != original.document_id
        or redacted.document.building_id != building_id
        or redacted.variant != DocumentVersion.Variant.REDACTED
        or redacted.scan_status != DocumentVersion.ScanStatus.CLEAN
        or redacted.redacts_id != original.pk
        or redacted.sha256 == original.sha256
    ):
        raise ValidationError(
            "Fund evidence requires a distinct clean redacted copy in the fund building."
        )
    return original, redacted


def _validate_source_amount(entry_type, amount_vnd):
    if entry_type not in SOURCE_ENTRY_TYPES:
        raise ValidationError("Only opening balance and inflow sources may be recorded.")
    if type(amount_vnd) is not int or amount_vnd <= 0:
        raise ValidationError("Fund source amount must be a positive integer VND amount.")


def _source_key(entry_type, fund_id, original_hash):
    return f"{entry_type}:{fund_id}:{original_hash}"


def _prior_verified_source_hash(fund):
    prior = (
        MaintenanceFundEntry.objects.filter(
            fund=fund,
            entry_type__in=SOURCE_ENTRY_TYPES,
            verification__isnull=False,
            verification__outbox_event__status=BlockchainOutboxEvent.Status.CONFIRMED,
            outbox_event__status=BlockchainOutboxEvent.Status.CONFIRMED,
        )
        .select_related("verification__outbox_event")
        .order_by("-recorded_at", "-pk")
        .first()
    )
    if prior is None:
        return "0x" + "00" * 32
    return "0x" + prior.verification.outbox_event.payload_hash


def build_fund_source_evidence_payload(
    fund_entry_id,
    entry_type,
    amount_vnd,
    evidence_original,
    evidence_redacted,
    maker_membership,
    checker_membership=None,
    timestamp=None,
):
    if type(fund_entry_id) is not int or fund_entry_id <= 0:
        raise ValidationError("Fund entry id must be a positive integer.")
    _validate_source_amount(entry_type, amount_vnd)
    if entry_type not in EVIDENCE_ENTRY_TYPE:
        raise ValidationError("Fund entry type is invalid for evidence.")
    if evidence_original is None or evidence_redacted is None:
        raise ValidationError("Fund source evidence documents are required.")
    entry_timestamp = timestamp or timezone.now()
    if not isinstance(entry_timestamp, type(timezone.now())) or entry_timestamp.tzinfo is None:
        raise ValidationError("Fund entry timestamp must be timezone-aware.")
    payload = {
        "fund_entry_id": fund_entry_id,
        "entry_type": EVIDENCE_ENTRY_TYPE[entry_type],
        "amount_vnd": amount_vnd,
        "source_document_original_hash": evidence_original.sha256,
        "source_document_redacted_hash": evidence_redacted.sha256,
        "maker_membership_id": maker_membership.pk,
        "entry_timestamp": utc_rfc3339(entry_timestamp),
    }
    if checker_membership is not None:
        payload["checker_membership_id"] = checker_membership.pk
    return payload


def build_fund_source_evidence_typed_data(
    fund,
    membership,
    fund_entry_id,
    entry_type,
    amount_vnd,
    evidence_original,
    evidence_redacted,
    event_id,
    timestamp=None,
    previous_hash=None,
):
    payload = build_fund_source_evidence_payload(
        fund_entry_id,
        entry_type,
        amount_vnd,
        evidence_original,
        evidence_redacted,
        membership,
        timestamp=timestamp,
    )
    if previous_hash is None:
        previous_hash = _prior_verified_source_hash(fund)
    return build_evidence_typed_data(
        event_id,
        EvidenceType.FUND_ENTRY,
        "0x" + payload_hash(payload),
        previous_hash,
    )


def build_fund_verification_evidence_payload(entry, verifier, timestamp=None):
    verified_at = timestamp or timezone.now()
    return build_fund_source_evidence_payload(
        entry.pk,
        entry.entry_type,
        entry.amount_vnd,
        entry.evidence_original,
        entry.evidence_redacted,
        entry.recorder,
        checker_membership=verifier,
        timestamp=verified_at,
    )


def build_fund_verification_evidence_typed_data(entry, membership, event_id, timestamp=None):
    payload = build_fund_verification_evidence_payload(
        entry, membership, timestamp=timestamp
    )
    return build_evidence_typed_data(
        event_id,
        EvidenceType.FUND_ENTRY,
        "0x" + payload_hash(payload),
        "0x" + entry.outbox_event.payload_hash,
    )


def _locked_fund(fund):
    locked = (
        MaintenanceFund.objects.select_for_update()
        .select_related("building")
        .filter(pk=getattr(fund, "pk", None))
        .first()
    )
    if locked is None:
        raise ValidationError("Maintenance fund does not exist.")
    return locked


def _locked_entry(entry):
    locked_id = (
        MaintenanceFundEntry.objects.select_for_update()
        .filter(pk=getattr(entry, "pk", None))
        .values_list("pk", flat=True)
        .first()
    )
    if locked_id is None:
        raise ValidationError("Fund entry does not exist.")
    return (
        MaintenanceFundEntry.objects.select_related(
            "fund__building",
            "recorder__user",
            "outbox_event",
            "evidence_original",
            "evidence_redacted",
        ).get(pk=locked_id)
    )


@transaction.atomic
def record_fund_source(
    fund,
    entry_type,
    amount_vnd,
    evidence_original,
    evidence_redacted,
    recorder,
    signature,
    event_id,
    fund_entry_id=None,
    timestamp=None,
    source_key=None,
) -> MaintenanceFundEntry:
    fund = _locked_fund(fund)
    actor = require_capability(recorder.user, recorder.pk, FUND_RECORD)
    if actor.organization.kind != Organization.Kind.BOARD:
        raise PermissionDenied("Only a Board membership may record fund sources.")
    if actor.organization.building_id != fund.building_id:
        raise PermissionDenied("Board must belong to the fund building.")
    _validate_source_amount(entry_type, amount_vnd)
    evidence_original, evidence_redacted = _require_evidence_pair(
        evidence_original,
        evidence_redacted,
        fund.building_id,
        lock=True,
    )
    if fund_entry_id is None:
        fund_entry_id = allocate_fund_entry_id()
    if type(fund_entry_id) is not int or fund_entry_id <= 0:
        raise ValidationError("Fund entry id must be a positive integer.")
    if MaintenanceFundEntry.objects.filter(pk=fund_entry_id).exists():
        raise ValidationError("Fund entry id is already used.")
    entry_timestamp = timestamp or timezone.now()
    if not isinstance(entry_timestamp, type(timezone.now())) or entry_timestamp.tzinfo is None:
        raise ValidationError("Fund entry timestamp must be timezone-aware.")
    key = source_key or _source_key(entry_type, fund.pk, evidence_original.sha256)
    if MaintenanceFundEntry.objects.filter(source_key=key).exists():
        raise ValidationError("Fund source key already exists.")
    previous_hash = _prior_verified_source_hash(fund)
    payload = build_fund_source_evidence_payload(
        fund_entry_id,
        entry_type,
        amount_vnd,
        evidence_original,
        evidence_redacted,
        actor,
        timestamp=entry_timestamp,
    )
    event = queue_signed_event(
        event_id,
        EvidenceType.FUND_ENTRY,
        payload,
        previous_hash,
        actor,
        signature,
    )
    entry = MaintenanceFundEntry(
        pk=fund_entry_id,
        fund=fund,
        entry_type=entry_type,
        amount_vnd=amount_vnd,
        evidence_original=evidence_original,
        evidence_redacted=evidence_redacted,
        evidence_original_hash=evidence_original.sha256,
        evidence_redacted_hash=evidence_redacted.sha256,
        recorder=actor,
        wallet=event.signer_wallet,
        signature=event.signature,
        outbox_event=event,
        source_key=key,
        recorded_at=timezone.now(),
    )
    entry.save(force_insert=True)
    record_audit(
        actor.user,
        actor,
        "fund.record",
        "MaintenanceFundEntry",
        str(entry.pk),
        "accepted",
        {
            "entry_type": entry_type,
            "amount_vnd": amount_vnd,
            "event_id": event.event_id,
        },
    )
    return entry


def verify_fund_source(
    entry,
    verifier,
    signature,
    event_id,
    timestamp=None,
) -> FundEntryVerification:
    denied = False
    denied_target = None
    denied_actor = verifier
    with transaction.atomic():
        entry = _locked_entry(entry)
        actor = require_capability(verifier.user, verifier.pk, FUND_VERIFY)
        if actor.organization.kind != Organization.Kind.BOARD:
            raise PermissionDenied("Only a Board membership may verify fund sources.")
        if actor.organization.building_id != entry.fund.building_id:
            raise PermissionDenied("Board must belong to the fund building.")
        if entry.entry_type not in SOURCE_ENTRY_TYPES:
            raise ValidationError("Only opening balance and inflow sources may be verified.")
        if entry.recorder is None:
            raise ValidationError("Fund source has no recorder.")
        if actor.user_id == entry.recorder.user_id:
            denied = True
            denied_target = entry
            denied_actor = actor
        else:
            if FundEntryVerification.objects.filter(entry=entry).exists():
                raise ValidationError("Fund source has already been verified.")
            if entry.outbox_event is None:
                raise ValidationError("Fund source maker event is required.")
            verification_timestamp = timestamp or entry.recorded_at or timezone.now()
            payload = build_fund_verification_evidence_payload(
                entry, actor, timestamp=verification_timestamp
            )
            event = queue_signed_event(
                event_id,
                EvidenceType.FUND_ENTRY,
                payload,
                "0x" + entry.outbox_event.payload_hash,
                actor,
                signature,
            )
            verification = FundEntryVerification.objects.create(
                entry=entry,
                membership=actor,
                wallet=event.signer_wallet,
                signature=event.signature,
                outbox_event=event,
                verified_at=timezone.now(),
            )
            record_audit(
                actor.user,
                actor,
                "fund.verify",
                "FundEntryVerification",
                str(verification.pk),
                "accepted",
                {
                    "entry_id": entry.pk,
                    "event_id": event.event_id,
                },
            )
            return verification
    if denied:
        record_audit(
            denied_actor.user,
            denied_actor,
            "fund.verify",
            "MaintenanceFundEntry",
            str(denied_target.pk),
            "denied",
            {"reason": "fund recorder cannot verify own source"},
        )
        raise PermissionDenied("Fund recorder cannot verify their own source.")


def _source_verified_q():
    return Q(
        entry_type__in=SOURCE_ENTRY_TYPES,
        outbox_event__status=BlockchainOutboxEvent.Status.CONFIRMED,
        verification__outbox_event__status=BlockchainOutboxEvent.Status.CONFIRMED,
    )


def _finalized_posting_q():
    return Q(
        entry_type__in=FINALIZED_ENTRY_TYPES,
        publication__ledger_entry__isnull=False,
    ) | Q(
        entry_type__in=FINALIZED_ENTRY_TYPES,
        proposal__published_ledger_entry__isnull=False,
    ) | Q(
        entry_type__in=FINALIZED_ENTRY_TYPES,
        correction_id__isnull=False,
    )


def fund_balance(building_id, verified_only=True) -> int:
    if type(building_id) is not int or building_id <= 0:
        building_id = getattr(building_id, "pk", None)
    if building_id is None:
        raise ValidationError("Building is required.")
    if not Building.objects.filter(pk=building_id).exists():
        raise ValidationError("Building does not exist.")
    fund = MaintenanceFund.objects.filter(building_id=building_id).first()
    if fund is None:
        return 0
    entries = MaintenanceFundEntry.objects.filter(fund=fund)
    if verified_only:
        entries = entries.filter(_source_verified_q() | _finalized_posting_q())
    else:
        entries = entries.filter(
            Q(entry_type__in=SOURCE_ENTRY_TYPES) | _finalized_posting_q()
        )
    total = entries.aggregate(total=Sum("amount_vnd"))["total"]
    return int(total or 0)


def create_publication_outflow(
    *,
    fund,
    proposal,
    publication,
    amount_vnd,
    recorded_at=None,
) -> MaintenanceFundEntry:
    """Insert-only outflow for a finalized publication. Caller must be in a transaction."""
    if type(amount_vnd) is not int or amount_vnd <= 0:
        raise ValidationError("Outflow magnitude must be a positive integer VND amount.")
    negative = -amount_vnd
    source_key = f"OUTFLOW:proposal:{proposal.pk}"
    existing = MaintenanceFundEntry.objects.filter(source_key=source_key).first()
    if existing is not None:
        return existing
    entry = MaintenanceFundEntry.objects.create(
        fund=fund,
        entry_type=MaintenanceFundEntry.EntryType.OUTFLOW,
        amount_vnd=negative,
        proposal=proposal,
        publication=publication,
        source_key=source_key,
        recorded_at=recorded_at or timezone.now(),
    )
    return entry
