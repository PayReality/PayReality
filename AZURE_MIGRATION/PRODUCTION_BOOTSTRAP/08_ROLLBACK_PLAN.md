# Production Bootstrap Program — Phase 6: Rollback Plan

**Status: plan only.** Simpler than `PRODUCTION_CUTOVER/04_ROLLBACK_PLAN.md`, which reasoned about a data-migration boundary that no longer exists in this program's scope. Assumes the scenario this program's instructions name: Azure fails after production traffic has already switched (`07_DNS_CUTOVER_PLAN.md`'s Step 2).

## The rollback action

Whichever method Step 2 used, in reverse:

- **Config path:** revert Vercel's `VITE_API_URL` to `https://payreality-api.onrender.com`, redeploy. No DNS propagation wait, because no DNS record ever moved. **This is the fast path, minutes bound, and the reason this plan continues to recommend it as the default choice in `04_PRODUCTION_ENVIRONMENT_GAP_ANALYSIS.md`.**
- **DNS path:** revert the A/CNAME record to Render's target; speed is bounded by whatever TTL was set on that record before cutover — set it short beforehand for exactly this reason.

## Why this rollback plan has no database or secrets section

The prior (superseded) rollback plan needed separate database and secrets rollback sections because a real migration meant Azure's database could hold real production writes that occurred during a failed cutover window, at risk of being lost or inconsistent with Render's copy. **That risk doesn't exist here.** Render was never paused, frozen, or copied from — it kept operating as production the entire time Azure was being bootstrapped and verified. The moment traffic reverts to Render, Render's own data (which never stopped being live) is exactly correct and current. Any writes that landed in Azure's database during the brief failed window are new-to-Azure data with no Render equivalent to reconcile against — they can be discarded when Azure's environment is fixed and re-attempted, with no data-loss question on Render's side at all.

## Application rollback

Not required to restore service (the DNS/config reversion above already does that). If the failure was specifically a bad Azure deployment rather than a broader problem, the already-tested Milestone 5 procedure applies independently: revert `container_image` in Terraform, plan, apply, confirm the resulting revision is `Healthy` — done at leisure, to prepare for a second cutover attempt, not on the critical path for restoring service.

## Timing expectations

| Component | Expected time |
|---|---|
| Service restoration (config path) | Minutes |
| Service restoration (DNS path) | TTL + margin |
| Verification traffic is back on Render | Immediate — one request |
| Azure-side cleanup / root cause | Not on the critical path |

## Verification that rollback succeeded

Re-run `06_PRODUCTION_VERIFICATION_CHECKLIST.md`'s smoke-test items against Render, exactly as they were run against Azure — confirming Render works is not an assumption just because it was previously production; it kept running the entire time, but a rollback deserves the same verification discipline as a forward cutover, not less.

## What this plan does not do

Nothing to Render beyond confirming it still works. It was never modified, paused, or degraded by any step in this program, and this rollback plan requires no action against it beyond that confirmation.
