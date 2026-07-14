"""Auditor CSV exports with formula neutralization and capability gates."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone as dt_timezone

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, StreamingHttpResponse
from django.views.decorators.http import require_GET

from lamto.accounts.capabilities import AUDIT_EXPORT
from lamto.accounts.models import OrganizationMembership
from lamto.accounts.security import deny_tech_admin_business_access, require_staff_mfa
from lamto.audit.models import AuditEvent
from lamto.audit.services import record_audit
from lamto.documents.models import DocumentVersion
from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.models import (
    ApprovalDecision,
    Correction,
    MaintenanceFundEntry,
    VerificationObservation,
)
from lamto.web.staff import require_staff_capability


FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralize_cell(value) -> str:
    """Neutralize spreadsheet-formula prefixes in text cells; never emit raw secrets."""
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in FORMULA_PREFIXES:
        return "'" + text
    return text


class _Echo:
    def write(self, value):
        return value


def _csv_stream(header: list[str], rows):
    pseudo = _Echo()
    writer = csv.writer(pseudo)
    yield writer.writerow([neutralize_cell(c) for c in header])
    for row in rows:
        yield writer.writerow([neutralize_cell(c) for c in row])


def _require_auditor_export(request):
    require_staff_mfa(request)
    membership, memberships = require_staff_capability(request, AUDIT_EXPORT)
    deny_tech_admin_business_access(membership)
    if membership.organization.kind != membership.organization.Kind.AUDITOR:
        # Capability map already enforces auditor org, but double-check kind.
        if membership.role != OrganizationMembership.Role.AUDITOR:
            raise PermissionDenied("Auditor organization required.")
    return membership, memberships


@login_required
@require_GET
def audit_export(request):
    """Stream fixed-column CSV covering audit/finance/evidence surfaces for auditors."""
    try:
        membership, _ = _require_auditor_export(request)
    except PermissionDenied as error:
        try:
            mid = request.session.get("active_membership_id")
            m = OrganizationMembership.objects.filter(pk=mid, user=request.user).first()
            record_audit(
                request.user,
                m,
                "audit.export",
                "Export",
                "audit",
                "denied",
                {"reason": str(error)},
            )
        except Exception:
            pass
        raise

    building_id = membership.organization.building_id
    kind = (request.GET.get("kind") or "audit_events").strip()

    try:
        if kind == "fund_entries":
            header, rows = _fund_entry_rows(building_id)
        elif kind == "approvals":
            header, rows = _approval_rows(building_id)
        elif kind == "documents":
            header, rows = _document_rows(building_id)
        elif kind == "outbox":
            header, rows = _outbox_rows(building_id)
        elif kind == "observations":
            header, rows = _observation_rows(building_id)
        elif kind == "corrections":
            header, rows = _correction_rows(building_id)
        else:
            kind = "audit_events"
            header, rows = _audit_event_rows(building_id)

        record_audit(
            request.user,
            membership,
            "audit.export",
            "Export",
            kind,
            "accepted",
            {"kind": kind},
        )
    except Exception as error:
        try:
            record_audit(
                request.user,
                membership,
                "audit.export",
                "Export",
                kind,
                "denied",
                {"reason": type(error).__name__},
            )
        except Exception:
            pass
        raise

    filename = f"lamto-{kind}-{datetime.now(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
    response = StreamingHttpResponse(
        _csv_stream(header, rows),
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _audit_event_rows(building_id):
    header = [
        "id",
        "created_at",
        "actor_id",
        "membership_id",
        "action",
        "target_type",
        "target_id",
        "result",
    ]
    qs = (
        AuditEvent.objects.filter(membership__organization__building_id=building_id)
        .order_by("id")
        .values_list(
            "id",
            "created_at",
            "actor_id",
            "membership_id",
            "action",
            "target_type",
            "target_id",
            "result",
        )
        .iterator(chunk_size=500)
    )
    return header, qs


def _fund_entry_rows(building_id):
    header = [
        "id",
        "entry_type",
        "amount_vnd",
        "evidence_original_hash",
        "evidence_redacted_hash",
        "recorder_membership_id",
        "wallet_address",
        "outbox_event_id",
        "transaction_hash",
        "source_key",
        "recorded_at",
    ]
    # Never include bank account numbers or private keys.
    rows = []
    for entry in (
        MaintenanceFundEntry.objects.filter(fund__building_id=building_id)
        .select_related("wallet", "outbox_event", "recorder")
        .order_by("id")
        .iterator(chunk_size=200)
    ):
        rows.append(
            [
                entry.id,
                entry.entry_type,
                entry.amount_vnd,
                entry.evidence_original_hash,
                entry.evidence_redacted_hash,
                entry.recorder_id,
                entry.wallet.address if entry.wallet_id else "",
                entry.outbox_event.event_id if entry.outbox_event_id else "",
                entry.outbox_event.transaction_hash if entry.outbox_event_id else "",
                entry.source_key,
                entry.recorded_at.isoformat() if entry.recorded_at else "",
            ]
        )
    return header, rows


def _approval_rows(building_id):
    header = [
        "id",
        "proposal_version_id",
        "stage",
        "decision",
        "membership_id",
        "wallet_address",
        "signature",
        "outbox_event_id",
        "transaction_hash",
        "decided_at",
    ]
    rows = []
    for row in (
        ApprovalDecision.objects.filter(
            version__proposal__work_order__case__building_id=building_id
        )
        .select_related("wallet", "outbox_event", "membership")
        .order_by("id")
        .iterator(chunk_size=200)
    ):
        rows.append(
            [
                row.id,
                row.version_id,
                row.stage,
                row.decision,
                row.membership_id,
                row.wallet.address if row.wallet_id else "",
                row.signature,
                row.outbox_event.event_id if row.outbox_event_id else "",
                row.outbox_event.transaction_hash if row.outbox_event_id else "",
                row.decided_at.isoformat() if row.decided_at else "",
            ]
        )
    return header, rows


def _document_rows(building_id):
    header = [
        "id",
        "document_id",
        "version",
        "variant",
        "filename",
        "content_type",
        "byte_size",
        "sha256",
        "scan_status",
        "uploader_id",
        "created_at",
    ]
    # Hashes only — never raw file bytes.
    qs = (
        DocumentVersion.objects.filter(document__building_id=building_id)
        .order_by("id")
        .values_list(
            "id",
            "document_id",
            "version",
            "variant",
            "filename",
            "content_type",
            "byte_size",
            "sha256",
            "scan_status",
            "uploader_id",
            "created_at",
        )
        .iterator(chunk_size=500)
    )
    return header, qs


def _outbox_rows(building_id):
    header = [
        "id",
        "event_id",
        "event_type",
        "payload_hash",
        "status",
        "transaction_hash",
        "chain_confirmed_block",
        "signer_wallet_address",
        "created_at",
        "confirmed_at",
    ]
    rows = []
    for event in (
        BlockchainOutboxEvent.objects.filter(building_id=building_id)
        .select_related("signer_wallet")
        .order_by("id")
        .iterator(chunk_size=200)
    ):
        rows.append(
            [
                event.id,
                event.event_id,
                event.event_type,
                event.payload_hash,
                event.status,
                event.transaction_hash,
                event.chain_confirmed_block,
                event.signer_wallet.address if event.signer_wallet_id else "",
                event.created_at.isoformat() if event.created_at else "",
                event.confirmed_at.isoformat() if event.confirmed_at else "",
            ]
        )
    return header, rows


def _observation_rows(building_id):
    header = [
        "id",
        "published_entry_id",
        "result",
        "details",
        "observed_at",
    ]
    rows = []
    for obs in (
        VerificationObservation.objects.filter(
            published_entry__case__building_id=building_id
        )
        .order_by("id")
        .iterator(chunk_size=200)
    ):
        details = getattr(obs, "details", None) or getattr(obs, "notes", "") or ""
        if isinstance(details, dict):
            details = str(details)
        rows.append(
            [
                obs.id,
                obs.published_entry_id,
                obs.result,
                details,
                obs.observed_at.isoformat() if obs.observed_at else "",
            ]
        )
    return header, rows


def _correction_rows(building_id):
    header = [
        "id",
        "original_entry_id",
        "operator_membership_id",
        "reason",
        "replacement_payload_hash",
        "wallet_address",
        "outbox_event_id",
        "transaction_hash",
        "created_at",
    ]
    rows = []
    for corr in (
        Correction.objects.filter(original_entry__case__building_id=building_id)
        .select_related("wallet", "outbox_event", "operator")
        .order_by("id")
        .iterator(chunk_size=200)
    ):
        rows.append(
            [
                corr.id,
                corr.original_entry_id,
                corr.operator_id,
                corr.reason,
                corr.replacement_payload_hash,
                corr.wallet.address if corr.wallet_id else "",
                corr.outbox_event.event_id if corr.outbox_event_id else "",
                corr.outbox_event.transaction_hash if corr.outbox_event_id else "",
                corr.created_at.isoformat() if corr.created_at else "",
            ]
        )
    return header, rows
