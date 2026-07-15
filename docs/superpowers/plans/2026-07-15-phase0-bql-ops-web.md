# BQL Ops Web Upgrade (`/s/`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the three Phase-0 gaps in the staff `/s/` console — a create-proposal flow, fund-ops screens, and a shared list/detail pattern — plus the six-area staff IA nav (Ledger deferred), all over the domain services that already exist.

**Architecture:** Presentation-only. Every mutation still routes through the existing finance services (`create_proposal`, `submit_proposal_version`, `record_fund_source`, `verify_fund_source`) which already enforce capability, building scope, and maker-checker separation. New staff forms reuse `SignedDecisionForm` + the ClamAV document pipeline. Two staff flows sign a server-computed EIP-712 payload, so they are **two-phase** (prepare → sign): `prepare` uploads evidence and allocates identifiers, then re-renders a signed form carrying the exact typed data; `sign` submits the wallet signature. Fund-verify is single-phase (the entry is immutable).

**Tech Stack:** Django 5.2 server-rendered templates + vanilla JS (`wallet-signing.js`), django-otp MFA, `eth_account` EIP-712 signing, PostgreSQL/psycopg3, pytest + pytest-django. No SPA, no staff API, no new frontend framework.

## Global Constraints

Every task's requirements implicitly include these (copied verbatim from `docs/superpowers/specs/2026-07-14-phase0-phase1-foundation-design.md`):

- **Vietnamese product language; integer VND only; older-adult-friendly UX; WCAG 2.2 AA.** Staff surface is desktop-first, tablet-acceptable (§4.4). (Display copy in these staff templates stays in the existing English idiom of `/s/`; resident-facing Vietnamese copy is unaffected.)
- **§4.4 Explicitly unchanged:** MFA gate, reauth-on-signed-actions, wallet signing (`SignedDecisionForm`), maker-checker separations, publication gates, auditor exports, break-glass audit. **No SPA, no staff API, no new frontend framework.**
- **§2.3 Tenant isolation is a security feature.** Cross-tenant object access → **404** (existence not revealed). Missing capability within the caller's own tenant → **403**. A client-supplied building ID is never trusted; building always derives from the resolved membership. **Every new `<int:pk>` route is classified in the two-building adversarial suite** or `test_every_pk_route_is_classified` fails.
- **§5.3:** Platform never initiates/holds funds — **no payment-provider dependency may enter `pyproject.toml`** (review-time check). No secrets in git.
- **§5.4 Regression gates stay green:** the six e2e journeys, the two-building adversarial walk (web + API), `tenant_integrity`, the OpenAPI drift check, and the disabled-mode publication/fund job.

## Verified test environment

`manage.py` is at the repo root. Postgres via compose; settings read `.env.example` plus test overrides:

```bash
docker compose up -d db
set -a; . ./.env.example; set +a
export SECRET_KEY=test-secret EVIDENCE_WRITE_SECRET=test-evidence \
       POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
# run: .venv/bin/python -m pytest <path> -q
```

## Design decisions

1. **Two-phase signing for create-proposal and fund-record.** An EIP-712 signature covers a server-computed payload (`proposal.pk` + quotation hashes; or `fund_entry_id` + evidence hashes + a pinned timestamp). The wallet cannot sign until the server has produced that payload, so these flows POST twice on one page: `action=prepare` uploads evidence, allocates the record id, and re-renders a `data-signed-form` embedding the exact typed data; `action=submit` posts the signature. This mirrors the seed/driver dance (`testing/factories.py::seed_opening_fund`, `submit_signed_proposal`). **Fund-verify is single-phase** — the entry is immutable, so its verification typed data is deterministic from the stored row.

2. **Server-generated `event_id`.** `prepare` generates a random bytes32 id (`new_event_id`) and pins it through the signed submit — random and non-sequential per spec §2.2 opacity. `wallet-signing.js` keeps the server's id (it only generates one when the field is absent).

3. **Staff upload reuses the resident pipeline.** New `upload_document_pair` calls `create_document_version` + `add_redacted_copy` with `scan_with_clamav` — same ClamAV scan/quarantine gate, same InsertOnly `DocumentVersion` rows, no presigned uploads (§3.6 spirit). Tests patch the scanner symbol where it is imported (`lamto.web.staff_signing.scan_with_clamav`), the established pattern.

4. **No new domain code.** All mutations go through existing services; `verifier ≠ recorder`, capability, and building scope are already enforced and unit-tested there. Plan 4 adds forms, views, templates, one read selector, and nav — nothing else.

5. **`/s/fund/` reachability + IA.** Fund screens mount in a new `web/views/fund.py`; a Fund nav entry (gated on `fund.record`/`fund.verify`) makes them reachable (Task 4). The final task folds Proposals·Payments·Fund into one **Finance** area and presents the **six active staff areas** (Inbox · Cases · Work · Finance · Audit · Ops). Spec §4.2's seventh area (**Ledger**) is **explicitly deferred** — it is not part of the completed Phase-0 IA. Membership switch returns to the Inbox (§4.2 tenancy-UX guard). The building name is **already** in the header chrome (`shell.html`), so no change is needed there.

6. **Deferred: a dedicated staff "Ledger" area.** Spec §4.2 lists a seventh staff area (published entries · corrections · integrity observations). §4.3's Phase-0 build work does **not** include it and no such view exists today — staff reach published entries through Proposals-publish and Audit. Building it is out of scope for Plan 4 (see the out-of-scope list). Navigation copy, tests, and commits must say **six active areas with Ledger deferred**, never claim a completed seven-area IA.

7. **Separate pending-fund-verification selector (not `verified_fund_entries`).** `verified_fund_entries` returns only rows held to the verified/finalized bar used by `fund_balance(verified_only=True)`. Entries awaiting verification are a different set (source entry types with no verification row yet). Task 3 adds `pending_fund_verification_entries(building_id)` and a distinct fund-home section. The verified list must never be the query source for "awaiting verification" rows or verify links.

8. **Prepared-draft / partial-pair hygiene.** `upload_document_pair` must not leave a usable half-pair if the redacted upload fails: wrap both uploads in `transaction.atomic()`, and on any failure after the original succeeds the transaction rolls back so evidence validators cannot treat an unpaired original as a complete quotation/fund pair. Prepared-but-never-signed proposal DRAFTs and orphan staff document pairs older than **24 hours** are cleaned by `cleanup_stale_prepared_ops(older_than_hours=24)` (Task 1 helper; callable from a management command or ops job later). Cleanup removes: (a) unpaired/orphan staff-uploaded documents with no linked proposal document / fund entry evidence; (b) `Proposal` rows still without a `current_version` older than the threshold; (c) does **not** delete signed/submitted domain records.

9. **Approved proposal purpose is immutably derived from the work order.** Domain `submit_proposal_version` already sets `purpose=work_order.case.category` and includes `purpose` in the proposal snapshot from `case.category`. The create-proposal form does **not** collect a free-text purpose field, and the signed payload does **not** add a separate operator-entered purpose — purpose is derived server-side from the case and is immutable once the version freezes. Templates may display the derived purpose as read-only context (`work_order.case.category`).

10. **Pending reconciliation uses publication eligibility, not only `decision == VERIFIED`.** `pending_reconciliation_proposals` must approximate the same gates `prepare_publication` enforces for "ready to publish but not yet published": payment verification `VERIFIED`, payment `external_status == COMPLETED`, proposal has `current_version`, work order is not drill, no `PublishedLedgerEntry` / open publication snapshot yet, and the prerequisite outbox events (proposal version, approvals as required by mode, acceptance, payment, verification) are all in `SETTLED_STATUSES`. Rows that are merely `VERIFIED` but still unsettled or otherwise ineligible for publication must not appear as pending reconciliation.

## File Structure

**Create:**
- `src/lamto/web/staff_signing.py` — `new_event_id()`, `upload_document_pair(...)`. Shared seam for the two-phase signed staff flows.
- `src/lamto/web/views/fund.py` — `fund_home`, `fund_record`, `fund_verify`.
- `src/lamto/web/templates/web/staff/proposal_create.html` — two-phase create-proposal page.
- `src/lamto/web/templates/web/staff/fund_detail.html` — fund home + record + verify.
- `src/lamto/web/templates/web/staff/_list.html` — shared list-page partial (filter chips · status chips · deadline badges).
- `src/lamto/web/tests/test_staff_signing.py`, `test_proposal_create.py`, `test_fund_ops.py`, `test_staff_nav.py`, `test_list_pattern.py`.

**Modify:**
- `src/lamto/web/forms/staff.py` — `+CreateProposalForm`, `+SignProposalForm`, `+RecordFundSourceForm`, `+SignFundSourceForm`.
- `src/lamto/web/views/operator.py` — `+proposal_create`.
- `src/lamto/web/urls.py` — `+4` routes.
- `src/lamto/finance/selectors.py` — `+pending_reconciliation_proposals`, `+pending_fund_verification_entries`.
- `src/lamto/web/staff.py` — `nav_items_for` restructure (Task 7).
- `src/lamto/web/views/staff_common.py` — `switch_membership` → Inbox (Task 7).
- `src/lamto/web/templates/web/staff/shell.html` — nav + switch form (Task 7).
- `src/lamto/web/templates/web/staff/work_order_detail.html` — "Create proposal" affordance (Task 2); `_list.html` (Task 6).
- `src/lamto/web/templates/web/staff/{case,proposal,payment}_detail.html` — `_list.html` (Task 6).
- `src/lamto/web/static/web/app.css` — chip/badge/filter styles (Task 6).
- `tests/isolation/test_cross_building_access.py` — classify `proposal-create` + `fund-verify` (Tasks 2, 5).

---

### Task 1: Staff document-pair upload helper

Turns an uploaded (original, redacted) PDF pair into two linked clean `DocumentVersion` rows through the same ClamAV pipeline residents use. Consumed by create-proposal (Task 2) and fund-record (Task 4).

**Files:**
- Create: `src/lamto/web/staff_signing.py`
- Test: `src/lamto/web/tests/test_staff_signing.py`

**Interfaces:**
- Consumes: `lamto.documents.services.create_document_version`, `add_redacted_copy`; `lamto.documents.scanner.scan_with_clamav`; `lamto.documents.models.{Document,DocumentVersion}`.
- Produces:
  - `new_event_id() -> str` — `"0x" + secrets.token_hex(32)`.
  - `upload_document_pair(building, kind, uploader, original_file, redacted_file) -> tuple[DocumentVersion, DocumentVersion]` — `(original, redacted)` where `redacted.redacts_id == original.pk`, both `ScanStatus.CLEAN`, same `document`. Raises `django.core.exceptions.ValidationError` on any rejection/quarantine/identical-bytes. **Atomic:** both uploads run inside `transaction.atomic()`; if the redacted step fails after the original was created, the transaction rolls back so no unpaired original remains valid evidence.
  - `cleanup_stale_prepared_ops(*, older_than_hours=24) -> dict` — deletes orphan staff document pairs (Document with only upload rows, not linked to a ProposalDocument / fund entry evidence FK) and proposals with no `current_version` older than the threshold; returns counts. Does not touch signed/submitted records.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/web/tests/test_staff_signing.py`:

```python
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from lamto.accounts.models import Building, Organization, OrganizationMembership
from lamto.documents.models import Document, DocumentVersion
from lamto.web.staff_signing import new_event_id, upload_document_pair

_TEMP = tempfile.mkdtemp(prefix="lamto-staffsign-")


