# Task 14 report: Final verification

Date: 2026-07-21

## Result

Passed after one fix-forward commit. The role-symbol sweep initially found four live Python hits. Obsolete `notify_roles` audit metadata was removed, and the internal proposal fund code/default was changed from the deleted role symbol `MAINTENANCE` to `GENERAL`. Django generated `finance.0014_alter_proposalversion_fund_code`.

## Environment

Commands that use Django/pytest sourced the main checkout environment and selected the migration/test owner as required by the plan:

```bash
set -a
. /home/nts/src/LamTo/.env
set +a
export POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner
```

`lamto-db-1` was running and healthy.

## Exact verification commands and results

### Role and capability sweeps

```bash
grep -rn "OPERATOR\|BOARD\|MAINTENANCE\b\|RESIDENT_REP\|AUDITOR\|TECH_ADMIN" src/lamto --include="*.py" | grep -v __pycache__ | grep -v migrations
grep -rn "require_capability\|capabilities_for\|CapabilityGrant" src/lamto tests --include="*.py" | grep -v __pycache__ | grep -v migrations
```

Final result: both commands produced no output (zero code hits; final grep exit status 1 means no matches).

Initial role sweep hits fixed:

```text
src/lamto/finance/models/proposals.py:43:    fund_code = models.CharField(max_length=32, default="MAINTENANCE")
src/lamto/finance/proposals.py:84:        "fund_code": "MAINTENANCE",
src/lamto/finance/integrity.py:229:                    "notify_roles": ["BOARD", "AUDITOR"],
src/lamto/finance/publication.py:91:                "notify_roles": ["BOARD", "AUDITOR"],
```

### Fresh database migration

```bash
docker exec lamto-db-1 psql -U lamto_bootstrap -d postgres -c "DROP DATABASE IF EXISTS lamto;" -c "CREATE DATABASE lamto OWNER lamto_owner;"
uv run python manage.py migrate
```

Result: `DROP DATABASE`, `CREATE DATABASE`, then all migrations applied without prompts, ending with `sessions.0001_initial... OK`. The new `finance.0014_alter_proposalversion_fund_code... OK` applied from zero.

One setup correction was required: the first migrate invocation inherited `.env`'s restricted runtime writer and failed before migrations with `permission denied for schema public`. Per the plan's global test environment, rerunning with `POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner` completed cleanly. No code change was needed for this environment error.

### Python suite

```bash
uv run pytest src/lamto tests -q
```

Result: `460 passed, 1 skipped in 77.96s (0:01:17)`.

### Flutter suite

```bash
cd app && flutter test
```

Result: `+141: All tests passed!`, exactly matching the pre-stage baseline of 141 passed. Flutter reported 17 dependency updates outside current constraints; no dependency files were changed.

### Supporting checks

```bash
uv run python manage.py makemigrations --check
git diff --check
git status --short
```

Results before the Task 14 commit:

```text
No changes detected
makemigrations --check: exit 0
git diff --check: exit 0
 M src/lamto/finance/integrity.py
 M src/lamto/finance/models/proposals.py
 M src/lamto/finance/proposals.py
 M src/lamto/finance/publication.py
?? src/lamto/finance/migrations/0014_alter_proposalversion_fund_code.py
```

## Concerns

None blocking. The database recreation command must be followed by Django commands using `lamto_owner`, as documented in the plan; the runtime writer intentionally cannot create objects in `public`.
