---
name: LamTo
description: Accountability layer for apartment maintenance across a resident mobile app and Management web workspace.
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
  warning: "#8a5c00"
  warning-bg: "#fff6dd"
  error: "#b42318"
  error-bg: "#fef3f2"
  info: "#175cd3"
  info-bg: "#eff8ff"
  staff-nav: "#1c2434"
  dark-bg: "#12141c"
  dark-surface: "#1c2030"
  dark-ink: "#e8eaf2"
  dark-muted: "#a0a8b8"
  dark-border: "#3a4158"
typography:
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  headline:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.25
  title:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.15rem"
    fontWeight: 700
    lineHeight: 1.25
  label:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 600
    lineHeight: 1.3
  amount:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1.2
    fontFeature: "tabular-nums"
  nav-label:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
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
  touch-web: "44px"
  touch-android: "48dp"
  nav-height: "4.25rem"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: "0.65rem 1rem"
    height: "{spacing.touch-web}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    rounded: "{rounded.md}"
    padding: "0.65rem 1rem"
    height: "{spacing.touch-web}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.65rem 0.75rem"
    height: "{spacing.touch-web}"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "{spacing.4}"
  status-chip:
    rounded: "{rounded.pill}"
    padding: "0.2rem 0.65rem"
    typography: "{typography.label}"
  filter-chip:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0.25rem 0.75rem"
  filter-chip-active:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.pill}"
    padding: "0.25rem 0.75rem"
  staff-nav-link:
    backgroundColor: "{colors.staff-nav}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.sm}"
    padding: "0.5rem 0.75rem"
    height: "{spacing.touch-web}"
---

# Design System: LamTo

## 1. Overview

**Creative North Star: "The Open Maintenance Desk"**

LamTo feels like a well-lit resident service desk where reports, decisions, money, and proof are arranged in one readable sequence. A resident should understand what happened and what comes next while checking a phone in a building corridor; Management staff should inspect the same evidence efficiently at a desktop.

The resident app and staff web platform are distinct systems joined by one evidence chain. The app follows iOS Human Interface Guidelines and Android Material 3 conventions. The web surface is denser and task-oriented. Both explain human outcomes before exposing technical proof.

**Key Characteristics:**

- Restrained cool neutrals with sparse Accountability Indigo.
- Platform-native resident navigation and controls.
- Desktop-first operational web workflows.
- Shared semantic integrity states and plain-language status vocabulary.
- State-only motion and a WCAG 2.2 AA baseline.

## 2. Colors

Neutral surfaces dominate. Accountability Indigo is reserved for primary actions, current selection, links, and focus; semantic colors communicate evidence state.

### Primary

- **Accountability Indigo:** Institutional emphasis without crypto-purple spectacle.
- **Focus Blue:** Keyboard focus on web and the closest platform focus equivalent on native.

### Neutral

- **Clear Ground:** Default light page and scaffold background.
- **Working Surface:** Forms, sheets, and grouped content.
- **Quiet Surface:** Toolbars, filter chrome, and secondary regions.
- **Record Ink:** Primary copy, financial amounts, and the staff navigation surface.
- **Quiet Ink:** Secondary labels and metadata that still meet AA contrast.
- **Border Mist:** Dividers, input strokes, and flat container boundaries.
- **Night Ground, Night Surface, Night Ink, Night Quiet Ink, Night Border:** The first-class dark appearance for the Flutter app.

### Semantic

- **Verified Green:** Confirmed, resolved, and independently verified.
- **Attention Amber:** Pending, incomplete, or requiring review.
- **Mismatch Red:** Failure, mismatch, or blocked progress.
- **Open Blue:** Open, informational, and in-progress states.

### Named Rules

**The Ten-Percent Rule.** Accountability Indigo occupies no more than ten percent of a screen.

**The Separate States Rule.** Success, warning, error, and information use independent semantic roles plus text or icons; color never carries meaning alone.

**The Native Role Rule.** Flutter maps the palette through iOS semantic colors and Material color roles so dark mode and increased contrast remain functional.

## 3. Typography

**Display Font:** Platform system sans

**Body Font:** Platform system sans

**Label/Mono Font:** Platform mono only inside expanded technical proof

**Character:** Approachable, neutral, and precise. One system family carries each surface; hierarchy comes from role, weight, and placement rather than decorative type pairing.

### Hierarchy