def _pdf(name, body):
    return SimpleUploadedFile(name, b"%PDF-1.4\n" + body, content_type="application/pdf")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class UploadDocumentPairTests(TestCase):
    def setUp(self):
        self.building = Building.objects.create(name="Signing Building")
        org = Organization.objects.create(
            building=self.building, name="Ops", kind=Organization.Kind.OPERATOR
        )
        self.user = get_user_model().objects.create_user(
            email="op@example.test", password="secret", display_name="Op"
        )
        OrganizationMembership.objects.create(
            user=self.user, organization=org, role=OrganizationMembership.Role.OPERATOR
        )

    def test_new_event_id_is_random_bytes32(self):
        a, b = new_event_id(), new_event_id()
        assert a.startswith("0x") and len(a) == 66 and a != b

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_uploads_linked_clean_pair(self):
        original, redacted = upload_document_pair(
            self.building,
            Document.Kind.QUOTATION,
            self.user,
            _pdf("q.pdf", b"original bytes"),
            _pdf("q-red.pdf", b"redacted bytes differ"),
        )
        assert original.variant == DocumentVersion.Variant.ORIGINAL
        assert original.redacts_id is None
        assert redacted.variant == DocumentVersion.Variant.REDACTED
        assert redacted.redacts_id == original.pk
        assert original.document_id == redacted.document_id
        assert original.scan_status == DocumentVersion.ScanStatus.CLEAN
        assert redacted.scan_status == DocumentVersion.ScanStatus.CLEAN
        assert original.sha256 != redacted.sha256

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_identical_bytes_rejected_as_validation_error(self):
        with self.assertRaises(ValidationError):
            upload_document_pair(
                self.building,
                Document.Kind.QUOTATION,
                self.user,
                _pdf("q.pdf", b"same"),
                _pdf("q.pdf", b"same"),
            )

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_redacted_failure_leaves_no_partial_pair(self):
        from unittest.mock import patch as _patch
        with _patch(
            "lamto.web.staff_signing.add_redacted_copy",
            side_effect=ValueError("redacted scan failed"),
        ):
            with self.assertRaises(ValidationError):
                upload_document_pair(
                    self.building,
                    Document.Kind.QUOTATION,
                    self.user,
                    _pdf("q.pdf", b"original bytes"),
                    _pdf("q-red.pdf", b"redacted bytes differ"),
                )
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentVersion.objects.count(), 0)

    def test_cleanup_stale_prepared_ops_removes_old_orphans(self):
        from datetime import timedelta
        from django.utils import timezone
        from lamto.web.staff_signing import cleanup_stale_prepared_ops
        with patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True):
            upload_document_pair(
                self.building,
                Document.Kind.QUOTATION,
                self.user,
                _pdf("old.pdf", b"old original"),
                _pdf("old-r.pdf", b"old redacted"),
            )
        DocumentVersion.objects.all().update(
            created_at=timezone.now() - timedelta(hours=48)
        )
        result = cleanup_stale_prepared_ops(older_than_hours=24)
        self.assertGreaterEqual(result.get("documents_deleted", 0), 1)
        self.assertEqual(Document.objects.count(), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_staff_signing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lamto.web.staff_signing'`.

- [ ] **Step 3: Write the helper**

Create `src/lamto/web/staff_signing.py`:

```python
"""Shared helpers for staff two-phase wallet-signed forms (spec 4.3).

Both create-proposal and fund-record sign a server-computed EIP-712 payload,
so they upload evidence + allocate a record id first, then sign. This module
holds the pieces both flows share; all domain mutations stay in finance.*.
"""

import secrets

from django.core.exceptions import ValidationError

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
    from django.db import transaction

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


def cleanup_stale_prepared_ops(*, older_than_hours=24):
    """Expire prepared-but-never-signed staff drafts and orphan document pairs.

    Removes:
    - Document rows whose versions are all older than the threshold and that
      are not referenced by ProposalDocument or as fund entry evidence.
    - Proposal rows still without a current_version older than threshold.

    Does not delete signed/submitted proposal versions, verified fund entries,
    or any outbox-linked evidence. Returns a dict of deletion counts.
    """
    from datetime import timedelta

    from django.utils import timezone

    from lamto.finance.models import MaintenanceFundEntry, Proposal, ProposalDocument

    cutoff = timezone.now() - timedelta(hours=older_than_hours)
    documents_deleted = 0

    linked_doc_ids = set(
        ProposalDocument.objects.values_list("document_version__document_id", flat=True)
    )
    fund_doc_ids = set(
        MaintenanceFundEntry.objects.exclude(evidence_original_id=None).values_list(
            "evidence_original__document_id", flat=True
        )
    ) | set(
        MaintenanceFundEntry.objects.exclude(evidence_redacted_id=None).values_list(
            "evidence_redacted__document_id", flat=True
        )
    )
    protected = linked_doc_ids | fund_doc_ids

    stale_docs = (
        Document.objects.exclude(pk__in=protected)
        .filter(versions__created_at__lt=cutoff)
        .distinct()
    )
    for doc in stale_docs:
        if not doc.versions.filter(created_at__gte=cutoff).exists():
            doc.delete()
            documents_deleted += 1

    proposals_deleted, _ = Proposal.objects.filter(
        current_version__isnull=True,
        created_at__lt=cutoff,
    ).delete()

    return {
        "documents_deleted": documents_deleted,
        "proposals_deleted": proposals_deleted,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_staff_signing.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/lamto/web/staff_signing.py src/lamto/web/tests/test_staff_signing.py
git commit -m "feat: staff document-pair upload helper for signed ops forms"
```

---

### Task 2: Create-proposal flow

Operator, from a spending-required work-order detail page: enter amount (integer VND) + contractor + upload a quotation pair → `prepare` freezes the draft and shows the signed form → operator signs → `submit_proposal_version` freezes the immutable version and routes it to the Board inbox. Reuses `SignedDecisionForm` and the document pipeline (§4.3.1).

**Purpose field (immutable derivation):** Do **not** add a purpose input to `CreateProposalForm` / `SignProposalForm`. Domain code already sets `purpose=work_order.case.category` on the frozen version and embeds `purpose: case.category` in the proposal snapshot / evidence payload. The operator cannot override it. The create page may show a read-only line: purpose = `{{ work_order.case.category }}`.

**Files:**
- Modify: `src/lamto/web/forms/staff.py`
- Modify: `src/lamto/web/views/operator.py`
- Modify: `src/lamto/web/urls.py`
- Create: `src/lamto/web/templates/web/staff/proposal_create.html`
- Modify: `src/lamto/web/templates/web/staff/work_order_detail.html`
- Modify: `tests/isolation/test_cross_building_access.py`
- Test: `src/lamto/web/tests/test_proposal_create.py`

**Interfaces:**
- Consumes: `upload_document_pair`, `new_event_id` (Task 1); `lamto.finance.proposals.{ZERO_HASH, build_proposal_evidence_payload, create_proposal, submit_proposal_version}`; `lamto.evidence.canonical.payload_hash`; `lamto.evidence.models.EvidenceType`; `lamto.evidence.signatures.build_evidence_typed_data`.
- Produces:
  - `CreateProposalForm` — fields `amount_vnd` (int ≥1), `contractor_name`, `quotation_original` (FileField), `quotation_redacted` (FileField).
  - `SignProposalForm(SignedDecisionForm)` — adds hidden `amount_vnd`, `contractor_name`, `quotation_original_id`, `proposal_id`.
  - `operator.proposal_create(request, pk)` at `web:proposal-create` = `s/work/<int:pk>/propose/` (`pk` is the work-order pk).

- [ ] **Step 1: Add the forms**

In `src/lamto/web/forms/staff.py`, append:

```python
class CreateProposalForm(forms.Form):
    """Operator-entered proposal draft; the quotation pair uploads on prepare."""

    amount_vnd = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={"class": "input"}))
    contractor_name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"class": "input"}))
    quotation_original = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "input"}))
    quotation_redacted = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "input"}))


class SignProposalForm(SignedDecisionForm):
    """Signed submit of the frozen proposal version. Hidden fields carry the
    prepared draft so the posted signature matches the exact payload."""

    amount_vnd = forms.IntegerField(min_value=1, widget=forms.HiddenInput())
    contractor_name = forms.CharField(max_length=255, widget=forms.HiddenInput())
    quotation_original_id = forms.IntegerField(widget=forms.HiddenInput())
    proposal_id = forms.IntegerField(widget=forms.HiddenInput())
```

- [ ] **Step 2: Add the view**

In `src/lamto/web/views/operator.py`, add imports at the top of the existing import block:

```python
import json

from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.proposals import (
    ZERO_HASH,
    build_proposal_evidence_payload,
    create_proposal,
    submit_proposal_version,
)
from lamto.web.forms.staff import CreateProposalForm, SignProposalForm
from lamto.web.staff_signing import new_event_id, upload_document_pair
```

Add `PROPOSAL_CREATE` is already imported; also ensure `require_recent_auth` is imported (it is). Append the view:

```python
@login_required
@require_http_methods(["GET", "POST"])
def proposal_create(request, pk):
    """Two-phase create-proposal from a spending work order (spec 4.3.1).

    action=prepare: upload quotation pair + create the DRAFT proposal, then
    render the signed form with the exact typed data. action=submit: freeze
    the immutable version via the domain service.
    """
    membership, memberships = require_staff_capability(request, PROPOSAL_CREATE)
    building_id = membership.organization.building_id
    work_order = get_object_or_404(
        WorkOrder.objects.select_related("case"),
        pk=pk,
        case__building_id=building_id,
    )
    if request.method == "POST":
        require_recent_auth(request)
    if not work_order.requires_spending:
        messages.error(request, "This work order does not require spending.")
        return redirect("web:work-order-detail", pk=work_order.pk)

    existing = (
        Proposal.objects.filter(work_order=work_order)
        .select_related("current_version")
        .first()
    )
    if existing is not None and existing.current_version_id is not None:
        messages.info(request, "A proposal has already been submitted for this work order.")
        return redirect("web:proposal-detail", pk=existing.pk)

    create_form = CreateProposalForm(request.POST or None, request.FILES or None)
    sign_form = None
    typed_data = None
    action = request.POST.get("action") if request.method == "POST" else None

    if action == "prepare" and create_form.is_valid():
        try:
            original, _redacted = upload_document_pair(
                work_order.case.building,
                Document.Kind.QUOTATION,
                request.user,
                create_form.cleaned_data["quotation_original"],
                create_form.cleaned_data["quotation_redacted"],
            )
            proposal = existing or create_proposal(work_order, membership)
            amount = create_form.cleaned_data["amount_vnd"]
            contractor = create_form.cleaned_data["contractor_name"]
            payload = build_proposal_evidence_payload(proposal, amount, contractor, [original])
        except (ValidationError, PermissionDenied) as error:
            if isinstance(error, ValidationError):
                create_form.add_error(None, error)
            else:
                raise
        else:
            event_id = new_event_id()
            typed_data = json.dumps(
                build_evidence_typed_data(
                    event_id, EvidenceType.PROPOSAL_CREATED, "0x" + payload_hash(payload), ZERO_HASH
                )
            )
            sign_form = SignProposalForm(
                initial={
                    "event_id": event_id,
                    "amount_vnd": amount,
                    "contractor_name": contractor,
                    "quotation_original_id": original.pk,
                    "proposal_id": proposal.pk,
                }
            )
    elif action == "submit":
        sign_form = SignProposalForm(request.POST)
        if sign_form.is_valid():
            proposal = get_object_or_404(
                Proposal,
                pk=sign_form.cleaned_data["proposal_id"],
                work_order__case__building_id=building_id,
            )
            original = get_object_or_404(
                DocumentVersion,
                pk=sign_form.cleaned_data["quotation_original_id"],
                document__building_id=building_id,
            )
            try:
                submit_proposal_version(
                    proposal,
                    sign_form.cleaned_data["amount_vnd"],
                    sign_form.cleaned_data["contractor_name"],
                    [original],
                    sign_form.cleaned_data["signature"],
                    sign_form.cleaned_data["event_id"],
                )
            except (ValidationError, PermissionDenied) as error:
                if isinstance(error, ValidationError):
                    sign_form.add_error(None, error)
                else:
                    raise
            else:
                messages.success(request, "Proposal submitted for Board review.")
                return redirect("web:proposal-detail", pk=proposal.pk)

    return render(
        request,
        "web/staff/proposal_create.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="proposals",
            work_order=work_order,
            create_form=create_form,
            sign_form=sign_form,
            typed_data=typed_data,
        ),
    )
```

- [ ] **Step 3: Add the URL**

In `src/lamto/web/urls.py`, add under the "Maintenance / work" group (after the `work-order-detail` line):

```python
    path("s/work/<int:pk>/propose/", operator.proposal_create, name="proposal-create"),
```

- [ ] **Step 4: Add the template**

Create `src/lamto/web/templates/web/staff/proposal_create.html`:

```html
{% extends "web/staff/shell.html" %}
{% block title %}Create proposal · LamTo{% endblock %}
{% block content %}
<section class="panel">
  <h1>Create proposal · Work order #{{ work_order.pk }}</h1>
  <p class="hint">Purpose (from case, immutable): {{ work_order.case.category }}</p>

  {% if sign_form %}
  <div class="signed-box">
    <h2>Review and sign</h2>
    <p class="hint">Amount {{ sign_form.amount_vnd.value }} VND · {{ sign_form.contractor_name.value }}</p>
    <p class="hint">The quotation is uploaded and frozen. Sign with your wallet to submit for Board review.</p>
    <form method="post" class="stack-form" data-signed-form>
      {% csrf_token %}
      <input type="hidden" name="action" value="submit">
      {{ sign_form.as_p }}
      <script type="application/json" data-typed-data>{{ typed_data|safe }}</script>
      <p class="hint" data-signing-status>Wallet will sign via eth_signTypedData_v4 when typed data is provided.</p>
      <button type="submit" class="button">Submit proposal</button>
    </form>
  </div>
  {% else %}
  <form method="post" class="stack-form" enctype="multipart/form-data">
    {% csrf_token %}
    <input type="hidden" name="action" value="prepare">
    {{ create_form.as_p }}
    <p class="hint">Upload the quotation original and a redacted copy (PDF). Amounts are integer VND.</p>
    <button type="submit" class="button">Prepare proposal</button>
  </form>
  {% endif %}
</section>
{% endblock %}
```

`typed_data` is server-built from ids/hashes/amounts only (no free text), so `|safe` carries no injection risk.

- [ ] **Step 5: Add the "Create proposal" affordance on work-order detail**

In `src/lamto/web/templates/web/staff/work_order_detail.html`, inside the `{% else %}` (detail) branch, after the closing `</dl>` (line ~32) and before the `is_assignee` start block, add:

```html
  {% if "proposal.create" in capabilities and work_order.requires_spending %}
  <p><a class="button button-secondary" href="{% url 'web:proposal-create' work_order.pk %}">Create proposal</a></p>
  {% endif %}
```

`capabilities` is already in `staff_context`.

- [ ] **Step 6: Write the failing tests**

Create `src/lamto/web/tests/test_proposal_create.py`:

```python
import tempfile
import time
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import EvidenceType
from lamto.evidence.signatures import build_evidence_typed_data
from lamto.finance.models import Proposal, ProposalVersion
from lamto.finance.proposals import ZERO_HASH, build_proposal_evidence_payload
from lamto.documents.models import Document, DocumentVersion
from lamto.maintenance.models import WorkOrder
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-propcreate-")


def _pdf(name, body):
    return SimpleUploadedFile(name, b"%PDF-1.4\n" + body, content_type="application/pdf")


@override_settings(
    ROOT_URLCONF="lamto.config.urls",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class ProposalCreateTests(TestCase):
    def setUp(self):
        self.seed = seed_pilot_world(building_name="Prop Create B", email_prefix="pc")
        driver = PilotDomainDriver(self.seed)
        driver.login(None, "resident").submit_report("Lift jerks", "Lift 2")
        driver.login(None, "operator").confirm_triage_and_create_paid_work_order()
        self.work = self.seed.work_order
        self.operator = self.seed.roles["operator"]
        self.account = self.seed.accounts[self.operator.pk]

    def _login_operator(self):
        self.client.force_login(self.operator.user)
        device = TOTPDevice.objects.create(
            user=self.operator.user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session["active_membership_id"] = self.operator.pk
        session.save()

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_prepare_then_sign_submits_version(self):
        self._login_operator()
        url = reverse("web:proposal-create", kwargs={"pk": self.work.pk})

        prepare = self.client.post(
            url,
            {
                "action": "prepare",
                "amount_vnd": 5_000_000,
                "contractor_name": "Acme Co",
                "quotation_original": _pdf("q.pdf", b"orig"),
                "quotation_redacted": _pdf("qr.pdf", b"redacted differs"),
            },
        )
        self.assertEqual(prepare.status_code, 200)
        self.assertContains(prepare, "data-signed-form")
        proposal = Proposal.objects.get(work_order=self.work)
        self.assertIsNone(proposal.current_version_id)
        original = DocumentVersion.objects.get(
            document__building=self.seed.building,
            document__kind=Document.Kind.QUOTATION,
            variant=DocumentVersion.Variant.ORIGINAL,
        )

        payload = build_proposal_evidence_payload(proposal, 5_000_000, "Acme Co", [original])
        event_id = "0x" + "11" * 32
        typed = build_evidence_typed_data(
            event_id, EvidenceType.PROPOSAL_CREATED, "0x" + payload_hash(payload), ZERO_HASH
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), self.account.key
        ).signature.hex()

        submit = self.client.post(
            url,
            {
                "action": "submit",
                "amount_vnd": 5_000_000,
                "contractor_name": "Acme Co",
                "quotation_original_id": original.pk,
                "proposal_id": proposal.pk,
                "event_id": event_id,
                "signature": signature,
            },
        )
        self.assertRedirects(submit, reverse("web:proposal-detail", kwargs={"pk": proposal.pk}))
        version = ProposalVersion.objects.get(proposal=proposal)
        self.assertEqual(version.amount_vnd, 5_000_000)
        self.work.refresh_from_db()
        self.assertEqual(self.work.authorization_status, WorkOrder.AuthorizationStatus.PENDING)

    def test_non_operator_forbidden(self):
        self.client.force_login(self.seed.roles["maintenance"].user)
        device = TOTPDevice.objects.create(
            user=self.seed.roles["maintenance"].user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()
        resp = self.client.get(reverse("web:proposal-create", kwargs={"pk": self.work.pk}))
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 7: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_proposal_create.py -q`
Expected: FAIL — `NoReverseMatch` for `web:proposal-create` until the URL is wired, then form/view assertions.

- [ ] **Step 8: Run the tests to verify they pass**

After Steps 1–5 are in place, run: `.venv/bin/python -m pytest src/lamto/web/tests/test_proposal_create.py -q`
Expected: PASS (2 passed).

- [ ] **Step 9: Classify the new pk route in the adversarial suite**

In `tests/isolation/test_cross_building_access.py`, add to `STAFF_CASES` (the work order already carries a submitted proposal, so a Building-A operator hitting Building-B's work pk must 404):

```python
    "web:proposal-create": ("work_pk", "operator", "POST"),
```

- [ ] **Step 10: Run the isolation suite**

Run: `.venv/bin/python -m pytest tests/isolation/test_cross_building_access.py -q`
Expected: PASS — `test_every_pk_route_is_classified` and `test_staff_cannot_reach_other_building_objects` both green (proposal-create returns 404 cross-tenant).

- [ ] **Step 11: Commit**

```bash
git add src/lamto/web/forms/staff.py src/lamto/web/views/operator.py src/lamto/web/urls.py \
        src/lamto/web/templates/web/staff/proposal_create.html \
        src/lamto/web/templates/web/staff/work_order_detail.html \
        src/lamto/web/tests/test_proposal_create.py tests/isolation/test_cross_building_access.py
git commit -m "feat: operator create-proposal flow from work-order detail"
```

---

### Task 3: Fund home — entries list, derived balance, pending verification, pending-reconciliation

Read-only `/s/fund/` for fund-recorder/verifier: verified entries + **separate pending-fund-verification list** + derived balance + period flows + a staff-only reconciliation block for proposals that pass the same publication-eligibility gates as the domain publish path but are not yet published (§4.3.2). No mutations yet.

**Files:**
- Modify: `src/lamto/finance/selectors.py`
- Create: `src/lamto/web/views/fund.py`
- Modify: `src/lamto/web/urls.py`
- Create: `src/lamto/web/templates/web/staff/fund_detail.html`
- Test: `src/lamto/web/tests/test_fund_ops.py`

**Interfaces:**
- Consumes: `lamto.finance.selectors.{verified_fund_entries, fund_period_flows}`; `lamto.finance.fund.fund_balance`; `lamto.finance.models.{MaintenanceFund, MaintenanceFundEntry, Proposal, PaymentVerification, PaymentEvidence, PublishedLedgerEntry, PublicationSnapshot}`; `lamto.evidence.models.SETTLED_STATUSES`.
- Produces:
  - `selectors.pending_fund_verification_entries(building_id)` — source-type fund entries (`OPENING_BALANCE`/`INFLOW`) in the building with **no** `verification` row yet, newest first. **Must not** reuse `verified_fund_entries` (that selector is verified/finalized only).
  - `selectors.pending_reconciliation_proposals(building_id)` — proposals eligible for publication under the same settled-gate rules as `prepare_publication` but not yet published (see Step 3 implementation). **Not** "any payment with `decision == VERIFIED`."
  - `fund.fund_home(request)` at `web:fund-home` = `s/fund/`.

- [ ] **Step 1: Write the failing selector test**

Create `src/lamto/web/tests/test_fund_ops.py` with the selector test first (the view/record/verify tests come in Tasks 4–5):

```python
import tempfile
import time
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex
from eth_account import Account
from eth_account.messages import encode_typed_data

from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.finance.models import MaintenanceFundEntry
from lamto.finance.selectors import pending_reconciliation_proposals
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

_TEMP = tempfile.mkdtemp(prefix="lamto-fundops-")


def _pdf(name, body):
    return SimpleUploadedFile(name, b"%PDF-1.4\n" + body, content_type="application/pdf")


def _full_publish(seed):
    """Run the pilot expenditure through verified payment (not yet published)."""
    d = PilotDomainDriver(seed)
    d.login(None, "resident").submit_report("Lift noise", "Lift 2")
    d.login(None, "operator").confirm_triage_and_create_paid_work_order()
    d.login(None, "operator").submit_signed_proposal()
    d.login(None, "board_approver").approve_proposal()
    d.login(None, "resident_representative").coapprove_proposal()
    d.login(None, "maintenance").complete_assigned_work()
    d.login(None, "board_payment_recorder").accept_and_record_payment()
    d.login(None, "board_payment_verifier").verify_payment()
    d.confirm_all_chain_events()
    return d


@override_settings(
    ROOT_URLCONF="lamto.config.urls",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": _TEMP}},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class FundSelectorTests(TestCase):
    def test_pending_reconciliation_lists_paid_but_unpublished(self):
        seed = seed_pilot_world(building_name="Fund Sel B", email_prefix="fs")
        _full_publish(seed)  # verified payment, settled chain, no publication yet
        pending = list(pending_reconciliation_proposals(seed.building.pk))
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0], seed.proposal)

    def test_pending_reconciliation_excludes_unsettled_verification(self):
        """Eligibility matches domain gates: settled prerequisites required, not only VERIFIED."""
        from lamto.evidence.models import OutboxEvent
        seed = seed_pilot_world(building_name="Fund Sel Unsettled", email_prefix="fsu")
        _full_publish(seed)
        v_event = seed.proposal.work_order.acceptance.payment.verification.outbox_event
        OutboxEvent.objects.filter(pk=v_event.pk).update(status=OutboxEvent.Status.QUEUED)
        pending = list(pending_reconciliation_proposals(seed.building.pk))
        self.assertEqual(pending, [])

    def test_pending_fund_verification_is_not_verified_fund_entries(self):
        from lamto.finance.selectors import (
            pending_fund_verification_entries,
            verified_fund_entries,
        )
        seed = seed_pilot_world(building_name="Fund Sel Pend", email_prefix="fsp")
        verified_ids = {e.pk for e in verified_fund_entries(seed.building.pk)}
        pending_ids = {e.pk for e in pending_fund_verification_entries(seed.building.pk)}
        self.assertTrue(verified_ids.isdisjoint(pending_ids))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_fund_ops.py::FundSelectorTests -q`
Expected: FAIL — `ImportError: cannot import name 'pending_reconciliation_proposals'`.

- [ ] **Step 3: Add the selector**

In `src/lamto/finance/selectors.py`, append both selectors (import models inside functions where that keeps the top-level import surface small, or expand the module imports as needed):

```python
def pending_fund_verification_entries(building_id):
    """Source fund entries still awaiting verification (spec 4.3.2).

    Distinct from verified_fund_entries — never reuse that selector here.
    Source types only; rows with a verification relation are excluded.
    """
    from lamto.finance.fund import SOURCE_ENTRY_TYPES

    return (
        MaintenanceFundEntry.objects.filter(
            fund__building_id=building_id,
            entry_type__in=SOURCE_ENTRY_TYPES,
            verification__isnull=True,
        )
        .select_related("recorder", "outbox_event")
        .order_by("-recorded_at", "-pk")
    )


def pending_reconciliation_proposals(building_id):
    """Staff reconciliation aid: publication-eligible but not yet published.

    Mirrors settled verification/publication eligibility used by
    prepare_publication — not merely payment.decision == VERIFIED:
    - payment verification decision VERIFIED
    - payment external_status COMPLETED
    - proposal has current_version; work order not drill
    - no PublishedLedgerEntry and no PublicationSnapshot yet
    - prerequisite outbox events settled (proposal version, board+rep
      approvals for NORMAL mode, acceptance, payment, verification)
    """
    from lamto.accounts.models import Organization
    from lamto.evidence.models import SETTLED_STATUSES
    from lamto.finance.models import (
        ApprovalDecision,
        PaymentEvidence,
        PaymentVerification,
        Proposal,
        PublicationSnapshot,
        PublishedLedgerEntry,
    )

    published_proposal_ids = PublishedLedgerEntry.objects.filter(
        case__building_id=building_id, proposal__isnull=False
    ).values("proposal_id")
    snapshotted_ids = PublicationSnapshot.objects.filter(
        proposal__work_order__case__building_id=building_id
    ).values("proposal_id")

    qs = (
        Proposal.objects.filter(
            work_order__case__building_id=building_id,
            work_order__drill=False,
            current_version__isnull=False,
            work_order__acceptance__payment__verification__decision=PaymentVerification.Decision.VERIFIED,
            work_order__acceptance__payment__external_status=PaymentEvidence.ExternalStatus.COMPLETED,
            current_version__outbox_event__status__in=SETTLED_STATUSES,
            work_order__acceptance__outbox_event__status__in=SETTLED_STATUSES,
            work_order__acceptance__payment__outbox_event__status__in=SETTLED_STATUSES,
            work_order__acceptance__payment__verification__outbox_event__status__in=SETTLED_STATUSES,
        )
        .exclude(pk__in=published_proposal_ids)
        .exclude(pk__in=snapshotted_ids)
        .select_related("current_version", "work_order")
        .prefetch_related("current_version__approvals__outbox_event", "current_version__approvals__membership__organization")
        .order_by("-created_at")
    )
    eligible = []
    for proposal in qs:
        if proposal.mode == Proposal.Mode.NORMAL:
            approvals = list(proposal.current_version.approvals.all())
            board = next(
                (
                    a
                    for a in approvals
                    if a.decision == ApprovalDecision.Decision.APPROVED
                    and a.membership.organization.kind == Organization.Kind.BOARD
                    and a.outbox_event_id
                    and a.outbox_event.status in SETTLED_STATUSES
                ),
                None,
            )
            rep = next(
                (
                    a
                    for a in approvals
                    if a.decision == ApprovalDecision.Decision.APPROVED
                    and a.membership.organization.kind
                    == Organization.Kind.RESIDENT_REPRESENTATIVE
                    and a.outbox_event_id
                    and a.outbox_event.status in SETTLED_STATUSES
                ),
                None,
            )
            if board is None or rep is None:
                continue
        eligible.append(proposal)
    return eligible
```

- [ ] **Step 4: Run to verify the selector passes**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_fund_ops.py::FundSelectorTests -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Add the fund home view**

Create `src/lamto/web/views/fund.py`:

```python
"""Fund ops workspace: entries list, balance, source recording + verification."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.http import require_GET

from lamto.accounts.capabilities import FUND_RECORD, FUND_VERIFY
from lamto.finance.fund import fund_balance
from lamto.finance.models import MaintenanceFund
from lamto.finance.selectors import (
    fund_period_flows,
    pending_fund_verification_entries,
    pending_reconciliation_proposals,
    verified_fund_entries,
)
from lamto.web.staff import capabilities_for, resolve_active_membership, staff_context


def _require_fund_access(request):
    from lamto.accounts.security import require_staff_mfa

    require_staff_mfa(request)
    membership, memberships = resolve_active_membership(request)
    caps = capabilities_for(membership)
    if FUND_RECORD not in caps and FUND_VERIFY not in caps:
        raise PermissionDenied("fund access")
    return membership, memberships, caps


@login_required
@require_GET
def fund_home(request):
    membership, memberships, caps = _require_fund_access(request)
    building_id = membership.organization.building_id
    entries = (
        verified_fund_entries(building_id)
        .select_related("recorder", "verification")
        .order_by("-recorded_at", "-pk")[:100]
    )
    pending_verification = list(pending_fund_verification_entries(building_id)[:50])
    inflows, outflows = fund_period_flows(building_id, days=30)
    pending = pending_reconciliation_proposals(building_id)[:50]
    return render(
        request,
        "web/staff/fund_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="fund",
            list_mode=True,
            entries=entries,
            pending_verification=pending_verification,
            balance_vnd=fund_balance(building_id, verified_only=True),
            period_inflows=inflows,
            period_outflows=outflows,
            pending=pending,
            fund_exists=MaintenanceFund.objects.filter(building_id=building_id).exists(),
            can_record=FUND_RECORD in caps,
            can_verify=FUND_VERIFY in caps,
        ),
    )
```

- [ ] **Step 6: Add the URL and Fund nav entry**

In `src/lamto/web/urls.py`, add the import `fund` and a route group:

```python
from lamto.web.views import auditor, board, fund, maintenance, operator, representative, resident
```

```python
    # Fund ops
    path("s/fund/", fund.fund_home, name="fund-home"),
```

In `src/lamto/web/staff.py`, inside `nav_items_for`, immediately before `return items`, add an interim Fund entry (Task 7 folds it into Finance):

```python
    fund_caps = {"fund.record", "fund.verify"}
    if caps & fund_caps and "web:fund-home" not in seen_urls:
        items.append({"label": "Fund", "url_name": "web:fund-home", "capability": "fund.record"})
```

- [ ] **Step 7: Add the fund template (list mode)**

Create `src/lamto/web/templates/web/staff/fund_detail.html`:

```html
{% extends "web/staff/shell.html" %}
{% block title %}Fund · LamTo{% endblock %}
{% block content %}
{% if list_mode %}
<section class="panel">
  <div class="panel-header">
    <h1>Maintenance fund</h1>
    {% if can_record %}
    <a class="button button-secondary" href="{% url 'web:fund-record' %}">Record source</a>
    {% endif %}
  </div>
  <dl class="detail-list">
    <div><dt>Verified balance</dt><dd>{{ balance_vnd }} VND</dd></div>
    <div><dt>Inflows (30d)</dt><dd>{{ period_inflows }} VND</dd></div>
    <div><dt>Outflows (30d)</dt><dd>{{ period_outflows }} VND</dd></div>
  </dl>
</section>

<section class="panel">
  <h2>Verified entries</h2>
  <ul class="card-list">
    {% for entry in entries %}
    <li>
      <p class="card-title">#{{ entry.pk }} · {{ entry.get_entry_type_display }} · {{ entry.amount_vnd }} VND</p>
      <p class="card-meta">Recorded {{ entry.recorded_at }}</p>
    </li>
    {% empty %}
    <li><p>No verified entries.</p></li>
    {% endfor %}
  </ul>
</section>

<section class="panel">
  <h2>Pending fund verification</h2>
  <p class="hint">Source entries recorded but not yet verified. Separate from verified entries.</p>
  <ul class="card-list">
    {% for entry in pending_verification %}
    <li>
      <p class="card-title">#{{ entry.pk }} · {{ entry.get_entry_type_display }} · {{ entry.amount_vnd }} VND</p>
      <p class="card-meta">
        Recorded {{ entry.recorded_at }}
        {% if can_verify %}
        · <a href="{% url 'web:fund-verify' entry.pk %}">Verify</a>
        {% endif %}
      </p>
    </li>
    {% empty %}
    <li><p>No entries awaiting verification.</p></li>
    {% endfor %}
  </ul>
</section>

<section class="panel">
  <h2>Pending reconciliation</h2>
  <p class="hint">Publication-eligible (settled verified payment chain) but not yet published to the resident ledger.</p>
  <ul class="card-list">
    {% for proposal in pending %}
    <li>
      <a class="card-link" href="{% url 'web:proposal-detail' proposal.pk %}">
        <p class="card-title">Proposal #{{ proposal.pk }}
          {% if proposal.current_version %}· {{ proposal.current_version.amount_vnd }} VND{% endif %}</p>
      </a>
    </li>
    {% empty %}
    <li><p>Nothing awaiting publication.</p></li>
    {% endfor %}
  </ul>
</section>
{% else %}
{% include "web/staff/_fund_forms.html" %}
{% endif %}
{% endblock %}
```

The `{% else %}` branch includes `_fund_forms.html`, created in Task 4. To keep this task's template renderable on its own, add a placeholder `_fund_forms.html` now:

```bash
printf '{# fund record/verify forms — filled in Task 4/5 #}\n' > src/lamto/web/templates/web/staff/_fund_forms.html
```

- [ ] **Step 8: Write the fund-home view test**

Append to `src/lamto/web/tests/test_fund_ops.py`:

```python
class FundHomeTests(TestCase):
    def _login(self, seed, role_key):
        membership = seed.roles[role_key]
        self.client.force_login(membership.user)
        device = TOTPDevice.objects.create(
            user=membership.user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session["active_membership_id"] = membership.pk
        session.save()
        return membership

    def test_fund_home_shows_balance_entries_and_pending(self):
        seed = seed_pilot_world(building_name="Fund Home B", email_prefix="fh")
        _full_publish(seed)
        self._login(seed, "fund_recorder")
        resp = self.client.get(reverse("web:fund-home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Maintenance fund")
        self.assertContains(resp, "Verified entries")
        self.assertContains(resp, "Pending fund verification")
        self.assertContains(resp, "Pending reconciliation")
        # The seeded opening balance is a verified entry.
        self.assertContains(resp, "Opening balance")

    def test_without_fund_capability_is_forbidden(self):
        seed = seed_pilot_world(building_name="Fund Home Deny", email_prefix="fhd")
        self._login(seed, "maintenance")
        self.assertEqual(self.client.get(reverse("web:fund-home")).status_code, 403)
```

`FundHomeTests` reuses the `@override_settings`/helpers already at module scope (move `_login` onto each class or share via a mixin — inline here for clarity).

- [ ] **Step 9: Run the fund tests**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_fund_ops.py -q`
Expected: PASS (5 passed: 3 selector + 2 home).

- [ ] **Step 10: Commit**

```bash
git add src/lamto/finance/selectors.py src/lamto/web/views/fund.py src/lamto/web/urls.py \
        src/lamto/web/staff.py src/lamto/web/templates/web/staff/fund_detail.html \
        src/lamto/web/templates/web/staff/_fund_forms.html src/lamto/web/tests/test_fund_ops.py
git commit -m "feat: fund ops home — balance, verified entries, pending reconciliation"
```

---

### Task 4: Fund record source (opening balance / inflow) with evidence upload

Two-phase, fund-recorder capability (§4.3.2): enter type + amount + upload evidence pair → `prepare` allocates the entry id, pins the timestamp, and shows the signed form → recorder signs → `record_fund_source` writes the (still unverified) entry.

**Files:**
- Modify: `src/lamto/web/forms/staff.py`
- Modify: `src/lamto/web/views/fund.py`
- Modify: `src/lamto/web/urls.py`
- Modify: `src/lamto/web/templates/web/staff/_fund_forms.html`
- Test: `src/lamto/web/tests/test_fund_ops.py`

**Interfaces:**
- Consumes: `upload_document_pair`, `new_event_id` (Task 1); `lamto.finance.fund.{get_or_create_fund, allocate_fund_entry_id, build_fund_source_evidence_typed_data, record_fund_source}`; `lamto.finance.models.MaintenanceFundEntry`; `lamto.evidence.services.utc_rfc3339`.
- Produces:
  - `RecordFundSourceForm` — `entry_type` (choice OPENING_BALANCE/INFLOW), `amount_vnd` (int ≥1), `evidence_original`/`evidence_redacted` (FileFields).
  - `SignFundSourceForm(SignedDecisionForm)` — hidden `entry_type`, `amount_vnd`, `evidence_original_id`, `evidence_redacted_id`, `fund_entry_id`, `entry_timestamp`.
  - `fund.fund_record(request)` at `web:fund-record` = `s/fund/record/`.

- [ ] **Step 1: Add the forms**

In `src/lamto/web/forms/staff.py`, append (import `MaintenanceFundEntry` at the top of the file's import block if not present: `from lamto.finance.models import ApprovalDecision, MaintenanceFundEntry, PaymentVerification`):

```python
class RecordFundSourceForm(forms.Form):
    """Fund source draft; the evidence pair uploads on prepare."""

    entry_type = forms.ChoiceField(
        choices=[
            (MaintenanceFundEntry.EntryType.OPENING_BALANCE, "Opening balance"),
            (MaintenanceFundEntry.EntryType.INFLOW, "Inflow"),
        ],
        widget=forms.Select(attrs={"class": "input"}),
    )
    amount_vnd = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={"class": "input"}))
    evidence_original = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "input"}))
    evidence_redacted = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "input"}))


