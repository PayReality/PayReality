# Milestone 6: Production Audit

Every finding below is from a live command run against the real subscription, DNS, and running services during this milestone — not inferred from prior milestones' documentation. Where a prior milestone already established a fact and this audit re-confirms it unchanged, that's noted; where this audit found something new, that's flagged explicitly.

## The central finding

**There is no Azure production environment.** Every prior milestone (1–5) provisioned and validated exactly one Azure environment: `rg-payreality-staging-cus`, built from `environments/staging.tfvars`, Terraform variable `environment = "staging"`. `environments/prod.tfvars` has existed since Milestone 2 but **has never been applied**.

```
az group list --query "[].{name:name, location:location}"
```
```
Name                                                                Location
-------------------------------------------------------------------  ----------
rg-payreality-tfstate                                                eastus2
NetworkWatcherRG                                                     eastus2
rg-payreality-staging-cus                                            centralus
ME_cae-payreality-staging-cus_rg-payreality-staging-cus_centralus    centralus
```

No resource group name contains `prod`. No Postgres server, Key Vault, Container App, or any other resource exists anywhere in this subscription outside `rg-payreality-staging-cus` and its auto-generated infrastructure companion. This is the single fact every other finding in this audit and every downstream document must be read against: **"Azure is production-ready" (Milestone 5's conclusion) means the platform design and the one environment built from it are ready — it does not mean a second, separate production deployment already exists.**

## Production DNS and SSL — does not exist yet on Azure

```
dns.google resolve payreality.aisecurewatch.com  → 76.76.21.21 (Vercel)
dns.google resolve api.payreality.aisecurewatch.com → NXDOMAIN
dns.google resolve staging.payreality.aisecurewatch.com → NXDOMAIN
az containerapp hostname list --name ca-payreality-api-staging-cus → []
az containerapp show ... --query properties.configuration.ingress.customDomains → (empty)
```

- The production frontend domain (`payreality.aisecurewatch.com`) resolves to Vercel and is unrelated to this migration — it is not expected to change.
- **There is no `api.*` subdomain in DNS at all.** The frontend calls Render's backend directly by its raw `payreality-api.onrender.com` hostname (confirmed in Milestone 4), not through a branded domain.
- **The Azure Container App has zero custom domains bound and zero SSL certificates provisioned.** It is reachable only via its default `*.azurecontainerapps.io` hostname. A production cutover needs either a new custom domain + managed certificate on the Container App, or a Vercel environment-variable change pointing at the Container App's default hostname directly — this is a decision that has not been made yet, not merely an unexecuted step.

## Production data — has never been migrated

Searched the entire repository for any data-migration tooling (`pg_dump`, `pg_restore`, a Render-to-Azure export/import script, anything beyond Alembic's schema migrations): **none exists.** Every milestone from 3 onward carried an explicit "no data migration" rule as a deliberate scope boundary, not an oversight — but that means the boundary this milestone now has to cross was never built.

Azure's Postgres (`psql-payreality-staging-cus`) contains exactly what Milestone 3's bootstrap and Milestone 5's testing put there: one organization, one signing key, the schema at head revision. It does not contain Render's actual production data — whatever organizations, agents, policies, evidence records, and users exist in Render's live database today. This session has no credentials to query Render's database directly and does not claim a specific row count there; the architectural fact stands regardless of the exact number: **no mechanism exists to move that data, and none has been executed.**

## Secrets — mostly real, one disclosed gap remains

Confirmed live via `az keyvault secret list` against `kv-pr-staging-lu2swm`:

| Secret | Status |
|---|---|
| `database-url` | Real, Terraform-managed |
| `postgres-administrator-password` | Real, Terraform-managed |
| `evidence-signing-key-b64` / `-id` | Real, generated and cryptographically validated in Milestone 5 |
| `admin-api-key` | Real, generated and validated in Milestone 5 |
| `anthropic-api-key` | **Still the Milestone 2 placeholder** (`PENDING-MILESTONE-5-MANUAL-ENTRY`) — unchanged since Milestone 5 flagged it. A third-party credential this program cannot generate. |

## Managed Identity permissions — confirmed intact

Re-verified role assignments unchanged since Milestone 5: `Key Vault Secrets Officer` (Terraform operator) / `Key Vault Secrets User` (Container App identity) on Key Vault; `Storage Blob Data Contributor` on both identities on Storage; `AcrPull`/`AcrPush` split correctly on Container Registry. No drift.

## Storage containers — confirmed intact

`uploads`, `evidence-exports`, `authorization-receipts` all present on `stprstagingadzg`, private access, RBAC-gated, unchanged since Milestone 4.

## PostgreSQL — production-shaped but not production-populated

`psql-payreality-staging-cus`: `state: Ready`, schema at head, 35-day backup retention, PITR restore point available and drill-tested (Milestone 5). Structurally sound. Contains no real production data (see above).

**A second Postgres server also currently exists**: `psql-payreality-staging-cus-restoretest`, created during Milestone 5's backup-restore drill. It was left in place pending an explicit keep-or-delete decision that has still not been made. It plays no role in this milestone's cutover planning and is not a candidate for anything — flagged here only because it is real, billed infrastructure an auditor would otherwise wonder about.

## Monitoring, Alerting, Application Insights — confirmed intact

`terraform plan` against the live environment: **"No changes. Your infrastructure matches the configuration"** — zero drift since Milestone 5. Five metric alert rules present (`az monitor metrics alert list` → 5). Application Insights confirmed instrumented and previously observed receiving live telemetry (Milestone 5); not re-exercised with fresh traffic this audit since no code or config changed.

## Container App revisions — confirmed healthy

`ca-payreality-api-staging-cus` responds `200` on `/health` right now. Running the real application image (`staging-371906d`), not a placeholder. Revision history includes the two intentionally-failed test revisions from Milestone 5's rollback drill, correctly deactivated.

## Render production — confirmed untouched and live

`https://payreality-api.onrender.com/health` → `200`. `https://payreality.aisecurewatch.com` → `200`. No Render resource has been modified, deleted, or otherwise touched by this or any prior milestone.

## One more real gap this audit surfaced: CORS

`modules/container-apps/main.tf`'s `CORS_ORIGIN` is computed as `var.environment == "prod" ? "https://payreality.aisecurewatch.com" : "https://staging.payreality.aisecurewatch.com"`. Because the deployed environment's Terraform variable is `"staging"`, the Container App is currently configured to accept cross-origin requests only from `staging.payreality.aisecurewatch.com` — a hostname that doesn't exist in DNS (see above) — not from the real production frontend at `payreality.aisecurewatch.com`. If production traffic were pointed at this Container App today without changing this, the real frontend's requests would be rejected by CORS before reaching any application logic.

## Summary table

| Production dependency | Status |
|---|---|
| Azure environment exists | **No** — staging only |
| Production custom domain / DNS | **No** |
| Production SSL certificate | **No** |
| Production data in Azure Postgres | **No** — no migration mechanism exists |
| CORS configured for the real production origin | **No** — currently set for a non-existent staging hostname |
| Real Evidence signing key | Yes (Milestone 5) |
| Real Admin API key | Yes (Milestone 5) |
| Real Anthropic API key | **No** — disclosed placeholder |
| Managed Identity permissions | Yes, correct and least-privilege |
| Storage containers | Yes |
| Alerting | Yes, 5 rules, notification path tested |
| Application Insights | Yes, instrumented and previously confirmed receiving data |
| Backup / PITR | Yes, drill-tested with real data verification |
| Render production | Untouched, live, healthy |
