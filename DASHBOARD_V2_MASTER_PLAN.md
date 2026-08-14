# Dashboard V2 Master Plan

Ties together `DASHBOARD_UX_V2_REVIEW.md`, `INFORMATION_ARCHITECTURE_V2.md`, `NAVIGATION_REDESIGN.md`, `USER_JOURNEY_REVIEW.md`, and `DESIGN_SYSTEM_REVIEW.md` into one prioritized plan. Nothing in this plan has been implemented; per this milestone's own rule, Phase 9 is documentation and planning only.

## The headline finding across all five documents

The dashboard was audited screen by screen against everything Milestones 1-7 actually shipped, on the explicit premise (stated in this milestone's own prompt) that it was "built before" most of the platform's real current capability and needed a workflow redesign. **That premise did not hold up.** Every one of the eight named workflows still makes sense; the current flat, workflow-ordered navigation reflects a real, already-executed, correctly-reasoned prior simplification, not a legacy structure. What the audit actually found is narrower and more useful: a handful of concrete, specific, independently fixable problems, not a system in need of rebuilding.

## Prioritized plan

**Tier 1, do first (small, high-value, low-risk content/copy fixes)**:
1. Correct `OrganisationSettingsPage.tsx`'s stale "no Azure/Bedrock integration" sentence.
2. Fix the "Evidence Vault" and "Rule" naming artifacts.
3. Resolve the `theme.css`/`theme.ts` default-mode comment contradiction.
4. Standardize loading states on the existing `SkeletonRows` pattern everywhere it's currently missing (`PlatformOverview.tsx`, `CorpusUploadPage.tsx`'s history table).

**Tier 2, do next (a real, scoped navigation change)**:
5. Add sub-navigation to Governance only, per `NAVIGATION_REDESIGN.md`'s exact spec (Policies, Authority Builder, Approvals, Simulator), leaving all six other top-level items untouched.
6. Decide, explicitly, on the single-document AI Policy Builder's retirement, and if confirmed, redirect its two routes to Authority Builder rather than leaving an orphaned, code-coupled surface live.

**Tier 3, do once a first pilot customer's real usage can inform it further**:
7. Build the role-specific dashboard views in `USER_JOURNEY_REVIEW.md`'s Part 2 (Executive, Security, Compliance, Platform Admin, Operations, Developers, Auditors); these are additive presentation layers over data that already exists, not urgent for a first pilot's Deployment stage, and better designed after watching which role actually asks for which view first.
8. Add a lightweight Developer surface linking out to the SDK documentation, closing the one genuinely missing surface this audit found (not a redesign of anything existing).
9. A dedicated follow-up audit (flagged, not resolved, by the Dashboard UX Review) on whether the UI visibly reflects a user's own RBAC permission boundaries before they attempt a disallowed action, versus only after the backend rejects it.

## What this plan explicitly does not include, and why

The department-shaped, deeply-nested hierarchy sketched as an example in this milestone's own prompt (Authority / Authority Intelligence / Simulation / Evidence / Operations / Platform / Administration). Every one of this plan's five supporting documents independently arrived at the same conclusion from a different angle (the audit, the IA model, the navigation spec, the workflow review, the design system review): that structure would undo a correct, already-shipped decision to organize navigation by workflow rather than by department, for no evidenced benefit and at real cost to the five screens (Agents, Decisions, Evidence, Assurance, Organisation Settings) that don't need it. Where real complexity does exist, Governance, this plan adds real structure. Nowhere else does it, because nowhere else the audit checked needed it.

## Sequencing relative to Milestone 8's other work

Tier 1 and Tier 2 are small enough to execute alongside the first pilot's own Deployment stage (`PILOT_PROGRAM_GUIDE.md`), not before it; none of them block a pilot from starting today. Tier 3 should follow real pilot usage, consistent with this milestone's own closing note that the roadmap now shifts from internal assumptions toward real enterprise deployment feedback.
