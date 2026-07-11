# Accountability MVP Design

**Status:** Approved design, pending written-spec review

**Date:** 2026-07-11

**Target:** Single-building operational pilot

**Primary priority:** Maintenance and financial accountability

## 1. Product outcome

The Accountability MVP proves one complete claim:

> Every published maintenance-fund expenditure can be traced to one or more resident reports, a confirmed maintenance case, a work order, an immutable proposal version, separately authorized approvals, completion and acceptance evidence, independently verified external-payment evidence, and blockchain-confirmed hashes.

The pilot is a real operational system for one apartment building, not a scripted demo. It uses one responsive, installable PWA for all roles. Vehicle access, personal billing, fee collection, and payment initiation are separate products and are not part of this design.

## 2. Approved scope

### Included

- Resident issue submission using text, selected location, and photos.
- Live AI suggestions for category, location interpretation, urgency, duplicate detection, responsible department, and deadline.
- Mandatory human review of every AI suggestion.
- Duplicate reports grouped into one maintenance case while preserving every original report and reporter's tracking access.
- Work-order assignment, deadlines, progress, cause, result, and before/after evidence.
- Maintenance-only expenditure proposals linked to a work order and at least one confirmed resident report.
- Fixed proposal approval and publication separation.
- Emergency authorization followed by resident-representative ratification or rejection within 24 hours.
- Quotations, invoices, acceptance reports, payment evidence, original documents, and resident-visible redacted copies.
- Manual reconciliation of external bank payments; the platform never initiates or holds funds.
- One Maintenance Fund with an append-only balance ledger.
- Resident Transparency Ledger with verified evidence status and corrections.
- Permissioned-blockchain evidence with independently controlled stakeholder signing keys and centrally managed node hosting.
- Auditing, exports, notifications, backups, recovery, and pilot health monitoring.

### Excluded

- Personal invoices, apartment charges, fee collection, receipts, or resident payment flows.
- Any payment initiation, money custody, cryptocurrency, tokens, or resident blockchain wallets.
- Vehicle registration, license-plate recognition, facial recognition, visitor passes, or gate control.
- Voice reports, video uploads, or AI image interpretation.
- Invoice OCR, maintenance-cost estimation, or contractor scoring.
- Native mobile applications or offline synchronization.
- Multi-building tenancy.
- Microservices, message brokers, workflow engines, and event sourcing.
- Production-scale high availability or a claim of completed statutory/compliance certification.

## 3. Success definition

The pilot succeeds when:

1. Real participants complete one real normal maintenance case end to end.
2. Real role-holders complete one controlled emergency workflow drill using realistic test data, unless a genuine emergency naturally occurs and supplies the same evidence.
3. A controlled document modification is detected as a hash mismatch.
4. A correction is appended and published without removing or changing the original.
5. A resident can trace the real expenditure from report to result, and an auditor can independently verify originals, signatures, chain transactions, and the Maintenance Fund balance.
6. All automated integrity, authorization, failure, and recovery gates in Section 16 pass.

No emergency may be manufactured, encouraged, or awaited for pilot acceptance.

## 4. Architecture decision

### Chosen approach

Use a **database-first modular monolith with blockchain evidence**.

- PostgreSQL is the operational source of truth.
- Private object storage holds complete documents and photos.
- The permissioned blockchain holds verification evidence only.
- One repository contains the PWA, API, domain modules, and background worker.
- The API and worker may run as separate processes, but they share one domain model and database.
- A transactional database outbox connects business actions to blockchain submission without a message broker.

This is preferred over a blockchain-led workflow because daily operations, recovery, querying, and corrections remain straightforward. It is preferred over event sourcing because PostgreSQL rows plus an append-only audit log and blockchain evidence already satisfy the pilot's trust requirement.

### Component boundaries

| Component | Responsibility | Depends on |
|---|---|---|
| Responsive PWA | Role-specific resident and staff experiences | API |
| Identity, RBAC, and audit | Authentication, MFA, organization membership, capabilities, separation rules, privileged audit | PostgreSQL |
| Reports and AI triage | Report intake, AI requests, suggestion review, duplicate grouping | PostgreSQL, object storage, AI provider |
| Work orders | Assignment, deadlines, progress, completion, acceptance handoff | PostgreSQL, object storage |
| Expenditures | Proposal versions, approval decisions, emergency path, actual cost, payment maker-checker | PostgreSQL, document module |
| Documents | Immutable versions, malware quarantine, originals, redacted copies, hashes, access control | Object storage, PostgreSQL |
| Fund and Transparency Ledger | Append-only fund entries, publication gates, resident views, corrections | PostgreSQL, blockchain evidence |
| Background worker | AI retries, notifications, blockchain outbox submission, integrity checks | PostgreSQL, external services |
| Permissioned blockchain | Signed hashes, decisions, milestones, transaction IDs, prior-record links | Managed nodes, stakeholder wallets |