class SignFundSourceForm(SignedDecisionForm):
    """Signed submit of a prepared fund source. Hidden fields pin the exact
    signed payload (id, amount, evidence hashes, timestamp)."""

    entry_type = forms.CharField(max_length=32, widget=forms.HiddenInput())
    amount_vnd = forms.IntegerField(min_value=1, widget=forms.HiddenInput())
    evidence_original_id = forms.IntegerField(widget=forms.HiddenInput())
    evidence_redacted_id = forms.IntegerField(widget=forms.HiddenInput())
    fund_entry_id = forms.IntegerField(widget=forms.HiddenInput())
    entry_timestamp = forms.CharField(max_length=40, widget=forms.HiddenInput())
```

- [ ] **Step 2: Add the fund_record view**

In `src/lamto/web/views/fund.py`, extend imports:

```python
import json
from datetime import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods

from lamto.accounts.security import require_recent_auth
from lamto.documents.models import Document, DocumentVersion
from lamto.evidence.services import utc_rfc3339
from lamto.finance.fund import (
    allocate_fund_entry_id,
    build_fund_source_evidence_typed_data,
    get_or_create_fund,
    record_fund_source,
)
from lamto.finance.models import MaintenanceFundEntry
from lamto.web.forms.staff import RecordFundSourceForm, SignFundSourceForm
from lamto.web.staff import require_staff_capability
from lamto.web.staff_signing import new_event_id, upload_document_pair
```

Append the view:

```python
@login_required
@require_http_methods(["GET", "POST"])
def fund_record(request):
    """Two-phase record of an opening-balance/inflow fund source (spec 4.3.2)."""
    membership, memberships = require_staff_capability(request, FUND_RECORD)
    building = membership.organization.building
    if request.method == "POST":
        require_recent_auth(request)
    fund = get_or_create_fund(building)

    record_form = RecordFundSourceForm(request.POST or None, request.FILES or None)
    sign_form = None
    typed_data = None
    action = request.POST.get("action") if request.method == "POST" else None

    if action == "prepare" and record_form.is_valid():
        try:
            original, redacted = upload_document_pair(
                building,
                Document.Kind.CONTRACT,
                request.user,
                record_form.cleaned_data["evidence_original"],
                record_form.cleaned_data["evidence_redacted"],
            )
            entry_type = record_form.cleaned_data["entry_type"]
            amount = record_form.cleaned_data["amount_vnd"]
            fund_entry_id = allocate_fund_entry_id()
            timestamp = timezone.now()
            event_id = new_event_id()
            typed = build_fund_source_evidence_typed_data(
                fund, membership, fund_entry_id, entry_type, amount,
                original, redacted, event_id, timestamp=timestamp,
            )
        except (ValidationError, PermissionDenied) as error:
            if isinstance(error, ValidationError):
                record_form.add_error(None, error)
            else:
                raise
        else:
            typed_data = json.dumps(typed)
            sign_form = SignFundSourceForm(
                initial={
                    "event_id": event_id,
                    "entry_type": entry_type,
                    "amount_vnd": amount,
                    "evidence_original_id": original.pk,
                    "evidence_redacted_id": redacted.pk,
                    "fund_entry_id": fund_entry_id,
                    "entry_timestamp": utc_rfc3339(timestamp),
                }
            )
    elif action == "submit":
        sign_form = SignFundSourceForm(request.POST)
        if sign_form.is_valid():
            original = get_object_or_404(
                DocumentVersion, pk=sign_form.cleaned_data["evidence_original_id"],
                document__building=building,
            )
            redacted = get_object_or_404(
                DocumentVersion, pk=sign_form.cleaned_data["evidence_redacted_id"],
                document__building=building,
            )
            timestamp = datetime.fromisoformat(sign_form.cleaned_data["entry_timestamp"])
            try:
                record_fund_source(
                    fund,
                    sign_form.cleaned_data["entry_type"],
                    sign_form.cleaned_data["amount_vnd"],
                    original,
                    redacted,
                    membership,
                    sign_form.cleaned_data["signature"],
                    sign_form.cleaned_data["event_id"],
                    fund_entry_id=sign_form.cleaned_data["fund_entry_id"],
                    timestamp=timestamp,
                )
            except (ValidationError, PermissionDenied) as error:
                if isinstance(error, ValidationError):
                    sign_form.add_error(None, error)
                else:
                    raise
            else:
                messages.success(request, "Fund source recorded; awaiting verification.")
                return redirect("web:fund-home")

    return render(
        request,
        "web/staff/fund_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="fund",
            list_mode=False,
            mode="record",
            record_form=record_form,
            sign_form=sign_form,
            typed_data=typed_data,
        ),
    )
