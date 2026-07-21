# Task 8 report

## RED

- Added `finance/tests/test_models.py` to characterize all nine finance attribution FKs.
- Confirmed RED: `OrganizationMembership is not ManagementMembership`.

## Sweeps

- Swapped proposal, acceptance, payment, fund, publication, and integrity attribution to `ManagementMembership`.
- Replaced finance capability/organization authorization with `require_management(user, building_id)`.
- Preserved service signatures and payment/fund same-user dual-control checks.
- Required finance grep is empty.

## Migration

- Generated `finance.0013_alter_acceptancerecord_membership_and_more` only.
- Dependencies are `accounts.0013` and `finance.0012`, ordering the FK cutover after the wallet cutover on a fresh database.
- `makemigrations --check --dry-run`: no changes detected.

## Tests

- Model characterization GREEN: `1 passed`.
- Finance module fresh run: `18 passed, 38 failed, 7 errors`.
- Failures are the planned wave dependencies: evidence wallet services still resolve `OrganizationMembership` until Task 9, and pilot factories still construct role memberships until Task 10. No Task 9/10 files were changed here.

## Commit

- `refactor(finance)!: management gate across proposals/payments/fund/publication (wave 4/6)`

## Concerns

- The Task 8 finance-module-green gate cannot be reached in isolation before the explicitly deferred Task 9 evidence and Task 10 factory cutovers; rerun the module after those wave commits.
