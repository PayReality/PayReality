# Milestone 14: Platform Reliability, Frontend Integrity & Enterprise Readiness -- Audit

This document is the record of what was actually checked, what was actually found, and what was
actually fixed. Every claim below is labeled **LIVE** (confirmed against the running production
system), **FIXED** (changed and verified by build/test, not yet re-verified live post-deploy unless
stated), **VERIFIED** (confirmed by direct code reading or a passing test, not by inference), **PLANNED**
(a real gap, not yet addressed), **RECOMMENDED** (a proposal requiring approval before implementation),
or **VISION** (a future-state description, not a current fact). Nothing here is claimed as verified if
it was only inferred from source code without running it.

## Phase 0: Baseline

- **VERIFIED** Backend test suite baseline, before any Milestone 14 change: `428 passed`, 0 failed
  (`server`, pytest, full suite).
- **VERIFIED** SDK test suite baseline: `68 passed` (`sdk-python`, pytest, full suite). Neither suite
  needed to be re-run after this milestone's changes, because every fix made this milestone is
  frontend-only; no backend or SDK source file was touched.
- **VERIFIED** No frontend test runner existed in this repository before this milestone
  (`package.json` had only `build`/`dev` scripts, no test framework, no TypeScript devDependency,
  no `tsconfig.json`, no `tsc` binary). This is a materially different, more precise finding than
  "there's no test coverage": it also means every prior milestone's "`npm run build` passes" claim
  verified that the code transpiles, not that its TypeScript types are internally consistent --
  `vite build` uses esbuild's type-stripping transform, which never type-checks. This is a real,
  disclosed, systemic gap, not a defect introduced this milestone.
- **VERIFIED** No browser automation tool is available in this environment (checked freshly this
  milestone via `ToolSearch`, not assumed from a prior session). Workstream 7's browser click-through
  script could not be executed. The strongest available substitute -- direct source tracing, a real
  passing build, a real passing backend/SDK/new-frontend test run, and live HTTP checks against the
  real production API and frontend -- was used instead, and is called out explicitly wherever it
  substitutes for an actual browser pass.
- **LIVE** Backend production (`api.aisecurewatch.com`): confirmed healthy and running the same image
  (`prod-04b2817`) as `prod.tfvars` before this milestone began -- no backend deployment drift existed.
  Unaffected by this milestone, since no backend code changed.
- **FIXED, then LIVE** Frontend production (`payreality.aisecurewatch.com`): confirmed, before this
  milestone's changes, to be serving `assets/index-CEBBLqx-.js`, which predates Milestone 12, the
  Milestone 10 UX-rename work, and Phase 6A's `resourceSync.ts` (commit `48b4bb4`) entirely -- real,
  previously-undiscovered production drift. After this milestone's fixes were committed and deployed
  (`vercel deploy --prod`), the live domain was re-checked and now serves `assets/index-wdtdkhhS.js`,
  which is byte-for-byte the same hash as the just-built local `dist/assets/index-wdtdkhhS.js` --
  confirmed via direct comparison, not inferred. The drift is closed.

## Scope actually covered this milestone

Three parallel, read-only research passes were run against the real codebase (not assumed from prior
milestone summaries), followed by direct personal verification of the highest-stakes findings:

1. **CRUD/data-loading audit** of `AgentDetailPage.tsx`, the policy-studio authoring/publish/review/
   version pages, `ai-authority-builder`/`ai-policy-builder` pages, organization pages, and
   `LiveAssurance.tsx`/`PlatformOverview.tsx` -- read in full and traced end-to-end, with
   `PolicyListPage.tsx`/`RuntimePolicyDashboardPage.tsx` read as a known-good comparison baseline.
2. **Frontend/backend API contract audit** across 8 endpoint groups (decisions, decision-explanation,
   agents-list, agent-detail, evidence, runtime-policies, intent-submission, auth) -- Pydantic schemas,
   router return shapes, and every frontend TS type/consuming component compared field-by-field.
3. **Dead/orphaned code sweep** across routes, API clients, exported types, imports, UI controls, and
   docs referencing retired infrastructure.

This is a real subset of "every production-facing page," not literally every route in the application
-- **PLANNED**: a small number of lower-traffic pages (e.g. individual Organisation Settings tabs
beyond what was directly touched, the Simulation page) were not independently re-audited this
milestone; nothing found elsewhere in this audit suggests they share the same defect classes, but
that is an inference, not a verification.

In addition, the following was done personally, not delegated, per the milestone's own instruction
that the Decisions and RBAC workstreams receive special attention:

- **Workstream 5 (Decisions deep audit)** -- `LiveTestIntent.tsx` read in full, current version.
- **Workstream 6 (RBAC/permission audit)** -- the frontend's `hasPermission` usage was audited against
  the backend's actual `Permission` enum and route-level `require_permission` gates.

## Workstream 5: Decisions / Runtime Decision Center -- root cause of "agents don't appear"

