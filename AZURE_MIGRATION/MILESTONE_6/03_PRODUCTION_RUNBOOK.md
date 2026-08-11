# Milestone 6: Production Migration Runbook

**This is a forward-looking execution plan, not a record of actions taken.** No step in this document has been executed. Per `01_PRODUCTION_AUDIT.md` and `02_CUTOVER_CHECKLIST.md`, several prerequisite steps (data migration, DNS/certificate provisioning, CORS correction) do not yet have their groundwork done — this runbook names them as real steps in the sequence, not glosses over them, precisely because skipping past them here would mean skipping past them in practice.

**Do not execute this runbook until `06_GO_NO_GO.md` reads GO.** As of this milestone, it reads NO-GO.

## Step 1 — Freeze Render deploys

Stop any in-flight or scheduled deploys to Render's `payreality-api` service. Cutover must happen against a known, static source of truth; a Render deploy mid-migration would create a moving target for the data-migration step.

## Step 2 — Resolve the Anthropic API key

Obtain the real `ANTHROPIC_API_KEY` from whoever owns that account relationship and set it via `az keyvault secret set --vault-name kv-pr-staging-lu2swm --name anthropic-api-key --value "<real key>"`, following the versionless-secret rotation procedure in `AZURE_MIGRATION/AZURE_RUNBOOK.md` (set the value, then force a new Container App revision — a plain restart is not reliable).

## Step 3 — Correct `CORS_ORIGIN` for real production traffic

The Container App's `CORS_ORIGIN` is currently computed from `var.environment`, which is `"staging"` for this environment. Before any real frontend traffic can reach it successfully, this needs to resolve to `https://payreality.aisecurewatch.com`, not `https://staging.payreality.aisecurewatch.com`. This is a Terraform-level decision (how the existing environment is labeled/promoted) that has not been made — resolve it explicitly rather than patching the computed value in isolation, since the same variable likely drives other environment-conditional behavior.

## Step 4 — Build and execute a real data migration

No tooling for this exists yet (`01_PRODUCTION_AUDIT.md`). At minimum this step requires:
1. A method to extract Render's live Postgres data (e.g., `pg_dump` against Render's connection string).
2. A verified, tested import path into Azure's Postgres (`psql-payreality-staging-cus`) that preserves referential integrity, especially the Evidence hash-chain (`payload_hash`/`previous_hash` linkage) and the signing-key registry.
3. A dry run against a disposable copy of Azure's database, with row-count and integrity checks, before doing this against the real target.
4. A final, short read-only freeze on Render (between Step 1 and this step) so the data snapshot used for migration is the actual last state before cutover, not a stale one.

This is the largest single piece of unbuilt work standing between today and a real cutover.

## Step 5 — Provision the production domain and certificate

Decide between: (a) bind a real custom domain (e.g. `api.payreality.aisecurewatch.com`) to the Container App and provision an Azure-managed certificate for it, or (b) point the frontend directly at the Container App's default `*.azurecontainerapps.io` hostname (which already has a valid Microsoft-issued certificate, so no new certificate work is needed under this option). Either is architecturally valid; this program has not made the choice yet. Execute whichever is chosen and verify the certificate is valid and trusted before proceeding.

## Step 6 — Point the frontend at Azure, but keep Render running

Update the Vercel production project's `VITE_API_URL` (or equivalent build-time environment variable) to the new Azure endpoint from Step 5. Redeploy the frontend. **Render's backend keeps running throughout** — this step only changes where the frontend sends its requests, it does not touch or disable Render.

## Step 7 — Verify with real production traffic at low volume

Immediately after Step 6, run every check in `05_VALIDATION_PLAN.md` against the now-live Azure backend receiving real frontend traffic. Watch Application Insights and the five alert rules for anything abnormal in real time, not just the synthetic checks.

## Step 8 — Observe

Per this program's own rule, Render must remain available and untouched for an agreed observation period after Step 6 (this program has not fixed a specific duration — that is a decision for whoever owns the go-live call, informed by how Step 7's validation goes). During this period, Render stays fully operational as the immediate rollback target — see `04_ROLLBACK_RUNBOOK.md`.

## Step 9 — Declare cutover complete

Only after the observation period in Step 8 passes with no rollback triggered. At that point, and only at that point, does a decision about Render's future (keep as a hot standby, scale down, eventually decommission) become a live question — and per this program's rules, that decision and any Render resource change is explicitly out of scope for this milestone and would require its own explicit approval.

## What this runbook deliberately does not include

Deleting or disabling any Render resource. Per this program's absolute rules, Render is never deleted or modified by this migration, before, during, or immediately after cutover.
