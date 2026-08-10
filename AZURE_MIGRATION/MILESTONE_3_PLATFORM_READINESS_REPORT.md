# Milestone 3: Platform Readiness Report

## Is the platform ready to host a functioning environment?

**Yes**, for the scope this milestone defined: a real, running Azure environment proven to boot the actual application, not a placeholder. It is **not** ready for production cutover — that was never this milestone's goal, and several deliberate gaps (below) remain by design.

## Evidence the platform actually works, not just that resources exist

Provisioning success (`terraform apply` returning `0 errors`) proves resources were created. It does not prove they work together. This milestone verified the difference:

1. **The real application container starts, not a placeholder.** `mcr.microsoft.com/k8se/quickstart` was replaced with the built `payreality-api` image; the running revision serves real `/health` and `/health/ready` responses.
2. **OPA runs embedded, unmodified, exactly as designed.** Container logs show OPA initializing on `127.0.0.1:8181` (loopback-only, per `server/Dockerfile`'s existing design) and the readiness probe genuinely round-tripping through it (`httpx` log line: `GET http://localhost:8181/health "HTTP/1.1 200 OK"`). No redesign was needed or attempted.
3. **The database connection is real, not assumed.** Alembic ran all 18 migrations from empty schema to head against the live Postgres Flexible Server at startup — this only succeeds if the managed identity, the Key-Vault-backed `DATABASE_URL` secret, the private endpoint, and the VNet delegation are all correctly wired together. A `terraform plan` showing "0 to change" cannot prove this; a real migration run can.
4. **Secrets flow through managed identity, not a shared key.** The Container App resolved `database-url` from Key Vault via its own identity with zero credential ever appearing in Terraform state, a pipeline log, or an environment variable in plaintext.
5. **The platform rejects what it should reject.** Unauthenticated calls to Key Vault (`401`) and Storage (`409`) confirm the identity-first security model is a real control, not a config comment.

## What is explicitly not ready, by design

- **No real Evidence signing key** — placeholder value, Milestone 5's job (see Known Issues #1).
- **No application-level APM telemetry** — Log Analytics receives platform logs; Application Insights does not yet receive app-level traces (Known Issues #2).
- **No alert rules** — explicitly out of this milestone's scope.
- **No production data, no DNS change, no customer traffic** — explicitly forbidden by this milestone's own rules; Render remains production.

## Recommendation

Proceed to Milestone 4 planning once this report is approved. Before any production cutover consideration, resolve: the real Evidence signing key (Milestone 5), a decision on Application Insights instrumentation, and confirmation that `prod.tfvars` picks up the same collision-resistant Key Vault naming this milestone introduced for staging.
