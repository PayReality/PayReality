# User Journey Review

Two parts: a workflow-by-workflow review of the eight named surfaces against what Milestones 1-7 actually shipped, and a set of role-specific dashboard journeys (Phase 9's "Executive dashboards" requirement) built from the platform's own real RBAC roles, not invented personas unrelated to how access actually works.

## Part 1: Workflow review

**Authority Builder**: the real workflow, upload a corpus, review principals/resources/operations/relationships/conflicts/gaps/questions each with a citation and stated confidence, promote a candidate to a draft policy, matches the shipped, Azure-AI-Foundry-backed pipeline exactly (Milestone 6). No change needed to the workflow itself; still makes sense.

**Policy Builder** (the single-document pipeline): still functional, still makes sense as a *mechanism*, but no longer makes sense as a *separate, user-facing workflow* now that Authority Builder covers the same case with richer output and the same underlying AI provider. See `INFORMATION_ARCHITECTURE_V2.md`'s retirement recommendation; this review agrees with it for the same reason, evidenced independently by walking the actual user path rather than only the code structure.

**Evidence**: the workflow (list, inspect, independently verify) matches the real, signed, hash-chained model exactly. Still makes sense unchanged; only the "Evidence Vault" naming artifact needs fixing (Navigation Redesign).

**Simulator**: the workflow (pick a policy, run a hypothetical Intent, optionally save it as a Test Scenario, optionally run a CSV batch) matches the real, Milestone-6-fixed feature exactly. Still makes sense; its only problem is discoverability, not its own internal design (Navigation Redesign addresses this).

**Approvals**: the review-queue workflow matches the real policy lifecycle (submitted for review, awaiting approval) exactly. Still makes sense; same discoverability gap as the Simulator.

**Organizations**: the lifecycle workflow (create, invite, deactivate, reactivate, archive) matches the real, tested Organization Lifecycle exactly (Milestone 3, live-validated again in Milestone 5). Still makes sense unchanged.

**Members**: role invitation and assignment matches the real six-role RBAC model exactly. Still makes sense unchanged; the one open question (not a defect, a genuine open item) is whether the UI visibly reflects a user's own permission boundaries before they attempt an action they lack rights for, flagged in the Dashboard UX Review as worth a dedicated follow-up audit.

**Runtime Policies**: the manual-authoring and versioning workflow (draft, submit for review, approve, activate, deprecate, archive, roll back) matches the real, shipped lifecycle exactly, including the real bundle-hash-producing compile/deploy step. Still makes sense unchanged; only the "Rule" naming artifact needs fixing.

**Overall conclusion for Part 1**: every one of the eight named workflows still makes sense after Milestones 1-7, with exactly one exception (Policy Builder as an independent surface) and a small set of naming/discoverability fixes, not a workflow-level redesign. This matches the Dashboard UX Review's own overall finding: the platform's screens have been kept in closer sync with its own growth than this milestone's premise assumed.

## Part 2: Dashboards by role

Built directly from the platform's real, shipped roles (Owner, Governance Administrator, Agent Administrator, Reviewer, Auditor, Executive), not from generic personas the access model doesn't actually support. Every item below is PROPOSED; none of these role-specific views exist yet as distinct dashboards, though the underlying data for each already exists somewhere in the current screens.

**Executive** (maps to the real `executive` role, `assurance.view` only): a single, simple view built from `LiveAssurance.tsx`'s existing data, real agent/policy counts, decision outcome distribution, nothing operational. This role already can't see anything beyond Assurance today; a dedicated executive dashboard is a presentation layer over data access that already exists, not a new permission to design.

**Security** (maps most closely to `auditor`, evidence/decisions/policy view-only): a view centered on Evidence chain integrity, signing-key status, and any HUMAN_REVIEW decisions awaiting resolution, since these are the specific things a security stakeholder checks that an executive doesn't need to.

**Compliance**: overlaps heavily with Security but adds the Authority Graph's own conflicts/gaps view (Authority Intelligence's explicit uncertainty disclosure) as first-class content, since a compliance reviewer's core question is "what does our own documented authority structure actually say, and where does the model admit it isn't sure," not just "did evidence verify."

**Platform Admin** (maps to `owner`): effectively the current Organisation Settings' full ten-tab surface, already comprehensive; the platform-admin-only Organization Lifecycle screen already exists as a separate, correctly-gated page (`PlatformOrganizationsPage.tsx`).

**Operations** (maps to `agent_admin`): a view centered on Agent lifecycle status and health, not policy content, matching that role's actual permission scope exactly.

**Developers**: per the Information Architecture review's own finding, this role has no dedicated in-dashboard page at all today (only external markdown docs); a lightweight developer view (recent Intent submissions, signature failures, a link out to the SDK docs and the live OpenAPI reference) would be new, additive surface area, not a reorganization of anything existing.

**Auditors** (maps directly to the real `auditor` role): view-only across Evidence, Decisions, Runtime Policies, and Agents, exactly matching that role's actual permission grant; this dashboard is closer to "the existing screens, with every mutating action hidden" than a new design.

**What this section deliberately does not do**: invent a permission model to match a generic enterprise-dashboard checklist. Every role above maps to a role that already exists in the shipped RBAC system; none of this requires a new grant or a backend change, which is exactly why it's appropriate for a documentation-and-planning milestone that explicitly rules out new backend feature work.
