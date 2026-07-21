# Task 7 report

## Result

- Replaced maintenance triage/work-order organization role and capability lookup helpers with `require_management(user, building_id)`.
- Preserved all public service signatures and assigned-user checks.
- Updated maintenance fixtures to use `ManagementMembership`; unaffiliated and cross-building users remain denied.
- Kept ratings/reporting behavior unchanged. The idempotent reporting tests now create only their required resident fixture instead of invoking the stale full pilot signer fixture.
- No maintenance model role foreign key remained to migrate.

## TDD evidence

- RED: with tests changed and production untouched, the focused run failed twice with `PermissionDenied: report.triage` from `_operator_membership`, proving management-only fixtures were rejected by the legacy gate.
- GREEN: `POSTGRES_DB=lamto_task7 POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner uv run pytest src/lamto/maintenance -q`
- Result: `42 passed in 10.57s`.

The initial run using the shared `test_lamto` database could not establish a behavioral red because another process/database owner had left it inaccessible. A task-specific database produced the expected red and isolated final verification.

## Self-review

- `git diff --check`: clean.
- Confirmed no `_operator_membership`, `_maintenance_membership`, maintenance capability imports, organization membership lookups, or organization-to-building traversal remain in the cut-over maintenance services/tests.
- Audit calls receive the `ManagementMembership` returned by `require_management`.
- Full-wave tests intentionally not run; the task brief expects later-wave failures outside this module.
