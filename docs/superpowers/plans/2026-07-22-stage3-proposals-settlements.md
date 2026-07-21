# Stage 3: Proposals & Settlements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proposals carry the seven spec fields, exist standalone (happy path 2), and anchor on publish with the platform key; payments become two-evidence Settlements (transfer + payee acknowledgement) that anchor on completion; anchoring shrinks to exactly those two artifact types; the per-staff wallet layer is deleted.

**Architecture:** Expand→cutover→contract again. Task 1 adds platform-key signing beside the wallet path. Task 2 reshapes proposals (fields, standalone, publish→anchor, decision, progress, ratings). Task 3 replaces acceptance+payment+verification with `Settlement`. Task 4 takes the fund ledger and publication fully off-chain and reduces integrity to the two anchored types. Task 5 deletes the wallet layer (models, registration, staff signing UI, typed-data builders). Task 6 aligns e2e/app and verifies. The `EvidenceRegistry` contract is untouched: settlement reuses reserved `eventType` value **10** (contract accepts 1..11).

**Tech Stack:** Django 5 + pytest-django + Postgres 17, `eth_account` EIP-712 signing (already a dependency via the worker), Foundry/Besu `EvidenceRegistry` (unchanged), OpenAPI YAML + dart-dio client, Flutter app.

**Spec:** `docs/superpowers/specs/2026-07-21-two-role-rebuild-design.md` §3, §5 (+§7 stage 3, §2 standalone-rating rule).

## Global Constraints

- Blockchain anchors exactly two artifact types: **published proposal versions** (`EvidenceType` value 1) and **settlement records** (value 10). Nothing else queues outbox events after this stage.
- Never on-chain: photos, personal data, AI results, comments, progress updates, Management reasons, information requests, resident ratings.
- A payment is settled only when Management has transfer evidence AND the payee acknowledgement is recorded. `ack_kind` = `MANAGEMENT_UPLOAD` now; `PAYEE_LINK` is a reserved enum value with no behavior.
- Published proposal versions are immutable (existing `InsertOnlyModel` pattern); a material change publishes a new version, anchored again; all versions stay visible.
- Evidence signing uses the platform key (`PLATFORM_SIGNER_PRIVATE_KEY` env); Management identity is recorded off-chain in audit + model fields. Residents/payees need no wallets.
- Standalone proposal rating: any resident with active occupancy in the building, one each, binary; the proposal closes 14 days after completion or immediately after settlement if later (`RATING_WINDOW_DAYS` from `lamto.maintenance.cases`).
- Fund ledger, `/fund/series`, fund charts, and dual-control fund record/verify all REMAIN — off-chain.
- Test environment (once per shell): `docker compose up -d && set -a; . ./.env; set +a && export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner`. Module tests `uv run pytest src/lamto/<app> -q`; full suite `uv run pytest src/lamto tests -q`. Stale test DB: `docker exec lamto-db-1 psql -U lamto_bootstrap -d postgres -c "DROP DATABASE IF EXISTS test_lamto;"`.
- No data preservation; new migrations only. Never edit existing migrations.
- Hard-coded payload/hash expectations in tests are always recomputed from the builders, never pasted.

---

### Task 1: Platform-key signing foundation (expand)

