# Phase 0 (Foundation) + Phase 1 (Resident Mobile v1) Design

**Status:** Approved design, pending written-spec review

**Date:** 2026-07-14

**Builds on:** `2026-07-11-accountability-mvp-design.md` (the P1 spec). P1 invariants remain authoritative, with exactly one explicit amendment: anchoring becomes a configurable transport (§5.2), so a deployment may settle evidence locally (`LOCAL_SIGNED`) instead of on-chain — honestly labeled everywhere and never presented as chain confirmation. All other gates (signatures, separation of duties, append-only records, publication prerequisites) are unchanged in both modes.

## 1. Goal and approach

Evolve the single-building pilot into a product that supports many buildings, a native resident mobile client, and a stronger BQL ops console — while the P1 maintenance + fund-ledger accountability chain keeps working and its e2e suite stays green.

### Chosen approach: evolve in place

The Django modular monolith remains the single backend. Phase 0 hardens what exists (tenancy, selectors, anchoring port, staff UI gaps); Phase 1 adds a new Flutter client speaking to a new resident-only API. Staff stay on the server-rendered `/s/` web surface.

Rejected alternatives:

- **API-first re-platform** (full DRF for residents and staff, staff SPA): rewrites the highest-risk surface (signed actions, maker-checker, MFA/reauth) for no user-visible gain, with months of P1 regression exposure. Rejected.
- **PWA-max, no native app** (invest in web push + installability instead of Flutter): cheapest Phase 1, but iOS web push is unreliable for the older-adult demographic, it contradicts `DESIGN.md`'s platform-native commitment, and a later native app redoes the client work. Rejected given available Flutter experience.

### Constraints honored throughout

- One backend, two clients long-term: resident mobile (Flutter) + BQL web.
- Vietnamese product language; integer VND; mobile-first residents; older-adult-friendly UX; WCAG 2.2 AA.
- Staff MFA stays; no secrets in git; tenant isolation is a security feature.
- YAGNI: no microservices, no message broker, no event sourcing, no resident crypto wallets, no schema-per-tenant.

### Facts this design rests on

- The schema is already tenant-shaped: `Building`, `Unit(building)`, `Organization(building, kind)`, `OrganizationMembership`, `CapabilityGrant`, `ResidentOccupancy`, `BuildingLocation(building)`, `MaintenanceCase(building)`, `Document(building)`, `MaintenanceFund` 1:1 with `Building`.
- Staff views already filter by `membership.organization.building_id`; resident views scope through `occupancy.unit.building`; a session membership switcher exists.
- Known gaps: no API layer (no DRF), `_active_occupancy()` takes `.first()`, `BlockchainOutboxEvent` has no building scope (bare-PK lookup at `auditor.py`), no proposal-creation or fund-ops staff UI, no push infrastructure, no anchoring on/off port.
- Deployment state: deployed pre-acceptance with seed/test data — normal Django migrations suffice; no zero-downtime choreography.

---

## Phase 0 — Foundation

## 2. Tenancy model and isolation

### 2.1 Tenant model (no new entities)

**`Building` is the tenant key.**

- **User** — global. One account may hold occupancies and memberships in any number of buildings. Add `phone` (unique, nullable) to `User`; a new auth backend accepts phone **or** email + password. Staff keep email; residents get phone, provisioned by BQL (no self-signup in Phase 0/1).
- **Organization** — stays per-building, per-kind. A PM company operating N buildings owns N per-building `Organization` rows; multi-building staff hold one membership per building and use the existing switcher. *Deferred upgrade path (documented, not built):* nullable `Organization.company` FK, backfilled when consolidated cross-building views arrive (Phase 2+).
- **OrganizationMembership / CapabilityGrant / SignerWallet** — unchanged; tenancy inherited through the organization.
- **ResidentOccupancy** — schema unchanged; the selection rule changes (§2.4).

### 2.2 Global vs per-tenant

| Global (shared across buildings) | Per-tenant (building-scoped) |
|---|---|
| User accounts, passwords, MFA devices, auth throttles | Units, locations, occupancies |
| Break-glass sessions, backup markers | Organizations, memberships, capabilities, wallets |
| The Besu chain and the outbox event *stream* | Fund + all fund entries |
| Push `Device` registrations (per user) | Reports, cases, work orders, proposals, payments, ledger, corrections, documents |
| — | Outbox event *rows* (via new `building` FK), notification deliveries, quarantined uploads |

