# Deployment

## Honest status, first

The frontend is live on Vercel today. **The backend is live on Render today** (see `GO_LIVE.md` for the original bring-up), reachable at `https://api.aisecurewatch.com`, which resolves via CNAME to Render behind Cloudflare.

A second, Azure-hosted backend has also been built, verified, and provisioned in parallel (`AZURE_MIGRATION/`), and is the designated target production platform. It is not yet cut over: no DNS record or Vercel environment variable currently points at it, and it is not ready to receive real traffic today for reasons that are specific and closing, not open-ended. See `MILESTONE_4_AZURE_PRODUCTION_READINESS_SUMMARY.md` for the full audit, what remains before cutover, and the retirement plan for Render once that happens. Until then, everything below describing Render as the live host remains accurate, and should be read alongside that document rather than instead of it.

## Hosting recommendation

### Now (zero-cost pilot/demo phase): Render, single free web service

Render's private services (needed for a separate OPA sidecar) have no free tier at all, confirmed directly by attempting to create one (`402 Payment Required`). For demonstrations and enterprise pilot conversations before there's billing set up, the deployed topology is instead:

| Requirement | How it's met at zero cost |
|---|---|
| Docker web service | `server/Dockerfile` on Render's `free` plan. |
| Policy evaluation (OPA) | Embedded in the same container as a loopback-only process (`server/entrypoint.sh` starts `opa run --server --addr 127.0.0.1:8181` alongside `uvicorn`), not a separate service. This is arguably *more* isolated than a private-service sidecar, not less: OPA is unreachable from any other service or the public internet outright, not just unreachable unless a security group is misconfigured (see SECURITY.md). |
| Database | The existing free-tier `payreality-db` Postgres instance, reused rather than provisioning a new one. |
| Cost | $0. |

**The real tradeoffs of this topology, stated plainly:**
- Render's free Postgres **expires 30 days after creation**. Fine for demos and pilot conversations happening within that window; not something to build a real customer's production data on. Re-provision or upgrade to a paid plan before that matters.
- Render's free web service **spins down after inactivity and cold-starts on the next request** (tens of seconds). A live demo hitting a cold instance is a real, visible risk, not a hypothetical one; if a demo is scheduled, hit `/health` a minute beforehand to warm it up.
- Both processes (OPA and uvicorn) share the free tier's memory/CPU limit. Adequate for pilot-conversation traffic volumes; not a load-bearing assumption at any real scale.

