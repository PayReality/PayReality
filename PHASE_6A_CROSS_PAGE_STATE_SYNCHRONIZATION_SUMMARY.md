# Phase 6A: Cross-Page State Synchronization and Stale Data Audit

Investigates the reported platform-wide defect ("creating/updating something on one page doesn't show up elsewhere without a reload") and implements a targeted fix. This is a frontend architecture change; no backend, policy-evaluation, or authorization code was touched.

## 1. Root cause: what the code actually shows

Before writing any fix, the frontend's actual data-fetching architecture was traced from source, not assumed. Confirmed facts:

- This app has **no data-fetching/caching library** at all -- no React Query, SWR, Redux, or Zustand (`package.json` has none of these). Every page fetches its own data with a plain `useState`/`useEffect`/`apiClient` call.
- Every real page is **route-level code-split** (`lazy(() => import(...))`, `routes.tsx`). Navigating to a different route via the app's own links always unmounts the previous route's component and mounts a fresh one, which runs its own `useEffect` fetch from scratch. **There is no stale in-memory cache for a fresh mount to accidentally read.**
- No shared/global Context anywhere in the app caches server-fetched business data (agents, policies, decisions, organisations) above the route level. The only Context providers found (`AuthContext`, `HelpContext`, `TourProvider`, `ui/toast`) hold identity/UI state, never mutable resource lists.
- No mutation anywhere dispatches a custom event, uses `localStorage`'s `storage` event, or has any other cross-component notification mechanism. Every page updates only its own local state after its own mutations.
- No page-level browser caching is in play (`fetch()` is called with no `cache` option and no `Cache-Control` request headers).

**Conclusion, stated honestly rather than assumed**: the exact scenario as most literally described -- a single tab, clicking from one page to another via the app's own navigation, seeing stale data -- does not reproduce from this architecture. Every route already refetches fresh on every mount, and there is no cache anywhere to invalidate.

**The real, distinct staleness gap this architecture does have**: a page that is **already mounted** has no way to learn that a resource it depends on changed elsewhere. This happens in two ordinary, common situations for a dashboard application:
1. **Multiple open tabs or windows** -- a resource is mutated in one tab while a dependent page sits open, already-mounted, in another.
2. **A tab left open and returned to later** -- the user switches away (another application, another tab) for a while, then comes back to a tab that was never actually re-navigated within.

This is a real defect, just a narrower and more specific one than "any navigation." It is exactly the class of problem a data-fetching library like React Query solves by default with `refetchOnWindowFocus`, and exactly what this fix targets, without adopting a library this codebase doesn't otherwise use.

## 2. The synchronization strategy implemented

New file: `src/app/services/resourceSync.ts`. Two small, dependency-free functions, no caching layer, no query keys, no request interception:

- **`notifyResourceChanged(kind)`** -- called immediately after a mutation succeeds. Writes a timestamp to `localStorage` under a well-known key. This is what makes the signal cross-**tab**: the browser's own `storage` event fires automatically in every *other* open tab/window (never the tab that wrote it), which is exactly the notification a page in a different tab needs, with no polling and no server changes.
- **`useResourceSync(kinds, onStale)`** -- a hook a page calls with the resource kinds it depends on and its own existing load function. It listens for the `storage` event (cross-tab) and for the tab regaining visibility/focus (the "left open, came back" case), debounced to avoid refetching on rapid alt-tabbing. It does not fetch anything itself -- it calls the page's own already-existing loader, which already knows how to fetch and render its own data correctly.

This directly follows the task's own architecture:

```
CREATE/UPDATE/DELETE succeeds
  -> notifyResourceChanged(kind)                     [in the api.ts mutation]
  -> another mounted page's useResourceSync(kind, ...) fires
  -> that page's own existing load function re-runs
  -> user sees the new state, without a reload
```

Deliberately **not** implemented: a blanket "refetch everything on every mutation" strategy, a new caching layer, or `window.location.reload()` anywhere. Each page opts in only to the specific resource kinds it actually depends on.

## 3. Resource dependency matrix (as wired this phase)