- **Headline:** Screen-level titles; never promotional display sizes.
- **Title:** Section headings and evidence groups.
- **Body:** Primary copy with a 65–75ch prose limit on web.
- **Label:** Field labels, metadata, and status text in sentence case.
- **Amount:** Financial figures with tabular numerals.
- **Native roles:** Dynamic Type on iOS and the Material type scale on Android; no hard-coded native point sizes.

### Named Rules

**The Human Before Hash Rule.** Explain evidence in human language before showing hashes, event IDs, or signatures.

**The Vietnamese-First Rule.** Resident type scales with the system and preserves enough leading for Vietnamese diacritics at every supported size.

## 4. Elevation

LamTo is flat by default. Structure comes from spacing, dividers, tonal surfaces, and platform materials. Native surfaces use system materials on iOS and Material tonal elevation on Android. The existing web panel shadow is a legacy implementation detail, not a pattern to copy.

### Named Rules

**The One Boundary Rule.** A container may use a solid border or a soft elevation shadow, never both as decoration.

**The Flat Record Rule.** Evidence at rest has no decorative lift. If a record needs a large shadow to look organized, its hierarchy is wrong.

**The State-Only Motion Rule.** Motion explains state or spatial relationship and honors Reduce Motion or Remove animations; page-load choreography is prohibited.

## 5. Components

Components are familiar, restrained, and consistent. Every interactive control must account for default, focus, active, disabled, loading, and error states where applicable.

### Buttons

- **Web:** Gently rounded, minimum 44px targets, indigo primary and white secondary treatments.
- **iOS:** Native button roles and 44pt minimum targets.
- **Android:** Material filled, tonal, outlined, or text roles and 48dp minimum targets.
- **Focus:** A visible Focus Blue ring on web and platform-native focus treatment elsewhere.

### Status and filter chips

- **Status chips:** Semantic background and ink, always paired with a label and icon where useful.
- **Filter chips:** Quiet Surface when inactive and Accountability Indigo when selected.
- **Separation:** Filter state never borrows verified, warning, or error colors.

### Cards and containers

- **Resident app:** Prefer platform lists and grouped content over card stacks.
- **Staff web:** Flat Working Surface panels with clear headings and one boundary treatment.
- **Links:** Whole-row hit targets; hover strengthens the border on web.
- **Nesting:** Nested cards are prohibited.

### Inputs and fields

- **Web:** Full-width white fields, visible labels, 44px minimum height, and an explicit error message block.
- **Native:** System text fields, switches, pickers, sheets, and dialogs.
- **Failure:** Preserve entered data where safe and explain whether it was saved.

### Navigation

- **iOS resident app:** A tab bar for top-level destinations and navigation stacks for hierarchy.
- **Android resident app:** A navigation bar on compact widths and a rail or drawer on expanded widths; system Back always works.
- **Staff web:** Dark operational navigation, a clear membership switcher, and task-dense content.

### Signature patterns

- **Fund balance:** A prominent tabular amount followed by opening, inflow, and outflow context.
- **Accountability chain:** An ordered plain-language sequence with technical proof behind progressive disclosure.
- **Action inbox:** A task list showing who must act next, not a surveillance dashboard.

## 6. Do's and Don'ts

### Do:

- **Do** connect each expenditure to the reports, work, decisions, documents, and verification that justify it.
- **Do** explain status and outcomes before technical proof.
- **Do** use platform-native resident controls while sharing brand and semantic roles across platforms.
- **Do** pair semantic color with text or icons and verify WCAG 2.2 AA contrast.
- **Do** use tabular numerals for money and expose the next safe action after failure.

### Don't:

- **Don't** resemble a crypto-trading or Web3 dashboard with neon visuals, token language, or hashes and transaction IDs dominating the interface.
- **Don't** become a generic admin template composed of interchangeable cards, charts, and tables without an accountability narrative.
- **Don't** resemble a glossy property-management sales app built around luxury imagery, promotional gradients, or marketing-first interactions.
- **Don't** create a surveillance or command-center interface that makes residents feel monitored or controlled.
- **Don't** expose an overly legalistic, accounting-heavy, or technically dense system instead of plain status and evidence.
- **Don't** look like a playful hackathon prototype that weakens the seriousness of financial records.
- **Don't** use gradient text, glassmorphism, colored side-stripe borders, nested cards, oversized radii, decorative grids, or repeated eyebrow scaffolding.
- **Don't** pair a one-pixel border with a wide soft shadow on the same container.
- **Don't** port web navigation chrome into the native resident app.
