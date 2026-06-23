# PolySignal Lab Design System

## 1. Atmosphere & Identity

PolySignal Lab feels like a quiet read-only trading operations console: dense enough for repeated inspection, restrained enough that risk and status stay legible. The signature is ledger clarity, with tabular data, compact metrics, and a muted amber focus accent reserved for navigation and keyboard states.

## 2. Color

### Palette

| Role | Token | Light | Dark | Usage |
|------|-------|-------|------|-------|
| Surface/primary | --surface-primary | #f7f4ed | #10100f | Page background |
| Surface/secondary | --surface-secondary | #efebe1 | #181713 | Summary bands and grouped rows |
| Surface/elevated | --surface-elevated | #fffdf8 | #222018 | Data panels and tables |
| Text/primary | --text-primary | #1f1c18 | #f7f4ed | Main text and headings |
| Text/secondary | --text-secondary | #625b50 | #c2b9aa | Metadata and labels |
| Text/tertiary | --text-tertiary | #8a8172 | #8f8779 | Empty states and timestamps |
| Border/default | --border-default | #d9d0c0 | #3a352c | Tables, panels, controls |
| Border/subtle | --border-subtle | #e9e1d4 | #2c2922 | Row dividers |
| Accent/primary | --accent-primary | #8f5b12 | #d39a37 | Links and focus rings |
| Accent/hover | --accent-hover | #6e430b | #f0bb5d | Link hover state |
| Status/success | --status-success | #277747 | #6fcb8a | Healthy status |
| Status/warning | --status-warning | #9a650d | #ddb25c | Paper-only/read-only state |
| Status/error | --status-error | #a33a2d | #db8176 | Errors |
| Status/info | --status-info | #356a80 | #7bb4c7 | Informational links |

### Rules

- Accent is interactive only: links, focus, and selected navigation state.
- Read-only state uses warning sparingly as a semantic label, not decoration.
- Never introduce a color outside this table without extending the table first.

## 3. Typography

### Scale

| Level | Size | Weight | Line Height | Tracking | Usage |
|-------|------|--------|-------------|----------|-------|
| H1 | 28px / 1.75rem | 650 | 1.2 | 0 | Page title |
| H2 | 18px / 1.125rem | 650 | 1.3 | 0 | Section headings |
| H3 | 16px / 1rem | 650 | 1.4 | 0 | Panel titles |
| Body | 14px / 0.875rem | 400 | 1.55 | 0 | Default dashboard text |
| Body/sm | 13px / 0.8125rem | 400 | 1.45 | 0 | Dense table cells |
| Caption | 12px / 0.75rem | 550 | 1.35 | 0 | Labels and timestamps |
| Mono | 13px / 0.8125rem | 500 | 1.45 | 0 | IDs, numbers, strategy names |

### Font Stack

- Primary: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif
- Mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace
- Serif: not used

### Rules

- Numerical dashboard values use tabular figures.
- Body text never goes below 13px in tables or 14px in prose.
- Letter spacing remains 0 for this operational surface.

## 4. Spacing & Layout

### Base Unit

All spacing derives from a base of 4px.

| Token | Value | Usage |
|-------|-------|-------|
| --space-1 | 4px | Tight inline gaps |
| --space-2 | 8px | Table cell padding |
| --space-3 | 12px | Compact panel padding |
| --space-4 | 16px | Default panel padding |
| --space-5 | 20px | Header and section spacing |
| --space-6 | 24px | Page rhythm |
| --space-8 | 32px | Major layout gaps |

### Grid

- Max content width: 1180px
- Column system: responsive CSS grid, auto-fit panels, table overflow contained by section
- Breakpoints: compact under 720px, full dashboard above 960px

### Rules

- Keep the first viewport functional: status, counts, latest report, and navigation visible without a hero.
- Use full-width bands and unframed sections; reserve panels for grouped operational data.

## 5. Components

### Metric Grid
- **Structure**: `<section>` containing compact `<article>` metric panels.
- **Variants**: count, report summary.
- **Spacing**: --space-3 and --space-4.
- **States**: links inside panels have hover and focus states.
- **Accessibility**: each panel has a heading and visible value.
- **Motion**: none.

### Data Table
- **Structure**: `<table>` with `<caption>`, `<thead>`, and `<tbody>`.
- **Variants**: counts, signals, trades, leaderboard.
- **Spacing**: --space-2 cell padding.
- **States**: row hover tonal shift; focus handled on links.
- **Accessibility**: captions describe table purpose; empty state uses a single full-width row.
- **Motion**: none.

## 6. Motion & Interaction

### Timing

| Type | Duration | Easing | Usage |
|------|----------|--------|-------|
| Micro | 120ms | ease-out | Link hover and focus color changes |

### Rules

- No layout animation on the dashboard.
- Every link has hover and visible focus states.
- Respect `prefers-reduced-motion`; current dashboard has no non-essential motion.

## 7. Depth & Surface

### Strategy

borders-only

| Type | Value | Usage |
|------|-------|-------|
| Default | 1px solid var(--border-default) | Panels and table outlines |
| Subtle | 1px solid var(--border-subtle) | Row dividers |

No box shadows. Surface hierarchy comes from tokenized background color and compact borders.
