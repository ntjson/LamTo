---
name: LamTo
description: Accountability layer for apartment maintenance—resident mobile app and staff web, two visual systems, one evidence chain.
colors:
  primary: "#2f3a8f"
  on-primary: "#ffffff"
  focus: "#0b57d0"
  neutral-bg: "#f6f7fb"
  surface: "#ffffff"
  surface-muted: "#eef1f8"
  ink: "#1c2434"
  muted: "#5b6577"
  border: "#d7dce8"
  success: "#0f7a45"
  success-bg: "#e7f6ee"
  warning: "#9a6700"
  warning-bg: "#fff6dd"
  error: "#b42318"
  error-bg: "#fef3f2"
  info: "#175cd3"
  info-bg: "#eff8ff"
  staff-nav: "#1c2434"
typography:
  body:
    fontFamily: "Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  headline:
    fontFamily: "Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.25
  title:
    fontFamily: "Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.15rem"
    fontWeight: 700
    lineHeight: 1.25
  label:
    fontFamily: "Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 600
    lineHeight: 1.3
  amount:
    fontFamily: "Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1.2
  nav-label:
    fontFamily: "Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.2
rounded:
  sm: "8px"
  md: "10px"
  lg: "12px"
  pill: "999px"
spacing:
  1: "0.25rem"
  2: "0.5rem"
  3: "0.75rem"
  4: "1rem"
  5: "1.5rem"
  6: "2rem"
  touch: "44px"
  nav-height: "4.25rem"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: "0.65rem 1rem"
    height: "{spacing.touch}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    rounded: "{rounded.md}"
    padding: "0.65rem 1rem"
    height: "{spacing.touch}"
  button-primary-hover:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.65rem 0.75rem"
    height: "{spacing.touch}"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "{spacing.4}"
  card-link:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "{spacing.3}"
  status-chip:
    rounded: "{rounded.pill}"
    padding: "0.2rem 0.65rem"
    typography: "{typography.label}"
  staff-nav-link:
    backgroundColor: "{colors.staff-nav}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.sm}"
    padding: "0.5rem 0.75rem"
    height: "{spacing.touch}"
---

# Design System: LamTo

## 1. Overview

**Creative North Star: "The Open Maintenance Desk"**

LamTo should feel like a well-lit resident service desk where reports, decisions, and proof are arranged in one readable sequence. The product is trustworthy, clear, and rigorous—never bureaucratic theater. Residents first see what happened, what is verified, and what comes next; operational users then inspect the same evidence with denser tools.

**Two visual systems, one evidence chain.** Resident and staff are not the same UI in two densities. They share brand color, semantic states, and accountability language, but they are designed as distinct systems:

- **Resident mobile app (adaptive):** Platform-native shells—iOS Human Interface Guidelines (tab bar, navigation stack, SF Symbols, Dynamic Type, system materials) and Android Material 3 (navigation bar/rail, type roles, tonal surfaces, system Back). Brand expresses through tint, semantic status, and content hierarchy—not through reinvented web chrome.
- **Staff web (desktop-first, tablet OK):** Task-dense product UI from the current Django PWA staff shell—dark operational nav, membership switcher, action inbox, proposal/payment detail workflows. Familiar web controls; restrained institutional feel; wider layouts and multi-column task surfaces.

Shared doctrine: plain-language outcomes before expandable technical proof; flat, ordered information with clear state, responsibility, and next action; motion only for state change. The system rejects crypto/Web3 dashboards, generic admin templates, glossy property-sales apps, surveillance command centers, legalistic density, and playful hackathon aesthetics.

**Key Characteristics:**

- Restrained neutrals with sparse Accountability Indigo (`#2f3a8f`).
- Two shells: native resident app vs desktop-first staff web.
- One family of semantic integrity states (verified, open, warning, mismatch).
- Explain before proving—hashes and signatures stay secondary.
- WCAG 2.2 AA baseline on both surfaces.

## 2. Colors

The palette is restrained: neutral surfaces carry the interface; a blue-leaning muted indigo provides institutional emphasis without neon, purple spectacle, or crypto cues.

### Primary

- **Accountability Indigo** (`#2f3a8f`): Primary actions, selected navigation, brand mark, and links. Occupies ≤10% of any screen. Never large purple or indigo fields; never gradients.
- **On Primary** (`#ffffff`): Text and icons on indigo fills.
- **Focus Blue** (`#0b57d0`): Focus rings and keyboard focus affordances on web; map to platform focus indicators on mobile.

