# Milestone 15: Enterprise Readiness Closure -- Audit

Every claim below is labeled **LIVE** (confirmed against the running production system), **FIXED**
(changed and verified by build/test/deploy), **VERIFIED** (confirmed by direct testing or reading, not
inferred), **PLANNED** (a real gap, not yet addressed), **RECOMMENDED** (a proposal awaiting approval),
or **BLOCKED BY ENVIRONMENT** (a verification this session's tooling cannot perform). Nothing here is
marked verified on the strength of a passing build or test suite alone.

## Workstream 1: Real-Session RBAC Verification

**LIVE, VERIFIED**. Full method and results: `MILESTONE_15_RBAC_MATRIX.md`. Summary: a dedicated test
organization and one real user per role (all six roles present in the codebase, not a subset) were
created via the platform Operator Key and real `POST /v1/auth/login` calls against production. This
found a genuine, live, previously-undiscovered authorization bypass:

**Every GET on `/v1/runtime-policies`** (list, single-policy detail, version history, single-version
detail, version diff) **plus its dry-run simulation action had zero permission gate at all.** Live
confirmation: Agent Admin, Reviewer, and (by the same code pattern, confirmed via source and the
Executive boundary tests) Executive could all read and simulate an organization's complete policy
library -- the product's core governance logic -- despite none holding `runtime_policy.view`. A full
route-table sweep (`fastapi.routing` introspection against the real running app, not a route list
typed by hand) found the identical pattern repeated: list/write endpoints correctly gated, sibling
detail/sub-resource GET endpoints not, across:
- `GET /v1/agents/{id}` and its `/certificates`, `/audit`, `/audit/{id}/verify` sub-resources (missing `agent.view`)
- Nearly every AI Authority Builder corpus-read endpoint: corpora list/detail, summary, principals,
  resources, operations, relationships, conflicts, gaps, questions, coverage, missing-information, diff,
  approvals (missing `authority.review`)
- The AI Policy Builder's uploads/candidates read endpoints (missing `authority.review`)
- `runtime-policy-lifecycle`'s dashboard, search, activation-preview, timeline, and schedules views
  (missing `runtime_policy.view`)

**FIXED and LIVE-VERIFIED**: every one of the above now carries the same `require_permission` gate its
list/write sibling already had. Built, deployed to production (`ca-payreality-api-prod-cus--0000010`,
confirmed `Healthy` at 100% traffic), and re-verified with the same real user accounts: every role that
should be denied now receives `403`; every role that should retain access still does. This is a genuine
before/after live comparison (see the matrix document), not a single post-fix assertion.

A small number of routes were confirmed **deliberately** ungated, each independently justified (not
merely "no error was thrown"): `/v1/auth/login`/`logout`/`accept-invitation`/`me` (auth bootstrap or a
different real auth gate), `POST /v1/intents` and `POST /v1/agents/{id}/heartbeat` (gated by
`verify_agent_signature`, a legitimate machine-identity mechanism, not a human role), the evidence
verification-key endpoints (deliberately public by design, per `EVIDENCE_KEY_ROTATION.md`), and the two
AI-builder `/status` endpoints plus `/v1/runtime-policies/vocabulary` (no organization-scoped or
sensitive data returned).

**FIXED**: a new, permanent regression test (`server/tests/unit/test_route_permission_gates.py`)
introspects the real FastAPI route table and fails if any `/v1/` route has neither a permission gate nor
a reviewed, named justification in an explicit allowlist -- closing the entire bug *class* this incident
represents, not just this instance, for every current and future route. This matters because the
existing test convention (calling `require_permission(...)` directly) can prove permission logic is
correct in isolation but can never prove a given route actually attached it -- precisely how this bug
survived 428 previously-passing tests.

**FIXED**: `src/app/components/Layout.tsx`'s sidebar navigation, previously fully static, now filters
each item by the signed-in user's real permissions (same permissive-when-no-session convention every
other gate in this app uses). A real-session check found 5 of 6 roles routinely seeing nav entries that
always dead-ended on a permission-denied page (Agent Admin/Reviewer/Executive seeing Decisions/Evidence/
Organisation Settings; Reviewer/Executive also seeing Agents; Agent Admin/Reviewer/Executive seeing
Governance).

## Workstream 2: Full Product Surface Audit

**VERIFIED**, via full-file reads (not filename-guessing) of every page not already deeply covered in
Milestone 14: `OrganizationSettingsPage.tsx` (all tabs), `UsersPage.tsx`, `ReviewQueuePage.tsx`,
`VersionsPage.tsx`, `PolicyListPage.tsx`, `RuntimePolicyDashboardPage.tsx`, `AgentDirectoryPage.tsx`,
`SimulationPage.tsx`, `NotFound.tsx`, `RouteErrorBoundary.tsx`, `Layout.tsx`/`routes.tsx`. Findings are
itemized in `MILESTONE_15_BUG_REGISTER.md`-equivalent form inside `MILESTONE_15_REMEDIATION_PLAN.md`
(this milestone did not produce a separate numbered bug register file; the remediation plan carries the
same information plus priority ordering, per this milestone's own instruction to fold discovered defects
into a prioritized closure plan rather than a static list).