```

Note: `datetime.fromisoformat` parses the `utc_rfc3339` "…Z" suffix on Python 3.11+ (this repo runs 3.12).

- [ ] **Step 3: Add the URL**

In `src/lamto/web/urls.py`, under the Fund ops group:

```python
    path("s/fund/record/", fund.fund_record, name="fund-record"),
```

- [ ] **Step 4: Fill the fund forms partial (record section)**

Replace `src/lamto/web/templates/web/staff/_fund_forms.html` with:

```html
<section class="panel">
  {% if mode == "record" %}
  <h1>Record fund source</h1>
  {% if sign_form %}
  <div class="signed-box">
    <h2>Review and sign</h2>
    <p class="hint">{{ sign_form.entry_type.value }} · {{ sign_form.amount_vnd.value }} VND</p>
    <form method="post" class="stack-form" data-signed-form>
      {% csrf_token %}
      <input type="hidden" name="action" value="submit">
      {{ sign_form.as_p }}
      <script type="application/json" data-typed-data>{{ typed_data|safe }}</script>
      <p class="hint" data-signing-status>Wallet will sign via eth_signTypedData_v4 when typed data is provided.</p>
      <button type="submit" class="button">Record source</button>
    </form>
  </div>
  {% else %}
  <form method="post" class="stack-form" enctype="multipart/form-data">
    {% csrf_token %}
    <input type="hidden" name="action" value="prepare">
    {{ record_form.as_p }}
    <p class="hint">Upload the source evidence original and a redacted copy (PDF). Amounts are integer VND.</p>
    <button type="submit" class="button">Prepare source</button>
  </form>
  {% endif %}
  {% endif %}
  {% if mode == "verify" %}{% include "web/staff/_fund_verify.html" %}{% endif %}
