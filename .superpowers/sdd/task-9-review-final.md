# Task 9 final re-review — emergency authorization and 24-hour outcomes

**Range:** `0130eab..3ef9bac`  
**Diff:** `.superpowers/sdd/review-0130eab..3ef9bac.diff`  
**Mode:** read-only security/integrity re-review (no tree mutations)

## Verdict summary

| Gate | Result |
|---|---|
| Spec compliance | **FAIL** |
| Critical findings | **0** |
| Important findings | **1** |
| Quality | **Rejected** |

Fix passes 1 and 2 closed the previously reported signature-binding, provenance, deadline-equality, overdue-label, and direct-`AUTHORIZED` transition issues for the happy path. One database-boundary gap remains: an already-`AUTHORIZED` normal work order can be converted into an emergency without a matching `EmergencyAuthorization`, so emergency-labeled paid work can proceed without Board `EMERGENCY_AUTHORIZATION` evidence or the 24-hour outcome window.

---

## Findings

### 1. Important — Emergency identity can be applied after normal authorization without an EmergencyAuthorization row

**Location**
- `src/lamto/maintenance/migrations/0007_emergency_authorization_boundary.py` (`maintenance_require_emergency_authorization`, lines 33–55)
- `src/lamto/finance/emergencies.py` (`request_emergency`, lines 106–144)
- Consumers that trust `authorization_status` / emergency labels: `src/lamto/maintenance/workorders.py` (`start_work_order`), `src/lamto/maintenance/models.py` (`verification_label` / `emergency_label`)

**Description**

The authorization-boundary trigger only enforces “emergency + `AUTHORIZED` requires an `EmergencyAuthorization` row” when the row is inserted as that pair, or when `authorization_status` **transitions into** `AUTHORIZED`:

```sql
IF NEW.emergency IS TRUE
   AND NEW.authorization_status = 'AUTHORIZED'
   AND (
        TG_OP = 'INSERT'
        OR OLD.authorization_status IS DISTINCT FROM 'AUTHORIZED'
   )
THEN
    -- require finance_emergencyauthorization for this work_order
```

`request_emergency()` sets the emergency-request identity (`emergency=True`, requester, reason, timestamp, drill) but does **not** require `authorization_status == PENDING`, does not clear authorization, and does not require an emergency Board signature. Therefore this production path succeeds:

1. Complete normal dual approval so the work order becomes `AUTHORIZED` (no emergency row).
2. Call `request_emergency(...)` on that work order.
3. Trigger fires on `UPDATE OF emergency` but skips the existence check because `OLD.authorization_status` is already `AUTHORIZED`.
4. `start_work_order()` trusts `AUTHORIZED` and starts paid work.
5. Labels report `Emergency` / drill while `emergency_verification_label()` has no authorization outbox and never opens the 24-hour ratification/overdue path.

Regression coverage only exercises the reverse order: emergency request first, then a direct ORM update to `AUTHORIZED` (correctly rejected) and the valid `authorize_emergency()` path.

**Why it matters**

Global Task 9 constraint: emergency work must start from locally verified **Board emergency authorization** and then record ratify / reject / overdue inside the fixed 24-hour window. This path yields emergency-labeled, startable paid work with only normal proposal approvals—no `EMERGENCY_AUTHORIZATION` outbox identity, no immutable authorization deadline, and no mandatory outcome. That breaks the emergency accountability branch even though ordinary dual approval still occurred.

Fix pass 2 required closing alternate WorkOrder persistence so emergency work cannot sit in `AUTHORIZED` without a matching emergency authorization. The transition-only predicate does not establish that invariant as a state property.

**Suggested fix**