**Outbox tenanting.** `BlockchainOutboxEvent` gains an immutable `building` FK (`PROTECT`), set at creation from the anchored record and guarded against update; existing pilot rows are backfilled through their linked records. Every UI/API/export lookup filters by it. Bare-primary-key outbox fetches are removed (the auditor lookup first). Rule: **an outbox event is visible only if the record it anchors is.**

**Shared-chain privacy claim (narrow).** No personal *content* is stored on-chain, but timing, signer identifiers, and traffic patterns remain observable to chain participants. Audit requirement: event IDs (already random 32-byte values) and canonical payloads must carry only opaque identifiers — never building names, never predictable sequential local IDs.

**Tenant ownership for global-ish records.** `NotificationDelivery` and `QuarantinedUpload` each gain a `building` FK (nullable only for legacy/system rows; backfilled where derivable). The action-inbox quarantine query switches from join-inference to the direct FK.

### 2.3 Isolation enforcement — four layers

Isolation is enforced by layered mechanisms, not by tests alone and not by queryset middleware magic:

1. **Explicit request tenant context.** A frozen `TenantContext` dataclass (`building_id`, actor kind, membership id or occupancy id) is resolved once per request and passed explicitly to domain code. Staff: active membership from session. Resident web: active occupancy from session. Resident API: validated occupancy header (§3.4).
2. **Shared building-scoped selectors.** Each domain module exposes selector/service functions that require the tenant context (or `building_id`) as a parameter. Templates and API both call these — one query path, one set of gates. Extracting these from the current view helpers is the first, behavior-preserving Phase 0 refactor.
3. **Database cross-building consistency.** Composite-FK pattern on the high-value edges — `UNIQUE (id, building_id)` on parent tables plus composite foreign keys from children (raw-SQL migrations; models unchanged): case↔location, report↔unit and report↔location, triage-decision↔location. Plus a `tenant_integrity` management command (extending the `finance/integrity.py` pattern) asserting cross-record building consistency, run in CI and nightly.
4. **Two-building adversarial suite.** `seed_pilot` gains a second building (own orgs, staff, residents, fund, one fully published expenditure). A parametrized suite walks **every registered URL (web and API)** as every role of Building A substituting Building B object IDs, and must receive 404/403, never data. New endpoints are added to the walk automatically via the URL registry. Runs in CI forever as part of the P1 regression gate.

**Status-code convention:** cross-tenant object access → **404** (existence not revealed). Missing capability within the caller's own tenant → **403**. Applies to web and API identically.

### 2.4 Occupancy selection rule

Kill the `.first()`. A resident's active context is one explicitly chosen active occupancy:

- Exactly one active occupancy → auto-selected.
- Multiple → web: session-stored choice with a minimal picker row in Account; API: validated header (§3.4); mobile: picker screen (§6).
- Occupancy selection is always validated server-side against the caller's own active occupancies; unit and building always derive from the validated occupancy, never from client-supplied building IDs.

### 2.5 Migration path from the pilot

1. Migrations: `User.phone` + auth backend; `building` FK on `BlockchainOutboxEvent`, `NotificationDelivery`, `QuarantinedUpload` (+ backfills); composite-FK constraints.
2. Code: `TenantContext` + selector extraction; occupancy selection rule; outbox lookup scoping; scope-audit fixes across views, forms, action-inbox builders, exports, worker jobs.
3. Seeds/tests: second building in dev/CI seeds; adversarial suite; `tenant_integrity`.
4. Runbook + command: `onboard_building` (Building, Units, Locations, Organizations, Fund, memberships, opening balance) reusing seed logic minus demo data.

Production pilot data is already a valid single tenant; it is not rebuilt.

## 3. API for mobile

### 3.1 Style and shape

- **REST + JSON via Django REST Framework**, mounted at `/api/v1/` in the same monolith process. URL-path versioning; breaking changes mean `/v2/`, additive changes don't bump.
- **Resident-only surface.** Staff get no API in Phase 0/1; their MFA'd, reauth-gated, signed-action web flows are untouched.
- **Parallel, not strangler.** Templates keep serving the web PWA. Both presentation layers call the shared selectors (§2.3). No template view is rewritten to consume the API.
- **Errors:** RFC 9457 `application/problem+json` plus a stable machine `code` field (e.g. `occupancy_selection_required`, `client_ref_conflict`, `validation_failed` with per-field codes). `detail` is developer English; the Flutter client owns all Vietnamese user-facing copy keyed off `code`. No stack traces or internal identifiers in responses.
- **Pagination:** DRF cursor pagination (stable under concurrent inserts), default page size 20, cursor links only.
- **Schema:** drf-spectacular generates OpenAPI; the schema file is committed. CI regenerates and fails on diff. The generated Dart client is regenerated and diffed in the app's CI. Contract checks sit alongside the two-building adversarial suite, which covers all API routes.