No module may bypass another module's public domain operations by directly mutating its protected records.

## 5. Roles and capability boundaries

| Role | Allowed | Prohibited |
|---|---|---|
| Resident | Submit and follow own reports; view all published ledger entries and redacted documents; rate completed work | Staff workflows, originals, unpublished finance data |
| Property-management operator | Review AI suggestions; group reports; create cases, work orders, proposals, document versions, and corrections | Proposal approval, payment recording or verification, publication |
| Maintenance staff | View and update assigned work; add progress and completion evidence | Fund data, proposals, personal data unrelated to the assignment, originals unrelated to work |
| Management Board | Capability-specific proposal approval, emergency authorization, work acceptance, payment recording, payment verification, fund-entry verification, and publication | Any forbidden actor combination in Section 10 |
| Resident representative | Review exact proposal versions and required originals; co-approve normal spending; ratify or reject emergency spending | Operational edits, payment actions, publication |
| Auditor | Read and export originals, redacted copies, audit events, fund entries, signatures, and blockchain evidence | Business-state mutation, approval, payment, publication |
| Technical administrator | Infrastructure and organization-account administration; audited, time-limited break-glass support | Business approvals, payment actions, publication, stakeholder-key access |
| AI provider | Return suggestions from the minimum required report text and selected location | Any workflow authority or direct access to financial records |

Board capabilities are assigned explicitly to users. A broad `BOARD` label alone never authorizes every Board action.

Users with more than one role use an explicit workspace/capability switcher. Each action records the active role, organization, and user; roles are never silently blended.

## 6. Core records and relationships

The accountability chain is:

```text
IssueReport (one or many)
→ MaintenanceCase
→ WorkOrder
→ ProposalVersion
→ ApprovalDecision (Board + resident representative)
→ AcceptanceRecord
→ PaymentEvidence
→ PaymentVerification
→ FundEntry
→ PublishedLedgerEntry
→ Correction (zero or many, append-only)
```

### Principal records

| Record | Purpose and important properties |
|---|---|
| User / OrganizationMembership / Capability | Authenticated identity, organization, role, fine-grained permissions, active/revoked state |
| BuildingLocation | Pilot building hierarchy used by reports and work orders |
| IssueReport | Reporter, text, selected location, photo references, submission state, resident-visible timeline |
| TriageSuggestion | AI output, confidence/validation metadata, provider request ID, timing, failure reason |
| TriageDecision | Operator-confirmed category, urgency, location, department, deadline, and differences from AI output |
| MaintenanceCase | Confirmed incident that groups one or more reports without deleting originals |
| WorkOrder | Case link, assignee, priority, deadline, status, cause, progress, result, timestamps, completion evidence |
| Proposal / ProposalVersion | Work-order link, immutable version number, proposed amount, contractor, fund source, quotation versions, canonical hash |
| ApprovalDecision | Exact proposal-version hash, actor, organization, decision, timestamp, signature, chain status |
| EmergencyAuthorization | Work order, safety reason, available estimate/evidence, Board signer, timestamp, signature, persistent emergency label |
| EmergencyRatification | Resident-representative approval/rejection, reason, timestamp, deadline result, signature |
| Document / DocumentVersion | Type, immutable object reference, original/redacted variant, byte hash, scan status, uploader, access class |
| AcceptanceRecord | Completion result, accepted actual cost, confirmer, invoice and acceptance-report versions |
| PaymentEvidence | External bank reference, amount, status, completion time, proof document, recorder |
| PaymentVerification | Verified evidence hash, verifier, decision, timestamp |
| MaintenanceFundEntry | Opening balance, inflow, outflow, reversal, or replacement; integer đồng; evidence and verification state |
| PublicationSnapshot | Immutable resident-facing payload signed by the eligible publisher before blockchain anchoring |
| PublishedLedgerEntry | Immutable resident-facing snapshot and related record IDs; effective integrity status is derived from chain checks and appended observations |
| Correction | Original-entry link, reason, replacement values/documents, approvals, publication, reversal/replacement fund entries |
| VerificationObservation | Append-only integrity check result that can expose a later mismatch without mutating the published entry |
| AuditEvent | Actor, active role, action, target, before/after version identifiers, timestamp, request/result metadata |
| BlockchainOutboxEvent | Stable event ID, canonical payload and hash, signer, retry state, transaction ID, confirmation or mismatch state |