</section>
```

Add a placeholder `_fund_verify.html` (filled in Task 5) so this renders now:

```bash
printf '{# fund verify form — filled in Task 5 #}\n' > src/lamto/web/templates/web/staff/_fund_verify.html
```

- [ ] **Step 5: Write the record test**

Append to `src/lamto/web/tests/test_fund_ops.py`:

```python
class FundRecordTests(TestCase):
    def _login(self, seed, role_key):
        membership = seed.roles[role_key]
        self.client.force_login(membership.user)
        device = TOTPDevice.objects.create(
            user=membership.user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session["active_membership_id"] = membership.pk
        session.save()
        return membership

    @patch("lamto.web.staff_signing.scan_with_clamav", lambda _f: True)
    def test_prepare_then_sign_records_inflow(self):
        from lamto.finance.fund import build_fund_source_evidence_typed_data, get_or_create_fund
        from lamto.evidence.services import utc_rfc3339
        from datetime import datetime

        seed = seed_pilot_world(building_name="Fund Rec B", email_prefix="fr")
        recorder = self._login(seed, "fund_recorder")
        account = seed.accounts[recorder.pk]
        url = reverse("web:fund-record")

        prepare = self.client.post(
            url,
            {
                "action": "prepare",
                "entry_type": MaintenanceFundEntry.EntryType.INFLOW,
                "amount_vnd": 2_000_000,
                "evidence_original": _pdf("e.pdf", b"orig"),
                "evidence_redacted": _pdf("er.pdf", b"redacted differs"),
            },
        )
        self.assertEqual(prepare.status_code, 200)
        self.assertContains(prepare, "data-signed-form")
        sign = prepare.context["sign_form"].initial

        fund = get_or_create_fund(seed.building)
        original = DocumentVersion.objects.get(pk=sign["evidence_original_id"])
        redacted = DocumentVersion.objects.get(pk=sign["evidence_redacted_id"])
        ts = datetime.fromisoformat(sign["entry_timestamp"])
        typed = build_fund_source_evidence_typed_data(
            fund, recorder, sign["fund_entry_id"], MaintenanceFundEntry.EntryType.INFLOW,
            2_000_000, original, redacted, sign["event_id"], timestamp=ts,
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), account.key
        ).signature.hex()

        submit = self.client.post(
            url,
            {
                "action": "submit",
                "entry_type": MaintenanceFundEntry.EntryType.INFLOW,
                "amount_vnd": 2_000_000,
                "evidence_original_id": original.pk,
                "evidence_redacted_id": redacted.pk,
                "fund_entry_id": sign["fund_entry_id"],
                "entry_timestamp": sign["entry_timestamp"],
                "event_id": sign["event_id"],
                "signature": signature,
            },
        )
        self.assertRedirects(submit, reverse("web:fund-home"))
        entry = MaintenanceFundEntry.objects.get(pk=sign["fund_entry_id"])
        self.assertEqual(entry.entry_type, MaintenanceFundEntry.EntryType.INFLOW)
        self.assertEqual(entry.amount_vnd, 2_000_000)
        self.assertFalse(hasattr(entry, "verification"))

    def test_non_recorder_forbidden(self):
        seed = seed_pilot_world(building_name="Fund Rec Deny", email_prefix="frd")
        self._login(seed, "fund_verifier")  # verify-only cannot record
        self.assertEqual(self.client.get(reverse("web:fund-record")).status_code, 403)
