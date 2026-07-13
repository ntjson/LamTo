# Task 9 report — emergency authorization and 24-hour outcomes

## Scope delivered

- Added immutable emergency-request identity to `WorkOrder`: requesting operator membership, safety reason, request timestamp, and drill identity.
- Added insert-only `EmergencyAuthorization` and `EmergencyRatification` records with PostgreSQL update/delete triggers.
- Added signed emergency authorization and resident-representative ratification services, plus an idempotent unsigned overdue outcome command.
- Preserved signed outbox identity: canonical payload hashes, EIP-712 evidence signatures, integer VND values, atomic outbox/state transitions, and the exact `authorized_at + timedelta(hours=24)` deadline.
- Added emergency and emergency-drill labels.  Emergency work keeps the existing local pending/anchored verification labels.
- Added `maintenance.0006_emergency_requests` and `finance.0004_emergency_flow`, matching the resolved migration numbering.

## TDD record

1. Wrote `test_board_signature_allows_start_before_chain_and_rep_records_outcome` first.
2. RED command (with the repository's required environment) failed as intended with:

   ```text
   ModuleNotFoundError: No module named 'lamto.finance.emergencies'
   ```

3. Implemented the minimal services/models/migrations.
4. Focused test failures then identified two real integration defects:

   - the public signing-payload helper received the pre-request work-order object;
   - PostgreSQL cannot lock the nullable side of the reverse-ratification join.

   The helper now refreshes an unrequested supplied work order, and overdue selection uses an anti-subquery rather than a nullable outer join.
5. Added focused coverage for immutable request/authorization identity, unsigned/idempotent overdue outcomes, late-decision denial, and PostgreSQL trigger protection for both insert-only models.

## Verification

- `manage.py test lamto.finance.tests.test_emergencies -v 2 --noinput` — 3 passed on a fresh PostgreSQL test database.
- `manage.py test lamto.finance.tests.test_emergencies lamto.finance lamto.maintenance -v 1 --noinput` — 48 passed on a fresh PostgreSQL test database.
- `manage.py makemigrations --check --dry-run finance maintenance` — no changes detected.
- `git diff --check` — clean.

The available local database has legacy ownership/role divergence. Fresh Django test databases succeed with `POSTGRES_USER=lamto` / `POSTGRES_PASSWORD=lamto`; no non-test schema migration was required for task verification.

## Self-review

- Request authorization checks active capability and matching building; Board and representative actions reuse existing capabilities and organization roles.
- Authorization payload commits the request reason digest and drill flag; ratification follows the authorization outbox hash.
- Authorization changes `WorkOrder.authorization_status` in the same transaction as its signed outbox event; deadline is exactly 24 hours after supplied authorization time.
- A system overdue row has no membership, wallet, signature, or outbox event; human rows require all of them.  A late human decision is audited and cannot replace an overdue row.
- Database triggers cover both new insert-only models, while the maintenance trigger prevents clearing/converting requested emergency/drill identity.
- No dependencies or unrelated source changes were added.  The existing dirty `.superpowers/sdd/task-3-report.md` was preserved untouched.