| Mutation | Resource changed | Emits | Dependent pages wired to `useResourceSync` |
|---|---|---|---|
| Agent register/update/activate/suspend/retire/transfer/bulk-suspend/bulk-activate/bulk-retire | agents | `notifyResourceChanged("agents")` | `LiveTestIntent.tsx` (Decision Center's agent dropdown -- the flagship reported example), `AgentDirectoryPage.tsx` |
| Agent revoke, certificate rotate, bulk-rotate | certificates (+ agents for revoke) | `notifyResourceChanged("certificates")` | `AgentDirectoryPage.tsx` |
| Policy create/edit/submit-for-review/approve/reject/compile/deploy | policies | `notifyResourceChanged("policies")` | `PolicyListPage.tsx`, `RuntimePolicyDashboardPage.tsx` |
| Policy lifecycle activate/schedule-activation/schedule-retirement/cancel-schedule/retire/deprecate/archive/rollback | policies | `notifyResourceChanged("policies")` | same as above |
| Intent submission (new decision + evidence) | decisions, evidence | `notifyResourceChanged("decisions")`, `notifyResourceChanged("evidence")` | `LiveEvidence.tsx` |
| Decision resolve (approve/deny) | decisions, evidence | same as above | `LiveEvidence.tsx` |
| Organisation settings update, business unit/department/team create/update/delete | organization | `notifyResourceChanged("organization")` | *(emitted; no consumer page wired this phase -- see section 5)* |

`dryRun` (Simulator) is deliberately excluded from emitting -- it changes nothing.

## 4. Testing

**Navigation-without-reload scenarios**: could not be tested in a real browser -- no browser-automation tool is available in this environment (checked this session, not assumed). This is disclosed explicitly rather than claimed.

**What was verified instead**:
- `npm run build` passes with all changes (the new `resourceSync.ts` module is correctly bundled as its own code-split chunk, confirming no import-cycle or bundling issue).
- Every wired mutation and consumer page was traced by hand to confirm the resource-kind strings match exactly between the emitting `notifyResourceChanged` call and the receiving `useResourceSync` call (a typo here would silently break the signal with no build-time error, since both are plain strings -- the `ResourceKind` union type at least catches a misspelled kind at compile time, which `npm run build` exercises).
- **This repository has no frontend test runner at all** (confirmed in a prior milestone: `package.json` has only `build`/`dev` scripts, no test framework, no TypeScript devDependency). This is a pre-existing, structural fact about the repository, not a gap introduced or left open by this phase -- `resourceSync.ts`'s logic (event listeners, debouncing, `localStorage` read/write) is exactly the kind of pure-ish logic that would benefit from a unit test if a test runner existed, and could not be added here without introducing a new devDependency and test infrastructure, which is a larger change than this phase's scope.

**No claim of full UI verification is made.** The fix is architecturally sound and traced by hand end-to-end; it has not been clicked through in a real browser.

## 5. What was not wired (disclosed, not silently incomplete)

The core utility applies to any page; only a representative, high-value subset matching the bug report's own named examples was wired this phase, not the entire application:

- **Organisation-structure changes** emit `notifyResourceChanged("organization")` but no consumer page was wired to listen this phase (e.g., Agent registration's business-unit picker, Authority Builder's principal-assignment views). The signal exists and is ready to be consumed; adding `useResourceSync(["organization"], ...)` to those pages is a small, low-risk follow-up.
- **Certificate-dependent signing views** beyond `AgentDirectoryPage.tsx` (e.g., `AgentDetailPage.tsx`'s own certificate list) were not wired this phase.
- **`LiveAssurance.tsx`** (the platform-wide rollup/summary page) reads agents/policies/evidence counts but was not wired to any resource kind this phase.
- User management, API keys, and invitations (`usersApi`, the `api-keys`/`invitations` parts of `organizationApi`) do not emit any resource-change signal yet.

None of these omissions reintroduce the *original* single-tab-navigation bug (which, per section 1, does not exist in this architecture to begin with) -- they are pages that would benefit from the same cross-tab/return-to-tab protection the wired pages now have, not pages with a known active defect.

## 6. Enterprise Knowledge status

Not applicable to this phase -- this is a pure frontend data-freshness fix, unrelated to Enterprise Knowledge, Runtime Authority, or any backend authorization work from the preceding milestones.
