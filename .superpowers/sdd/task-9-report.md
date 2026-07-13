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

## Fix pass 1 — signing and database integrity correction

### Root cause evidence

- `build_emergency_authorization_evidence_payload()` defaulted `authorization_timestamp` to `WorkOrder.emergency_requested_at`, and `authorize_emergency()` called it without a timestamp while independently persisting caller-supplied `now` as `authorized_at` and deriving the deadline from `now`. There was no `now >= emergency_requested_at` check. The verified signature therefore did not authenticate the persisted authorization time or its 24-hour window.
- `build_emergency_ratification_evidence_payload()` had no representative-reason parameter and derived `reason_digest` from `EmergencyAuthorization.reason`. `decide_emergency()` persisted the supplied representative reason but verified a signature over the original authorization reason instead.
- `emergency_ratification_provenance` required non-null membership, wallet, and outbox references for a human row, but allowed an empty signature and any `RATIFY`/`REJECT` decision with any human outcome.
- Both emergency models inherit the instance `save()` guard from `InsertOnlyModel`, and PostgreSQL triggers reject queryset updates/deletes. Coverage previously exercised only queryset mutation, not the inherited instance guard.

### TDD RED evidence

The regressions were written before production changes. The first command attempt stopped before test collection with `KeyError: 'SECRET_KEY'`; it was rerun with the established explicit PostgreSQL test environment:

```bash
SECRET_KEY=task9-fix1 POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 CLAMAV_HOST=127.0.0.1 CLAMAV_PORT=3310 AI_TRIAGE_URL=https://triage.example.test/v1/triage AI_TRIAGE_TOKEN=test-token PRIVATE_STORAGE_ENDPOINT_URL=http://127.0.0.1:9000 PRIVATE_STORAGE_BUCKET=lamto-documents PRIVATE_STORAGE_ACCESS_KEY=lamto-local PRIVATE_STORAGE_SECRET_KEY=lamto-local-secret .venv/bin/python manage.py test lamto.finance.tests.test_emergencies -v 2 --noinput
```

Expected RED on a fresh PostgreSQL test database: 7 tests found; 2 failures, 4 errors, 1 pass. Evidence included `ValidationError not raised` for a pre-request `now`, wallet-signature mismatch when signing the intended authorization timestamp, the outcome helper treating the new reason argument as a timestamp because no reason slot existed, and `IntegrityError not raised` for an empty human signature. The existing immutable-request test remained green.

### Minimal repair

- Passed the validated `now` into the exact authorization payload that is signed and queued, rejected `now` before the request, and continued deriving both `authorized_at` and the deadline from that same value.
- Added the normalized representative reason to the outcome payload/typed-data interfaces and committed only its canonical digest to the payload.
- Replaced the ratification provenance constraint with exact valid branches: unsigned system `OVERDUE`, signed human `RATIFY`/`RATIFIED`, or signed human `REJECT`/`REJECTED`.
- Added additive migration `finance.0005`; committed migration `finance.0004` was not rewritten.
- Added model-instance `save()` and queryset `update()`/`delete()` rejection coverage for both insert-only emergency models.

### GREEN verification

- Focused fresh PostgreSQL run: the RED command above applied migrations through `finance.0005` and passed all 7 tests in 4.357 seconds.
- Affected fresh PostgreSQL run with the same environment: `.venv/bin/python manage.py test lamto.finance.tests.test_emergencies lamto.finance lamto.maintenance -v 1 --noinput` — 52 tests passed in 17.174 seconds.
- Migration drift check with the same environment: `.venv/bin/python manage.py makemigrations --check --dry-run finance maintenance` — no changes detected.
- `git diff --check` and the staged diff check were clean.

### Changed files and commit

- `src/lamto/finance/emergencies.py`
- `src/lamto/finance/models/emergencies.py`
- `src/lamto/finance/migrations/0005_remove_emergencyratification_emergency_ratification_provenance_and_more.py`
- `src/lamto/finance/tests/test_emergencies.py`
- `.superpowers/sdd/task-9-report.md`
- Correction implementation commit: `db04297` (`fix: bind emergency signatures and outcomes`).

### Self-review and minor finding

- The signed authorization timestamp now exactly equals the persisted timestamp, and the deadline remains exactly 24 hours later.
- Human outcome evidence contains the canonical digest of the normalized supplied reason and no raw reason.
- The new database constraint preserves the valid unsigned system-overdue row and rejects empty human signatures and mismatched decision/outcome pairs.
- No Task 10 or unrelated source changes were made. The pre-existing dirty `.superpowers/sdd/task-3-report.md` remains untouched.
- Minor finding retained as directed: a denied late decision still audits action `emergency.ratify` even when the attempted decision is `REJECT`; this correction pass did not widen scope to change it.

## Fix pass 2 — decision-time binding, DB boundaries, overdue labels

### Root cause evidence

