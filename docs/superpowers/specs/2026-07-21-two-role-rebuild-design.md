# Two-Role Rebuild — Design

**Date:** 2026-07-21
**Status:** Approved
**Approach:** Collapse in place (staged), no data preservation, Flutter-only resident surface.

## Goal

Rebuild LamTo around exactly two human user types and two user interfaces:

1. **Management** — one desktop-first web workspace.
2. **Residents** — the Flutter mobile app.

Board, Operator, Maintenance, Resident Representative, Auditor, and Technical Admin disappear from the product model, authorization, APIs, navigation, forms, tests, and UIs. Internal service accounts (AI triage worker, anchoring worker, Django superuser) remain but have no product-facing interface. Contractors and payees have no system role or portal.

## Decisions made during brainstorming

| Question | Decision |
|---|---|
| Rebuild style | Collapse in place — keep repo, infra, evidence pipeline, app, chain |
| Existing data | None to preserve; reshape schema freely, plain new migrations |
| Payee acknowledgement | Management uploads acknowledgement evidence (signed receipt etc.); settlement model reserves a `PAYEE_LINK` ack kind for a future tokenized link |
| Legacy workflows | Delete all four: approvals, emergencies, corrections, work orders (acceptance folds into "mark completed") |
| Resident surface | Flutter app only; resident web PWA deleted; web becomes Management-only |
| Structure | Staged collapse: four sequenced sub-projects, each ending green |
| Fund ledger | Off-chain fund ledger, `/fund/series`, and fund-balance UI on both surfaces all remain; only per-ledger-entry chain anchoring is removed |

## 1. Roles & access

- **Resident** = user with an active `ResidentOccupancy` (unchanged).
- **Management** = new `ManagementMembership(user, building, active)` — one table, building-scoped. Replaces `Organization`, `OrganizationMembership` (six roles), and `CapabilityGrant`. `capabilities.py` is deleted.
- Authorization collapses to two gates: `management_required` and `resident_required`. No capability codes or role checks anywhere.
- Management keeps MFA + re-auth for sensitive actions. Break-glass is deleted with the emergency flow.
- The staff membership switcher becomes a building switcher.
- Evidence signing uses the platform key (server-side); Management identity is recorded off-chain.

## 2. Request lifecycle (happy path 1)

Kept entities: `IssueReport` + `ReportPhoto` + `BuildingLocation`, `TriageJob`/`TriageSuggestion`/`TriageDecision`, `MaintenanceCase` + `CaseReport` (duplicate merging), `WorkUpdate` (+evidence), `CompletionRating`.

- **AI triage** (suggest-only, existing manual fallback kept): suggestion already carries category, urgency, interpreted location, confidence %, duplicate report ids, and `department` (relabeled "Management queue" in product copy). Add `missing_information` to `TriageSuggestion`. Management confirms or edits via `TriageDecision`. AI never rejects, approves, closes, or decides.
- **Resident-visible status lives on the report:**
  `SUBMITTED → IN_REVIEW → NEEDS_INFO → (DECLINED | IN_PROGRESS | PROPOSED) → COMPLETED → CLOSED`
- **Outcome A — more information:** new `InfoRequest(report, message, created_by, created_at, resolved_at)`; one open at a time; resident replies with text/photos/documents attached to the report; report returns to `IN_REVIEW`. No chat, no escalation, no disputes.
- **Outcome B — not proceeding:** decline reason + timestamp + decider recorded as fields on the report; resident sees the reason; request closed. No appeals.
- **Outcomes C and D both create (or attach to) a `MaintenanceCase`.** C tracks the work directly on the case; D additionally attaches a proposal to the case (section 3). `WorkUpdate` re-parents from `WorkOrder` to the case; residents see status, progress notes, and photos. No work-assignment workflow; internal responsibility notes only.
- **Rating:** `CompletionRating` becomes binary Satisfied / Not satisfied (+optional comment), one per rater, parented case-XOR-proposal. For case-backed requests, each reporter is invited to rate on completion; the request closes when they rate or after 14 days, whichever comes first. Ratings are off-chain.
- **Private requests** (e.g. vehicle-card replacement): `is_private` flag on the report; outcomes A/B/C only; excluded from community lists; fully off-chain.

## 3. Proposals & settlements (path D + happy path 2)

- `Proposal` detaches from `WorkOrder`: nullable `case` FK — set for outcome D, null for Management-initiated proposals (happy path 2).
- Version snapshots carry: problem/need, proposed action, estimated cost (VND), funding source, contractor/responsible party, supporting document versions, expected schedule — using the existing append-only version pattern.
- **Publish** = canonicalize → hash → sign (platform key) → anchor, via the existing evidence pipeline. Published versions are immutable; a material change creates a new version, anchored again; all versions stay visible.
- Proceed / not-proceed is a recorded Management decision, off-chain.
- Progress uses `WorkUpdate` with nullable case-XOR-proposal FKs (DB check constraint). Rule: updates attach to the case whenever one exists (outcomes C and D); the proposal FK is used only for standalone proposals (happy path 2).
- **Rating for standalone proposals:** any resident of the building may rate a completed standalone proposal (Satisfied / Not satisfied, one per resident). The proposal closes 14 days after completion — or immediately after settlement if later — and ratings remain viewable after closure.
- **Settlement:** existing `Payment` reshaped into `Settlement(proposal, amount, payee_name, transfer_evidence, ack_evidence, ack_kind)` reusing the original/redacted proof-pair machinery. `ack_kind` = `MANAGEMENT_UPLOAD` now; `PAYEE_LINK` reserved. The settlement record is created only when **both** evidence sides exist, then hashed, signed, and anchored. A payment is settled only at that point.
- Settled amounts feed `MaintenanceFundEntry` and the fund chart exactly as today.

