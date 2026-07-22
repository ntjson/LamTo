# Single Manager, No Redaction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one management account record and publish everything, and serve residents original documents instead of redacted copies.

**Architecture:** Two independent changes against a Django 5.2 + DRF backend with a Flutter resident app. The first deletes a single recorder≠verifier rule in `finance/fund.py` and seeds one manager instead of two. The second removes the redaction concept in dependency order — finance evidence pairs first, then the `DocumentVersion.variant`/`redacts` schema, then cosmetic field renames, then the resident API contract — so every commit leaves a green test suite.

**Tech Stack:** Python 3.12, Django 5.2, Django REST Framework, PostgreSQL (roles: `lamto_owner` for migrations/tests, `lamto_writer` for runtime), drf-spectacular, Flutter/Dart with an OpenAPI-generated `lamto_api` package.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-22-single-manager-no-redaction-design.md`. Read it before starting.
- **No new dependencies.** Nothing is added to `pyproject.toml` or `app/pubspec.yaml`.
- **The database is disposable.** It holds dev and seed data only. Migrations drop columns outright — no data migrations, no back-compat branches, no nullable-then-drop two-step.
- **Django tests:** `.venv/bin/python manage.py test <label> -v 2`
- **Pytest suites (e2e, isolation):** `.venv/bin/python -m pytest <path> -v`
- **Flutter tests:** run from `app/`: `flutter test`
- **Migrations and tests connect as `lamto_owner`**, not `lamto_writer`. If `manage.py migrate` fails with a permission error, that env override is missing.
- **Amounts are integer VND.** Never introduce a float or `Decimal` into a money path.
- **Resident-facing copy is Vietnamese-first** and keyed from machine codes. Both `app/lib/l10n/app_en.arb` and `app_vi.arb` change together, never one alone.
- **`variant` and `redacts` stay untouched until Task 5.** Tasks 1–4 must not reference them in new code, but must not remove them either.
- **Commit at the end of every task.** Never bundle two tasks into one commit.

---

### Task 1: Fund self-confirmation for a single manager

Removes the only hard two-person rule in the domain. `verify_fund_source` currently sets a `denied` flag when the verifier is the recorder, escapes the atomic block, writes a denial audit, and raises `PermissionDenied`. After this task the same manager may record and then confirm.

**Files:**
- Modify: `src/lamto/finance/fund.py:189-245`
- Modify: `src/lamto/web/views/fund.py:141-142` (docstring only)
- Test: `src/lamto/finance/tests/test_fund.py`
- Test: `src/lamto/web/tests/test_fund_ops.py:249-256`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `verify_fund_source(entry, verifier, timestamp=None) -> FundEntryVerification` — signature unchanged; no longer raises `PermissionDenied` when `verifier` is the recorder. Still raises `ValidationError` when already verified.

- [ ] **Step 1: Rewrite the existing dual-control test as a self-confirm test**

In `src/lamto/finance/tests/test_fund.py`, first drop the second membership from `setUp`. This is the last use of `self.verifier` in the file, and leaving the binding would make the next task fail — Task 2 reduces the list to one entry, and unpacking a one-element slice into two names raises `ValueError`. Index rather than unpack, so the line is correct both before and after Task 2. Replace line 14:

```python
        self.recorder = self.seed.management_memberships[0]
```

Then replace the whole of `test_record_and_verify_are_offchain_and_dual_controlled`. The old test asserted the denial that is being deleted, so it is replaced rather than inverted.

```python
    def test_record_and_self_confirm_are_offchain_and_move_the_balance(self):
        before = BlockchainOutboxEvent.objects.count()
        balance_before = fund_balance(self.seed.building.pk)
        entry = record_fund_source(
            self.fund, MaintenanceFundEntry.EntryType.INFLOW, 50_000_000,
            self.original, self.redacted, self.recorder,
        )
        # The balance only counts confirmed sources, so recording alone moves nothing.
        self.assertEqual(fund_balance(self.seed.building.pk), balance_before)

        verification = verify_fund_source(entry, self.recorder)

        self.assertEqual(verification.membership, self.recorder)
        self.assertEqual(BlockchainOutboxEvent.objects.count(), before)
        self.assertEqual(fund_balance(self.seed.building.pk), balance_before + 50_000_000)

    def test_a_source_cannot_be_confirmed_twice(self):
        entry = record_fund_source(
            self.fund, MaintenanceFundEntry.EntryType.INFLOW, 1_000_000,
            self.original, self.redacted, self.recorder,
        )
        verify_fund_source(entry, self.recorder)
        with self.assertRaisesRegex(ValidationError, "already been verified"):
            verify_fund_source(entry, self.recorder)
```

Fix the imports at the top of that file — `PermissionDenied` is no longer used, and `ValidationError` now is:

```python
from django.core.exceptions import ValidationError
from django.test import TestCase
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python manage.py test lamto.finance.tests.test_fund -v 2`
Expected: FAIL. `test_record_and_self_confirm_are_offchain_and_move_the_balance` raises `PermissionDenied: Fund recorder cannot verify their own source.`

- [ ] **Step 3: Delete the same-actor denial branch**

In `src/lamto/finance/fund.py`, replace the entire `verify_fund_source` function with the version below. The `denied` / `denied_target` / `denied_actor` locals existed only to carry the denial out of the atomic block, so they go with it, and the trailing `if denied:` block goes too. The function no longer needs its own `with transaction.atomic():` scope juggling — the decorator form is enough.

```python
@transaction.atomic
def verify_fund_source(
    entry,
    verifier,
    timestamp=None,
) -> FundEntryVerification:
    entry = _locked_entry(entry)
    actor = require_management(verifier.user, entry.fund.building_id)
    if entry.entry_type not in SOURCE_ENTRY_TYPES:
        raise ValidationError("Only opening balance and inflow sources may be verified.")
    if entry.recorder is None:
        raise ValidationError("Fund source has no recorder.")
    if FundEntryVerification.objects.filter(entry=entry).exists():
        raise ValidationError("Fund source has already been verified.")
    verification = FundEntryVerification.objects.create(
        entry=entry,
        membership=actor,
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
        },
    )
    return verification
```

- [ ] **Step 4: Drop the now-unused PermissionDenied import**

`PermissionDenied` is still imported at the top of `src/lamto/finance/fund.py` but no longer raised anywhere in the file. Confirm with `grep -n "PermissionDenied" src/lamto/finance/fund.py` — if the only hit is the import line, change:

```python
from django.core.exceptions import PermissionDenied, ValidationError
```

to:

```python
from django.core.exceptions import ValidationError
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python manage.py test lamto.finance.tests.test_fund -v 2`
Expected: PASS, 2 tests.

- [ ] **Step 6: Delete the web-layer denial test and fix its login helper**

In `src/lamto/web/tests/test_fund_ops.py`, delete `test_recorder_cannot_verify_own_source` (lines 249-256) entirely — the 403 it asserts can no longer happen.

In the same file there are two identical `_login` helpers (one in `FundRecordTests` at line 162, one in `FundVerifyTests` at line 210). Both index `management_memberships[1]` for verifier roles. Task 2 reduces that list to one entry, so both must change now. In **both** helpers, replace:

```python
        membership = seed.management_memberships[1 if "verifier" in role_key else 0]
```

with:

```python
        membership = seed.management_memberships[0]
```

- [ ] **Step 7: Run the web fund tests**

Run: `.venv/bin/python manage.py test lamto.web.tests.test_fund_ops -v 2`
Expected: PASS. `test_verifier_signs_and_verifies` now confirms as the recorder and still redirects to `web:fund-home`.

- [ ] **Step 8: Correct the view docstring**

In `src/lamto/web/views/fund.py`, the `fund_verify` docstring claims a rule that no longer exists. Replace:

```python
    """Sign the verification of an unverified fund source (verifier != recorder,
    enforced by the domain service)."""
```

with:

```python
    """Confirm an unverified fund source. Managers sign off offline before data
    entry, so the recorder may confirm their own source; the balance only counts
    confirmed sources, which keeps this a real gate against typos."""
```

- [ ] **Step 9: Commit**

```bash
git add src/lamto/finance/fund.py src/lamto/web/views/fund.py \
        src/lamto/finance/tests/test_fund.py src/lamto/web/tests/test_fund_ops.py
git commit -m "feat(finance): allow a fund recorder to confirm their own source

Managers already meet and sign off offline before touching the software,
so the in-app recorder != verifier rule duplicated a control that had
already happened and forced a second account to exist to click a button.

The record -> confirm gesture survives: fund_balance still counts only
confirmed sources, so confirmation remains a real gate against typos.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Seed one management account

Reduces the pilot fixture to a single manager and updates every fixture consumer that reached for the second one. Depends on Task 1 — without it, `seed_opening_fund` would raise `PermissionDenied` the moment both roles collapse onto one membership.

**Files:**
- Modify: `src/lamto/testing/factories.py:219-227` (seeding loop), `:254-268` (`seed_opening_fund`), `:405-412`, `:498-520`
- Modify: `src/lamto/accounts/management/commands/seed_pilot.py:60-66`
- Modify: `src/lamto/api/tests/test_proposals.py:137`
- Modify: `src/lamto/api/tests/test_ledger.py:201`
- Modify: `src/lamto/web/tests/test_proposal_create.py:104`
- Modify: `tests/e2e/test_anchoring_disabled_mode.py:89-103`

