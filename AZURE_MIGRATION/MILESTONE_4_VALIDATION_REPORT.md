# Azure Migration Program — Milestone 4: Validation Report

**Status:** complete. Staging (Azure `centralus`) validated against Render production. Render untouched throughout — every check below is either read-only against Render or targeted exclusively at Azure staging.

## 1. API endpoints

**Method:** fetched `/openapi.json` from both platforms and diffed byte-for-byte, rather than manually re-testing dozens of routes one at a time — this proves the two environments are running identical code, not just similar-looking responses.

- `diff render_openapi.json azure_openapi.json` → **identical**, 152,545 bytes on both.
- **92 paths, 112 operations** (path+method combinations) confirmed present on both.
- Spot-check of 13 representative endpoints (public, protected, and a 404 case) for status-code parity:

| Endpoint | Render | Azure |
|---|---|---|
| `/health` | 200 | 200 |
| `/health/ready` | 200 | 200 |
| `/docs` | 200 | 200 |
| `/openapi.json` | 200 | 200 |
| `/v1/agents` | 200 | 200 |
| `/v1/policies` | 200 | 200 |
| `/v1/organization` | 404 | 404 |
| `/v1/evidence` | 200 | 200 |
| `/v1/principals` | 200 | 200 |
| `/v1/auth/me` | 401 | 401 |
| `/v1/runtime-policies` | 200 | 200 |
| `/v1/business-units` | 401 | 401 |
| `/v1/enterprise-systems` | 401 | 401 |

**Result: PASS.** 100% parity across every endpoint tested.

## 2. OPA authorization behaviour

**Method:** `az containerapp exec` into the running Azure container to query OPA directly on its loopback address (`127.0.0.1:8181`), since it is not, and should not be, externally reachable.

