# Milestone 15: Remediation Plan

Everything in this milestone's scope that was fixed and deployed is listed here for completeness, but
the real purpose of this document is the second half: what's left, ordered the way this engagement has
consistently prioritized fixes -- security, then data integrity/tenant isolation, then auth/RBAC, then
broken core workflows, then cross-page state, then API contract, then loading/error handling, then UX,
then cosmetic.

## Closed this milestone (for reference, not re-litigated here)

1. **[Security]** Six route groups with zero permission gate (`runtime-policies` reads + dry-run, agent
   detail/certificates/audit, most AI Authority/Policy Builder reads, runtime-policy-lifecycle views) --
   fixed, deployed, live-verified before/after with real sessions.
2. **[Security, process]** Added a generic regression test closing the entire bug class (route-table
   introspection vs. a reviewed allowlist), not just the six specific instances found.
3. **[Security]** Blob/Search tenant-isolation defense-in-depth (centralized filter + independent
   scope-check on every result) -- fixed, deployed, regression-tested.
4. **[Auth/RBAC, UX]** Sidebar navigation now filtered by real permissions instead of showing every item
   to every role.
5. **[Broken workflow]** `AgentDirectoryPage.tsx`'s unhandled-fetch-rejection bug (same class as
   Milestone 14's `AgentDetailPage.tsx` fix, different file).
6. **[UX]** Table overflow fixes on two pages; create-principal error handling and busy state.

## Remaining, in priority order

### Priority: Auth/RBAC clarity (small, high-value)
- **`owner`-session rejection from platform-admin-only endpoints returns `422` instead of `401`.** The
  security property already holds (a session token cannot bypass the Operator-Key-only gate), confirmed
  live; this is a pure API-consistency cleanup (`verify_operator_key`'s `Header(...)` is FastAPI-required,
  so a missing header short-circuits with FastAPI's own validation error before the function body ever
  runs). Low effort, no security benefit, purely cosmetic-for-API-consumers. **P3.**

### Priority: Broken core workflows / cross-page state
- **`OrganizationSettingsPage.tsx` never wired to `useResourceSync`** despite every one of its own
  mutations emitting the signal -- a second open tab (or this tab left idle and returned to) goes stale
  indefinitely on Organisation Settings specifically. **P2.** Smallest correct fix: `useResourceSync(["organization"], load)` where `load` already exists for the initial fetch.
- **`OrganizationSettingsPage.tsx`'s dead `?tab=Organisation+Health` deep link** from its own "About"
  tab -- the page never reads its URL's query string. **P2.** Fix: read `useSearchParams` on mount and
  seed the initial tab state from it, or remove the link if "Organisation Health" isn't a real tab name
  anymore.

### Priority: API contract / stale claims
- **`OrganizationSettingsPage.tsx`'s "About" tab claims "Render + Vercel (Azure staged, not yet live)"**,
  which appears to contradict this engagement's own Milestone 7 DNS cutover history. **P2.** Needs a
  quick confirmation of current infra status (already substantially known from this and prior
  milestones' production checks) and a copy fix -- not a functional change.
- Stale GitHub remote URL in the same tab. **P3.**

### Priority: Loading/error handling
- **Session-timeout and retention-day inputs accept negative values** with only a decorative `min` HTML
  attribute, no real client-side validation, and unverified server-side rejection. **P2** for the
  session-timeout field specifically (security-relevant setting), **P3** for the two retention fields.
- `createApiKey`/`revokeApiKey` still don't emit `notifyResourceChanged("organization")`, inconsistent
  with every sibling mutation in the same file. Currently inert (no page subscribes to this data via
  that signal), but the same inconsistency class Milestone 14 explicitly closed for
  `createEnterpriseSystem`. **P3.**

### Priority: UX consistency
- `UsersPage.tsx`'s invitation-revoke has no confirm step, unlike the page's own "Disable user" flow.
  **P3.**
- `SimulationPage.tsx`: re-selecting an identical CSV filename won't re-trigger `onChange`; an empty
  scenario name silently no-ops with no message. **P3 each.**
- Decision Center test-tool dropdown copy clarification (from `MILESTONE_15_DECISION_CENTER_ARCHITECTURE.md`) -- distinguishing "agents you can test as in this browser" from "all agents in this organization." **P3.**

### Priority: Accessibility (cosmetic-adjacent, low effort)
- Theme toggle buttons missing `aria-pressed`. **P3.**
- Cascade-delete warnings exposed only via hover-only `title` attributes, not reachable by keyboard/most
  screen readers. **P3.**

### Priority: Decision gates awaiting explicit approval (not implementable without sign-off)
- Legacy `documents` table: **APPROVED** to deprecate the dead read endpoint + remove 2 dead frontend
  types (safe, no schema change) -- not yet executed, next available slot. Actual schema migration
  (`DROP TABLE`/`DROP COLUMN`): **DEFERRED** to its own dedicated milestone; not required for Enterprise
  Knowledge.
- Decision Center device-bound-key architecture: **DECIDED** (Option A, keep) -- only the copy
  clarification above remains, already captured in the UX priority group.

### Priority: Test coverage (ongoing, not urgent)
- Component-level regression tests for `AgentDirectoryPage.tsx` and the Layout nav filter would need
  `apiClient` mocking or `@testing-library/react` (not yet installed) -- correctly scoped as its own
  follow-up rather than rushed into this milestone.
- A full page-by-page RBAC sweep (every remaining page × every role, via real sessions) beyond the
  specific endpoints this milestone targeted -- the highest-value targets (agent, policy, AI-builder,
  decisions, evidence, org-admin surfaces) are now covered; less-trafficked surfaces were not
  exhaustively re-probed with real sessions this round.

## What was explicitly not done, and why that's correct

No Enterprise Knowledge functionality was built, extended, or scaffolded. No live external knowledge
retrieval was introduced into any authorization path. No schema migration was executed. No major
architecture change was made to the Decision Center's signing model. Each of these was either out of
this milestone's explicit scope or a decision gate correctly left for explicit approval rather than
executed unilaterally.
