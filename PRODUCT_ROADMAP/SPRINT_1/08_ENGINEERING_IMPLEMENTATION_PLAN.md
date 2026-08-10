# Sprint 1, Part 8 — Engineering Implementation Plan

**Status:** final. Every task below is concrete, independently executable, and traces to a specific finding in Parts 1–7. Task IDs (`T1`–`T13`) match the checklist references in [07_PRODUCTION_READINESS_CHECKLIST.md](07_PRODUCTION_READINESS_CHECKLIST.md).

## Tasks

- **T1 — Upgrade the production database off the expiring free tier.**
  *Objective:* move `payreality-db` to a paid Render Postgres plan with automated backups and point-in-time recovery enabled, before 2026-08-24.
  *Complexity:* S.
  *Dependencies:* none.
  *Implementation order:* first — every dated risk in this sprint traces back to this one.
  *Expected outcome:* the single highest-priority risk in [01_INFRASTRUCTURE_ASSESSMENT.md](01_INFRASTRUCTURE_ASSESSMENT.md) is closed; backups exist where none did before.

- **T2 — Stand up the staging environment.**
  *Objective:* a second Render web service + Postgres instance and a second Vercel project, mirroring production's topology exactly, per [02_INFRASTRUCTURE_BLUEPRINT.md](02_INFRASTRUCTURE_BLUEPRINT.md).
  *Complexity:* M.
  *Dependencies:* none (staging deliberately stays on a cheap/free tier, independent of T1).
  *Implementation order:* can start immediately, in parallel with T1.
  *Expected outcome:* a real environment exists to rehearse changes against before they reach real customers — the first time this has ever been true for this platform.

- **T3 — Add rotation support for the shared operator credential and per-developer API keys.**
  *Objective:* a brief dual-key overlap window for `ADMIN_API_KEY` rotation; a graceful rotate path (not just revoke-and-recreate) for per-developer keys.
  *Complexity:* M.
  *Dependencies:* none.
  *Implementation order:* independent; can run in parallel with T1/T2.
  *Expected outcome:* the platform's highest-value credential can be rotated without an instant, ungraceful cutover.

- **T4 — Include `EVIDENCE_SIGNING_KEY_ID` in boot-time production validation.**
  *Objective:* extend `main.py::_validate_production_config` to refuse boot if this is left at its dev default in production.
  *Complexity:* S.
  *Dependencies:* none.
  *Implementation order:* trivial; bundle with T3.
  *Expected outcome:* closes the one gap [03_ENVIRONMENT_STANDARD.md](03_ENVIRONMENT_STANDARD.md) found in the existing validation's coverage.

- **T5 — Durably back up the Evidence signing key material off-platform.**
  *Objective:* store `EVIDENCE_SIGNING_KEY_B64` (and the operator key) in a durable, access-controlled secret store outside Render's own environment-variable store.
  *Complexity:* S.
  *Dependencies:* none.
  *Implementation order:* immediate — this is process, not code, and closes a real, catastrophic-if-triggered gap at near-zero engineering cost.
  *Expected outcome:* losing the Render account or misconfiguring the service no longer means permanently losing the ability to verify historical Evidence.

- **T6 — Add error tracking and basic performance monitoring.**
  *Objective:* integrate Sentry (or an equivalent single product) at the FastAPI service/router layer, explicitly never inside `domain/decision/engine.py`.
  *Complexity:* S.
  *Dependencies:* none.
  *Implementation order:* independent; can start immediately.
  *Expected outcome:* the platform's first real-time error visibility, closing the largest single gap in [05_OBSERVABILITY_DESIGN.md](05_OBSERVABILITY_DESIGN.md).

- **T7 — Build the staging-then-production deployment pipeline.**
  *Objective:* extend CI so every merge to `main` auto-deploys to staging and runs the existing smoke test against it; add a separate, scripted (not manual-dashboard) production-promotion step that still requires a deliberate human trigger.
  *Complexity:* M.
  *Dependencies:* T2 (staging must exist first).
  *Implementation order:* after T2.
  *Expected outcome:* every future deploy is rehearsed before it reaches production, and production promotion becomes an auditable, scripted action instead of an ad hoc dashboard sequence.