1. **Database:** In `maintenance_require_emergency_authorization`, require an `EmergencyAuthorization` row whenever `NEW.emergency IS TRUE AND NEW.authorization_status = 'AUTHORIZED'`, on both `INSERT` and any `UPDATE` that touches `authorization_status` or `emergency`—remove the `OLD.authorization_status IS DISTINCT FROM 'AUTHORIZED'` exception (or replace it with an always-on state check).
2. **Service:** In `request_emergency()`, reject work orders that are already `AUTHORIZED` / not `PENDING` (and ideally reject non-spending / already-started orders if those are out of scope for emergency request).
3. **Tests (RED then GREEN):**
   - Normal-authorize → `request_emergency` must raise at service layer and/or DB.
   - Direct ORM/SQL: set complete emergency identity on an already-`AUTHORIZED` non-emergency row → `IntegrityError`.
   - Keep the existing service-path authorize + start coverage green.

---

### Minor findings (non-blocking alone)

#### M1. Public signing helpers still default timestamps differently from service defaults

**Location:** `build_emergency_authorization_evidence_payload` / `build_emergency_ratification_evidence_payload` in `src/lamto/finance/emergencies.py`

Helpers default missing timestamps to `emergency_requested_at` / `authorized_at`, while `decide_emergency(now=None)` defaults to `timezone.now()`. Service paths that pass `timestamp=now` are fail-closed and correctly bound; clients that omit the keyword-only timestamp will get wallet mismatches rather than silent drift. Prefer requiring an explicit timestamp in typed-data builders (or defaulting them to the same clock source as the service) to match the plan’s positional `decide_emergency(...)` call shape safely.

#### M2. Insert-only model error text still says “Proposal versions are append-only”

**Location:** `InsertOnlyModel` in `src/lamto/finance/models/proposals.py`, reused by emergency models

Cosmetic; behavior is correct.

#### M3. Django state vs PostgreSQL deadline constraint intentionally diverge

**Location:** `EmergencyAuthorization.Meta` + `finance.0006_emergency_deadline_and_outcome_invariants`

PostgreSQL enforces `ratification_deadline = authorized_at + interval '24 hours'`; Django state keeps the weaker `gt` expression under the same constraint name. Documented and `makemigrations --check` is clean. Residual tooling/confusion risk only.

#### M4. Test gaps (hygiene)

- No direct-ORM regression for the human-outcome insert trigger (`RATIFY`/`REJECT` at/after deadline).
- No full happy-path `RATIFY` test (only `REJECT` / overdue / deny paths).
- Partial emergency-identity coverage exists; the post-`AUTHORIZED` emergency conversion above is the missing boundary case.

These do not by themselves reject the task, but M4’s missing conversion case is part of Finding 1’s required fix.

---

## Spec compliance checklist

| Requirement | Status |
|---|---|
| Emergency request fields + immutability after request | **Met** — fields, immutability trigger, identity CHECK (complete or clean non-emergency) |
| `request_emergency` capability, building, audit | **Met** — `WORK_ASSIGN` + allowed operator kind via capability map, building check, audit |
| Insert-only `EmergencyAuthorization` / `EmergencyRatification` + PG triggers + save/update/delete tests | **Met** |
| `authorize_emergency`: prior request, `EMERGENCY_AUTHORIZE`, signed payload (reason digest, estimate, drill, timestamp), atomic outbox + `AUTHORIZED`, deadline `+ 24h` | **Met** on service path; signature binds `authorized_at` / deadline |
| Exact 24h deadline at DB | **Met** — PG interval equality in `finance.0006` |
| Human decide binds `decided_at` to signed `decision_timestamp`; reject at/after deadline | **Met** — keyword-only `now=`, service + temporal insert trigger |
| Representative reason digest (not auth reason); raw reason not in outbox payload | **Met** |
| Provenance: unsigned system OVERDUE vs signed human RATIFY/REJECT pairs | **Met** — tightened CHECK in `finance.0005` |
| `mark_overdue_ratifications` idempotent, unsigned, no fabricated signature; deadline `<= now` | **Met** |
| Late human decision denied + audited without replacing OVERDUE; audit action matches decision | **Met** after fix pass 2 |
| Labels: Emergency / Emergency drill; overdue not “Blockchain anchored” on auth-only confirm | **Met** |
| Direct transition to `AUTHORIZED` without EA rejected | **Met** for status transition; **not met** for emergency-on-already-authorized (Finding 1) |
| Integer VND; privileged actions audited; `transaction.atomic` with outbox | **Met** |
| No PII beyond digests in evidence payloads | **Met** for emergency event schemas |
| No invented DB cryptography subsystem; residual app-trust crypto documented | **Met** (see residual risks) |

