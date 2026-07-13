# Emergency drill runbook — controlled, isolated, preserved

## Purpose

Exercise the emergency authorization → work-start-before-chain → 24h
ratification path with a **permanently labeled** drill that **never posts the
real fund** and **cannot convert to a real ledger record**.

## Non-negotiables

1. **No incident is manufactured.** Do not create false hazards.
2. **Safety action is never delayed** for drill paperwork or chain availability.
3. The pilot is **not held open** awaiting a genuine emergency.
4. Use **actual role accounts/wallets** (Board emergency authorizer, maintenance
   assignee, resident representative) — same dual-control rules as production.
5. Drill rows are permanently labeled **Emergency drill** (`drill=True`).

## When to run

- Prefer a scheduled **controlled drill** on a non-production work order that has
  not been normally authorized.
- If a genuine emergency occurs, handle it as live emergency (`drill=False`);
  do not re-label or convert a drill into a real fund posting.

## Procedure

1. Ensure chain may be paused or unavailable (publication still blocked for drills).
2. Operator requests emergency with `drill=True` and a clear safety reason text
   that includes the word “drill” in non-prod messaging.
3. Board emergency approver authorizes with signed estimate within process rules.
4. Maintenance starts assigned work while anchoring may show
   **Pending blockchain anchoring**.
5. Within **24 hours**, resident representative **RATIFY** or **REJECT** with reason.
   - Automated overdue path marks **OVERDUE** if no decision by deadline.
6. Resume/retry chain confirmation for authorization/outcome events; event IDs
   are preserved (no duplicate financial/chain rows).
7. Assert:
   - Fund balance unchanged by the drill
   - `ledger_count(drill=True) == 0`
   - Audit contains authorize / start / decide (ratify|reject|overdue)
   - Drill flag remains true (cannot convert to real)

## Automated outcomes

Domain suite covers:

- Rejected drill (isolated)
- Ratified drill (still no fund post without separate real publication rules)
- Overdue unsigned outcome

```bash
.venv/bin/python manage.py test \
  lamto.finance.tests.test_pilot_acceptance.PilotAcceptanceTests \
  -v 2
.venv/bin/python -m pytest tests/e2e/test_emergency_drill.py -v
```

## After-action

Record participants, timestamps, outcomes, and any chain outage notes in
`ops/acceptance-report-template.md`. Preserve all events; never delete drill
audit/outbox history.
