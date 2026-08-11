# Production Cutover Program — Phase 1: Production Environment Audit

**Method:** every finding below is from a live command run today, against the real subscription, DNS, and running services — re-verifying `AZURE_MIGRATION/MILESTONE_6/01_PRODUCTION_AUDIT.md`'s findings from the immediately preceding session rather than assuming they still hold. Nothing was modified during this audit.

## Does an Azure production environment exist?

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

**No.** Unchanged from the prior audit. The only application environment in this subscription is `rg-payreality-staging-cus`, built from `environments/staging.tfvars` (Terraform `environment = "staging"`). `environments/prod.tfvars` has never been applied. This directly determines the answer to this phase's own question ("verify Azure production environment exists, or determine if staging will become production") — it does not exist, so if this program proceeds, the decision to make is whether the existing staging environment is promoted to serve as production, or a genuinely separate production environment is built. That decision has not been made and this audit does not make it unilaterally.

## DNS ownership and custom domains

```
dns.google resolve api.payreality.aisecurewatch.com → NXDOMAIN (Status: 3)
dns.google resolve payreality.aisecurewatch.com → 76.76.21.21 (Vercel, the frontend, unrelated to backend cutover)
az containerapp hostname list --name ca-payreality-api-staging-cus → []
```

No DNS record for a backend API domain exists at all. The Azure Container App has zero custom domains bound. **TLS certificates**: none exist on the Azure side because there is no custom domain to issue one for — the Container App's only reachable hostname is its default `*.azurecontainerapps.io` address, which does carry a valid Microsoft-issued certificate for that hostname specifically.

## Environment variables / CORS

`CORS_ORIGIN` on the Container App is computed from `var.environment == "prod" ? "https://payreality.aisecurewatch.com" : "https://staging.payreality.aisecurewatch.com"`. Because the deployed environment is `"staging"`, it currently resolves to a hostname with no DNS record. Unchanged since the prior audit — not re-derived today because zero Terraform drift was confirmed (below), so nothing could have changed it.

## Key Vault secrets

```
az keyvault secret list --vault-name kv-pr-staging-lu2swm --query "[].name"
```
Six secrets present: `database-url`, `postgres-administrator-password`, `evidence-signing-key-b64`, `evidence-signing-key-id`, `admin-api-key`, `anthropic-api-key`. The first five are real, non-placeholder values (installed and validated in the prior Milestone 5). `anthropic-api-key` remains `PENDING-MILESTONE-5-MANUAL-ENTRY` — confirmed unchanged today.

**On the signing-key startup error specifically**, since a debugging request about it was raised immediately before this program began: queried Log Analytics directly for the most recent signing-key-related log lines. The current, most recent entry is:
```
{"timestamp": "2026-08-11T00:15:57Z", "level": "INFO", "logger": "payreality.signing_keys",
 "message": "signing_key_registered key_id=signing_key_azure_prod_v1"}
```
Every `signing_key_registration_failed_at_startup` / `binascii.Error: Incorrect padding` entry in the log is timestamped *before* this success line, from the incident that was root-caused and fixed during Milestone 5 (a `cut -d= -f2` bash extraction bug that silently truncated the trailing `=` padding character of a base64 value — documented in `AZURE_RUNBOOK.md`'s "Setting a real secret" section). It has not recurred since. This is not currently an active defect.

## Managed Identity permissions

Confirmed unchanged via live role-assignment listing: least-privilege roles intact on Key Vault (`Key Vault Secrets Officer` / `Key Vault Secrets User`), Storage (`Storage Blob Data Contributor` ×2), and Container Registry (`AcrPull`/`AcrPush` split). No drift.

## Storage access

`uploads`, `evidence-exports`, `authorization-receipts` containers all present, private, RBAC-gated — unchanged.

## PostgreSQL backups / PITR status

35-day retention, real restore point available, a full restore drill already performed and data-verified in Milestone 5 (not repeated today — no reason to suspect regression, and repeating a restore drill is a real-cost action this audit did not judge necessary to re-run for a status check).

## Container revisions, monitoring, alerts, dashboard, OpenTelemetry

- **Container App**: `/health` → `200`, confirmed live today.
- **Terraform drift**: `terraform plan -detailed-exitcode` → exit `0`, *"No changes. Your infrastructure matches the configuration."* Confirmed live today.
- **Monitoring / Alerts / Dashboard / App Insights**: not independently re-exercised with fresh synthetic tests this audit (Milestone 5 already proved each with live data, and zero Terraform drift means the underlying resources are unchanged) — re-confirmed only that the alert rule count is still 5 and the dashboard resource still exists.

## Scaling rules, health/readiness/liveness probes

Unchanged from Terraform (`http_scale_rule.concurrent_requests = 50`, `max_replicas = 3`, `min_replicas = 0` for staging); `/health` (liveness) and `/health/ready` (readiness, genuinely checks DB + OPA) both confirmed responding correctly today.

## Render production

```
curl https://payreality-api.onrender.com/health → 200 (7.6s -- cold start after idle, consistent with free-tier behavior documented since Milestone 4)
curl https://payreality.aisecurewatch.com → 200
```
Live, healthy, and untouched. No Render resource has been modified by any part of this program.

## Data migration tooling

Re-searched the repository for `pg_dump`, `pg_restore`, or any Render-to-Azure data export/import script: **none exists**, beyond Alembic's own schema migrations (which move schema, not data) and one unrelated code comment about a hypothetical future *agent-record* bulk-import tool in `server/app/services/agent_service.py` that has nothing to do with this migration.

## Phase 1 conclusion

Every finding from the immediately preceding Milestone 6 audit is reconfirmed, unchanged, live, today. The signing-key error that prompted a debugging request at the start of this session is confirmed historical and already resolved — not a live blocker. **The two disqualifying gaps remain: no Azure production environment exists, and no data migration mechanism exists.** Per this program's own Completion Gate ("stop immediately if any production verification fails"), this is exactly such a failure, evaluated honestly rather than assumed past.
