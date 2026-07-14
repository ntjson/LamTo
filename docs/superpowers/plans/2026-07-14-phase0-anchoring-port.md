# Phase 0 Plan 2 — Anchoring Port, Evidence Levels, Chain Opacity

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make blockchain anchoring a configurable transport (`besu | disabled`), replace every boolean notion of "verified" with the explicit evidence-level enum (`PENDING · LOCAL_SIGNED · CHAIN_CONFIRMED · MISMATCH`), and lock down what the shared chain can observe — implementing spec §5.1, §5.2, and the §2.2 opacity audit of `docs/superpowers/specs/2026-07-14-phase0-phase1-foundation-design.md`.

**Architecture:** A new terminal outbox status `LOCAL` marks events settled without a chain round-trip. Every settlement gate (publication prerequisites, finalization, resident ledger visibility, fund verification, corrections) switches from `status == CONFIRMED` to `is_settled` (`LOCAL` or `CONFIRMED`). Labels, exports, health, and integrity observations render the evidence level honestly — `LOCAL_SIGNED` never borrows `CHAIN_CONFIRMED` wording. Wallet signatures, the outbox, canonical hashing, publication gates, and corrections are untouched in both modes.

**Tech Stack:** Django 5.2, PostgreSQL (psycopg3), existing `web3` chain client, pytest + pytest-django, `PilotDomainDriver` domain-level e2e.

## Two documented design decisions (read before implementing)

1. **The port is the existing `ChainClient` protocol plus a settings switch — no new backend classes.** Spec §5.2 sketches `BesuBackend` / `DisabledBackend`. `lamto/evidence/worker.py` already injects a `ChainClient` (`find`/`submit`/`set_signer`); `EvidenceRegistryClient` **is** the Besu backend and stays byte-for-byte unchanged. "Disabled" has nothing to submit to, so a no-op client class would be a fiction — instead the worker branches on `settings.EVIDENCE_ANCHORING_BACKEND` and settles claimed rows as `LOCAL` without constructing any client. All spec-normative behavior (statuses, gates, labels, runbook semantics) is implemented exactly.
2. **`PublicationSnapshot` settlement facts are derived properties, not stored columns.** Spec §5.2 says the snapshot "immutably records the anchoring backend and evidence level at settlement". Migration `finance/0008` installs `publication_snapshot_append_only`, a DB trigger rejecting **every** UPDATE on `finance_publicationsnapshot`. Stamping columns post-insert would require weakening that trigger — amending the P1 append-only gate, which §5.3 explicitly keeps and which is *not* the one approved amendment. Derivation is lossless: `LOCAL` and `CONFIRMED` are terminal statuses, and `confirmed_at` survives the only post-settlement transition (`CONFIRMED → MISMATCH`), so backend-at-settlement and level-at-settlement are always reconstructible from the outbox row (which is itself the identity-protected evidence spine). The properties are named exactly `anchoring_backend` and `settled_evidence_level`.

## Global Constraints

- **Verified test environment** (identical to Plan 1):

```bash
cd /home/nts/src/LamTo
docker compose up -d db
set -a; . ./.env.example; set +a
export SECRET_KEY=test-secret EVIDENCE_WRITE_SECRET=test-evidence \
       POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
# then: .venv/bin/python -m pytest <path> -q
# manage.py lives at the repo root: .venv/bin/python manage.py <command>
```

- `EVIDENCE_ANCHORING_BACKEND` defaults to `"besu"`; with the default, **every existing test must stay green after every task**. Run the full suite (`.venv/bin/python -m pytest src/lamto tests -q`) at the end of Tasks 4, 7, and 8; task-local suites otherwise.
- Honesty invariants (spec §5.2): a `LOCAL` event never has `transaction_hash` or `confirmed_at` set, never becomes `CONFIRMED`, and is never retro-anchored. No wording, badge, CSS class, or export value for `LOCAL_SIGNED` may reuse `CHAIN_CONFIRMED` presentation.
- No generic `verified` boolean anywhere (spec §5.1). Gates use `is_settled` / `SETTLED_STATUSES`; exports carry enum values verbatim.
- Append-only financial records, integer VND, separation of duties, and the `queue_signed_event` SQL insert path are untouched. No payment-provider dependency may enter `pyproject.toml`.
- New user-facing copy is English, matching the existing template language (Vietnamese l10n is Phase 1 client-side work).
- Commit after every task with the message given in its final step.

---

### Task 1: `LOCAL` outbox status and the `EvidenceLevel` enum

**Files:**
- Modify: `src/lamto/evidence/models.py`
- Create: `src/lamto/evidence/migrations/0011_outbox_local_status.py` (via makemigrations)
- Test: `src/lamto/evidence/tests/test_levels.py`

**Interfaces:**
- Consumes: existing `BlockchainOutboxEvent.Status` choices.
- Produces (used by every later task):
  - `BlockchainOutboxEvent.Status.LOCAL` (value `"LOCAL"`, label `"Locally settled"`)
  - `EvidenceLevel(models.TextChoices)` with members `PENDING`, `LOCAL_SIGNED`, `CHAIN_CONFIRMED`, `MISMATCH` (values equal to their names)
  - `SETTLED_STATUSES: tuple` = `(Status.LOCAL, Status.CONFIRMED)`
  - `evidence_level(status) -> str` — total mapping from any status value (enum member or raw string) to an `EvidenceLevel` value
  - `is_settled(status) -> bool`
  - `BlockchainOutboxEvent.evidence_level` property (current level of the row)

- [ ] **Step 1: Write the failing test**

Create `src/lamto/evidence/tests/test_levels.py`:

```python
"""Evidence-level enum: total status mapping, no generic verified boolean (spec 5.1)."""

from django.test import SimpleTestCase

from lamto.evidence.models import (
    SETTLED_STATUSES,
    BlockchainOutboxEvent,
    EvidenceLevel,
    evidence_level,
    is_settled,
)

Status = BlockchainOutboxEvent.Status


class EvidenceLevelTests(SimpleTestCase):
    def test_status_to_level_mapping_is_total(self):
        expected = {
            Status.PENDING: EvidenceLevel.PENDING,
            Status.SUBMITTED: EvidenceLevel.PENDING,
            Status.FAILED: EvidenceLevel.PENDING,
            Status.LOCAL: EvidenceLevel.LOCAL_SIGNED,
            Status.CONFIRMED: EvidenceLevel.CHAIN_CONFIRMED,
            Status.MISMATCH: EvidenceLevel.MISMATCH,
        }
        self.assertEqual(set(expected), set(Status))
        for status, level in expected.items():
            self.assertEqual(evidence_level(status), level)
            # Raw DB string values map identically.
            self.assertEqual(evidence_level(str(status)), level)

    def test_is_settled_only_for_local_and_confirmed(self):
        self.assertEqual(
            {status for status in Status if is_settled(status)},
            {Status.LOCAL, Status.CONFIRMED},
        )
        self.assertEqual(set(SETTLED_STATUSES), {Status.LOCAL, Status.CONFIRMED})

    def test_event_property_reflects_current_status(self):
        event = BlockchainOutboxEvent(status=Status.LOCAL)
        self.assertEqual(event.evidence_level, EvidenceLevel.LOCAL_SIGNED)
        event.status = Status.CONFIRMED
        self.assertEqual(event.evidence_level, EvidenceLevel.CHAIN_CONFIRMED)
        # Spec 5.1: no generic verified boolean exists on the event.
        self.assertFalse(hasattr(event, "verified"))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/evidence/tests/test_levels.py -q`
Expected: FAIL — `ImportError: cannot import name 'SETTLED_STATUSES'` (and `LOCAL` missing).

- [ ] **Step 3: Implement the enum and helpers**

In `src/lamto/evidence/models.py`, add `LOCAL` to the `Status` choices (insert between `CONFIRMED` and `FAILED`):

```python
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUBMITTED = "SUBMITTED", "Submitted"
        CONFIRMED = "CONFIRMED", "Confirmed"
        LOCAL = "LOCAL", "Locally settled"
        FAILED = "FAILED", "Failed"
        MISMATCH = "MISMATCH", "Mismatch"
```

Add `EvidenceLevel` immediately after the `EvidenceType` class (before `BlockchainOutboxEvent`):

```python
class EvidenceLevel(models.TextChoices):
    """Explicit verification state — replaces any boolean notion of verified (spec 5.1)."""

    PENDING = "PENDING", "Pending"
    LOCAL_SIGNED = "LOCAL_SIGNED", "Locally signed"
    CHAIN_CONFIRMED = "CHAIN_CONFIRMED", "Chain confirmed"
    MISMATCH = "MISMATCH", "Mismatch"
```

Add a property inside `BlockchainOutboxEvent` (after the field definitions, before `class Meta`):

```python
    @property
    def evidence_level(self) -> str:
        return evidence_level(self.status)
```

Add at module level, after the `BlockchainOutboxEvent` class:

```python
SETTLED_STATUSES = (
    BlockchainOutboxEvent.Status.LOCAL,
    BlockchainOutboxEvent.Status.CONFIRMED,
)


def evidence_level(status) -> str:
    """Map an outbox delivery status to the explicit evidence level (spec 5.1)."""
    if status == BlockchainOutboxEvent.Status.LOCAL:
        return EvidenceLevel.LOCAL_SIGNED
    if status == BlockchainOutboxEvent.Status.CONFIRMED:
        return EvidenceLevel.CHAIN_CONFIRMED
    if status == BlockchainOutboxEvent.Status.MISMATCH:
        return EvidenceLevel.MISMATCH
    return EvidenceLevel.PENDING


def is_settled(status) -> bool:
    """Settled = evidence durably recorded: locally signed or chain-confirmed."""
    return status in SETTLED_STATUSES
```

(The property body resolves the module-level `evidence_level` at call time; the name collision between property and function is intentional — each reads naturally at its call sites.)

- [ ] **Step 4: Generate the choices migration**

```bash
set -a; . ./.env.example; set +a
export SECRET_KEY=test-secret EVIDENCE_WRITE_SECRET=test-evidence
.venv/bin/python manage.py makemigrations evidence --name outbox_local_status
```

