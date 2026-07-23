## Task 3 Report

### Red test

`POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner PYTHONPATH=/home/nts/src/LamTo/.worktrees/building-announcements/src /home/nts/src/LamTo/.venv/bin/pytest src/lamto/web/tests/test_staff_announcements.py src/lamto/web/tests/test_staff.py -q`

Result: `11 failed, 1 passed`; failures were the missing announcement routes and navigation item. An earlier run with the application role was invalid because that role could not create `test_lamto`.

### Final tests

`POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner PYTHONPATH=/home/nts/src/LamTo/.worktrees/building-announcements/src /home/nts/src/LamTo/.venv/bin/pytest src/lamto/web/tests/test_staff_announcements.py src/lamto/web/tests/test_staff.py -q`

Result: `12 passed in 12.22s`.

`POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner PYTHONPATH=/home/nts/src/LamTo/.worktrees/building-announcements/src /home/nts/src/LamTo/.venv/bin/pytest src/lamto/web/tests/test_staff_announcements.py src/lamto/web/tests/test_staff.py src/lamto/web/tests/test_staff_nav.py src/lamto/web/tests/test_staff_registrations.py -q`

Result: `26 passed in 15.19s`.

`DJANGO_SETTINGS_MODULE=lamto.config.settings POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner PYTHONPATH=/home/nts/src/LamTo/.worktrees/building-announcements/src /home/nts/src/LamTo/.venv/bin/python -m django check`

Result: no issues.

### Files

- `.superpowers/sdd/task-3-report.md`
- `src/lamto/web/announcement_views.py`
- `src/lamto/web/forms/announcements.py`
- `src/lamto/web/staff.py`
- `src/lamto/web/templates/web/staff/announcements/detail.html`
- `src/lamto/web/templates/web/staff/announcements/list.html`
- `src/lamto/web/tests/test_staff.py`
- `src/lamto/web/tests/test_staff_announcements.py`
- `src/lamto/web/tests/test_staff_nav.py`
- `src/lamto/web/urls.py`

### Behavior

- Adds announcement navigation, building-scoped history/detail, publish/edit forms, and POST-only withdrawal.
- Uses the explicit active building ID for publish and optimistic expected revisions for edit/withdraw.
- Validates stripped title/body limits, prevents cross-building access, reports stale conflicts, and keeps withdrawn records visible without mutation controls.

### Commit

`feat: manage building announcements`

### Self-review

- Confirmed every announcement lookup is filtered by the active management building before display or mutation.
- Confirmed invalid forms create no records or deliveries, stale edits preserve newer content, and CSRF/HTTP method protections are exercised.
- Confirmed no resident recipient list is rendered and no Task 4/5/7 report deletions were staged.

### Concerns

- The shared virtualenv does not contain `ruff`; byte-compilation, `git diff --check`, Django checks, and focused tests passed instead.
