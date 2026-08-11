# Production Cutover Program — Phase 4: Rollback Plan

**Status: plan only.** Written to be executable without improvisation once a real cutover has actually happened — which, per `05_PRODUCTION_READINESS_REPORT.md`, it has not yet. Assumes the scenario named in this program's instructions: Azure fails *after* production traffic has already switched.

## DNS rollback

Depends on which Step 5 method (`03_CUTOVER_PLAN.md`) was used:

- **If the frontend's `VITE_API_URL`/build config was changed (no DNS record moved):** revert the Vercel production project's environment variable to `https://payreality-api.onrender.com` and redeploy. No DNS propagation delay applies, because no DNS record ever pointed at Azure — this is the fast path and the one this program recommends specifically so rollback is minutes, not TTL-bound.
- **If an actual DNS record (e.g., `api.payreality.aisecurewatch.com`) was repointed:** revert the A/CNAME record to Render's target. **Rollback speed is bounded by that record's TTL** — the Cutover Plan's Step 5 must set a short TTL (60–300s) on this record *before* cutover specifically so this path stays fast. Verify actual propagation with the `dns.google` resolver rather than trusting the TTL alone, since some resolvers cache past it.

**Timing expectation:** minutes for the config path; TTL-plus-a-safety-margin for the DNS path — this is precisely why the config path is the recommended default.

## Application rollback

The Azure Container App itself does not need to be rolled back to receive traffic back — DNS/config rollback (above) already redirects traffic to Render regardless of Azure's internal state. If the failure was specifically a bad Azure deployment (as opposed to a data or infrastructure problem), the tested procedure from Milestone 5 applies independently: revert `container_image` in Terraform, plan, apply, verify the resulting revision is `Healthy`. This is not on the critical path for restoring service, since DNS/config rollback already did that — it matters for restoring Azure to a good state before attempting cutover again.

## Database rollback

Because the migration method (`02_DATA_MIGRATION_ASSESSMENT.md`) is a **copy**, not a **move**, Render's database was never modified, emptied, or disabled by the migration itself — it still holds the authoritative data throughout the cutover window. **There is no database rollback action required on Render's side.** On Azure's side: whatever wrote to Azure's database during the failed cutover window is now potentially inconsistent with Render's (which resumed as the source of truth the moment DNS/config rolled back) — Azure's copy should be treated as suspect and not blindly reused for the next cutover attempt without re-running the migration and re-validating from a fresh Render snapshot.

## Secrets rollback

No secret needs to be rolled back as part of restoring service — Render's own environment variables were never touched, and reverting DNS/config doesn't require any Azure secret to change. If a secret was rotated as part of this cutover attempt (e.g., a new `ANTHROPIC_API_KEY`) and is suspected as the failure cause, the prior value should be restored via `az keyvault secret set` and a new Container App revision forced (per `AZURE_RUNBOOK.md`'s documented, tested procedure) — but this affects only Azure's own internal state, not the rollback-to-Render path, which doesn't depend on it.

## Configuration rollback

`CORS_ORIGIN`, `container_image`, and any other Terraform-managed configuration changed specifically for cutover should be reverted via the same plan-then-apply discipline used throughout this program (`terraform plan -out=x.tfplan` → review → `terraform apply x.tfplan`; never `-auto-approve`, which this environment's own permission controls block for exactly the review-skipping risk it represents). This is cleanup after service is already restored via DNS/config rollback, not a prerequisite for it.

## Timing expectations, end to end

| Rollback component | Expected time |
|---|---|
| DNS/config rollback (service restoration) | Minutes (config path) or TTL + margin (DNS path) |
| Verification that Render is receiving traffic again | Immediate — a single request |
| Application rollback (Azure-side cleanup) | Not on the critical path; minutes when performed |
| Database/secrets/config rollback (Azure-side cleanup) | Not on the critical path; done at leisure before the next cutover attempt |

**The number that matters for "restore Render as production within minutes" is the first row.** Everything else is cleanup that happens after service is already restored, not before.

## Verification that rollback succeeded

Run the same smoke tests as `03_CUTOVER_PLAN.md`'s Step 6, now against Render: login, a real intent submission, Evidence verification. A rollback is a cutover in the opposite direction and deserves the same verification discipline — "traffic is pointed at Render again" is necessary but not sufficient; confirm the application actually works there, which it should, since Render was never modified, but confirm it rather than assume it.

## What this plan does not include

Any action against Render beyond confirming it still works. Render is never deleted, disabled, or reconfigured as part of a rollback — it is the target being rolled back *to*, and per this program's absolute rules it remains untouched throughout.