Expected: one new file `src/lamto/evidence/migrations/0011_outbox_local_status.py` containing a single `AlterField` on `blockchainoutboxevent.status` with the six choices (no SQL schema change — the DB has no status check constraint, and the identity trigger from migrations 0002/0009 deliberately leaves `status` mutable).

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/evidence/tests/test_levels.py src/lamto/evidence/tests -q`
Expected: new tests PASS; all existing evidence tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/evidence/models.py src/lamto/evidence/migrations/0011_outbox_local_status.py src/lamto/evidence/tests/test_levels.py
git commit -m "feat: LOCAL outbox status and evidence-level enum"
```

---

### Task 2: `EVIDENCE_ANCHORING_BACKEND` setting and disabled-mode worker settlement

**Files:**
- Modify: `src/lamto/config/settings.py` (after the `EVIDENCE_WRITE_SECRET` line, ~line 195)
- Modify: `.env.example` (blockchain block, after line 28)
- Modify: `src/lamto/evidence/worker.py`
- Modify: `src/lamto/evidence/management/commands/sync_signer_authorizations.py`
- Test: `src/lamto/evidence/tests/test_worker.py`

**Interfaces:**
- Consumes: `BlockchainOutboxEvent.Status.LOCAL` (Task 1).
- Produces:
  - `settings.EVIDENCE_ANCHORING_BACKEND: str` — `"besu"` (default) or `"disabled"`, validated at import
  - `lamto.evidence.worker.anchoring_disabled() -> bool`
  - `lamto.evidence.worker._mark_local(event) -> BlockchainOutboxEvent` — settles as `LOCAL`, empty `transaction_hash`, `confirmed_at` stays `NULL`
  - Behavior: `process_outbox_event` / `process_due_outbox_events` settle claimed rows as `LOCAL` in disabled mode and construct **no** chain client; `LOCAL` is terminal (never re-checked, never resubmitted, never retro-anchored)
  - Test helper: `OutboxEventFactoryMixin` in `test_worker.py` (reused by later evidence tests)

- [ ] **Step 1: Write the failing tests**

In `src/lamto/evidence/tests/test_worker.py`, first extract the five helper methods of `BlockchainWorkerTests` into a mixin so a second settings-variant class can reuse them. Insert this class directly above `BlockchainWorkerTests` and move the methods **verbatim** (delete them from `BlockchainWorkerTests`, whose decorator and test methods stay unchanged):

```python
class OutboxEventFactoryMixin:
    """Wallet + signed-event setup shared by worker test variants."""

    def make_membership(self, role=OrganizationMembership.Role.OPERATOR, suffix="worker"):
        kind = OrganizationMembership.ROLE_TO_ORGANIZATION_KIND[role]
        building = Building.objects.create(name=f"Building {suffix}")
        organization = Organization.objects.create(
            building=building, name=f"Organization {suffix}", kind=kind
        )
        user = get_user_model().objects.create_user(
            email=f"{suffix}@example.test", password="secret", display_name=suffix
        )
        return OrganizationMembership.objects.create(
            user=user, organization=organization, role=role
        )

    def register(self, membership, account=None):
        account = account or Account.create()
        challenge = begin_wallet_registration(membership)
        proof = Account.sign_message(
            encode_typed_data(full_message=challenge), account.key
        ).signature.hex()
        return account, register_wallet(membership, account.address.lower(), proof)

    def sign_event(self, account, event_id, event_type, payload, previous_hash=None):
        previous_hash = previous_hash or "0x" + "00" * 32
        typed = build_evidence_typed_data(
            event_id,
            event_type,
            "0x" + payload_hash(payload),
            previous_hash,
        )
        return Account.sign_message(
            encode_typed_data(full_message=typed), account.key
        ).signature.hex()

    def make_pending_outbox_event(self, suffix="pending", event_byte="11"):
        membership = self.make_membership(suffix=suffix)
        account, wallet = self.register(membership)
        event_id = "0x" + event_byte * 32
        payload = dict(PROPOSAL_PAYLOAD)
        signature = self.sign_event(account, event_id, EvidenceType.PROPOSAL_CREATED, payload)
        with transaction.atomic():
            event = queue_signed_event(
                event_id,
                EvidenceType.PROPOSAL_CREATED,
                payload,
                "0x" + "00" * 32,
                membership,
                signature,
            )
        return event

    def fake_chain_client(self, **kwargs):
        return FakeChainClient(**kwargs)
```

Change the existing class header to:

```python
@override_settings(
    BLOCKCHAIN_CHAIN_ID=1337,
    EVIDENCE_CONTRACT_ADDRESS="0x0000000000000000000000000000000000000001",
    WALLET_REGISTRATION_TTL_SECONDS=600,
)
class BlockchainWorkerTests(OutboxEventFactoryMixin, TestCase):
```

Then append the disabled-mode class at the end of the file. Add `process_due_outbox_events` to the existing `from lamto.evidence.worker import ...` line:

```python
@override_settings(
    BLOCKCHAIN_CHAIN_ID=1337,
    EVIDENCE_CONTRACT_ADDRESS="0x0000000000000000000000000000000000000001",
    WALLET_REGISTRATION_TTL_SECONDS=600,
    EVIDENCE_ANCHORING_BACKEND="disabled",
)
class DisabledAnchoringWorkerTests(OutboxEventFactoryMixin, TestCase):
    """Disabled backend settles LOCAL, honestly and terminally (spec 5.2)."""

    def test_pending_event_settles_local_without_touching_chain(self):
        event = self.make_pending_outbox_event(suffix="local", event_byte="44")
        client = self.fake_chain_client()

        processed = process_outbox_event(event.id, client=client)

        self.assertEqual(processed.status, BlockchainOutboxEvent.Status.LOCAL)
        self.assertEqual(processed.transaction_hash, "")
        self.assertIsNone(processed.confirmed_at)
        self.assertIsNone(processed.lease_expires_at)
        self.assertEqual(client.find_calls, 0)
        self.assertEqual(client.submit_calls, 0)

    def test_local_is_terminal_and_never_retro_anchored(self):
        event = self.make_pending_outbox_event(suffix="terminal", event_byte="55")
        process_outbox_event(event.id, client=self.fake_chain_client())

        # Mode switch back to besu: settled events keep their status (spec 5.2).
        with override_settings(EVIDENCE_ANCHORING_BACKEND="besu"):
            client = self.fake_chain_client()
            again = process_outbox_event(event.id, client=client)

        self.assertEqual(again.status, BlockchainOutboxEvent.Status.LOCAL)
        self.assertEqual(client.find_calls, 0)
        self.assertEqual(client.submit_calls, 0)

    def test_batch_processing_constructs_no_chain_client(self):
        self.make_pending_outbox_event(suffix="batch", event_byte="66")

        # client=None must not call default_client() in disabled mode.
        results = process_due_outbox_events()

        self.assertEqual(
            [event.status for event in results],
            [BlockchainOutboxEvent.Status.LOCAL],
        )

    def test_confirmed_event_keeps_chain_record_in_disabled_mode(self):
        event = self.make_pending_outbox_event(suffix="keepconf", event_byte="77")
        with override_settings(EVIDENCE_ANCHORING_BACKEND="besu"):
            confirmed = process_outbox_event(event.id, client=self.fake_chain_client())
        self.assertEqual(confirmed.status, BlockchainOutboxEvent.Status.CONFIRMED)

        client = self.fake_chain_client()
        again = process_outbox_event(event.id, client=client)

        self.assertEqual(again.status, BlockchainOutboxEvent.Status.CONFIRMED)
        # Disabled mode skips the chain re-check entirely.
        self.assertEqual(client.find_calls, 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/evidence/tests/test_worker.py -q`
Expected: the four new tests FAIL (events settle `CONFIRMED` via submit, or `AttributeError` on missing setting); all pre-existing tests PASS (mixin move is behavior-preserving).

- [ ] **Step 3: Add the setting**

In `src/lamto/config/settings.py`, directly after the `EVIDENCE_WRITE_SECRET` line:

```python
# Anchoring transport (spec 5.2): "besu" performs the chain round-trip;
# "disabled" settles outbox events locally as LOCAL — honest, never CONFIRMED.
EVIDENCE_ANCHORING_BACKEND = os.getenv("EVIDENCE_ANCHORING_BACKEND", "besu")
if EVIDENCE_ANCHORING_BACKEND not in {"besu", "disabled"}:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "EVIDENCE_ANCHORING_BACKEND must be 'besu' or 'disabled', got "
        f"{EVIDENCE_ANCHORING_BACKEND!r}."
    )
```

In `.env.example`, after the `BLOCKCHAIN_CONTRACT_OWNER_PRIVATE_KEY=` line:

```bash
# Anchoring transport: besu (default) | disabled.
# disabled settles evidence locally (LOCAL_SIGNED) — never presented as chain-confirmed.
# EVIDENCE_ANCHORING_BACKEND=besu
```

- [ ] **Step 4: Implement the worker branch**

In `src/lamto/evidence/worker.py`:

Add to the imports (after `from django.db.models import Q`):

```python
from django.conf import settings
```

Add after the `_retry_delay` function:

```python
def anchoring_disabled() -> bool:
    return settings.EVIDENCE_ANCHORING_BACKEND == "disabled"
```

Add after `_mark_confirmed`:

```python
def _mark_local(event: BlockchainOutboxEvent) -> BlockchainOutboxEvent:
    """Settle without a chain round-trip. Honest LOCAL: no tx hash, no confirmed_at."""
    event.status = BlockchainOutboxEvent.Status.LOCAL
    event.lease_expires_at = None
    event.last_error = ""
    event.save(update_fields=["status", "lease_expires_at", "last_error", "updated_at"])
    return event
```

Replace `process_outbox_event` (currently lines 206–288) entirely with:

```python
def process_outbox_event(event_id, client: ChainClient | None = None) -> BlockchainOutboxEvent:
    """
    Process one outbox row idempotently by stable event primary key.

    Never re-signs or changes payload identity fields. Only delivery status,
    attempts, lease, and receipt metadata are mutated. With anchoring disabled,
    due rows settle immediately as LOCAL and no chain client is constructed.
    """
    existing = (
        BlockchainOutboxEvent.objects.select_related("signer_wallet__membership__user")
        .filter(pk=event_id)
        .first()
    )
    if existing is None:
        raise BlockchainOutboxEvent.DoesNotExist(
            f"BlockchainOutboxEvent id={event_id} does not exist"
        )
    if existing.status in {
        BlockchainOutboxEvent.Status.CONFIRMED,
        BlockchainOutboxEvent.Status.MISMATCH,
        BlockchainOutboxEvent.Status.LOCAL,
    }:
        # Terminal states: re-check chain for CONFIRMED but never resubmit.
        # LOCAL settled off-chain and is never retro-anchored (spec 5.2).
        if (
            existing.status == BlockchainOutboxEvent.Status.CONFIRMED
            and not anchoring_disabled()
        ):
            client = client or default_client()
            try:
                record = client.find(existing)
            except Exception:
                return existing
            if record is not None and not _record_matches_event(record, existing):
                with transaction.atomic():
                    return _mark_mismatch(existing, record)
        return existing

    claimed = _claim_outbox_event(event_id)
    if claimed is None:
        # Another worker holds the lease, or the row is not due.
        return BlockchainOutboxEvent.objects.select_related("signer_wallet").get(
            pk=event_id
        )

    return _process_claimed_event(claimed, client=client)
```

Replace `process_due_outbox_events` and `_process_claimed_event` (currently lines 329–382) entirely with:

```python
def process_due_outbox_events(
    *, limit: int = 100, client: ChainClient | None = None
) -> list[BlockchainOutboxEvent]:
    if client is None and not anchoring_disabled():
        client = default_client()
    processed: list[BlockchainOutboxEvent] = []
    for _ in range(limit):
        claimed = claim_next_due_outbox_event()
        if claimed is None:
            break
        processed.append(_process_claimed_event(claimed, client=client))
    return processed


def _process_claimed_event(
    claimed: BlockchainOutboxEvent, *, client: ChainClient | None = None
) -> BlockchainOutboxEvent:
    if anchoring_disabled():
        with transaction.atomic():
            event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
            return _mark_local(event)

    client = client or default_client()
    try:
        record = client.find(claimed)
    except Exception as exc:
        with transaction.atomic():
            event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
            return _mark_retry(event, exc)

    if record is not None:
        with transaction.atomic():
            event = (
                BlockchainOutboxEvent.objects.select_for_update()
                .select_related("signer_wallet__membership__user")
                .get(pk=claimed.pk)
            )
            if _record_matches_event(record, event):
                return _mark_confirmed(
                    event,
                    transaction_hash=event.transaction_hash,
                    recorded_at=record.recorded_at,
                )
            return _mark_mismatch(event, record)

    try:
        tx_hash = client.submit(claimed)
        receipt = getattr(client, "last_receipt", None) or {}
    except Exception as exc:
        with transaction.atomic():
            event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
            return _mark_retry(event, exc)

    with transaction.atomic():
        event = BlockchainOutboxEvent.objects.select_for_update().get(pk=claimed.pk)
        return _mark_confirmed(event, transaction_hash=tx_hash, receipt=receipt)
```

(This deduplicates the previously copy-pasted find/submit pipeline of `process_outbox_event`; the collapsed `except Exception` branches all called `_mark_retry` identically. The now-unused imports `ChainClientError` and `ChainTimeoutError` may drop from the import line if nothing else in the module uses them — check before deleting.)

In `src/lamto/evidence/management/commands/sync_signer_authorizations.py`, guard the handle method (signer authorization is a chain operation; a disabled deployment has no registry to sync). Change the import line to:

```python
from lamto.evidence.worker import anchoring_disabled, sync_signer_authorizations
```

and add the guard as the first lines of `handle`:

```python
    def handle(self, *args, **options):
        if anchoring_disabled():
            self.stdout.write("anchoring backend disabled; signer sync skipped")
            return
        results = sync_signer_authorizations()
        confirmed = sum(1 for item in results if item.status == item.Status.CONFIRMED)
        self.stdout.write(
            f"synchronized {len(results)} authorization request(s); confirmed={confirmed}"
        )
        for item in results:
            self.stdout.write(
                f"  id={item.pk} action={item.action} status={item.status} "
                f"tx={item.transaction_hash or '-'}"
            )
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/evidence/tests -q`
Expected: all PASS (new disabled-mode tests plus every pre-existing worker/outbox test under the `besu` default).

- [ ] **Step 6: Commit**

```bash
git add src/lamto/config/settings.py .env.example src/lamto/evidence/worker.py \
        src/lamto/evidence/management/commands/sync_signer_authorizations.py \
        src/lamto/evidence/tests/test_worker.py
git commit -m "feat: anchoring backend port with disabled-mode local settlement"
```

---

### Task 3: `PublicationSnapshot` settlement derivation

**Files:**
- Modify: `src/lamto/finance/models/ledger.py` (`PublicationSnapshot`, ~line 140)
- Test: `src/lamto/finance/tests/test_settlement_derivation.py`

**Interfaces:**
- Consumes: `EvidenceLevel`, `BlockchainOutboxEvent` (Task 1).
- Produces:
  - `PublicationSnapshot.anchoring_backend -> str` — `"disabled"` | `"besu"` | `""` (unsettled)
  - `PublicationSnapshot.settled_evidence_level -> str` — `EvidenceLevel.LOCAL_SIGNED` | `EvidenceLevel.CHAIN_CONFIRMED` | `""` (unsettled)

- [ ] **Step 1: Write the failing test**

Create `src/lamto/finance/tests/test_settlement_derivation.py`:

```python
"""Backend and level at settlement, derived from the terminal outbox status (spec 5.2).

Stored columns were rejected: finance_publicationsnapshot is DB append-only
(migration 0008), and weakening that trigger would amend a P1 gate.
"""

from django.test import SimpleTestCase
from django.utils import timezone

from lamto.evidence.models import BlockchainOutboxEvent, EvidenceLevel
from lamto.finance.models import PublicationSnapshot

Status = BlockchainOutboxEvent.Status


def _snapshot(status, confirmed_at=None):
    snapshot = PublicationSnapshot()
    snapshot.outbox_event = BlockchainOutboxEvent(
        status=status, confirmed_at=confirmed_at
    )
    return snapshot


class SettlementDerivationTests(SimpleTestCase):
    def test_local_settlement_records_disabled_backend(self):
        snapshot = _snapshot(Status.LOCAL)
        self.assertEqual(snapshot.anchoring_backend, "disabled")
        self.assertEqual(snapshot.settled_evidence_level, EvidenceLevel.LOCAL_SIGNED)

    def test_confirmed_settlement_records_besu_backend(self):
        snapshot = _snapshot(Status.CONFIRMED, confirmed_at=timezone.now())
        self.assertEqual(snapshot.anchoring_backend, "besu")
        self.assertEqual(snapshot.settled_evidence_level, EvidenceLevel.CHAIN_CONFIRMED)

    def test_post_settlement_mismatch_keeps_settlement_facts(self):
        # CONFIRMED -> MISMATCH re-check preserves confirmed_at; the level at
        # settlement stays CHAIN_CONFIRMED even though the current level is MISMATCH.
        snapshot = _snapshot(Status.MISMATCH, confirmed_at=timezone.now())
        self.assertEqual(snapshot.anchoring_backend, "besu")
        self.assertEqual(snapshot.settled_evidence_level, EvidenceLevel.CHAIN_CONFIRMED)
        self.assertEqual(
            snapshot.outbox_event.evidence_level, EvidenceLevel.MISMATCH
        )

    def test_unsettled_snapshot_has_no_settlement_facts(self):
        for status in (Status.PENDING, Status.SUBMITTED, Status.FAILED, Status.MISMATCH):
            snapshot = _snapshot(status)
            self.assertEqual(snapshot.anchoring_backend, "")
            self.assertEqual(snapshot.settled_evidence_level, "")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/finance/tests/test_settlement_derivation.py -q`
Expected: FAIL — `AttributeError: 'PublicationSnapshot' object has no attribute 'anchoring_backend'`.

- [ ] **Step 3: Implement the properties**

In `src/lamto/finance/models/ledger.py`, extend the evidence import (line 5) to:

```python
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceLevel
```

Add to `PublicationSnapshot`, after the existing `status` property:

```python
    @property
    def anchoring_backend(self) -> str:
        """Backend in force at settlement, derived from the terminal outbox status.

        LOCAL and CONFIRMED are terminal, and confirmed_at survives the only
        post-settlement transition (CONFIRMED -> MISMATCH), so this is exact.
        Empty string while unsettled.
        """
        status = self.outbox_event.status
        if status == BlockchainOutboxEvent.Status.LOCAL:
            return "disabled"
        if (
            status == BlockchainOutboxEvent.Status.CONFIRMED
            or self.outbox_event.confirmed_at is not None
        ):
            return "besu"
        return ""

    @property
    def settled_evidence_level(self) -> str:
        """Evidence level at settlement (spec 5.2); empty string while unsettled."""
        status = self.outbox_event.status
        if status == BlockchainOutboxEvent.Status.LOCAL:
            return EvidenceLevel.LOCAL_SIGNED
        if (
            status == BlockchainOutboxEvent.Status.CONFIRMED
            or self.outbox_event.confirmed_at is not None
        ):
            return EvidenceLevel.CHAIN_CONFIRMED
        return ""
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/finance/tests/test_settlement_derivation.py src/lamto/finance/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lamto/finance/models/ledger.py src/lamto/finance/tests/test_settlement_derivation.py
git commit -m "feat: derive publication settlement backend and level"
```

---

### Task 4: Settlement gates accept `LOCAL`-settled evidence