### 3.2 Resident auth and token lifecycle

- **django-rest-knox** per-device tokens. `POST /auth/login` (phone or email + password) → token + expiry. TTL 30 days, sliding refresh on use.
- **Client storage:** iOS Keychain / Android Keystore only (`flutter_secure_storage`); never plain preferences.
- **Revocation:** `POST /auth/logout` deletes the calling device's token; `POST /auth/logout-all` deletes all of the user's tokens. Deactivating a user (or their last active occupancy) deletes all their knox tokens server-side, and authentication rejects inactive accounts regardless.
- **Device cap:** 5 concurrent tokens per user; oldest evicted at login.
- **Throttling:** login reuses the existing `AuthThrottleBucket` (account|IP keyed).
- Auth tokens and FCM device tokens are separate records; an FCM token is never an auth credential (§7).
- No JWT (weaker revocation), no OAuth (no third-party clients), no resident MFA (write surface is report submission; staff MFA unchanged).

### 3.3 Endpoints

| Area | Endpoints |
|---|---|
| Session | `POST /auth/login`, `POST /auth/logout`, `POST /auth/logout-all` |
| Identity | `GET /me` — profile, active occupancies (id, unit label, building name), notification prefs |
| Reporting | `GET /reports` (mine), `POST /reports`, `GET /reports/{id}` (timeline: triage → case → work → acceptance), `POST /reports/{id}/photos` (multipart), `POST /work/{id}/rating` |
| Reference | `GET /locations` — active location tree for the selected occupancy's building |
| Ledger | `GET /ledger` (published entries, period filters), `GET /ledger/{id}` (plain-language payload + expandable proof with evidence level, hashes, event IDs, chain status), `GET /fund/summary` (balance + period in/outflows) |
| Push | `POST /devices` (register/upsert FCM token), `DELETE /devices/{install_id}` |
| Feed | `GET /notifications` (in-app feed), mark-read |

**Phase 0 slice:** plumbing (DRF, knox, problem-json handler, tenant-context resolution for tokens, throttles, OpenAPI + CI drift checks, adversarial walk over API routes) plus `/auth/*`, `/me`, and read-only `/ledger` + `/fund/summary`. **Phase 1 slice:** the reporting write path, `/locations`, `/devices`, `/notifications`, ratings.

### 3.4 Occupancy context (server-validated)

Requests carry `X-LamTo-Occupancy: <id>`. The server validates it against the caller's own **active** occupancies and derives unit + building from the validated occupancy. Sole active occupancy → auto-selected when the header is absent. Multiple occupancies and no header → 422 `occupancy_selection_required`. An ID that is not the caller's active occupancy → 404. A client-supplied building ID is never trusted or accepted.

### 3.5 Idempotent report submission

`POST /reports` requires a client-generated `client_ref` UUID (unique per user):

- First submission → 201.
- Retry with the same `(user, client_ref)` and canonically identical content (text, occupancy, location) → 200 returning the existing report.
- Same `client_ref` with materially different content → 409 `client_ref_conflict`.

Photos upload separately after the report row exists (per-photo retry), so a dropped upload never loses the report text — preserving the P1 "commit report before AI call" invariant.

### 3.6 Uploads and downloads

- **Uploads go through Django** (multipart, size/type-checked), never presigned MinIO URLs — the ClamAV scan/quarantine gate must stay in the path. Same pipeline as the web form.
- **Signed download URLs:** authorization runs before issuance on every request. The resident API code path can only issue URLs for the caller's own report photos and **redacted** variants of published-ledger documents; original-variant issuance is unreachable from the resident surface (not merely forbidden). TTL ≤ 5 minutes; responses carry `Cache-Control: private, no-store`; storage keys stay random/opaque (no building, unit, or filename components); signed URLs are never written to logs.

## 4. BQL ops web — upgrade of `/s/`

### 4.1 Users

Exactly the existing roles; Phase 0 adds none: operator (intake, cases, work, proposals, corrections), maintenance (assigned work only), Board members with explicit capability grants (approve, emergency-authorize, accept, record payment, verify payment, record/verify fund entries, publish), resident representative (co-approval, ratification), tech admin (health, accounts, break-glass), auditor (kept as-is: read/verify/export). `CapabilityGrant` remains the authority; a bare BOARD role authorizes nothing.

