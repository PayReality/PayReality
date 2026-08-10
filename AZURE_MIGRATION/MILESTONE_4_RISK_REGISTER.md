# Milestone 4: Risk Register

Consolidates every open risk touching the Azure environment as of this milestone — carried-forward items from Milestones 1–3 plus what this milestone's validation surfaced directly. Ranked by what would actually hurt if production cut over today.

| # | Risk | Severity | Source | Status |
|---|---|---|---|---|
| 1 | **No alert rules configured.** An outage in Azure staging (or, if cut over, production) would not page anyone. | **High** | Confirmed this milestone (`az monitor metrics alert list` → empty) | Open |
| 2 | **Evidence signing key is still a placeholder.** Signature-dependent functionality cannot work correctly in this environment. | **High** (for functional readiness), **N/A** (for platform readiness) | Milestone 3, reconfirmed this milestone | Open — Milestone 5's explicit scope |
| 3 | **No PITR restore has ever actually been rehearsed.** Configuration is confirmed correct; the procedure itself is unverified. | **Medium-High** | This milestone | Open — deliberately not performed, see Validation Report item 13 |
| 4 | **No application-level APM (Application Insights receives zero telemetry).** Diagnosing a live production issue would rely on container logs alone. | **Medium** | Milestone 3, reconfirmed this milestone | Open |
| 5 | **In-process, per-replica rate limiter does not coordinate across multiple Container App replicas.** Effective per-client limit multiplies with replica count once `max_replicas > 1` sees real traffic. | **Medium** | Sprint 1's own Task T12 (pre-existing, application-level, not introduced by this migration); reconfirmed via this milestone's load test | Open — deferred by design, unrelated to the Azure migration itself |
| 6 | **OPA authorization decisions were not exercised end-to-end** (only the engine's health, not a real ALLOW/DENY/HUMAN_REVIEW path) because the environment has no policy data and the placeholder `ADMIN_API_KEY` blocks creating any. | **Medium** | This milestone | Open — blocked on Risk #2/Milestone 5 |
| 7 | **Key Vault naming collision residue**: `kv-pr-staging-adzg` remains soft-deleted and unpurgeable until 2026-11-08; `prod.tfvars` has not yet been exercised against the new naming convention. | **Low** | Milestone 3 | Open, monitor before any prod apply |
| 8 | **Cold-start latency not precisely measured for Azure** (qualitatively fast, not instrumented to the millisecond). | **Low** | This milestone | Open — trivial to close if a precise figure is needed |
| 9 | **Render's free-tier Postgres database expiry** (~30 days, per `render.yaml`'s own comment) — the one risk the entire "Render stays production" principle depends on. | **High**, but pre-existing and outside Azure's control | Milestone 1, still open | Open, unrelated to this migration's own risk surface but blocking if it lapses before cutover is ready |
| 10 | **No CDN/edge layer in front of Azure Container Apps** (Render has Cloudflare; Azure does not, in its current default-ingress configuration). | **Low** | This milestone | Open — Azure Front Door would be the equivalent addition, out of scope until a custom domain is planned |

## What is explicitly NOT a risk, despite looking like one at first glance

- **The 76% error rate in the first load-test run** — this was the application's own intentional rate limiter correctly rejecting a single-IP burst, not an infrastructure defect. Re-tested with simulated distinct clients: 0% errors. See Performance Report.
- **The `signing_key_registration_failed_at_startup` log line on every boot** — expected, logged-and-continues behavior given the known placeholder secret (Risk #2), not a crash or an unhandled exception.
- **Storage/Key Vault having a public network endpoint** — deliberately, by approved design (identity-first RBAC model, Milestone 3), not an oversight. Verified this milestone that unauthenticated calls are still rejected.

## Net assessment

Nothing in this register is new evidence of the *platform itself* being unsound — every High-severity item is either explicitly out of this milestone's scope (Milestone 5's secrets), a pre-existing application-level item unrelated to the migration (the rate limiter, Render's DB expiry), or an operational gap (alerting) that is straightforward to close and does not require redesigning anything already built. See the Production Cutover Readiness Assessment for how these weigh into the final recommendation.
