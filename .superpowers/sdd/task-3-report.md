# Task 3 completion report

## Commit

- Task 3 implementation: `a2e20a13ebaf329fb83dc1f04881fc4e61697308` (`feat: add immutable private documents`)

## Delivered

- Added immutable `Document`, `DocumentVersion`, and `QuarantinedUpload` records, including PostgreSQL update/delete/truncate triggers.
- Added private S3-compatible storage, streamed size/type/signature/Pillow/SHA-256 validation, ClamAV INSTREAM scanning, one-write storage, quarantine metadata/retention/purge, and original-to-redacted linkage.
- Added exact provider-version reads with SHA-256 verification and audited access for operators, auditors, representatives, maintenance, and occupancy-based residents.
- Residents use `ResidentOccupancy` and call `authorize_download(user, None, version)`; no `RESIDENT` membership role was added. Audit membership is nullable only for occupancy/unaffiliated document-download attribution; active staff memberships remain validated.
- Replaced the invalid JPEG fixture with Pillow-generated valid JPEG bytes; image verification remains enforced.

## RED evidence

- `lamto.documents.tests.test_access.DocumentAccessTests.test_resident_can_read_published_redacted_copy` initially errored with `PermissionDenied: Invalid membership.` when called with the resident-safe `membership_id=None`.
- `lamto.documents.tests.test_versions.DocumentVersionTests.test_database_trigger_rejects_version_update_and_delete` initially failed because direct `Document` mutation was accepted.
- `lamto.documents.tests.test_quarantine.QuarantineTests.test_quarantine_has_a_fixed_retention_deadline` initially errored because `QuarantinedUpload` had no retention deadline.
- The supplied JPEG fixture began with JPEG signature bytes but was not a JPEG; Pillow correctly rejected it. The fixture was corrected rather than weakening validation.

## GREEN evidence

- Focused access: `manage.py test lamto.documents.tests.test_access -v 1` — 6 passed.
- Documents suite: `manage.py test lamto.documents -v 1` — 16 passed.
- Full Lamto suite: `manage.py test lamto -v 2` — 31 passed.
- `manage.py check` — no issues.
- `manage.py makemigrations --check --dry-run` — no changes detected.
- `manage.py migrate --noinput` against PostgreSQL at `127.0.0.1` — applied `audit.0002_alter_auditevent_membership` and `documents.0001_initial`.
- `python -m compileall -q src` and `git diff --check` — passed.

All Django commands used explicit `SECRET_KEY`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST=127.0.0.1`, and `POSTGRES_PORT=5432` environment variables; Docker and SQLite were not used.

## Files

- `src/lamto/documents/{apps,models,services,access,scanner}.py`
- `src/lamto/documents/migrations/0001_initial.py`
- `src/lamto/documents/tests/{test_versions,test_quarantine,test_access}.py`
- `src/lamto/config/settings.py`
- `src/lamto/audit/{models,services}.py`
- `src/lamto/audit/migrations/0002_alter_auditevent_membership.py`

## Concerns

- `purge_expired_quarantine()` is intentionally a small callable retention job; production needs to schedule it.
- Workflow attachment models are not present yet, so representative/report/maintenance checks follow linked related objects and are covered by the current access matrix fixtures.

## Fix

- Finalized the review fix on top of `a2e20a1`: redacted copies reject identical bytes, S3 storage requires a returned `VersionId` and reads fail closed without one, operator/workflow access no longer defaults to allow, nullable audit attribution requires an active resident occupancy, and access tests no longer use transient workflow attributes.

## Verification

All commands used explicit `SECRET_KEY`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST=127.0.0.1`, `POSTGRES_PORT=5432`, `CLAMAV_HOST`, `CLAMAV_PORT`, and private-storage environment variables. Tests used the existing PostgreSQL test database via `--keepdb`; Docker and SQLite were not used.

- `SECRET_KEY=task3-local POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 CLAMAV_HOST=127.0.0.1 CLAMAV_PORT=3310 PRIVATE_STORAGE_ENDPOINT_URL=http://127.0.0.1:9000 PRIVATE_STORAGE_BUCKET=lamto-documents PRIVATE_STORAGE_ACCESS_KEY=lamto-local PRIVATE_STORAGE_SECRET_KEY=lamto-local-secret .venv/bin/python manage.py test --keepdb lamto.audit.tests.test_immutability lamto.documents.tests.test_access lamto.documents.tests.test_versions -v 1` — 19 passed.
- Same explicit environment with `.venv/bin/python manage.py test --keepdb lamto.documents -v 1` — 19 passed.
- Same explicit environment with `.venv/bin/python manage.py test --keepdb lamto.accounts lamto.audit -v 1` — 17 passed.
- Same explicit environment with `.venv/bin/python manage.py test --keepdb lamto -v 1` — 36 passed.
- Same explicit environment with `.venv/bin/python manage.py check` — no issues.
- Same explicit environment with `.venv/bin/python manage.py makemigrations --check --dry-run` — no changes detected.
- `.venv/bin/python -m compileall -q src` — passed.
- `git diff --check` — passed.

## Remaining review fix on `956c267`

### Fix

- `authorize_download()` now keeps the actor's own active membership for denied staff requests when `membership_id` is invalid or not owned, so denial auditing cannot fail while preserving fail-closed access.
- Unaffiliated document-download denials now use an active occupancy for nullable audit attribution even when the occupancy is in another building.
- `record_audit(..., membership=None)` remains limited to `document.download`/`DocumentVersion` events for actors with no active membership and a valid active occupancy; active memberships must be supplied.
- No `RESIDENT` role or workflow-grant model was added. Operator, representative, and maintenance access remains fail-closed until Tasks 4/5/12/15/16 add persisted workflow relationships; those relationships are the cross-task integration point for this access matrix.

### Tests

- `SECRET_KEY=task3-local POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 CLAMAV_HOST=127.0.0.1 CLAMAV_PORT=3310 PRIVATE_STORAGE_ENDPOINT_URL=http://127.0.0.1:9000 PRIVATE_STORAGE_BUCKET=lamto-documents PRIVATE_STORAGE_ACCESS_KEY=lamto-local PRIVATE_STORAGE_SECRET_KEY=lamto-local-secret .venv/bin/python manage.py test --keepdb lamto.documents.tests.test_access.DocumentAccessTests.test_invalid_staff_membership_denial_uses_own_membership_for_audit lamto.documents.tests.test_access.DocumentAccessTests.test_unaffiliated_denial_with_occupancy_in_another_building_is_audited -v 2` — 2 expected failures before implementation, then 2 passed after the fix.
- Same environment with `.venv/bin/python manage.py test --keepdb lamto.audit.tests.test_immutability lamto.documents.tests.test_access -v 1` — 16 passed.
- Same environment with `.venv/bin/python manage.py test --keepdb lamto.documents -v 1` — 21 passed.
- Same environment with `.venv/bin/python manage.py test --keepdb lamto.accounts lamto.audit -v 1` — 17 passed.
- Same environment with `.venv/bin/python manage.py test --keepdb lamto -v 1` — 38 passed.
- Same environment with `.venv/bin/python manage.py check` — no issues.
- Same environment with `.venv/bin/python manage.py makemigrations --check --dry-run` — no changes detected.
- `.venv/bin/python -m compileall -q src` — passed.
- `git diff --check` — passed.

### Commit

- Pending final fix commit SHA after report update.