**Interfaces:**
- Consumes: `verify_fund_source` from Task 1 (no longer rejects the recorder).
- Produces: `seed_pilot_world(...) -> PilotSeed` where `seed.management_users` and `seed.management_memberships` each contain exactly one element. Both stay `list` — a building may legitimately have several managers; what changed is that nothing requires it.

- [ ] **Step 1: Seed a single manager**

In `src/lamto/testing/factories.py`, replace the two-manager loop:

```python
    for number in (1, 2):
        user = get_user_model().objects.create_user(
            email=email(f"management-{number}"),
            password=password,
            display_name=f"Pilot Manager {number}",
        )
        membership = ManagementMembership.objects.create(user=user, building=building)
        seed.management_users.append(user)
        seed.management_memberships.append(membership)
```

with:

```python
    # One manager: sign-off happens offline, so the software needs one operator.
    # The lists stay lists — a building may have several staff, none of whom
    # exist to satisfy a dual-control rule.
    manager = get_user_model().objects.create_user(
        email=email("management-1"),
        password=password,
        display_name="Pilot Manager 1",
    )
    seed.management_users.append(manager)
    seed.management_memberships.append(
        ManagementMembership.objects.create(user=manager, building=building)
    )
```

- [ ] **Step 2: Make the opening fund record and confirm with one membership**

In the same file, `seed_opening_fund` unpacks two memberships. Replace:

```python
    recorder, verifier = seed.management_memberships
```

with:

```python
    (recorder,) = seed.management_memberships
```

and replace the final verification call:

```python
    verify_fund_source(entry, verifier)
```

with:

```python
    verify_fund_source(entry, recorder)
```

- [ ] **Step 3: Point the driver's second-manager call sites at the only manager**

Still in `src/lamto/testing/factories.py`, four `PilotDomainDriver` methods index `[1]`. Change each:

In `decide_proposal` (line ~408):

```python
        decided = decide_published_proposal(
            proposal, self.seed.management_users[0], proceed, "Approved for delivery"
        )
```

In `record_settlement_ack` (line ~500):

```python
        recorder = self.seed.management_memberships[0]
```

In `publish_settlement_entry` (line ~519):

```python
        publisher = self.seed.management_memberships[0]
```

In `attempt_publication` (line ~525):

```python
        publisher = self.seed.management_memberships[0]
```

- [ ] **Step 4: Fix the three tests that act as the second manager**

`src/lamto/api/tests/test_proposals.py:137`:

```python
        decide_proposal(proposal, self.seed.management_users[0], True, "Go")
```

`src/lamto/api/tests/test_ledger.py:201`:

```python
        acknowledger = self.seed.management_memberships[0]
```

`src/lamto/web/tests/test_proposal_create.py:104`:

```python
        manager = self.seed.management_memberships[0]
```

- [ ] **Step 5: Fix the anchoring-disabled e2e fund flow**

In `tests/e2e/test_anchoring_disabled_mode.py`, replace the comment and the two-membership unpack at lines 89-91:

```python
    # --- Fund flow (record then self-confirm) -----------------------------
    fund = get_or_create_fund(seed.building)
    (recorder,) = seed.management_memberships
```

and replace the verification call at line 103:

```python
    verify_fund_source(inflow, recorder)
```

- [ ] **Step 6: Print one login from the seed command**

In `src/lamto/accounts/management/commands/seed_pilot.py`, the idempotent-reuse branch lists two management logins. Replace:

```python
            self.stdout.write(
                "Idempotent reuse: no new rows created. Documented logins use prefix pilot-:\n"
                f"  pilot-management-1@{PILOT_EMAIL_DOMAIN}\n"
                f"  pilot-management-2@{PILOT_EMAIL_DOMAIN}\n"
                f"  pilot-resident@{PILOT_EMAIL_DOMAIN}\n"
            )
```

with:

```python
            self.stdout.write(
                "Idempotent reuse: no new rows created. Documented logins use prefix pilot-:\n"
                f"  pilot-management-1@{PILOT_EMAIL_DOMAIN}\n"
                f"  pilot-resident@{PILOT_EMAIL_DOMAIN}\n"
            )
```

The `for number, user in enumerate(seed.management_users, 1)` loop below it needs no change — it already prints whatever the seed created.

- [ ] **Step 7: Run every suite that touches the fixture**

Run: `.venv/bin/python manage.py test lamto.finance lamto.api lamto.web -v 2`
Expected: PASS. Watch specifically for `IndexError: list index out of range` — that means a `management_users[1]` or `management_memberships[1]` was missed. If one appears, `grep -rn "management_users\[1\]\|management_memberships\[1\]" src/ tests/` and fix it.

- [ ] **Step 8: Run the e2e suites**

Run: `.venv/bin/python -m pytest tests/e2e tests/isolation -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/lamto/testing/factories.py src/lamto/accounts/management/commands/seed_pilot.py \
        src/lamto/api/tests/test_proposals.py tests/e2e/test_anchoring_disabled_mode.py
git commit -m "feat(accounts): seed one management account

The second pilot manager existed only to satisfy the dual-control rule
removed in the previous commit. Fixture consumers that reached for
management_users[1] now use the only manager.

management_users and management_memberships stay lists: a building may
have several staff, none of whom exist to click a second button.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Kind allowlist on resident downloads

Adds the fail-closed guard **before** removing the one it replaces. `resident_can_download` currently relies on `version.variant != REDACTED → False` to guarantee no staff original escapes. Task 4 deletes the reference queries that guard sits above, and Task 5 deletes the variant itself. Landing the allowlist first means the guarantee is never absent, not even for one commit.

**Files:**
- Modify: `src/lamto/api/downloads.py:1-33` (docstring, `__all__`), `:85-88`
- Test: `src/lamto/api/tests/test_downloads.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `RESIDENT_DOWNLOADABLE_KINDS: frozenset[str]` in `lamto.api.downloads`, exported via `__all__`. `resident_can_download(user, version) -> bool` returns `False` for any `Document.Kind` outside that set before running any reference query.

- [ ] **Step 1: Write the failing test**

Append to the download-permission test class in `src/lamto/api/tests/test_downloads.py` (the class containing `test_original_staff_document_is_unreachable`):

```python
    def test_fund_contract_is_unreachable_even_inside_the_residents_building(self):
        """CONTRACT is fund-source evidence: staff-only, and not merely by
        accident of the reference queries. The allowlist must refuse it before
        any lookup runs."""
        from lamto.api.downloads import RESIDENT_DOWNLOADABLE_KINDS, resident_can_download
        from lamto.documents.models import Document

        resident = self.seed.residents[0]
        manager = self.seed.management_users[0]
        contract = self.seed.photo(Document.Kind.CONTRACT, manager, "fund-contract")

        self.assertNotIn(Document.Kind.CONTRACT, RESIDENT_DOWNLOADABLE_KINDS)
        self.assertIs(resident_can_download(resident, contract), False)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python manage.py test lamto.api.tests.test_downloads.ResidentDownloadTests.test_fund_contract_is_unreachable_even_inside_the_residents_building -v 2`

If that class name is wrong, find it with `grep -n "^class\|def test_original_staff_document_is_unreachable" src/lamto/api/tests/test_downloads.py` and use the class that contains that method.

Expected: FAIL with `ImportError: cannot import name 'RESIDENT_DOWNLOADABLE_KINDS'`.

- [ ] **Step 3: Add the allowlist constant**

In `src/lamto/api/downloads.py`, add the constant just below `DOWNLOAD_MAX_AGE`:

```python
DOWNLOAD_SALT = "lamto.api.download"
DOWNLOAD_MAX_AGE = 300  # spec 3.6: TTL <= 5 minutes

# Fail-closed outer gate. Every kind absent here is unreachable by residents no
# matter what the reference queries below do, so a bug in one of them cannot
# leak fund contracts, invoices, or completion reports.
RESIDENT_DOWNLOADABLE_KINDS = frozenset(
    {
        Document.Kind.REPORT_PHOTO,
        Document.Kind.BEFORE_PHOTO,
        Document.Kind.AFTER_PHOTO,
        Document.Kind.QUOTATION,
        Document.Kind.PAYMENT_PROOF,
    }
)
```

- [ ] **Step 4: Export it and apply it**

Add `"RESIDENT_DOWNLOADABLE_KINDS",` to the `__all__` tuple, keeping alphabetical order (after `"issue_download_token",`).

Then add the guard as the first statement of `resident_can_download`:

```python
def resident_can_download(user, version) -> bool:
    """True only for the caller's own report photos and the redacted
    published-ledger documents their building has published. Staff-only kinds
    are refused by RESIDENT_DOWNLOADABLE_KINDS before any lookup runs."""
    if version.document.kind not in RESIDENT_DOWNLOADABLE_KINDS:
        return False
    if version.document.kind == Document.Kind.REPORT_PHOTO:
```

