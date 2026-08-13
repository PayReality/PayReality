# Operations Runbook

Day-2 operations: what to do once the platform is live, as distinct from `GO_LIVE.md`'s one-time bring-up procedure. Assumes the Render deployment described there exists.

**Current as of Render being the live production host.** Every procedure below that names the Render dashboard directly is accurate today, since production traffic is still on Render, confirmed live in `MILESTONE_4_AZURE_PRODUCTION_READINESS_SUMMARY.md`. Once that document's Phase 7 cutover plan actually executes, this runbook needs a matching Azure-native pass (Container App revision management in place of the Deploys tab, Key Vault in place of Render's environment settings, and so on); that pass is not done yet, and this file should not be read as already describing Azure.

## Health and monitoring

- **Liveness**: `GET /health`, no dependency calls, should always return `200 {"status":"ok"}` if the process is up at all. Point Render's own health check at this.
- **Readiness**: `GET /health/ready`, checks Postgres and OPA live, each bounded to a hard 3-second deadline. Returns `503` if either is down. Use this for alerting (page someone), not for the load balancer's own routing decision, since Render already routes based on the simpler liveness check.
- **Logs**: structured JSON on stdout, one line per request (`request_id`, `method`, `path`, `status`, `duration_ms`), visible in Render's built-in log viewer. Every unhandled exception is logged with a full traceback server-side and the same `request_id` that was returned to the caller in `X-Request-ID`, so a client-reported error can always be traced to the exact server-side log line.
- **Smoke test as a monitor**: `scripts/smoke_test.py` can be run on a schedule (a cron job, a Render cron service, or a simple external uptime check calling it) as a synthetic end-to-end check, not just a post-deploy gate. A failure here means something deeper than a health check would catch, e.g. Evidence signatures no longer verifying, which is a P1 regardless of what `/health/ready` reports.

## What to actually watch

In rough priority order, because they represent categorically different failure severities:

1. **`POST /v1/evidence/{id}/verify` returning `false` for a record that previously verified.** This means tampering or a corrupted signing key, not a routine bug. Treat as a P1 immediately, per `SECURITY.md`'s evidence-integrity section: this is the one thing this entire platform exists to make impossible.
2. **`/health/ready`'s `opa` check going false while `database` stays true.** OPA down means every new Intent falls back to `HUMAN_REVIEW` (fail-closed, so nothing incorrectly executes), but it also means the platform is effectively not making autonomous decisions at all until it's back. Page on this, don't just log it.
3. **A spike in `429` responses.** The rate limiter (`app/security.py`) is in-process memory; a spike here on a single-instance deployment means either real abuse or a client retry-storm bug, not a scaling signal yet (see `ARCHITECTURE.md`'s known gaps: this limiter doesn't work correctly across more than one instance, so don't scale horizontally without fixing that first).
4. **Any `500` with `{"detail": "internal_error"}`.** Look up the `request_id` in the logs immediately; the client never sees the real exception, so the log is the only place to find it.

## Rollback

- **Bad code deploy**: Render dashboard → the service → Deploys tab → redeploy the previous successful deploy. No database migration action is required for most rollbacks, since Alembic migrations here have been additive to date; if a future migration ever drops or renames a column, rolling back the application code without also rolling back the schema will break, plan for that explicitly when it happens rather than assuming today's simple case always holds.
- **Bad policy activation**: reactivate the previously-active Policy version via `POST /v1/policies/{id}/activate` (operator key required). This is the actual rollback mechanism for policy, not a separate feature, per `ARCHITECTURE.md`.
- **Compromised or leaked `ADMIN_API_KEY`**: rotate it immediately in Render's environment settings and redeploy. Every operator-gated endpoint stops accepting the old key the instant the new one is live; there is no grace period, and there shouldn't be, since a leaked operator key means anyone holding it could have already resolved decisions or activated policy under it.
- **Compromised signing key**: this is the one rollback this platform cannot do cleanly today. There's no key registry (see `SECURITY.md`), so rotating `EVIDENCE_SIGNING_KEY_B64` breaks verification of every Evidence record signed before the rotation. If this ever happens: rotate anyway (a compromised key is worse than an unverifiable old record), but treat every pre-rotation Evidence record's verification status as suspect until the key-registry work in `VERSION_3_ROADMAP.md` lands, and disclose this explicitly to any customer or auditor relying on that evidence.

## Database recovery

- Render managed Postgres includes automated daily backups and point-in-time recovery on paid tiers, confirm this is actually enabled for the production database (it is not automatic on every plan tier); this is a one-time check to do right after provisioning, in `GO_LIVE.md`'s Step 1.
- Restore procedure: Render dashboard → the database → Backups → restore to a new instance → update `DATABASE_URL` on the API service to point at the restored instance → verify with `/health/ready` and the smoke test before cutting over traffic.
- This restore procedure has not been exercised against this specific schema, since there was no production database to test it against while writing this. Do a real restore drill against a copy once real customer data exists, before the first incident that requires it for real.

## Incident checklist

When something is actually wrong in production:

1. Check `/health/ready` first: is it Postgres, OPA, or neither.
2. Check the structured logs for the relevant `request_id` if a specific request was reported as failing.
3. If Evidence verification is in question, treat it as the P1 it is (see above) before anything else, and do not resolve any pending `HUMAN_REVIEW` decisions until the cause is understood, since a compromised signing key would make new resolutions just as unverifiable as old ones.
4. If a rollback is warranted, use the specific rollback path above matching the actual cause, not a blanket "redeploy everything" reflex; a policy problem and a code problem have different, non-overlapping fixes.
5. After resolution, run `scripts/smoke_test.py` against production before considering the incident closed.
