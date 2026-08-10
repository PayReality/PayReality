# Sprint 1, Part 1 — Production Infrastructure Assessment

**Status:** final. **Method:** direct inspection of `render.yaml`, `docker-compose.yml`, `vercel.json`, `server/app/config.py`, `server/app/main.py`, `server/app/security.py`, `server/.env.example`, `.github/workflows/ci.yml`, and the root operational documents (`DEPLOYMENT.md`, `GO_LIVE.md`, `PRODUCTION_CHECKLIST.md`, `OPERATIONS_RUNBOOK.md`), this session, against the current `main` branch. This document states what exists, not what is planned — the Blueprint (Part 2) is where planning happens.

## Hosting

- **Backend**: Render, one free-tier web service (`payreality-api`), Docker runtime, deployed from `server/Dockerfile`. Live at a custom domain (`https://api.aisecurewatch.com`, per `GO_LIVE.md`) with a valid TLS certificate.
- **OPA**: runs **embedded in the same container** as the API (`server/entrypoint.sh`), bound to loopback only — not a separate service. This is a deliberate, documented zero-cost choice: Render's private services have no free tier at all (confirmed by the team hitting a `402 Payment Required` when attempting to create one).
- **Frontend**: Vercel, a single SPA rewrite (`vercel.json`) with no environment-specific configuration beyond that.
- **`render.yaml` exists but has never been applied as a Render Blueprint** — the real deployment was performed imperatively against Render's REST API, service by service. The file is documentation of intent, not the actual provisioning mechanism today.

## Databases

- **Postgres**: one instance, `payreality-db`, on Render's **free tier**. `GO_LIVE.md` and `render.yaml` both state it **expires 2026-08-24** (Render's free-tier 30-day limit) — this is the single most time-sensitive fact in this assessment.
- No read replica, no connection pooling layer (PgBouncer or equivalent), no separate analytics/reporting database.
- Migrations are Alembic, applied manually (no evidence of an automated migration-on-deploy step in CI or `render.yaml`).

## Storage

- **No object storage service exists anywhere in this stack.** Uploaded documents (AI Policy Builder, AI Authority Builder) are read as raw bytes and stored directly in a Postgres column (`PolicyExtractionUpload.content`, confirmed directly in `ai_policy_builder_service.create_upload`) — not S3, not a blob store, not the filesystem.
- This is tolerable at today's pilot volume and consistent with "prefer simplicity" — but it means every uploaded document permanently grows the primary database and travels inside every database backup, with no independent lifecycle or retention policy of its own.

## Networking

- The backend and OPA share one container's network namespace; OPA is unreachable from outside that container by construction (not by a firewall rule that could be misconfigured).
- CORS is a single configurable origin (`CORS_ORIGIN`), enforced by FastAPI's `CORSMiddleware`, allowing `GET/POST/PATCH/PUT/DELETE` and exactly the headers this API actually uses.
- No CDN, no WAF, no DDoS mitigation layer in front of either service beyond whatever Render/Vercel provide by default at their respective free/entry tiers.

## Authentication

Four independent mechanisms, all already live (confirmed directly in `security.py`, `dependencies.py`, `domain/rbac/permissions.py`):
1. Agent request signatures (ED25519, per-request, replay-windowed).
2. A single shared operator API key (`ADMIN_API_KEY`), constant-time compared.
3. Human login + session (bcrypt password hashing, session-bearer tokens, database-revocable).
4. Per-developer API keys, SHA-256 hashed at rest, role-scoped via RBAC.

## Secrets

Handled via environment variables through `pydantic-settings` (`server/app/config.py`), never hardcoded, never logged. `_validate_production_config()` refuses to boot at all under `ENVIRONMENT=production` if `EVIDENCE_SIGNING_KEY_B64`, `ADMIN_API_KEY`, or a non-default `CORS_ORIGIN` is missing — a real, enforced boot-time guard, not just documentation. Full audit and gaps: [04_SECRETS_MANAGEMENT_GUIDE.md](04_SECRETS_MANAGEMENT_GUIDE.md).

## Backups

Render's managed Postgres includes automated daily backups and point-in-time recovery **on paid tiers only** — the current free-tier instance does not have this. `OPERATIONS_RUNBOOK.md` states directly that no restore has ever been exercised against this schema. No backup exists for the frontend (Vercel deployments are themselves the artifact; no separate backup is meaningful there) or for uploaded-document bytes beyond whatever the Postgres backup covers.

## CI/CD

`.github/workflows/ci.yml`, three jobs, triggered on every push to `main` and every pull request:
1. `server-tests` — installs the backend, installs a pinned OPA v1.7.1 binary (so the real OPA-integration suite runs rather than silently skipping), runs `pytest`.
2. `server-image` — Docker build of the server image only (no registry push).
3. `frontend-build` — `npm ci && npm run build`.

**No CD exists.** Every actual deploy to Render or Vercel today is a manual, imperative action. There is no automatic promotion of a passing build to any environment.

## Environments

**Exactly one environment exists: production.** There is no staging deployment of either the backend or the frontend anywhere. Local development uses `docker-compose.yml` (Postgres + OPA + the API, wired together) plus Vite's dev server for the frontend — a real, working local topology, but it is the only alternative to production that exists today.

## Observability

- Structured JSON request logging (`logging_config.py`, one line per request: `request_id`, `method`, `path`, `status`, `duration_ms`), emitted via `security.py::observability_middleware`.
- `/health` (liveness, no dependency calls), `/health/ready` (checks Postgres and OPA live, each bounded by an explicit timeout so a hung dependency can't hang the health check itself), and `/version` (reports the running build's commit, via Render's `RENDER_GIT_COMMIT`).
- A synthetic end-to-end smoke test (`scripts/smoke_test.py`) exists but runs manually, not on a schedule.
- **No APM, no error tracking, no metrics, no tracing, no alerting/paging, and no external status page exist anywhere.** Confirmed by exhaustive search in the prior product audit ([`PRODUCT_ROADMAP/03_PRODUCT_GAP_ANALYSIS.md`](../03_PRODUCT_GAP_ANALYSIS.md)) and re-confirmed here: zero Sentry/Datadog/OpenTelemetry/Prometheus references anywhere in `server/`.

## Every production risk identified

Ranked by urgency:

1. **The production database expires 2026-08-24.** Dated, absolute, unrelated to code quality. Highest-priority item in this entire sprint.
2. **No backups exist for the current database at all** (free tier has none) — until #1 is resolved onto a paid tier, there is no recovery path from any data-loss event, accidental or otherwise.
3. **No staging environment** — every deploy ships directly to the only environment that exists, with no rehearsal.
4. **No alerting** — a production outage (database, OPA, or the API process itself) produces no page to anyone; it would be discovered only when someone happens to look, or a customer reports it.
5. **No CD** — every deploy is a manual, unscripted action against Render's/Vercel's API, with no audit trail of who deployed what, when.
6. **Single shared operator key** as a full-bypass credential with no rotation mechanism (detailed in [04_SECRETS_MANAGEMENT_GUIDE.md](04_SECRETS_MANAGEMENT_GUIDE.md)).
7. **No object storage** — uploaded document bytes live in the primary database, growing its size and backup footprint indefinitely, with no lifecycle policy. Tolerable today; a real constraint at higher volume.
8. **No DR drill ever performed** — even once #2 is fixed by moving to a paid tier with backups, nobody has verified a restore actually works against this schema.
