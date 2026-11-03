# Pilot runbook — normal accountability path

## Purpose

Prove one complete **real** normal maintenance/spend case end-to-end on the pilot
building: report → triage → proposal → Proceed decision → work → Settlement →
public ledger → Integrity observation.

## Preconditions

- Non-production or controlled pilot environment only.
- `PILOT_ALLOW_FIXTURES=1` only when loading seed data; production must keep it false.
- PostgreSQL migrated; private object storage reachable.
- Gate face threshold and sharpness are explicitly set from a committed reader-capture calibration report. If FMR=0 and FNMR<=5% cannot both be met, run plate recognition only. See `docs/ops/gate-threshold-calibration.md`.
- The worker is running (`.venv/bin/python manage.py run_worker`): it makes the
  triage suggestion, drains the evidence outbox, and records the Integrity
  observation of each ledger entry. Besu is optional; with
  `EVIDENCE_ANCHORING_BACKEND=disabled` evidence settles as `LOCAL_SIGNED`.
- Seed (non-prod):

  ```bash
  export PILOT_ALLOW_FIXTURES=1
  .venv/bin/python manage.py seed_pilot --fixture
  ```

  Prints login emails only; wallet private keys are never printed.

## Safety and ethics

- **No incident is manufactured.** Do not stage false hazards or delay real safety work.
- If a genuine emergency arises during the pilot window, follow the building's
  emergency procedures outside LamTo. Safety action is never delayed for pilot
  paperwork.

## Participants

| Participant | Responsibility |
|-------------|----------------|
| Resident | Report, inspect the public ledger |
| Management account | Triage, publish the proposal, make the Proceed decision, publish progress, complete the work, and file the Transfer proof |
| Worker | Drains the evidence outbox and records the Integrity observation |

One Management account performs the whole staff path. Managers meet and agree
offline before data entry; the application records the agreed result rather than
re-running the review. A building may have several Management accounts, but no
step requires a second person.

Management access is password-only in every deployment (ADR 0001): a successful
password login opens the workspace directly — there is no authenticator
enrollment or re-authentication step. Each authenticated `/s/` request renews a
persistent 400-day rolling session with no inactivity timeout and no
browser-close expiry. Selecting **Logout** is the normal way to end the session;
a password change, account disablement, browser cookie loss, server-side session
deletion, or secret-key rotation may also end it.

## Procedure (normal path)

1. A resident files a report with a photo and location in the Resident app.
2. A manager opens the report under **Cases** and confirms triage, choosing the
   Case location. The worker's suggestion prefills the category, urgency,
   Management queue and deadline; the manager may change any of them.
3. On the case, the manager chooses **Create spending proposal**, enters the
   amount and quotation document, and chooses **Publish proposal**. Create it before
   work starts: starting work closes that option.
4. On the published proposal, the manager records the Proceed decision under
   **Decide whether to proceed**. Proceeding starts the work; not proceeding
   closes it as not proceeding. One account decides alone, and the case's
   **Start work** is unavailable until the decision is made. A case with no
   spending proposal starts with **Start work**.
5. On the case, the manager publishes progress updates, each with a cause and
   result.
6. On the case, the manager chooses **Complete work** with a cause and result.
7. The manager chooses **Record settlement** on the completed proposal and
   files the Transfer proof. Filing it settles the proposal and creates the
   public ledger entry.
8. The resident opens the latest ledger entry in the Resident app: the actual
   cost, the Management account that made the Proceed decision, and the original supporting
   documents.
9. The worker records the Integrity observation for the entry. To record
   another, run
   `.venv/bin/python manage.py verify_integrity --entry-id <id>` (or `--all`).
   Document hashes must match their recorded values; with anchoring on, the
   chain must agree. With anchoring off the observation is LamTo checking its
   own records and names no verifier.

## Automated proof

```bash
.venv/bin/python manage.py test lamto.finance.tests.test_settlements -v 2
# optional browser suite (domain fallback if Chromium missing):
.venv/bin/python -m pytest tests/e2e -v
```

## Acceptance artifacts

Collect sign-off in `ops/acceptance-report-template.md` from the participating
Management accounts and resident.

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
  an Integrity observation records that it did not consult the chain.

## Onboard a new building

```bash
.venv/bin/python manage.py onboard_building \
  --name "Toà nhà Example" \
  --locations "Sảnh, Thang máy 1, Hầm xe" \
  --units "A-101,A-102,A-103" \
  --managers "manager1@example.vn"
```

The command creates missing manager users with unusable passwords and gives
existing or new users a Management account membership for the building. Then, per the
printed next steps: set manager passwords, register signer wallets,
add resident occupancies (with phone numbers), and record and confirm the fund
opening balance. Run `manage.py tenant_integrity` afterwards.