Amounts are stored as integer đồng. Floating-point money is prohibited.

## 7. Report, triage, and work-order flow

1. A resident submits text, selected location, and photos.
2. The report is committed before any AI call.
3. A background job requests text/location triage. Photos remain operational evidence and are not sent for AI image interpretation in this MVP.
4. AI returns structured suggestions: category, interpreted location, urgency, potential duplicates, department, and deadline.
5. Missing, invalid, low-confidence, or timed-out output routes the report to manual triage without losing or blocking it.
6. The operator accepts or edits suggestions and may group the report with similar reports into a single maintenance case.
7. Every original report remains immutable and linked; every reporter can track the grouped case.
8. The operator creates and assigns a work order.
9. Unpaid diagnostic inspection may occur before expenditure authorization. Paid repair work follows Section 8.
10. Maintenance records acceptance, progress, cause, timestamps, result, and before/after photos.
11. Residents receive in-app and email notifications for material status changes and may rate accepted work.

Work that requires no spending may complete without creating an expenditure or Transparency Ledger entry.

## 8. Normal expenditure workflow

1. The operator creates a proposal linked to exactly one work order and its maintenance case.
2. The proposal includes the Maintenance Fund source, proposed integer-VND amount, contractor, quotation, and purpose.
3. Submission freezes an immutable proposal version. Its canonical snapshot includes all referenced work-order and document-version hashes, and the operator signs it as the proposal creator.
4. An authorized Board approver reviews and signs that exact version.
5. If approved, the resident representative reviews and signs the same version. A rejection ends that version; revision creates a new version and never alters or reuses approvals from the old version.
6. The database atomically commits each approval and its blockchain outbox event. Work authorization requires both locally verified signatures against the exact version, not immediate blockchain availability.
7. When anchoring is temporarily unavailable, paid work may proceed with `Pending blockchain anchoring` shown on the case, work order, approval detail, and operational inbox.
8. The worker retries the original event IDs idempotently until confirmed. Any proposal edit invalidates the signatures and authorization.
9. After completion, the operator uploads the invoice, acceptance report, and required original/redacted variants.
10. An authorized Board user confirms the work result, actual cost, and acceptance.
11. An authorized Board payment recorder records the external bank reference, amount, status, completion time, and payment proof.
12. A different authorized Board user verifies that payment evidence against the accepted actual cost.
13. After all prerequisite evidence is confirmed, an eligible Board publisher reviews and signs an immutable publication snapshot. The database commits that publication intent and its outbox event atomically.
14. The worker anchors the publication snapshot. While that event is pending, the expenditure remains unpublished and creates no resident-visible fund posting.
15. Confirmation of the publication-snapshot event allows one idempotent database transaction to create the outflow fund entry and expose the resident-facing ledger snapshot. Repeated requests cannot create duplicate entries.

The platform records external payment evidence only. It never initiates payment, redirects funds, holds funds, or treats a blockchain transaction as payment.

## 9. Emergency expenditure workflow

1. The operator marks the confirmed work order as emergency and supplies a mandatory safety reason.
2. A designated Board emergency approver reviews the available facts and signs an emergency authorization.
3. Work may begin immediately after local signature verification, including while blockchain anchoring is unavailable. The record remains visibly labeled `Emergency` and, where applicable, `Pending blockchain anchoring`.
4. The operator completes the proposal and available cost/document evidence without delaying safety work.
5. The resident representative must ratify or reject the emergency within 24 hours of authorization. A missed deadline becomes `Ratification overdue`.
6. Authorization, work start, anchoring delay, ratification, rejection, or overdue status is never deleted or hidden.
7. Completion, acceptance, payment recording, independent payment verification, document hashing, and blockchain confirmation still apply.
8. After the 24-hour decision window and all evidence gates, the ledger may publish the emergency result as `Ratified`, `Ratification rejected`, or `Ratification overdue`. Rejected or overdue records must not be presented as approved.

## 10. Separation-of-duties invariants

These are server-side domain rules and database constraints where the database can express them. Hiding a button is not enforcement.