```

- [ ] **Step 6: Run the record tests**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_fund_ops.py::FundRecordTests -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add src/lamto/web/forms/staff.py src/lamto/web/views/fund.py src/lamto/web/urls.py \
        src/lamto/web/templates/web/staff/_fund_forms.html \
        src/lamto/web/templates/web/staff/_fund_verify.html src/lamto/web/tests/test_fund_ops.py
git commit -m "feat: fund source recording with evidence upload and wallet signing"
```

---

### Task 5: Fund verification (verifier ≠ recorder)

Single-phase, fund-verifier capability: open an unverified entry, sign its deterministic verification payload → `verify_fund_source`. The service already rejects `verifier == recorder` (403) and cross-building entries; this task just surfaces it.

**Files:**
- Modify: `src/lamto/web/views/fund.py`
- Modify: `src/lamto/web/urls.py`
- Modify: `src/lamto/web/templates/web/staff/_fund_verify.html`
- Modify: `tests/isolation/test_cross_building_access.py`
- Test: `src/lamto/web/tests/test_fund_ops.py`

**Interfaces:**
- Consumes: `SignedDecisionForm` (base); `lamto.finance.fund.{build_fund_verification_evidence_typed_data, verify_fund_source}`; `MaintenanceFundEntry`.
- Produces: `fund.fund_verify(request, pk)` at `web:fund-verify` = `s/fund/verify/<int:pk>/` (`pk` is the fund-entry pk).

- [ ] **Step 1: Add the fund_verify view**

In `src/lamto/web/views/fund.py`, extend imports:

```python
from lamto.finance.fund import (
    allocate_fund_entry_id,
    build_fund_source_evidence_typed_data,
    build_fund_verification_evidence_typed_data,
    get_or_create_fund,
    record_fund_source,
    verify_fund_source,
)
from lamto.web.forms.staff import RecordFundSourceForm, SignFundSourceForm, SignedDecisionForm
```

Append the view:

```python
@login_required
@require_http_methods(["GET", "POST"])
def fund_verify(request, pk):
    """Sign the verification of an unverified fund source (verifier != recorder,
    enforced by the domain service)."""
    membership, memberships = require_staff_capability(request, FUND_VERIFY)
    building_id = membership.organization.building_id
    entry = get_object_or_404(
        MaintenanceFundEntry.objects.select_related("recorder", "outbox_event"),
        pk=pk,
        fund__building_id=building_id,
    )
    already_verified = hasattr(entry, "verification")
    verify_form = SignedDecisionForm(request.POST or None) if not already_verified else None
    typed_data = None
    if not already_verified and entry.outbox_event is not None:
        event_id = request.POST.get("event_id") or new_event_id()
        typed_data = json.dumps(
            build_fund_verification_evidence_typed_data(
                entry, membership, event_id, timestamp=entry.recorded_at
            )
        )
        if verify_form is not None and not request.POST:
            verify_form = SignedDecisionForm(initial={"event_id": event_id})

    if request.method == "POST" and verify_form is not None and verify_form.is_valid():
        require_recent_auth(request)
        try:
            verify_fund_source(
                entry,
                membership,
                verify_form.cleaned_data["signature"],
                verify_form.cleaned_data["event_id"],
                timestamp=entry.recorded_at,
            )
        except (ValidationError, PermissionDenied) as error:
            if isinstance(error, ValidationError):
                verify_form.add_error(None, error)
            else:
                raise
        else:
            messages.success(request, "Fund source verified.")
            return redirect("web:fund-home")

    return render(
        request,
        "web/staff/fund_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="fund",
            list_mode=False,
            mode="verify",
            entry=entry,
            verify_form=verify_form,
            typed_data=typed_data,
            already_verified=already_verified,
        ),
    )
```

`verify_fund_source` raises `PermissionDenied` when `verifier == recorder`; the view re-raises it (→ 403), matching the §2.3 in-tenant convention.

- [ ] **Step 2: Add the URL**

In `src/lamto/web/urls.py`, under the Fund ops group:

```python
    path("s/fund/verify/<int:pk>/", fund.fund_verify, name="fund-verify"),
```

- [ ] **Step 3: Fill the verify partial**

Replace `src/lamto/web/templates/web/staff/_fund_verify.html` with:

```html
<h1>Verify fund source #{{ entry.pk }}</h1>
<dl class="detail-list">
  <div><dt>Type</dt><dd>{{ entry.get_entry_type_display }}</dd></div>
  <div><dt>Amount</dt><dd>{{ entry.amount_vnd }} VND</dd></div>
  <div><dt>Recorded</dt><dd>{{ entry.recorded_at }}</dd></div>
</dl>
{% if already_verified %}
<p class="hint">This source is already verified.</p>
{% elif verify_form %}
<div class="signed-box">
  <h2>Sign verification</h2>
  <p class="hint">A source recorder cannot verify their own source.</p>
  <form method="post" class="stack-form" data-signed-form>
    {% csrf_token %}
    {{ verify_form.as_p }}
    <script type="application/json" data-typed-data>{{ typed_data|safe }}</script>
    <p class="hint" data-signing-status>Wallet will sign via eth_signTypedData_v4 when typed data is provided.</p>
    <button type="submit" class="button">Verify source</button>
  </form>
</div>
{% endif %}
```

- [ ] **Step 4: Write the verify tests**

Append to `src/lamto/web/tests/test_fund_ops.py`:

```python
class FundVerifyTests(TestCase):
    def _login(self, seed, role_key):
        membership = seed.roles[role_key]
        self.client.force_login(membership.user)
        device = TOTPDevice.objects.create(
            user=membership.user, name="t", confirmed=True, key=random_hex()
        )
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session["active_membership_id"] = membership.pk
        session.save()
        return membership

    def _unverified_entry(self, seed):
        """Record an inflow via the recorder domain path (unverified)."""
        from datetime import datetime
        from lamto.finance.fund import (
            allocate_fund_entry_id,
            build_fund_source_evidence_typed_data,
            get_or_create_fund,
            record_fund_source,
        )
        from lamto.documents.models import Document

        fund = get_or_create_fund(seed.building)
        recorder = seed.roles["fund_recorder"]
        original, redacted = seed.document_pair(Document.Kind.CONTRACT, recorder.user, "inflow")
        entry_id = allocate_fund_entry_id()
        ts = timezone.now()
        event_id = "0x" + "22" * 32
        typed = build_fund_source_evidence_typed_data(
            fund, recorder, entry_id, MaintenanceFundEntry.EntryType.INFLOW,
            1_000_000, original, redacted, event_id, timestamp=ts,
        )
        sig = seed.sign_typed(recorder, typed)
        return record_fund_source(
            fund, MaintenanceFundEntry.EntryType.INFLOW, 1_000_000, original, redacted,
            recorder, sig, event_id, fund_entry_id=entry_id, timestamp=ts,
        )

    def test_verifier_signs_and_verifies(self):
        from lamto.finance.fund import build_fund_verification_evidence_typed_data

        seed = seed_pilot_world(building_name="Fund Ver B", email_prefix="fv")
        entry = self._unverified_entry(seed)
        verifier = self._login(seed, "fund_verifier")
        account = seed.accounts[verifier.pk]
        url = reverse("web:fund-verify", kwargs={"pk": entry.pk})

        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        event_id = page.context["verify_form"].initial["event_id"]
        typed = build_fund_verification_evidence_typed_data(
            entry, verifier, event_id, timestamp=entry.recorded_at
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), account.key
        ).signature.hex()
        resp = self.client.post(url, {"event_id": event_id, "signature": signature})
        self.assertRedirects(resp, reverse("web:fund-home"))
        entry.refresh_from_db()
        self.assertTrue(hasattr(entry, "verification"))

    def test_recorder_cannot_verify_own_source(self):
        from lamto.finance.fund import build_fund_verification_evidence_typed_data

        seed = seed_pilot_world(building_name="Fund Ver Deny", email_prefix="fvd")
        entry = self._unverified_entry(seed)
        # Recorder also holds verify capability for this test.
        from lamto.accounts.services import grant_capability
        from lamto.accounts.capabilities import FUND_VERIFY

        recorder = seed.roles["fund_recorder"]
        grant_capability(recorder, FUND_VERIFY)
        self._login(seed, "fund_recorder")
        account = seed.accounts[recorder.pk]
        url = reverse("web:fund-verify", kwargs={"pk": entry.pk})
        page = self.client.get(url)
        event_id = page.context["verify_form"].initial["event_id"]
        typed = build_fund_verification_evidence_typed_data(
            entry, recorder, event_id, timestamp=entry.recorded_at
        )
        signature = Account.sign_message(
            encode_typed_data(full_message=typed), account.key
        ).signature.hex()
        resp = self.client.post(url, {"event_id": event_id, "signature": signature})
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 5: Run the verify tests**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_fund_ops.py::FundVerifyTests -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Classify the new pk route in the adversarial suite**

In `tests/isolation/test_cross_building_access.py`:

Add `MaintenanceFundEntry` to the finance-models import:

```python
from lamto.finance.models import (
    AcceptanceRecord,
    MaintenanceFundEntry,
    PaymentEvidence,
    Proposal,
    PublishedLedgerEntry,
)
```

In `setUpTestData`, after the existing `cls.b = {...}` assignment, capture Building B's verified opening-balance entry pk (seeded by `seed_pilot_world`, `create_opening_fund=True`):

```python
        b_fund_entry = MaintenanceFundEntry.objects.get(
            fund__building=b_building,
            entry_type=MaintenanceFundEntry.EntryType.OPENING_BALANCE,
        )
        cls.b["fund_entry_pk"] = b_fund_entry.pk
```

Add to `STAFF_CASES`:

```python
    "web:fund-verify": ("fund_entry_pk", "fund_verifier", "POST"),
```

- [ ] **Step 7: Run the isolation suite**

Run: `.venv/bin/python -m pytest tests/isolation/test_cross_building_access.py -q`
Expected: PASS — `fund-verify` returns 404 for Building A's verifier against Building B's entry; `test_every_pk_route_is_classified` green.

- [ ] **Step 8: Commit**

```bash
git add src/lamto/web/views/fund.py src/lamto/web/urls.py \
        src/lamto/web/templates/web/staff/_fund_verify.html \
        src/lamto/web/tests/test_fund_ops.py tests/isolation/test_cross_building_access.py
