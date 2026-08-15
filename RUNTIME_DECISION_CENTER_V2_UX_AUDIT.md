# Runtime Decision Center V2, UX Audit

## Method and its limitation, stated up front

No browser-automation tool was available in this session (confirmed by searching for one before starting; `WebFetch` was tried against the live page and, as expected for a client-rendered SPA, returned only the static `<title>` tag with no rendered content). This audit is therefore a **code-level review**: reading the actual JSX/Tailwind/CSS-variable source in `src/app/live/pages/LiveTestIntent.tsx`, computing what's computable (contrast ratios from real hex values), and comparing structural patterns against the rest of the shipped dashboard. It is not an observed visual review. Anything below that would normally require eyes on a rendered page is marked as such rather than asserted.

## Findings

### 1. Eyebrow-label inconsistency with the rest of the dashboard

The three column headers ("Business context," "Runtime authority," "Decision") use `text-[11px] font-semibold uppercase tracking-wider`. The established eyebrow pattern elsewhere in this app (`PlatformOverview.tsx`, `LiveAssurance.tsx`) is `text-xs font-mono uppercase tracking-widest`, typically paired with a small leading icon and an accent color. The new column headers don't match this exactly (different size token, different font weight, no monospace, no icon). Not wrong, but a real, fixable inconsistency, this page invented a near-miss of an existing pattern rather than reusing it outright.

### 2. Evidence section reads as a data dump, not a curated summary

`EvidenceRecordCard` renders up to 14 label/value rows in a flat two-column grid per record, with no visual hierarchy distinguishing a handful of headline facts (outcome, risk, who reviewed) from denser provenance detail (hashes, bundle IDs, signature). The original brief for this whole redesign explicitly warned against "dense logs." This section, while entirely accurate (see the Data Provenance audit), is the one place Phase 1 drifts back toward that same undifferentiated-list feel it was meant to move away from. Worth a follow-up pass that promotes 3 to 4 fields to a prominent tier and demotes the rest, not a data problem, a presentation one.

### 3. "×" glyph on the "unavailable" pipeline stage overstates severity

`StageRow` renders a "×" inside the stage-node circle when a stage's state is `unavailable` (e.g., no policy matched, or authority context never resolved). "×" reads as an error or failure. Several `unavailable` cases are neutral, not failures (e.g., an agent legitimately has no principal set yet). A less alarming glyph, or no glyph at all with the adjacent "Not available" chip carrying the meaning, would better match the actual severity.

### 4. Loading-state inconsistency: text vs. the app's own Skeleton component

Most of the dashboard's established loading pattern (`PlatformOverview.tsx`, `LiveAssurance.tsx`, several Policy Studio pages) is the shared `<Skeleton>`/`<SkeletonRows>` component: a pulsing placeholder block. This page uses that component in exactly two places (the principal-context card, the authority-chain card) but falls back to plain "Loading..." text in two others (the pipeline's "Risk classified" stage detail, the Decision panel's risk-classification row). Both are real loading states, just inconsistent in how they're presented within the same page.

### 5. Color contrast: `--pr-text-disabled` on `--pr-bg-primary` computes to ~3.98:1

This page uses the existing `--pr-text-disabled` (`#64748B`) token heavily for muted/secondary text: stage timing labels, "not set" values, disabled hints. Computed against the dark theme's `--pr-bg-primary` (`#07111F`), the WCAG contrast ratio is approximately 3.98:1, under the 4.5:1 AA threshold for normal-size text (it clears the 3:1 threshold for large/bold text). This is a **pre-existing token used throughout the whole app**, not something introduced by this page, but this page is a comparatively heavy new user of it (the "Not set" fallback values throughout Business Context and Authority Chain), so it's worth flagging here rather than treating as someone else's problem.

### 6. Italic styling for "not set" values is a new, one-off convention

`ContextRow`'s `muted` variant renders unset values in italic. No other page reviewed during this session's earlier work used italics for this purpose (the established pattern elsewhere is color-only, via `--pr-text-disabled`/`--pr-text-muted`). Introducing italics here, specifically, is a small, avoidable inconsistency.

### 7. Layout stability: the second Business Context card appears only after agent selection

The "Acting identity" card doesn't render at all until an agent is selected, so selecting an agent causes a new card to pop into the left column rather than an already-present card filling in. Minor, but a real layout shift a first-time user will notice.

### 8. Accessibility: stage-node glyphs have no text alternative

The ✓/× glyphs inside `StageRow`'s circular nodes are bare Unicode characters with no `aria-label`. A screen-reader user isn't left with nothing (the adjacent chip text, e.g. "Confirmed," "Not available," is real accessible text), but the glyph itself is decorative-only without being marked `aria-hidden`, which is a small, easy correctness fix rather than a real barrier.

### 9. Responsive behavior: reasoned about, not observed

The three-column hero uses `grid-cols-1 lg:grid-cols-3`, meaning it stacks to a single column below the `lg` breakpoint (1024px) rather than an intermediate two-column layout at tablet widths. This is a reasonable, conservative choice (matches how `PlatformOverview.tsx` handles its own card grid), but whether it feels right at real tablet/laptop widths was not observed in a browser and should be checked manually.

### 10. What's genuinely good, for balance

- The empty/loading/allow/deny/escalate/blocked states are all handled with distinct, real content rather than a single generic placeholder repeated everywhere, this was a specific risk for a page this size and it was avoided.
- Every section (`Card` component, consistent `padding={20}`, consistent hairline borders via `--pr-overlay-*` tokens) uses the app's existing design tokens throughout; there is no hardcoded color or spacing value that bypasses the token system.
- The Approve/Deny/resolver-name flow, the signing flow, and the polling indicator are unchanged, already-shipped, already-familiar interactions, just relocated, which is exactly what a "reskin, not a rebuild" should do.

## Does it feel like the central operating surface of Runtime Authority?

Structurally, yes: the three-column frame genuinely centers the page on "agent asks, Runtime Authority decides," rather than the old page's plain form-then-result layout. Whether it *feels* that way in practice (information density at a glance, whether the pipeline reads as authoritative or busy, whether the Evidence section's density undercuts the rest) cannot be honestly confirmed without a rendered browser pass. The specific, likely-highest-impact fix if a human reviewer agrees after looking at it: address finding #2 (Evidence density) first, since it's the section most likely to make the page feel like the "dense log" the original redesign was meant to escape.

No redesign was performed in this task, per instruction. These ten findings are documented for a separate follow-up pass.
