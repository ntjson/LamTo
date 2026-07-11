# Product

## Register

product

## Platform

web

## Users

LamTo serves two equally primary groups in one apartment building:

- Residents use a mobile-first experience to report maintenance issues, follow cases and work, and understand how published Maintenance Fund spending connects to the original reports and evidence.
- Operational and governance roles—including the property-management operator, maintenance staff, Management Board, resident representative, and auditor—coordinate work, review evidence, authorize distinct steps, publish verified outcomes, and audit the accountability chain.

The experience must remain approachable for older adults and people with limited digital confidence while supporting precise, role-specific work for operational users.

## Product Purpose

LamTo coordinates resident-reported maintenance cases and makes every published Maintenance Fund expenditure traceable from the original reports through work, approvals, acceptance, payment evidence, and an independently verifiable resident-facing outcome.

The MVP focuses specifically on maintenance accountability and financial transparency. It does not replace the building's full maintenance, accounting, or property-management systems. It is a responsive web product, including mobile web; its boundaries may allow native clients later, but native applications are outside the current scope.

The MVP succeeds when participants complete one real normal maintenance case end to end and one controlled emergency drill, residents and auditors can independently verify the resulting evidence, tampering is detected, corrections remain append-only, and recovery creates neither lost nor duplicate records.

## Positioning

LamTo is the accountability layer for apartment maintenance, linking resident reports to traceable and independently verifiable Maintenance Fund spending—without replacing the building's existing property-management or accounting systems.

## Brand Personality

Trustworthy, clear, and rigorous. The product should feel neutral, evidence-led, restrained, and purpose-built for accountability. Its voice explains status and evidence in plain language before exposing technical detail.

## Anti-references

LamTo must not resemble:

- A crypto-trading or Web3 dashboard with neon visuals, token language, or hashes and transaction IDs dominating the interface.
- A generic admin template composed of interchangeable cards, charts, and tables without an accountability narrative.
- A glossy property-management sales app built around luxury imagery, promotional gradients, or marketing-first interactions.
- A surveillance or command-center interface that makes residents feel monitored or controlled.
- An overly legalistic, accounting-heavy, or technically dense system that exposes internal terminology instead of explaining evidence and status plainly.
- A playful hackathon prototype that weakens the seriousness of financial records.

Blockchain and AI should be visible only where they help people understand verification or automation.

## Design Principles

1. **Make accountability continuous.** Connect each published expenditure to the resident reports, work, decisions, documents, and verification that justify it.
2. **Explain before proving.** Lead with plain-language status and outcomes; reveal hashes, event IDs, signatures, and other technical proof only as supporting detail.
3. **Support the building's systems.** Own the maintenance-accountability workflow without expanding into general property management, accounting, payment initiation, or building operations.
4. **Make responsibility legible.** Show who must act, what evidence they are reviewing, and what happens next without creating a surveillance atmosphere.
5. **Preserve trust under failure.** State whether data was saved, retain drafts where possible, expose pending or failed verification honestly, and give the next safe action.

## Accessibility & Inclusion

WCAG 2.2 AA is the baseline. The resident experience is mobile-first and must remain usable for older adults and people with limited digital confidence.

- Primary actions use touch targets of at least 44px, clear labels, visible focus states, and never rely on color alone.
- Keyboard and screen-reader support, reduced-motion behavior, readable contrast, and small-screen operation are required.
- Every status, approval, document check, and verification result is explained in plain language before technical details appear.
- Blockchain hashes, event IDs, and signatures appear only in expandable verification details, not as the primary resident-facing explanation.
- Vietnamese is the default MVP language. Product copy and component structure remain localization-ready for English, but multilingual administration is outside this phase.
- Currency is displayed in Vietnamese đồng. Dates and deadlines use the building's configured Vietnam time zone.
- Error messages explain what happened, whether data was saved, and the next safe action.
- Unreliable connections must not silently lose work; failed submissions preserve drafts where possible.