This is the deliberately simplest deployment that preserves the actual Runtime Authority architecture (real OPA, real Rego evaluation, nothing mocked), not a permanent architecture decision. Once billing is set up, moving OPA back out to its own private service (`SECURITY.md`'s original recommendation) is a Dockerfile/entrypoint revert, not a redesign.

**Alternatives considered:** Railway (comparable simplicity, historically less production-track-record for enterprise diligence); Fly.io (better for globally-distributed low-latency needs this product doesn't have yet); a bare AWS/Azure VM (more control, no matching increase in value at this stage: pure overhead).

`render.yaml` at the repo root reflects this zero-cost topology: one free web service, no separate OPA service, no `databases:` block (the existing free Postgres is adopted via a manually-set `DATABASE_URL`, not blueprint-managed). The actual deploy in this pass was done directly against Render's REST API rather than a Blueprint import, since Blueprint import requires the Render GitHub App to already have repository access; `render.yaml` stays here as the documented, re-appliable equivalent. `GO_LIVE.md` covers both paths.

### Once billing exists: Render, back to a separate OPA service

The original recommendation, unchanged in spirit: FastAPI web service + a private (non-public) OPA service + managed (paid, persistent) Postgres, all on Render's `starter` plan. Revert `server/Dockerfile`/`entrypoint.sh` to call out to `OPA_URL` instead of embedding OPA, and re-add the `payreality-opa` private service. Worth doing once there's a real pilot customer, since the free Postgres's 30-day expiry and the free web service's cold starts stop being acceptable the moment someone outside the company is relying on this.

### Series A / scale: AWS or Azure

**Update: the Azure half of this section is no longer hypothetical.** A full Azure environment (Container Apps, Postgres Flexible Server, Key Vault, Managed Identity, private networking, monitoring, staging and prod resource groups) has already been built and verified; see `MILESTONE_4_AZURE_PRODUCTION_READINESS_SUMMARY.md` for its current status and what remains before cutover. The description below is kept as the original rationale for choosing this path, not as a statement that it's still a future decision.

Whichever the majority of actual enterprise pilot customers already standardize on (worth asking rather than presuming), this is the point where infrastructure choices should follow the customer's compliance requirements, not the other way around:

- **Compute**: ECS Fargate (AWS) or Container Apps (Azure), same container images built here, no rewrite.
- **Database**: RDS Multi-AZ Postgres (AWS) or Azure Database for PostgreSQL Flexible Server, with automated backups and a read replica once read load justifies it.
- **Secrets**: AWS Secrets Manager / Azure Key Vault for `EVIDENCE_SIGNING_KEY_B64` and `ADMIN_API_KEY`, ideally with the evidence signing key backed by a real HSM (KMS asymmetric signing key or Azure Key Vault HSM-backed key) rather than an env var, once the roadmap's key-rotation work lands (see VERSION_3_ROADMAP.md and SECURITY.md).
- **Networking**: private VPC/VNet, OPA and Postgres with no public IP at all, API behind an ALB/Application Gateway with WAF.

Don't build this before there's a customer whose procurement process requires it: it's real infrastructure debt either way, but taking it on early has no payoff yet.

## Environment variables

See `server/.env.example` for the authoritative, current list. Summary:

| Variable | Required in production | Notes |
|---|---|---|
| `ENVIRONMENT` | yes (`production`) | Enables strict boot-time validation (below) and HSTS. |
| `DATABASE_URL` | yes | `postgresql+psycopg://...`. Must point at the managed Postgres instance, not localhost. |
| `OPA_URL` | yes | Must be a private-network address, never public. |
| `EVIDENCE_SIGNING_KEY_B64` | yes | Generate once, store in the host's secret manager, never commit it. Losing this key means all historical Evidence becomes unverifiable; back it up as carefully as the database itself. |
| `EVIDENCE_SIGNING_KEY_ID` | yes | Human-readable identifier for the current key; changes only on a deliberate rotation (see roadmap). |
| `ADMIN_API_KEY` | yes | The operator credential: generate with `secrets.token_urlsafe(32)`, rotate if it ever leaks. |
| `ANTHROPIC_API_KEY` | recommended | Without it, document extraction falls back to a deterministic stub rather than real AI extraction: fine for testing, not for a real pilot document. |
| `INTENT_SIGNATURE_WINDOW_SECONDS` | no (default 300) | Widen only if agent clock skew is a known issue; narrowing tightens replay protection. |
| `CORS_ORIGIN` | yes | The frontend's real deployed origin. Refusing to boot with the `localhost` default in production is enforced in code (`app/main.py::_validate_production_config`). |
| `VITE_API_URL` (frontend, Vercel env var) | yes | The backend's real public URL. The frontend build fails closed to `/api` if unset, which will silently 404 in production if there's no matching Vercel rewrite, so this must be set explicitly for any real deploy. |

**Boot-time validation**: `server/app/main.py::_validate_production_config` refuses to start at all if `ENVIRONMENT=production` and any of `EVIDENCE_SIGNING_KEY_B64`, `ADMIN_API_KEY`, or a real `CORS_ORIGIN` are missing or left at their dev defaults. A misconfigured production deploy fails immediately and loudly, not partway through serving degraded traffic.

## CI/CD

`.github/workflows/ci.yml` runs on every push/PR to `main`: the full pytest suite, a Docker build of the server image (build-only, no registry push configured yet, since there's no deploy target to push *to*), and the frontend Vite build. Wiring an actual deploy step (Render's GitHub auto-deploy, or a `docker push` + Render/ECS deploy hook) is a five-minute addition once a host is chosen and provisioned; it's deliberately not built ahead of having somewhere to point it.

Recommended flow once a host exists: Render's native GitHub integration (deploy on push to `main` after CI passes) rather than a custom deploy script, one less thing to maintain.

## Migrations

Alembic, `server/alembic/`. `server/Dockerfile`'s `CMD` runs `alembic upgrade head` before starting `uvicorn`: a failed migration aborts the container start rather than serving traffic against a schema it doesn't match. For a zero-downtime deploy with more than one instance, this needs to change to a separate migration step that runs once before the new instances start (Render's "pre-deploy command," or a dedicated migration job) rather than running redundantly in every instance's entrypoint.

## Rollback

- **Application code**: redeploy the previous image tag/commit. No database migration is required for most rollbacks since Alembic migrations here are additive to date.
- **Policy**: reactivate the previously-active Policy version via `POST /v1/policies/{id}/activate`; this *is* the rollback mechanism, not a separate feature (see ARCHITECTURE.md).
- **Database schema**: `alembic downgrade -1`, tested against a staging copy first. Not yet exercised against production data because there is no production database yet: do this exercise before the first real migration that isn't purely additive.

## Monitoring, logging, backups

- **Logging**: structured JSON to stdout (`app/logging_config.py`), one line per request (`app/security.py::observability_middleware`) including a request id, method, path, status, and duration. Ready to ship to any log aggregator that reads stdout (Render's built-in log viewer today; a real aggregator like Axiom/Datadog once volume justifies it).
- **Health/readiness**: `/health` (liveness, no dependency calls) and `/health/ready` (checks Postgres and OPA live, each bounded to a hard 3-second deadline via a worker thread). Two real bugs were caught and fixed here by actually timing the endpoint against an unreachable database, not by assuming the config was sufficient: first, the original check had no connect timeout at all and could hang indefinitely; then, after adding a `connect_timeout=5` to the database engine, the endpoint still took 14.7 seconds in practice, because psycopg retries every address a hostname resolves to (e.g. both `::1` and `127.0.0.1` for `localhost`), each getting its own 5-second budget. Wrapping each check in `ThreadPoolExecutor` with `.result(timeout=3)` bounds the HTTP response itself regardless of how many addresses get tried underneath; it now fails in 4.6 seconds. Point the host's health check at `/health` and any alerting/orchestration logic that should avoid routing traffic at `/health/ready`.
- **Smoke test**: `scripts/smoke_test.py` runs the full Runtime Authority pipeline (health, readiness, create a Principal and Agent, submit a real signed Intent, resolve it if needed, verify the resulting Evidence, check the public verification key, read real Assurance counts) against any deployed instance and exits non-zero on any failure. Run it once after every deploy: `PAYREALITY_API_URL=https://api.aisecurewatch.com PAYREALITY_OPERATOR_KEY=<the deployed ADMIN_API_KEY> python scripts/smoke_test.py`. Its HTTP and cryptographic-signing mechanics were verified locally (real `/health` calls, real ED25519 signing); the operator-gated and database-dependent stages were not runnable end-to-end in the environment this was written in, since no live Postgres was available there, so this script is the actual first full validation once a real instance exists.
- **Backups**: Render managed Postgres includes automated daily backups + point-in-time recovery on paid tiers; enable this explicitly when the database is provisioned, don't assume a default tier includes it.
- **SSL/domains**: Render (and Vercel, already) issue and renew TLS automatically for custom domains; no manual certificate management needed at this stage.

## Scaling

Not a near-term concern at pilot volume. When it is: the rate limiter is in-process memory (correct for one instance, a no-op across several; see ARCHITECTURE.md's known gaps), and the database connection pool (`server/app/db/session.py`) would need pool-size tuning under real concurrent load. Both are cheap, well-understood fixes to make when there's actual traffic to justify them, not before.