**Spec compliance: FAIL** because Finding 1 violates the emergency Board-authorization + 24-hour outcome invariant for emergency-labeled work and leaves the fix-pass-2 DB boundary incomplete as a state property.

---

## What fix passes correctly addressed

1. **Authorization timestamp binding** — `authorize_emergency` signs and persists the same `now`; rejects `now` before request; deadline derived from that value; covered by tests.
2. **Outcome reason binding** — representative reason is normalized, digested into the signed payload, and stored; mismatch fails signature verification.
3. **Decision-time binding** — `decide_emergency(..., *, now=)` binds signed `decision_timestamp` and `decided_at`; mismatched timestamps fail closed; at/after deadline rejected.
4. **Provenance CHECK** — empty human signatures and decision/outcome mismatches rejected at DB.
5. **Exact 24h deadline + outcome temporal triggers** — overdue before deadline and human at/after deadline rejected in PostgreSQL.
6. **Direct ORM `AUTHORIZED` without EA** (status transition) — rejected; service path still works.
7. **Complete emergency request identity CHECK** — partial `emergency=True` rejected.
8. **Overdue verification label** — unsigned OVERDUE stays pending even if authorization outbox is confirmed.
9. **Late deny audit action** — `emergency.ratify` vs `emergency.reject` matches attempted decision.
10. **Proposal emergency fixture** — uses real authorize service instead of forging partial emergency state.

---

## Residual risks (intentionally application-trust-bound)

These are accepted under the project rule “do not reimplement ECDSA / JSON canonicalization in PostgreSQL,” and match the implementer report:

1. **ECDSA recovery and canonical JSON hashing** remain in `queue_signed_event` / application code. PostgreSQL enforces relational, temporal, and emergency-`AUTHORIZED` existence invariants (once Finding 1 is closed), not cryptographic validity of signatures.
2. **`EmergencyAuthorization` / human `EmergencyRatification` rows can still be inserted via app-role ORM/SQL** if a pre-existing signed outbox row is attached (including a recycled event of another `event_type`), because finance tables retain ordinary `INSERT` privileges and there is no DB check that `outbox_event.event_type` is `EMERGENCY_AUTHORIZATION` / `EMERGENCY_OUTCOME` or that payload `work_order_id` matches. Creating a *new* outbox identity still requires the signed write procedure. Documented residual; optional future hardening is a BEFORE INSERT linkage trigger on event type + payload id, not full crypto in PG.
3. **Caller-supplied `now` for authorize/decide** is signature-bound but not clamped to server clock skew. A Board signer can bind a future authorization timestamp and thus a future 24h window; that is Board-key power, not an unsigned bypass.
4. **Outbox delivery status** remains mutable by design; only signed identity/payload fields are immutable.

Finding 1 is **not** residual app-trust crypto; it is a missing feasible relational/state invariant.

---

## Test and code-quality notes

- Focused suite drives shipped services (`request_emergency`, `authorize_emergency`, `decide_emergency`, `mark_overdue_ratifications`, payload/typed-data builders, `start_work_order`) rather than private hooks.
- Insert-only coverage includes instance `save()` and queryset update/delete for both emergency models.
- Boundary tests added in fix pass 2 for direct `AUTHORIZED`, partial identity, exact 24h deadline, premature OVERDUE, and decision-time binding.
- Gap: no regression for emergency conversion of an already-`AUTHORIZED` normal work order (Finding 1).
- Report claims (14 focused / 59 affected tests, makemigrations clean) are consistent with the delivered tree; this re-review did not re-execute the suite (read-only).

---

## Final scores

- **Spec compliance:** FAIL  
- **Critical count:** 0  
- **Important count:** 1  
- **Quality:** Rejected  

**Gate for Task 10:** Do not start Task 10 until Finding 1 is fixed with additive migration + service guard + RED/GREEN regressions and an independent re-review of the correction range.