### Fixed normal proposal chain

- Operator creates the proposal.
- Authorized Board user approves it.
- Resident representative co-approves it.
- An eligible Board user publishes it.

### Payment maker-checker and publication

- `payment_verifier_id != payment_recorder_id`
- `publisher_id != proposal_creator_id`
- `publisher_id != proposal_approver_id`
- `publisher_id != payment_recorder_id`
- The publisher **may** also be the payment verifier when every rule above passes.
- Proposal creation, proposal approval, payment recording, payment verification, and publication remain separate audited actions even when verification and publication share one eligible user.

The actual-cost/acceptance confirmer and payment recorder may be the same authorized Board user; the required independent check is between payment recording and payment verification.

### Version and publication gates

- Approvals reference one immutable proposal-version hash.
- Changing an approved field or referenced document creates a new version and requires fresh approvals.
- Verified or published financial records cannot be updated or deleted.
- The publisher may sign a publication snapshot only after every prerequisite event and original/redacted document hash is confirmed.
- The ledger entry becomes resident-visible only after the publication-snapshot event itself is confirmed.
- Publication and its Maintenance Fund posting are idempotent and unique per expenditure/correction.

## 11. Documents, redaction, and corrections

### Document handling

- Every upload creates an immutable document version.
- Required document types are quotation, invoice, acceptance report, and payment proof. Contracts may be attached when applicable but are not mandatory for every pilot expenditure.
- Uploads are size/type checked, malware scanned, and quarantined until safe.
- Hashes are calculated from the immutable stored bytes after scanning.
- Restricted originals and resident-visible redacted copies are separate document versions with separate hashes.
- Residents receive meaningful redacted documents; bank details, identity numbers, private signatures, and unrelated personal data are removed.
- Resident representatives and auditors may access originals required for their approved duties. Access is logged.
- No complete document, image, or personal information is stored on-chain.

### Corrections

1. A published record remains unchanged.
2. The operator creates a correction linked to the original, with a mandatory reason and replacement evidence.
3. The Board approves the correction; the resident representative co-approves it; an eligible different Board user signs its publication snapshot.
4. The chain confirms the correction, prior-record, and publication-snapshot hashes before resident exposure.
5. The resident ledger displays original and correction together.
6. Financial corrections use reversing and replacement fund entries; they never edit an earlier fund entry.

## 12. Maintenance Fund model

- The pilot has one Maintenance Fund.
- Its balance is derived from append-only entries; no field stores an independently editable current balance.
- Entry types are verified opening balance, verified inflow, published maintenance outflow, reversal, and replacement.
- An authorized Board fund recorder enters opening-balance or inflow evidence; a different authorized Board fund verifier confirms it before resident display.
- Opening-balance and inflow evidence is hashed and anchored as financial evidence, but it does not require a work order because it is not expenditure.
- An expenditure outflow posts only after payment verification and publication. Staff views may show paid-but-unpublished amounts separately as pending reconciliation; those amounts do not appear in the resident verified balance.
- Residents see opening/current balance, period inflows, period outflows, and published maintenance entries.
- Personal fee-assessment and collection workflows are not part of this fund model.

## 13. Blockchain evidence and key custody

### Evidence contents

Blockchain transactions contain only:

- Stable event ID and event type.
- Canonical record hash and relevant document-version hashes.
- Previous evidence-record hash.
- Timestamp and process status.
- Signing user and organization identifiers that do not expose personal profile data.
- Approval, rejection, ratification, verification, or publication result.
- Transaction ID and confirmation metadata.

They do not contain documents, photos, report text, bank account details, complete personal data, vehicle data, or money/digital assets.

### Key custody and managed hosting

- The pilot network models four organizations: Management Board, property-management operator, resident representative, and auditor. Their nodes are centrally hosted for the pilot, while authorization keys remain outside platform custody.
- Each authorized stakeholder signer registers an individual, stakeholder-controlled signing wallet.
- Before signature, the PWA shows the canonical snapshot and hash.
- The backend verifies the authenticated user's current capability, organization membership, and signature, then relays the evidence transaction.
- The platform hosts the pilot's permissioned nodes but never receives stakeholder private keys.
- Key revocation/replacement requires organization-authorized registration. Old signatures and key history remain verifiable.
- The auditor has read/verify access and may export evidence but does not mutate pilot business state.

This pilot validates independent authorization keys, not full infrastructure independence. A later production phase must distribute node operation if the product is to claim that the provider is not the sole infrastructure operator.

