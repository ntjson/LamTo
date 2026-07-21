# Task 13 report

## Status

Complete. The legacy organization role model, grants, and emergency-support elevation model are removed. Building onboarding now creates the tenant skeleton and optional management users/memberships.

## Legacy sweep

The required non-migration Python sweep returned zero hits:

```text
grep -rn "OrganizationMembership\|CapabilityGrant\|Organization\b\|break_glass\|BreakGlass\|capabilit" src/lamto tests --include="*.py" | grep -v __pycache__ | grep -v migrations
```

Deleted `accounts/capabilities.py`, its tests, the five legacy models, capability services, and the enumerated security functions/constants. Remaining callers, forms, MFA audit attribution, and tests use `ManagementMembership`.

## Migration

Generated accounts migration `0015_remove_breakglasssession_authorizing_membership_and_more.py`; no historical migration was edited. It deletes the five legacy models and depends on the audit, finance/evidence, and maintenance cutover migrations so their old foreign keys and procedures are removed/replaced before the legacy tables are dropped.

A stale `test_lamto` database was dropped, and the targeted test run rebuilt it from scratch successfully. `manage.py makemigrations --check --dry-run` reports `No changes detected`.

## Tests

- Onboarding/security slice: `14 passed`
- Full suite: `460 passed, 1 skipped`
- `git diff --check`: clean

The skipped test is pre-existing and unrelated to Task 13.

## Follow-up residue cleanup

Removed the stale isolation exemption for the deleted support-elevation route, the unused `LAMTO_BREAK_GLASS_MAX_MINUTES` setting, and its obsolete operations-checklist reference. A case-insensitive `break[-_ ]?glass` sweep across non-migration Python under `src/lamto` and `tests` now returns zero hits.

- Isolation suite: `11 passed`
- Full suite: `460 passed, 1 skipped`