### 4.2 Information architecture

Top nav: seven stable areas, capability-filtered per active membership — **Inbox** (default landing, authoritative) · **Cases** · **Work** · **Finance** (proposals · payments · fund) · **Ledger** (published entries, corrections, integrity observations) · **Audit** · **Ops**.

Tenancy-UX guards for multi-building staff:

- The building name sits in the persistent header chrome next to the membership switcher — staff always see which building they act in before signing anything.
- Switching membership returns to the Inbox, never deep-links into a detail page from the previous building.

### 4.3 Gap-filling (the Phase 0 build work)

1. **Create-proposal flow** (UI over the complete domain): from a work-order detail page (operator; spending-required orders only) — amount (integer VND), contractor, purpose, quotation upload → freeze immutable version → operator signs → Board inbox. Reuses `SignedDecisionForm` and the existing document pipeline.
2. **Fund ops screens** (`/s/fund/`, currently unreachable outside seeds/commands): entries list + derived balance + staff-only pending-reconciliation block (paid-but-unpublished); record opening balance/inflow with evidence upload (fund-recorder capability); verification screen (fund-verifier capability; `verifier ≠ recorder` enforced server-side as today).
3. **List/detail polish, not redesign:** one shared list-page pattern (filter chips, status chips, deadline badges) applied to cases/work/proposals/payments. Server-rendered Django templates + vanilla JS stay.

### 4.4 Explicitly unchanged

MFA gate, reauth-on-signed-actions, wallet signing (`SignedDecisionForm`), maker-checker separations, publication gates, auditor exports, break-glass audit. No SPA, no staff API, no new frontend framework. Desktop-first, tablet-acceptable, per `DESIGN.md`.

## 5. Keeping P1 stable

### 5.1 Evidence levels (replaces any boolean notion of "verified")

Verification state is an explicit enum used consistently by domain helpers, API responses, resident labels, staff badges, and auditor exports:

`PENDING` · `LOCAL_SIGNED` · `CHAIN_CONFIRMED` · `MISMATCH`

No generic `verified` boolean exists anywhere. Gate helpers operate on the enum (`is_settled` = `LOCAL_SIGNED` or `CHAIN_CONFIRMED`); exports carry the enum value verbatim.

### 5.2 The anchoring port

`EVIDENCE_ANCHORING_BACKEND = besu | disabled` (env-level, global per deployment; a per-building column is the documented later upgrade, one migration away).

- **Port interface** wraps what the worker already does: `submit(event) → receipt`, `check_confirmation(event) → status`. `BesuBackend` is the current web3 code, unchanged. `DisabledBackend` settles events immediately and locally.
- **Honest statuses:** disabled-mode events settle with outbox status `LOCAL` (empty `transaction_hash`), never `CONFIRMED`. Their evidence level is `LOCAL_SIGNED`, never `CHAIN_CONFIRMED`.
- **LOCAL publications:** resident-visible only with an explicit off-chain integrity label (plain language: records signed and hash-locked; blockchain anchoring is off for this deployment). Wording, badges, export columns, and pilot metrics for `LOCAL_SIGNED` never reuse `CHAIN_CONFIRMED` presentation. `PublicationSnapshot` immutably records the anchoring backend and evidence level in force at settlement.
- **What disabling never disables:** wallet signatures on decisions (separation-of-duties evidence stays mandatory in both modes), the outbox, canonical hashing, idempotent publication → fund posting, corrections, integrity recomputation of stored document hashes. Only the chain round-trip is skipped; chain-dependent verification observations are skipped, not faked.
- **Mode-switch runbook:** events keep the status they settled with (a `LOCAL` event is never retro-anchored in place); pending events settle with whichever backend is active; switching is an audited ops action, not a UI toggle.

### 5.3 Non-negotiables → enforcement

| Invariant | Enforced by |
|---|---|
| Append-only financial records | `InsertOnlyModel` guards + DB constraints (existing tests) |
| Integer VND only | `BigIntegerField` + sign constraints (existing) |
| Separation of duties | Domain checks + `test_payment_separation` e2e (existing) |
| Human confirms AI triage | `TriageDecision` required before any case (existing) |
| Platform never initiates/holds funds | No such code path; review-time check — no payment-provider dependency may enter `pyproject.toml` |
| Ledger resident-visible only after gates | Publication gate suite, run in **both** anchoring modes (new) |
| Tenant isolation | Adversarial suite + composite FKs + `tenant_integrity` (new) |

