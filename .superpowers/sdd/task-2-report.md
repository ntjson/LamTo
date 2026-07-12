# Task 2 report: capabilities and immutable audit events

## Requirements addressed

- Added explicit `CapabilityGrant(membership, code)` storage with a unique membership/code constraint.
- Added all 15 capability constants, the fixed organization-kind allowlist, and `grant_capability()` / `require_capability()` guards. Unknown codes, inactive memberships, missing grants, and incompatible organization kinds raise `PermissionDenied`.
- Added the `lamto.audit` app, insert-only `AuditEvent`, `record_audit()`, and PostgreSQL `BEFORE UPDATE OR DELETE` trigger. ORM instance updates/deletes and bulk/raw mutations are rejected.
- Kept PostgreSQL as the only database backend; no SQLite fallback or dependency was added.

## Files

- Modified: `src/lamto/config/settings.py`, `src/lamto/accounts/models.py`
- Added: `src/lamto/accounts/capabilities.py`, `src/lamto/accounts/services.py`, `src/lamto/accounts/migrations/0002_capability_grants.py`, `src/lamto/accounts/tests/test_capabilities.py`
- Added: `src/lamto/audit/{__init__,apps,models,services}.py`, `src/lamto/audit/migrations/{__init__,0001_initial}.py`, `src/lamto/audit/tests/{__init__,test_immutability}.py`

## TDD evidence

- RED: `SECRET_KEY=task2-test POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 .venv/bin/python manage.py test lamto.accounts.tests.test_capabilities lamto.audit.tests.test_immutability -v 2`
  - Failed as expected before implementation: `ModuleNotFoundError` for `lamto.accounts.capabilities` and `lamto.audit.models`.
- GREEN: same command after implementation
  - Passed: 5 tests, including the explicit-grant denial/grant flow, fixed allowlist, incompatible/unknown grant denial, model immutability, queryset update rejection, and raw SQL delete rejection.

## Exact verification commands and results

- `SECRET_KEY=task2-test POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 .venv/bin/python manage.py test lamto.accounts -v 1` — 7 passed (baseline).
- `SECRET_KEY=task2-test POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 .venv/bin/python manage.py test lamto.accounts.tests.test_capabilities lamto.audit.tests.test_immutability -v 2` — 5 passed.
- `SECRET_KEY=task2-test POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 .venv/bin/python manage.py makemigrations accounts audit` — no changes detected.
- `SECRET_KEY=task2-test POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 .venv/bin/python manage.py migrate` — applied `accounts.0002_capability_grants` and `audit.0001_initial`.
- `SECRET_KEY=task2-test POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 .venv/bin/python manage.py test lamto.accounts lamto.audit -v 2` — 12 passed.
- `git diff --check` and `manage.py makemigrations --check --dry-run` — clean; no model/migration drift.

## Self-review

- The allowlist is the single source of organization-kind policy, and `require_capability()` independently checks it so an erroneous direct database grant cannot authorize an incompatible actor.
- The audit migration uses a reversible PostgreSQL `RunSQL` trigger, while the model blocks normal ORM updates/deletes.
- The implementation is limited to the Task 2 paths; no speculative permission abstractions were added.

## Commit

`9c012c29ab82cb8f2609f66f3f01c4cee85f7732` — `feat: enforce capabilities and immutable audit`

## Concerns

None.

## Task 2 review fix verification

### Files

- Modified: `src/lamto/audit/migrations/0001_initial.py`, `src/lamto/audit/services.py`, `src/lamto/audit/tests/test_immutability.py`
- Documented: `.superpowers/sdd/task-2-report.md`

### Exact verification results

- `SECRET_KEY=task2-test POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 .venv/bin/python manage.py test lamto.accounts lamto.audit -v 2` — 15 tests passed.
- `SECRET_KEY=task2-test POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 .venv/bin/python manage.py check` — no issues (0 silenced).
- `SECRET_KEY=task2-test POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 .venv/bin/python manage.py makemigrations --check --dry-run accounts audit` — no changes detected in `audit`, `accounts`.
- `.venv/bin/python -m compileall -q manage.py src` — passed.
- `git diff --check` — passed.
