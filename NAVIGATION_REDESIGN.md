# Navigation Redesign

The concrete sidebar specification implementing `INFORMATION_ARCHITECTURE_V2.md`'s recommendation. PROPOSED throughout; not implemented in this milestone, per its own rule against redesigning the product.

## Current sidebar (VERIFIED, `Layout.tsx`)

```
Overview
Agents
Governance
Decisions
Evidence
Assurance
Organisation Settings
```

Flat, no expansion, no sub-items rendered anywhere in the sidebar itself.

## Proposed sidebar

```
Overview
Agents
Governance              (expandable)
  Policies
  Authority Builder
  Approvals
  Simulator
Decisions
Evidence
Assurance
Organisation Settings
```

**Six of the seven top-level items are completely unchanged.** Only Governance gains an expansion, and only because it is the one item the Dashboard UX Review found actually needs one. This is a minimal, targeted change, not a rebuild of the navigation component.

## Interaction detail

**PROPOSED**: Governance expands in place (an accordion-style disclosure within the sidebar), matching the existing sidebar's own visual language rather than introducing a flyout menu or a second navigation level with different styling. Clicking "Governance" itself (not a chevron) should navigate to the Policies list, exactly as it does today, so a user who doesn't care about the new sub-structure loses nothing; the sub-items are additive, not a new required step.

## Naming changes bundled into this redesign (from the Dashboard UX Review's Section 4)

- The manual-authoring page's title changes from "New Rule" to "New Runtime Policy," matching the term used everywhere else in the product and in external messaging.
- `LiveEvidence.tsx`'s on-page kicker text changes from "Evidence Vault" to "Evidence," matching the nav label and route that were already renamed in the prior simplification pass.
- Internal error copy in `policy-studio/` referencing "the Policy Studio backend" changes to "the Governance backend" or a more specific, feature-accurate message, since "Policy Studio" is a pre-rename name that should not still appear anywhere user-visible, even in an error state.

## What happens to the single-document AI Policy Builder

Per `INFORMATION_ARCHITECTURE_V2.md`'s retirement recommendation: it does not appear in the proposed sidebar at all, expanded or otherwise. Its two routes (`/governance/upload`, `/governance/upload/:uploadId`) should redirect to Authority Builder once that pipeline is confirmed to handle the single-document case identically, the same pattern the codebase already uses for its other retired routes (a redirect, not a hard 404, so no old bookmark or link breaks silently).

## Mobile

No change beyond what the expansion itself requires: the existing `Sheet` drawer (already used below the 768px breakpoint) should render the same expandable Governance group inline, using whatever disclosure pattern is chosen for desktop, rather than a separate mobile-specific navigation structure.

## What this redesign explicitly rejects, and why

- **A generic top-level "Platform" or "Operations" group** (as sketched in this milestone's own example hierarchy): would relocate Organisation Settings, Agents, or Evidence into a parent category none of them need, undoing a correct prior decision for no evidenced benefit.
- **A separate top-level "Simulation" item**: the Simulator is a step inside the policy lifecycle, not an independent workflow; nesting it under Governance (where the user is already looking at the specific policy they want to test) matches how the feature is actually used today, confirmed directly by reading `SimulationPage.tsx`'s own routing (`/governance/:policyKey/simulate`, always entered from a specific policy, never as a standalone destination).
- **A separate top-level "Authority Intelligence" item** distinct from Governance: Authority Builder's entire purpose is to produce Governance's own input (candidate Runtime Policies); splitting it into a separate top-level concept would separate a workflow step from the workflow it feeds, the exact fragmentation the current design correctly avoids elsewhere.
