# Task 4 report — off-chain ledger and two-type integrity

Status: complete.

## RED / GREEN

- RED: retained settlement boundary tests proved ledger publication still depended on a third `PublicationSnapshot` anchor; fund tests proved maker/checker created two additional outbox rows.
- RED after the first cutover: focused tests exposed PostgreSQL rejecting `FOR UPDATE` across the nullable case join. The lock was narrowed to the settlement row with `of=("self",)`.
- GREEN focused contract: settlement story + two anchors, off-chain fund dual control, and rejected legacy event types: `8 passed`.
- GREEN finance module: `39 passed`.
- GREEN full Django suite: `413 passed, 1 skipped`.
- GREEN Flutter: `flutter analyze` reported no issues; `flutter test` passed `144` tests.

## Implementation

- Settlement acknowledgement now calls idempotent `publish_settlement_entry(settlement)` in the same transaction as the off-chain fund outflow.
- `PublishedLedgerEntry` owns `resident_payload` and a one-to-one `settlement`; the legacy snapshot and gate models and finalization worker/command are removed.
- Ledger proof exposes `proposal_version` and `settlement`, each with `event_id`, `payload_hash`, and `evidence_level`; integrity checks exactly those two events plus the linked evidence documents.
- Fund record/verify signatures no longer accept signature/event parameters, queue events, or store wallet/outbox/signature relations. Recorder/verifier separation and audit remain.
- Evidence validation has one allowlist: types 1 and 10. Enum members 6–9 and 11 and their schemas/tests are removed; explicit rejection coverage checks 6/7/8/9/11.
- Management fund forms are plain recent-auth forms. Publication signing/finalization inbox and worker paths are gone.
- Notification naming was aligned from payment-event constants to settlement recording so the required legacy-symbol sweep is exact.

## Migrations

- `evidence.0018_two_anchored_types`
- `finance.0022_offchain_ledger_and_fund`

Both are forward-only. Applied successfully against the shared Compose database. `makemigrations --check --dry-run` reports no changes.

## Sweeps and contracts

- Required non-migration Python sweep for `PublicationSnapshot|PUBLICATION_SNAPSHOT|FUND_ENTRY|WORK_ACCEPTANCE|PAYMENT_RECORDED|PAYMENT_VERIFIED|prepare_publication|finalize_publication`: zero hits.
- `manage.py check`: no issues.
- `git diff --check`: clean.
- OpenAPI was regenerated with drf-spectacular, then the Dart client was regenerated. The resident ledger screen keeps the existing proof/event fields and gains both named anchors; no manual Flutter rendering change was required.

## Files

- Domain/model: `finance/publication.py`, `finance/fund.py`, `finance/integrity.py`, `finance/selectors.py`, `finance/settlements.py`, `finance/models/ledger.py`, `finance/models/__init__.py`.
- Evidence: `evidence/models.py`, `evidence/services.py`, new evidence migration and focused platform validation tests.
- API/app: ledger serializers/views/download authorization, OpenAPI, regenerated `lamto_api` client.
- Web/ops: fund views/export, proposal/request/accountability cleanup, inbox and worker cleanup.
- Tests/factories/e2e/isolation updated to the atomic off-chain publication and fund contracts.

## Self-review

- The off-chain ledger is created before the settlement anchor is confirmed, intentionally: resident selectors still hide it until the settlement event is locally settled or chain-confirmed.
- `VerificationObservation` remains because it records current integrity checks over proposal/settlement anchors and documents; only snapshot-specific models were deleted.
- Wallet infrastructure remains for Task 5, while all Task 4 publication/fund typed-data production paths are removed.
- No destructive database operation was used.

## Reviewer follow-up

- Standalone proposals are now reachable through ledger list/detail, story rendering, redacted downloads, integrity observations, reconciliation, and action-inbox scoping by using the proposal's building instead of requiring a case.
- Resident ledger visibility and downloads require both anchors independently: the proposal current-version event and the settlement event must each be settled or chain-confirmed.
- Restored the active outbox and chain-opacity suites, retaining wallet authorization, idempotence/conflict, database-boundary, procedure-security, sensitive-payload, concurrency, canonicalization, and hash-opacity coverage while narrowing valid evidence payloads to proposal and settlement.
- Added an end-to-end standalone proposal lifecycle test and independent pending/failed/mismatch visibility checks for both anchors.
- Reviewer verification: focused suites `59 passed`; evidence/finance/API/web modules `268 passed, 1 skipped`; full Django suite `439 passed, 1 skipped`; `manage.py check`, migration drift check, legacy-symbol sweep, and `git diff --check` are clean.
- Flutter was not rerun for this follow-up because it changes server-side visibility/scoping only and does not change the regenerated OpenAPI or Dart client contract.