**FIXED** (this milestone, P1): `AgentDirectoryPage.tsx` had the identical "unhandled fetch rejection ->
permanently stuck loading state" defect Milestone 14 fixed in `AgentDetailPage.tsx`, in a file Milestone
14 did not touch. A Reviewer or Executive (both lacking `agent.view`) hitting the now-correctly-gated
`GET /v1/agents` would see an infinite loading skeleton with no error and no retry. Fixed with the same
pattern: `.catch()` + error state + Retry button, plus a busy state on "Create principal" and a
try/catch around it (previously an unhandled rejection).

**FIXED** (P2): `AgentDirectoryPage.tsx` and `PolicyListPage.tsx` tables had no `overflow-x-auto`
wrapper -- content clipped or forced page-level horizontal scroll on narrow viewports, unlike
`UsersPage.tsx`/`PlatformOrganizationsPage.tsx`, which already wrap their tables correctly.

**PLANNED, not fixed this milestone** (real findings, disclosed rather than hidden, prioritized in
`MILESTONE_15_REMEDIATION_PLAN.md`):
- `OrganizationSettingsPage.tsx` never calls `useResourceSync` despite every one of its own mutations
  emitting `notifyResourceChanged("organization")` -- a second open tab on this exact page goes stale
  indefinitely (P2).
- `OrganizationSettingsPage.tsx`'s "About" tab links to `/organization?tab=Organisation+Health`, but the
  page never reads its own URL's query string -- a dead deep link (P2).
- `OrganizationSettingsPage.tsx`'s "About" tab states "Render + Vercel (Azure staged, not yet live)" --
  contradicted by this engagement's own history (Milestone 7's real DNS cutover put the API live on
  Azure). Worth flagging as potentially misleading to an operator during an incident (P2), though the
  live Azure/Render status itself was not independently re-verified this session beyond what Milestones
  7-14 already established.
- A stale GitHub URL (`AI-Securewatch/Pay-Reality-` vs. the real `PayReality/PayReality` remote) in the
  same tab (P3).
- Session-timeout and retention-day number inputs accept negative values with no client-side validation
  beyond the decorative HTML `min` attribute (P2 for session timeout, P3 for retention fields; whether
  the backend itself rejects these was not independently verified).
- `createApiKey`/`revokeApiKey` in `organization/api.ts` still don't emit `notifyResourceChanged`,
  inconsistent with every sibling mutation in the same file (P3, currently inert -- no page subscribes to
  this data via that kind yet).
- `UsersPage.tsx`'s invitation-revoke has no confirmation step, unlike the same file's "Disable user"
  flow two rows below it (P3).
- Several accessibility gaps: missing `aria-pressed` on theme toggle buttons, a delete-warning exposed
  only via a hover-only `title` attribute (P3 each).
- `SimulationPage.tsx`: a re-selected identical CSV filename won't re-fire `onChange` in most browsers
  (no reset after use); an empty scenario name silently no-ops with no message (P3 each).

**VERIFIED, no defect found**: `ReviewQueuePage.tsx`, `VersionsPage.tsx`, `PolicyListPage.tsx` (beyond
the overflow fix above), and `RuntimePolicyDashboardPage.tsx` all have correct loading/error/empty
states, two-step confirmation on consequential actions, correct `resourceSync` wiring, and
permission-aware disabling with explanatory text -- these are the pages that already followed the
pattern Milestone 14 and this milestone applied elsewhere.

## Workstream 3: Browser Verification

**BLOCKED BY ENVIRONMENT**, confirmed freshly this milestone via a live tool-availability check (not
assumed from a prior session) -- no browser automation tool is available. None of the specific scenarios
named in this workstream (login/session/logout, RBAC per-role clicking, every Decision outcome state,
agent registration, policy create/edit/deploy/versioning, evidence display, destructive-action
confirm/cancel) were exercised in an actual browser this milestone.

**Strongest available alternative, actually performed** (not a substitute claimed to be equivalent, but
the real work done in its place): every RBAC scenario above was verified through genuine authenticated
HTTP calls against the live production API using real session tokens -- arguably a *more* rigorous check
of the authorization boundary itself than a browser click-through would be, since it tests the boundary
directly rather than through whatever the frontend happens to render. What this alternative
**cannot** verify, and what remains open: real rendering/layout behavior, actual click-target reachability,
focus/keyboard navigation, and the literal visual experience of a denied action (whether a hidden nav
item genuinely disappears versus merely being present-but-broken in some edge case the source reading
missed).

## Workstream 4: Test Coverage Expansion

**FIXED**: `server/tests/unit/test_route_permission_gates.py` (2 tests) -- the generic, class-closing
regression test described above.