**Files:**
- Modify: `src/lamto/finance/publication.py` (`_require_confirmed` ~line 130, its call at ~line 485, finalize gate ~line 626)
- Modify: `src/lamto/finance/selectors.py` (~line 23)
- Modify: `src/lamto/finance/fund.py` (`_prior_verified_source_hash` ~line 119, `_source_verified_q` ~line 423)
- Modify: `src/lamto/finance/corrections.py` (gates at ~lines 270, 391, 541, 691)
- Modify: `src/lamto/finance/models/corrections.py` (`is_resident_visible` ~line 40, `status` ~line 78)
- Modify: `src/lamto/web/action_inbox.py` (~line 494)
- Modify: `src/lamto/finance/management/commands/finalize_publications.py`
- Modify: `src/lamto/config/worker.py` (~lines 97, 111)
- Modify: `src/lamto/testing/factories.py` (`attempt_publication` message map ~line 866)
- Test: `src/lamto/finance/tests/test_settled_gates.py`

**Interfaces:**
- Consumes: `is_settled`, `SETTLED_STATUSES` (Task 1).
- Produces:
  - `lamto.finance.publication._require_settled(event, label)` (renamed from `_require_confirmed`; raises `ValidationError(f"{label} evidence is not settled.")`)
  - Every settlement gate and settlement-driven query accepts both `LOCAL` and `CONFIRMED`; `MISMATCH`/`PENDING`/`SUBMITTED`/`FAILED` still blocked everywhere.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/finance/tests/test_settled_gates.py`:

```python
"""LOCAL-settled evidence passes every settlement gate (spec 5.2)."""

import tempfile

from django.test import TestCase, override_settings

from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.models import MaintenanceFundEntry, PublishedLedgerEntry
from lamto.finance.publication import finalize_publication
from lamto.finance.selectors import published_ledger_entries
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world
from lamto.web.action_inbox import _pending_publication_items

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-settled-gates-")


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class SettledGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seed = seed_pilot_world(
            building_name="Settled Gates Building", create_sample_report=False
        )
        driver = PilotDomainDriver(cls.seed)
        driver.pause_chain()  # suppress the driver's fake CONFIRMED updates
        driver.prepare_locally_approved_normal_work(None)
        driver.complete_assigned_work()
        driver.accept_and_record_payment()
        driver.verify_payment()
        # Settle every pending flow event off-chain.
        BlockchainOutboxEvent.objects.filter(
            status=BlockchainOutboxEvent.Status.PENDING
        ).update(status=BlockchainOutboxEvent.Status.LOCAL)
        # Signing requires settled prerequisites; with LOCAL they must pass.
        cls.snapshot = driver.sign_publication_snapshot()
        BlockchainOutboxEvent.objects.filter(pk=cls.snapshot.outbox_event_id).update(
            status=BlockchainOutboxEvent.Status.LOCAL
        )

    def test_local_settled_snapshot_finalizes_and_posts_outflow(self):
        entry = finalize_publication(self.snapshot.pk)
        self.assertIsInstance(entry, PublishedLedgerEntry)
        outflow = MaintenanceFundEntry.objects.get(
            entry_type=MaintenanceFundEntry.EntryType.OUTFLOW,
            proposal=entry.proposal,
        )
        self.assertEqual(outflow.amount_vnd, -entry.actual_cost_vnd)

    def test_local_settled_entry_is_resident_visible(self):
        entry = finalize_publication(self.snapshot.pk)
        listed = published_ledger_entries(self.seed.building.pk)
        self.assertIn(entry.pk, [row.pk for row in listed])

    def test_pending_snapshot_still_blocks_finalization(self):
        BlockchainOutboxEvent.objects.filter(pk=self.snapshot.outbox_event_id).update(
            status=BlockchainOutboxEvent.Status.PENDING
        )
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            finalize_publication(self.snapshot.pk)

    def test_local_settled_snapshot_appears_in_finalize_inbox(self):
        items = _pending_publication_items(self.seed.building.pk)
        targets = [(item.target_type, item.target_id) for item in items]
        self.assertIn(("PublicationSnapshot", self.snapshot.pk), targets)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest src/lamto/finance/tests/test_settled_gates.py -q`
Expected: FAIL in `setUpTestData` — `sign_publication_snapshot` raises `ValidationError("Prerequisite evidence is not chain-confirmed.")` because LOCAL is not yet accepted.

- [ ] **Step 3: Switch the gates**

`src/lamto/finance/publication.py`:

Extend the evidence import (line 13) to:

```python
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceType, is_settled
```

Replace `_require_confirmed` (~line 130):

```python
def _require_settled(event, label):
    if event is None:
        raise ValidationError(f"{label} evidence event is required.")
    if not is_settled(event.status):
        raise ValidationError(f"{label} evidence is not settled.")
    return event
```

Update its only call site (~line 485): `_require_confirmed(event, "Prerequisite")` → `_require_settled(event, "Prerequisite")`.

Replace the finalize gate (~line 626):

```python
    if not is_settled(snapshot.outbox_event.status):
        raise ValidationError(
            "Publication snapshot must be settled before finalization."
        )
```

`src/lamto/finance/selectors.py`: add `SETTLED_STATUSES` to the evidence import and change the filter (~line 23):

```python
from lamto.evidence.models import SETTLED_STATUSES
```
```python
            snapshot__outbox_event__status__in=SETTLED_STATUSES,
```

(`BlockchainOutboxEvent` becomes unused in that module after this change — drop it from the import if so.)

`src/lamto/finance/fund.py`: add `SETTLED_STATUSES` to the evidence import (line 12). In `_prior_verified_source_hash` (~lines 118–121):

```python
            verification__outbox_event__status__in=SETTLED_STATUSES,
            outbox_event__status__in=SETTLED_STATUSES,
```

In `_source_verified_q` (~lines 420–425):

```python
def _source_verified_q():
    return Q(
        entry_type__in=SOURCE_ENTRY_TYPES,
        outbox_event__status__in=SETTLED_STATUSES,
        verification__outbox_event__status__in=SETTLED_STATUSES,
    )
```

`src/lamto/finance/corrections.py`: add `is_settled` to its `lamto.evidence.models` import, then four gate edits:

~line 270:
```python
    if not is_settled(entry.snapshot.outbox_event.status):
        raise ValidationError("Only published entries with settled snapshots may be corrected.")
```

~line 391:
```python
    if not is_settled(correction.outbox_event.status):
        raise ValidationError("Correction creation must be settled before decisions.")
```

~line 541 (inside the `for label, event in (...)` loop):
```python
        if not is_settled(event.status):
            raise ValidationError(f"{label} is not settled.")
```

~line 691:
```python
    if not is_settled(snapshot.outbox_event.status):
        raise ValidationError(
            "Correction publication snapshot must be settled before finalization."
        )
```

`src/lamto/finance/models/corrections.py`: add `is_settled` to the evidence import (line 5). In `Correction.is_resident_visible` (~line 40):

```python
        if not is_settled(snapshot.outbox_event.status):
            return False
```

In `Correction.status` (~line 78):

```python
            if is_settled(snap.outbox_event.status):
                return "APPROVED"
