# Task 10 report

## Status

Complete. The pilot world now seeds one building, two management users with `ManagementMembership` signer wallets, and one resident. The surviving pilot driver flow uses the first manager for triage, work, acceptance, and payment recording, and the second manager for payment verification and publication.

## Sweeps

- Chased `PilotSeed` consumers across `src/lamto` and `tests`.
- No `seed.roles`, `seed.users`, legacy organization membership, capability grant, or role-capability references remain in the factory, e2e, isolation, pilot acceptance, or seed command paths.
- `git diff --check` passed.

## Verification

```text
uv run pytest src/lamto tests -q --ignore=src/lamto/web/tests
378 passed, 1 skipped in 60.33s
```

The skip is the existing opt-in live integration test.

```text
uv run pytest src/lamto tests -q
34 failed, 466 passed, 1 skipped in 74.37s
```

All 34 failures are confined to legacy web tests deferred to Tasks 11–12:

- `src/lamto/web/tests/test_exports_and_health.py` (6)
- `src/lamto/web/tests/test_fund_ops.py` (11)
- `src/lamto/web/tests/test_list_pattern.py` (2)
- `src/lamto/web/tests/test_proposal_create.py` (2)
- `src/lamto/web/tests/test_resident_views.py` (9)
- `src/lamto/web/tests/test_role_workspaces.py` (3)
- `src/lamto/web/tests/test_staff_signing.py` (1)

No failure occurred outside `src/lamto/web/tests/*`.

## Self-review

- Reused `ManagementMembership` and the existing wallet registration path; removed the eleven-key role emulation instead of adding a compatibility map.
- Preserved payment self-verification and publication dual-control with two distinct managers.
- Kept resident occupancy and the surviving report-to-publication domain behavior unchanged.
- `PilotDomainDriver` exposes only domain-flow methods; actor selection stays explicit inside the two management membership lists.

## Review follow-up

- Removed `PilotDomainDriver.login`, `_active_role`, and all role-switch choreography from factory consumers, e2e, isolation, API, notification, and pilot acceptance tests.
- Restored strict cross-building assertions: tenant object routes return exactly 404; scoped Management lists and audit exports return 200 and contain no other-building data.
- Fixed the root 403: the shared staff resolver now recognizes `ManagementMembership` and provides the unified Management capabilities while retaining the temporary legacy fallback needed by deferred web tests.

```text
uv run pytest tests/isolation/test_cross_building_access.py -q
10 passed in 6.77s

uv run pytest tests/e2e src/lamto/finance/tests/test_pilot_acceptance.py -q
18 passed in 15.91s

uv run pytest src/lamto tests -q --ignore=src/lamto/web/tests
378 passed, 1 skipped in 66.12s

uv run pytest src/lamto tests -q --tb=no
34 failed, 466 passed, 1 skipped in 80.42s
```

All full-suite failures remain confined to the seven previously listed `src/lamto/web/tests/*` files deferred to Tasks 11–12. Residue sweeps found no driver login API, `_active_role`, role-key choreography, or `seed.roles`/`seed.users` usage outside those deferred web tests.