1. `build_emergency_ratification_evidence_payload()` defaulted `decision_timestamp` to `authorization.authorized_at`, and `decide_emergency()` always persisted `timezone.now()` while verifying that unauthenticated default. A signature for one decision time could therefore produce a record at another, and the 24-hour window was not signature-bound for the human outcome.
2. A direct ORM/SQL update could set a requested emergency WorkOrder to `AUTHORIZED`. `start_work_order()` trusts that status, so paid work could start without a matching Board authorization/outbox transition.
3. Partial emergency request identity (`emergency=True` alone) was accepted at the database. Deadline was only constrained as `>` authorization time, not exact `+ 24 hours`. An unsigned `OVERDUE` row could be inserted before the deadline. An unsigned overdue outcome rendered as `Blockchain anchored` when only the earlier authorization outbox was confirmed.
4. Late denied decisions always audited `emergency.ratify`, including when the attempted decision was `REJECT`.

### TDD RED evidence

Regressions were present before production edits. Focused command:

```bash
SECRET_KEY=task9-fix2 POSTGRES_DB=lamto POSTGRES_USER=lamto POSTGRES_PASSWORD=lamto POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 CLAMAV_HOST=127.0.0.1 CLAMAV_PORT=3310 AI_TRIAGE_URL=https://triage.example.test/v1/triage AI_TRIAGE_TOKEN=test-token PRIVATE_STORAGE_ENDPOINT_URL=http://127.0.0.1:9000 PRIVATE_STORAGE_BUCKET=lamto-documents PRIVATE_STORAGE_ACCESS_KEY=lamto-local PRIVATE_STORAGE_SECRET_KEY=lamto-local-secret .venv/bin/python manage.py test lamto.finance.tests.test_emergencies -v 2 --noinput
```

Expected RED on a fresh PostgreSQL test database: 13 tests; 4 failures, 6 errors. Evidence included `decide_emergency() got an unexpected keyword argument 'now'`, `IntegrityError not raised` for direct AUTHORIZED / partial identity / premature OVERDUE / non-24h deadline, and overdue verification label `Blockchain anchored` instead of pending.

### Minimal repair

- Added keyword-only `now=` on `decide_emergency()` (default `timezone.now()`), validated it as timezone-aware, bound both the signed payload `decision_timestamp` and persisted `decided_at` to that value, and rejected decisions with `now >= ratification_deadline`.
- Late denied audits now use `emergency.ratify` or `emergency.reject` matching the attempted decision.
- `mark_overdue_ratifications()` selects authorizations with `ratification_deadline <= now` so the boundary matches human rejection at/after the deadline.
- `emergency_verification_label()` keeps unsigned OVERDUE (no outcome outbox) as `Pending blockchain anchoring` even when the authorization outbox is confirmed.
- Added `work_order_emergency_request_identity` CHECK requiring complete emergency request identity or a clean non-emergency row.
- Added trigger `work_order_emergency_authorization_required` so emergency WorkOrders cannot become `AUTHORIZED` without a matching `EmergencyAuthorization` row.
- Replaced the soft deadline CHECK with exact `authorized_at + interval '24 hours'` and added insert-time outcome temporal validation for OVERDUE/human decisions.
- Updated the emergency-proposal fixture so it authorizes through the service path instead of forging partial emergency state.

### GREEN verification

- Focused fresh PostgreSQL run: 14 tests passed.
- Affected suite: `.venv/bin/python manage.py test lamto.finance.tests.test_emergencies lamto.finance lamto.maintenance -v 1 --noinput` — 59 tests passed.
- `manage.py makemigrations --check --dry-run finance maintenance` — no changes detected.
- `git diff --check` — clean.

### Changed files and migrations

- `src/lamto/finance/emergencies.py`
- `src/lamto/finance/models/emergencies.py`
- `src/lamto/finance/migrations/0006_emergency_deadline_and_outcome_invariants.py`
- `src/lamto/finance/tests/test_emergencies.py`
- `src/lamto/finance/tests/test_proposals.py`
- `src/lamto/maintenance/models.py`
- `src/lamto/maintenance/migrations/0007_emergency_authorization_boundary.py`
- `.superpowers/sdd/task-9-report.md`

### Remaining intentionally application-trust-bound

- ECDSA signature verification and JSON canonicalization remain in the application/outbox path; PostgreSQL enforces relational/temporal/identity invariants and the emergency AUTHORIZED transition boundary, not cryptography.
- Task 10 (Foundry/OpenZeppelin contract work) remains gated until independent re-review of the full Task 9 range accepts these corrections.

## Fix pass 3 — emergency-on-already-AUTHORIZED boundary

### Root cause
The authorization-boundary trigger only checked when transitioning *into* `AUTHORIZED`. Setting complete emergency identity on an already-`AUTHORIZED` normal work order skipped the existence check. `request_emergency()` also accepted already-authorized work orders.

### Repair
- Service: `request_emergency()` rejects `AUTHORIZED` and other non-eligible statuses.
- DB: `maintenance.0008` replaces the trigger function with a pure state invariant: `emergency AND AUTHORIZED` always requires an `EmergencyAuthorization` row.
- Tests: service rejection + direct ORM conversion IntegrityError.

### GREEN
Focused emergency suite 15 passed; affected finance+maintenance suite results recorded in scratch.
