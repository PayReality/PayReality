# PayReality Visual System V3

**Status: design foundation, not yet applied to the shipped product.** This document specifies the visual language that will be consumed by three later, separate milestones (Product V3, Demo V3, Website V2), in that order. It changes zero runtime behavior, information architecture, API contracts, or Trusted Integration semantics; see [SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md](SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md) and the rest of `SPECIFICATION/` for what those remain. Five representative prototypes at `/_design-system` (source: `src/app/design-system/`) exercise everything below against real demo data; they are not linked from the real app and are not a shipped surface.

## 1. Visual philosophy

PayReality should read as **enterprise authority infrastructure for autonomous systems**: serious, precise, calm, technically sophisticated, distinctive. Not a generic SaaS template, not a crypto product, not a neon security dashboard, not consumer fintech, not a chatbot, not a purple-gradient AI startup, not a military command center.

The audit in §2 found the existing system (built across several prior "Visual Experience" passes) already earns most of that: a real dark/light token architecture, a restrained shadow/motion scale, a working focus-visible ring, reduced-motion handling, and a consistent type pairing. V3 is **evolution, not replacement**: it keeps everything that already works and adds the specific pieces the product's own subject matter (authority, decisions, evidence, trusted integration) needs and didn't have a name for yet.

The organizing idea (§2 of the brief) is literal in the new components: **Agent → Action → Authority → Decision → Evidence**. This sequence is now a real, reusable shape (`AuthorityChain`, §7), not just a sentence repeated in prose across five different pages.

## 2. Existing design audit (KEEP / REFINE / REPLACE)

Grounded in direct code reading (`src/styles/theme.css`, `src/app/components/ui/*`, and a sample of real pages), not assumption.