### 5.4 Regression gates

1. **The six e2e journeys** (`tests/e2e/`: normal flow, emergency drill, tamper + correction, payment separation, role access, blockchain outage) stay blocking in CI through every Phase 0 refactor.
2. **New permanent gates:** two-building adversarial walk (web + API); `tenant_integrity` in CI + nightly; OpenAPI drift check; a disabled-mode CI job running publication, correction, and fund flows with `EVIDENCE_ANCHORING_BACKEND=disabled`.
3. **Runbooks that must keep working:** restore drill (hash + fund-balance reconciliation), `seed_pilot`, `onboard_building`.

**Sequencing rule:** the riskiest refactor (selector extraction) lands first, behind the full existing suite, before any new surface (API, fund screens, Flutter) builds on top.

---

## Phase 1 — Resident mobile v1

## 6. Flutter resident app

### 6.1 Client decision

**Flutter.** Rationale: existing Flutter experience on the team; `DESIGN.md` commits residents to platform-native shells (HIG + Material 3) and forbids shipping web chrome as the native app; FCM gives reliable push on both platforms where iOS web push (16.4+, manual home-screen install) is hostile to the older-adult demographic. React Native rejected (no experience). The web PWA stays alive untouched as the web fallback; it stops being the mobile strategy.

### 6.2 Architecture

- One codebase, iOS + Android. Material 3 base with Flutter's platform-adaptive behaviors (`.adaptive` constructors, navigation transitions, back gesture) — not two hand-built UI trees.
- Tab scaffold: **Home · Report · My issues · Ledger · Account**.
- **Dart API client generated from the committed OpenAPI schema** (regenerated + diffed in app CI). Thin repository layer; **Riverpod** for state.
- **Vietnamese-first l10n** via ARB files. All user-facing copy lives in the app, keyed off API `code` fields; the server never sends display strings.
- **Accessibility:** system font scaling end-to-end, screen-reader semantics, ≥44pt touch targets, AA contrast with `DESIGN.md` tokens. Older-adult defaults: generous type, one primary action per screen, no gesture-only affordances.

### 6.3 Screens (complete v1 surface)

1. **Login** — phone/email + password; token to secure storage; throttle-aware error copy.
2. **Occupancy picker** — only when `/me` returns >1 active occupancy; changeable from Account.
3. **Home** — fund balance block (tabular numerals, integer VND), period inflows/outflows, my active reports, recent published spending, notification bell.
4. **Report issue** — required text; location picker from `GET /locations` (tree, large rows); up to 5 photos (camera/gallery) with client-side compression (max edge 2048px, JPEG) before multipart upload. Text submits first with `client_ref`; photos upload individually with per-photo retry. Local draft persists across app kill. No other offline behavior (P1: no offline sync).
5. **My issues** — list + detail timeline: submitted → triage → grouped-into-case notice → work status/deadline → completion evidence → rate work (1–5).
6. **Ledger** — list with period filters; detail leads with plain language (what was fixed, why, how much, who approved, payment verified) and an expandable proof section rendering the evidence-level enum: distinct labels/badges for `LOCAL_SIGNED` vs `CHAIN_CONFIRMED` vs `MISMATCH` (mismatch rendered prominently), hashes/event IDs in mono type only inside the expansion.
7. **Account** — profile, occupancy switcher, notification preferences, logout, logout-all.
8. **Notifications feed** — in-app list, mark-read, deep-links into report/ledger details.

### 6.4 Session and failure behavior

One HTTP interceptor owns auth: attach token; any 401 → clear secure storage → login. App start: `GET /me` decides route. Every error path follows the product failure doctrine — what happened, whether data was saved, next safe action — mapped from problem-json codes; no raw HTTP jargon shown to residents.

### 6.5 Testing and distribution

Widget tests: login, report submission (including `client_ref` retry → 200 and conflict → 409), ledger evidence-label rendering. One end-to-end happy path (`integration_test`) against a compose-seeded backend, nightly. Store-standard distribution; no OTA code push in v1.

## 7. Push notifications

### 7.1 Provider

**FCM only** (delivers to APNs on iOS). Server: `firebase-admin` with a service-account credential from environment/secret (never in git). No second provider, no push abstraction layer. Zalo ZNS is a noted later option, not built.

### 7.2 Device registry and token hygiene