### Secondary

Omit a decorative secondary brand color. Integrity and feedback use independent semantic colors below—not tints of indigo.

### Neutral

- **Clear Ground** (`#f6f7fb`): Primary page background; cool-neutral, suitable for long reading.
- **Working Surface** (`#ffffff`): Panels, cards, forms, sheets.
- **Quiet Surface** (`#eef1f8`): Membership bars, grouped tool chrome, subtle region fills (staff).
- **Record Ink** (`#1c2434`): Body text, financial amounts, staff nav background.
- **Quiet Ink** (`#5b6577`): Secondary labels and metadata that still meet contrast.
- **Border Mist** (`#d7dce8`): Dividers, input strokes, card outlines.

### Semantic (integrity and feedback)

- **Success** (`#0f7a45` / bg `#e7f6ee`): Verified, resolved, confirmed.
- **Warning** (`#9a6700` / bg `#fff6dd`): Pending, attention, incomplete ratification.
- **Error** (`#b42318` / bg `#fef3f2`): Mismatch, failure, blocking errors.
- **Info** (`#175cd3` / bg `#eff8ff`): Open, informational, in progress.

### Named Rules

**The Ten-Percent Rule.** Accountability Indigo occupies no more than 10% of a screen. Its rarity makes actions, selection, and focus unmistakable.

**The Separate States Rule.** Success, warning, error, info, and pending use independent semantic colors plus text or icons. Never derive them from brand indigo, and never communicate state by color alone.

**The No-Purple-Surface Rule.** Neon violet, gradients, glassmorphism, and large purple or indigo surfaces are prohibited.

**The Two-System Rule.** Resident mobile and staff web may differ in chrome, density, and platform materials. They must not diverge on integrity colors, primary brand, or plain-language status vocabulary.

## 3. Typography

**Display Font:** System / platform default (web: Segoe UI, system-ui, -apple-system; iOS: SF Pro; Android: Roboto / Material type theme)

**Body Font:** Same as Display

**Label/Mono Font:** Platform mono only for expandable technical identifiers (hashes, event IDs, signatures)—never for primary status copy

**Character:** Approachable, neutral, precise. Hierarchy comes from size, weight, and placement—not competing families. Resident type follows Dynamic Type / Material type scale; staff web uses a fixed rem scale for denser operational reading.

### Hierarchy

- **Headline** (700, `1.5rem` web / platform Large Title or Headline): Screen-level titles (e.g. fund balance, case title). Never promotional display sizes.
- **Title** (700, `1.15rem` web / Title): Section and evidence-group headings.
- **Body** (400, `1rem`, line-height 1.5): Primary copy; long prose capped near 65–75ch on web; native follows system body style.
- **Label** (600, `0.85rem`): Field labels, metadata, status chip text—sentence case, no decorative tracked uppercase.
- **Amount** (700, `1.75rem`, tabular nums): Fund balance and money figures.
- **Nav label** (600, `0.75rem` web; platform tab labels on mobile): Bottom or side navigation.

### Named Rules

**The One-Voice Rule.** One humanist sans family (or platform system face) carries the primary interface. Weight and scale create hierarchy.

**The Human Before Hash Rule.** Explain evidence in human language first. Monospace technical identifiers appear only after the user expands verification details.

**The Platform Type Rule.** Resident mobile uses system text styles (Dynamic Type / Material roles). Do not hard-code web rem sizes into native UI.

## 4. Elevation

LamTo is flat by default. Evidence at rest has no decorative lift. Depth comes from surface changes, spacing, grouping, and borders. Content panels may use a soft ambient lift; staff and native chrome use platform-appropriate materials sparingly.

### Shadow Vocabulary

- **Panel ambient** (`0 1px 2px rgba(28, 36, 52, 0.06), 0 8px 24px rgba(28, 36, 52, 0.06)`): Optional lift for primary content panels on staff/resident web PWA. Not stacked, not dark, not “card theater.”
- **Native:** Prefer system materials and Material tonal elevation over custom drop shadows.

Motion is limited to loading/submission progress, success/warning/error feedback, expandable verification, dialogs/sheets, and newly changed workflow status. Short and subtle; honor reduced motion / Remove animations.

### Named Rules

**The Flat-Record Rule.** Evidence at rest has no decorative lift. If a record needs a large shadow to look organized, its hierarchy is wrong.

