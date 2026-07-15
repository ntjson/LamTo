"""Shared helpers for staff two-phase wallet-signed forms (spec 4.3).

Both create-proposal and fund-record sign a server-computed EIP-712 payload,
so they upload evidence + allocate a record id first, then sign. This module
holds the pieces both flows share; all domain mutations stay in finance.*.
"""

import secrets

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from lamto.documents.models import Document, DocumentVersion
from lamto.documents.scanner import scan_with_clamav
from lamto.documents.services import add_redacted_copy, create_document_version


def new_event_id() -> str:
    """Server-generated random bytes32 event id (spec 2.2 opacity)."""
    return "0x" + secrets.token_hex(32)


def upload_document_pair(building, kind, uploader, original_file, redacted_file):
    """Upload an (original, redacted) PDF pair through the ClamAV pipeline.

    Returns two linked clean DocumentVersions (redacted.redacts == original) —
    the exact shape the proposal/fund evidence validators require. Raises
    ValidationError on any rejection, quarantine, or identical bytes so views
    surface one uniform error.

    Both steps run inside transaction.atomic(). If the redacted upload fails
    after the original was written, the transaction rolls back so no unpaired
    original remains valid as proposal/fund evidence.
    """
    try:
        with transaction.atomic():
            document = Document.objects.create(building=building, kind=kind)
            original = create_document_version(
                document,
                original_file,
                DocumentVersion.Variant.ORIGINAL,
                uploader,
                scan_with_clamav,
            )
            redacted = add_redacted_copy(original, redacted_file, uploader, scan_with_clamav)
    except ValueError as error:  # DocumentUploadRejected/Quarantined + identical-bytes all subclass ValueError
        raise ValidationError(f"Evidence upload failed: {error}") from error
    return original, redacted


def _disable_document_append_only_triggers():
    """Allow owner-level maintenance deletes/updates of append-only document rows.

    Document / DocumentVersion have BEFORE UPDATE OR DELETE triggers that reject
    mutation for normal app paths. Cleanup of stale prepared-op orphans is an
    ops maintenance action and must run as the table owner (e.g. lamto_owner).
    Callers must re-enable via `_enable_document_append_only_triggers`.
    """
    with connection.cursor() as cursor:
        # Flush deferred FK checks so ALTER TABLE is allowed mid-transaction.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("ALTER TABLE documents_documentversion DISABLE TRIGGER USER")
        cursor.execute("ALTER TABLE documents_document DISABLE TRIGGER USER")


def _enable_document_append_only_triggers():
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE documents_documentversion ENABLE TRIGGER USER")
        cursor.execute("ALTER TABLE documents_document ENABLE TRIGGER USER")


def _hard_delete_document(document_id: int) -> None:
    """Delete a Document and its versions, bypassing instance-level InsertOnly guards.

    Redacted versions reference originals via PROTECT self-FK, so delete redacted
    rows first. Uses QuerySet.delete() (instance .delete() raises append-only).
    """
    DocumentVersion.objects.filter(document_id=document_id, redacts__isnull=False).delete()
    DocumentVersion.objects.filter(document_id=document_id).delete()
    Document.objects.filter(pk=document_id).delete()


def _referenced_document_ids():
    """Document pks whose versions are linked from domain evidence FKs."""
    from lamto.finance.models import (
        AcceptanceRecord,
        CorrectionDocument,
        MaintenanceFundEntry,
        PaymentEvidence,
        ProposalDocument,
    )
    from lamto.maintenance.models import ReportPhoto, WorkUpdateEvidence

    def _docs_from_version_ids(qs_values):
        version_ids = [vid for vid in qs_values if vid is not None]
        if not version_ids:
            return set()
        return set(
            DocumentVersion.objects.filter(pk__in=version_ids).values_list(
                "document_id", flat=True
            )
        )

    protected = set(
        ProposalDocument.objects.values_list("document_version__document_id", flat=True)
    )
    for field in ("evidence_original_id", "evidence_redacted_id"):
        protected |= _docs_from_version_ids(
            MaintenanceFundEntry.objects.exclude(**{field: None}).values_list(
                field, flat=True
            )
        )
    for model, fields in (
        (
            AcceptanceRecord,
            (
                "invoice_original_id",
                "invoice_redacted_id",
                "acceptance_original_id",
                "acceptance_redacted_id",
            ),
        ),
        (PaymentEvidence, ("proof_original_id", "proof_redacted_id")),
    ):
        for field in fields:
            protected |= _docs_from_version_ids(
                model.objects.exclude(**{field: None}).values_list(field, flat=True)
            )
    protected |= _docs_from_version_ids(
        CorrectionDocument.objects.values_list("version_id", flat=True)
    )
    protected |= _docs_from_version_ids(
        ReportPhoto.objects.values_list("version_id", flat=True)
    )
    protected |= _docs_from_version_ids(
        WorkUpdateEvidence.objects.values_list("version_id", flat=True)
    )
    return protected


def cleanup_stale_prepared_ops(*, older_than_hours=24):
    """Expire prepared-but-never-signed staff drafts and orphan document pairs.

    Removes:
    - Document rows whose versions are all older than the threshold and that
      are not referenced by any domain evidence FK (proposal docs, fund,
      acceptance, payment, corrections, report photos, work-update evidence).
    - Proposal rows still without a current_version older than threshold.

    Does not delete signed/submitted proposal versions, verified fund entries,
    or any outbox-linked evidence. Returns a dict of deletion counts.

    Document tables are DB append-only; this function briefly disables their
    user triggers as table owner inside a single transaction so a crash
    re-enables them on rollback. Run from an owner-role ops job, not the
    restricted web writer role.
    """
    from datetime import timedelta

    from django.utils import timezone

    from lamto.finance.models import Proposal

    cutoff = timezone.now() - timedelta(hours=older_than_hours)
    documents_deleted = 0
    protected = _referenced_document_ids()

    stale_docs = (
        Document.objects.exclude(pk__in=protected)
        .filter(versions__created_at__lt=cutoff)
        .distinct()
    )
    orphan_ids = [
        doc.pk
        for doc in stale_docs
        if not doc.versions.filter(created_at__gte=cutoff).exists()
    ]

    if orphan_ids:
        # ALTER TABLE is transactional in Postgres: wrap disable+delete+enable
        # so a mid-flight crash rolls triggers back to ENABLED.
        with transaction.atomic():
            _disable_document_append_only_triggers()
            try:
                for document_id in orphan_ids:
                    _hard_delete_document(document_id)
                    documents_deleted += 1
            finally:
                _enable_document_append_only_triggers()

    proposals_deleted, _ = Proposal.objects.filter(
        current_version__isnull=True,
        created_at__lt=cutoff,
    ).delete()

    return {
        "documents_deleted": documents_deleted,
        "proposals_deleted": proposals_deleted,
    }