**Files:**
- Modify: `src/lamto/evidence/signatures.py` (add two functions), `src/lamto/evidence/models.py` (outbox `signer_address`; `signer_wallet` becomes `null=True, blank=True`), `src/lamto/evidence/services.py` (add `queue_platform_event`), `src/lamto/evidence/worker.py` (`_record_matches_event` accepts either identity), `src/lamto/config/settings.py` (`PLATFORM_SIGNER_PRIVATE_KEY = os.getenv("PLATFORM_SIGNER_PRIVATE_KEY", "")`), `.env` + `.env.example` (dev key entry; use the well-known Anvil/Besu dev key #1 for local: `0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d`).
- Create: `src/lamto/evidence/management/commands/authorize_platform_signer.py`, `src/lamto/evidence/tests/test_platform_signing.py`.
- Create (generated): evidence migration.

**Interfaces:**
- Consumes: existing `build_evidence_typed_data(event_id, event_type, payload_hash_hex, previous_hash_hex)` and the worker `Backend.set_signer(address, authorized)` protocol.
- Produces:
  - `platform_signer_address() -> str` (checksum address of the configured key; raises `ImproperlyConfigured` when unset).
  - `platform_sign_evidence(event_id, event_type, payload_hash_hex, previous_hash_hex) -> str` (normalized signature hex).
  - `queue_platform_event(event_id, event_type, payload, previous_hash, building) -> BlockchainOutboxEvent` — validates payload with the existing `_validate_payload`, computes the payload digest exactly like `queue_signed_event` does, signs server-side, stores `signer_address`, `signer_wallet=None`; same duplicate-resolution semantics as `queue_signed_event` (match on identical type/digest/previous/signature → return existing).
  - Outbox rows where `signer_address != ""` are platform-signed; the worker matches signer against `signer_address` first, else the wallet address.

- [ ] **Step 1: Write failing tests**

```python
# src/lamto/evidence/tests/test_platform_signing.py
import hashlib
import json
import secrets

from django.test import TestCase, override_settings

from lamto.accounts.models import Building
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType
from lamto.evidence.services import queue_platform_event
from lamto.evidence.signatures import (
    build_evidence_typed_data, platform_sign_evidence, platform_signer_address, recover_signer,
)

DEV_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"


@override_settings(PLATFORM_SIGNER_PRIVATE_KEY=DEV_KEY)
class PlatformSigningTests(TestCase):
    def test_signature_recovers_to_platform_address(self):
        event_id = "0x" + secrets.token_hex(32)
        payload_hash = hashlib.sha256(b"x").hexdigest()
        signature = platform_sign_evidence(event_id, 1, payload_hash, "0x" + "0" * 64)
        typed = build_evidence_typed_data(event_id, 1, payload_hash, "0x" + "0" * 64)
        self.assertEqual(recover_signer(typed, signature), platform_signer_address())

    def test_queue_platform_event_persists_signed_row(self):
        building = Building.objects.create(name="B1")
        event_id = "0x" + secrets.token_hex(32)
        payload = {"schema": "proposal_version.v2", "building_id": building.pk}
        event = queue_platform_event(
            event_id, EvidenceType.PROPOSAL_CREATED, payload, "0x" + "0" * 64, building
        )
        self.assertEqual(event.signer_address, platform_signer_address())
        self.assertIsNone(event.signer_wallet_id)
        self.assertEqual(event.status, BlockchainOutboxEvent.Status.PENDING)
        again = queue_platform_event(
            event_id, EvidenceType.PROPOSAL_CREATED, payload, "0x" + "0" * 64, building
        )
        self.assertEqual(again.pk, event.pk)
```

Note: if `_validate_payload` enforces per-type payload schemas, register/permit the minimal test payload accordingly — read `_validate_payload` first and use a payload it accepts for type 1 (adjust the test payload, not the validator, unless the validator hard-requires wallet fields).

- [ ] **Step 2: Run to verify failure** — `uv run pytest src/lamto/evidence/tests/test_platform_signing.py -q` → ImportError.
- [ ] **Step 3: Implement.** In `signatures.py`:

```python
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from eth_account import Account


def _platform_account():
    key = getattr(settings, "PLATFORM_SIGNER_PRIVATE_KEY", "")
    if not key:
        raise ImproperlyConfigured("PLATFORM_SIGNER_PRIVATE_KEY is not configured.")
    return Account.from_key(key)


def platform_signer_address() -> str:
    return _platform_account().address


def platform_sign_evidence(event_id, event_type, payload_hash_hex, previous_hash_hex) -> str:
    typed_data = build_evidence_typed_data(event_id, event_type, payload_hash_hex, previous_hash_hex)
    signed = Account.sign_typed_data(_platform_account().key, full_message=typed_data)
    return normalize_signature(signed.signature.hex())
```

(If the existing code signs typed data elsewhere — e.g., in tests or factories — mirror that exact `sign_typed_data` call form.) Model: add `signer_address = models.CharField(max_length=42, blank=True, default="")` to `BlockchainOutboxEvent`, relax `signer_wallet` to `null=True, blank=True`. `queue_platform_event` in `services.py` follows `queue_signed_event`'s body (same digest computation, same duplicate resolution matching on signature) minus the wallet/membership resolution, with `signature=platform_sign_evidence(...)`, `signer_address=platform_signer_address()`. Worker `_record_matches_event`: compare `to_checksum_address(record.signer)` against `to_checksum_address(event.signer_address)` when `event.signer_address` else the wallet path; `_mark_mismatch` must not dereference `event.signer_wallet.membership` when wallet is None (guard with `if event.signer_wallet_id`).
- [ ] **Step 4: Command** — `authorize_platform_signer.py`:

```python
from django.core.management.base import BaseCommand

from lamto.evidence.signatures import platform_signer_address
from lamto.evidence.worker import get_backend  # match the worker's actual backend accessor


class Command(BaseCommand):
    help = "Authorize the platform signer address on the EvidenceRegistry (owner key)."

    def handle(self, *args, **options):
        address = platform_signer_address()
        tx = get_backend().set_signer(address, True)
        self.stdout.write(self.style.SUCCESS(f"Authorized {address} (tx {tx})"))
```

(Read `worker.py` for the real backend accessor name and mirror it; if signer authorization currently flows through `SignerAuthorizationRequest` sync, calling `Backend.set_signer` directly is the intended bypass.)
- [ ] **Step 5: Migration + green** — `uv run python manage.py makemigrations evidence && uv run pytest src/lamto/evidence -q` → all passed; full suite still green.
- [ ] **Step 6: Commit** — `git commit -am "feat(evidence): platform-key signing path beside wallet signing"`

---

### Task 2: Proposal reshape — seven fields, standalone, publish→anchor, decision, progress, rating

**Files:**
- Modify: `src/lamto/finance/models/proposals.py` (`Proposal`: `case` → `null=True, blank=True`; add `building = models.ForeignKey("accounts.Building", on_delete=models.PROTECT, related_name="proposals")` always set (from case at creation when case-backed); Status → `DRAFT, PUBLISHED, NOT_PROCEEDING, IN_PROGRESS, COMPLETED, CLOSED`; add decision fields `decided_by (FK ManagementMembership, null)`, `decided_at (null)`, `decision_note (blank)`, and `completed_at (null)`, `closed_at (null)`; `ProposalVersion`: add `proposed_action = models.TextField()`, `expected_schedule = models.CharField(max_length=200)` — existing `purpose` field is the problem/need, `amount_vnd` the estimated cost, `fund_code` the funding source, `contractor_name` the contractor, `ProposalDocument` the supporting documents), `src/lamto/finance/proposals.py` (services below; `_submission_snapshot` + `build_proposal_evidence_payload` include the two new fields and `case_id`-or-null + `building_id`; the publish path calls `queue_platform_event` — the staff signature/typed-data parameters disappear from `submit_proposal_version`, which is renamed `publish_proposal_version`), `src/lamto/maintenance/models.py` (`WorkUpdate.case` → `null=True, blank=True`, add `proposal = models.ForeignKey("finance.Proposal", null=True, blank=True, on_delete=models.PROTECT, related_name="updates")` + XOR check constraint `(case IS NULL) != (proposal IS NULL)`; `CompletionRating` identically gains nullable `proposal` FK + XOR with `case`, plus unique `("resident", "proposal")` condition-style constraint mirroring the case one), `src/lamto/maintenance/cases.py` (`publish_progress`/`complete` grow a proposal target — see Produces), `src/lamto/maintenance/ratings.py` (add `rate_completed_proposal`), `src/lamto/maintenance/management/commands/close_completed_cases.py` + `cases.py::close_expired_completed_cases` (also close expired completed standalone proposals per the Global Constraints rule), `src/lamto/web/views/proposals.py` (standalone create + publish + decide + progress/complete actions), `src/lamto/web/forms/staff.py` (StandaloneProposalForm, ProposalDecisionForm; extend the existing proposal version form with the two new fields), `src/lamto/web/urls.py` (`s/proposals/new/` route), `src/lamto/web/action_inbox.py` (undecided published proposals item), `src/lamto/api/` + `docs/api/openapi-v1.yaml` (resident proposal list/detail + `proposals/<int:pk>/rating` endpoint — reuse the CaseRating serializer pattern with `proposal_id`), tests across those modules.
- Create: `src/lamto/finance/tests/test_standalone_proposals.py`.
- Create (generated): finance + maintenance migrations.

**Interfaces:**
- Consumes: Task 1's `queue_platform_event`.
- Produces:
  - `create_standalone_proposal(building, creator_membership) -> Proposal` (DRAFT, `case=None`).
  - `publish_proposal_version(proposal, creator_membership, *, amount_vnd, contractor_name, fund_code, purpose, proposed_action, expected_schedule, quotation_versions, event_id) -> ProposalVersion` — creates the immutable version, platform-anchors it (type 1, `previous_hash` = prior version's event payload hash or zero-hash for v1 — keep the existing chaining rule), sets proposal `PUBLISHED` and `current_version`; republishing a PUBLISHED/IN_PROGRESS proposal creates version N+1 (material change), never mutates old versions.
  - `decide_proposal(proposal, manager, proceed: bool, note="") -> Proposal` — guards `status == PUBLISHED`; proceed → `IN_PROGRESS` (case-backed: caller separately runs `start_case_work`), else → `NOT_PROCEEDING` + `closed_at`; records decision fields + audit `"proposal.decided"`; off-chain.
  - In `lamto.maintenance.cases`: `publish_progress(case=None, proposal=None, ...)` and a new `complete_proposal_work(proposal, manager, cause, result, before_versions=(), after_versions=()) -> Proposal` (standalone only — case-backed proposals complete through `complete_case_work`, which also sets the linked proposal `COMPLETED`+`completed_at` when one exists).
  - `rate_completed_proposal(resident, proposal, satisfied, comment="") -> CompletionRating` — any active occupant of `proposal.building`, once, after `completed_at`; does NOT close the proposal by itself (closure = 14-day/settlement rule in the close command).

- [ ] **Step 1: Write failing tests** (`test_standalone_proposals.py`) covering: standalone create+publish anchors a platform-signed outbox event with the seven fields in the snapshot; republish creates version 2 with `previous_hash` chaining to version 1; `decide_proposal` proceed/not-proceed transitions; publish on a case-backed proposal still works; `WorkUpdate` XOR constraint rejects both-set and both-null; `rate_completed_proposal` requires occupancy + completion and rejects duplicates. Model the test bodies on `test_outcomes_ab.py`'s fixture style (building/unit/occupancy/manager) — write them concretely in the file, asserting on `outbox_event.signer_address`, `snapshot["proposed_action"]`, `snapshot["expected_schedule"]`.
- [ ] **Step 2: Run to verify failure**, then implement models + migrations (`makemigrations finance maintenance`).
- [ ] **Step 3: Service implementation.** `publish_proposal_version` reuses the existing `_quotation_pairs`/`_submission_snapshot` machinery — extend the snapshot dict with `"proposed_action"`, `"expected_schedule"`, `"case_id"`, `"building_id"`; drop the wallet/signature plumbing in favor of `queue_platform_event(event_id, EvidenceType.PROPOSAL_CREATED, payload, previous_hash, proposal.building)`. Keep `create_proposal(case, membership)` (case path) delegating to shared internals; `create_standalone_proposal` guards `require_management(creator.user…)` — signature above.
- [ ] **Step 4: Progress/complete/rating extensions** in `maintenance` per Produces; `complete_case_work` additionally: `if case has a proposal → proposal.status=COMPLETED, completed_at=now`. Close command: close standalone proposals where `completed_at <= now-14d` (or settled earlier than that window's end — after Task 3 adds `settlement`, the condition is `completed_at <= now-14d or (settlement.settled_at is not None and completed_at is not None)` evaluated as: close when `now >= completed_at + 14d` OR `settlement exists AND now >= max(settled_at, completed_at + 14d)` — implement exactly the spec sentence: *closes 14 days after completion, or immediately after settlement if later*; write it as `close_at = completed_at + 14d; if settlement and settlement.settled_at > close_at: close_at = settlement.settled_at; close when now >= close_at` — guard the settlement lookup with `hasattr` until Task 3 lands, or implement this clause in Task 3).
- [ ] **Step 5: Web + API + inbox** as listed in Files (publish/decide actions gate with `require_recent_auth` since wallet signing is gone for proposals from this task on).
- [ ] **Step 6: Green** — `uv run pytest src/lamto/finance src/lamto/maintenance src/lamto/web src/lamto/api -q`, then full suite. Payment/publication tests still pass because acceptance/payment flows are untouched until Task 3 (they still read `proposal.current_version` etc. — if any of them asserted on old Status values `NORMAL_AUTHORIZED`/`IN_REVIEW`/`REJECTED`, update those assertions to the new machine: published-and-proceeding == `IN_PROGRESS`).
- [ ] **Step 7: Commit** — `git commit -am "feat(finance)!: seven-field standalone proposals with platform-anchored publication"`

---

### Task 3: Settlement — two-evidence payment record, anchored (replaces acceptance + payments)

**Files:**
- Modify: `src/lamto/finance/models/execution.py` (delete `AcceptanceRecord`, `PaymentEvidence`, `PaymentVerification`; add `Settlement` below), `src/lamto/finance/models/__init__.py`, rename `src/lamto/finance/payments.py` → `src/lamto/finance/settlements.py` (services below; keep `normalize_bank_reference`, `_require_proof_pair` mechanics), delete `src/lamto/finance/acceptance.py` + `src/lamto/finance/tests/test_acceptance.py` + `test_payments.py` (replaced), `src/lamto/web/views/payments.py` → `src/lamto/web/views/settlements.py` (record-transfer + record-ack + list/detail views; the `accept_work` view dies), `src/lamto/web/urls.py` (`s/settlements/` routes replace `s/payments/` + the accept route), `src/lamto/web/staff.py` (finance nav "Payments" → "Settlements", url names), `src/lamto/web/action_inbox.py` (`_payment_record_items` → `_settlement_transfer_items`: COMPLETED proposals without settlement; `_payment_verify_items` → `_settlement_ack_items`: settlements without ack), `src/lamto/notifications/hooks.py` (`notify_payment_recorded`/`notify_payment_verified` → `notify_settled(settlement)` to reporters+managers), `src/lamto/finance/fund.py` (`create_publication_outflow` → `create_settlement_outflow(settlement)` writing the off-chain outflow `MaintenanceFundEntry` — Task 4 finishes the entry's off-chain shape), templates.
- Create: `src/lamto/finance/tests/test_settlements.py`.
- Create (generated): finance migration.

**Interfaces:**
- Consumes: Tasks 1–2 (`queue_platform_event`, proposal `COMPLETED` status, `RATING_WINDOW_DAYS` close rule clause from Task 2 Step 4).
- Produces:

```python
class Settlement(models.Model):
    class AckKind(models.TextChoices):
        MANAGEMENT_UPLOAD = "MANAGEMENT_UPLOAD", "Management-uploaded evidence"
        PAYEE_LINK = "PAYEE_LINK", "Payee link (reserved)"

    proposal = models.OneToOneField(Proposal, on_delete=models.PROTECT, related_name="settlement")
    amount_vnd = models.BigIntegerField()
    payee_name = models.CharField(max_length=255)
    bank_reference = models.CharField(max_length=64)
    transfer_original = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name="+")
    transfer_redacted = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name="+")
    transfer_recorded_by = models.ForeignKey(ManagementMembership, on_delete=models.PROTECT, related_name="+")
    transfer_recorded_at = models.DateTimeField()
    ack_kind = models.CharField(max_length=24, choices=AckKind.choices, default=AckKind.MANAGEMENT_UPLOAD)
    ack_original = models.ForeignKey(DocumentVersion, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    ack_redacted = models.ForeignKey(DocumentVersion, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    ack_recorded_by = models.ForeignKey(ManagementMembership, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    ack_recorded_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    outbox_event = models.OneToOneField(BlockchainOutboxEvent, null=True, blank=True, on_delete=models.PROTECT, related_name="settlement")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(settled_at__isnull=True)
                    | (models.Q(ack_recorded_at__isnull=False) & models.Q(outbox_event__isnull=False))
                ),
                name="settlement_requires_both_evidence_sides",
            ),
            models.CheckConstraint(condition=models.Q(amount_vnd__gt=0), name="settlement_amount_positive"),
        ]
```

  - `record_transfer(proposal, membership, *, amount_vnd, payee_name, bank_reference, transfer_original, transfer_redacted) -> Settlement` — guards: `require_management(membership.user, proposal.building_id)`, `proposal.status == COMPLETED`, no existing settlement, positive int amount, non-empty payee name, proof pair valid (reuse `_require_proof_pair` with `proposal.building_id`); audits `"settlement.transfer_recorded"`.
  - `record_acknowledgement(settlement, membership, *, ack_original, ack_redacted, event_id) -> Settlement` — guards: management, not yet settled, proof pair valid; sets ack fields; then **finalizes atomically**: builds `build_settlement_evidence_payload(settlement)` (schema `"settlement.v1"`: settlement id, proposal id + current version number, amount, payee name, bank reference normalized, transfer/ack document sha256 pairs, timestamps — mirror `build_payment_evidence_payload`'s field style), queues `queue_platform_event(event_id, EvidenceType value 10, payload, "0x" + proposal.current_version.outbox_event.payload_hash, proposal.building)`, sets `settled_at`, creates the fund outflow via `create_settlement_outflow(settlement)`; audits `"settlement.settled"`; notifies.

- [ ] **Step 1: Write failing tests** (`test_settlements.py`): transfer-then-ack settles and anchors (assert outbox `event_type == 10`, `previous_hash` chains to the published version, `signer_address` set); transfer on a non-COMPLETED proposal rejected; second settlement rejected; ack on a settled settlement rejected; amount must be positive int; `settled_at` null until ack. Use the Task 2 fixture style plus the document-pair factory helpers (`testing/factories.document_pair`).
- [ ] **Step 2: Run to verify failure**, add the model + `EvidenceType` change: rename member `RESERVED_10 = 10, "Reserved"` → `SETTLEMENT = 10, "Settlement"`; `makemigrations finance evidence`.
- [ ] **Step 3: Implement services**; delete the acceptance/payment layer files listed; sweep:

Run: `grep -rn "AcceptanceRecord\|PaymentEvidence\|PaymentVerification\|accept_work\|record_payment\|verify_payment\|acceptance" src/lamto tests --include="*.py" | grep -v __pycache__ | grep -v migrations`
Every hit either dies with its file or converts to the settlement equivalents (publication.py hits get a temporary conversion here — its full reshape is Task 4; make `_load_execution_chain` read `proposal.settlement` instead of acceptance/payment and drop `_require_settled` on deleted event types).
- [ ] **Step 4: Web/urls/nav/inbox/notifications** per Files; the settlement detail template shows both evidence pairs, ack kind, settled status, anchor level (reuse the existing evidence-level chip partials).
- [ ] **Step 5: Close-rule clause** from Task 2 Step 4 now activates for settled proposals (implement/enable the settlement branch in `close_expired_completed_cases`).
- [ ] **Step 6: Green** — module then full suite.
- [ ] **Step 7: Commit** — `git commit -am "feat(finance)!: two-evidence anchored settlements replace acceptance and payments"`

---

### Task 4: Off-chain ledger & two-type integrity

**Files:**
- Modify: `src/lamto/finance/publication.py` (the anchored `PublicationSnapshot` + gate machinery + `build_publication_evidence_payload`/typed-data/`prepare_publication`/`finalize_publication` collapse into one off-chain function `publish_settlement_entry(settlement) -> PublishedLedgerEntry` called from settlement finalize — it builds the resident-visible story payload (`_resident_payload` survives) linking proposal + settlement + documents, with NO outbox event; keep `PublishedLedgerEntry`, delete `PublicationSnapshot` + `PublicationGateFailure` + `VerificationObservation` if it only observed snapshot anchors — check its consumers first with grep and keep it if integrity observations reference it), `src/lamto/finance/models/ledger.py` (drop `wallet`/`outbox_event` from `MaintenanceFundEntry` and `FundEntryVerification`; drop `publication` FK if it pointed at `PublicationSnapshot`; entries keep evidence document pairs + recorder + verification), `src/lamto/finance/fund.py` (strip typed-data/anchor plumbing from `record_fund_source`/`verify_fund_source` — they stay dual-control, audited, off-chain; delete `build_fund_source_evidence_typed_data`/`build_fund_verification_evidence_typed_data` and the outbox queuing), `src/lamto/finance/integrity.py` (verification walks exactly: every `ProposalVersion.outbox_event` + every `Settlement.outbox_event`; ledger-entry integrity derives from its linked settlement/proposal anchors), `src/lamto/finance/selectors.py` (`ledger_entry_proof` presents the proposal-version anchor + settlement anchor as the entry's proof; `_ledger_story_fields` keyed off the new publication payload), `src/lamto/evidence/services.py` (`_validate_payload`: only types 1 and 10 are queueable — raise on anything else), `src/lamto/evidence/models.py` (delete enum members `WORK_ACCEPTANCE`, `PAYMENT_RECORDED`, `PAYMENT_VERIFIED`, `PUBLICATION_SNAPSHOT`, `FUND_ENTRY`; keep `RESERVED_*` 2–5 and 1, 10), `src/lamto/web/action_inbox.py` (delete `_pending_publication_items`; `_integrity_mismatch_items` reworked to the two-type walk), `src/lamto/web/views/fund.py` + fund templates (signing UI gone — plain forms + `require_recent_auth`), API serializers if the ledger proof shape changes field names (keep names stable where possible: the app reads them).
- Test: rewrite `src/lamto/finance/tests/test_publication.py` → `test_ledger_offchain.py`, update `test_fund.py`, `test_integrity.py`.
- Create (generated): finance migration.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `publish_settlement_entry(settlement) -> PublishedLedgerEntry` (idempotent per settlement); `ledger_entry_proof(entry)` returning `{"proposal_version": {...anchor fields...}, "settlement": {...anchor fields...}}`; fund record/verify signatures unchanged minus the `signature`/`event_id`/typed-data parameters.

- [ ] **Step 1: Failing tests** for: settlement finalize creates a published ledger entry with story fields; `ledger_entry_proof` exposes both anchors' `event_id`/`payload_hash`/`evidence_level`; fund source record+verify works without any outbox row; `queue_platform_event` refuses type 6/7/8/9/11.
- [ ] **Step 2–4: Implement + migrate + sweep.**

Run: `grep -rn "PublicationSnapshot\|PUBLICATION_SNAPSHOT\|FUND_ENTRY\|WORK_ACCEPTANCE\|PAYMENT_RECORDED\|PAYMENT_VERIFIED\|prepare_publication\|finalize_publication" src/lamto tests --include="*.py" | grep -v __pycache__ | grep -v migrations`
Zero hits when done (except the two-type validator's own rejection list).
- [ ] **Step 5: Green** — module then full suite; check the resident app's ledger screen contract: `grep -rn "proof\|ledger" docs/api/openapi-v1.yaml | head` and update the YAML to the new proof shape; regenerate the client only if the YAML changed (`bash app/tool/generate_api.sh`) and patch the app's proof rendering minimally (field renames only).
- [ ] **Step 6: Commit** — `git commit -am "feat(finance)!: off-chain ledger and fund; integrity keyed to two anchored types"`

---

### Task 5: Delete the wallet layer (contract)

**Files:**
- Delete: `src/lamto/web/staff_signing.py`, `src/lamto/web/templates/web/staff/_sign_confirmation.html`, `src/lamto/web/tests/test_staff_signing.py`, wallet-related JS under `src/lamto/web/static/` (find: `grep -rln "typed_data\|eth_sign\|wallet" src/lamto/web/static`).
- Modify: `src/lamto/accounts/models.py` (delete `SignerWallet`, `WalletRegistrationChallenge`, `SignerAuthorizationRequest`), `src/lamto/evidence/services.py` (delete `begin_wallet_registration`, `register_wallet`, `revoke_wallet`, `_registration_typed_data`, `_active_signing_membership`, `_signed_write_authorization`, and `queue_signed_event` itself — every producer now uses `queue_platform_event`), `src/lamto/evidence/models.py` (drop `signer_wallet` FK entirely; `signer_address` becomes non-blank required for new rows — keep `blank=True` off, migration fine with disposable data), `src/lamto/evidence/worker.py` (wallet match path + `SignerAuthorizationRequest` synchronizer deleted; mismatch handler reads `signer_address` only), `src/lamto/testing/factories.py` (`make_signer` deleted; seeds set `PLATFORM_SIGNER_PRIVATE_KEY` via settings/env — e2e `.env` already carries the dev key from Task 1), `src/lamto/web/views/staff_common.py` (`set_sign_confirmation`/`pop_sign_confirmation` + `signed_action_failure` deleted; `staff_context` in `staff.py` drops `sign_confirmation`), a new accounts migration dropping the three models, and a migration dropping the `lamto_security` signed-write procedures (mirror the style of `accounts/migrations/0007_restrict_signed_write_procedures.py` with `DROP FUNCTION IF EXISTS` statements for the functions it references).
- Test: affected accounts/evidence/web tests.

**Interfaces:**
- Consumes: everything on the platform path.
- Produces: a codebase with zero wallet symbols.

- [ ] **Step 1: Sweep-driven deletion.**

Run: `grep -rn "SignerWallet\|WalletRegistrationChallenge\|SignerAuthorizationRequest\|queue_signed_event\|make_signer\|sign_confirmation\|signed_write" src/lamto tests --include="*.py" | grep -v __pycache__ | grep -v migrations`
Delete/convert every hit; the task is done when the grep returns zero.
- [ ] **Step 2: Migrations** — `uv run python manage.py makemigrations accounts evidence finance` (+ the hand-written procedure-drop migration; that one is new, not an edit).
- [ ] **Step 3: Green** — full suite `uv run pytest src/lamto tests -q` → all passed.
- [ ] **Step 4: Commit** — `git commit -am "feat!: delete per-staff wallet layer; platform key signs all evidence"`

---

### Task 6: e2e, ops, verification

**Files:**
- Modify: `src/lamto/testing/factories.py` + `tests/e2e/*` (driver: publish proposal → decide → progress → complete → record transfer → record ack → assert anchored settlement + published ledger entry + resident rating; both happy paths), `ops/deployment-checklist.md` (+ authorize_platform_signer step, PLATFORM_SIGNER_PRIVATE_KEY entry), `docs/api/openapi-v1.yaml` drift check.
- No app UX work beyond what Tasks 2/4 already patched (stage 4 owns the resident proposal screens).

- [ ] **Step 1: e2e rework + full green** — `uv run pytest src/lamto tests -q` → all passed.
- [ ] **Step 2: Chain smoke** — with Besu running and the platform signer authorized (`uv run python manage.py authorize_platform_signer`), run the existing chain-integration test module (`uv run pytest src/lamto/evidence/tests/test_chain_integration.py -q`) → all passed (it must now anchor a proposal version and a settlement end-to-end).
- [ ] **Step 3: Sweeps**

```bash
grep -rn "SignerWallet\|queue_signed_event\|AcceptanceRecord\|PaymentEvidence\|PaymentVerification" src/lamto tests --include="*.py" | grep -v __pycache__ | grep -v migrations   # zero
grep -rn "EvidenceType\." src/lamto --include="*.py" | grep -v __pycache__ | grep -v migrations | grep -v "PROPOSAL_CREATED\|SETTLEMENT\|RESERVED"                                  # zero
```

- [ ] **Step 4: Fresh-DB migration check** — drop/create `lamto`, `uv run python manage.py migrate` → clean.
- [ ] **Step 5: Flutter** — `cd app && flutter analyze && flutter test` → green (client regenerated in Task 4 if the YAML changed).
- [ ] **Step 6: Commit** — `git commit -am "feat!: stage 3 complete — anchored proposals and settlements, platform signing"`

---

## Self-review notes (already applied)

- `EvidenceType` value 1 keeps its number (existing enum member `PROPOSAL_CREATED`) so the contract range holds; settlement takes reserved value 10 — **no Solidity change, no redeploy**. Only the Python enum labels/membership change.
- The settlement's `previous_hash` chains to the published proposal version's event, preserving the parent-child chaining convention used by the old acceptance→payment chain.
- Publication gates (document confirmation, publisher separation) die with snapshot anchoring; the two-role model's protection is the reauth-gated Management action plus both artifacts' anchors. `_resident_payload`'s story content survives into `publish_settlement_entry`.
- Fund record/verify keeps dual-control (different manager verifies) — it lost only its anchor, not its process.
- Standalone-proposal closure implements the spec sentence "closes 14 days after completion — or immediately after settlement if later" exactly as written in Task 2 Step 4 / Task 3 Step 5.
- Task ordering keeps every task green: platform path exists before proposals use it (T1→T2), settlements exist before publication reshapes around them (T3→T4), wallet layer dies only after no producer uses it (T5).