git commit -m "feat: fund source verification screen with maker-checker separation"
```

---

### Task 6: Shared list-page pattern (filter chips · status chips · deadline badges)

One reusable list partial + CSS, applied to cases/work/proposals/payments/fund lists. Server-rendered, vanilla only, no redesign (§4.3.3). Adds a minimal `?status=` exact-match filter rendered as clickable chips.

**Files:**
- Create: `src/lamto/web/templates/web/staff/_list.html`
- Modify: `src/lamto/web/static/web/app.css`
- Modify: `src/lamto/web/views/maintenance.py` (work-order list `?status=`)
- Modify: `src/lamto/web/templates/web/staff/work_order_detail.html` (list mode → partial)
- Test: `src/lamto/web/tests/test_list_pattern.py`

**Interfaces:**
- Consumes: existing list context (`work_orders`, etc.).
- Produces: `_list.html` partial expecting `items` (list of `{"url", "title", "status", "deadline"}`), `filters` (list of `{"label", "value", "active"}`), `filter_param`, `empty_label`. `maintenance.work_order_list` accepts `?status=<WorkOrder.Status>`.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/web/tests/test_list_pattern.py`:

```python
import time

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.models import (
    Building,
    Organization,
    OrganizationMembership,
    Unit,
)
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.maintenance.models import (
    BuildingLocation,
    IssueReport,
    MaintenanceCase,
    TriageDecision,
    WorkOrder,
)


@override_settings(ROOT_URLCONF="lamto.config.urls")
class ListPatternTests(TestCase):
    def _make_work(self, building, case, assignee, status):
        return WorkOrder.objects.create(
            case=case, assignee=assignee, priority="HIGH",
            deadline_at=timezone.now(), requires_spending=True,
            authorization_status=WorkOrder.AuthorizationStatus.AUTHORIZED, status=status,
        )

    def test_work_list_renders_status_chip_and_filters(self):
        building = Building.objects.create(name="List B")
        location = BuildingLocation.objects.create(building=building, name="Lobby", active=True)
        org = Organization.objects.create(
            building=building, name="M", kind=Organization.Kind.OPERATOR
        )
        user = get_user_model().objects.create_user(
            email="m@example.test", password="secret", display_name="M"
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=org, role=OrganizationMembership.Role.MAINTENANCE
        )
        unit = Unit.objects.create(building=building, label="A-1")
        resident = get_user_model().objects.create_user(
            email="r@example.test", password="secret", display_name="R"
        )
        report = IssueReport.objects.create(
            reporter=resident, unit=unit, text="x", selected_location=location,
            location_path_snapshot="x",
        )
        decision = TriageDecision.objects.create(
            report=report, operator=user, category="c", urgency="HIGH",
            location=location, department="Ops", deadline_minutes=60, differences={},
        )
        case = MaintenanceCase.objects.create(
            decision=decision, building=building, category="c", urgency="HIGH",
            location=location, department="Ops", deadline_at=timezone.now(), active=True,
        )
        self._make_work(building, case, user, WorkOrder.Status.ASSIGNED)
        self._make_work(building, case, user, WorkOrder.Status.COMPLETED)

        self.client.force_login(user)
        device = TOTPDevice.objects.create(user=user, name="t", confirmed=True, key=random_hex())
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()

        resp = self.client.get(reverse("web:work-order-list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "status-chip")
        self.assertContains(resp, "filter-bar")

        filtered = self.client.get(reverse("web:work-order-list"), {"status": "ASSIGNED"})
        self.assertContains(filtered, "ASSIGNED")
        self.assertNotContains(filtered, "COMPLETED")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_list_pattern.py -q`
Expected: FAIL — response lacks `status-chip`/`filter-bar`.

- [ ] **Step 3: Add the shared partial**

Create `src/lamto/web/templates/web/staff/_list.html`:

```html
{% if filters %}
<div class="filter-bar" role="group" aria-label="Filter by status">
  {% for f in filters %}
  <a class="chip {% if f.active %}chip-active{% endif %}"
     href="?{{ filter_param }}={{ f.value }}">{{ f.label }}</a>
  {% endfor %}
  <a class="chip {% if not filters_active %}chip-active{% endif %}" href="?">All</a>
</div>
{% endif %}
<ul class="card-list">
  {% for item in items %}
  <li>
    <a class="card-link" href="{{ item.url }}">
      <p class="card-title">{{ item.title }}
        {% if item.status %}<span class="status-chip">{{ item.status }}</span>{% endif %}</p>
      {% if item.deadline %}<p class="card-meta"><span class="deadline-badge">Deadline {{ item.deadline }}</span></p>{% endif %}
    </a>
  </li>
  {% empty %}
  <li><p>{{ empty_label|default:"Nothing to show." }}</p></li>
  {% endfor %}
</ul>
```

- [ ] **Step 4: Add the CSS**

Append to `src/lamto/web/static/web/app.css`:

```css
.filter-bar { display: flex; flex-wrap: wrap; gap: .5rem; margin: .5rem 0 1rem; }
.chip { display: inline-flex; align-items: center; min-height: 36px; padding: .25rem .75rem;
        border-radius: 999px; background: #eef1f8; color: #1c2434; text-decoration: none; font-size: .9rem; }
.chip-active { background: #2f3a8f; color: #fff; }
.status-chip { display: inline-block; margin-left: .5rem; padding: .1rem .5rem; border-radius: 6px;
               background: #eef1f8; color: #1c2434; font-size: .8rem; }
.deadline-badge { display: inline-block; padding: .1rem .5rem; border-radius: 6px;
                  background: #fff4e5; color: #7a4b00; font-size: .8rem; }
```

- [ ] **Step 5: Apply to the work-order list**

In `src/lamto/web/views/maintenance.py`, replace the `work_order_list` body's queryset + render with a status filter and item mapping:

```python
@login_required
@require_GET
def work_order_list(request):
    membership, memberships = resolve_active_membership(request)
    _require_maintenance(membership)
    building_id = membership.organization.building_id
    qs = WorkOrder.objects.filter(case__building_id=building_id)
    if membership.role == OrganizationMembership.Role.MAINTENANCE:
        qs = qs.filter(assignee=request.user)
    status = request.GET.get("status") or ""
    valid_status = status in WorkOrder.Status.values
    if valid_status:
        qs = qs.filter(status=status)
    work_orders = qs.order_by("-created_at")[:100]
    items = [
        {
            "url": f"/s/work/{wo.pk}/",
            "title": f"Work order #{wo.pk}",
            "status": wo.status,
            "deadline": wo.deadline_at,
        }
        for wo in work_orders
    ]
    filters = [
        {"label": label, "value": value, "active": valid_status and value == status}
        for value, label in WorkOrder.Status.choices
    ]
    return render(
        request,
        "web/staff/work_order_detail.html",
        staff_context(
            request,
            membership,
            memberships,
            nav_active="work",
            list_mode=True,
            items=items,
            filters=filters,
            filters_active=valid_status,
            filter_param="status",
            empty_label="No work orders.",
        ),
    )
```

In `src/lamto/web/templates/web/staff/work_order_detail.html`, replace the `{% if list_mode %}` block's `<h1>…</h1>` + `<ul class="card-list">…</ul>` with:

```html
{% if list_mode %}
<section class="panel">
  <h1>Work orders</h1>
  {% include "web/staff/_list.html" %}
</section>
{% else %}
```

(Leave the detail `{% else %}` branch unchanged.)

- [ ] **Step 6: Run the test**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_list_pattern.py -q`
Expected: PASS (1 passed).

- [ ] **Step 7: Apply the partial to cases, proposals, and payments**

The partial takes one `items` list; multi-list pages call it twice with `{% include ... with items=... %}`. Keep every existing context key the other (detail) branches use; `fund_home` keeps its bespoke entries list (verify links) — do not rewire it.

**`operator.case_list`** — in `src/lamto/web/views/operator.py`, add `items` builds to the render context (keep `open_reports`/`cases` too):

```python
    report_items = [
        {"url": f"/s/reports/{r.pk}/", "title": r.text, "status": r.get_status_display(), "deadline": None}
        for r in open_reports
    ]
    case_items = [
        {"url": f"/s/cases/{c.pk}/", "title": f"Case #{c.pk} · {c.category}",
         "status": c.urgency, "deadline": c.deadline_at}
        for c in cases
    ]
```

Pass `report_items=report_items, case_items=case_items` into `staff_context(...)`. In `case_detail.html` list mode, replace each `<ul class="card-list">…</ul>` with the include:

```html
<section class="panel">
  <h1>Open reports</h1>
  {% include "web/staff/_list.html" with items=report_items empty_label="No open reports." %}
</section>
<section class="panel">
  <h2>Active cases</h2>
  {% include "web/staff/_list.html" with items=case_items empty_label="No active cases." %}
</section>
```

**`operator.proposal_list`** — add to context:

```python
    proposal_items = [
        {
            "url": f"/s/proposals/{p.pk}/",
            "title": f"Proposal #{p.pk}" + (f" · {p.current_version.amount_vnd} VND" if p.current_version else ""),
            "status": p.get_status_display(),
            "deadline": None,
        }
        for p in proposals
    ]
```

Pass `proposal_items=proposal_items`. In `proposal_detail.html` list mode, replace the `<ul class="card-list">…</ul>` with:

```html
{% include "web/staff/_list.html" with items=proposal_items empty_label="No proposals." %}
```

**`board.payment_list`** — add to context:

```python
    record_items = [
        {"url": f"/s/payments/record/{a.pk}/", "title": f"Acceptance #{a.pk} · {a.actual_cost_vnd} VND",
         "status": None, "deadline": None}
        for a in pending_record
    ]
    verify_items = [
        {"url": f"/s/payments/verify/{p.pk}/", "title": f"Payment #{p.pk} · {p.amount_vnd} VND",
         "status": p.get_external_status_display(), "deadline": None}
        for p in pending_verify
    ]
```

Pass `record_items=record_items, verify_items=verify_items`. In `payment_detail.html` list mode, keep the single `<section>`, the `<h1>Payments</h1>`, and both `<h2>` headings; replace only each `<ul class="card-list">…</ul>` with the include:

```html
{% if list_mode %}
<section class="panel">
  <h1>Payments</h1>
  {% if can_record %}
  <h2>Record payment</h2>
  {% include "web/staff/_list.html" with items=record_items empty_label="No payments to record." %}
  {% endif %}
  {% if can_verify %}
  <h2>Payment verification</h2>
  {% include "web/staff/_list.html" with items=verify_items empty_label="No payments awaiting verification." %}
  {% endif %}
</section>
{% else %}
```

Leave the detail `{% else %}` branch (the signed record/verify forms) unchanged. Keep the `Record payment` / `Payment verification` heading strings — `test_role_workspaces` asserts on them.

- [ ] **Step 8: Run the affected suites**

Run: `.venv/bin/python -m pytest src/lamto/web/tests -q`
Expected: PASS — existing role-workspace and view tests still green with the partial in place.

- [ ] **Step 9: Commit**

```bash
git add src/lamto/web/templates/web/staff/_list.html src/lamto/web/static/web/app.css \
        src/lamto/web/views/maintenance.py src/lamto/web/views/operator.py src/lamto/web/views/board.py \
        src/lamto/web/templates/web/staff/work_order_detail.html \
        src/lamto/web/templates/web/staff/proposal_detail.html \
        src/lamto/web/templates/web/staff/payment_detail.html \
        src/lamto/web/templates/web/staff/case_detail.html \
        src/lamto/web/tests/test_list_pattern.py
git commit -m "feat: shared staff list pattern with filter chips, status chips, deadline badges"
```

---

### Task 7: IA — six active areas (Ledger deferred) + switch-returns-to-inbox

Fold Proposals·Payments·Fund into a single **Finance** area; present the **six active** staff areas (Inbox · Cases · Work · Finance · Audit · Ops). Spec §4.2's seventh area (**Ledger**) remains **deferred** — do not claim a completed seven-area IA. Return the membership switch to the Inbox (§4.2). (Building name is already in the header.)

**Files:**
- Modify: `src/lamto/web/staff.py`
- Modify: `src/lamto/web/views/staff_common.py`
- Modify: `src/lamto/web/templates/web/staff/shell.html`
- Modify: `src/lamto/web/views/operator.py`, `board.py`, `fund.py` (remap `nav_active` to `"finance"`)
- Test: `src/lamto/web/tests/test_staff_nav.py`

**Interfaces:**
- Consumes: `capabilities_for`, `OrganizationMembership`.
- Produces: `nav_items_for(membership)` returning the six active areas (Ledger deferred); `switch_membership` always redirects to `web:action-inbox`.

- [ ] **Step 1: Write the failing tests**

Create `src/lamto/web/tests/test_staff_nav.py`:

```python
import time

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex

