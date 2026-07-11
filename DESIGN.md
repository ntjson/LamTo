---
name: LamTo
description: A clear accountability layer for apartment maintenance and verifiable Maintenance Fund spending.
---

<!-- SEED: re-run $impeccable document once there's code to capture the actual tokens and components. -->

# Design System: LamTo

## 1. Overview

**Creative North Star: "The Open Maintenance Desk"**

LamTo should feel like a well-lit resident service desk where reports, decisions, and proof are arranged in one readable sequence. The interface is trustworthy, clear, and rigorous without becoming bureaucratic: residents first see what happened, what is verified, and what comes next; operational users can then inspect the underlying evidence.

The visual system is restrained and purpose-built. It borrows plain-language hierarchy from GOV.UK services, broad-user accessibility from the NHS App, and precise financial-record structure from the Stripe Dashboard. These are behavioral references, not an invitation to copy their branding or default to generic SaaS patterns.

The primary scene is a resident checking a repair update on a small phone in a bright apartment lobby while an operational user reviews the same evidence on a tablet or desktop. Information must remain calm, legible, and credible in both contexts. Motion supports state changes only and never performs for attention.

**Key Characteristics:**

- Restrained neutral surfaces with a sparse, blue-leaning muted-indigo anchor.
- One legible humanist sans-serif family across resident and operational interfaces.
- Plain-language outcomes before expandable technical proof.
- Flat, ordered information with clear state, responsibility, and next action.
- Accessible mobile-first behavior with denser—but still readable—operational views.

## 2. Colors

The palette is restrained: neutral surfaces carry the interface, while a slightly blue-leaning muted indigo provides institutional emphasis without feeling futuristic, playful, or crypto-like.

### Primary

- **Accountability Indigo** (`[to be resolved during implementation]`): Use sparingly for primary actions, selected navigation, links, and focus states. It must lean blue rather than purple and never become neon.

### Secondary

Omit a decorative secondary brand color. Success, warning, error, information, and pending states will receive separate restrained semantic colors during implementation.

### Neutral

- **Clear Ground** (`[to be resolved during implementation]`): The primary page background; light, untinted, and suitable for long reading sessions.
- **Working Surface** (`[to be resolved during implementation]`): A subtle neutral layer for navigation, grouped evidence, and operational controls.
- **Record Ink** (`[to be resolved during implementation]`): High-contrast body text and financial data.
- **Quiet Ink** (`[to be resolved during implementation]`): Secondary text that remains readable and never substitutes low contrast for refinement.

### Named Rules

**The Ten-Percent Rule.** Accountability Indigo occupies no more than 10% of a screen. Its rarity makes actions, selection, links, and focus unmistakable.

**The Separate States Rule.** Success, warning, error, information, and pending states use independent semantic colors plus text or icons. Never derive them from the brand indigo, and never communicate state by color alone.

**The No-Purple-Surface Rule.** Neon violet, gradients, and large purple or indigo surfaces are prohibited.

## 3. Typography

**Display Font:** `[single humanist sans-serif family to be chosen during implementation]`

**Body Font:** Same family as Display

**Label/Mono Font:** `[supporting monospace to be chosen during implementation]`, technical details only

**Character:** Approachable, neutral, and precise. The primary family must have excellent Vietnamese diacritic support and clearly distinguish similar characters. Hierarchy comes from size, weight, spacing, and placement rather than competing font families.

### Hierarchy

- **Display** (`[to be resolved during implementation]`): Rare screen-level titles only; never promotional or oversized.
- **Headline** (`[to be resolved during implementation]`): Major workflow and record headings with balanced, compact line lengths.
- **Title** (`[to be resolved during implementation]`): Section, task, and evidence-group headings.
- **Body** (`[to be resolved during implementation]`): Comfortable on mobile resident screens, with long prose capped at 65–75 characters per line.
- **Label** (`[to be resolved during implementation]`): Clear sentence-case control and metadata labels; no decorative tracked uppercase.

Financial amounts, balances, dates in aligned records, and operational tables use tabular numerals. Operational dashboards may be slightly denser than resident screens but must remain comfortably readable.

Monospace is reserved for expandable hashes, event IDs, signatures, and transaction references. It never appears in primary navigation, status explanations, buttons, or financial summaries.

### Named Rules

**The One-Voice Rule.** One humanist sans-serif family carries the primary interface. Weight and scale create hierarchy; extra font families do not.

**The Human Before Hash Rule.** Explain the evidence in human language first. Monospace technical identifiers appear only after the user expands verification details.

## 4. Elevation

LamTo is flat by default. Depth comes from neutral surface changes, spacing, grouping, and clear hierarchy rather than decorative shadows. Dialogs, drawers, menus, and other genuinely overlapping layers may use restrained elevation values to be resolved during implementation.

Motion is limited to loading and submission progress, success/warning/error feedback, expandable verification details, dialogs or drawers, and newly changed workflow status. Transitions are short and subtle, never delay action, and preserve all meaning when reduced motion is enabled.

### Named Rules

**The Flat-Record Rule.** Evidence at rest has no decorative lift. If a record needs a large shadow to look organized, its hierarchy is wrong.

**The State-Only Motion Rule.** Motion explains a state change or spatial relationship. Choreographed entrances, scroll effects, decorative animation, and animated charts are prohibited.

## 6. Do's and Don'ts

### Do:

- **Do** keep neutral surfaces dominant and reserve Accountability Indigo for primary actions, selected navigation, links, and visible focus.
- **Do** explain every status, approval, document check, and verification result in plain language before technical detail.
- **Do** use one highly legible humanist sans-serif family with Vietnamese diacritic support and tabular numerals for money.
- **Do** design resident journeys mobile-first for older adults and users with limited digital confidence, including 44px minimum touch targets.
- **Do** keep operational screens task-oriented and evidence-led, with clear responsibility and next actions rather than interchangeable dashboard cards.
- **Do** keep essential meaning available without motion, color, or a reliable connection.

### Don't:

- **Don't** resemble the Binance trading dashboard or any crypto-trading or Web3 dashboard with neon visuals, token language, prominent hashes, or transaction IDs dominating the interface.
- **Don't** use neon violet, gradients, or large purple surfaces.
- **Don't** become a generic admin template made of interchangeable cards, charts, and data tables without a clear accountability narrative.
- **Don't** resemble a glossy property-management sales app with luxury-building imagery, promotional gradients, or marketing-first interactions.
- **Don't** create a surveillance or command-center interface that makes residents feel monitored or controlled.
- **Don't** expose an overly legalistic, accounting-heavy, or technically dense system instead of explaining evidence and status in plain language.
- **Don't** look like a playful hackathon prototype that weakens the seriousness of financial records.
- **Don't** let blockchain or AI dominate the visual identity; show them only where they clarify verification or automation.
- **Don't** use choreographed entrances, scroll-driven effects, decorative motion, or animated charts.
