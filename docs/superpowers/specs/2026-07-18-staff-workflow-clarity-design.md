# Staff Workflow Clarity Design

## Goal

Make LamTo's staff workflows safer and easier to understand by replacing manual evidence identifiers with scoped selections, showing the accountability chain, summarizing signed consequences, improving navigation and hierarchy, and removing navigation that does not belong in the shown contexts.

## Product Context

LamTo is an accountability layer for apartment maintenance. Staff must be able to tell what happened, why a record is trustworthy, what they must do now, and which role acts next. The interface remains restrained, desktop-first, server-rendered, and WCAG 2.2 AA compliant.

## Scope

This change covers all five priority issues from the staff UI critique:

1. Evidence selection and error prevention.
2. Accountability-chain hierarchy.
3. Rigorous review summaries for signed actions.
4. Deep navigation and Finance discoverability.
5. Operational hierarchy for panels, fund balance, and Ops Health.

It also includes two explicit navigation changes:

- Remove the `Account` link from the staff navigation only.
- Hide resident bottom navigation on the sign-in page and security pages (`mfa_setup` and `reauth`) only.

The resident account page and route remain available. Authenticated resident pages retain their bottom navigation.

## Non-goals

- No new JavaScript framework, component library, dependency, API, or database migration.
- No redesign of the resident application's authenticated navigation.
- No removal of resident profile, notification preferences, occupancy switching, notices, or sign-out.
- No change to capability checks, tenancy boundaries, wallet-signature verification, evidence integrity rules, or append-only records.
- No bulk workflow, saved-filter, or keyboard-shortcut system in this pass.

## Chosen Approach

Extend the existing Django forms, views, templates, wallet-signing script, and CSS tokens. Server-rendered state remains authoritative. Native HTML controls provide evidence selection; the existing wallet script may mirror current form values into review text, but it does not become a second source of truth.

This is preferred over a navigation-only patch because it resolves the highest-risk evidence-entry problem. It is preferred over a client-side workflow system because the current server-rendered architecture already owns validation, access control, and signed payload construction.

## Evidence Selection and Error Prevention

### Completion evidence

The work-completion form will replace free-text `before_version_ids` and `after_version_ids` inputs with native multi-select controls populated by the view. Choices are limited to clean document versions in the active building that the existing completion service accepts. Labels show the document filename, variant, and version identifier so staff can recognize the evidence without memorizing a primary key.

The server will continue resolving submitted identifiers and passing `DocumentVersion` objects to `complete_work_order`. It will reject missing, cross-building, quarantined, or otherwise ineligible selections. Invalid submissions retain all form values and show field-level guidance.

### Acceptance and payment evidence

Acceptance and payment forms will replace editable numeric evidence fields with server-scoped choices. The available invoice, acceptance-report, and payment-proof choices are limited to clean versions in the active building and correct document kind.

Original and redacted versions are selected as a valid document pair. The UI presents one recognizable pair label rather than asking staff to coordinate two unrelated numeric fields. The server expands the chosen pair into the existing original/redacted `DocumentVersion` objects before calling the domain service. Existing domain validation remains the final guardrail and does not broaden eligibility.

When no eligible pair exists, the form explains which evidence must be uploaded and disables the signed action. It never silently substitutes evidence from another building or document.

## Accountability Chain

Work-order, proposal, payment, and audit detail pages will include one compact ordered list:

`Report → Triage → Work → Proposal/Approval → Acceptance → Payment → Publication`

Each stage has one of four states:

- `complete`: the required record exists and passed its applicable check.
- `current`: this is the stage the current page or action represents.
- `blocked`: an unmet prerequisite prevents progress.
- `upcoming`: the stage is not yet reachable.

Each page receives a small list of stage dictionaries from its existing view context. One shared `_accountability_chain.html` partial renders the list consistently. Text and current-step semantics carry meaning; color is supplemental. Technical hashes and event identifiers remain under the existing Technical proof disclosure.

The chain is explanatory, not interactive navigation in this pass. Existing safe record links remain available in surrounding details.

## Rigorous Signed Review Summary

Every signed financial or evidentiary action will place a review summary immediately before its submit control. The summary states:

- the exact action being signed;
- the acting building and role;
- the relevant amount or outcome;
- the selected evidence filenames and variants;
- the immutable or append-only consequence;
- the role or stage that acts next.

Decision buttons use consequence-specific copy, including `Sign and approve proposal`, `Sign and reject for correction`, `Sign and accept work`, `Sign and record payment`, `Sign and verify payment`, and `Sign and publish to resident ledger`.

For values the user can change before submission, the existing wallet-signing script updates only the visible review text and CTA wording. The signed payload continues to come from the existing typed-data generation and form submission. Server-rendered defaults ensure the summary is understandable without JavaScript.

Signing failures preserve entries, restore controls, announce the error through the existing live region, and keep the review summary visible.