Leave the rest of the function — including the existing `if version.variant != DocumentVersion.Variant.REDACTED: return False` line — exactly as it is. Both guards coexist until Task 4.

- [ ] **Step 5: Run the download tests to verify they pass**

Run: `.venv/bin/python manage.py test lamto.api.tests.test_downloads -v 2`
Expected: PASS, all tests including the new one and the existing `test_original_staff_document_is_unreachable`.

- [ ] **Step 6: Run the isolation suite**

Run: `.venv/bin/python -m pytest tests/isolation -v`
Expected: PASS. Cross-building refusals are unaffected — the allowlist narrows, never widens.

- [ ] **Step 7: Commit**

```bash
git add src/lamto/api/downloads.py src/lamto/api/tests/test_downloads.py
git commit -m "feat(api): gate resident downloads on a document-kind allowlist

resident_can_download relies on 'variant != REDACTED' to guarantee no
staff original escapes regardless of whether the reference queries are
exact. Removing redaction deletes that guarantee, so add its replacement
first: CONTRACT, INVOICE, and ACCEPTANCE_REPORT become unreachable by
construction, before any lookup runs.

Both guards coexist until the redacted variant is removed.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Drop paired redacted evidence from finance

The atomic core. Every fund source, quotation, and settlement proof stops requiring a redacted twin; the `*_redacted` columns go; residents are served originals. `DocumentVersion.variant` and `redacts` stay — Task 5 removes those. This task must land whole because `Settlement.transfer_redacted` is `NOT NULL`.

**Files:**
- Modify: `src/lamto/finance/models/ledger.py:32-48`, `src/lamto/finance/models/execution.py:19-26`
- Create: `src/lamto/finance/migrations/0024_*.py` (generated)
- Modify: `src/lamto/finance/fund.py:58-89`, `:130-190`
- Modify: `src/lamto/finance/proposals.py:34-77`, `:79-108`, `:110-131`, `:236-282`
- Modify: `src/lamto/finance/settlements.py:24-38`, `:41-58`, `:61-79`
- Modify: `src/lamto/finance/publication.py:38-60`
- Modify: `src/lamto/finance/selectors.py:26-28`, `:79-86`, `:228-275`
- Modify: `src/lamto/evidence/services.py:27-45`
- Modify: `src/lamto/web/staff_documents.py:42-125`, `:170-200`
- Modify: `src/lamto/web/forms/staff.py:118-135`, `:179-211`
- Modify: `src/lamto/web/views/fund.py:108-118`, `views/proposals.py:225-229`, `:270-273`, `views/settlements.py`, `views/exports.py:132-160`, `views/requests.py:43`
- Modify: `src/lamto/web/templates/web/staff/_fund_forms.html:9`, `proposal_create.html:13`, `settlement_detail.html:18-19`
- Modify: `src/lamto/api/downloads.py:78-125`, `src/lamto/api/serializers.py:344-376`, `src/lamto/api/views.py:386-395`
- Modify: `src/lamto/testing/factories.py:95-131`, `:180-190`, `:254-268`, `:480-514`, `:578-581`
- Test: all suites listed in the spec's Verification section

**Interfaces:**
- Consumes: the single-manager fixture from Task 2; `RESIDENT_DOWNLOADABLE_KINDS` from Task 3.
- Produces:
  - `upload_document(building, kind, uploader, file) -> DocumentVersion` (replaces `upload_document_pair`)
  - `document_options(building_id, kind) -> list[tuple[str, str, DocumentVersion]]` where value is `str(version.pk)` (replaces `document_pair_options`)
  - `selected_document(options, value) -> DocumentVersion | None` (replaces `selected_pair`)
  - `record_fund_source(fund, entry_type, amount_vnd, evidence, recorder, fund_entry_id=None, timestamp=None, source_key=None) -> MaintenanceFundEntry`
  - `record_transfer(proposal, membership, *, amount_vnd, payee_name, bank_reference, transfer_original) -> Settlement`
  - `record_acknowledgement(settlement, membership, *, ack_original, event_id) -> Settlement`
  - `document(building, kind, uploader, tag) -> DocumentVersion` and `PilotSeed.document(kind, uploader, tag=None)` (replace `document_pair`)
  - `ledger_entry_proof(entry)` returns key `"docs"` instead of `"redacted_docs"`
  - Snapshot entries in `ProposalVersion.snapshot["quotation_versions"]` become `{"version_id": int, "sha256": str}`

- [ ] **Step 1: Drop the redacted model fields**

In `src/lamto/finance/models/ledger.py`, delete the `evidence_redacted` field and the `evidence_redacted_hash` field from `MaintenanceFundEntry`, leaving:

```python
    evidence_original = models.ForeignKey(
        DocumentVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    evidence_original_hash = models.CharField(max_length=64, blank=True)
```

In `src/lamto/finance/models/execution.py`, delete the `transfer_redacted` and `ack_redacted` fields from `Settlement`, leaving `transfer_original`, `transfer_recorded_by`, `transfer_recorded_at`, `ack_kind`, `ack_original`, `ack_recorded_by`, `ack_recorded_at` in place.

- [ ] **Step 2: Generate and inspect the migration**

Run: `.venv/bin/python manage.py makemigrations finance`
Expected: creates `src/lamto/finance/migrations/0024_<autoname>.py` containing exactly four `migrations.RemoveField` operations — `maintenancefundentry.evidence_redacted`, `maintenancefundentry.evidence_redacted_hash`, `settlement.transfer_redacted`, `settlement.ack_redacted`.

Read the generated file. If it contains anything else — an `AlterField`, a `RunPython`, a prompt about a non-nullable field — stop and reconcile before continuing.

- [ ] **Step 3: Collapse the fund evidence validator**

In `src/lamto/finance/fund.py`, replace `_require_evidence_pair` with:

```python
def _require_evidence(evidence, building_id, *, lock=False):
    evidence_id = getattr(evidence, "pk", None)
    if evidence_id is None:
        raise ValidationError("Fund source evidence document is required.")
    queryset = DocumentVersion.objects.select_related("document").filter(pk=evidence_id)
    if lock:
        queryset = queryset.select_for_update()
    version = queryset.first()
    if version is None:
        raise ValidationError("Fund source evidence version must still exist.")
    if (
        version.document.building_id != building_id
        or version.scan_status != DocumentVersion.ScanStatus.CLEAN
    ):
        raise ValidationError(
            "Fund evidence must be clean, safe, and in the fund building."
        )
    return version
```

Then update `record_fund_source`. Change its signature:

```python
@transaction.atomic
def record_fund_source(
    fund,
    entry_type,
    amount_vnd,
    evidence,
    recorder,
    fund_entry_id=None,
    timestamp=None,
    source_key=None,
) -> MaintenanceFundEntry:
```

Replace the pair call:

```python
    evidence = _require_evidence(evidence, fund.building_id, lock=True)
```

Replace the source-key line, which keyed on the original's hash:

```python
    key = source_key or _source_key(entry_type, fund.pk, evidence.sha256)
```

And in the `MaintenanceFundEntry(...)` constructor, replace the four evidence kwargs with two:

```python
        evidence_original=evidence,
        evidence_original_hash=evidence.sha256,
```

Finally, in `_locked_entry`, drop `"evidence_redacted"` from the `select_related` tuple so it reads:

```python
        MaintenanceFundEntry.objects.select_related(
            "fund__building",
            "recorder__user",
            "evidence_original",
        ).get(pk=locked_id)
```

- [ ] **Step 4: Collapse the quotation validator and snapshot**

In `src/lamto/finance/proposals.py`, replace `_quotation_pairs` with:

```python
def _quotation_versions(building_id, quotation_versions, *, lock=False):
    supplied = list(quotation_versions or [])
    ids = [getattr(version, "pk", None) for version in supplied]
    if not ids or any(value is None for value in ids) or len(set(ids)) != len(ids):
        raise ValidationError("At least one distinct quotation is required.")
    queryset = DocumentVersion.objects.select_related("document").filter(pk__in=ids)
    if lock:
        queryset = queryset.select_for_update()
    versions = {version.pk: version for version in queryset}
    if len(versions) != len(ids):
        raise ValidationError("Every quotation version must still exist.")

    resolved = []
    for version_id in ids:
        version = versions[version_id]
        if (
            version.document.kind != version.document.Kind.QUOTATION
            or version.document.building_id != building_id
            or version.scan_status != DocumentVersion.ScanStatus.CLEAN
        ):
            raise ValidationError("Quotations must be clean, safe, and in the work-order building.")
        resolved.append(version)
    return resolved
```

Replace `_submission_snapshot`'s parameter `pairs` with `versions` and its quotation snapshot / payload hashes:

```python
def _submission_snapshot(proposal, amount_vnd, contractor_name, fund_code, purpose,
                         proposed_action, expected_schedule, versions, number):
    case = proposal.case
    quotation_snapshot = [
        {"version_id": version.pk, "sha256": version.sha256}
        for version in versions
    ]
```

and inside the same function:

```python
    evidence_payload = {
        "proposal_id": proposal.pk,
        "proposal_version": number,
        "record_id": proposal.pk,
        "building_id": proposal.building_id,
        "amount_vnd": amount_vnd,
        "proposal_snapshot_hash": payload_hash(snapshot),
        "quotation_original_hash": payload_hash([version.sha256 for version in versions]),
    }
```

In `build_proposal_evidence_payload`, rename the local and the call:

```python
    versions = _quotation_versions(proposal.building_id or proposal.case.building_id, quotation_versions)
    number = (ProposalVersion.objects.filter(proposal=proposal).aggregate(Max("number"))["number__max"] or 0) + 1
    _, evidence_payload = _submission_snapshot(
        proposal, amount_vnd, contractor_name.strip(), fund_code, purpose,
        proposed_action, expected_schedule, versions, number
    )
```

In `publish_proposal_version`, rename the local, and flatten the `ProposalDocument` creation:

```python
    versions = _quotation_versions(locked_proposal.building_id, quotation_versions, lock=True)
    previous = locked_proposal.versions.order_by("-number").first()
    number = (previous.number if previous else 0) + 1
    snapshot, evidence_payload = _submission_snapshot(
        locked_proposal, amount_vnd, contractor_name.strip(), fund_code.strip(), purpose.strip(),
        proposed_action.strip(), expected_schedule.strip(), versions, number
    )
```

```python
    ProposalDocument.objects.bulk_create(
        [
            ProposalDocument(proposal_version=version, document_version=document)
            for document in versions
        ]
    )
```

- [ ] **Step 5: Collapse the settlement proof validator**

In `src/lamto/finance/settlements.py`, replace `_require_proof_pair` with:

```python
def _require_proof(proof, building_id, *, lock=False):
    qs = DocumentVersion.objects.select_related("document").filter(pk=getattr(proof, "pk", None))
    if lock:
        qs = qs.select_for_update()
    version = qs.first()
    if (
        not version
        or version.document.kind != Document.Kind.PAYMENT_PROOF
        or version.document.building_id != building_id
        or version.scan_status != DocumentVersion.ScanStatus.CLEAN
    ):
        raise ValidationError("Settlement evidence requires a clean payment proof in the proposal building.")
    return version
```

Replace `build_settlement_evidence_payload` (the redacted SHA-256 keys go; the remaining names are renamed in Task 6):

```python
def build_settlement_evidence_payload(settlement):
    proposal = settlement.proposal
    return {"schema": "settlement.v1", "settlement_id": settlement.pk, "proposal_id": proposal.pk, "proposal_version": proposal.current_version.number, "amount_vnd": settlement.amount_vnd, "payee_name": settlement.payee_name, "bank_reference": normalize_bank_reference(settlement.bank_reference), "transfer_original_sha256": settlement.transfer_original.sha256, "ack_original_sha256": settlement.ack_original.sha256, "transfer_recorded_at": utc_rfc3339(settlement.transfer_recorded_at), "ack_recorded_at": utc_rfc3339(settlement.ack_recorded_at)}
```

In `record_transfer`, change the signature's last keyword and the body:

```python
def record_transfer(proposal, membership, *, amount_vnd, payee_name, bank_reference, transfer_original):
```

```python
    original = _require_proof(transfer_original, proposal.building_id, lock=True)
    settlement = Settlement.objects.create(proposal=proposal, amount_vnd=amount_vnd, payee_name=payee_name, bank_reference=normalize_bank_reference(bank_reference), transfer_original=original, transfer_recorded_by=actor, transfer_recorded_at=timezone.now())
```

In `record_acknowledgement`:

```python
def record_acknowledgement(settlement, membership, *, ack_original, event_id):
```

```python
    original = _require_proof(ack_original, settlement.proposal.building_id, lock=True)
    now = timezone.now()
    settlement.ack_original, settlement.ack_recorded_by, settlement.ack_recorded_at = original, actor, now
```

and its `save(update_fields=...)`:

```python
    settlement.save(update_fields=["ack_original", "ack_recorded_by", "ack_recorded_at", "outbox_event", "settled_at"])
```

- [ ] **Step 6: Drop the redacted keys from the anchored payload schemas**

In `src/lamto/evidence/services.py`, remove `"quotation_redacted_hash": "hash",` from the `PROPOSAL_CREATED` required dict, and remove `"transfer_redacted_sha256": "hash",` and `"ack_redacted_sha256": "hash",` from the `SETTLEMENT` required dict. The result:

```python
    EvidenceType.PROPOSAL_CREATED: ({
        "proposal_id": "id", "proposal_version": "positive_int", "record_id": "id",
        "amount_vnd": "money", "proposal_snapshot_hash": "hash",
        "quotation_original_hash": "hash",
    }, {"building_id": "id", "case_id": "id", "report_id": "id", "case_snapshot_hash": "hash",
        "report_snapshot_hash": "hash", "estimated_amount_vnd": "money",
        "photo_hash": "hash", "photo_hashes": "hashes"}),
    EvidenceType.SETTLEMENT: ({
        "schema": frozenset({"settlement.v1"}), "settlement_id": "id",
        "proposal_id": "id", "proposal_version": "positive_int", "amount_vnd": "money",
        "payee_name": "text", "bank_reference": "text",
        "transfer_original_sha256": "hash",
        "ack_original_sha256": "hash",
        "transfer_recorded_at": "timestamp", "ack_recorded_at": "timestamp",
    }, {}),
```

- [ ] **Step 7: Drop the redacted document integrity gates**

In `src/lamto/finance/publication.py`, replace `_collect_document_checks`:

```python
def _collect_document_checks(proposal, version, settlement, using="default"):
    from lamto.documents.models import DocumentVersion

    checks = []
    for item in version.snapshot.get("quotation_versions", []):
        quotation = DocumentVersion.objects.using(using).get(pk=item["version_id"])
        checks.append((quotation, item["sha256"], "QUOTATION"))
    checks.extend((
        (settlement.transfer_original, settlement.transfer_original.sha256, "SETTLEMENT_TRANSFER"),
        (settlement.ack_original, settlement.ack_original.sha256, "SETTLEMENT_ACK"),
    ))
    return checks
```

and drop the two redacted names from `publish_settlement_entry`'s `select_related`:

```python
    settlement = type(settlement).objects.select_for_update(of=("self",)).select_related(
        "proposal__current_version", "proposal__case__decision__report", "transfer_original",
        "ack_original", "outbox_event",
    ).get(pk=settlement.pk)
```

- [ ] **Step 8: Serve originals to residents and delete the variant guard**

In `src/lamto/api/downloads.py`, delete the line `if version.variant != DocumentVersion.Variant.REDACTED: return False` and repoint the two reference queries. The tail of `resident_can_download` becomes:

```python
    building_ids = list(active_occupancies(user).values_list("unit__building_id", flat=True))
    if not building_ids:
        return False
    if (
        version.document.kind == Document.Kind.QUOTATION
        and ProposalDocument.objects.filter(
            proposal_version__proposal__building_id__in=building_ids,
            proposal_version__proposal__status__in=[
                Proposal.Status.PUBLISHED,
                Proposal.Status.NOT_PROCEEDING,
                Proposal.Status.IN_PROGRESS,
                Proposal.Status.COMPLETED,
                Proposal.Status.CLOSED,
            ],
            document_version=version,
        ).exists()
    ):
        return True
    return (
        PublishedLedgerEntry.objects.filter(
            proposal__building_id__in=building_ids,
            proposal__current_version__outbox_event__status__in=SETTLED_STATUSES,
            settlement__outbox_event__status__in=SETTLED_STATUSES,
        )
        .filter(
            Q(settlement__transfer_original=version)
            | Q(settlement__ack_original=version)
        )
        .exists()
    )
```

Update the module docstring's second paragraph and the function docstring, both of which promise redacted documents:

```python
"""Signed resident document downloads (spec 3.6).

Django-hosted, short-TTL signed URLs — never presigned object-store URLs.
The token binds a version to the requesting user; redemption re-checks the
user and re-runs resident_can_download, so a token can never widen access.
"""
```

```python
def resident_can_download(user, version) -> bool:
    """True only for the caller's own report photos and the published-ledger
    documents their building has published. Staff-only kinds are refused by
    RESIDENT_DOWNLOADABLE_KINDS before any lookup runs."""
```

`DocumentVersion` may now be unused in this module — check with `grep -n "DocumentVersion" src/lamto/api/downloads.py` and drop it from the import if the only hit is the import line.

- [ ] **Step 9: Serve originals through the selectors and API**

In `src/lamto/finance/selectors.py`, change the prefetch in `resident_proposals`:

```python
    versions = ProposalVersion.objects.select_related("outbox_event").prefetch_related(
        "quotations"
    ).order_by("number", "pk")
```

change the `select_related` in the published-entry detail query:

```python
        .select_related(
            "case__decision__report",
            "settlement__transfer_original",
            "settlement__ack_original",
            "settlement__outbox_event",
            "proposal__current_version",
        )
```

and rewrite the document block in `ledger_entry_proof`:

```python
    docs = []
    for label, version_obj in (
        ("Transfer evidence", entry.settlement.transfer_original),
        ("Payee acknowledgement", entry.settlement.ack_original),
    ):
        if version_obj is not None:
            docs.append(
                {
                    "label": label,
                    "filename": version_obj.filename,
                    "sha256": version_obj.sha256,
                    "version_id": version_obj.pk,
                }
            )
```

with the returned key renamed:

```python
        "docs": docs,
```

In `src/lamto/api/views.py`, change the consumer at line 394 only — the outer `"redacted_documents"` key is the wire contract and stays until Task 7:

```python
                for doc in detail["docs"]
```

In `src/lamto/api/serializers.py`, flatten `get_versions`' nested loop:

```python
        for version in proposal.versions.all():
            documents = []
            for quotation in version.quotations.all():
                documents.append(
                    {
                        "id": quotation.pk,
                        "filename": quotation.filename,
                        "sha256": quotation.sha256,
                        "download_url": reverse(
                            "api:document-download",
                            args=[issue_download_token(request.user.pk, quotation.pk)],
                        ),
                    }
                )
```

- [ ] **Step 10: Collapse the staff upload helpers**

In `src/lamto/web/staff_documents.py`, replace `upload_document_pair` with:

```python
def upload_document(building, kind, uploader, file):
    """Upload one PDF through the ClamAV pipeline.

    Returns a clean DocumentVersion — the exact shape the proposal/fund
    evidence validators require. Raises ValidationError on any rejection or
    quarantine so views surface one uniform error.

    Storage is not transactional, so a blob already written to private storage
    is purged when the surrounding transaction rolls back.
    """
    written_blobs = []  # (storage_key, provider_version_id)
    try:
        with transaction.atomic():
            document = Document.objects.create(building=building, kind=kind)
            version = create_document_version(
                document,
                file,
                DocumentVersion.Variant.ORIGINAL,
                uploader,
                scan_with_clamav,
            )
            written_blobs.append((version.storage_key, version.provider_version_id or ""))
    except ValueError as error:  # DocumentUploadRejected/Quarantined both subclass ValueError
        for key, pvid in written_blobs:
            _delete_storage_blob(key, pvid)
        raise ValidationError(f"Evidence upload failed: {error}") from error
    return version
```

Note the `DocumentVersion.Variant.ORIGINAL` argument stays for now — Task 5 removes the parameter. Update the import at line 12 to drop `add_redacted_copy`:

```python
from lamto.documents.services import create_document_version
```

Replace `document_pair_options` and `selected_pair`:

```python
def document_options(building_id: int, kind: str):
    """Return clean document versions for a building and document kind.

    Each option is ``(value, label, version)`` where value is the version pk as
    a string. Scoped to the building.
    """
    versions = (
        DocumentVersion.objects.filter(
            document__building_id=building_id,
            document__kind=kind,
            scan_status=DocumentVersion.ScanStatus.CLEAN,
        )
        .select_related("document")
        .order_by("-pk")
    )
    return [(str(version.pk), version.filename, version) for version in versions]


def selected_document(options, value):
    """Resolve a document value against freshly rebuilt options; None if gone."""
    return next(
        (version for key, _, version in options if key == value),
        None,
    )
```

In `_referenced_document_ids`, replace the fund loop and the settlement tuple:

```python
    protected |= _docs_from_version_ids(
        MaintenanceFundEntry.objects.exclude(evidence_original_id=None).values_list(
            "evidence_original_id", flat=True
        )
    )
    settlement_fields = ("transfer_original_id", "ack_original_id")
```

In `_hard_delete_document`, drop the redacted-first pass and its comment. The docstring and body become:

```python
def _hard_delete_document(document_id: int) -> int:
    """Delete a Document and its versions, then purge storage blobs.

    Uses QuerySet.delete() (instance .delete() raises append-only).
    Returns the number of storage blobs successfully purged.
    """
    versions = list(
        DocumentVersion.objects.filter(document_id=document_id).values_list(
            "storage_key", "provider_version_id"
        )
    )
    DocumentVersion.objects.filter(document_id=document_id).delete()
    Document.objects.filter(pk=document_id).delete()
    purged = 0
    for key, pvid in versions:
        if _delete_storage_blob(key, pvid or ""):
            purged += 1
    return purged
```

- [ ] **Step 11: Collapse the staff forms**

In `src/lamto/web/forms/staff.py`:

`CreateProposalForm` — delete the `quotation_redacted` field, leaving `quotation_original`. Update the class docstring:

```python
class CreateProposalForm(forms.Form):
    """Management-entered proposal draft; the quotation uploads on prepare."""
```

`RecordFundSourceForm` — delete the `evidence_redacted` field, leaving `evidence_original`. Update the docstring:

```python
class RecordFundSourceForm(forms.Form):
    """Fund source draft; the evidence uploads on prepare."""
```

`RecordSettlementTransferForm` and `RecordSettlementAcknowledgementForm` — rename `proof_pair` to `proof` in both, in the field declaration and in `__init__`:

```python
class RecordSettlementTransferForm(forms.Form):
    amount_vnd = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={"class": "input"}))
    payee_name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"class": "input"}))
    bank_reference = forms.CharField(max_length=64, widget=forms.TextInput(attrs={"class": "input"}))
    proof = forms.ChoiceField(choices=(), widget=forms.Select(attrs={"class": "input"}))

    def __init__(self, *args, proof_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proof"].choices = [("", "Select evidence…"), *proof_choices]


class RecordSettlementAcknowledgementForm(forms.Form):
    event_id = forms.CharField(max_length=66, widget=forms.HiddenInput())
    proof = forms.ChoiceField(choices=(), widget=forms.Select(attrs={"class": "input"}))

    def __init__(self, *args, proof_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proof"].choices = [("", "Select evidence…"), *proof_choices]
```

- [ ] **Step 12: Update the staff views**

In `src/lamto/web/views/fund.py`, change the import at line 30 to `from lamto.web.staff_documents import upload_document` and replace the upload block in `fund_record`:

```python
            evidence = upload_document(
                building,
                Document.Kind.CONTRACT,
                request.user,
                record_form.cleaned_data["evidence_original"],
            )
            entry_type = record_form.cleaned_data["entry_type"]
            amount = record_form.cleaned_data["amount_vnd"]
            record_fund_source(fund, entry_type, amount, evidence, membership)
```

In `src/lamto/web/views/proposals.py`, change the import at line 38 to `from lamto.web.staff_documents import new_event_id, upload_document`, then replace both upload calls:

at line ~225:

```python
            original = upload_document(
                case.building, Document.Kind.QUOTATION, request.user,
                create_form.cleaned_data["quotation_original"],
            )
```

at line ~270:

```python
                original = upload_document(
                    membership.building, Document.Kind.QUOTATION, request.user,
                    form.cleaned_data["quotation_original"],
                )
```

In `src/lamto/web/views/settlements.py`, change the import at line 13:

```python
from lamto.web.staff_documents import document_options, new_event_id, selected_document
```

replace the body of `settlement_record_transfer` from the options line through the record call:

```python
    options = document_options(membership.building_id, Document.Kind.PAYMENT_PROOF)
    form = RecordSettlementTransferForm(request.POST or None, proof_choices=[(value, label) for value, label, _ in options])
    if request.method == "POST" and form.is_valid():
        proof = selected_document(options, form.cleaned_data["proof"])
        if proof is None:
            form.add_error("proof", "Selected evidence is no longer available.")
        else:
            try:
                settlement = record_transfer(proposal, membership, transfer_original=proof, **{key: form.cleaned_data[key] for key in ("amount_vnd", "payee_name", "bank_reference")})
```

replace the same region of `settlement_record_ack`:

```python
    options = document_options(membership.building_id, Document.Kind.PAYMENT_PROOF)
    initial = {"event_id": new_event_id()}
    form = RecordSettlementAcknowledgementForm(request.POST or None, initial=initial, proof_choices=[(value, label) for value, label, _ in options])
    if request.method == "POST" and form.is_valid():
        proof = selected_document(options, form.cleaned_data["proof"])
        if proof is None:
            form.add_error("proof", "Selected evidence is no longer available.")
        else:
            try:
                record_acknowledgement(settlement, membership, ack_original=proof, event_id=form.cleaned_data["event_id"])
```

and trim `settlement_detail`'s `select_related`:

```python
    settlement = get_object_or_404(Settlement.objects.select_related("proposal", "outbox_event", "transfer_original", "ack_original"), pk=pk, proposal__building_id=membership.building_id)
```

In `src/lamto/web/views/exports.py`, drop the redacted column from `_fund_entry_rows` — remove `"evidence_redacted_hash",` from the header list and `entry.evidence_redacted_hash,` from the row append.

In `src/lamto/web/views/requests.py`, delete line 43 entirely — `upload_document_pair` is imported there and never used. Verify first with `grep -n "upload_document_pair\|new_event_id" src/lamto/web/views/requests.py`; if `new_event_id` **is** used, keep it: `from lamto.web.staff_documents import new_event_id`.

- [ ] **Step 13: Update the staff templates**

`src/lamto/web/templates/web/staff/_fund_forms.html:9`:

```html
    <p class="hint">{% trans "Upload the source evidence (PDF). Amounts are integer VND." %}</p>
```

`src/lamto/web/templates/web/staff/proposal_create.html:13`:

```html
    <p class="hint">{% trans "Upload the quotation (PDF). Amounts are integer VND." %}</p>
```

`src/lamto/web/templates/web/staff/settlement_detail.html:18-19`:

```html
  <p>Transfer: {{ settlement.transfer_original.filename }}</p>
  <p>Acknowledgement ({{ settlement.get_ack_kind_display }}): {% if settlement.ack_original %}{{ settlement.ack_original.filename }}{% else %}Pending — <a href="{% url 'web:settlement-record-ack' settlement.pk %}">record acknowledgement</a>{% endif %}</p>
```

- [ ] **Step 14: Collapse the fixture factories**

In `src/lamto/testing/factories.py`, replace the module-level `document_pair` function with:

```python
def document(building, kind, uploader, tag: str):
    content = f"{tag}-content".encode()
    key = f"pilot/{secrets.token_hex(6)}/{tag}"
    write_bytes(key, content)
    return DocumentVersion.objects.create(
        document=Document.objects.create(building=building, kind=kind),
        version=1,
        variant=DocumentVersion.Variant.ORIGINAL,
        storage_key=key,
        provider_version_id=key,
        filename=f"{tag}.pdf",
        content_type="application/pdf",
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        uploader=uploader,
    )
```

Replace the `PilotSeed.document_pair` method with:

```python
    def document(self, kind, uploader, tag: str | None = None):
        return document(self.building, kind, uploader, tag or self._tag("doc"))
```

In `seed_opening_fund`, replace the pair call and the `record_fund_source` call:

```python
    evidence = seed.document(Document.Kind.CONTRACT, recorder.user, "fund-opening")
    entry = record_fund_source(
        fund,
        MaintenanceFundEntry.EntryType.OPENING_BALANCE,
        amount_vnd,
        evidence,
        recorder,
    )
```

In `PilotDomainDriver.record_settlement_transfer`:

```python
        proof = self.seed.document(
            Document.Kind.PAYMENT_PROOF, recorder.user, "settlement-transfer"
        )
        settlement = record_transfer(
            self.seed.proposal or self._ctx["proposal"],
            recorder,
            amount_vnd=amount_vnd,
            payee_name="Pilot Contractor Co",
            bank_reference=f"BANK-PILOT-{new_event_id()[-12:]}",
            transfer_original=proof,
        )
```

In `PilotDomainDriver.record_settlement_ack`:

```python
        proof = self.seed.document(
            Document.Kind.PAYMENT_PROOF, recorder.user, "settlement-ack"
        )
        settlement = record_acknowledgement(
            settlement,
            recorder,
            ack_original=proof,
            event_id=new_event_id(),
        )
```

In `open_latest_ledger_entry`, rename the local and its lambda so the pilot driver stops speaking of redaction:

```python
        documents_ok = bool(
            entry.resident_payload.get("document_hashes")
            or entry.settlement.transfer_original_id
        )
        return SimpleNamespace(
            actual_cost_vnd=entry.actual_cost_vnd,
            status=display if status != "UNCHECKED" else "Record verified",
            has_documents=lambda: documents_ok,
            current_fund_balance_vnd=self.fund_balance(),
            entry=entry,
            effective_integrity_status=status,
        )
```

Also check whether `publish_proposal` (around line 390) calls `self.seed.document_pair` for the quotation; if it does, change it to `self.seed.document(...)` and pass the single version to `quotation_versions=[...]`.

- [ ] **Step 15: Update the remaining test call sites**

Run `grep -rn "document_pair\|_redacted\|redacted\b" --include="*.py" src/ tests/ | grep -v migrations` and work through every hit. Expected edits:

- `src/lamto/finance/tests/test_fund.py` — in `setUp`, replace the pair line with `self.evidence = self.seed.document(Document.Kind.CONTRACT, self.recorder.user, "fund")`, deleting `self.original` / `self.redacted`. Then in both tests written in Task 1, replace the two evidence positionals `self.original, self.redacted` with the single `self.evidence`, so each call reads `record_fund_source(self.fund, MaintenanceFundEntry.EntryType.INFLOW, <amount>, self.evidence, self.recorder)`.
- `src/lamto/finance/tests/test_settlements.py`, `test_proposals.py`, `test_standalone_proposals.py` — single documents, no pairs.
- `src/lamto/documents/tests/test_versions.py` — leave alone; Task 5 owns it.
- `src/lamto/api/tests/test_ledger.py`, `test_downloads.py`, `test_proposals.py` — assert against originals.
- `src/lamto/web/tests/test_fund_ops.py:186` — delete the `"evidence_redacted"` POST field. `:233-236` — single document.
- `src/lamto/web/tests/test_proposal_create.py` — delete the `quotation_redacted` POST field.
- `tests/isolation/test_cross_building_access.py:463-476` — `entry_b.settlement.transfer_original`, comment reads "A ledger document from B's published expenditure."
- `tests/e2e/test_normal_flow.py:58,88` — `assert ledger.has_documents()`.
- `tests/e2e/test_anchoring_disabled_mode.py:92-101` — single document.
- `src/lamto/evidence/tests/` — drop redacted keys from any hand-built payload.

- [ ] **Step 16: Migrate and run the full Python suite**

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto -v 2
.venv/bin/python -m pytest tests -v
```

Expected: PASS. Then confirm nothing was missed:

```bash
grep -rn "redacted" --include="*.py" --include="*.html" src/ tests/ | grep -v migrations | grep -v log_filters | grep -v "settings.py"
```

Expected: no hits. The surviving `redact` references in `config/log_filters.py` and `config/settings.py` are about scrubbing download tokens from logs and are unrelated — leave them.

- [ ] **Step 17: Commit**

```bash
git add -A
git commit -m "feat(finance): drop paired redacted evidence

Every fund source, quotation, and settlement proof required a distinct
redacted twin, doubling each upload so residents could be served a
censored copy. Residents now get the original.

Drops evidence_redacted(_hash) from fund entries and transfer_redacted /
ack_redacted from settlements, removes the redacted hashes from the
anchored payload schemas, and repoints resident downloads at the
originals. The kind allowlist added earlier is now the sole outer gate.

DocumentVersion.variant and .redacts survive this commit; they go next.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Delete the REDACTED variant from documents

Removes the concept itself, now that nothing depends on it.

**Files:**
- Modify: `src/lamto/documents/models.py:36-60`
- Create: `src/lamto/documents/migrations/0005_*.py` (generated)
- Modify: `src/lamto/documents/services.py:72-81`, `:210-225`, `:303-325`, `:341-358`
- Modify: `src/lamto/documents/management/commands/backup_objects.py:72`
- Modify: `src/lamto/web/staff_documents.py`, `src/lamto/maintenance/cases.py:40`, `src/lamto/maintenance/reporting.py:69`, `src/lamto/testing/factories.py`
- Test: `src/lamto/documents/tests/test_versions.py`, `test_access.py`, `test_quarantine.py`

**Interfaces:**
- Consumes: everything from Task 4.
- Produces: `create_document_version(document, uploaded_file, uploader, scanner, *, allow_resident_occupancy=False) -> DocumentVersion` — the `variant` positional and the `_redacts` keyword are gone. `DocumentVersion` has no `variant` or `redacts` attribute and `DocumentVersion.Variant` no longer exists.

- [ ] **Step 1: Write the failing test for the version counter**

`test_versions.py`'s first two tests are the redaction ones, and they are what currently exercises the 1 → 2 increment. Deleting them would leave the counter with no coverage, so replace both with a direct test. In `src/lamto/documents/tests/test_versions.py`, delete `test_original_and_redacted_bytes_get_distinct_immutable_hashes` and `test_redacted_copy_rejects_identical_bytes_before_persistence`, and add:

```python
    def test_a_document_accumulates_versions_and_hashes_are_immutable(self):
        """One upload creates one version — but a document is not capped at one.
        A genuine later revision still inserts version 2."""
        uploader, building = self.make_operator_and_building()
        document = Document.objects.create(building=building, kind=Document.Kind.QUOTATION)
        first_bytes = b"%PDF-1.7\\nfirst-quotation"
        second_bytes = b"%PDF-1.7\\ncorrected-quotation"

        first = create_document_version(
            document,
            SimpleUploadedFile("quote.pdf", first_bytes, content_type="application/pdf"),
            uploader,
            scanner=lambda _: True,
        )
        second = create_document_version(
            document,
            SimpleUploadedFile("quote-v2.pdf", second_bytes, content_type="application/pdf"),
            uploader,
            scanner=lambda _: True,
        )

        self.assertEqual(first.version, 1)
        self.assertEqual(second.version, 2)
        self.assertEqual(first.sha256, hashlib.sha256(first_bytes).hexdigest())
        self.assertNotEqual(first.sha256, second.sha256)
        self.assertNotEqual(first.storage_key, second.storage_key)
        self.assertEqual(first.provider_version_id, first.storage_key)

        first.sha256 = "0" * 64
        with self.assertRaises(ValueError):
            first.save()
```

Update that file's import block to drop `add_redacted_copy`:

```python
from lamto.documents.services import (
    DocumentStorageError,
    _store,
    create_document_version,
)
```

and drop the `DocumentVersion.Variant.ORIGINAL` argument from the remaining `create_document_version` call in `test_database_trigger_rejects_version_update_and_delete`:

```python
        version = create_document_version(
            Document.objects.create(building=building, kind=Document.Kind.QUOTATION),
            SimpleUploadedFile("quote.pdf", b"%PDF-1.7\\nprivate", content_type="application/pdf"),
            uploader,
            scanner=lambda _: True,
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python manage.py test lamto.documents.tests.test_versions -v 2`
Expected: FAIL with `ImportError` on `add_redacted_copy`, or `TypeError` about the argument count.

- [ ] **Step 3: Remove the model fields**

In `src/lamto/documents/models.py`, delete the `Variant` inner class, the `variant` field, and the `redacts` field from `DocumentVersion`. Keep `version`, the `document_version_once` constraint, and everything else exactly as it is:

```python
class DocumentVersion(InsertOnlyModel):
    class ScanStatus(models.TextChoices):
        CLEAN = "CLEAN", "Clean"

    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    storage_key = models.CharField(max_length=512, unique=True)
    provider_version_id = models.CharField(max_length=512)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=127)
    byte_size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    scan_status = models.CharField(max_length=16, choices=ScanStatus.choices, default=ScanStatus.CLEAN)
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["document", "version"], name="document_version_once")
        ]