**FIXED**: `server/tests/unit/test_authority_intelligence_service.py` gained 2 new tests
(`test_retrieve_corpus_text_drops_a_result_whose_organization_id_does_not_match`,
`..._whose_corpus_id_does_not_match`) covering the new Blob/Search defense-in-depth check (Workstream 6
below); 2 pre-existing tests in the same file were updated because the fix's correctness depends on
fields (`corpus_id`/`organization_id`) the old fake search-result fixtures didn't model.

**VERIFIED, unaffected**: the full backend suite -- **432 passed** (428 baseline + 4 new this milestone),
0 failed, confirmed by an actual full run, not assumed from the diff. The SDK suite (68 tests) was not
re-run this milestone since no SDK code changed; its Milestone 14 baseline remains the last confirmed
result.

**VERIFIED**: `npm run build` passes cleanly; the Milestone 14 Vitest suite (8 tests, `resourceSync.ts`)
still passes unchanged.

**PLANNED, not built this milestone**: dedicated regression tests for the specific newly-found P1s
(`AgentDirectoryPage.tsx`'s fetch handling, the nav-permission filter) would require either mocking
`apiClient`'s `fetch` or full component rendering (`@testing-library/react` is still not installed) --
correctly scoped as follow-up work rather than rushed in. Organization-isolation and certificate/signer
regression coverage already exists from prior milestones (`test_policy_api_security.py`'s org-isolation
tests, `test_h_*` authority tests) and was re-run and reconfirmed passing this milestone, not newly
written.

## Workstream 5: Decision Center Architecture

See `MILESTONE_15_DECISION_CENTER_ARCHITECTURE.md`. **Decision: Option A (Keep)**, with a small,
non-implemented UI-copy clarification recommended. Not a readiness blocker.

## Workstream 6: Milestone 14 Workstream 10/11 Recommendations -- Revisited

**Legacy `documents` table.**
- Problem confirmed real (re-verified this milestone, not merely carried forward): no `organization_id`
  column, two independent nullable FKs (`Authority.document_id`, `Principal.source_document_id`), zero
  live write path, one live Owner-only read path, zero SDK/frontend consumers, zero production rows.
- Severity: low (dead schema surface, not an active risk) but a real source of future confusion.
- Enterprise Knowledge relevance: **none** -- confirmed again this milestone that Enterprise Knowledge
  would build on the separate, modern, already-organization-scoped `authority_corpus_documents` table
  regardless of this table's fate.
- Recommendation: **APPROVE** deprecating/removing the dead `GET /v1/policies/documents` endpoint and
  the two confirmed-dead frontend types (`LiveDocument`, `LiveAuthority`) as a small, safe, near-term
  follow-up (no schema change, no data risk). **DEFER** the actual `DROP TABLE`/`DROP COLUMN` migration
  to its own dedicated, explicitly-approved schema-migration step -- not required for Enterprise
  Knowledge readiness, and this engagement's standing practice is to never execute schema migrations
  against production without a dedicated approval step, regardless of how low-risk the migration is.
  **Not implemented this milestone** (a decision gate, per this workstream's own instruction).

**Blob/Search tenant hardening.**
- Problem confirmed real: a single shared Blob container and Azure AI Search index across every
  organization, isolation enforced entirely at the query layer with no independent backstop.
- Severity: MEDIUM/WARNING (as Milestone 13 originally classified it) -- functionally correct in every
  path checked, but structurally fragile against a future caller forgetting the filter.
- Enterprise Knowledge relevance: **high** -- Enterprise Knowledge will very likely add new consumers of
  exactly this subsystem, meaning the fragility this finding describes would only get more exposure, not
  less, over time.
- Recommendation: **APPROVE and implement now** (done): centralized the OData filter into one function
  (`_scoped_filter`) and added an independent defense-in-depth check that drops any Search result whose
  own `corpus_id`/`organization_id` fields don't match the caller's expected scope, fail-closed, before
  it ever reaches a caller. This is code-only, no schema or infrastructure change, and directly closes
  the actual mechanism of the risk (a filter that could theoretically be bypassed or misconfigured) with
  an independent check that doesn't rely on every future caller getting the query right.
  **FIXED and deployed to production** (`ca-payreality-api-prod-cus--0000011`, confirmed `Healthy`),
  covered by 2 new regression tests. Heavier options (per-organization Search indexes or Blob
  containers) remain **DEFERRED**, pending a concrete Enterprise Knowledge requirement that would justify
  their operational cost.

## Production verification

**LIVE, VERIFIED**: both backend deploys this milestone reached `Healthy` at 100% traffic
(`--0000010` for the RBAC fix, `--0000011` for the Blob/Search hardening). The frontend deploy was
verified against Vercel's own build log (not a separately-run local build, which is not guaranteed
byte-identical across build environments even from identical source) -- the live domain serves exactly
`index-C9tF39z9.js`, matching what Vercel's own build step reported producing. `GET
/openapi.json` (backend) and the root frontend URL both return `200`.