**The State-Only Motion Rule.** Motion explains a state change or spatial relationship. Choreographed entrances, scroll effects, decorative animation, and animated charts are prohibited.

## 5. Components

Restrained and institutional. Familiar product controls; clear primary actions; status chips for integrity; no playful chrome.

### Buttons

- **Shape:** Gently rounded (`10px` web); platform button shapes on native.
- **Primary:** Accountability Indigo fill, white label, min height `44px` (web) / 44pt iOS / 48dp Android.
- **Secondary:** White surface, indigo text, mist border.
- **Focus:** `3px` solid Focus Blue offset on web; platform focus on native.
- **Loading / disabled:** Preserve label space; never rely on color alone.

### Status chips

- **Style:** Pill radius, small bold label, icon + text, semantic bg/ink pairs from the integrity palette.
- **Roles:** Open/info, verified/resolved, warning, mismatch/error.
- **Rule:** Always pair color with text (and icon when present).

### Cards / containers

- **Resident:** Prefer platform list rows / grouped lists over nested card stacks. Where cards exist, single border, Working Surface, `12px` radius, no nested cards.
- **Staff panels:** Working Surface, mist border, optional panel ambient shadow, `1rem` padding, clear panel header with title + action.
- **Card links:** Full-row hit targets; hover strengthens border to indigo (web only).

### Inputs / fields

- **Style:** Full width, mist border, `10px` radius, min height touch target, white fill.
- **Label:** Bold, above control.
- **Error:** Error ink on error-bg message block; associate with field.
- **Native:** System text fields, pickers, and date controls—do not port web input chrome.

### Navigation

- **Resident mobile:** Platform tab bar (3–5 destinations: Home, Report, Issues, Ledger, Account or equivalent). Stack for hierarchy. Large titles on top-level iOS screens. Material nav bar compact / rail expanded on Android.
- **Resident web PWA (current):** Fixed bottom nav, five equal columns, Quiet Ink default, indigo when active, min height `4.25rem`.
- **Staff web:** Dark Record Ink horizontal nav with white labels; active/hover uses indigo fill; membership switcher on Quiet Surface bar above content. Desktop-first width; wrap allowed on tablet.

### Signature patterns

- **Fund balance block:** Large tabular amount + currency label + secondary stat grid (opening / inflows / outflows).
- **Accountability chain detail:** Ordered plain-language timeline; technical proof in expandable sections only.
- **Action inbox (staff):** Task list of “who must act next,” not a surveillance dashboard.
- **Signed action box (staff):** Bordered surface for wallet-signed decisions; mono only inside the expandable proof region.

## 6. Do's and Don'ts

### Do:

- **Do** keep neutral surfaces dominant and reserve Accountability Indigo for primary actions, selection, links, and focus.
- **Do** explain every status, approval, document check, and verification result in plain language before technical detail.
- **Do** design **two systems**: platform-native resident mobile (HIG + Material 3) and desktop-first staff web—sharing tokens for brand, integrity states, and vocabulary.
- **Do** use tabular numerals for money and aligned financial records.
- **Do** meet WCAG 2.2 AA on both surfaces; pair every semantic color with text or icon.
- **Do** keep staff screens task-oriented and evidence-led, with clear responsibility and next actions.
- **Do** honor reduced motion and platform accessibility settings.

### Don't:

- **Don't** resemble a crypto-trading or Web3 dashboard with neon visuals, token language, or hashes and transaction IDs dominating the interface.
- **Don't** use neon violet, gradients, glassmorphism, or large purple surfaces.
- **Don't** become a generic admin template of interchangeable cards, charts, and tables without an accountability narrative.
- **Don't** resemble a glossy property-management sales app with luxury imagery, promotional gradients, or marketing-first interactions.
- **Don't** create a surveillance or command-center interface that makes residents feel monitored or controlled.
- **Don't** expose an overly legalistic, accounting-heavy, or technically dense system instead of plain status and evidence.
- **Don't** look like a playful hackathon prototype that weakens the seriousness of financial records.
- **Don't** let blockchain or AI dominate visual identity; show them only where they clarify verification or automation.
- **Don't** ship web bottom-nav chrome as the resident “native” app; use platform navigation and controls.
- **Don't** use choreographed entrances, scroll-driven effects, decorative motion, or animated charts.
- **Don't** use side-stripe borders, gradient text, or identical icon+heading card grids as scaffolding.