```

`src/lamto/web/action_inbox.py`: add `SETTLED_STATUSES` to its `lamto.evidence.models` import; at ~line 491–495:

```python
    # Snapshots waiting finalize (settled outbox)
    snaps = PublicationSnapshot.objects.filter(
        proposal__work_order__case__building_id=building_id,
        outbox_event__status__in=SETTLED_STATUSES,
    ).exclude(
```

Also update the item summary two lines below from `f"Snapshot #{snap.pk} confirmed — finalize pending"` to `f"Snapshot #{snap.pk} settled — finalize pending"`.

`src/lamto/finance/management/commands/finalize_publications.py`:

```python
from django.core.management.base import BaseCommand

from lamto.evidence.models import SETTLED_STATUSES
from lamto.finance.models import PublicationSnapshot, PublishedLedgerEntry
from lamto.finance.publication import finalize_publication


class Command(BaseCommand):
    help = "Finalize settled publication snapshots into ledger and fund postings."

    def handle(self, *args, **options):
        pending = (
            PublicationSnapshot.objects.filter(
                outbox_event__status__in=SETTLED_STATUSES,
            )
            .exclude(pk__in=PublishedLedgerEntry.objects.values("snapshot_id"))
            .order_by("pk")
        )
        finalized = 0
        for snapshot in pending.iterator():
            finalize_publication(snapshot.pk)
            finalized += 1
        self.stdout.write(str(finalized))
```

`src/lamto/config/worker.py`, in `process_publication_finalization_batch`: change the local import to `from lamto.evidence.models import SETTLED_STATUSES` (drop `BlockchainOutboxEvent`) and both queries (~lines 96–98 and 110–112) to:

```python
                outbox_event__status__in=SETTLED_STATUSES,
```

`src/lamto/testing/factories.py`, in `attempt_publication` (~line 866), extend the message map so the outage e2e keeps its pilot phrasing:

```python
            if (
                "not chain-confirmed" in messages
                or "chain-confirmed" in messages
                or "not settled" in messages
            ):
                reason = "Required blockchain evidence is still pending"
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/finance/tests/test_settled_gates.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite (gate-sweep regression)**

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS — including all six e2e journeys (`tests/e2e/`), the isolation suite, and the publication/correction/fund suites, all under the default `besu` backend.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/finance/publication.py src/lamto/finance/selectors.py src/lamto/finance/fund.py \
        src/lamto/finance/corrections.py src/lamto/finance/models/corrections.py \
        src/lamto/web/action_inbox.py src/lamto/finance/management/commands/finalize_publications.py \
        src/lamto/config/worker.py src/lamto/testing/factories.py \
        src/lamto/finance/tests/test_settled_gates.py
git commit -m "feat: settlement gates accept LOCAL-settled evidence"
```

---

### Task 5: Integrity observations skip the chain for `LOCAL`/disabled — never fake it

**Files:**
- Modify: `src/lamto/finance/integrity.py` (`_check_chain_records` ~line 40, result branch ~line 163)
- Modify: `src/lamto/testing/factories.py` (`verify_latest_ledger_entry` chain check ~line 989)
- Test: `src/lamto/finance/tests/test_integrity.py` (append a new test class)

**Interfaces:**
- Consumes: `is_settled` (Task 1), `settings.EVIDENCE_ANCHORING_BACKEND` (Task 2).
- Produces:
  - `_check_chain_records` details entries: `{"result": "SKIPPED_ANCHORING_DISABLED"}` (disabled mode, all events) and `{"result": "SKIPPED_LOCAL"}` (besu mode, per LOCAL event); `details["anchoring_backend"] == "disabled"` in disabled mode
  - `verify_published_entry` result rule: when the chain is unreachable/skipped, `VERIFIED` iff documents verified **and** every related event `is_settled`; otherwise `UNAVAILABLE`. Document mismatches still dominate as `MISMATCH`.

- [ ] **Step 1: Write the failing tests**

Append to `src/lamto/finance/tests/test_integrity.py` (keep existing content; add imports only if not already present: `tempfile`, `override_settings`, `PilotDomainDriver`, `seed_pilot_world`):

```python
import tempfile

from django.test import TestCase, override_settings

from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.integrity import verify_published_entry
from lamto.finance.models import PublishedLedgerEntry, VerificationObservation
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world

_ANCHOR_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-integrity-anchor-")


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _ANCHOR_TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _ANCHOR_TEMP_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class AnchoringAwareIntegrityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seed = seed_pilot_world(
            building_name="Integrity Anchor Building", create_sample_report=False
        )
        driver = PilotDomainDriver(cls.seed)
        driver.prepare_locally_approved_normal_work(None)
        driver.complete_assigned_work()
        driver.accept_and_record_payment()
        driver.verify_payment()
        driver.confirm_all_chain_events()
        driver.sign_publication_snapshot()
        driver.confirm_all_chain_events()
        cls.entry = PublishedLedgerEntry.objects.get(
            case__building=cls.seed.building
        )

    def test_disabled_mode_skips_chain_checks_without_faking(self):
        with override_settings(EVIDENCE_ANCHORING_BACKEND="disabled"):
            observation = verify_published_entry(self.entry.pk)

        self.assertEqual(
            observation.result, VerificationObservation.Result.VERIFIED
        )
        self.assertEqual(observation.details.get("anchoring_backend"), "disabled")
        results = {check["result"] for check in observation.details["chain_checks"]}
        self.assertEqual(results, {"SKIPPED_ANCHORING_DISABLED"})

    def test_local_events_are_skipped_not_faked_in_besu_mode(self):
        snapshot_event_id = self.entry.snapshot.outbox_event_id
        BlockchainOutboxEvent.objects.filter(pk=snapshot_event_id).update(
            status=BlockchainOutboxEvent.Status.LOCAL, confirmed_at=None
        )

        observation = verify_published_entry(self.entry.pk)

        by_event = {
            check["event_id"]: check["result"]
            for check in observation.details["chain_checks"]
        }
        self.assertEqual(
            by_event[self.entry.snapshot.outbox_event.event_id], "SKIPPED_LOCAL"
        )
        # Documents verified and every event settled: VERIFIED even though the
        # chain is unreachable in the test environment.
        self.assertEqual(
            observation.result, VerificationObservation.Result.VERIFIED
        )

    def test_unsettled_event_downgrades_to_unavailable(self):
        snapshot_event_id = self.entry.snapshot.outbox_event_id
        BlockchainOutboxEvent.objects.filter(pk=snapshot_event_id).update(
            status=BlockchainOutboxEvent.Status.PENDING, confirmed_at=None
        )

        with override_settings(EVIDENCE_ANCHORING_BACKEND="disabled"):
            observation = verify_published_entry(self.entry.pk)

        self.assertEqual(
            observation.result, VerificationObservation.Result.UNAVAILABLE
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/finance/tests/test_integrity.py -q`
Expected: the three new tests FAIL (`anchoring_backend` key missing / no `SKIPPED_*` results); existing tests PASS.

- [ ] **Step 3: Implement the skip logic**

In `src/lamto/finance/integrity.py`, add imports:

```python
from django.conf import settings
```

and extend the evidence import:

```python
from lamto.evidence.models import BlockchainOutboxEvent, is_settled
```

Replace `_check_chain_records` entirely:

```python
def _check_chain_records(events):
    """Return (chain_ok, chain_unavailable, details).

    Chain-dependent checks are skipped, never faked (spec 5.2): disabled mode
    skips every event; besu mode skips LOCAL-settled events individually.
    """
    if settings.EVIDENCE_ANCHORING_BACKEND == "disabled":
        return None, True, {
            "anchoring_backend": "disabled",
            "chain_checks": [
                {
                    "event_id": event.event_id,
                    "local_status": event.status,
                    "result": "SKIPPED_ANCHORING_DISABLED",
                }
                for event in events
            ],
        }

    details = {"chain_checks": []}
    chain_events = []
    for event in events:
        if event.status == BlockchainOutboxEvent.Status.LOCAL:
            details["chain_checks"].append(
                {
                    "event_id": event.event_id,
                    "local_status": event.status,
                    "result": "SKIPPED_LOCAL",
                }
            )
        else:
            chain_events.append(event)
    if not chain_events:
        return None, True, details

    try:
        from lamto.evidence.chain import EvidenceRegistryClient

        client = EvidenceRegistryClient()
    except Exception as exc:  # pragma: no cover - import/config failure path
        details["chain_error"] = str(exc)
        return None, True, details

    any_unavailable = False
    any_mismatch = False
    for event in chain_events:
        check = {
            "event_id": event.event_id,
            "local_payload_hash": event.payload_hash,
            "local_status": event.status,
        }
        try:
            record = client.find(event)
        except Exception as exc:
            any_unavailable = True
            check["result"] = "UNAVAILABLE"
            check["error"] = str(exc)
            details["chain_checks"].append(check)
            continue
        if record is None:
            if event.status == BlockchainOutboxEvent.Status.CONFIRMED:
                # Local confirmation without on-chain record in test/dev: soft unavailable.
                any_unavailable = True
                check["result"] = "UNAVAILABLE"
                check["error"] = "chain record missing"
            else:
                any_unavailable = True
                check["result"] = "UNAVAILABLE"
            details["chain_checks"].append(check)
            continue
        on_chain = record.payload_hash.removeprefix("0x")
        local = event.payload_hash.removeprefix("0x")
        check["chain_payload_hash"] = on_chain
        if on_chain != local:
            any_mismatch = True
            check["result"] = "MISMATCH"
        else:
            check["result"] = "VERIFIED"
        details["chain_checks"].append(check)

    if any_mismatch:
        return False, False, details
    if any_unavailable:
        return None, True, details
    return True, False, details
```

In `verify_published_entry`, replace the `elif chain_unavailable:` branch (~lines 162–168):

```python
        elif chain_unavailable:
            # Documents verified; chain not independently reachable or anchoring
            # skipped. Prefer VERIFIED when every local outbox event is settled.
            if all(is_settled(event.status) for event in events):
                result = VerificationObservation.Result.VERIFIED
            else:
                result = VerificationObservation.Result.UNAVAILABLE
```

In `src/lamto/testing/factories.py`, `verify_latest_ledger_entry` (~line 989), update the chain acceptance check:

```python
        # Chain may be UNAVAILABLE without live Besu; accept settled events as match.
        chain_ok = observation.result in {observation.Result.VERIFIED, "VERIFIED"} or all(
            is_settled(e.status)
            for e in BlockchainOutboxEvent.objects.filter(
                event_id__in=observation.checked_chain_event_ids
            )
        )
```

Add `is_settled` to the factories' `lamto.evidence.models` import.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/finance/tests/test_integrity.py tests/e2e -q`
Expected: PASS (including the tamper e2e, which exercises the document-MISMATCH dominance path).

- [ ] **Step 5: Commit**

```bash
git add src/lamto/finance/integrity.py src/lamto/testing/factories.py src/lamto/finance/tests/test_integrity.py
git commit -m "feat: integrity checks skip chain for local or disabled anchoring"
```

---

### Task 6: Evidence-level labels across staff, resident, export, and health surfaces

**Files:**
- Modify: `src/lamto/finance/approvals.py` (labels ~line 18, `proposal_verification_label` ~line 240)
- Modify: `src/lamto/finance/emergencies.py` (labels ~line 21, `emergency_verification_label` ~line 343)
- Modify: `src/lamto/web/views/resident.py` (`ledger_detail` ~line 246)
- Modify: `src/lamto/web/templates/web/resident/ledger_detail.html`
- Modify: `src/lamto/web/views/exports.py` (`_outbox_rows` ~line 288)
- Modify: `src/lamto/web/views/health.py` (`collect_health_snapshot` ~line 83, `collect_pilot_metrics` ~line 152)
- Modify: `src/lamto/web/templates/web/staff/audit_search.html` (~line 20)
- Test: `src/lamto/web/tests/test_evidence_level_labels.py`

**Interfaces:**
- Consumes: `EvidenceLevel`, `evidence_level`, `is_settled` (Task 1), `BlockchainOutboxEvent.evidence_level` property (Task 1).
- Produces:
  - `lamto.finance.approvals.LOCAL_SIGNED_LABEL = "Signed and hash-locked (off-chain)"` (same constant added to `emergencies.py`)
  - Three-way staff labels: any unsettled → `PENDING_ANCHORING_LABEL`; all `CONFIRMED` → `ANCHORED_LABEL`; all settled with any `LOCAL` → `LOCAL_SIGNED_LABEL`
  - Resident detail context keys: `evidence_level`, `anchoring_label`, `anchoring_class`, `anchoring_icon`
  - `_outbox_rows` CSV gains an `evidence_level` column (enum value verbatim)
  - Health snapshot and pilot metrics gain `anchoring_backend`

- [ ] **Step 1: Write the failing tests**

Create `src/lamto/web/tests/test_evidence_level_labels.py`:

```python
"""LOCAL_SIGNED never borrows CHAIN_CONFIRMED presentation (spec 5.1/5.2)."""

import tempfile

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from lamto.evidence.models import BlockchainOutboxEvent
from lamto.finance.approvals import (
    ANCHORED_LABEL,
    LOCAL_SIGNED_LABEL,
    PENDING_ANCHORING_LABEL,
    proposal_verification_label,
)
from lamto.finance.models import PublishedLedgerEntry
from lamto.testing.factories import PilotDomainDriver, seed_pilot_world
from lamto.web.views.exports import _outbox_rows
from lamto.web.views.health import collect_health_snapshot

_TEMP_STORAGE = tempfile.mkdtemp(prefix="lamto-evidence-labels-")


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": _TEMP_STORAGE},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class EvidenceLevelLabelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seed = seed_pilot_world(
            building_name="Label Building", create_sample_report=False
        )
        driver = PilotDomainDriver(cls.seed)
        driver.prepare_locally_approved_normal_work(None)
        driver.complete_assigned_work()
        driver.accept_and_record_payment()
        driver.verify_payment()
        driver.confirm_all_chain_events()
        driver.sign_publication_snapshot()
        driver.confirm_all_chain_events()
        cls.entry = PublishedLedgerEntry.objects.get(case__building=cls.seed.building)

    def _proposal_event_ids(self):
        version = self.entry.proposal.current_version
        ids = [version.outbox_event_id]
        ids.extend(
            BlockchainOutboxEvent.objects.filter(
                approval_decision__version=version
            ).values_list("pk", flat=True)
        )
        return ids

    def test_staff_label_is_three_way(self):
        version = self.entry.proposal.current_version
        self.assertEqual(proposal_verification_label(version), ANCHORED_LABEL)

        BlockchainOutboxEvent.objects.filter(pk__in=self._proposal_event_ids()).update(
            status=BlockchainOutboxEvent.Status.LOCAL, confirmed_at=None
        )
        self.assertEqual(proposal_verification_label(version), LOCAL_SIGNED_LABEL)

        BlockchainOutboxEvent.objects.filter(pk=version.outbox_event_id).update(
            status=BlockchainOutboxEvent.Status.PENDING
        )
        self.assertEqual(proposal_verification_label(version), PENDING_ANCHORING_LABEL)

    def test_resident_detail_shows_offchain_label_for_local(self):
        BlockchainOutboxEvent.objects.filter(
            pk=self.entry.snapshot.outbox_event_id
        ).update(status=BlockchainOutboxEvent.Status.LOCAL, confirmed_at=None)
        client = Client()
        client.force_login(self.seed.users["resident"])

        response = client.get(
            reverse("web:ledger-detail", kwargs={"pk": self.entry.pk})
        )

        self.assertContains(response, "anchoring is off for this deployment")
        self.assertNotContains(response, "Blockchain anchored")

    def test_resident_detail_shows_anchored_for_confirmed(self):
        client = Client()
        client.force_login(self.seed.users["resident"])

        response = client.get(
            reverse("web:ledger-detail", kwargs={"pk": self.entry.pk})
        )

        self.assertContains(response, "Blockchain anchored")
        self.assertNotContains(response, "anchoring is off for this deployment")

    def test_outbox_export_carries_evidence_level_verbatim(self):
        BlockchainOutboxEvent.objects.filter(
            pk=self.entry.snapshot.outbox_event_id
        ).update(status=BlockchainOutboxEvent.Status.LOCAL, confirmed_at=None)

        header, rows = _outbox_rows(self.seed.building.pk)

        self.assertIn("evidence_level", header)
        level_by_event = {
            row[header.index("event_id")]: row[header.index("evidence_level")]
            for row in rows
        }
        snapshot_event = self.entry.snapshot.outbox_event
        self.assertEqual(level_by_event[snapshot_event.event_id], "LOCAL_SIGNED")
        self.assertIn("CHAIN_CONFIRMED", set(level_by_event.values()))

    def test_health_snapshot_reports_anchoring_backend(self):
        self.assertEqual(collect_health_snapshot()["anchoring_backend"], "besu")
        with override_settings(EVIDENCE_ANCHORING_BACKEND="disabled"):
            self.assertEqual(
                collect_health_snapshot()["anchoring_backend"], "disabled"
            )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_evidence_level_labels.py -q`
Expected: FAIL — `ImportError: cannot import name 'LOCAL_SIGNED_LABEL'`.

- [ ] **Step 3: Implement the label surfaces**

`src/lamto/finance/approvals.py`: add `is_settled` to the evidence import; add the constant next to the existing two (~line 19):

```python
LOCAL_SIGNED_LABEL = "Signed and hash-locked (off-chain)"
```

Replace the tail of `proposal_verification_label` (~lines 250–252):

```python
    if any(not is_settled(event.status) for event in events):
        return PENDING_ANCHORING_LABEL
    if all(
        event.status == BlockchainOutboxEvent.Status.CONFIRMED for event in events
    ):
        return ANCHORED_LABEL
    return LOCAL_SIGNED_LABEL
```

`src/lamto/finance/emergencies.py`: same constant after line 22, add `is_settled` to the evidence import, and replace the tail of `emergency_verification_label` (~lines 359–361):

```python
    if any(not is_settled(event.status) for event in events):
        return PENDING_ANCHORING_LABEL
    if all(
        event.status == BlockchainOutboxEvent.Status.CONFIRMED for event in events
    ):
        return ANCHORED_LABEL
    return LOCAL_SIGNED_LABEL
```

`src/lamto/web/views/resident.py`: add the import:

```python
from lamto.evidence.models import EvidenceLevel, evidence_level
```

Add after `_integrity_display`:

```python
def _evidence_level_display(level):
    """Distinct presentation per level; LOCAL_SIGNED never borrows chain wording (spec 5.2)."""
    if level == EvidenceLevel.CHAIN_CONFIRMED:
        return {"label": "Blockchain anchored", "css_class": "status-verified", "icon": "✓"}
    if level == EvidenceLevel.LOCAL_SIGNED:
        return {
            "label": "Signed and hash-locked — blockchain anchoring is off for this deployment",
            "css_class": "status-info",
            "icon": "◆",
        }
    if level == EvidenceLevel.MISMATCH:
        return {"label": "Anchoring mismatch detected", "css_class": "status-mismatch", "icon": "!"}
    return {"label": "Pending blockchain anchoring", "css_class": "status-warning", "icon": "○"}
```

In `ledger_detail`, before the `return render(...)`:

```python
    snapshot_level = evidence_level(entry.snapshot.outbox_event.status)
    anchoring = _evidence_level_display(snapshot_level)
```

and add to the context dict (next to the `integrity_*` keys):

```python
            "evidence_level": snapshot_level,
            "anchoring_label": anchoring["label"],
            "anchoring_class": anchoring["css_class"],
            "anchoring_icon": anchoring["icon"],
```

`src/lamto/web/templates/web/resident/ledger_detail.html`: inside the first `<dl class="detail-list">`, after the "Integrity status" `<div>`:

```html
    <div>
      <dt>Evidence anchoring</dt>
      <dd>
        <span class="status {{ anchoring_class }}">
          <span class="status-icon" aria-hidden="true">{{ anchoring_icon }}</span>
          {{ anchoring_label }}
        </span>
      </dd>
    </div>
```

and replace the Transaction IDs empty state (`<p class="empty">No on-chain transaction IDs recorded yet.</p>`) with:

```html
  {% if evidence_level == "LOCAL_SIGNED" %}
  <p class="empty">Blockchain anchoring is off for this deployment. Records are signed and hash-locked locally.</p>
  {% else %}
  <p class="empty">No on-chain transaction IDs recorded yet.</p>
  {% endif %}
```

`src/lamto/web/views/exports.py`, `_outbox_rows`: insert `"evidence_level"` into the header list directly after `"status"`, and in the row append `event.evidence_level` directly after `event.status`:

```python
    header = [
        "id",
        "event_id",
        "event_type",
        "payload_hash",
        "status",
        "evidence_level",
        "transaction_hash",
        "chain_confirmed_block",
        "signer_wallet_address",
        "created_at",
        "confirmed_at",
    ]
```
```python
                event.status,
                event.evidence_level,
                event.transaction_hash,
```

`src/lamto/web/views/health.py`: add `from django.conf import settings` to the imports; in `collect_health_snapshot`'s return dict (after `"outbox_status_counts"`):

```python
        "anchoring_backend": settings.EVIDENCE_ANCHORING_BACKEND,
```

and the same key in `collect_pilot_metrics`'s return dict (before `"authoritative"`). The existing `anchoring_delay_seconds_avg` and `last_confirmed_*` computations already filter on `CONFIRMED` only — they stay chain-honest with no change; `LOCAL` counts surface via the existing `outbox_status_counts`.

`src/lamto/web/templates/web/staff/audit_search.html`: after the Status row (line 20), add:

```html
    <div><dt>Evidence level</dt><dd>{{ outbox_event.evidence_level }}</dd></div>
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest src/lamto/web/tests/test_evidence_level_labels.py src/lamto/web/tests src/lamto/finance/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lamto/finance/approvals.py src/lamto/finance/emergencies.py \
        src/lamto/web/views/resident.py src/lamto/web/templates/web/resident/ledger_detail.html \
        src/lamto/web/views/exports.py src/lamto/web/views/health.py \
        src/lamto/web/templates/web/staff/audit_search.html \
        src/lamto/web/tests/test_evidence_level_labels.py
git commit -m "feat: evidence-level labels across resident, staff, export, health surfaces"
```

---

### Task 7: Disabled-mode journey — publication, fund, and correction flows

**Files:**
- Test: `tests/e2e/test_anchoring_disabled_mode.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6; `process_due_outbox_events` (real worker settle), `process_publication_finalization_batch` (real finalization batch), `PilotDomainDriver` with `pause_chain()` (suppresses the driver's fake `CONFIRMED` updates so the real worker does the settling), `seed.sign_typed`, `temp_storage`/`page`/`settings` fixtures from `tests/e2e/conftest.py`.
- Produces: the spec §5.4 disabled-mode regression gate — the P1 publication → fund → correction chain end-to-end with `EVIDENCE_ANCHORING_BACKEND=disabled`, all evidence `LOCAL_SIGNED`, honestly labeled.

- [ ] **Step 1: Write the journey test**

Create `tests/e2e/test_anchoring_disabled_mode.py`:

```python
"""Disabled anchoring: publication, fund, and correction flows settle LOCAL (spec 5.2/5.4).

The driver's chain is paused so it never fake-confirms; the REAL worker
(`process_due_outbox_events`) performs every settlement, constructing no chain
client. Nothing may present LOCAL_SIGNED as chain confirmation.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from lamto.config.worker import process_publication_finalization_batch
from lamto.documents.models import Document
from lamto.evidence.canonical import payload_hash
from lamto.evidence.models import BlockchainOutboxEvent, EvidenceLevel
from lamto.evidence.worker import process_due_outbox_events
from lamto.finance.corrections import (
    _correction_resident_payload,
    allocate_correction_id,
    allocate_correction_publication_id,
    build_correction_evidence_typed_data,
    create_correction,
    decide_correction,
    finalize_correction_publication,
    prepare_correction_publication,
)
from lamto.finance.fund import (
    allocate_fund_entry_id,
    build_fund_source_evidence_typed_data,
    build_fund_verification_evidence_typed_data,
    fund_balance,
    get_or_create_fund,
    record_fund_source,
    verify_fund_source,
)
from lamto.finance.integrity import verify_published_entry
from lamto.finance.models import (
    CorrectionDecision,
    MaintenanceFundEntry,
    PublishedLedgerEntry,
    VerificationObservation,
)
from lamto.finance.selectors import published_ledger_entries
from lamto.testing.factories import PilotDomainDriver, new_event_id, seed_pilot_world

pytestmark = pytest.mark.django_db

ZERO_BARE = "00" * 32
Status = BlockchainOutboxEvent.Status


def _settle_locally():
    """Run the real worker; in disabled mode every due event settles LOCAL."""
    for event in process_due_outbox_events():
        assert event.status == Status.LOCAL, event.status


def test_disabled_mode_publication_fund_and_correction_flows(page, temp_storage, settings):
    settings.EVIDENCE_ANCHORING_BACKEND = "disabled"
    seed = seed_pilot_world(
        building_name="Offchain Building", create_sample_report=False
    )
    driver = PilotDomainDriver(seed)
    # seed_opening_fund fake-confirms its two events (a legitimate mixed
    # history); everything queued after this line must settle LOCAL.
    preconfirmed = set(
        BlockchainOutboxEvent.objects.filter(status=Status.CONFIRMED).values_list(
            "pk", flat=True
        )
    )
    driver.pause_chain()

    # --- Publication flow -------------------------------------------------
    driver.prepare_locally_approved_normal_work(page)
    driver.complete_assigned_work()
    driver.accept_and_record_payment()
    driver.verify_payment()
    _settle_locally()

    snapshot = driver.sign_publication_snapshot()  # prerequisites are LOCAL-settled
    _settle_locally()
    batch = process_publication_finalization_batch()
    assert batch.ok, batch.detail

    entry = PublishedLedgerEntry.objects.get(case__building=seed.building)
    assert entry.snapshot_id == snapshot.pk
    snapshot.outbox_event.refresh_from_db()
    assert snapshot.outbox_event.status == Status.LOCAL
    assert snapshot.outbox_event.transaction_hash == ""
    assert snapshot.outbox_event.confirmed_at is None
    assert snapshot.anchoring_backend == "disabled"
    assert snapshot.settled_evidence_level == EvidenceLevel.LOCAL_SIGNED

    # Nothing queued in disabled mode ever became CONFIRMED, nothing is pending.
    flow_events = BlockchainOutboxEvent.objects.filter(building=seed.building)
    assert not flow_events.filter(status=Status.PENDING).exists()
    assert not (
        flow_events.filter(status=Status.CONFIRMED)
        .exclude(pk__in=preconfirmed)
        .exists()
    )

    # Resident visibility with the honest off-chain label.
    assert entry.pk in [row.pk for row in published_ledger_entries(seed.building.pk)]
    web = Client()
    web.force_login(seed.users["resident"])
    response = web.get(reverse("web:ledger-detail", kwargs={"pk": entry.pk}))
    body = response.content.decode()
    assert "anchoring is off for this deployment" in body
    assert "Blockchain anchored" not in body

    # Integrity observation: documents checked, chain skipped, never faked.
    observation = verify_published_entry(entry.pk)
    assert observation.result == VerificationObservation.Result.VERIFIED
    assert observation.details.get("anchoring_backend") == "disabled"
    assert {c["result"] for c in observation.details["chain_checks"]} == {
        "SKIPPED_ANCHORING_DISABLED"
    }

    balance_after_publication = fund_balance(seed.building.pk, verified_only=True)

    # --- Fund flow (maker-checker stays mandatory) ------------------------
    fund = get_or_create_fund(seed.building)
    recorder = seed.roles["fund_recorder"]
    verifier = seed.roles["fund_verifier"]
    original, redacted = seed.document_pair(
        Document.Kind.CONTRACT, recorder.user, "offchain-inflow"
    )
    entry_id = allocate_fund_entry_id()
    event_id = new_event_id()
    ts = timezone.now()
    typed = build_fund_source_evidence_typed_data(
        fund,
        recorder,
        entry_id,
        MaintenanceFundEntry.EntryType.INFLOW,
        5_000_000,
        original,
        redacted,
        event_id,
        timestamp=ts,
    )
    inflow = record_fund_source(
        fund,
        MaintenanceFundEntry.EntryType.INFLOW,
        5_000_000,
        original,
        redacted,
        recorder,
        seed.sign_typed(recorder, typed),
        event_id,
        fund_entry_id=entry_id,
        timestamp=ts,
    )
    verify_event = new_event_id()
    verify_typed = build_fund_verification_evidence_typed_data(
        inflow, verifier, verify_event, timestamp=inflow.recorded_at
    )
    verify_fund_source(
        inflow,
        verifier,
        seed.sign_typed(verifier, verify_typed),
        verify_event,
        timestamp=inflow.recorded_at,
    )
    # Unsettled source does not count yet; LOCAL settlement makes it count.
    assert fund_balance(seed.building.pk, verified_only=True) == balance_after_publication
    _settle_locally()
    assert (
        fund_balance(seed.building.pk, verified_only=True)
        == balance_after_publication + 5_000_000
    )

    # --- Correction flow ---------------------------------------------------
    operator = seed.roles["correction_operator"]
    board = seed.roles["correction_board"]
    rep = seed.roles["resident_representative"]
    publisher = seed.roles["eligible_publisher"]
    original_cost = entry.actual_cost_vnd
    new_amount = original_cost - 500_000
    balance_before_correction = fund_balance(seed.building.pk, verified_only=True)

    evidence_o, _ = seed.document_pair(
        Document.Kind.CORRECTION_EVIDENCE, operator.user, "offchain-corr"
    )
    replacement_hashes = [evidence_o.sha256]
    correction_id = allocate_correction_id()
    create_ts = timezone.now()
    create_event = new_event_id()
    create_typed = build_correction_evidence_typed_data(
        correction_id=correction_id,
        original_event_id=entry.snapshot.outbox_event.event_id,
        original_hash=entry.snapshot.outbox_event.payload_hash,
        replacement_hashes=replacement_hashes,
        reason="Invoice arithmetic error",
        decision="APPROVE",
        actor_organization_id=operator.organization_id,
        publisher_snapshot_hash=ZERO_BARE,
        event_id=create_event,
        timestamp=create_ts,
        previous_hash="0x" + entry.snapshot.outbox_event.payload_hash,
    )
    correction = create_correction(
        entry,
        operator,
        "Invoice arithmetic error",
        {"actual_cost_vnd": new_amount, "contractor_name": entry.contractor_name},
        [evidence_o],
        seed.sign_typed(operator, create_typed),
        create_event,
        correction_id=correction_id,
        timestamp=create_ts,
    )
    _settle_locally()  # creation must be settled before decisions

    decisions = {}
    previous_hash = "0x" + correction.outbox_event.payload_hash
    for actor, stage in (
        (board, CorrectionDecision.Stage.BOARD),
        (rep, CorrectionDecision.Stage.RESIDENT_REP),
    ):
        decide_ts = timezone.now()
        decide_event = new_event_id()
        decide_typed = build_correction_evidence_typed_data(
            correction_id=correction.pk,
            original_event_id=entry.snapshot.outbox_event.event_id,
            original_hash=entry.snapshot.outbox_event.payload_hash,
            replacement_hashes=replacement_hashes,
            reason="approve",
            decision="APPROVE",
            actor_organization_id=actor.organization_id,
            publisher_snapshot_hash=ZERO_BARE,
            event_id=decide_event,
            timestamp=decide_ts,
            previous_hash=previous_hash,
        )
        decision = decide_correction(
            correction,
            actor,
            stage,
            "APPROVE",
            "approve",
            seed.sign_typed(actor, decide_typed),
            decide_event,
            timestamp=decide_ts,
        )
        decisions[stage] = decision
        previous_hash = "0x" + decision.outbox_event.payload_hash
        _settle_locally()

    snapshot_id = allocate_correction_publication_id()
    pub_ts = timezone.now()
    pub_event = new_event_id()
    resident_payload_hash = payload_hash(_correction_resident_payload(correction))
    pub_typed = build_correction_evidence_typed_data(
        correction_id=correction.pk,
        original_event_id=entry.snapshot.outbox_event.event_id,
        original_hash=entry.snapshot.outbox_event.payload_hash,
        replacement_hashes=replacement_hashes,
        reason=correction.reason,
        decision="APPROVE",
        actor_organization_id=publisher.organization_id,
        publisher_snapshot_hash=resident_payload_hash,
        event_id=pub_event,
        timestamp=pub_ts,
        previous_hash="0x"
        + decisions[CorrectionDecision.Stage.RESIDENT_REP].outbox_event.payload_hash,
    )
    corr_snapshot = prepare_correction_publication(
        correction,
        publisher,
        seed.sign_typed(publisher, pub_typed),
        pub_event,
        snapshot_id=snapshot_id,
        timestamp=pub_ts,
    )
    _settle_locally()
    finalize_correction_publication(corr_snapshot.pk)

    correction.refresh_from_db()
    entry.refresh_from_db()
    assert entry.actual_cost_vnd == original_cost  # original is append-only
    assert correction.is_resident_visible
    corr_snapshot.outbox_event.refresh_from_db()
    assert corr_snapshot.outbox_event.status == Status.LOCAL

    reversal = MaintenanceFundEntry.objects.get(
        correction=correction, entry_type=MaintenanceFundEntry.EntryType.REVERSAL
    )
    replacement = MaintenanceFundEntry.objects.get(
        correction=correction, entry_type=MaintenanceFundEntry.EntryType.REPLACEMENT
    )
    assert reversal.amount_vnd == original_cost
    assert replacement.amount_vnd == -new_amount
    assert fund_balance(seed.building.pk, verified_only=True) == (
        balance_before_correction + original_cost - new_amount
    )
```

- [ ] **Step 2: Run the journey**

Run: `.venv/bin/python -m pytest tests/e2e/test_anchoring_disabled_mode.py -q`
Expected: PASS. If the correction choreography errors on an argument name, cross-check against the working besu-mode dance in `tests/e2e/test_tamper_and_correction.py` — the two must stay parallel except for `confirm_event(...)` vs `_settle_locally()`.

(Note: `seed_pilot_world` seeds an opening fund balance whose events are `CONFIRMED` by the seed helper — that is a legitimate mixed-history deployment. The flow assertions therefore check the expenditure/correction/inflow events specifically, plus "no CONFIRMED without a tx hash" globally.)

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS — both anchoring modes now have permanent regression coverage (spec §5.4 gate 2).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_anchoring_disabled_mode.py
git commit -m "test: disabled-mode publication, fund, and correction journey"
```

---

### Task 8: Chain-payload opacity audit, secure event-ID randomness, mode-switch runbook

**Files:**
- Test: `src/lamto/evidence/tests/test_chain_opacity.py`
- Modify: `src/lamto/web/static/web/wallet-signing.js` (`randomBytes32`, lines 17–30)
- Modify: `ops/pilot-runbook.md` (new section after "## Tenant integrity (nightly)")

**Interfaces:**
- Consumes: `EVIDENCE_PAYLOAD_SCHEMAS` (`lamto/evidence/services.py`).
- Produces: a permanent schema-lockdown test (spec §2.2 audit) and the spec §5.2 mode-switch runbook entry.

**Audit scope (what the chain can observe).** `EvidenceRegistryClient.submit` transmits exactly `(event_id, payload_hash, previous_hash, event_type, signer, signature)` — payload bodies never leave the database. Opacity therefore rests on: (a) event IDs being random 32-byte values, (b) payload hashes being non-invertible, which holds because every payload schema requires at least one 256-bit hash/digest field (unknown to outsiders), and (c) payload schemas never growing free-text fields such as building names. The tests below freeze (b) and (c); (a) is enforced server-side by the `outbox_event_id_bytes32` DB constraint + `BYTES32_RE` validation in `queue_signed_event` (already tested), and client-side by removing the predictable `Math.random()` fallback.

- [ ] **Step 1: Write the failing test**

Create `src/lamto/evidence/tests/test_chain_opacity.py`:

```python
"""Chain-payload opacity audit (spec 2.2).

Only opaque values reach the chain: random event IDs and payload hashes.
These tests freeze the properties that keep payload hashes non-invertible
and keep identifying free text (building names, personal content) out of
evidence payload schemas forever.
"""

from django.test import SimpleTestCase

from lamto.evidence.models import EvidenceType
from lamto.evidence.services import EVIDENCE_PAYLOAD_SCHEMAS

# Closed vocabulary of value shapes. Anything else — in particular any
# free-text shape — is an opacity regression and must not be added.
OPAQUE_SHAPES = {"id", "positive_int", "money", "bool", "hash", "hashes", "bytes32", "timestamp"}
HASH_SHAPES = {"hash", "hashes", "bytes32"}


class ChainOpacityTests(SimpleTestCase):
    def test_every_event_type_has_a_schema(self):
        self.assertEqual(set(EVIDENCE_PAYLOAD_SCHEMAS), set(EvidenceType.values))

    def test_payload_schemas_admit_only_opaque_shapes(self):
        for event_type, (required, optional) in EVIDENCE_PAYLOAD_SCHEMAS.items():
            for field, shape in {**required, **optional}.items():
                with self.subTest(event_type=event_type, field=field):
                    if isinstance(shape, frozenset):
                        # Closed enums only: uppercase machine tokens, no names.
                        for member in shape:
                            self.assertRegex(member, r"^[A-Z_]+$")
                    else:
                        self.assertIn(shape, OPAQUE_SHAPES)

    def test_every_schema_requires_a_hash_field(self):
        # At least one 256-bit unknown per payload keeps the on-chain
        # payload hash non-invertible by dictionary attack.
        for event_type, (required, _optional) in EVIDENCE_PAYLOAD_SCHEMAS.items():
            with self.subTest(event_type=event_type):
                self.assertTrue(
                    HASH_SHAPES.intersection(required.values()),
                    f"event type {event_type} has no required hash field",
                )
```

- [ ] **Step 2: Run the test**

Run: `.venv/bin/python -m pytest src/lamto/evidence/tests/test_chain_opacity.py -q`
Expected: PASS immediately (the audit confirms current schemas are already opaque — the tests exist to fail on future regressions). If any assertion fails, that is a real finding: stop and report it rather than loosening the test.

- [ ] **Step 3: Remove the predictable event-ID fallback**

In `src/lamto/web/static/web/wallet-signing.js`, replace `randomBytes32` (lines 17–30):

```js
  function randomBytes32() {
    // Event IDs must be cryptographically random (spec 2.2): a predictable ID
    // would leak submission ordering to chain observers. No Math.random fallback.
    if (!global.crypto || typeof global.crypto.getRandomValues !== "function") {
      throw new Error("Secure random generator unavailable; cannot sign evidence.");
    }
    var bytes = new Uint8Array(32);
    global.crypto.getRandomValues(bytes);
    var hex = "";
    for (var j = 0; j < bytes.length; j++) {
      hex += bytes[j].toString(16).padStart(2, "0");
    }
    return "0x" + hex;
  }
```

(No JS test harness exists; `crypto.getRandomValues` is universal in the supported staff browsers, so the throw path is defensive. Manual check: staff proposal-approval form still signs in a browser session, or rely on the unchanged e2e signing paths which bypass JS.)

- [ ] **Step 4: Add the mode-switch runbook section**

In `ops/pilot-runbook.md`, insert after the "## Tenant integrity (nightly)" section:

```markdown
## Anchoring mode switch

`EVIDENCE_ANCHORING_BACKEND` (environment) selects the evidence anchoring
transport: `besu` (default, chain round-trip) or `disabled` (local settlement,
`LOCAL_SIGNED`).

- Switching is an audited ops action, never a UI toggle: record who/why/when in
  the ops log, then change the environment value and restart web + worker.
- Events keep the status they settled with. A `LOCAL` event is never
  retro-anchored; a `CONFIRMED` event keeps its chain record.
- Events still `PENDING` at switch time settle with whichever backend is active
  when the worker next claims them.
- Verify after switching: `/s/ops/health/?format=json` reports
  `anchoring_backend`; new publications must show `LOCAL_SIGNED` (disabled) or
  `CHAIN_CONFIRMED` (besu) — never each other's wording, badges, or export values.
- Disabling never disables: wallet signatures on decisions, the outbox,
  canonical hashing, publication gates, idempotent fund posting, corrections,
  or document-hash integrity checks. Only the chain round-trip is skipped, and
  chain-dependent verification observations are skipped, not faked.
```

- [ ] **Step 5: Run the full suite one last time**

Run: `.venv/bin/python -m pytest src/lamto tests -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lamto/evidence/tests/test_chain_opacity.py src/lamto/web/static/web/wallet-signing.js ops/pilot-runbook.md
git commit -m "feat: chain opacity audit, secure event-id randomness, mode-switch runbook"
```

---

## Spec coverage map (self-review aid)

| Spec requirement | Task |
|---|---|
| §5.1 evidence-level enum, no verified boolean, gates on enum | 1, 4 |
| §5.1 exports carry enum verbatim | 6 |
| §5.2 `EVIDENCE_ANCHORING_BACKEND = besu \| disabled` | 2 |
| §5.2 port wraps existing worker; Besu code unchanged | 2 (design decision 1) |
| §5.2 disabled settles `LOCAL`, empty tx hash, never `CONFIRMED` | 2 |
| §5.2 LOCAL publications resident-visible with explicit off-chain label | 4, 6 |
| §5.2 `PublicationSnapshot` records backend + level at settlement | 3 (design decision 2) |
| §5.2 disabling never disables signatures/outbox/hashing/publication→fund/corrections/integrity | 4, 5, 7 |
| §5.2 chain-dependent observations skipped, not faked | 5 |
| §5.2 mode-switch runbook (keep settled status, no retro-anchor, audited action) | 2 (worker), 8 (runbook) |
| §5.3 publication gate suite in both modes | 4 (besu full suite), 7 (disabled) |
| §5.4 disabled-mode job: publication, correction, fund flows | 7 |
| §2.2 opacity: random event IDs, no building names / free text near the chain | 8 |
| §9 per-building anchoring column | deliberately deferred (documented seam, not built) |

## Out of scope for this plan

- DRF resident API (Plan 3), BQL `/s/` upgrade (Plan 4), Flutter + push (Phase 1 plans).
- Per-building anchoring toggle (spec §9 seam: move the setting to a `Building` column later).
- Changing `published_ledger_entries` semantics for post-settlement `MISMATCH` snapshots — today such entries drop off the resident list (pre-existing behavior, observed and preserved; the resident-facing mismatch signal remains the integrity-observation label).
- Vietnamese copy for the new labels — all resident/staff template copy is currently English; l10n arrives with the Phase 1 client.
