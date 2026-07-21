# Task 12 report

## Result

- Moved case/report, proposal, payment/acceptance, and work-order views into `requests.py`, `proposals.py`, `payments.py`, and `work.py`.
- Replaced role/capability workspace gates with the shared management context gate.
- Rewrote the web URL map to the Stage 1 management-only routes; `/` now redirects to `/s/`.
- Moved the login template to `web/login.html` and removed resident web/PWA routes, views, forms, templates, assets, and obsolete resident/role workspace tests.
- Removed audit search and redirected its remaining UI/inbox references to the audit export.
- Updated export, fund, and health access and migrated affected tests to the two-management-member model.
- Flutter and API routes/code were preserved.

## Deleted surfaces

- Role view modules: `operator.py`, `board.py`, `maintenance.py`, `auditor.py`, `resident.py`.
- Resident form and resident template directory (after moving `login.html`).
- Resident service worker, manifest, and PWA icons.
- Audit search view module/template/route.
- Obsolete resident, occupancy, and role-workspace web tests.

## Final routes

- Security: MFA setup/verify/revoke and reauthentication under `/s/security/`.
- Shell: `/s/`, `/s/inbox/`, `/s/building/`.
- Requests: `/s/cases/`, case detail, and staff report detail.
- Proposals: proposal list/detail and work proposal creation.
- Work: work list/detail and acceptance.
- Payments: list, record, record detail, and verification detail.
- Export: `/s/audit/export/` only.
- Fund: home, record, and verify.
- Operations: health and pilot metrics.

## Tests

- TDD management workspace seam: 4 passed (all management nav areas, resident-only denial, case detail rendering, distinct payment record/second-manager verification paths).
- `uv run pytest src/lamto/web -q`: 97 passed.
- `uv run pytest src/lamto tests -q`: 474 passed, 1 skipped.

Tests used the repository `.env` with `POSTGRES_USER=lamto_owner` and `POSTGRES_PASSWORD=lamto-owner`. The stale `test_lamto` database created under the writer role was dropped and recreated for the runs.