- **T8 — Schedule health-check and smoke-test monitoring.**
  *Objective:* poll `/health`/`/health/ready` on a fixed interval from outside the app (a scheduled CI job or a third-party uptime monitor); run `scripts/smoke_test.py` on a schedule, not only manually.
  *Complexity:* S.
  *Dependencies:* none technically, but most valuable once T1 gives production something stable worth monitoring continuously.
  *Implementation order:* alongside T1.
  *Expected outcome:* the first continuous, automated check that the platform is actually up, rather than relying on someone noticing.

- **T9 — Build decision-outcome and backlog metrics.**
  *Objective:* track `ALLOW`/`DENY`/`HUMAN_REVIEW` counts over time, `HUMAN_REVIEW` backlog size/age, and OPA/database latency.
  *Complexity:* M.
  *Dependencies:* none required, though it pairs naturally with T6's performance monitoring for latency specifically.
  *Implementation order:* after T6.
  *Expected outcome:* the platform's own domain-specific health signals (named precisely in [05_OBSERVABILITY_DESIGN.md](05_OBSERVABILITY_DESIGN.md)) become visible for the first time, ahead of any customer-visible symptom.

- **T10 — Wire real alert routing.**
  *Objective:* route T6's error tracker and T8/T9's monitoring into an actual paging channel (at minimum a routed Slack/email webhook; ideally PagerDuty/Opsgenie) for the P1 class defined in [05_OBSERVABILITY_DESIGN.md](05_OBSERVABILITY_DESIGN.md); add explicit TLS-certificate-expiry monitoring.
  *Complexity:* S.
  *Dependencies:* T6, T8, T9 (needs something to alert on).
  *Implementation order:* last among the observability tasks.
  *Expected outcome:* a real production incident produces a page, not silence.

- **T11 — Perform and document a real restore drill.**
  *Objective:* restore a production backup into a throwaway database, confirm the app can boot and read real data against it, measure the actual time taken, and update `OPERATIONS_RUNBOOK.md` and the RPO/RTO targets in [06_BACKUP_DISASTER_RECOVERY_PLAN.md](06_BACKUP_DISASTER_RECOVERY_PLAN.md) with the measured result.
  *Complexity:* M.
  *Dependencies:* T1 (a paid-tier backup must exist to restore from).
  *Implementation order:* after T1.
  *Expected outcome:* RTO becomes a measured fact instead of an estimate, and the team has actually done, once, the thing the runbook claims is possible.

- **T12 — Move the rate limiter to a shared store. *(Deferred, not scheduled.)***
  *Objective:* replace the in-process rate limiter with a shared-store-backed one (Redis or equivalent) before running more than one API instance.
  *Complexity:* M.
  *Dependencies:* none technically, but there is no current need — this platform runs one instance today.
  *Implementation order:* **not scheduled in Sprint 1.** Named here so it isn't rediscovered under pressure the day horizontal scaling actually becomes necessary; building it now would be exactly the speculative work this sprint's directive rules out.
  *Expected outcome (when eventually done):* horizontal scaling becomes safe without silently breaking rate limiting.

- **T13 — Document a realistic pilot-stage uptime target.**
  *Objective:* write down an honest, pilot-appropriate uptime target (not an enterprise SLA number the team can't yet substantiate) in `OPERATIONS_RUNBOOK.md`, informed by T11's measured RTO.
  *Complexity:* S.
  *Dependencies:* T11 (should reflect a measured RTO, not a guess).
  *Implementation order:* last.
  *Expected outcome:* the checklist item in [07](07_PRODUCTION_READINESS_CHECKLIST.md) is closed with something true, not aspirational.

## Recommended build order

1. **T1** (database) and **T5** (secrets backup) — start immediately, both trivial and both close dated/catastrophic risks.
2. **T2** (staging), **T3+T4** (credential rotation), **T6** (error tracking), **T8** (scheduled health checks) — all independent, run in parallel with each other and with the tail of step 1.
3. **T7** (deployment pipeline) — once T2 exists.
4. **T9** (domain metrics) — once T6 exists.
5. **T10** (alert routing) — once T6, T8, and T9 all exist.
6. **T11** (restore drill) — once T1 exists.
7. **T13** (uptime target) — once T11's measured number exists.
8. **T12** — explicitly not scheduled; revisit only when horizontal scaling is actually needed.
