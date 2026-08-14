# Dashboard UX V2 Review

**Framing, stated plainly up front, the same way `WEBSITE_V2_MASTER_PLAN.md` framed the website**: this is not a rebuild either. A prior UX simplification pass already happened (referenced directly in `Layout.tsx`'s own code comments as "the product simplification review") and already replaced an earlier, more fragmented navigation with the current flat, seven-item, single-workflow sidebar (Overview, Agents, Governance, Decisions, Evidence, Assurance, Organisation Settings). That decision is sound and explicitly, deliberately rejects "department-shaped groups." The Phase 9 hierarchy example in this milestone's own prompt (Authority, Authority Intelligence, Simulation, Evidence, Operations, Platform, Administration, each with sub-items) is exactly the department-shaped, deeply-nested structure that prior review already considered and rejected. This review does not recommend adopting it. What it recommends instead is narrower and better evidenced: fix the specific, real gaps a direct audit of every screen actually found, which are not "the whole IA is legacy," but a handful of concrete, fixable problems.

Every finding below comes from a direct, file-level read of `src/app/routes.tsx`, `src/app/components/Layout.tsx`, and the individual page components, not from assuming staleness because the platform has grown. VERIFIED means read directly in code; INFERRED means a reasonable conclusion; PROPOSED means a recommendation.

## 1. Screen-by-screen: does each still reflect the real product?

**Yes, for every screen reviewed.** VERIFIED: `PlatformOverview.tsx` already frames itself as "Enterprise AI Authority Infrastructure" and "one workflow, not a dashboard"; `AgentDirectoryPage.tsx` already reflects the real Agent lifecycle (registered/active/suspended/revoked/retired) including the two-step registration/activation distinction; `RuntimePolicyDashboardPage.tsx` already reflects the real policy lifecycle (pending approvals, scheduled changes, recently activated, deprecated, rollback history); `CorpusReviewPage.tsx` already reflects the real, full Authority Graph extraction output (principals, resources, operations, relationships, conflicts, gaps, questions); `OrganizationSettingsPage.tsx` already has real RBAC, API key management, and organization-lifecycle actions. No screen was found describing a materially earlier version of the product's own concepts. The platform's growth has been kept in sync with its own dashboard more successfully than this milestone's own premise assumed.

**The one real exception**: one static sentence on `OrganizationSettingsPage.tsx` ("Azure OpenAI and AWS Bedrock have no integration built yet, shown honestly") is stale, since Azure AI Foundry integration is real and live as of Milestone 6. This is a one-line content fix, not a screen redesign; see the Design System Review for the specific correction.

## 2. Navigation and Information Architecture

Current state (VERIFIED, `Layout.tsx`): a flat, single-section sidebar, seven items, in workflow order (Overview, Agents, Governance, Decisions, Evidence, Assurance, Organisation Settings), no sub-nav rendered in the sidebar at all. See `NAVIGATION_REDESIGN.md` and `INFORMATION_ARCHITECTURE_V2.md` for the specific, narrow change this review recommends: the flat top level stays exactly as it is; **Governance** specifically needs internal sub-navigation, since it alone now contains manual policy authoring, two separate document-extraction builders, a dashboard/search view, an approvals queue, and the Simulator, all reachable today only via in-page links after landing on `/governance`, with zero of that structure visible from the sidebar.

## 3. User journeys and workflows

Reviewed against the platform's real, current lifecycles (per Milestones 1-7):

- **Authority Builder / Policy Builder**: the workflow (upload documents, review extracted candidates with citations and confidence, promote to a draft Runtime Policy, then the same review/approve/activate lifecycle every policy uses) matches the real backend exactly. **The one real structural problem**: the single-document AI Policy Builder (`/governance/upload`) is fully functional but has zero inbound links from anywhere in the current IA (confirmed via a direct grep for links to that route); it is reachable only by a direct URL. It shares UI components directly with the Authority Builder it was superseded by (`CorpusReviewPage.tsx` imports `CandidateCard`/`ConfidenceBadge` straight from the `ai-policy-builder/` directory), meaning the two are already code-coupled even though only one is meant to be the primary path. This needs an explicit decision (see Navigation Redesign), not a further audit.
- **Evidence**: matches the real signed-record-plus-verification model; the one naming artifact is the page's own on-page kicker text still reading "Evidence Vault" (a pre-simplification name) even though the nav/route were already renamed to plain "Evidence."
- **Simulator**: `/governance/:policyKey/simulate` already covers the real, current feature set (single simulation, saved Test Scenarios, Batch CSV simulation) in one page, correctly reflecting the Milestone 6 fix and the feature's actual current shape. No structural change needed; only its discoverability suffers from being three clicks deep with no direct sidebar entry (see Navigation Redesign).
- **Approvals**: `/governance/approvals` correctly reflects the real review-queue concept; it just isn't visible from the sidebar today, only from within `/governance`.
- **Organizations / Members**: `OrganizationSettingsPage.tsx`'s ten tabs (General, Organisation Structure, Security, Runtime Authority, Integrations, Enterprise Systems, Notifications, Audit, Organisation Health, About) correctly reflect the real, current organization model including RBAC, but ten tabs on one page, each fetching independently with no unified loading treatment, is a real usability gap worth naming even though it isn't a structural/IA problem (see Design System Review).
- **Runtime Policies**: the manual-authoring path (`/governance/new`) still calls a new policy a "Rule" in its own page title, while everywhere else in the product (backend, other pages, external messaging) the term is "Runtime Policy." A small, real naming inconsistency, not a workflow problem.

## 4. Naming

A consolidated list of every inconsistency actually found, not a general call for consistency:

| Concept | Names currently used, verbatim | Where |
|---|---|---|
| The policy-authoring feature | "Governance" (nav, route), "Policy Studio" (directory name `policy-studio/`, internal error copy: "Could not reach the Policy Studio backend"), "Rule" (new-policy page title) | `Layout.tsx`, `policy-studio/*` |
| The signed-record feature | "Evidence" (nav, route), "Evidence Vault" (on-page kicker text, and the name of an old, now-redirected URL) | `LiveEvidence.tsx` |

**PROPOSED**: standardize on "Governance" and "Runtime Policy"/"policy" externally (already the nav-level and messaging-level terms), and "Evidence" without "Vault." Both are small, mechanical text changes, not a rename of any route or backend concept.

## 5. Empty states, loading states, search, tables, forms

Inconsistent, but not absent, which is an important distinction. `AgentDirectoryPage.tsx`, `RuntimePolicyDashboardPage.tsx`, and `CorpusReviewPage.tsx` all have real, considered skeleton-loading and empty-state copy (e.g. "Nothing waiting on review," "No rules were found in this corpus"). `PlatformOverview.tsx` has no loading skeleton at all, rendering literal placeholder text ("N/A"/"None") until data resolves rather than a skeleton, a real, visible flash worth fixing. `CorpusUploadPage.tsx`'s "past corpora" table renders nothing at all while loading (not even a spinner), unlike every comparable table elsewhere in the product. **PROPOSED**: adopt the `SkeletonRows` pattern already used successfully in three places as the one standard for every data table and status strip in the product, rather than introducing a new pattern.

## 6. Permissions and multi-tenancy in the UI

VERIFIED: RBAC (six roles) is real on the backend; this review did not find evidence the frontend consistently reflects a user's own role by hiding or disabling actions they lack permission for, versus relying on the backend to reject the request after the fact. **PROPOSED, worth a follow-up audit specifically on this point before Dashboard V2 ships**: confirm whether a Reviewer, for instance, sees a disabled "Activate" button with an explanation, or sees the same button as a Governance Admin and only learns they lack permission after clicking it and receiving an error. The latter is a real usability gap for exactly the enterprise pilot audience this milestone is preparing for.

## 7. Mobile and accessibility

**Mobile**: real, working (a `Sheet` drawer replaces the fixed sidebar under 768px), but the 768px breakpoint is defined once in JS (`use-mobile.ts`) and not coordinated with the ad-hoc Tailwind `sm:`/`md:`/`lg:` breakpoints used in roughly a dozen form-layout spots elsewhere, a latent inconsistency risk rather than a currently-visible bug.

**Accessibility**: a genuine, deliberate strength, not a gap. A real skip-link, a universal `:focus-visible` ring cited to WCAG 2.4.7, a hand-built modal with a real focus trap and Escape-to-close cited to the WAI-ARIA APG pattern, 62 `aria-*` usages, and `prefers-reduced-motion` respected for loading animations. An existing `ACCESSIBILITY_REPORT.md` documents a prior, deliberate accessibility pass. **PROPOSED**: Dashboard V2 should preserve and extend this baseline explicitly, and review that report's own stated "what this pass does not claim" section before assuming full coverage.

## 8. A real, small, currently-contradictory design-token bug

`src/styles/theme.css`'s own comment states dark is the platform default; `src/app/lib/theme.ts`'s own comment states light is the platform default; in practice, light wins, since the JS sets `data-theme="light"` before first paint. Both comments cannot be right at once; this is a documentation trap for the next person who touches either file, not a visible user-facing bug today, and should be resolved as part of the Design System Review's own cleanup, not left for someone to rediscover by trial and error.

## 9. Pilot UX: can an enterprise customer arrive tomorrow and do this without training?

Walking through the platform's real, current screens for each named task:

- **Understand the platform?** Yes: `PlatformOverview.tsx`'s "one workflow, not a dashboard" framing and the sidebar's own left-to-right ordering (Agents, Governance, Decisions, Evidence, Assurance) already teach the mental model on first load.
- **Configure it?** Yes, via `OrganizationSettingsPage.tsx`, though the ten-tab, independently-loading structure (Section 3) means a first-time admin has no single "you're done setting up" signal.
- **Upload documents?** Yes, via Authority Builder, with real, considered empty/loading states.
- **Build authority?** Yes, the Authority Graph review flow (principals, relationships, conflicts, gaps, questions, each cited) is genuinely one of the platform's best-designed screens for a first-time user, since the citations and stated confidence do real explanatory work without needing separate documentation.
- **Test policies?** Yes, mechanically, via the Simulator, but **only if the user already knows it exists**, since it has no sidebar-level presence today (Section 2's finding). A first-time user following only the sidebar would not discover it without already knowing to look inside a specific policy's own workspace.
- **Approve policies?** Same finding as above: real, working, but discoverable only from inside `/governance`, not from the sidebar.
- **Deploy policies?** Yes, the activate action and its resulting bundle hash are real and visible.
- **Investigate evidence?** Yes, `LiveEvidence.tsx`'s verify action is real, working, and a genuinely strong, literal answer to "prove this decision was really made this way."

**Overall verdict**: a first-time enterprise user can complete every task in this list without training, with one real caveat: two of the platform's most differentiated capabilities, the Simulator and the Approvals queue, are functionally excellent but not discoverable from the sidebar alone, the single concrete, well-evidenced problem this whole review keeps returning to, and the one this review's companion documents (Navigation Redesign, Information Architecture V2) are built specifically to fix.
