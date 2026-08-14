# Design System Review

## What already exists and is working (VERIFIED)

`src/styles/theme.css` is a real, actively-used, single source of truth: CSS custom properties for background layers, brand/semantic colors (`--pr-authority-blue`, `--pr-evidence-cyan`, `--pr-trust-green`, `--pr-warning-amber`, `--pr-critical-red`, `--pr-verification-purple`), a text-color scale, translucent overlay tokens, a shared type scale (h1-h4, label, button, input), a universal focus-visible ring, a skip-link, a skeleton-pulse loading animation that respects `prefers-reduced-motion`, and a print stylesheet. A prior, unused shadcn/ui OKLCH theme (`default_shadcn_theme.css`) was already confirmed dead and removed, a genuine, verified cleanup, not a guess. Dark mode is real and working (`lib/theme.ts`, persisted to `localStorage`, applied pre-paint to avoid a flash). Mobile responsiveness is real and working (a single 768px breakpoint driving a sidebar-to-drawer swap). Accessibility is a deliberate, documented strength (see the Dashboard UX Review's own Section 7), not a gap this review needs to open.

**This design system does not need replacing.** Its own naming convention (a `--pr-` prefix, semantic rather than purely visual token names) is sound, and the decision to consume tokens via inline styles rather than a large custom Tailwind theme extension was a real, considered tradeoff (documented in the codebase's own comments), not an oversight.

## Real, specific problems found

1. **A genuine, self-contradictory default-theme bug.** `theme.css`'s own comment states dark mode is the platform default; `lib/theme.ts`'s own comment states light mode is the platform default. In practice, light wins, since the JS sets `data-theme="light"` before first paint. **PROPOSED fix**: pick one (light, matching actual current behavior, is the simpler fix since it requires no behavior change, only correcting the stale comment in `theme.css`), and update whichever file's comment is wrong, so the next person to touch either file doesn't have to rediscover this by testing rather than reading.

2. **Inconsistent loading-state coverage.** Three screens (`AgentDirectoryPage.tsx`, `RuntimePolicyDashboardPage.tsx`, `CorpusReviewPage.tsx`) use a real `SkeletonRows` pattern; `PlatformOverview.tsx` shows literal placeholder text ("N/A", "None") instead of a skeleton while its first fetch resolves; `CorpusUploadPage.tsx`'s history table renders nothing at all during its own load. **PROPOSED**: standardize on the existing `SkeletonRows` component everywhere data loads, rather than introducing a new pattern; this is consolidation, not new design work.

3. **`OrganisationSettingsPage.tsx`'s ten tabs each load independently with no unified loading treatment**, and one contains stale content: "Azure OpenAI and AWS Bedrock have no integration built yet, shown honestly," no longer true since Azure AI Foundry integration is real and live (Milestone 6). **PROPOSED fix, both together**: correct the stale sentence to reflect the real, current Azure AI Foundry integration, and while editing that section, add a single top-of-page loading indicator that resolves once all ten tabs' initial data has loaded, rather than each tab flashing independently.

4. **Two design-system-relevant naming inconsistencies**, already named in the User Journey and Navigation Redesign documents, repeated here because they are also, specifically, a content/design-system consistency issue: "Evidence Vault" (on-page kicker) versus "Evidence" (nav/route), and "Rule" (page title) versus "Runtime Policy" (everywhere else).

5. **No coordination between the JS mobile breakpoint (768px) and the ad-hoc Tailwind breakpoint utilities (`sm:`, `md:`, `lg:`) used in roughly a dozen form-layout spots.** Not currently visibly broken, but a latent risk: a future change to one without the other could produce a layout that looks fine on the sidebar/drawer switch but breaks on a form nearby. **PROPOSED**: define the 768px value once, in a location both the JS breakpoint hook and any future Tailwind customization can reference, rather than two independently-maintained numbers that happen to agree today.

## Typography, spacing, cards, tables, charts, status colors: no material findings

Nothing in this review's pass through the codebase surfaced a real typography, spacing, card, table, or chart-specific inconsistency beyond the loading-state coverage gap already named in item 2. Status colors (the semantic `--pr-trust-green`/`--pr-warning-amber`/`--pr-critical-red` tokens) are used consistently everywhere this review checked. This is a genuinely well-maintained design system; the fixes above are small and specific, not evidence of broader neglect.

## What this review does not propose

A new component library, a new token naming scheme, or a visual redesign of any kind. Every finding above is a correction to something already built correctly in principle but drifted in one specific place, consistent with this milestone's own instruction that Phase 9 is "not a visual redesign."
