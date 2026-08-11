# Production Cutover Program — Phase 3: Cutover Plan

**Status: plan only. Nothing in this document has been executed. This plan is not eligible for execution until Phase 1's two disqualifying gaps (no Azure production environment, no data migration mechanism) are closed — see `05_PRODUCTION_READINESS_REPORT.md`.**

Each step: objective, expected outcome, verification, rollback.

## Step 0 — Prerequisites (must all be true before Step 1 begins)

Resolve the environment-identity question (does the existing staging environment become production, or is a separate one built), close the CORS/domain gap that follows from that decision, resolve `ANTHROPIC_API_KEY`, and complete a validated data migration per `02_DATA_MIGRATION_ASSESSMENT.md`. This plan assumes Step 0 is complete by the time Step 1 begins — it does not itself close these gaps.

## Step 1 — Enable maintenance mode on Render (if required)

**Objective:** stop new writes to Render's production database so the final data sync (Step 2) captures a truly final state.
**Expected outcome:** Render serves a maintenance response or read-only mode; no new mutating requests succeed.
**Verification:** attempt a real write-path request (e.g., submit a test intent) and confirm it is rejected or queued, not silently accepted and lost.
**Rollback:** disable maintenance mode; Render resumes normal read-write service immediately. This step alone is fully reversible with no data risk, since nothing has moved yet.

## Step 2 — Final database sync

**Objective:** execute the migration method from `02_DATA_MIGRATION_ASSESSMENT.md` against the now-frozen Render database.
**Expected outcome:** Azure's Postgres contains a byte-exact copy of Render's data as of the freeze point, including a correctly-populated signing-key registry.
**Verification:** row counts match exactly; Evidence chain verification passes on a representative sample; Alembic head matches on both sides.
**Rollback:** discard Azure's copy (a `DROP`/re-migrate schema-only, or simply don't proceed past this step); Render is untouched and still holds the authoritative data. Return to Step 1's rollback (disable maintenance mode) if aborting the whole cutover here.

## Step 3 — Container validation

**Objective:** confirm the Azure Container App is healthy and running the intended image *before* any traffic is pointed at it.
**Expected outcome:** current revision `Healthy`, `replicas >= 1`, correct image tag.
**Verification:** `az containerapp revision list --query "[].{name:name, healthState:properties.healthState}"`.
**Rollback:** none needed — no traffic has moved yet at this step.

## Step 4 — Health verification

**Objective:** confirm `/health` and `/health/ready` both pass against the environment that now holds the migrated data.
**Expected outcome:** both return `200`; `/health/ready`'s database and OPA checks both pass.
**Verification:** direct `curl` against the Container App's own hostname (not yet through any production domain).
**Rollback:** none needed — same as Step 3.

## Step 5 — DNS / traffic switch

**Objective:** point real production traffic at Azure.
**Expected outcome:** depends on the Step 0 domain decision — either a DNS record now resolves to Azure, or the frontend's `VITE_API_URL` now points at Azure's hostname.
**Verification:** `dns.google` resolver (DNS path) or a fresh frontend deploy's build output (config path) confirms the new target; a real request from the production frontend reaches Azure (confirmed via Azure-side access logs or Application Insights `requests`, not just a manual `curl`).
**Rollback:** revert the DNS record or the frontend config exactly as described in `04_ROLLBACK_PLAN.md`, and do so immediately if Step 6 or Step 7 fails — this is the step every later rollback in this plan reverses.

## Step 6 — Smoke tests

**Objective:** confirm the application works end-to-end against real production traffic patterns, not just synthetic health checks.
**Expected outcome:** login succeeds, a real intent submits and receives a decision, that decision's Evidence record verifies.
**Verification:** each of `05_VALIDATION_PLAN.md`'s (Milestone 6) checks, re-run now that real data and real traffic exist — the checks that were "Blocked" in that plan specifically because no real data existed are exactly the ones this step exists to finally exercise.
**Rollback:** same as Step 5 — revert DNS/config immediately.

## Step 7 — Evidence verification

**Objective:** confirm Evidence generated *after* cutover chains correctly to Evidence migrated *before* cutover.
**Expected outcome:** a new post-cutover Evidence record's `previous_hash` correctly references the last pre-cutover record migrated in Step 2; `GET /v1/evidence/chain/verify` passes across the boundary.
**Verification:** this specific check — chain continuity across the migration boundary — has no precedent in any prior milestone and deserves explicit attention here, since it's the one correctness property unique to a live cutover rather than a fresh empty-database deploy.
**Rollback:** same as Step 5.

## Step 8 — Policy evaluation / OPA verification

**Objective:** confirm OPA in Azure is evaluating the same policies Render was evaluating, with the same results for the same inputs.
**Expected outcome:** OPA's loaded policy bundle in Azure matches Render's active policies (migrated via Step 2's database sync, then reconciled into OPA via the existing `_reconcile_opa_with_active_policies` startup hook — already-shipped application code, unmodified).
**Verification:** `curl http://localhost:8181/v1/policies` (via container exec) shows a non-empty, correct bundle; replay a small set of known Render decisions against Azure and confirm identical outcomes.
**Rollback:** same as Step 5.

## Step 9 — Storage verification

**Objective:** confirm blob access (uploads, evidence exports) works against real, migrated references, not just the infrastructure-level RBAC test already performed in Milestone 4.
**Expected outcome:** a real, pre-existing (migrated) document reference resolves correctly to its blob.
**Verification:** fetch a known document through the application's own API, not directly against the storage account.
**Rollback:** same as Step 5.

## Step 10 — Monitoring verification

**Objective:** confirm Application Insights and Log Analytics are receiving real production telemetry, and all five alert rules remain enabled and correctly scoped.
**Expected outcome:** live `requests`/`dependencies`/`traces` data reflecting real user traffic; `az monitor metrics alert list` unchanged.
**Verification:** the same live-query method used throughout Milestones 3–5.
**Rollback:** none needed — observability failing doesn't itself require reverting traffic, but would materially increase the urgency of every other rollback checkpoint in this plan.

## Step 11 — Disable maintenance mode

**Objective:** resume full read-write service, now against Azure (Render remains fully able to as well, per this program's rules — it is not being disabled).
**Verification:** a real write-path request succeeds against Azure.
**Rollback:** same as Step 5 if this is where a problem first surfaces.

## Rollback checkpoints, summarized

Steps 1–4 are fully reversible with zero data risk (nothing has moved traffic or committed to a direction yet). Steps 5–11 all share the same rollback action — revert Step 5's DNS/config change — because Render was never modified and still holds the pre-migration authoritative data throughout. See `04_ROLLBACK_PLAN.md` for the full procedure.
