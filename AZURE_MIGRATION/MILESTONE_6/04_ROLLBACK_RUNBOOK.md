# Milestone 6: Rollback Runbook

**Scenario:** production traffic has been switched to Azure per `03_PRODUCTION_RUNBOOK.md`, and Azure then fails. Render has been kept running and untouched throughout (this program's standing rule) — it is available to receive traffic back immediately, with no rebuild required.

This is a planning document for a scenario that has not occurred, since traffic has never been switched. It is written to be genuinely executable within minutes when the time comes, not a hypothetical gesture.

## The rollback path depends on which cutover method was used (Step 5 of the Production Runbook)

### If the frontend was pointed directly at Azure's default hostname, or at a custom domain via a Vercel-side change (no DNS record change)

This is the fast path, and the one this audit recommends specifically because it makes rollback minutes-fast rather than DNS-propagation-slow.

1. In the Vercel dashboard (or via the Vercel API/CLI), revert `VITE_API_URL` for the production project back to `https://payreality-api.onrender.com`.
2. Trigger a redeploy of the production frontend.
3. Verify: `curl` the live production frontend and confirm API calls now hit Render (check response headers for `x-render-origin-server: uvicorn` / `rndr-id`, both confirmed present on Render's responses during Milestone 4's investigation).
4. **Total time: the duration of one Vercel deploy** — typically under a few minutes, with no DNS TTL wait, because no DNS record ever pointed at Azure in this path.

### If a custom domain's DNS record (e.g. `api.payreality.aisecurewatch.com`) was repointed at Azure

1. Revert the DNS record (A/CNAME) at the registrar/DNS provider back to Render's target.
2. **Rollback speed is now bounded by the DNS record's TTL**, not by anything Azure- or Render-side. Whoever executes Step 5 of the Production Runbook under this option should set a short TTL (e.g. 60–300 seconds) on that record specifically *before* cutover, precisely so this rollback path stays minutes-fast rather than being at the mercy of whatever the default TTL happened to be.
3. Verify propagation with `dns.google`'s resolver (the same tool used throughout this program's audits) before declaring the rollback complete, since some resolvers will cache past the record's TTL regardless.

## What does not need to happen during rollback

- **No Render action at all.** Render was never stopped, scaled down, or modified — it has been serving zero or near-zero traffic during the Azure cutover window but has not been idle in the sense of needing a cold start or a redeploy to resume full service.
- **No Azure resource needs to be deleted or modified** to complete a rollback. The failed Azure deployment can be left running for post-incident investigation; per this program's rules, nothing gets deleted as part of a rollback either.
- **No customer data needs to move back.** Because Step 4 of the Production Runbook (data migration) is a copy, not a cutover-and-delete, Render's database was never emptied or disabled — it still holds the authoritative data throughout, meaning a rollback loses at most whatever wrote to Azure's database during the failed window, not the pre-migration history. (This assumes Step 4 is implemented as one-way replication or a frozen-then-copied snapshot, not a destructive move — call this out explicitly when Step 4 is actually designed, since it directly determines how clean this rollback guarantee is.)

## Validating a completed rollback

Run the health/auth/OPA checks from `05_VALIDATION_PLAN.md` against the production frontend after rollback, exactly as they'd be run after a forward cutover — a rollback is a cutover in the opposite direction and deserves the same verification discipline, not an assumption that "reverting" is automatically safe.

## Decision owner

This runbook does not name a specific rollback trigger threshold (e.g., "X failed health checks in Y minutes") — that is an operational decision for whoever owns production on-call, informed by the alert rules already in place (`modules/alerts`), not something this document should invent unilaterally.
