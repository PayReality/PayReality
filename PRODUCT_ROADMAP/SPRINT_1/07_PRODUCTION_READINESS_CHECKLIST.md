# Sprint 1, Part 7 — Production Readiness Checklist

**Status:** final. Every item is concrete and independently verifiable — checked "done" only where [01_INFRASTRUCTURE_ASSESSMENT.md](01_INFRASTRUCTURE_ASSESSMENT.md) directly confirmed it, "not done" where it confirmed the absence, never left ambiguous. Items map to the engineering tasks in [08_ENGINEERING_IMPLEMENTATION_PLAN.md](08_ENGINEERING_IMPLEMENTATION_PLAN.md) by ID (in brackets).

## Infrastructure

- [x] Backend hosted with a valid TLS certificate on a custom domain
- [x] Frontend hosted with a valid TLS certificate on a custom domain
- [ ] Production database on a plan with backups enabled *(currently free-tier, no backups)* [T1]
- [ ] Production database is not on a plan with a hard expiry date *(currently expires 2026-08-24)* [T1]
- [ ] A staging environment exists, mirroring production's topology [T2]
- [ ] Object storage strategy explicitly documented as "Postgres column, by deliberate choice" rather than assumed *(done by this sprint's own [01](01_INFRASTRUCTURE_ASSESSMENT.md)/[02](02_INFRASTRUCTURE_BLUEPRINT.md))*

## Security

- [x] No hardcoded secrets in the codebase (confirmed by direct search)
- [x] Boot-time refusal to start in production with missing/default secrets
- [x] Constant-time comparison for the shared operator credential
- [x] Passwords hashed (bcrypt); API keys hashed (SHA-256) at rest
- [x] Evidence signing keys have a real rotation mechanism with historical verification preserved
- [ ] The shared operator credential (`ADMIN_API_KEY`) has a rotation mechanism [T3]
- [ ] Per-developer API keys support graceful rotation (overlap window), not just revoke-and-recreate [T3]
- [ ] `EVIDENCE_SIGNING_KEY_ID` is included in boot-time production validation [T4]
- [ ] A durable, off-platform backup of the Evidence signing key material exists [T5]

## Operations

- [x] Structured, correlated request logging
- [x] A documented internal incident-response runbook
- [ ] Error tracking / basic APM in place [T6]
- [ ] A deploy is a scripted, repeatable action, not a manual sequence of dashboard clicks [T7]
- [ ] CI/CD includes automatic deployment to staging on merge [T7]
- [ ] Production deployment remains a deliberate, manually-triggered promotion step *(by design — this stays a checklist item confirming the deliberateness, not something to automate away)*

## Monitoring

- [x] Liveness (`/health`), readiness (`/health/ready`), and build-identity (`/version`) endpoints exist
- [ ] Health/readiness endpoints are polled on a schedule by something outside the app itself [T8]
- [ ] The existing smoke test runs on a schedule, not only manually [T8]
- [ ] Decision-outcome metrics (`ALLOW`/`DENY`/`HUMAN_REVIEW` counts) are tracked over time [T9]
- [ ] `HUMAN_REVIEW` backlog size and age are tracked and alertable [T9]
- [ ] P1 alert routing exists (paging, not just a dashboard) [T10]
- [ ] TLS certificate expiry is monitored explicitly, independent of trusting auto-renewal silently [T10]

## Deployment

- [x] CI runs the full backend test suite, a Docker build, and the frontend build on every PR
- [ ] A staging environment receives every merge to `main` automatically [T7]
- [ ] Production promotion is scripted (not manual dashboard actions), even though it stays a deliberate, human-gated step [T7]

## Backups

- [ ] Automated daily backups enabled on the production database [T1]
- [ ] Point-in-time recovery enabled on the production database [T1]
- [ ] Backup retention window explicitly confirmed against the chosen plan and documented [T1]

## Recovery

- [ ] A real restore has been performed at least once and its duration measured [T11]
- [ ] RPO/RTO targets are documented and based on a measured drill, not assumption [T11]
- [ ] `OPERATIONS_RUNBOOK.md` reflects the actual, drilled restore procedure [T11]

## Availability

- [x] The platform is fail-closed by construction at the application layer (pre-existing, verified architecture — [`SPECIFICATION/45_PHASE_5_BROKEN_PROMISE_REPORT.md`](../../SPECIFICATION/45_PHASE_5_BROKEN_PROMISE_REPORT.md))
- [ ] No single-instance-only assumption blocks horizontal scaling when it's eventually needed *(the in-process rate limiter does today — named, not yet fixed, since scaling isn't needed yet)* [T12, deferred until scaling is actually required]
- [ ] A documented uptime target exists, appropriate to pilot-stage, not an enterprise SLA number the team can't yet back up [T13]

## Reliability

- [x] Fail-closed evaluation semantics tested and enforced at the code level
- [ ] A production incident has never occurred without detection *(unverifiable as a positive claim; the real requirement is P1 alerting existing at all, tracked above)*
- [ ] Dependency (OPA, database) health is tracked as a leading indicator, not only discovered via a failed request [T9]

## Support

- [ ] A support channel beyond a personal email inbox exists *(carried from the prior product audit — Sprint 2+ scope per this sprint's own boundary, not re-scoped here)*
- [x] An internal, engineering-facing incident runbook exists

## Explicitly out of scope for Sprint 1 (do not check these here)

Compliance (SOC 2, pentest, DPA), customer-facing support tooling/SLA, Authorization Receipts, multi-tenancy, and horizontal-scaling work are real, tracked items from the prior product audit's backlog — deliberately not included in this checklist, per this sprint's own stop condition.