```

- [ ] **Step 4: Generate and inspect the migration**

Run: `.venv/bin/python manage.py makemigrations documents`
Expected: `src/lamto/documents/migrations/0005_<autoname>.py` with exactly two `RemoveField` operations — `documentversion.variant` and `documentversion.redacts`.

Read the file. Anything else means a model edit went wrong.

- [ ] **Step 5: Delete add_redacted_copy and simplify create_document_version**

In `src/lamto/documents/services.py`, delete the whole `add_redacted_copy` function.

Change `create_document_version`'s signature and its resident-occupancy guard — the `variant == ORIGINAL` clause is now implied:

```python
def create_document_version(document, uploaded_file, uploader, scanner, *, allow_resident_occupancy=False) -> DocumentVersion:
    try:
        membership = require_management(uploader, document.building_id)
    except PermissionDenied:
        membership = None
    occupancy = None
    if membership is None:
        if not (
            allow_resident_occupancy
            and document.kind == Document.Kind.REPORT_PHOTO
        ):
            raise PermissionDenied("Document uploader does not belong to this building.")
```

and drop the two removed kwargs from the `DocumentVersion.objects.create(...)` call:

```python
            version = DocumentVersion.objects.create(
                document=locked_document,
                version=next_version,
                storage_key=storage_key,
                provider_version_id=provider_version_id,
                filename=metadata["filename"],
                content_type=metadata["content_type"],
                byte_size=metadata["byte_size"],
                sha256=digest.hexdigest(),
                uploader=uploader,
            )
