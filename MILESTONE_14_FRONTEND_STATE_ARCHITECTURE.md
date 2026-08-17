# Milestone 14: Frontend State Architecture

## Architecture, unchanged this milestone

This app has no data-fetching/caching library (no React Query, SWR, Redux, or Zustand). Every route is
lazy-loaded (`lazy(() => import(...))`), so ordinary in-app navigation unmounts the previous route and
mounts a fresh one, which fetches its own data from scratch on mount. There is no stale in-memory
cache for a fresh mount to accidentally read -- the "click to a different page and see stale data"
scenario, as literally described, does not reproduce from this architecture (confirmed originally in
Phase 6A, reconfirmed by this milestone's own source reading of every audited page).

The real staleness gap is narrower: a page that is **already mounted** has no way to learn a resource
it depends on changed elsewhere -- a second open tab, or this tab left idle and returned to.
`src/app/services/resourceSync.ts` closes that gap with two functions and no caching layer of its own:

- `notifyResourceChanged(kind: ResourceKind)` -- called after a mutation succeeds; writes a timestamp
  to `localStorage`. The browser's own `storage` event fires in every *other* open tab automatically.
- `useResourceSync(kinds, onStale)` -- a hook a page calls with the resource kinds it depends on and
  its own existing load function; listens for the `storage` event and for the tab regaining focus/
  visibility, debounced, and calls the caller's own loader. It does not fetch or cache anything itself.

## Fixed this milestone: a real bug in the mechanism itself

`useResourceSync`'s debounce ref (`lastRefreshRef`) initialized to `Date.now()` at mount. Its guard,
`now - lastRefreshRef.current < MIN_REFRESH_INTERVAL_MS`, is true (and therefore suppresses the
trigger) for any real signal arriving within 3 seconds of the component mounting -- not just repeated
signals, the *first* one too. This was caught by writing this file's first unit tests
(`resourceSync.test.ts`), not by hand tracing; three of the eight tests failed against the original
code before the one-line fix (initialize to `0` instead). All 8 tests now pass. This means every page
listed in the dependency matrix below had a real, if narrow, race: a mutation in another tab landing
within 3 seconds of this page's own mount would have been silently missed until the *next* signal.

## Resource dependency matrix (as of the end of this milestone)

| Resource kind | Emitted by | Consumed by (`useResourceSync`) |
|---|---|---|
| `agents` | Agent register/update/activate/suspend/retire/transfer/bulk-* (`agents/api.ts`) | Decision Center agent dropdown, Agent Directory, **Agent Detail (new this milestone)**, **Live Assurance (new)**, **Platform Overview (new)** |
| `certificates` | Agent revoke, certificate rotate, bulk-rotate (`agents/api.ts`) | Agent Directory, **Agent Detail (new this milestone)** |
| `policies` | Policy create/edit/submit/approve/reject/compile/deploy (`policy-studio/api.ts`), lifecycle activate/schedule/retire/deprecate/archive/rollback (`policy-studio/lifecycleApi.ts`), **AI Policy Builder's promote-candidate action (new this milestone)** | Policy List, Runtime Policy Dashboard, **Live Assurance (new)**, **Platform Overview (new)** |
| `decisions` | Intent submission, decision resolve (`LiveTestIntent.tsx`) | Live Evidence |
| `evidence` | Intent submission, decision resolve (`LiveTestIntent.tsx`) | Live Evidence, **Live Assurance (new this milestone)** |
| `organization` | Organisation settings update, business-unit/department/team CRUD (`organization/api.ts`), **enterprise-system registration (new this milestone -- was the one mutation in the file not emitting)** | **Policy Workspace's Enterprise System dropdown (new this milestone -- the first real consumer of this kind anywhere in the app; it was emitted since Phase 6A with zero listeners until now)** |

**Still not wired, disclosed rather than silently incomplete**: `createApiKey`/`revokeApiKey`/`usersApi`
(no clean `ResourceKind` exists for API keys or users yet -- see BUG-021 in the bug register; expanding
the taxonomy without a concrete consumer page driving the need would not be "the smallest correct
mechanism" this workstream asked for). AI Authority Builder's own corpus/principal/resource/operation/
relationship mutations still emit nothing -- these belong to a different, not-yet-modeled resource
space (a corpus, not an organization-wide list), and forcing them into the existing six kinds would
misrepresent their actual scope; this is a real gap for a future milestone to design deliberately,
not to patch by reusing the nearest existing kind.

## Resources outside this matrix entirely

Authorities, Principals, Approvals, and insurance-related/governance-report data were reviewed for
resourceSync applicability. **VERIFIED**: Authorities and Principals in the modern sense (the AI
Authority Builder's corpus-scoped graph) don't yet participate in `resourceSync` at all -- see above.
The legacy `Authority`/`Principal`/`Document` tables (server-side, `server/app/db/models.py`) have no
live write path at all (confirmed in Milestone 13, reconfirmed this milestone -- see the Enterprise
Readiness Assessment's Workstream 10 section), so there is no mutation to notify about. "Insurance-
related data" and "governance reports" as named in the milestone's own resource inventory instruction
do not correspond to any implemented resource in this codebase today -- **VERIFIED, not found**, not
merely unaudited.

## Frontend test suite (Workstream 8)

**FIXED**: introduced Vitest (`vitest.config.ts`, `npm test` → `vitest run`) plus `jsdom` as dev
dependencies -- this repository had no test runner of any kind before this milestone. Scope is
deliberately narrow, not "hundreds of superficial snapshot tests": `resourceSync.test.ts`, 8 tests,
covering `notifyResourceChanged` (writes the correct key, never throws even if `localStorage` is
blocked) and `useResourceSync` (does not fire spuriously on mount, fires on a matching storage event,
ignores a non-matching one, fires on visibility regain, debounces rapid repeats, cleans up its
listeners on unmount). This is the single highest-value, safety-critical piece of pure-ish logic this
milestone's audit identified, and testing it caught a real bug (BUG-009) that hand-tracing across three
prior milestones had not.

**PLANNED, not built this milestone**: the workstream's full named scope also asked for coverage of
"API client behavior, key state transitions, critical form submissions, error states, the Decisions
workflow, and cross-page mutation propagation." Only the resource-sync piece was built this milestone;
the rest would require either mocking `apiClient`'s `fetch` calls or full component rendering
(`@testing-library/react` is not yet installed), which is real, additional work correctly scoped to a
following pass rather than rushed into this one.