**KEEP, unchanged:**
- Token architecture: `--pr-*` CSS custom properties, dark-first with `data-theme="light"` override (`theme.css:3-124`). The real app's actual default is **light**, set by `src/app/lib/theme.ts`'s `initTheme()` before first paint, toggleable in Organisation Settings → General: a genuine, working, previously undocumented-in-this-audit theme system, not a gap.
- Overlay scale (`--pr-overlay-03` through `-12`), shadow scale (`sm`/`card`/`raised`), motion scale (`fast`/`base`/`slow` plus a named ease): all already correct, already used consistently.
- `Card`, `Sheet` (Radix-based), `Skeleton`/`SkeletonRows`, `Alert` (4 severities): solid, minimal shells; keep the API surface exactly as-is.
- Inter (UI/body) plus IBM Plex Mono (technical/monospace values) pairing.
- Focus-visible rings, reduced-motion global handling, print stylesheet, `tabular-nums` on metric numbers, the `.pr-enter` staggered-entrance convention.
- Sidebar plus slim topbar navigation shape; the 7-item locked IA (unchanged, per this milestone's own instruction).

**REFINE:**
- `StatusBadge`: shape (left-border plus monospace label) is good and stays; extended with an **optional icon prop** (§6) since this milestone's status vocabularies (Decision outcomes especially) genuinely benefit from a third channel beyond color and text. Fully backward-compatible; no existing call site needed to change.
- `Alert`: icon is currently optional/inconsistent per severity; V3 doesn't change the component but recommends every severity get a default icon when Product V3 actually touches call sites (not done here, to avoid an unrelated sweep).
- Page container widths: currently seven different `max-w-*` values chosen independently per page with no stated rule. V3 doesn't force a migration now, but recommends the convention in §10.
- Icon usage: currently three different conventions in the same app (decorative-on-every-heading, inline-with-button-text, semantic-in-empty-state) with no stated rule. §11 states one.

**REPLACE / NEW** (the actual gaps this audit found, addressed by the new components in §7):
- No shared `Table`, `EmptyState`, or `PageHeader` component existed; every page hand-rolled its own, five-plus independently-written empty states found in one grep alone.
- No distinctive Decision-outcome presentation existed as a shared unit; `OUTCOME_STYLE` (icon/color map) was already correct but re-implemented inline, slightly differently, at every call site.
- No Agent visual identity beyond plain text existed anywhere.
- No distinct "this record is permanent" surface existed for Evidence/Receipts; they used the same flat `Card` as everything else.
- No structured way to show a chain of custody (Principal → Agent → Action → Authority) existed; every page that needed this wrote it as a sentence.

## 3. Color system

Unchanged palette, all already real tokens, none introduced by this milestone:

| Token | Value | Use |
|---|---|---|
| `--pr-authority-blue` | `#4D7CFE` | The one accent: primary actions, active nav, focus rings, the Authority/Agent identity color |
| `--pr-evidence-cyan` | `#00D4FF` | Evidence/Receipt/proof surfaces only, never a general accent |
| `--pr-trust-green` | `#22C55E` | ALLOW, active, approved, verified |
| `--pr-warning-amber` | `#F59E0B` | HUMAN_REVIEW, needs-attention, review-due |
| `--pr-critical-red` | `#EF4444` | DENY, revoked, critical error |
| `--pr-verification-purple` | `#8B5CF6` | Reserved for independent-verification contexts (signature checks); lightly used today (4 sites), not expanded by this milestone |

**Rule for the accent**: `--pr-authority-blue` is the only color used for *interactive/navigational* meaning (links, active states, primary buttons, focus). Semantic colors (green/amber/red/cyan) are never repurposed as decoration and never used for two different meanings on the same page. No gradients anywhere in the product surface itself; the one pre-existing, previously-unused `--pr-logo-gradient-end` (`#7C3AED`) token stays reserved for a single, deliberate brand moment (a website/marketing hero treatment, not a dashboard element). Product V3 should not introduce a gradient anywhere in the actual application.

New, additive tokens (all derived via `color-mix()` from existing tokens, so they already work correctly in both themes with no separate light-mode block needed):

```css
--pr-evidence-border: color-mix(in srgb, var(--pr-evidence-cyan) 28%, var(--pr-overlay-10));
--pr-evidence-tint:   color-mix(in srgb, var(--pr-evidence-cyan) 5%, transparent);
--pr-evidence-corner: color-mix(in srgb, var(--pr-evidence-cyan) 45%, transparent);
--pr-chain-line:        var(--pr-overlay-12);
--pr-chain-dot:         var(--pr-text-disabled);
--pr-chain-dot-active:  var(--pr-authority-blue);
```

## 4. Typography

No new typefaces. Inter for everything except technical/proof values (IBM Plex Mono). The existing `h1` to `h4` scale (reading from Tailwind v4's default `--text-*` scale) stays the base for every "regular" page.

| Context | Treatment |
|---|---|
| Marketing (website) | Larger, expressive display type, out of scope for this milestone's prototypes, specified for Website V2 |
| Product page title | Existing `h1` rule (`var(--text-2xl)`, medium weight) |
| Section heading | Existing `h2`/`h3` |
| Body | Default Inter, `--pr-text-primary`/`-secondary`/`-muted`/`-disabled` for hierarchy |
| Metadata (timestamps, ids) | 11 to 12px, `--pr-text-disabled`, sometimes monospace for exact ids |
| Table cells | 13 to 14px, `tabular-nums` for any numeric column |
| Evidence/proof data | IBM Plex Mono, always: signatures, hashes, key ids, external operation ids |
| Demo | Same scale as product; guided-tour copy (already conversational, see `DEMO_NARRATIVE.md`) can run slightly larger for the tour overlay itself |

## 5. Surface system

| Surface | Token | When |
|---|---|---|
| App background | `--pr-bg-primary` | Page canvas |
| Primary surface | `--pr-bg-card` | Every `Card` |
| Secondary surface | `--pr-bg-secondary` | Sidebar, sticky headers |
| Raised/hover | `--pr-bg-hover`, `--pr-shadow-raised` | Menus, active hover |
| Selected state | `color-mix(authority-blue 12%, transparent)` | Active nav (existing pattern, reused) |
| Informational callout | `Alert severity="neutral"` | Existing |
| Warning / critical | `Alert severity="warning"/"error"` | Existing |
| **Evidence surface** | `EvidenceCard` (new, §7) | Evidence, Authorization Receipt: the one genuinely new surface tier |

Rule carried forward from the existing codebase and reinforced, not changed: a card's border should read as a hairline against its own background, never a second flat rectangle. `--pr-shadow-card` is what actually separates a card from the page, not the border alone.

## 6. Status / Decision system

Canonical human-facing labels (never the raw enum in product copy):

| Enum | Label | Color | Icon |
|---|---|---|---|
| `ALLOW` | Allowed | `--pr-trust-green` | `CheckCircle2` |
| `DENY` | Not allowed | `--pr-critical-red` | `XCircle` |
| `HUMAN_REVIEW` | Needs human approval | `--pr-warning-amber` | `ShieldAlert` |
| Mapping `draft` | Draft | `--pr-text-disabled` | None |
| Mapping `validated` | Validated | `--pr-warning-amber` | None |
| Mapping `approved` | Approved | `--pr-trust-green` | None |
| Mapping/Connection `retired` | Retired | `--pr-text-disabled` | None |
| Connection `active` | Active | `--pr-trust-green` | None |
| Trusted Connection `registered` | Registered | `--pr-text-disabled` | None |
| Trusted Connection `suspended` | Suspended | `--pr-warning-amber` | None |
| Trusted Connection `revoked` | Revoked | `--pr-critical-red` | None |

Every status is color **plus** text (the pre-existing `StatusBadge` contract) **plus**, where a vocabulary genuinely benefits (Decision outcomes), an icon and a distinct pill shape (`DecisionOutcomeBadge`, §7) rather than the flatter left-border tag. The lifecycle badges (mapping/connection/trusted-connection) keep the left-border shape: they're inspected in a management table, not a first-glance outcome, and don't need the stronger treatment.

## 7. New/updated components (implemented)

All in `src/app/components/ui/`, all additive; no existing import broke, confirmed by a full build and test pass.

- **`StatusBadge`** (updated): now accepts an optional `icon` prop; unchanged for every existing caller.
- **`EmptyState`**: icon, title, one-sentence description, optional single action. Replaces five-plus independently hand-written empty states this audit found.
- **`PageHeader`**: title, optional description, status slot, primary/secondary action, optional breadcrumbs. Deliberately compact, not the oversized hero treatment `PlatformOverview.tsx` keeps for its own, documented, different role.
- **`Table` / `TableHead` / `TableBody` / `TableRow` / `TableHeaderCell` / `TableCell`**: a thin shell over the native `<table>` shape every list page already converges on, with truncation and native-title-tooltip built in for long values (§9's data-density requirement) by default.
- **`DecisionOutcomeBadge`**: the canonical Decision presentation, built on the pre-existing (and already correct) `OUTCOME_STYLE` map, not a second color table.
- **`AgentIdentity`**: a square (never circular, so it never reads as a human-user avatar), fixed-authority-blue-tint, initials-based mark with a status-colored corner dot. Explicitly not a humanoid illustration.
- **`EvidenceCard`**: the permanent-record surface (§5, §8).
- **`AuthorityChain`**: the reusable "structure without a flowchart" connector (§9).

**Specified, not yet implemented** (per this milestone's own instruction not to build every abstraction): `AuthoritySummary`, `TrustedConnectionSummary`, `ActionMappingSummary`, `Metric`, `Tabs`, `Dropdown`, `Tooltip`, `Dialog` (Sheet already covers most dialog needs), `Checkbox`/`Radio`/`Textarea`/`Select` refinement. These should be built by whichever of Product V3 / Demo V3 / Website V2 first needs them, following the same token-first, additive-API discipline as the seven above.

## 8. Evidence and Receipt visual language ("this is a record I can rely on later")

`EvidenceCard` (see the component's own extensive doc comment for the full rationale): a hairline border tinted toward `--pr-evidence-cyan` instead of the neutral overlay border, a faint radial cyan tint anchored to the top-left corner, and a small, permanent "EVIDENCE"/"AUTHORIZATION RECEIPT" corner label with a lock glyph, present on every instance, so the surface itself is recognizable before a reader parses its contents. Deliberately **not** blockchain/crypto pastiche: no neon glow, no chained-block imagery, no monospace-everything (only the actual proof values, signatures, hashes, ids, go monospace, not the whole surface).

## 9. Authority visual language ("authority has structure")

`AuthorityChain`: a single row (wraps to multi-row on narrow viewports) of small labeled nodes connected by a hairline, each carrying an icon plus a two-line label/value pair. Used for exactly the sequences the product already asserts in prose: Agent → Action → Authority → Decision → Evidence (Overview), Agent → Delegated-by → Environment (Agent Detail), System → Trusted Connection → Action Mapping → Allowed Agents → PayReality Decision (Integration Detail), and the three-question model itself (Decision Detail). An `inactive` link state (dashed/muted, not hidden) represents a real authority boundary that wasn't reached; an absent step is information, never erased.

This is deliberately **one shape, reused**, not a general diagramming primitive, exactly the brief's own instruction ("without turning every page into a flowchart").

## 10. Trusted Integration visual language

The three-question model (Agent / Trusted Adapter / PayReality) is rendered as an `AuthorityChain` on Decision Detail, with the middle node's icon (`Radio`, chosen for "reporting," not a network/security glyph) shown `inactive` for an agent-direct decision: the same component, the same visual grammar, communicating "this step didn't happen" without a second design language. Integration Detail uses the identical component for System → Trusted Connection → Action Mapping → Allowed Agents → PayReality. No network-security-diagram styling (no padlocks-and-firewalls imagery, no directional data-flow arrows beyond the chain's own plain connector) anywhere.

## 11. Iconography

Library: `lucide-react` (already the sole icon dependency, confirmed; no second library exists or is needed).

**Rule, replacing the three inconsistent conventions this audit found:**
- An icon appears **decoratively on a heading** only for a page's own top-level identity (kept, e.g. Overview's hero), not on every section subheading.
- An icon appears **inline with an action label** only when it reinforces the verb (`Plus` plus "Register agent"), never purely decorative.
- An icon appears **semantically** (status, empty state, chain node) as the primary carrier of meaning: this is the new, expanded category this milestone adds real components for (`StatusBadge`, `DecisionOutcomeBadge`, `EmptyState`, `AuthorityChain`).
- The same concept gets the same icon everywhere it appears (Agent = `Bot`, Action = `FlaskConical`, Authority = `ShieldCheck`, Evidence = `FileCheck`/`Lock`, System = `Building2`, Trusted Adapter/Connection = `Radio`): recognizability through repetition, per the brief.

## 12. Motion

Unchanged: the existing three-step scale (`--pr-motion-fast/base/slow` plus one named ease) already satisfies "restrained motion, not cinematic." `.pr-enter` (staggered fade with a 4px rise) is the one entrance pattern; nothing in V3 adds a second. Reduced-motion is already handled globally (`theme.css`'s `@media (prefers-reduced-motion: reduce)` block, confirmed `!important` so it wins over any component-level transition) and needs no change.

## 13. Responsive rules

Not newly designed this milestone (no production page was touched), but stated as the rule for Product V3 to follow: desktop-first (enterprise software, per the brief), with the existing sidebar → Radix `Sheet` drawer pattern (already built, `Layout.tsx`) as the mobile nav mechanism. New guidance for the components this milestone adds: `Table` truncates rather than wraps by default (§9's data-density need); `AuthorityChain` wraps to multiple rows rather than horizontally scrolling; `PageHeader`'s action row wraps below the title on narrow viewports (`flex-wrap` already built in).

## 14. Accessibility

No regression introduced: every new component reuses the existing focus-visible mechanism (nothing here adds a custom, non-standard interactive element that would need its own keyboard handling; `PageHeader`'s breadcrumbs are plain `Link`s, `EmptyState`'s action is caller-supplied). Status is never color-only anywhere in the new components (§6). `AgentIdentity`'s initials mark is `aria-hidden` (decorative; the real name is always adjacent text). Contrast: every new token is a `color-mix()` derived from already-shipped, already-reviewed tokens, not a new hex value introduced without a contrast check.

## 15. Product vs. Demo vs. Website

Unchanged principle, restated for the next three milestones to build against:

- **Product**: most restrained. Every component in §7 as specified, no extra motion, no extra color, dense tables by default.
- **Demo**: identical component set, guided emphasis layered on top (the existing `TourOverlay` spotlight mechanism, unchanged), never a second visual language.
- **Website**: most expressive. The one place the reserved `--pr-logo-gradient-end` gradient and larger display typography belong. Still built from the same tokens (`--pr-authority-blue`, the same status colors, the same `AgentIdentity`/`AuthorityChain` shapes reused as conceptual diagrams) so a visitor moving Website → Demo → Product recognizes the same system at increasing density, per the brief's own cross-surface-continuity goal.

## 16. Design tokens reference

All new tokens live in `src/styles/theme.css`, in the existing `:root` block, following the file's own established comment convention. No new token file, no Tailwind config change (this codebase's Tailwind v4 setup is CSS-first with no `tailwind.config.*`), centralized through the existing architecture exactly as instructed. See §3/§9 above for the full list.
