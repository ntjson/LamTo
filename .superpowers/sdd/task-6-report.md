# Task 6 report

## RED

- Added `WalletMembershipModelTests.test_wallet_models_use_management_memberships`.
- Confirmed failure: `SignerWallet.membership` resolved to `OrganizationMembership`, not `ManagementMembership`.

## Migration

- Generated `accounts/0013_alter_signerauthorizationrequest_requested_by_and_more.py` with `makemigrations accounts`.
- It alters only the three requested foreign keys; no historical migration was edited.
- `makemigrations accounts --check --dry-run`: no changes detected.

## Tests

- FK characterization: `1 passed`.
- `pytest src/lamto/accounts -q` could not reach module tests on a fresh database: historical `evidence/0009_outbox_building_backfill_and_guard` imports the live wallet model and traverses the removed `membership.organization` relation. This is outside Task 6's allowed migration edits and is recorded for the later wave.
- A shared-database retry was also unavailable because the existing `test_lamto` database is owned by another test role.
- Ruff is not installed in the project environment.

## Commit

- `refactor(accounts)!: key signer wallets by ManagementMembership (wave 2/6)`

## Concerns

- Fresh full migration replay remains blocked until the historical evidence migration is made state-safe or the later wave removes its live-model dependency.
- The staff signing cleanup proposal still assigns a `ManagementMembership` to the legacy proposal membership FK; web/full green is deferred by the brief.
