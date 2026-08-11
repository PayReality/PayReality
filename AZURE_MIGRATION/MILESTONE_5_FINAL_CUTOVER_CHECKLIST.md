# Milestone 5: Final Cutover Checklist

Every item below reflects a real, evidence-backed check performed this milestone against the live `rg-payreality-staging-cus` environment — not a design intention. "Done" means verified; "Open" means a real, disclosed gap.

## Secrets and cryptography

- [x] Real Ed25519 Evidence signing key generated, installed in Key Vault, and cryptographically validated — the API's own `/v1/evidence/verification-keys` endpoint returns a public key that matches an independently-computed value byte-for-byte.
- [x] Real Admin API key generated and installed — confirmed a request with the real key succeeds (`200`) and a wrong key is rejected (`401`).
- [x] No plaintext secret anywhere in Terraform config, state variables, or git history — every secret is either Terraform-generated (Postgres password, `DATABASE_URL`) or set directly in Key Vault out-of-band (`az keyvault secret set`), never round-tripped through a `.tfvars` file.
- [ ] **Open:** `ANTHROPIC_API_KEY` remains the Milestone-2 placeholder. This is a third-party (Anthropic) API credential, not something this program can generate — it requires the actual account credential from whoever owns that relationship. Not a signing key, so it does not block this milestone's "production signing keys" criterion, but AI-dependent features (Policy Builder, Authority Builder corpus generation) will not function until it's set.

## Observability

- [x] Application Insights fully instrumented (`server/app/observability.py`, OpenTelemetry auto-instrumentation, opt-in via `APPLICATIONINSIGHTS_CONNECTION_STRING`) — confirmed with live data: real `requests`, `dependencies` (DB call spans), and `traces` rows, not zero as found in Milestone 4.
- [x] Render's own behavior is unaffected — the instrumentation is a no-op without that environment variable, which Render never sets. `pytest`: 194 passed, unchanged.
- [x] Log Analytics ingestion re-confirmed live and current.
- [x] Monitoring dashboard (`dash-payreality-staging`) deployed via Terraform, zero drift, six tiles covering Container App / Postgres / Key Vault using the same metric names the alert rules use.

## Alerting

- [x] Five metric alert rules deployed via Terraform (`modules/alerts`): Postgres unavailable (Sev 0), Postgres storage high (Sev 2), Container App restarting (Sev 1), Container App CPU high (Sev 2), Key Vault availability low (Sev 1).
- [x] Notification delivery path tested live and confirmed: `az monitor action-group test-notifications` returned `Status: Succeeded` for a real email send.
- [ ] **Partial / disclosed:** an organic, real metric-breach firing was not achieved for two of the five rules within this milestone's testing window. `RestartCount` does not respond to a CLI-initiated `revision restart` (confirmed — it tracks platform-detected crash restarts specifically); the CPU-high threshold could not be organically triggered against the lightweight `/health` endpoint even under sustained load (throughput ~15 req/s for 3+ minutes kept CPU under 5% on the 0.5-vCPU allocation). The rules themselves are confirmed correctly configured against real, valid metric names (the same ones the dashboard uses) — this is a gap in *live-fire test coverage*, not in configuration correctness.

## Backup and recovery

- [x] Point-in-time restore capability confirmed configured (35-day retention, real restore point available).
- [x] **A full restore drill was actually performed**, not just configuration-checked: a new server (`psql-payreality-staging-cus-restoretest`) was restored from the live source, and its data was queried and confirmed to match the source exactly (same Alembic head revision `d7e28b4c91a6`, same organization count, same signing-key registration) — connected to from inside the VNet via the running Container App's exec access, using real credentials from Key Vault.
- [ ] **Decision needed:** the restore-test server is a new, real, ongoing-cost resource (~$14/month). This program's rules don't authorize deleting Azure resources without explicit approval — awaiting a decision on whether to keep it or delete it.

## Rollback

- [x] A real rollback was tested, not just documented: deployed a Container App revision with a deliberately nonexistent image tag, confirmed it failed to activate (`ActivationFailed`, `0` replicas) while **the previous healthy revision kept serving `/health` at `200` throughout** — no outage occurred from the bad deploy itself, a genuine and valuable finding about Container Apps' built-in behavior in `Single` revision mode.
- [x] Rolled back via Terraform (the source of truth) by reverting `container_image` and re-applying — confirmed the resulting new revision came up `Healthy` and the application fully recovered (`/version` reflecting the correct build).
- [x] The rollback procedure is now written up in full in `AZURE_RUNBOOK.md`'s "Rollback plan" section, based on this real test, not a hypothetical.

## Runbook

- [x] Every command in `AZURE_RUNBOOK.md` was re-run against the live environment this milestone (Terraform plan/apply, container logs, exec, restart, secret rotation, load testing, backup checks, telemetry queries, alert testing) and the document updated with what was actually learned, including the secret-rotation-needs-a-new-revision finding, the `cut -d=` padding trap, and the transient ARM `503` observed once.

## Infrastructure integrity

- [x] `terraform plan`: **"No changes. Your infrastructure matches the configuration"** — confirmed at the end of this milestone, after every change made during it.
- [x] `pytest`: 194 passed, 0 failed — unchanged from Milestones 2–4, confirming zero unintended behavioral impact from the Application Insights instrumentation, the only application-code change this milestone made.
- [x] No file under `server/` was touched except the one deliberate, disclosed, milestone-scoped exception (`app/observability.py` and its two call sites) — no `SPECIFICATION/` or `PRODUCT_ROADMAP/` file touched at all.

## What this checklist does not cover

Production DNS, customer traffic migration, and the actual cutover itself — none of those were performed or are proposed here, consistent with every prior milestone's rules. See `MILESTONE_5_PRODUCTION_CUTOVER_REPORT.md` for the recommendation this checklist feeds into.
