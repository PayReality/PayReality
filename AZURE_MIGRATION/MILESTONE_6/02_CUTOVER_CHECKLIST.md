# Milestone 6: Production Cutover Checklist

Every item's status is drawn directly from `01_PRODUCTION_AUDIT.md`'s live findings. "Ready" means verified working now. "Not ready" means a real, specific gap with no ambiguity about what closes it.

## Production DNS

**Not ready.** No `api.*` (or equivalent) DNS record exists for the backend at all — the current frontend calls Render's raw `.onrender.com` hostname directly. Before cutover, a decision is needed: bind a new custom domain to the Azure Container App, or point the frontend's `VITE_API_URL` at the Container App's default `*.azurecontainerapps.io` hostname directly. Neither has been done.

## SSL certificates

**Not ready.** Zero certificates provisioned on the Azure side (`az containerapp hostname list` → empty). A managed certificate cannot be issued without a custom domain decision (above) resolved first — this item is blocked by the DNS item, not independent of it.

## Environment variables

**Partially ready.** `ENVIRONMENT=production`, `ADMIN_API_KEY`, `EVIDENCE_SIGNING_KEY_B64/_ID`, `DATABASE_URL` are all real and correct for the deployed environment. **`CORS_ORIGIN` is wrong for real production traffic** — it currently resolves to `https://staging.payreality.aisecurewatch.com` (a nonexistent hostname) because the deployed Terraform environment is `"staging"`, not `"prod"`. **`ANTHROPIC_API_KEY` is still a placeholder.**

## Key Vault secrets

**Ready, with one disclosed exception.** Five of six secrets are real and validated (Milestone 5). `anthropic-api-key` remains `PENDING-MILESTONE-5-MANUAL-ENTRY` — a third-party credential, not something this program can generate.

## Managed Identity permissions

**Ready.** Confirmed unchanged and correct: least-privilege role assignments on Key Vault, Storage, and Container Registry, verified live this milestone.

## Storage containers

**Ready.** `uploads`, `evidence-exports`, `authorization-receipts` all present, private, RBAC-gated.

## PostgreSQL production database

**Not ready — the most significant gap in this checklist.** The server itself is healthy, backed up, and PITR-capable, but **it contains none of Render's actual production data**, and no tooling exists anywhere in this codebase to move it. This is not a configuration step that was skipped; it is a capability that has never been built. Standing up Azure's database schema is done — populating it with the real records production traffic depends on is not.

## Database backups

**Ready.** 35-day retention, geo-redundancy correctly disabled for a non-geo-redundant tier, a real PITR restore point available, and a full restore drill already performed and data-verified (Milestone 5) — the strongest-evidenced item on this entire checklist.

## Monitoring

**Ready.** Log Analytics confirmed ingesting live container logs and platform diagnostic logs; zero Terraform drift as of this audit.

## Alerting

**Ready, with one noted test-coverage caveat carried from Milestone 5.** Five rules deployed against real metrics; the notification path itself is proven (a real test email was sent and confirmed delivered). Two of the five rules were not organically triggered in live testing (documented in Milestone 5 as a coverage gap, not a configuration defect).

## Application Insights

**Ready.** Instrumented via OpenTelemetry, confirmed receiving real telemetry in Milestone 5. Not re-exercised with fresh traffic this milestone since nothing changed that would affect it.

## Container App revisions

**Ready.** Current revision healthy and serving the real application image. Revision history is clean (the two intentional failure-test revisions from Milestone 5 are deactivated, not deleted, consistent with this program's no-deletion rule).

## Rollback strategy

**Documented and tested, but only for an Azure-internal failure (Milestone 5's bad-image-deploy drill).** A rollback scenario where **production DNS has already moved to Azure and then needs to revert to Render within minutes** has not been tested, because DNS has never pointed at Azure in the first place. See `04_ROLLBACK_RUNBOOK.md` for what this would require.

## Checklist summary

| Item | Status |
|---|---|
| Production DNS | Not ready |
| SSL certificates | Not ready (blocked by DNS decision) |
| Environment variables | Partially ready (CORS wrong, Anthropic key placeholder) |
| Key Vault secrets | Ready except Anthropic key |
| Managed Identity permissions | Ready |
| Storage containers | Ready |
| PostgreSQL production database | **Not ready — no production data** |
| Database backups | Ready |
| Monitoring | Ready |
| Alerting | Ready (with disclosed test-coverage caveat) |
| Application Insights | Ready |
| Container App revisions | Ready |
| Rollback strategy | Documented for Azure-internal failure only; DNS-reversion scenario untested because DNS has never moved |