## 4. Surfaces & API

- **Web = Management only.** One workspace: action inbox (single queue), requests (triage confirm/edit + A/B/C/D actions), proposals, settlements + fund, documents, exports. Per-role view modules replaced by topic modules. Resident PWA (`/r/...`, offline page, manifest, service worker) deleted.
- **Flutter app = Resident interface.** New/reworked: respond to info request, view decline reason, case progress timeline, proposal detail with versions and progress, binary rating. Existing submit-request, ledger, and fund chart stay. `lamto_api` Dart client regenerated from the updated OpenAPI schema.
- Audit trail stays as internal logging; auditor workspace disappears; exports live under Management.
- Residents need no blockchain wallets; verification is in-app, server-mediated, with an optional explorer link.

## 5. Chain anchoring

Exactly two anchored artifact types:

1. Finalized, published proposal versions.
2. Completed payment-settlement records.

Anchoring of everything else (ledger entries, payment verification, acceptance, publication artifacts) is removed. Never on-chain: photos, personal data, AI results, comments, progress updates, Management reasons, information requests, resident ratings. The existing worker/retry/integrity-status pipeline is reused; contracts gain a settlement payload-type id only if the registry distinguishes types.

## 6. Module disposition

| Module | Kept as-is | Reshaped | Removed |
|---|---|---|---|
| `accounts/` | `backends`, `managers`, `mfa`, `middleware`, `services` | `models` (keep Building/Unit/User/ResidentOccupancy; add `ManagementMembership`), `tenancy` (two-gate context), `security` (minus break-glass), `onboard_building` (rewritten) | `capabilities.py`; `Organization`, `OrganizationMembership`, `CapabilityGrant` |
| `finance/` | `fund.py`, `selectors.py` | `payments.py` → settlements, `proposals.py` (case-or-standalone, seven fields), `publication.py` + `integrity.py` (two anchor types), `models/` | `approvals.py`, `emergencies.py`, `corrections.py`, `acceptance.py` + models/tests |
| `maintenance/` | `ai.py` core, `candidates.py`, `reporting.py` | `models` (statuses, `InfoRequest`, `is_private`, `WorkUpdate` and binary `CompletionRating` re-parented case-XOR-proposal), `triage.py` (+`missing_information`), `ratings.py`, `selectors.py` | `workorders.py` + `WorkOrder` |
| `evidence/` | `canonical`, `chain`, `signatures`, `worker`, `services` | `models` (types → PROPOSAL_VERSION + SETTLEMENT) | — |
| `documents/` | `models`, `scanner`, `services` | `access.py` (two gates) | — |
| `audit/` | `models`, `services` | — | auditor-facing UI |
| `notifications/` | `devices`, `push`, `hooks` | `services` (targeting → management/resident) | — |
| `api/` | `authentication`, `problems`, `downloads`, `occupancy` | `views`/`serializers`/`urls` (prune role endpoints; add info-reply, proposals, binary rate) | role-scoped endpoints |
| `web/` | `views/fund.py`, `views/exports.py`, `views/health.py`, `views/security.py` | `staff.py` (management nav + building switcher), `action_inbox.py` (single queue), `staff_common.py`, `urls.py`; new: requests, proposals, settlements views | role view modules, resident templates, PWA, role-workspace tests, break-glass |
| `app/` | ledger, fund chart, submit-request | new resident screens; client regen | work-order screens |
| `chain/` | contracts, Besu, explorer | settlement payload-type id if needed | — |
| docs | — | `PRODUCT.md` users, triage-labels agent doc | — |

## 7. Implementation stages

Each stage is its own implementation plan and ends with a green suite.

1. **Two-role foundation.** Accounts collapse, two authz gates, tenancy reshape; delete `approvals`/`emergencies`/`corrections`/`acceptance`, role views, role nav, role tests, resident PWA, break-glass; consolidate management workspace shell and single inbox. `WorkOrder` survives this stage untouched so nothing dangles.
2. **Request lifecycle.** Report status machine, `InfoRequest` loop, decline fields, `is_private`, triage `missing_information`; re-parent `WorkUpdate` + `CompletionRating` to the case; swap `Proposal.work_order` → `Proposal.case` mechanically; then delete `workorders.py` + `WorkOrder`. Management request-review UI with A/B/C/D actions. Minimal app compatibility patch (rating shape).
3. **Proposals & settlements.** Seven spec fields, standalone proposals, publish→hash→sign→anchor; `Payment` → `Settlement` with dual evidence + reserved `PAYEE_LINK`; evidence types pruned to two; publication/integrity reshaped; management proposal + settlement UI; settlement payload type on chain.
4. **App + API alignment.** Full Flutter build-out (info-reply, decline view, progress timeline, proposal detail, rating), Dart client regen, docs rewrite, and two e2e scripts: happy path 1 (variants C and D) and happy path 2.

## Testing

- Django suite green at the end of every stage; Flutter tests green from stage 2 onward (compatibility patches included in the stage that breaks them).
- Chain tests extend only for the settlement payload type.
- E2E: two scripts mirroring the happy paths end to end, including anchor verification.

## Out of scope (explicitly)

Appeals, disputes, multi-level approvals, chat, escalation workflows, staff work assignment, contractor portals, payee accounts, resident wallets, emergency spending flow, correction/republication flow, anchoring anything beyond the two artifact types.
