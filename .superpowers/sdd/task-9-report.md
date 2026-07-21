# Task 9 report

## Status

Complete. Documents now authorize active management or active resident occupancy in the document building, notifications target every active management user in the building, and evidence tests use `ManagementMembership` consistently with the Task 8 service cutover.

## Commit

`679cd32 refactor!: management targeting for documents/notifications/evidence (wave 5/6)`

## Verification

```text
uv run pytest src/lamto/documents src/lamto/notifications src/lamto/evidence -q
100 passed, 1 skipped in 13.63s
```

The skipped test is the existing opt-in live Besu integration test.

`git diff --check` passed before commit. A residue scan found no legacy organization membership, role, or capability targeting references in the three modules outside historical migrations.

## Self-review

- Kept quarantine storage, retention, scanning, and resident report-photo restrictions unchanged; only its management membership lookup changed.
- Reused `require_management` for document upload/download gates.
- Left Task 8's evidence service and migrations intact; only remaining evidence test fixtures were cut over.
- Concern: `authorize_download` retains the transitional `membership_id` parameter for callers, but authorization is deliberately resolved from the user and document building through `require_management`.

## Review follow-up

Fixed quarantined-upload fan-out when callers pass only the upload: the hook now derives its building from `upload.building_id`, notifying the uploader and active management in that building while excluding inactive and other-building memberships.

```text
uv run pytest src/lamto/notifications/tests/test_building_scope.py::NotificationBuildingTests::test_quarantined_upload_notifies_active_management_in_its_building -q
1 passed in 4.42s

uv run pytest src/lamto/documents src/lamto/notifications src/lamto/evidence -q
101 passed, 1 skipped in 11.92s
```
