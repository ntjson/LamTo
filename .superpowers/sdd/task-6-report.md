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
