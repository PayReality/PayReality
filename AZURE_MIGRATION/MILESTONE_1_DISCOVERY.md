# Azure Production Migration Program — Milestone 1: Discovery

**Status:** final. **Scope:** read-only. No production code, configuration, or cloud resource was modified or created to produce this document. **Method:** direct inspection of `server/Dockerfile`, `server/entrypoint.sh`, `render.yaml`, `docker-compose.yml`, `vercel.json`, `.github/workflows/ci.yml`, `server/app/config.py`, plus a live, read-only check of local Azure CLI access — not carried forward from any earlier session's memory.

## Current architecture

- **Compute**: one Render free-tier web service (`payreality-api`), Docker runtime, one container. That container runs **two processes**, not one: OPA (`opa run --server --addr 127.0.0.1:8181`, loopback-only, no auth of its own — deliberately unreachable from outside the container) and the FastAPI app (`uvicorn`), started by `entrypoint.sh` in that order, with OPA's own health endpoint polled before the API starts.
- **Startup sequence** (from `entrypoint.sh`, verified directly): start OPA → poll its `/health` up to 10 seconds → run `alembic upgrade head` → start `uvicorn`. A failed migration aborts the container's startup entirely — it never serves traffic against a schema it doesn't match.
- **Database**: one Render-managed Postgres instance (`payreality-db`), free tier, no backups, **expires 2026-08-24** (unchanged since Sprint 1's assessment — this has not been resolved).
- **Frontend**: Vercel, a single-page app, unrelated to Render. **Not mentioned anywhere in this program's milestones** — see "Scope boundary" below.
- **Storage**: none separate from the database — uploaded document bytes are a Postgres column (`PolicyExtractionUpload.content`), confirmed in Sprint 1.
- **Secrets**: environment variables in Render's own store (`DATABASE_URL`, `EVIDENCE_SIGNING_KEY_B64`/`_ID`, `ADMIN_API_KEY`, `ANTHROPIC_API_KEY`, `CORS_ORIGIN`), `sync: false` in `render.yaml` (never committed).
- **CI**: GitHub Actions (`.github/workflows/ci.yml`) — backend tests + OPA-integration tests (pinned OPA v1.7.1 binary installed in the runner), a Docker build (image never pushed anywhere), and a frontend build. **No CD** — every deploy today is a manual, imperative call against Render's/Vercel's own REST APIs.
- **Container image**: `python:3.12-slim` base, OPA binary downloaded and pinned at build time (`ARG OPA_VERSION=1.7.1`, matching CI's pinned version), runs as a non-root user (`uid 1000`), has a `HEALTHCHECK` directive against `/health`.
- **IaC**: `render.yaml` exists but **has never been applied as a Render Blueprint** — the real deployment was provisioned imperatively, service by service, against Render's REST API. This repository has **zero applied Infrastructure as Code today**, for any provider.

## Scope boundary — flagged, not assumed

Every milestone in this program describes backend concerns (API, database, storage, secrets, monitoring, "the policy engine," "evidence generation"). **Vercel/the frontend is never named.** This document assumes the frontend **stays on Vercel** and only the backend (API, database, OPA, storage, secrets) migrates to Azure — consistent with "the application itself is not being rewritten" and "migrate infrastructure, not redesign the product." If frontend hosting should also move (e.g., to Azure Static Web Apps), that needs to be stated explicitly, since nothing in the current instructions asks for it.

## Azure target architecture

| Current (Render/Vercel) | Azure equivalent | Why this one, not an alternative |
|---|---|---|
| Render Web Service (Docker) | **Azure Container Apps** | Runs the existing single container unchanged (including its two-process OPA+API pattern, or optionally split into a sidecar within the same Container App later — not required for a like-for-like migration). Deliberately **not AKS**: this is one container serving pilot-scale traffic; a Kubernetes cluster would be exactly the unnecessary technology and speculative architecture this program's Absolute Rules forbid. Deliberately not plain App Service for Containers either: Container Apps is purpose-built for this exact shape (a containerized web workload with scale-to-zero and revision-based rollback) with less operational surface than App Service's fuller feature set, most of which this app doesn't need. |
| *(not currently a separate Render service — OPA is embedded)* | *(no separate Azure service — OPA stays embedded in the same container)* | Preserving the existing, deliberate, documented security property (OPA unreachable from outside the container) rather than "improving" it into a separate service nobody asked for. |
| Render Postgres | **Azure Database for PostgreSQL — Flexible Server** | Wire-compatible standard Postgres; the existing `postgresql+psycopg://` connection string scheme and every SQLAlchemy model/migration is unaffected. Flexible Server (not Single Server, which Microsoft has deprecated, and not Cosmos DB's Postgres-compatible API, which is a different product for a different scale problem) is the direct, current, boring choice. |
| *(document bytes in Postgres — no separate storage today)* | **Azure Blob Storage** | Only for Milestone 7, and only because the migration principles ask for a proper home for file bytes when one is being built anyway — not a requirement to do this before Milestone 7. |
| Render env vars, `sync: false` | **Azure Key Vault** + Container Apps secret references via **Managed Identity** | Removes the "secret value sits in a platform's env-var store" model entirely in favor of the app authenticating to Key Vault with its own identity — a real improvement Render's model didn't offer at all, not a lateral move. |
| *(no registry — Render builds directly from the Dockerfile)* | **Azure Container Registry** | Required the moment Container Apps is the compute target: Container Apps deploys a pre-built image, it doesn't build from a Dockerfile the way Render does. This is a structural dependency, not a nice-to-have — see "Gap found," below. |
| No APM/metrics/tracing today | **Application Insights + Azure Monitor + Log Analytics** | Standard, first-party Azure trio for exactly this: App Insights for request/dependency telemetry and error tracking, Azure Monitor for alert rules on top of it, Log Analytics as the query/retention backend both write to. One coherent set, not three competing tools. |
| *(no VNet — Render's networking is opaque/managed)* | **Azure Virtual Network**, with Postgres on a **private endpoint** | The one place this migration is a real security improvement over today's Render topology: the database becomes unreachable from the public internet at all, reachable only from inside the VNet the Container App is injected into — tightening, not just replicating, the existing "OPA is loopback-only" security instinct already present in this codebase. |
| GitHub Actions (test-only) | **GitHub Actions, extended** | The existing `server-tests` job is reused unchanged; new jobs are added (build + push to ACR, deploy to Container Apps) rather than replacing the CI system with an Azure-native one (Azure DevOps Pipelines). Introducing a second CI system would itself be unnecessary technology. |

## Gap found during discovery, worth stating precisely

Milestone 2's own service list (Resource Groups, Networking, PostgreSQL, Blob Storage, Key Vault, **Container Registry**, Application Insights, Azure Monitor, Log Analytics, Identity) names a registry to *store* the container image but nothing to *run* it. Without a compute service (Azure Container Apps, per the table above), Milestone 6 ("Backend Deployment") would have nowhere to deploy to. This document adds **Azure Container Apps** (plus its required **Container Apps Environment**, which itself needs the VNet from the Networking line item) to Milestone 2's provisioning list as a corrected dependency, not a scope expansion — it's the one service the stated milestone structure implies but doesn't name.

## Migration risks

1. **Timing collision with the Render database's free-tier expiry (2026-08-24).** This program's own principle — "Render remains the production environment until Azure is verified" — assumes Render stays healthy throughout. Ten milestones, each individually gated on manual approval, will very plausibly take longer than the time remaining before that expiry. **This is the most urgent finding in this document**: either Render's database needs the same paid-tier upgrade already scoped as Sprint 1's Task T1 (as a bridge, independent of whether Azure ultimately replaces it), or this Azure migration needs to reach at least Milestone 4 (database live on Azure) before 2026-08-24 — and Milestone 1 alone cannot make that guarantee.
2. **Azure CLI access exists but its cached login has expired and now requires interactive MFA.** Verified directly: `az account show` returned a previously-authenticated subscription (`Azure subscription 1`), but `az group list` failed with `AADSTS50076` (interactive multi-factor authentication required). **No resource can be provisioned from this environment until a human runs `az login` interactively.** This blocks Milestone 2's actual `terraform apply`/`az` execution (though not Milestone 2's IaC authoring, which requires no live Azure connection) and must be resolved before Milestone 3.
3. **TLS/SSL connection parameters for Postgres will need verification, not assumption.** Azure Database for PostgreSQL enforces SSL by default; the current `postgresql+psycopg://` connection strings don't specify `sslmode`. This is a small, mechanical compatibility check (Milestone 4), not a redesign — flagged now so it isn't discovered as a surprise mid-migration.
4. **The embedded-OPA-in-one-container pattern must be preserved deliberately, not "fixed."** A future engineer (or an AI agent) unfamiliar with why OPA is embedded could "improve" this into a separate Azure Container App during the migration, silently reintroducing the exact two-writer/network-exposure risk this codebase's own `SECURITY.md` and `entrypoint.sh` comments went out of their way to avoid. Named here so Milestone 6 doesn't relitigate it.
5. **Cost is bounded but not yet precisely estimated.** Container Apps (consumption plan), Postgres Flexible Server (Burstable tier is proportionate to today's traffic), a Standard storage account, Key Vault, and Application Insights are all low-cost services at pilot scale — comfortably inside the ~$5,000 credit on general knowledge of current Azure pricing, but this document does not commit to an exact number. Milestone 2 should validate real pricing via `az` or the Azure Pricing Calculator before provisioning, not rely on this estimate.
6. **Data volume is small enough that Azure Database Migration Service would be disproportionate.** A direct `pg_dump`/`pg_restore` (or Azure's simpler "migrate" tooling built for this exact size of database) is the right-sized tool for Milestone 4 — confirmed by the same reasoning Sprint 1 already applied to backups: match the tool to the actual data volume, not to what a much larger migration would need.

## Migration dependencies (what must exist before what)

- Resource Group → everything else (Azure's own hard requirement).
- Virtual Network + Container Apps Environment → Container Apps, and → Postgres's private endpoint.
- Key Vault + Managed Identity → Milestone 5 (secrets) and → Milestone 6 (the app needs its identity wired before it can read secrets at startup).
- Container Registry → Milestone 6 (nothing to deploy without an image to pull).
- Postgres Flexible Server → Milestone 4.
- Blob Storage → Milestone 7 only (not required earlier).
- Application Insights / Monitor / Log Analytics → provisioned in Milestone 2, actually wired into the app and given alert rules in Milestone 8 — provisioning and configuration are different milestones deliberately, not the same step.
- Interactive `az login` (human, MFA) → any milestone that actually touches Azure (3 onward; Milestone 2's authoring doesn't require it).

## Required Azure services (corrected list, per the gap found above)

Resource Groups, Virtual Network (+ Container Apps Environment), Azure Database for PostgreSQL Flexible Server, Azure Blob Storage, Azure Key Vault, Azure Container Registry, **Azure Container Apps**, Application Insights, Azure Monitor, Log Analytics, Managed Identity + RBAC role assignments.

## Implementation order (Milestones 2 onward, as already specified)

The existing 10-milestone structure is sound and is not being reordered — direct inspection found nothing that makes a different milestone order objectively safer, other than the single cross-cutting risk (#1 above) that needs resolving in parallel, not by reordering. Recommended immediate parallel action, not a reordering of this program: resolve Sprint 1's Task T1 (Render database paid-tier upgrade) independently and concurrently, since it protects the "Render stays online as the safety net" assumption this entire program depends on, regardless of how long the Azure migration itself takes.

## Not done in this milestone

No Azure resource was created. No Terraform/Bicep file was written. No production code was modified. No deployment occurred. `az login` was not attempted interactively (requires the user's own MFA device).