New `Device` model (notifications app): `user`, `install_id` (client UUID, upsert key), `fcm_token` (globally unique), `platform`, `app_version`, `active`, `last_seen_at`.

- **Registration:** `POST /devices` after login + OS permission; upsert by `(user, install_id)`.
- **Rotation/reassignment rules (explicit):** possession of a current FCM token proves control of the device, so if an incoming registration carries an `fcm_token` already attached to a different user or install, the old binding is deactivated and the token reattaches to the registering `(user, install_id)`. Logout deactivates that install's Device row. Account switching on one device = logout (deactivate) + login + re-register, so a token can never remain attached to the previous user. The app re-registers on FCM's token-refresh callback. Reinstalls get a new `install_id` and token; stale rows die on first `UNREGISTERED` response or via inactivity cleanup (devices unseen for 180 days are deactivated).
- Auth tokens and FCM tokens are separate records; an FCM token is never an auth credential.

### 7.3 Delivery pipeline

- **`PUSH` becomes a third `NotificationDelivery.Channel`** beside `IN_APP` and `EMAIL`, inheriting the existing queue, claim, retry, and preference machinery. The worker fans a `PUSH` delivery out to the user's active devices.
- **Send-time revalidation:** immediately before sending, the worker re-checks that the user is active and still holds an active occupancy in the delivery's `building`. Inactive users, or users with no active occupancy in that building, receive no tenant-specific push — regardless of what was true at creation time.
- **Provider error classification:** terminal errors (`UNREGISTERED`, invalid/mismatched token) → immediately deactivate the Device row, no retry. Transient errors (unavailable/internal/quota) → capped exponential backoff, `MAX_*_ATTEMPTS` pattern; then the delivery is marked failed and the authoritative in-app feed still holds the item.
- **Idempotency and duplicates:** each push payload carries the delivery ID as a dedupe key; the app tolerates duplicate provider delivery safely (re-navigation and re-fetch are harmless; no action executes from a push alone).
- **Aggregation/rate limits:** ledger-publication pushes within a short window collapse into one summary notification per user (FCM `collapse_key`; e.g. "3 khoản chi mới được công bố"), with a per-user daily cap per category so bulk publication days don't spam residents. Report-status events are naturally low-volume and send individually.

### 7.4 Events and payload minimization

Resident-relevant events only: report received/triaged, report grouped into a case, work completed (rate prompt), published ledger entry for the resident's building, published correction. No staff push in Phase 1.

Push payloads carry **no sensitive content** — no amounts, no names, no report text — because they transit Google/Apple infrastructure. Payload = generic Vietnamese title/body + deep-link reference (`type` + `id`) + delivery ID. **Deep links resolve through an allowlisted type→route map** (report, case, ledger entry, notifications feed); anything else is ignored. The app always re-fetches content through the authenticated API, which re-authorizes on every request — a push can never grant access; 404/403 on follow-up lands on a safe fallback screen. The in-app feed and inbox remain authoritative; push is best-effort and its failure never blocks any workflow.

### 7.5 Consent

Two independent layers, both required:

1. **OS permission**, requested in context at the first moment push has obvious value (right after first report submission), never as an app-launch ambush. iOS prompt and Android 13+ runtime permission handled identically.
2. **In-app preferences** per event category, extending `NotificationPreference` with the push channel, managed from Account. Defaults once OS permission exists: report updates on, ledger publications on.

### 7.6 Ops

Push failure counts and dead-token cleanup age join `/s/ops/health/`.

---

## 8. Out of scope (unchanged non-goals)

Fee payment and "I transferred" confirmations (Phase 4), multi-type helpdesk/SLA/AI routing (Phase 2), fee transparency catalog (Phase 3), native staff app, consolidated cross-building staff views, resident self-signup, SMS OTP login, Zalo ZNS, per-building anchoring toggle, offline sync, OTA code push, microservices/brokers/event sourcing, resident crypto wallets.

## 9. Documented upgrade paths (deliberately deferred)

| Future need | Prepared seam |
|---|---|
| PM-company consolidated views | Nullable `Organization.company` FK + backfill |
| Per-building anchoring choice | Move `EVIDENCE_ANCHORING_BACKEND` to a `Building` column |
| Zalo/other notification channels | Additional `NotificationDelivery.Channel` value |
| Staff API / staff mobile | Same selectors already serve DRF; add staff auth model then |
| Phone OTP login | Auth backend already keyed on phone; add OTP flow + SMS provider |