from lamto.accounts.capabilities import FUND_RECORD, PAYMENT_VERIFY, PROPOSAL_APPROVE
from lamto.accounts.models import Building, Organization, OrganizationMembership
from lamto.accounts.security import RECENT_REAUTH_KEY
from lamto.accounts.services import grant_capability
from lamto.web.staff import nav_items_for


class NavStructureTests(TestCase):
    def _board(self, *caps):
        building = Building.objects.create(name="Nav B")
        org = Organization.objects.create(
            building=building, name="Board", kind=Organization.Kind.BOARD
        )
        user = get_user_model().objects.create_user(
            email="b@example.test", password="secret", display_name="B"
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=org, role=OrganizationMembership.Role.BOARD
        )
        for c in caps:
            grant_capability(membership, c)
        return membership

    def test_finance_area_appears_once_for_finance_capabilities(self):
        membership = self._board(PROPOSAL_APPROVE, PAYMENT_VERIFY, FUND_RECORD)
        labels = [i["label"] for i in nav_items_for(membership)]
        self.assertEqual(labels.count("Finance"), 1)
        self.assertNotIn("Proposals", labels)
        self.assertNotIn("Payments", labels)
        self.assertIn("Inbox", labels)

    def test_finance_lands_on_fund_when_only_fund_capability(self):
        membership = self._board(FUND_RECORD)
        finance = [i for i in nav_items_for(membership) if i["label"] == "Finance"]
        self.assertEqual(finance[0]["url_name"], "web:fund-home")

    def test_ledger_area_not_present_phase0(self):
        """Six active areas only; Ledger is deferred (no nav entry)."""
        membership = self._board(PROPOSAL_APPROVE, PAYMENT_VERIFY, FUND_RECORD)
        labels = [i["label"] for i in nav_items_for(membership)]
        self.assertNotIn("Ledger", labels)
        for label in ("Inbox", "Finance"):
            self.assertIn(label, labels)


@override_settings(ROOT_URLCONF="lamto.config.urls")
class SwitchReturnsToInboxTests(TestCase):
    def test_switch_redirects_to_inbox(self):
        building = Building.objects.create(name="Switch B")
        org = Organization.objects.create(
            building=building, name="Ops", kind=Organization.Kind.OPERATOR
        )
        user = get_user_model().objects.create_user(
            email="s@example.test", password="secret", display_name="S"
        )
        membership = OrganizationMembership.objects.create(
            user=user, organization=org, role=OrganizationMembership.Role.OPERATOR
        )
        self.client.force_login(user)
        device = TOTPDevice.objects.create(user=user, name="t", confirmed=True, key=random_hex())
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session[RECENT_REAUTH_KEY] = time.time()
        session.save()
        resp = self.client.post(
            reverse("web:switch-membership"),
            {"membership": membership.pk, "next": "/s/cases/"},
        )
        self.assertRedirects(resp, reverse("web:action-inbox"), target_status_code=200)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_staff_nav.py -q`
Expected: FAIL — the current nav still emits "Proposals"/"Payments"; switch honours `next`.

- [ ] **Step 3: Restructure `nav_items_for`**

In `src/lamto/web/staff.py`, replace the entire `NAV_BY_CAPABILITY` tuple and `nav_items_for` function with:

```python
def nav_items_for(membership) -> list[dict]:
    """Six active capability-filtered areas (spec 4.2 Phase-0): Inbox · Cases ·
    Work · Finance (proposals · payments · fund) · Audit · Ops.
    Ledger (seventh area) is deferred — not in this nav."""
    caps = capabilities_for(membership)
    role = membership.role
    Role = OrganizationMembership.Role
    items: list[dict] = [{"label": "Inbox", "url_name": "web:action-inbox", "capability": None}]

    if "report.triage" in caps:
        items.append({"label": "Cases", "url_name": "web:case-list", "capability": "report.triage"})

    # Work: operators (assign), board acceptors (accept), and maintenance.
    # Preserves the pre-Plan-4 behavior where work.accept also surfaced Work.
    if caps & {"work.assign", "work.accept"} or role == Role.MAINTENANCE:
        maintenance_only = role == Role.MAINTENANCE and not (caps & {"work.assign", "work.accept"})
        items.append(
            {"label": "My work" if maintenance_only else "Work", "url_name": "web:work-order-list", "capability": None}
        )

    # Finance groups proposals · payments · fund; appears once, landing on the
    # first sub-area the membership can open.
    finance_caps = {
        "proposal.create", "proposal.approve", "ledger.publish",
        "payment.record", "payment.verify", "fund.record", "fund.verify",
    }
    if caps & finance_caps:
        if caps & {"proposal.create", "proposal.approve", "ledger.publish"}:
            finance_url = "web:proposal-list"
        elif caps & {"payment.record", "payment.verify"}:
            finance_url = "web:payment-list"
        else:
            finance_url = "web:fund-home"
        items.append({"label": "Finance", "url_name": finance_url, "capability": None})

    if role == Role.AUDITOR or "audit.export" in caps:
        items.append({"label": "Audit", "url_name": "web:audit-search", "capability": "audit.export"})

    if role == Role.TECH_ADMIN:
        items.append({"label": "Ops", "url_name": "web:ops-health", "capability": "tech.admin"})

    return items
```

Delete the now-unused interim Fund block added in Task 3 (it is superseded by the Finance grouping) and the `NAV_BY_CAPABILITY` constant.

- [ ] **Step 4: Remap `nav_active` to `"finance"`**

Set `nav_active="finance"` on every finance page so the Finance nav item highlights:
- `operator.py`: `proposal_list`, `proposal_detail`, `proposal_create` → `nav_active="finance"`.
- `board.py`: `payment_record`? (POST-only, no render) — update `payment_list`, `payment_record_detail`, `payment_verify_detail` renders → `nav_active="finance"`.
- `fund.py`: `fund_home`, `fund_record`, `fund_verify` → `nav_active="finance"`.

Update `nav_active="work"` stays; `case-*` stays `"cases"`; inbox stays `"inbox"`. The shell matches `nav_active == item.label|lower` (`"finance" == "Finance"|lower`).

- [ ] **Step 5: Switch returns to Inbox**

In `src/lamto/web/views/staff_common.py`, change `switch_membership` to ignore `next` and always land on the Inbox (§4.2 — never deep-link into a previous building's detail page):

```python
@login_required
@require_http_methods(["GET", "POST"])
def switch_membership(request):
    membership_id = request.POST.get("membership") or request.GET.get("membership")
    if membership_id is None:
        raise PermissionDenied("membership is required")
    membership, _ = resolve_active_membership(request, membership_id=membership_id)
    request.session[SESSION_MEMBERSHIP_KEY] = membership.pk
    return redirect("web:action-inbox")
```

In `src/lamto/web/templates/web/staff/shell.html`, remove the `<input type="hidden" name="next" value="{{ request.path }}">` line from the membership-switch form (no longer used).

- [ ] **Step 6: Run the nav tests**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_staff_nav.py -q`
Expected: PASS (4 passed).

- [ ] **Step 7: Run the staff web suite for regressions**

Run: `.venv/bin/python -m pytest src/lamto/web/tests -q`
Expected: PASS — role-workspace, occupancy-switch, and evidence-label tests still green under the new nav.

- [ ] **Step 8: Commit**

```bash
git add src/lamto/web/staff.py src/lamto/web/views/staff_common.py \
        src/lamto/web/views/operator.py src/lamto/web/views/board.py src/lamto/web/views/fund.py \
        src/lamto/web/templates/web/staff/shell.html src/lamto/web/tests/test_staff_nav.py
git commit -m "feat: six-area staff nav (Ledger deferred) and switch returns to inbox"
```

- [ ] **Step 9: Full regression gate (exit gate)**

Run the whole suite to confirm the six e2e journeys, the two-building adversarial walk, and the finance/isolation suites are all green:

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS — no regressions; new `proposal-create` and `fund-verify` routes classified; all Plan 4 tests green.

---

## Self-review

### Spec §4 coverage map

| Spec | Requirement | Task |
|---|---|---|
| §4.3.1 | Create-proposal from spending work order: amount VND · contractor · quotation upload → freeze version → operator signs → Board inbox; reuses `SignedDecisionForm` + document pipeline | Task 2 (+ Task 1 upload) |
| §4.3.2 | Fund entries list + derived balance + pending-fund-verification (separate selector) + pending-reconciliation (publication-eligible, settled chain) | Task 3 |
| §4.3.2 | Record opening balance / inflow with evidence upload (fund-recorder) | Task 4 |
| §4.3.2 | Verification screen (fund-verifier; verifier ≠ recorder server-enforced) | Task 5 |
| §4.3.3 | One shared list-page pattern (filter chips · status chips · deadline badges) on cases/work/proposals/payments | Task 6 |
| §4.2 | Six active IA areas (Ledger deferred), capability-filtered; Finance groups proposals · payments · fund | Task 7 |
| §4.2 | Building name in header chrome | Already present in `shell.html` — no change |
| §4.2 | Switching membership returns to Inbox | Task 7 |
| §4.4 | MFA / reauth / wallet signing / maker-checker / publication gates / auditor exports / break-glass unchanged; no SPA, no staff API | Preserved — new forms reuse `require_staff_capability` (MFA) + `require_recent_auth` + `SignedDecisionForm`; all mutations via existing services |
| §2.3 | New `<int:pk>` routes classified in adversarial suite (cross-tenant → 404) | Tasks 2, 5 |
| §5.3 | No payment-provider dependency added | No `pyproject.toml` change in this plan |

### Placeholder scan

No `TBD`/`add validation`/`similar to Task N`. Every code step carries complete code; the one interim placeholder file (`_fund_forms.html`, `_fund_verify.html`) is explicitly created in Task 3/4 and filled in Task 4/5.

### Type consistency

- `new_event_id` / `upload_document_pair` signatures identical across Tasks 1, 2, 4.
- `SignProposalForm` / `SignFundSourceForm` hidden-field names match exactly what the views read (`cleaned_data[...]`) and what the tests POST.
- `nav_active="finance"` (Task 7) matches the `"Finance"` label lowercased in `shell.html`'s active-match; `nav_active="fund"` used interim in Tasks 3–5 is remapped to `"finance"` in Task 7 Step 4.
- Domain service call signatures (`submit_proposal_version`, `record_fund_source`, `verify_fund_source`, `build_fund_source_evidence_typed_data`, `build_fund_verification_evidence_typed_data`) match `finance/proposals.py` and `finance/fund.py` verbatim.

## Out of scope (Plan 4)

- **Staff "Ledger" area** (published entries · corrections · integrity observations as a dedicated nav area) — §4.2's seventh area; no view exists and §4.3 does not build it. Deferred to a later plan. Phase-0 ships **six active areas only**; do not describe the nav as a completed seven-area IA.
- Resident API and Flutter app (Plans 3 done / Phase 1).
- New domain behavior — none; all services pre-exist.
- Emergency-mode proposal nuances beyond `submit_proposal_version`'s existing handling (the create flow guards on `requires_spending` and delegates mode to the service).
- Rich list filtering beyond a single `?status=` exact-match chip row (no date-range/search DSL — YAGNI).
- Payment recording/verification UI redesign — untouched beyond the shared list partial.

## Deviations