**VERIFIED**, from `src/app/live/pages/LiveTestIntent.tsx:347` and `src/app/live/agentKeyStore.ts`:
the Decision Center's agent dropdown is populated from `signableAgents`, defined as:

```ts
const signableAgents = (agents ?? []).filter((a) => getAgentPrivateKey(a.id) && a.certificate_id);
```

`getAgentPrivateKey` reads from a `localStorage` key (`payreality_live_agent_keys`) that is written
to **only** by `saveAgentKeyPair`, called **only** from this same browser's own key-generation flow
(the Agents page's "Register" action, and `AgentDetailPage.tsx`'s "Rotate certificate" action).

This is a materially different, more fundamental finding than the "stale until reload" framing this
milestone's own prompt used as an example, and different from Phase 6A's own fix (which addressed a
real but narrower cross-tab/tab-refocus staleness gap). **An agent registered through the Python SDK,
or registered/activated from a different browser or device than the one currently viewing the
Decision Center, can never appear in this dropdown on this device -- not until a reload, forever,
regardless of any resource-sync fix.** This is a by-design consequence of the private key being
generated and held client-side (`src/app/live/agentKeyStore.ts:1-6` documents this as a deliberate
Phase 1 simplification: "a real Agent integration generates and holds its own key pair in its own
runtime and never hands the private key to a browser"), not a bug in the resourceSync mechanism, the
agents API, or the dropdown's rendering logic. The existing warning message
(`"No agents with a signing key in this browser yet. Register one on the Agents page first."`,
`LiveTestIntent.tsx:663`) is accurate and already explains this correctly to a user who reads it --
the actual defect, if any, is that this is easy to encounter and mildly surprising (an SDK-registered
agent simply never becomes selectable here), not that the UI is lying about anything.
**RECOMMENDED, not implemented**: if agents commonly get registered outside the browser currently
viewing Decisions (the expected real-world case for any agent integrated via the SDK), the
architecture itself needs a decision, not a frontend patch -- either the SDK path needs its own way to
supply a signable identity to this UI, or the "browser as the agent" simplification needs to be
retired before Enterprise customers rely on this page. This is a product/architecture decision, out
of scope to make unilaterally this milestone.

**VERIFIED by direct source reading**, every other named Decision Center state:
- Empty (no decision yet): `LiveTestIntent.tsx:830-834`, correct.
- Evaluating: `:787-792`, correct spinner state while `submitting && !decision`.
- Allow/Deny/Human Review: `OUTCOME_STYLE` (`:44-48`) covers exactly these three outcomes returned by
  the backend (confirmed against `GetDecisionResponse.outcome`'s real value set in the contract
  audit); rendering at `:852-948` handles all three plus the not-yet-decided `PENDING` sub-state.
  `Escalate`/"Awaiting Approval" as a distinct fourth state does not exist in the backend's outcome
  enum -- `HUMAN_REVIEW` with `status: "PENDING"` is that state, and is handled (`:896-934`).
- "Blocked": no distinct backend outcome by this name exists; `DENY` is the closest real outcome and
  is handled.
- API error / submission failure: `:479-488`, `:836-850`, correct, with the fail-closed messaging
  already in place.
- Timeout: `POLL_MAX_ATTEMPTS`/`POLL_INTERVAL_MS` (`:41-42`) give a 2-minute polling window;
  `:806-818` handles the timeout state with a manual "Resume checking" action, correct.
- Missing agent / invalid certificate / unauthorized action: `:441-447` guards against submitting with
  no agent/key/certificate selected client-side; a genuinely invalid certificate or unauthorized
  action is rejected server-side and surfaced through the same generic submission-error path
  (`describeApiError`), which is correct but generic -- **PLANNED**: no state-specific messaging exists
  for "this certificate was revoked" versus any other 4xx, which would be a real, if minor, UX
  improvement.

None of the above states were exercised in a real browser this milestone (unavailable, disclosed in
Phase 0). This is source-level and contract-level verification, not live UI verification.

## Workstream 6: Authentication & Permission Behaviour

**FIXED**, two confirmed, source-verified gaps where the frontend implied an operation was available
when the backend would reject it -- the exact failure mode the milestone's own instructions named
explicitly ("The frontend must not imply that a user can perform an operation when the backend will
reject it"):

1. `AgentDetailPage.tsx`'s Activate/Suspend/Retire/Revoke/Rotate/Transfer buttons rendered based only
   on the agent's lifecycle `status`, with no `hasPermission` check at all -- unlike the established,
   correct pattern already in use in `ReviewQueuePage.tsx`, `VersionsPage.tsx`, `PolicyWorkspacePage.tsx`,
   and `CorpusReviewPage.tsx`. A `REVIEWER`, `AUDITOR`, or `EXECUTIVE` role (none of which hold any
   `agent.*` permission per `server/app/domain/rbac/permissions.py`) would see fully clickable
   controls that the backend's own `require_permission(Permission.AGENT_*)` gates
   (`server/app/routers/agents.py`) would reject with a 403.
2. `LiveTestIntent.tsx`'s Approve/Deny buttons for a `HUMAN_REVIEW` decision rendered based only on
   `decision.outcome`/`decision.status`, with no `hasPermission("decisions.resolve")` check --
   `AGENT_ADMIN`, `AUDITOR`, and `EXECUTIVE` roles all lack `DECISIONS_RESOLVE`
   (`server/app/routers/intents.py:326`) and would see clickable resolve buttons the backend rejects.

Both now follow the same `!!user && !hasPermission(...)` convention `ReviewQueuePage.tsx` already
established (stay permissive when there is no session, since the Operator Key bypass is still active
in that case; only disable when a real signed-in user is positively known to lack the permission).
**FIXED, verified by build**; not yet verified against a real non-Owner-role live session (no browser
tooling, and creating and testing under every one of the six roles live was out of scope for the time
available this milestone) -- **PLANNED** as a follow-up verification step.

**PLANNED, not audited this milestone**: a full page-by-page sweep of every remaining interactive
control against every one of the six roles (`OWNER`, `GOVERNANCE_ADMIN`, `AGENT_ADMIN`, `REVIEWER`,
`AUDITOR`, `EXECUTIVE`) was not performed. This milestone's RBAC work confirmed the existing correct
pattern in four files, found and fixed the two most consequential violations (agent lifecycle
mutations and decision resolution), and stopped there rather than claiming exhaustive coverage it did
not have time to earn.

## Findings and fixes: see `MILESTONE_14_BUG_REGISTER.md` for the itemized list with severity, root
cause, fix, and verification status for every defect found this milestone (not just the two above).

## Workstream 9: Dead / Orphaned Code

**VERIFIED**, clean sweep, no destructive deletions made (per the instruction to remove only code
provably dead):
- Two genuinely orphaned exported types confirmed, both leftovers from the already-retired legacy
  Authority/Mandate document pipeline: `LiveDocument` and `LiveAuthority` in `src/app/live/types.ts`
  (zero references anywhere in `src/`). **PLANNED**: left in place, tied to the Workstream 10 decision
  below rather than deleted in isolation.
- One route-linking gap, not a bug: `/governance/upload` (the single-document AI Policy Builder route)
  has no forward link from any current UI surface -- reachable only via five legacy-bookmark redirects,
  a "back" link from inside its own flow, or a direct URL. `routes.tsx`'s own comment marks it as kept
  for backward compatibility. **RECOMMENDED**: a product decision on whether to add a real entry point
  or convert it to redirect-only.
- No duplicate API clients, no broken imports (`npm run build` passed both before and after this
  milestone's changes), no disguised dead UI controls, and no doc actively misdescribing current
  architecture as live when it is not (`ARCHITECTURE.md` already correctly discloses its own
  supersession; the Rust/gRPC claim is correctly recorded as resolved).

## Workstream 3: API Contract Audit -- clean

**VERIFIED**: zero confirmed field-name typos, missing fields, extra silently-ignored fields, or
optional/required mismatches across all 8 audited endpoint/type/component triads. One systemic,
currently-safe observation worth carrying forward: the backend types several enum-like fields
(`status`, `health`, `outcome`, `decision`, `risk_impact`) as plain `str` while the frontend narrows
them to literal unions. Every actual value the backend assigns today was traced and matches the
frontend's unions exactly, so there is no live bug -- **RECOMMENDED**: tightening these to a real
`Enum`/`Literal` on the backend would make a future new status value a compile-time frontend error
instead of a silent "falls through every branch" runtime bug.

## Workstream 10 and 11

See `MILESTONE_14_ENTERPRISE_READINESS_ASSESSMENT.md` for the full legacy-`documents` options analysis
and the Blob/Search tenant-hardening proposal. Both are recommendations only, per the instruction not
to implement schema or infrastructure changes without explicit approval.

## Workstream 12: Production Reliability Sweep

- **LIVE**, verified by direct HTTP check: `https://api.aisecurewatch.com/openapi.json` returns 200;
  `https://payreality.aisecurewatch.com/` returns 200 and now serves the current build (drift closed,
  see Phase 0 above).
- **VERIFIED**: no backend deployment drift (`prod.tfvars` matched the live, Healthy, 100%-traffic
  container app revision before this milestone began; unaffected since no backend code changed).
- **PLANNED, not re-verified this milestone**: CORS configuration, environment variable correctness,
  and TLS certificate validity were not independently re-checked this milestone beyond the passing
  HTTP checks above -- nothing in this milestone's work touched infrastructure or environment
  configuration, so there is no specific reason to suspect drift there, but that is an inference from
  "nothing changed," not a fresh verification.

## Workstream 13: UX Integrity

Every UX change made this milestone was a direct consequence of a functional defect fixed above
(busy/disabled states preventing double-submission, error banners replacing silent failures,
confirmation steps on destructive actions, a corrected loading-vs-error indicator on the Overview
page). No visual redesign was performed; the existing design system and component set
(`Card`, `Alert`, `Button`, `ConfirmButton`) were reused throughout, never replaced.
