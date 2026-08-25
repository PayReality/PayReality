# Production Readiness Checklist

Every item below is either genuinely done (checked, with where to verify it), or an explicitly named gap (unchecked, with why it's not done yet and where it's scoped). Nothing here is checked because it's planned or partially started.

## Authentication

- [x] Agent-to-API authentication: ED25519 request signing, client-generated keys, never transmitted (`server/app/domain/auth/signature.py`).
- [x] Operator authentication on every state-mutating endpoint (`server/app/security.py::verify_operator_key`).
- [ ] Human user login / per-person identity. Doesn't exist. A single shared `ADMIN_API_KEY` stands in for it. Scoped in `VERSION_3_ROADMAP.md`'s Enterprise Pilot phase, the top-priority item there.

## Authorization

- [x] Endpoint-level authorization via dependency injection (`Depends(verify_operator_key)`), consistent across all routers.
- [ ] Row-level / per-tenant authorization. Not needed yet (single-tenant), a hard requirement before a second tenant (`VERSION_3_ROADMAP.md`'s Series A phase, `SECURITY.md`'s Authorization section).

## Secrets

- [x] Read from environment variables only, never hardcoded, never logged (`server/app/config.py`).
- [x] Boot-time validation refuses to start in production with missing/default secrets (`server/app/main.py::_validate_production_config`).
- [ ] Dedicated secrets manager on the live production path. Env vars via Render's own secret storage remain what's actually in front of production traffic today; an Azure Key Vault (RBAC-only, purge protection on) exists and is verified live in both Azure environments per `MILESTONE_4_AZURE_PRODUCTION_READINESS_SUMMARY.md`, but is not yet what production reads from until that document's cutover plan executes.

## Environment variables

- [x] Every required variable documented in `server/.env.example` and `DEPLOYMENT.md`'s table.
- [x] `render.yaml` wires all of them for today's live hosting path, with secrets marked `sync: false` so they're never committed. Azure's equivalent wiring (Key Vault-backed Container App secrets) is verified separately; see `MILESTONE_4_AZURE_PRODUCTION_READINESS_SUMMARY.md`.

## Logging

- [x] Structured JSON to stdout, one line per request, including a request id and duration (`server/app/logging_config.py`, `server/app/security.py::observability_middleware`).
- [x] Every unhandled exception logged server-side with full traceback, never leaked to the caller.

## Monitoring

- [x] Liveness and readiness endpoints (`/health`, `/health/ready`).
- [x] Readiness check bounded to a hard deadline (fixed during this pass: an unbounded connect timeout meant an unreachable database could take 14.7 seconds to report unready; now bounded to 4.6 seconds via a worker-thread timeout, see `DEPLOYMENT.md`).
- [x] Synthetic end-to-end monitor available (`scripts/smoke_test.py`) and run against the actual live production backend, 9/9 stages passed (see `GO_LIVE.md`); not yet wired to run on a schedule (see `OPERATIONS_RUNBOOK.md`).
- [ ] Real alerting (PagerDuty/Opsgenie-style paging on the conditions in `OPERATIONS_RUNBOOK.md`'s "what to actually watch"). Not wired yet; proportionate to add once there's an on-call rotation to page.

## Database migrations

- [x] Alembic, 4 migrations to date, all additive (no destructive schema changes yet).
- [x] Migrations run automatically before the API starts (`server/Dockerfile`'s `CMD`), and a failed migration aborts startup rather than serving traffic against a mismatched schema.
- [ ] Zero-downtime migration strategy for more than one instance (a separate pre-deploy migration step instead of running it in every instance's entrypoint). Not needed at single-instance pilot scale; scoped in `DEPLOYMENT.md`'s Migrations section.

## Error handling

- [x] Every unhandled exception caught and converted to a clean `{"detail": "internal_error"}` 500, never a stack trace to the client (`server/app/security.py::observability_middleware`).
- [x] Fixed a real bug during this pass: three separately stacked middleware layers were silently losing exceptions between them (a documented Starlette `BaseHTTPMiddleware` interaction), producing empty 500 bodies instead of clean ones. Consolidated into one middleware; verified via direct testing, not assumed.

## Health checks

- [x] `/health` (liveness) and `/health/ready` (readiness, checking real dependencies), see Monitoring above.

## Rate limiting

- [x] Fixed-window limiter, 120 requests/60s per client IP, applied globally (`server/app/security.py`).
- [ ] Shared-state backing (Redis or equivalent) for correctness across more than one instance. In-process memory is correct for the single-instance pilot deployment recommended in `DEPLOYMENT.md`, a real gap the moment a second instance exists; named explicitly rather than silently.

## CORS

- [x] Single explicit allowed origin from `CORS_ORIGIN`, not a wildcard, with an explicit method and header allowlist (tightened during this pass from `allow_methods=["*"]`).
- [ ] `CORS_ORIGIN` currently must be manually kept in sync with the frontend's actual production origin (`render.yaml`, `GO_LIVE.md` Step 4.3); no automatic sync exists, and doesn't need to for a single known frontend origin.

## API validation

- [x] Every request body validated by Pydantic schemas (`server/app/schemas/`); malformed input is rejected with FastAPI's standard `422` field-level errors before reaching any handler logic.

## OpenAPI documentation

- [x] Full OpenAPI schema auto-generated by FastAPI, exported to `docs/openapi.json`, documented in human-readable form in `docs/API_SPECIFICATION.md`, and served live at `/docs` and `/openapi.json` on any running instance.

## Versioning

- [x] Every business endpoint under `/v1`. No breaking changes have been made to it; the intended policy for a future `/v2` is additive versioning (both live simultaneously until callers migrate), documented in `docs/API_SPECIFICATION.md`'s Versioning section.

## Security headers

- [x] `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` on every response; `Strict-Transport-Security` added when `ENVIRONMENT=production` (`server/app/security.py::observability_middleware`).

## Evidence architecture (beyond the standard checklist, specific to this product)

- [x] ED25519 signing over a canonical (sorted-key, whitespace-free) JSON payload's SHA-256 digest.
- [x] Public verification key published (`GET /v1/evidence/verification-key`) so a third party never has to trust this server's own `/verify` result.
- [x] Signing-key rotation support: a real key registry keyed by `key_id` (the `signing_keys` table, `signing_key_service`), retained forever. Rotating `EVIDENCE_SIGNING_KEY_B64`/`_ID` and redeploying registers the new key and retires the old one automatically, without invalidating anything signed under a prior key. See `SECURITY.md` and `EVIDENCE_KEY_ROTATION.md`.
- [x] Cryptographic chaining between consecutive Evidence records for the same Decision: every new record embeds `previous_hash`, checked by `evidence_service.verify_chain`, which also detects a deleted or reordered record even when every remaining record's own signature still checks out. See `SECURITY.md`.

## Overall

**Live**: the backend is deployed and reachable at its production custom domain, `https://api.aisecurewatch.com`, with a verified TLS certificate (Google Trust Services, valid through October 2026), and the full Runtime Authority pipeline (Principal, Agent, signed Intent, Decision, signed Evidence, verification) has been exercised end-to-end against that domain directly, 9/9 stages passed (see `GO_LIVE.md`). The frontend's production build is confirmed pointing at it.

This platform is functionally ready for demonstrations and enterprise pilot conversations today. It is not ready for a real paying pilot's production data (the Postgres instance is free-tier and expires in 30 days) or multi-tenant production or a compliance audit until the unchecked items above are closed, most urgently human authentication, the evidence key registry, and upgrading off the free-tier database and web service, all already scoped with a specific roadmap phase rather than left open-ended.
