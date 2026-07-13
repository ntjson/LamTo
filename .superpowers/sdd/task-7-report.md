# Task 7 Report: Immutable Expenditure Proposal Versions

## Delivered

- Added the `finance` Django app with mutable `Proposal` aggregates and fixed normal/emergency modes/statuses.
- Added insert-only numbered `ProposalVersion` snapshots, positive integer amount checks, creator wallet/signature references, immutable quotation links, exact snapshot hashes, and one proposal per work order.
- Added transactional proposal creation/submission with capability and building checks, clean original/redacted quotation requirements, EIP-712 evidence signing through the Task 6 outbox, revision chaining, and work-order authorization-state handling.
- Added PostgreSQL immutability triggers for proposal versions, quotation links, and proposal mode changes.

## Verification

- `manage.py test lamto.finance.tests.test_proposals` — 6 passed.
- `manage.py test lamto.finance lamto.evidence lamto.accounts lamto.audit lamto.maintenance lamto.documents` — 110 passed.
- Existing local database migration through `finance.0001` and `finance.0002` — passed.
- `manage.py makemigrations --check --dry-run` — no changes detected.
- `python -m compileall -q src` and `git diff --check` — passed.

## Scope

Proposal approvals, emergency authorization outcomes, payment flow, and publication remain in their later named tasks. The pre-existing uncommitted Task 3 report change remains preserved and excluded.
