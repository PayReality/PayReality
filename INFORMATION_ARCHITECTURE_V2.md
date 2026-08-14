# Information Architecture V2

The conceptual model behind `NAVIGATION_REDESIGN.md`'s concrete sidebar spec. Per `DASHBOARD_UX_V2_REVIEW.md`'s own finding, the current flat, workflow-ordered top level (Overview, Agents, Governance, Decisions, Evidence, Assurance, Organisation Settings) is sound and already reflects a deliberate, correct prior decision to reject department-shaped grouping. This document does not replace that model; it specifies exactly where it needs one more level of structure, and nowhere else.

## The organizing principle, stated explicitly (carried forward from the existing design, not invented here)

Navigation should follow the order a user actually acts in, not the org chart of departments that might use the product. This is the same principle `Layout.tsx`'s own code comment already states ("One workflow, in order... No department-shaped groups"). This document's only addition is: **a single workflow step can itself contain more than one screen, and when it does, that structure should be visible, not hidden behind in-page links.**

## Where the current model is complete as-is

Agents, Decisions, Evidence, Assurance, and Organisation Settings are each a single, coherent surface; none of them need internal sub-navigation, and none of this review's findings suggest otherwise.

## Where the current model needs one more level

**Governance** is the one place in the product where a single top-level item now represents five materially different activities: writing a policy manually, extracting policy candidates from a single document (the orphaned AI Policy Builder), extracting a full Authority Graph from a multi-document corpus, reviewing/approving pending changes, and simulating a policy before activation. Per the Dashboard UX Review, none of this is visible from the sidebar today; all of it is reached only after landing on `/governance` and using in-page links.

**PROPOSED information architecture for Governance specifically** (not a department tree for the whole product, a sub-structure for this one area only):

```
Governance
  Policies            (the existing policy list/dashboard, /governance)
  Authority Builder   (multi-document corpus extraction, the primary path)
  Approvals           (the review queue)
  Simulator           (policy simulation, currently three clicks deep)
```

**The single-document AI Policy Builder does not get its own sidebar entry in this proposal.** Per the Dashboard UX Review's own finding (zero inbound links today, already code-coupled with Authority Builder, explicitly described in the codebase's own comments as superseded), this document recommends **retiring it as a separate surface**, not giving it more visibility. See the Retirement Recommendation below.

## Retirement recommendation: the single-document AI Policy Builder

**PROPOSED, not executed by this milestone** (per this milestone's own rule against redesigning the product): retire `/governance/upload` and `/governance/upload/:uploadId` as user-facing surfaces once Authority Builder is confirmed to fully cover the single-document case (a corpus of one document is already a valid Authority Builder corpus; nothing about that pipeline requires more than one document). This mirrors, at the frontend layer, the same consolidation direction `AI_PIPELINE_CONSOLIDATION_REVIEW.md` already recommended at the backend layer in Milestone 6 (both pipelines already produce the same `CandidateRuntimePolicy` shape and now share the same canonical Azure AI Foundry provider). Retiring the frontend surface without also retiring the backend route would be half a decision; this document flags both halves together so a future milestone doesn't do one without the other.

## SDK / developer surface: a real gap, not a naming issue

Per the Dashboard UX Review: extensive SDK documentation exists as markdown files (`SDK_QUICKSTART.md`, `SDK_REFERENCE.md`, and others) but has no corresponding page anywhere in the actual dashboard. **PROPOSED**: this is not urgent enough to add a new top-level sidebar item (that would reintroduce exactly the kind of item-for-every-concept sprawl the prior simplification review correctly avoided), but a link from Organisation Settings' existing "Integrations" tab or a footer/help-menu entry pointing to the SDK documentation would close a real, currently-silent gap for a pilot customer's own developer, without adding sidebar weight.

## What this document deliberately does not propose

It does not propose the eight-group, department-shaped hierarchy sketched as an example in this milestone's own prompt (Authority / Authority Intelligence / Simulation / Evidence / Operations / Platform / Administration, each with three or four sub-items). That structure would fragment single coherent workflows (Evidence, Assurance, Agents) into artificial parent/child relationships they don't currently need, contradicting the one clear, already-correct design principle this whole product's navigation is built on. The one place real complexity actually exists (Governance) gets real structure; nowhere else does, because nowhere else needs it.