### Required financial evidence events

The resident-facing verified chain requires confirmed events for every applicable milestone:

- Operator-signed proposal-version creation.
- Board proposal approval and resident-representative co-approval.
- Emergency authorization and the eventual ratified, rejected, or overdue outcome when the emergency path applies.
- Work acceptance and actual-cost confirmation.
- Required original and redacted document-version hashes.
- External-payment evidence recording and independent payment verification.
- Publisher-signed immutable publication snapshot.
- Correction creation, approvals, prior-record link, replacement evidence, and correction-publication snapshot when a correction applies.
- Verified Maintenance Fund opening-balance and inflow entries.

The system may anchor operational milestones such as work start or completion, but they are not a substitute for the required financial events above.

### Anchoring semantics and outage behavior

- Business action and blockchain outbox event commit in the same database transaction.
- Each event has a stable ID and canonical payload hash.
- Retries reuse the same event ID; submissions and confirmations are idempotent.
- Normal work authorization depends on valid local Board and representative signatures, not chain availability.
- Emergency work authorization depends on the valid local emergency Board signature.
- Pending anchoring is visible and auditable.
- Resident-facing verified publication always depends on confirmation of every required financial event, document hash, and the publisher-signed publication snapshot.
- A rejected transaction, hash mismatch, or inconsistent confirmation freezes publication and alerts Board and auditor.

## 14. PWA information architecture

### Resident workspace

- Home: Maintenance Fund snapshot, active reports, recent verified spending, notifications.
- Report issue: text, selected location, photos, submission confirmation.
- My issues: report/case timeline, grouped-report notice, work status, deadline, completion, rating.
- Transparency Ledger: period totals, verified entries, filters, entry details, redacted documents, correction history, plain-language verification evidence.
- Account: profile, session security, notification preferences.

### Operational workspaces

- Operator: AI intake, duplicate clusters, cases, work orders, proposals, corrections, document/redaction tasks.
- Maintenance: assigned work only, deadline, issue evidence, progress, completion form.
- Board: action inbox, proposal approval, emergency authorization, acceptance, payment recording, payment verification, publication, fund entries.
- Resident representative: co-approval inbox, exact-version comparison, emergency ratification, published ledger.
- Auditor: verification search, original/redacted comparison, activity history, fund reconciliation, exports.
- Technical administrator: account and infrastructure administration without business actions.

### Interaction rules

- Resident navigation is mobile-first; operational navigation adapts to tablet/desktop.
- The action inbox is authoritative; notifications may fail without losing tasks.
- In-app and email notifications cover assignments, decisions, deadline risk, completion, and publication.
- Authorization is checked server-side on every record, transition, export, and download.
- Status is never conveyed by color alone; keyboard, screen-reader, focus, and touch-target basics are required.
- Personal bills and vehicle modules do not appear.

## 15. Failure handling, security, and recovery

### Dependency failure behavior

| Failure | Required behavior |
|---|---|
| AI timeout, invalid output, or low confidence | Preserve report; route to manual triage; record reason; retry only when safe |
| Photo/document upload failure | Preserve draft; identify failed file; prohibit advancement when required evidence is absent |
| Malware detection | Quarantine file; prevent hash approval/use; alert authorized operator |
| Blockchain outage | Preserve signed action and atomic outbox event; show pending anchoring; retry same event ID; block verified publication |
| Evidence mismatch | Freeze an unpublished record; for a published record append a mismatch observation that the UI renders prominently; alert; preserve both values; require correction |
| Repeated/concurrent action | Reject stale versions and deduplicate approvals, verification, fund postings, and blockchain events |
| Notification outage | Complete workflow independently; retry delivery; preserve authoritative inbox task |
| Lost PWA connectivity | Preserve a local form draft only; require connectivity for workflow and financial submission; no offline sync |

### Security controls

- MFA is mandatory for privileged roles; sensitive actions require recent re-authentication.
- All object- and action-level authorization is server-side.
- Transport and storage encryption are required.
- Documents use private storage and short-lived authorized download links.
- Sessions can be revoked; suspicious logins and abuse are rate-limited and alerted.
- Every privileged read, mutation, export, failed permission check, and break-glass access is audited.
- Platform administrators cannot access stakeholder private keys or perform business signatures.
- AI receives only the minimum text/location data required for triage; financial records and original documents are excluded.

### Recovery