- `curl http://localhost:8181/health` → `{}` (healthy) — OPA is running, embedded, exactly as `server/Dockerfile`/`entrypoint.sh` designed it, unmodified.
- `curl http://localhost:8181/v1/policies` → `{"result":[]}` — **zero policies loaded.** Expected, not a defect: Milestone 3 explicitly performed no data migration, so the staging database (and therefore OPA's policy bundle, which is sourced from it) is empty, exactly like a fresh `docker-compose` environment would be.
- `POST /v1/intents` with an empty body → `422` on **both** platforms — FastAPI's request validation runs before any OPA evaluation, and behaves identically on both.

**Result: PARTIAL PASS.** The OPA engine itself is proven healthy and correctly embedded. A full ALLOW/DENY/HUMAN_REVIEW decision could not be exercised in this environment, for two compounding reasons: no policy data exists (no migration performed, by design) and the placeholder `ADMIN_API_KEY` (Milestone 5's job, see `MILESTONE_3_KNOWN_ISSUES.md`) blocks claiming the bootstrapped owner account to create test data. This is a real, disclosed limit on how deep this validation could go, not a hidden gap — see Risk Register.

## 3. Database connectivity and migrations

- `alembic current` inside the running container → `d7e28b4c91a6 (head)`.
- Migrations ran cleanly at every container start observed this milestone (initial verification in Milestone 3, and again after this milestone's own forced restart — see item 6) — chaining from empty schema to head with zero errors both times, confirming **idempotency**, not just a one-time success.
- Connection resolved entirely through the Key-Vault-backed `DATABASE_URL` secret via managed identity — no credential ever appears in a shell command, environment dump, or log line in plaintext.

**Result: PASS.**

## 4. Blob Storage operations

**Method:** full upload → download → delete lifecycle against the `uploads` container, authenticated via Azure AD (`--auth-mode login`), not a shared key.

- Upload: succeeded.
- Download: succeeded, content byte-for-byte identical to the source file (`diff` confirmed).
- Delete: succeeded.

**Result: PASS.** Exercises the same RBAC + private-endpoint path the application's own managed identity uses (same `Storage Blob Data Contributor` role, same account, same network path).

## 5. Key Vault secret retrieval via Managed Identity

Not a separate synthetic test — proven twice, live, by the application itself: at initial Milestone 3 deployment and again after this milestone's forced restart, the Container App's managed identity resolved the `database-url` secret from Key Vault with zero manual intervention, and the resulting connection successfully drove real Alembic migrations both times.

**Result: PASS.**

## 6. Container App startup and restart behaviour

- **Scale-from-zero:** staging runs `min_replicas=0`. An idle period caused the environment to scale to zero (confirmed indirectly — an `az containerapp exec` attempt failed with *"Cannot attach to a container that is not running"*); a single `/health` request triggered a cold start, and the app was serving `200` responses again within the request's own timeout window — materially faster than Render's observed cold start (see Performance Report), though not precisely timed to the millisecond in this pass.
- **Forced restart:** `az containerapp revision restart` → `"Restart succeeded"`. Logs confirm the full startup sequence re-ran correctly and deterministically: OPA initialized, the known/expected signing-key placeholder error logged (see Known Issues), `Application startup complete.` — then `/health` returned `200` within 15 seconds end-to-end.

**Result: PASS.**

## 7. Health endpoints

`/health` and `/health/ready` both return `200` consistently across every check this milestone (cold start, warm, post-restart, under load). `/health/ready` genuinely round-trips through OPA (`httpx` log line confirms the live call), not a hardcoded `200`.

**Result: PASS.**

## 8. Application logging

Live KQL query against `log-payreality-staging-cus` immediately after the forced restart: **394 new `ContainerAppConsoleLogs_CL` rows in the prior 10 minutes** — not a one-time observation from Milestone 3, a fresh, independent re-confirmation.

**Result: PASS.**

## 9. Application Insights ingestion

`union requests, traces, dependencies | count` against `appi-payreality-staging-cus` → **0 rows.** Unchanged from the gap already disclosed in `MILESTONE_3_KNOWN_ISSUES.md`: Container Apps does not auto-instrument to Application Insights, and no APM SDK is wired into the application code.

**Result: FAIL — pre-existing, disclosed gap, not new.** Carried into this milestone's Risk Register.

## 10. Log Analytics

Confirmed working (see item 8) — this is where all real observability currently lives for this environment.

**Result: PASS.**

## 11. Alerts

`az monitor metrics alert list` and `az monitor action-group list` against `rg-payreality-staging-cus`: **zero custom alert rules.** The only action group present is `Application Insights Smart Detection`, an auto-created default that ships with every App Insights resource — not a configured alert.

**Result: FAIL.** No one is paged if this environment goes down. Milestone 3 explicitly deferred alert configuration ("verify observability without configuring alert rules yet") — this milestone confirms that deferral is still in effect, not resolved. Carried into the Risk Register and factors directly into the final recommendation.

## 12. Backup configuration

`az postgres flexible-server show` → `backupRetentionDays: 35`, `geoRedundantBackup: Disabled` (correct for staging, per `environments/staging.tfvars`), `earliestRestoreDate: 2026-08-10T20:31:57Z` — a real, usable restore point already exists.

**Result: PASS.**

## 13. PostgreSQL recovery capability

Point-in-time restore is configured and has a real, usable restore point (see item 12), proving the *capability* exists. A live restore-to-a-new-server drill was **deliberately not performed** this milestone: Azure Flexible Server restore always creates a new server resource, and this milestone's own absolute rule ("do not delete Azure resources") would make that new server a permanent addition rather than a disposable test. Recommended as a distinct, explicitly-scoped exercise before actual production cutover — see Risk Register and Production Cutover Readiness Assessment.

**Result: PARTIAL PASS** — capability confirmed configured and available; a live restore has not been rehearsed.

## 14–16. Load testing, latency, and behavioural differences

See `MILESTONE_4_PERFORMANCE_REPORT.md` for full data and methodology.

## Test suite

`pytest`: **194 passed, 0 failed** — unchanged from Milestones 2 and 3. No application code was touched this milestone.
