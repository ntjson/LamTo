# Pilot runbook — normal accountability path

## Purpose

Prove one complete **real** normal maintenance/spend case end-to-end on the pilot
building: report → triage → proposal → dual approval → work → acceptance →
payment maker-checker → publication → resident ledger → auditor verify.

## Preconditions

- Non-production or controlled pilot environment only.
- `PILOT_ALLOW_FIXTURES=1` only when loading seed data; production must keep it false.
- PostgreSQL migrated; private object storage reachable; staff MFA enrolled for staff roles.
- Optional: Besu/outbox worker for live chain confirmation. If chain is paused or
  unavailable, local dual-control still permits work start with
  **Pending blockchain anchoring**; publication waits for confirmed evidence.
- Seed (non-prod):

  ```bash
  export PILOT_ALLOW_FIXTURES=1
  .venv/bin/python manage.py seed_pilot --fixture
  ```

  Prints login emails only. Wallet private keys are never printed; optional
  `--wallet-env .env.pilot-wallets.local` writes keys to an ignored local file.

## Safety and ethics

- **No incident is manufactured.** Do not stage false hazards or delay real safety work.
- If a genuine emergency arises during the pilot window, follow
  `ops/emergency-drill-runbook.md` / live emergency procedures — safety action is
  never delayed for pilot paperwork.
- The pilot is **not held open** awaiting an emergency to complete acceptance.

## Roles that must participate

| Role | Capability focus |
|------|------------------|
| Resident | Report, inspect published ledger (redacted docs) |
| Operator | Triage, work order, proposal create |
| Board approver | Proposal approve, optional accept |
| Resident representative | Co-approve proposal |
| Maintenance | Start/complete work with before/after photos |
| Board payment recorder | Accept work + record payment |
| Board payment verifier | Verify payment (not same user as recorder) |
| Eligible publisher | Publish ledger (not creator, board proposal approver, or payment recorder) |
| Auditor | Verify ledger hashes / chain / fund balance; exports |

## Procedure (normal path)

1. Resident submits issue report with photo and location.
2. Operator confirms triage and creates a **paid** work order.
3. Operator submits a signed proposal (amount + quotation pair).
4. Board approver approves; resident representative co-approves.
5. Maintenance starts work (may show **Pending blockchain anchoring** until
   prerequisite outbox events confirm) and completes with cause/result photos.
6. Board payment recorder accepts work and records payment evidence.
7. Board payment verifier verifies payment (self-verify denied).
8. Confirm chain/outbox events (`confirm_all_chain_events` in tests; worker in live).
9. Eligible publisher signs publication snapshot; finalize after confirmation.
10. Resident opens latest ledger entry: actual cost, **Record verified**, redacted docs only.
11. Auditor runs verification: document hashes match, chain events match (or local
    confirmed when registry unavailable), recomputed fund balance agrees.

## Automated proof

```bash
source /tmp/grok-goal-717590634826/implementer/env.sh  # or project env
.venv/bin/python manage.py test lamto.finance.tests.test_pilot_acceptance -v 2
# optional browser suite (domain fallback if Chromium missing):
.venv/bin/python -m pytest tests/e2e -v
```

## Acceptance artifacts

Collect sign-off in `ops/acceptance-report-template.md` from Board, operator,
resident representative, auditor, maintenance, and participating resident.

## Tenant integrity (nightly)

```bash
.venv/bin/python manage.py tenant_integrity
```

Runs the cross-building consistency checks (spec 2.3). Non-zero exit means a
scoping bug wrote cross-tenant references; treat as a security incident.

## Anchoring mode switch

`EVIDENCE_ANCHORING_BACKEND` (environment) selects the evidence anchoring
transport: `besu` (default, chain round-trip) or `disabled` (local settlement,
`LOCAL_SIGNED`).

- Switching is an audited ops action, never a UI toggle: record who/why/when in
  the ops log, then change the environment value and restart web + worker.
- Events keep the status they settled with. A `LOCAL` event is never
  retro-anchored; a `CONFIRMED` event keeps its chain record.
- Events still `PENDING` at switch time settle with whichever backend is active
  when the worker next claims them.
- Verify after switching: `/s/ops/health/?format=json` reports
  `anchoring_backend`; new publications must show `LOCAL_SIGNED` (disabled) or
  `CHAIN_CONFIRMED` (besu) — never each other's wording, badges, or export values.
- Disabling never disables: wallet signatures on decisions, the outbox,
  canonical hashing, publication gates, idempotent fund posting, corrections,
  or document-hash integrity checks. Only the chain round-trip is skipped, and
  chain-dependent verification observations are skipped, not faked.

## Onboard a new building

```bash
.venv/bin/python manage.py onboard_building \
  --name "Toà nhà Example" \
  --locations "Sảnh, Thang máy 1, Hầm xe" \
  --units "A-101,A-102,A-103"
```

Then, per the printed next steps: create staff users + memberships, grant
capabilities, register signer wallets, add resident occupancies (with phone
numbers), and record + verify the fund opening balance. Run
`manage.py tenant_integrity` afterwards.