- PostgreSQL uses encrypted point-in-time recovery and daily backups.
- Object storage uses versioning and encrypted backup.
- Restore procedures are exercised before the pilot begins.
- Restore verification recomputes document hashes and Maintenance Fund balance.
- The blockchain worker can replay unconfirmed outbox events idempotently.
- A health view shows AI queue age, quarantined uploads, notification failures, outbox state, last confirmed block, backup recency, and integrity mismatches without exposing private keys.

## 16. Testing and pilot acceptance

### Automated checks

1. **Domain:** state transitions, proposal versions, emergency outcomes, correction append-only behavior, integer money, and actor-separation rules.
2. **Database integration:** approval/outbox atomicity, stable event IDs, immutable records, stale-write rejection, unique fund postings, and document references.
3. **Adapter contracts:** AI validation/fallback, upload quarantine/hashing, stakeholder signatures, blockchain retries, and notification isolation.
4. **Role-based end to end:** each role completes allowed journeys; prohibited objects, files, actions, and exports remain inaccessible.
5. **Security:** MFA/re-authentication, session revocation, rate limits, malicious uploads, audit completeness, and absence of personal data on-chain.
6. **Recovery:** database/object restore, hash reconciliation, outbox replay, and proof of no duplicate chain or fund entries.

### Required adversarial scenarios

- Blockchain unavailable during normal approval: local signatures authorize work, pending status appears, outbox retries the same IDs, and publication remains blocked until confirmation.
- Payment recorder attempts self-verification: rejected and audited.
- Ineligible publisher attempts publication: rejected and audited.
- Approved proposal or document changes: new version required; old approvals do not carry forward; mismatch is detected.
- AI and notifications unavailable: manual intake and authoritative inbox continue.
- Backup restore and outbox replay: hashes and fund balance match; no duplicates appear.
- Correction: original remains, new approvals bind the correction, and reversing/replacement entries reconcile exactly.

### Operational proof

#### Real normal case

One genuine resident-reported maintenance case completes the entire normal path, including AI review, work, approvals, acceptance, payment maker-checker, blockchain confirmation, publication, resident review, and auditor verification.

#### Controlled emergency drill

Real participating role-holders execute realistic test data in an isolated drill record. The drill:

- Is visibly and permanently labeled `Emergency drill` in every screen, export, audit event, and blockchain payload.
- Uses test contractor/documents/amount and never affects the real Maintenance Fund or resident Transparency Ledger.
- Uses actual pilot identities, capabilities, wallets, signatures, outbox, worker, and blockchain path.
- Demonstrates immediate Board authorization.
- Deliberately pauses anchoring and demonstrates the maintenance participant starting the drill work order with `Pending blockchain anchoring` visible.
- Records resident-representative ratification or rejection within 24 hours without waiting for the deadline.
- Restores anchoring, retries the original event IDs, and preserves the pending interval.
- Preserves authorization, work start, anchoring delay, representative decision, retries, and final status.
- Cannot be converted into a real financial record.

Automated end-to-end scenarios cover ratified, rejected, and overdue emergency outcomes.

If a genuine emergency naturally occurs and supplies all required proof, it may replace the drill. The pilot never manufactures an incident, delays safety action, or remains open waiting for an emergency.

### Exit gates

- No unresolved critical or high-severity security or financial-integrity defect.
- No lost or duplicate approval, evidence event, payment verification, or fund entry.
- Every prohibited role combination and object-access attempt is rejected and audited.
- Every published entry independently recomputes to its stored hashes and the same Maintenance Fund balance.
- Database restore, object recovery, hash verification, and idempotent outbox replay succeed.
- Board, operator, resident representative, auditor, maintenance staff, and participating residents sign off on their actual workflows.

AI suggestion acceptance/edit rates, duplicate quality, triage latency, response time, approval time, and anchoring delay are measured. No AI accuracy threshold is invented before pilot data exists, and no AI score gains workflow authority.

## 17. Implementation boundary

This design intentionally does not mandate a programming language, UI framework, cloud provider, AI vendor, object-store vendor, or permissioned-chain implementation. The implementation plan must choose one supported, boring stack that preserves:

- One PWA and one modular-monolith codebase.
- One relational operational database.
- One private object store.
- One database-backed outbox worker rather than a broker.
- Independently controlled stakeholder signing keys.
- Managed permissioned-chain nodes and evidence-only payloads.
- Every workflow, security, failure, and acceptance invariant in this specification.

Vendor/framework choice may not broaden the product scope or weaken these invariants.
