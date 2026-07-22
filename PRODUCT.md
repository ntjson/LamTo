# Product

## Register

product

## Platform

adaptive

## Users

**Primary:** Vietnamese-speaking residents, on the mobile app only. They report apartment maintenance issues, answer requests for missing information, follow the case and the work, rate a completed job, and open the published Maintenance Fund ledger to see how spending connects back to the original reports and the supporting documents. Design trade-offs favor mobile-native clarity, plain Vietnamese, and low cognitive load. Residents have no web surface; the app is the whole resident product.

**Secondary:** The building's Management user, on the web workspace only. One account carries the entire staff path: reviewing an AI triage suggestion and recording the decision, requesting missing information, declining with a recorded reason, opening a case and running the work with published progress, creating and publishing an immutable spending proposal, recording transfer evidence and the payee acknowledgement, publishing the ledger, and verifying hashes and balances. The application does not enforce separation of duties. Where a building wants more than one person involved, managers meet and sign off offline, and the workspace records the agreed result rather than re-running the review. The workspace is denser and desktop-first because that is where the evidence is inspected.

The resident app and the Management workspace share one accountability model and one evidence chain. Neither replaces the building's full maintenance, accounting, or property-management systems.

## Product Purpose

LamTo coordinates resident-reported maintenance cases and makes every published Maintenance Fund expenditure traceable from the original reports through triage, work, acceptance, payment evidence, and an independently verifiable resident-facing outcome.

Triage is assisted rather than automated. A suggestion proposes a category, urgency, interpreted location, responsible department, deadline, likely duplicates, and any missing information; a manager confirms or overrides it, and the recorded decision keeps both the suggestion and the differences from it. A report can also end without a case: declined with a stated reason, or held while missing information is requested. Those outcomes are part of the accountability record, not exceptions to it.

Published evidence is the real document. Residents download the original supporting files, gated by an explicit allowlist of document kinds. There is no redacted variant, so nothing a resident sees is a scrubbed stand-in for something they cannot see.

The MVP focuses on maintenance accountability and financial transparency. It does not initiate payments, hold funds, introduce resident crypto wallets, or replace the building's existing operational systems.

Success means both happy paths complete end to end: a normal maintenance case and a standalone spending proposal, each with independently verifiable proposal and settlement anchors. Residents can independently verify the evidence, tampering is detected, corrections remain append-only, and recovery creates neither lost nor duplicate records.

## Positioning

LamTo is the accountability layer for apartment maintenance, linking resident reports to traceable and independently verifiable Maintenance Fund spending without replacing existing property-management or accounting systems.

## Brand Personality

**Trustworthy, clear, rigorous.** Neutral, evidence-led, and restrained. The voice explains status and evidence in plain language before exposing technical detail. Blockchain and AI appear only when they clarify verification or automation, never as identity or spectacle. An AI suggestion is always shown as a suggestion a person accepted or changed, never as a verdict the system reached.

## Anti-references

LamTo must not resemble:

- A crypto-trading or Web3 dashboard with neon visuals, token language, or hashes and transaction IDs dominating the interface.
- A generic admin template composed of interchangeable cards, charts, and tables without an accountability narrative.
- A glossy property-management sales app built around luxury imagery, promotional gradients, or marketing-first interactions.
- A surveillance or command-center interface that makes residents feel monitored or controlled.
- An overly legalistic, accounting-heavy, or technically dense system that exposes internal terminology instead of explaining evidence and status plainly.
- A playful hackathon prototype that weakens the seriousness of financial records.
- An AI product that presents a model's output as an authoritative decision instead of a suggestion a named person accepted or overrode.

## Design Principles

1. **Make accountability continuous.** Connect each published expenditure to the resident reports, work, decisions, documents, and verification that justify it. A decline or an unanswered information request is part of that chain, not a dead end.
2. **Explain before proving.** Lead with plain-language status and outcomes; reveal hashes, event IDs, signatures, and other technical proof only as supporting detail.
3. **Attribute every judgement to a person.** Show what was suggested, what was decided, and who decided it. Automation may propose; it never appears to have concluded.
4. **Support the building's systems.** Own the maintenance-accountability workflow without expanding into general property management, accounting, payment initiation, or building operations.
5. **Make responsibility legible.** Show who must act, what evidence they are reviewing, and what happens next without creating a surveillance atmosphere.
6. **Preserve trust under failure.** State whether data was saved, retain drafts where possible, expose pending or failed verification honestly, and give the next safe action.

## Accessibility & Inclusion

WCAG 2.2 AA is the baseline for the resident app and the Management workspace.

- Controls have clear labels, visible focus or platform equivalents, and never rely on color alone.
- Web supports keyboard and screen-reader use; native surfaces use platform accessibility APIs.
- Reduced-motion settings are respected, and essential meaning never depends on animation.
- Resident-facing copy is Vietnamese-first, keyed from machine codes rather than server-supplied display strings.
- Type and layout accommodate Vietnamese diacritics and system text scaling without clipping.
- Resident screens use generous touch targets, one primary action per screen, and no gesture-only affordances.
- Errors explain what happened, whether data was saved, and the next safe action.
