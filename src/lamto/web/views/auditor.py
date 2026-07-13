"""Auditor workspace: read-only search and integrity verify."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from lamto.accounts.capabilities import AUDIT_EXPORT
from lamto.accounts.models import OrganizationMembership
from lamto.audit.services import record_audit
from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.fund import fund_balance
from lamto.finance.integrity import verify_published_entry
from lamto.finance.models import PublishedLedgerEntry, VerificationObservation
from lamto.web.staff import require_staff_capability, resolve_active_membership, staff_context


def _require_auditor(membership):
    if membership.role != OrganizationMembership.Role.AUDITOR:
        from lamto.accounts.models import CapabilityGrant

        if not CapabilityGrant.objects.filter(
            membership=membership, code=AUDIT_EXPORT
        ).exists():
            raise PermissionDenied("Auditor access required.")


@login_required
@require_http_methods(["GET", "POST"])
def audit_search(request):
    membership, memberships = resolve_active_membership(request)
    _require_auditor(membership)
    building_id = membership.organization.building_id

    entry = None
    entry_id = request.GET.get("entry") or request.POST.get("entry")
    outbox_id = request.GET.get("outbox")
    if entry_id:
        try:
            entry = (
                PublishedLedgerEntry.objects.select_related(
                    "snapshot__outbox_event",
                    "work_order",
                    "case",
                    "proposal__current_version",
                    "payment__verification__membership__user",
                    "payment__outbox_event",
                    "payment__recorder__user",
                )
                .filter(pk=int(entry_id), case__building_id=building_id)
                .first()
            )
        except (TypeError, ValueError):
            entry = None

    if request.method == "POST" and request.POST.get("action") == "verify" and entry:
        try:
            observation = verify_published_entry(entry.pk)
        except (ValidationError, PermissionDenied) as error:
            messages.error(request, str(error))
        else:
            record_audit(
                request.user,
                membership,
                "workspace.integrity.verify",
                "PublishedLedgerEntry",
                str(entry.pk),
                "accepted",
                {
                    "observation_id": observation.pk,
                    "result": observation.result,
                },
            )
            messages.success(
                request, f"Verification observation appended: {observation.result}"
            )
            return redirect(f"{request.path}?entry={entry.pk}")

    observations = []
    doc_hashes = []
    signer_addresses = []
    tx_ids = []
    balance = None
    outbox_event = None

    if outbox_id:
        try:
            outbox_event = BlockchainOutboxEvent.objects.filter(pk=int(outbox_id)).first()
        except (TypeError, ValueError):
            outbox_event = None

    if entry is not None:
        observations = list(
            entry.verification_observations.order_by("-observed_at")[:20]
        )
        balance = fund_balance(building_id, verified_only=True)
        acceptance = getattr(entry.work_order, "acceptance", None)
        if acceptance is not None:
            for version in (
                acceptance.invoice_original,
                acceptance.invoice_redacted,
                acceptance.acceptance_original,
                acceptance.acceptance_redacted,
            ):
                if version is not None:
                    doc_hashes.append(
                        {
                            "filename": version.filename,
                            "variant": version.variant,
                            "sha256": version.sha256,
                        }
                    )
        payment = entry.payment
        if payment is not None:
            for version in (payment.proof_original, payment.proof_redacted):
                if version is not None:
                    doc_hashes.append(
                        {
                            "filename": version.filename,
                            "variant": version.variant,
                            "sha256": version.sha256,
                        }
                    )
            if payment.wallet_id:
                signer_addresses.append(payment.wallet.address)
            if payment.outbox_event and payment.outbox_event.transaction_hash:
                tx_ids.append(payment.outbox_event.transaction_hash)
        if entry.snapshot.outbox_event and entry.snapshot.outbox_event.transaction_hash:
            tx_ids.append(entry.snapshot.outbox_event.transaction_hash)
        if entry.snapshot.wallet_id:
            signer_addresses.append(entry.snapshot.wallet.address)

    return render(
        request,
        "web/staff/audit_search.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="audit",
            entry=entry,
            observations=observations,
            doc_hashes=doc_hashes,
            signer_addresses=signer_addresses,
            transaction_ids=tx_ids,
            recomputed_balance=balance,
            outbox_event=outbox_event,
            search_entry_id=entry_id or "",
        ),
    )