```

Update `create_resident_report_photo` to match:

```python
    return create_document_version(
        document,
        uploaded_file,
        resident,
        scanner,
        allow_resident_occupancy=True,
```

- [ ] **Step 6: Update the remaining variant references**

Run `grep -rn "Variant\|variant" --include="*.py" src/ tests/ | grep -v migrations | grep -v invariant` and fix each:

- `src/lamto/web/staff_documents.py` — drop `DocumentVersion.Variant.ORIGINAL` from the `create_document_version` call in `upload_document`, and drop the `variant__in=(...)` filter from `document_options`.
- `src/lamto/maintenance/cases.py:40` and `reporting.py:69` — drop `variant=DocumentVersion.Variant.ORIGINAL` from those filter/create calls.
- `src/lamto/testing/factories.py` — drop `variant=DocumentVersion.Variant.ORIGINAL` from both `document()` and `photo()`.
- `src/lamto/documents/management/commands/backup_objects.py:72` — delete the `"variant": version.variant,` manifest key.
- `src/lamto/documents/tests/test_access.py`, `test_quarantine.py`, `src/lamto/api/tests/test_report_photos.py`, `src/lamto/finance/tests/*` — drop the argument from every `create_document_version` call.

- [ ] **Step 7: Migrate and run the full suite**

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto -v 2
.venv/bin/python -m pytest tests -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(documents): delete the REDACTED variant and redacts link

With paired evidence gone, variant could only ever hold ORIGINAL and
redacts had nothing to point at. Both are dead schema.

The version counter is untouched: create_document_version still locks
the Document and computes Max(version) + 1, so a genuine later revision
still inserts version 2. add_redacted_copy was merely the only caller
that passed an existing Document; its tests were also the only coverage
of the increment, so a direct test replaces them.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Drop the `_original` suffix from evidence fields

Purely mechanical. "Original" only meant something in contrast to "redacted"; with the contrast gone the suffix is noise. A reviewer could reject this task and keep everything before it.

**Files:**
- Modify: `src/lamto/finance/models/ledger.py`, `models/execution.py`
- Create: `src/lamto/finance/migrations/0025_*.py` (generated)
- Modify: `src/lamto/finance/fund.py`, `settlements.py`, `publication.py`, `selectors.py`
- Modify: `src/lamto/evidence/services.py`
- Modify: `src/lamto/web/staff_documents.py`, `views/settlements.py`, `views/exports.py`, `views/fund.py`, `views/proposals.py`, `forms/staff.py`
- Modify: `src/lamto/web/templates/web/staff/settlement_detail.html`
- Modify: `src/lamto/testing/factories.py` and the test suites

**Interfaces:**
- Consumes: everything from Task 5.
- Produces: `MaintenanceFundEntry.evidence`, `MaintenanceFundEntry.evidence_hash`, `Settlement.transfer`, `Settlement.ack`. `record_transfer(..., *, transfer)` and `record_acknowledgement(..., *, ack)`. Anchored payload keys `quotation_hash`, `transfer_sha256`, `ack_sha256`.

- [ ] **Step 1: Rename the model fields**

In `src/lamto/finance/models/ledger.py`, rename `evidence_original` → `evidence` and `evidence_original_hash` → `evidence_hash` on `MaintenanceFundEntry`.

In `src/lamto/finance/models/execution.py`, rename `transfer_original` → `transfer` and `ack_original` → `ack` on `Settlement`.

- [ ] **Step 2: Generate the migration as renames, not drop-and-add**

Run: `.venv/bin/python manage.py makemigrations finance`

Django will ask, for each field, whether it was renamed. **Answer yes to all four.** Expected result: `0025_<autoname>.py` containing four `migrations.RenameField` operations and no `RemoveField`/`AddField` pair.

If the generated file contains `RemoveField` + `AddField` instead, delete it, re-run, and answer the prompts correctly. Drop-and-add would discard the evidence links.

- [ ] **Step 3: Update every reference**

Run `grep -rn "evidence_original\|transfer_original\|ack_original" --include="*.py" --include="*.html" src/ tests/ | grep -v migrations` and rename each hit. The renames are exact-string:

- `evidence_original` → `evidence`, `evidence_original_hash` → `evidence_hash`, `evidence_original_id` → `evidence_id`
- `transfer_original` → `transfer`, `transfer_original_id` → `transfer_id`
- `ack_original` → `ack`, `ack_original_id` → `ack_id`

Two form fields keep a name that no longer needs the suffix — in `src/lamto/web/forms/staff.py` rename `CreateProposalForm.quotation_original` → `quotation` and `RecordFundSourceForm.evidence_original` → `evidence`, then update `views/proposals.py` (`cleaned_data["quotation"]`, both call sites) and `views/fund.py` (`cleaned_data["evidence"]`). Any test posting those form fields changes with them.

- [ ] **Step 4: Rename the anchored payload keys**

In `src/lamto/evidence/services.py`, rename in `EVIDENCE_PAYLOAD_SCHEMAS`: `quotation_original_hash` → `quotation_hash`, `transfer_original_sha256` → `transfer_sha256`, `ack_original_sha256` → `ack_sha256`.

In `src/lamto/finance/proposals.py`, `_submission_snapshot` emits `quotation_hash`.

In `src/lamto/finance/settlements.py`, `build_settlement_evidence_payload` emits `transfer_sha256` and `ack_sha256`.

- [ ] **Step 5: Migrate and run the full suite**

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test lamto -v 2
.venv/bin/python -m pytest tests -v
```

Expected: PASS. Then confirm the suffix is gone:

```bash
grep -rn "_original" --include="*.py" --include="*.html" src/ tests/ | grep -v migrations
```

Expected: no hits.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(finance): drop the _original suffix from evidence fields

'Original' only meant something in contrast to 'redacted'. With the
contrast gone the suffix is noise: Settlement.transfer, Settlement.ack,
MaintenanceFundEntry.evidence and .evidence_hash.

Migrated as RenameField so the evidence links survive.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Rename the resident API documents field

The wire contract still says `redacted_documents`. This is the only task that touches Dart.

**Files:**
- Modify: `docs/api/openapi-v1.yaml:1299`, `:1316`, and the `RedactedDocument` schema
- Modify: `src/lamto/api/serializers.py:134-138`, `:178`
- Modify: `src/lamto/api/views.py:386`
- Regenerate: `app/packages/lamto_api/**`
- Modify: `app/lib/features/ledger/ledger_detail_screen.dart:162-167`, `:281`
- Modify: `app/lib/l10n/app_en.arb:151`, `app_vi.arb:152`
- Modify: `app/test/ledger_screens_test.dart`, `app/test/proposals_test.dart`

**Interfaces:**
- Consumes: `ledger_entry_proof(entry)["docs"]` from Task 4.
- Produces: JSON field `documents` on `LedgerEntryDetail`; schema `LedgerDocument`; Dart `entry.documents` of type `BuiltList<LedgerDocument>`.

- [ ] **Step 1: Rename the serializer**

In `src/lamto/api/serializers.py`, rename the class:

```python
class LedgerDocumentSerializer(serializers.Serializer):
    label = serializers.CharField()
    filename = serializers.CharField()
    sha256 = serializers.CharField()
    download_url = serializers.CharField()
```

and its use at line 178:

```python
    documents = LedgerDocumentSerializer(many=True)
```

In `src/lamto/api/views.py:386`, rename the emitted key:

```python
            "documents": [
```

- [ ] **Step 2: Regenerate the OpenAPI document**

The repo keeps `docs/api/openapi-v1.yaml` as the generator input. Regenerate it from the DRF schema if the project has a command for it — check with `grep -rn "spectacular" ops/ .github/ app/tool/`. If there is no command, hand-edit:

- rename the `RedactedDocument` schema key to `LedgerDocument`
- in `LedgerEntryDetail.properties`, rename `redacted_documents` to `documents` and point its `items.$ref` at `#/components/schemas/LedgerDocument`
- in `LedgerEntryDetail.required`, replace `- redacted_documents` with `- documents`, keeping the list alphabetical (it moves up, between `- corrections` and `- id`)

- [ ] **Step 3: Regenerate the Dart client**

```bash
cd app
chmod +x tool/generate_api.sh tool/check_api_generated.sh
./tool/generate_api.sh
```

Expected: `app/packages/lamto_api/lib/src/model/redacted_document.dart` and `.g.dart` are replaced by `ledger_document.dart` / `.g.dart`; `serializers.dart`, `serializers.g.dart`, `lamto_api.dart`, `ledger_entry_detail.dart` and the `doc/` and `test/` folders update to match.

If the old `redacted_document*` files linger, delete them by hand — the generator does not always remove renamed outputs:

```bash
rm -f packages/lamto_api/lib/src/model/redacted_document.dart \
      packages/lamto_api/lib/src/model/redacted_document.g.dart \
      packages/lamto_api/test/redacted_document_test.dart \
      packages/lamto_api/doc/RedactedDocument.md
```

- [ ] **Step 4: Update the Flutter screen**

In `app/lib/features/ledger/ledger_detail_screen.dart`, replace the document block at lines 162-169:

```dart
              child: entry.documents.isEmpty
                  ? null
                  : Column(
                      children: [
                        for (final doc in entry.documents)
                          _DocumentTile(document: doc),
                      ],
                    ),
```

and the field type at line 281:

```dart
  final LedgerDocument document;
```

- [ ] **Step 5: Update both localisation files**

`app/lib/l10n/app_en.arb:151`:

```json
  "ledgerDocuments": "Documents",
```

`app/lib/l10n/app_vi.arb:152`:

```json
  "ledgerDocuments": "Tài liệu",
```

Then regenerate: `flutter gen-l10n` from `app/`, or `flutter pub get` if the project generates on build. Confirm `app/lib/l10n/app_localizations_vi.dart` now reads `String get ledgerDocuments => 'Tài liệu';`.

- [ ] **Step 6: Update the Dart tests**

Run `grep -rn "redacted\|Redacted" app/lib app/test` and rename each hit to the `documents` / `LedgerDocument` names. Both `app/test/ledger_screens_test.dart` and `app/test/proposals_test.dart` build fixture entries with the old field.

- [ ] **Step 7: Verify the app**

```bash
cd app
./tool/check_api_generated.sh
flutter analyze
flutter test
```

Expected: all three pass. `check_api_generated.sh` failing means the committed client does not match the spec — re-run `./tool/generate_api.sh` and commit the result.

- [ ] **Step 8: Run the Python API tests**

Run: `.venv/bin/python manage.py test lamto.api -v 2`
Expected: PASS. Any test asserting `redacted_documents` in a response body changes to `documents`.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(api): rename the ledger redacted_documents field to documents

The resident contract still said redacted_documents and RedactedDocument
after redaction was removed. Renamed to documents / LedgerDocument, Dart
client regenerated, and both .arb files updated: 'Redacted documents' ->
'Documents', 'Tai lieu (da che thong tin)' -> 'Tai lieu'.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Correct the pilot runbook and run the acceptance pass

The runbook documents software that does not exist: a payment maker-checker separation deleted back in migration `0012_delete_approvaldecision`, plus the redaction this branch removed. This task fixes it and then proves the whole branch on a fresh database.

**Files:**
- Modify: `ops/pilot-runbook.md:6-8`, `:36-53`, `:100-120`
- Modify: `ops/acceptance-report-template.md` (only if it names two managers or redacted docs)

**Interfaces:**
- Consumes: everything.
- Produces: no code.

- [ ] **Step 1: Correct the participants table**

In `ops/pilot-runbook.md`, replace the participants table and the paragraph under it:

```markdown
| Participant | Responsibility |
|-------------|----------------|
| Resident | Report, inspect published ledger |
| Management user | Triage, create the work order and proposal, start and complete work, record and confirm payment, publish the ledger, and verify hashes and balances |

One Management user performs the whole staff path. Managers meet, review, and
sign off offline before data entry; the application records the agreed result
rather than re-running the review. A building may have several Management
users, but no step requires a second person.
```

- [ ] **Step 2: Correct the procedure**

Replace steps 5, 6, 8 and 9 of the "Procedure (normal path)" list:

```markdown
5. A manager accepts work and records payment evidence.
6. The same manager confirms the payment record.
7. Confirm chain/outbox events (`confirm_all_chain_events` in tests; worker in live).
8. A manager signs the publication snapshot; finalize after confirmation.
9. Resident opens latest ledger entry: actual cost, **Record verified**, and the
   original supporting documents.
```

- [ ] **Step 3: Correct the preconditions and onboarding example**

At line ~16, "local dual-control still permits work start" becomes "a local signature still permits work start".

In the `onboard_building` example, drop the second manager:

```bash
  --managers "manager1@example.vn"
```

and in the paragraph below it, replace "record + verify the fund opening balance" with "record and confirm the fund opening balance".

- [ ] **Step 4: Check the acceptance template**

Run `grep -n "redact\|verifier\|maker\|checker\|two\b" ops/acceptance-report-template.md`. Fix any line that names a second manager or redacted documents. If there are no hits, leave the file alone.

- [ ] **Step 5: Rebuild the database from scratch**

The migrations in this branch are destructive by design, so prove them on an empty database rather than an incrementally-migrated one.

```bash
dropdb -h 127.0.0.1 -U lamto_owner lamto
createdb -h 127.0.0.1 -U lamto_owner lamto
psql -h 127.0.0.1 -U lamto_owner -d lamto -f ops/postgres-init.sql
.venv/bin/python manage.py migrate
PILOT_ALLOW_FIXTURES=1 .venv/bin/python manage.py seed_pilot --fixture
```

Expected: `migrate` applies cleanly with no prompts; `seed_pilot` prints exactly one management login and one resident login.

- [ ] **Step 6: Run every suite**

```bash
.venv/bin/python manage.py test lamto -v 2
.venv/bin/python -m pytest tests -v
.venv/bin/python manage.py tenant_integrity
cd app && ./tool/check_api_generated.sh && flutter analyze && flutter test
```

Expected: all pass; `tenant_integrity` exits 0.

- [ ] **Step 7: Walk the normal path manually**

Log in as the seeded manager and confirm, in order:

1. Fund → record an inflow with one PDF upload; the form shows one file field.
2. The entry lands in "awaiting verification" and the balance has **not** moved.
3. Confirm the same entry as the same manager; the balance moves by the recorded amount.
4. Create a proposal with one quotation upload; publish it.
5. Complete the work, record transfer and acknowledgement, publish the ledger entry.
6. Log in as the seeded resident, open the published ledger entry, and download a
   supporting document. Confirm the bytes are the original — the file downloaded
   matches the one uploaded in step 4 or 5, and the UI label reads "Tài liệu".

Record the outcome in `ops/acceptance-report-template.md`.

- [ ] **Step 8: Commit**

```bash
git add ops/
git commit -m "docs(ops): correct the pilot runbook for one manager

The runbook described a payment maker-checker separation deleted in
migration 0012 and resident-facing redacted documents removed in this
branch. Neither existed in the code it documents.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

**If a task's grep turns up more hits than the plan lists**, fix them — the plan was written against a snapshot and the file line numbers drift as earlier tasks land. Line numbers are navigation hints, not assertions.

**Never make a migration non-destructive out of caution.** The database is disposable and the spec is explicit about it. A data migration added "just in case" is a bug in this branch.

**The `redact` references in `src/lamto/config/log_filters.py` and `src/lamto/config/settings.py` stay.** They scrub signed download tokens out of log lines and have nothing to do with document redaction.
