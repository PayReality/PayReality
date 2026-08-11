# Production Bootstrap Program — Phase 6: DNS Cutover Plan

**Status: plan only. Nothing in this document has been executed.** Materially simpler than the superseded `PRODUCTION_CUTOVER/03_CUTOVER_PLAN.md`, which was built around a data-migration boundary that no longer exists. There is no maintenance mode, no data freeze, no migration step — only deployment, verification, and a traffic switch.

## Step 1 — Confirm Phases 1–5 complete

`05_DEPLOYMENT_INITIALIZATION_PLAN.md` fully executed and `06_PRODUCTION_VERIFICATION_CHECKLIST.md` fully passed, using real data created during that checklist's own smoke test.

## Step 2 — Switch production traffic to Azure

Per the domain decision made in Phase 3/4 (`04_PRODUCTION_ENVIRONMENT_GAP_ANALYSIS.md`):

- **Config path (recommended):** update the Vercel production project's `VITE_API_URL` to the prod Container App's hostname (custom domain or default `*.azurecontainerapps.io`, per the decision made). Redeploy the frontend.
- **DNS path:** if a custom domain was chosen and its own DNS record needs to move, repoint it now, having set a short TTL beforehand specifically so this step and any rollback of it stay minutes-fast, not TTL-bound.

**Objective:** real end-user traffic now reaches Azure. **Expected outcome:** frontend requests succeed against the prod Container App. **Verification:** confirm via Application Insights `requests` showing new traffic matching real user request patterns (not just the smoke test's own traffic from Phase 5). **Rollback:** see `08_ROLLBACK_PLAN.md` — revert the same config/DNS change.

## Step 3 — Immediate post-switch verification

Re-run the health, OPA, and Evidence-generation checks from `06_PRODUCTION_VERIFICATION_CHECKLIST.md` against real traffic, not the smoke test alone. Watch Application Insights and the five alert rules in real time during this window specifically.

## Step 4 — Observation period

Render remains fully running and untouched throughout — per this program's absolute rules, it is not stopped, scaled down, or modified at any point in this plan. The length of the observation period before considering any change to Render's own future is a business decision this document does not set unilaterally.

## Step 5 — Declare cutover complete

Only after the observation period passes with no rollback triggered. Render's future (kept as a standing rollback target indefinitely, or eventually decommissioned) becomes a live question only at this point, and only with its own explicit approval — this plan does not authorize any Render change, now or as a natural next step.

## What this plan does not include, and why it's shorter than the superseded version

No maintenance mode, no final database sync, no data-integrity validation across a migration boundary, no signing-key-registry cross-registration for historical records. All five were specific to the "real production data must move" premise this program's business clarification retired. What remains is exactly what a from-scratch production launch actually requires: deploy it, prove it works with its own first real usage, then point real users at it.