## Navigation

### Staff Account link

Remove the hard-coded Account anchor from `web/staff/shell.html`. Do not delete or restrict the resident account route. Staff users who also have a resident occupancy still reach resident account functionality through the resident surface.

### Resident bottom navigation on authentication and security pages

Wrap the resident bottom navigation in a named `bottom_nav` block in `web/base.html`. The following templates override that block with no content:

- `web/resident/login.html`
- `web/security/mfa_setup.html`
- `web/security/reauth.html`

Authenticated resident home, report, issue, ledger, account, rating, and offline pages retain the current bottom navigation. Pages without bottom navigation must not retain the body's navigation-sized bottom padding.

### Staff orientation and Finance discovery

Detail pages receive a compact back/breadcrumb link to their owning list or Action Inbox. The implementation uses stable list URLs; preserving arbitrary browser history or every prior filter combination is outside this pass.

When a membership has Finance capabilities, the staff shell shows a secondary Finance navigation containing only accessible destinations among Proposals, Payments, and Fund. Existing capability checks determine visibility. The top-level Finance state remains active on all three destinations.

Mutation forms receive an explicit Cancel or Back link to the owning record/list. Signed domain actions remain append-only; this control exits before submission and is not an undo mechanism.

## Operational Hierarchy

Existing panels remain where they represent a real grouped task. Record metadata and sequential evidence use flat sections and dividers rather than additional nested containers.

The current action region receives the strongest local hierarchy. Status and next responsibility appear before secondary metadata. The fund overview uses the existing prominent tabular amount treatment for verified balance, followed by inflow and outflow context.

Ops Health is grouped into Queue, Evidence integrity, Notifications, Devices, and Anchoring. Non-zero failures, quarantined files, integrity mismatches, and stale conditions appear before healthy supporting metrics. Semantic text labels accompany state color.

## Data Flow and Security

1. The view builds eligible evidence choices using the active membership's building and the required document kind/status.
2. Django renders native controls and a server-authored review summary.
3. The submitted form validates that selected choices still belong to the eligible queryset.
4. The view expands an evidence-pair choice into the existing original/redacted versions.
5. Existing domain services and wallet-signature checks perform final authorization and integrity validation.
6. Success redirects to the owning detail page with the existing message framework; failure preserves form state and explains recovery.

Eligibility is always rechecked on POST. Hidden inputs and client-side review text are never trusted for authorization, tenancy, evidence pairing, amounts, or signature verification.

## Accessibility and Responsive Behavior

- Native labels, selects, links, buttons, details, lists, and live regions remain the default.
- Accountability stages use ordered-list semantics and expose the current stage in text.
- Evidence option labels remain meaningful when read without surrounding layout.
- Focus-visible treatment and 44px minimum targets remain unchanged.
- Review summaries are visible in the normal reading order before signed controls.
- Finance sub-navigation wraps without clipping at narrow widths.
- Removing bottom navigation from security pages also removes the reserved bottom space.
- Reduced-motion behavior remains unchanged; no decorative animation is added.

## Error Handling

- No eligible evidence: explain the required upload and disable the signed action.
- Evidence becomes ineligible between GET and POST: reject at the field, preserve other entries, and ask the user to select again.
- Pair is incomplete or mismatched: reject before typed-data submission.
- Wallet unavailable, wrong account, rejected signature, or network failure: preserve the form and reuse the existing inline recovery flow.
- Unauthorized Finance destination: retain existing capability denial; navigation never implies access the server does not grant.

## Testing

Tests are written before production changes and must prove:

- completion, acceptance, and payment evidence choices exclude cross-building, quarantined, wrong-kind, and mismatched records;
- a valid pair expands to the same original/redacted objects expected by existing domain services;
- invalid POST choices preserve user-entered fields and display actionable errors;
- accountability chains render ordered stages and one current state on representative work, proposal, payment, and audit pages;
- signed actions render the selected amount/outcome, evidence labels, consequence, next role, and decision-specific CTA;
- staff navigation no longer contains Account;
- Finance sub-navigation contains only capability-accessible destinations;
- login, MFA setup, and re-auth pages do not render resident bottom navigation or reserved bottom spacing;
- authenticated resident pages still render resident bottom navigation;
- fund balance and grouped Ops Health hierarchy render their expected semantic structure;
- existing staff UI, role workspace, signing, resident view, security, and accessibility tests remain green.

## Success Criteria

- Staff never type a document-version primary key for completion, acceptance, or payment workflows.
- Every high-stakes detail page explains its place in the accountability chain.
- Every signed action states what will happen and who acts next before signature.
- Staff can discover every Finance area their active membership may access.
- Deep staff pages provide a stable exit before mutation.
- The staff Account tab is absent.
- Resident bottom navigation is absent only on sign-in and security pages.
- No new dependency, migration, client-side state store, or parallel navigation system is introduced.
