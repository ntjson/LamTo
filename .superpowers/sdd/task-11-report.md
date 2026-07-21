# Task 11 report

## Result

- Replaced the legacy staff membership/capability shell with building-scoped `ManagementMembership` resolution and the `active_management_id` session key.
- Exposed all six management areas (`Inbox`, `Cases`, `Work`, `Finance`, `Exports`, `Ops`) and all surviving inbox queues unconditionally.
- Replaced membership switching with building switching and removed break-glass routes, views, middleware enforcement, and template branches.
- Migrated web view callers away from capability codes to `require_management_context`.

## Verification

- `uv run python manage.py check`: passed.
- Task 11 tests (`test_staff_nav.py`, `test_staff_signing.py`, `test_exports_and_health.py`, `test_list_pattern.py`): **34 passed**.
- `uv run pytest src/lamto/web -q`: collection stops only in the Task 12-owned `src/lamto/web/tests/test_role_workspaces.py`, which still imports the deliberately removed `SESSION_MEMBERSHIP_KEY` and `capabilities_for` interfaces.

## Remaining failure files

- `src/lamto/web/tests/test_role_workspaces.py` (Task 12-owned legacy workspace tests)
