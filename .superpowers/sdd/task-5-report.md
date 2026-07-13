# Task 5 Report: Maintenance Cases and Work Orders

## Implementation

- Added triage decisions, active maintenance cases, and explicit case/report links. Confirmation and grouping are atomic, row-locked, building-scoped, idempotent, audited, and retain the original reports.
- Added assigned work orders with the required lifecycle and authorization statuses, separate diagnostic/paid orders, and a database guard that forbids converting diagnostic work into paid work.
- Added atomic start and completion transitions. Completion requires the assigned active maintenance user plus clean, original, same-building, assignee-uploaded before/after image versions. Immutable work updates and evidence links are protected in Python and PostgreSQL triggers.
- Used `0004_cases_and_workorders.py` because Task 4 already owns maintenance migrations `0002` and `0003`; creating the brief's requested `0002` would collide.

## TDD evidence

1. Added focused case and work-order tests before production code.
2. The first test command was blocked before collection by missing local settings environment variables; with the required local variables supplied, the tests failed as expected because `CaseReport` and `WorkOrder` did not exist.
3. After implementation, the focused run found the `deadline_minutes`/`MaintenanceCase` construction defect; the minimal shared-path correction made all four Task 5 tests pass.

## Verification

- `manage.py test lamto.maintenance.tests.test_cases lamto.maintenance.tests.test_workorders -v 2 --keepdb` — 4 passed.
- `manage.py test lamto.maintenance -v 2 --keepdb` — 24 passed.
- `manage.py makemigrations --check --dry-run` — no changes detected.
- `python -m compileall -q src/lamto/maintenance` — passed.
- `git diff --check` — passed.

## Commit

- `a3c5c57` — `feat: add maintenance cases and work orders`

The pre-existing uncommitted Task 3 report edit was preserved and was not included in this commit.

## Review fixes

### TDD

- Added the case/link, authorization, boundary, evidence, and append-only regression tests first; the red run failed on direct paid insertion, direct active-case linking, and active-case reactivation before the migration existed.
- Added only a `WorkOrder` check constraint and the PostgreSQL ownership triggers; service workflows remain unchanged.

### Verification

- Focused case/work-order tests — 13 passed.
- `manage.py test lamto.maintenance -v 1` — 33 passed.
- `manage.py test lamto.audit -v 1` — 7 passed.
- `manage.py makemigrations --check --dry-run`, `python -m compileall -q src/lamto/maintenance`, and `git diff --check` — passed.

### Final implementation commit

- `3cadf624175bdabd04f4fb13dae9d98f01aa4ca8` — `fix: enforce maintenance case boundaries`
