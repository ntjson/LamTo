# Task 6 Report: Signed Blockchain Outbox

## Delivered

- Added strict NFC canonical JSON and SHA-256 hashing, exact EIP-712 evidence data, current `eth-account` encoding/recovery, and UTC/identifier/integer-VND payload primitives.
- Added single-use expiring EIP-712 wallet-registration challenges, checksum signer wallets for eligible operator/Board/resident-representative memberships, immutable revocation history, audited transitions, and pending signer-authorization handoffs for Task 11.
- Added evidence types 1–11 and a transactional signed outbox with canonical payload hashes, prior-payload hash linkage, signer recovery, active-wallet authorization, duplicate conflict handling, delivery metadata, and PostgreSQL identity immutability.
- Added a payload trust-boundary guard against private report text, photos, bank details, personal profiles, and private-key fields while allowing hash-only references. No chain worker or private-key storage was added.

## TDD evidence

1. Signature/canonical tests first failed because `lamto.evidence.canonical` did not exist; the minimal helpers then passed 6 focused tests.
2. Wallet/outbox tests first failed because signer models and evidence services did not exist; implementation and migrations then passed the focused suite.
3. Strict event-type and private-payload tests failed against permissive queueing, then passed after boundary validation.
4. Cross-membership idempotent lookup failed by returning another signer's event, then passed after duplicate authorization was enforced.
5. The registration proof test failed when the challenge was not EIP-712 typed data, then passed using `encode_typed_data(full_message=...)` and `Account.recover_message`.

## Verification

- Local PostgreSQL `manage.py migrate --noinput` — passed.
- `manage.py test lamto.evidence lamto.accounts lamto.audit -v 1 --noinput` — 34 passed.
- `manage.py makemigrations --check --dry-run` — no changes detected.
- `python -m compileall -q src/lamto/accounts src/lamto/evidence src/lamto/config` — passed.
- `git diff --check` — passed.

## Scope

The pre-existing uncommitted Task 3 report SHA edit was preserved and excluded. Task 11 chain submission, receipt polling, retries, relayer/owner keys, and signer synchronization remain intentionally unimplemented.

## Review fixes

- Canonicalized proof/evidence signatures to exactly 65 bytes with `v` 27/28 and secp256k1 low-`s`, rejecting malformed/high-`s` values before recovery and storing normalized lowercase `0x` hex.
- Moved complete event, payload-schema/hash, active-wallet, and signature validation before duplicate lookup; idempotency now compares every signed immutable field.
- Added transaction-local service guards and PostgreSQL triggers for wallet insert/revocation/deletion and outbox insertion, plus outbox `BEFORE TRUNCATE` rejection. Delivery metadata remains mutable and signed identity remains immutable.
- Replaced the private-key blacklist with per-`EvidenceType` field allowlists, nested-object rejection, and 32-byte hash/digest validation.
- Added ORM, queryset, raw-SQL, audit, malformed duplicate, alternate-sensitive-key, and high-`s` regression coverage. No private keys are stored.

### TDD and verification

- Initial adversarial run: 23 tests, 12 expected failures across all five findings.
- Additional hash-slot privacy test failed when raw report text was accepted under `report_snapshot_hash`, then passed after digest validation.
- Focused signature/outbox run: 23 passed.
- `manage.py test --keepdb lamto.evidence lamto.accounts lamto.audit -v 1 --noinput` — 40 passed.
- `manage.py makemigrations --check --dry-run` — no changes detected.
- `manage.py migrate --noinput` applied `accounts.0004` and `evidence.0002`; `manage.py migrate --check` passed.
- `python -m compileall -q src/lamto/accounts src/lamto/evidence src/lamto/config` — passed.
- `git diff --check` — passed.

### Final fix commit

- `64eb0b598bc9697f9850ac7051170f69617e1c8a` — `fix: harden signed evidence boundaries`.

### Final review fixes

- Replaced permissive field allowlists with required/optional schemas for every evidence type. IDs, positive integer versions, integer đồng amounts, booleans, UTC timestamps, enums, bytes32 links, and non-empty declared hash lists are validated before hashing or duplicate lookup.
- Locked the active signing membership first and its active wallet second while queueing evidence; wallet revocation follows the same membership-before-wallet order.
- Removed forgeable transaction GUC authorization. Wallet and outbox write procedures now live in a dedicated `lamto_security` schema, are owned by a separate NOLOGIN `POSTGRES_SERVICE_ROLE`, and are the only identities accepted by the insert/revocation triggers. Compose provisions the role for migrations and removes the migration role's temporary membership after ownership transfer.
- Added regression coverage for complete event schemas, value-slot smuggling, malformed enums/timestamps/hash lists, and the old GUC bypass.

### Final verification

- Fresh PostgreSQL migration plus `manage.py test lamto.evidence lamto.accounts lamto.audit -v 1 --noinput` — 44 passed.
- `manage.py makemigrations --check --dry-run` — no changes detected.
- `python -m compileall -q src/lamto/accounts src/lamto/evidence src/lamto/config` — passed.
- `git diff --check` — passed.
