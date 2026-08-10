# Sprint 1, Part 6 — Backup & Disaster Recovery Plan

**Status:** final. **Principle:** realistic for a small team with no dedicated ops function yet — targets that can actually be met and verified, not aspirational numbers copied from an enterprise SLA template.

## What needs backing up

| Asset | Backup mechanism | Why nothing separate is needed |
|---|---|---|
| All application data (Decisions, Evidence, Agents, Policies, Organizations, uploaded document bytes) | Render managed Postgres backups (once on a paid plan — see [02_INFRASTRUCTURE_BLUEPRINT.md](02_INFRASTRUCTURE_BLUEPRINT.md)) | Everything, including uploaded documents, already lives in this one database (see [01_INFRASTRUCTURE_ASSESSMENT.md](01_INFRASTRUCTURE_ASSESSMENT.md)'s storage finding) — one backup mechanism covers all of it, which is exactly the point of not having introduced a separate object store |
| Frontend build artifacts | None needed — Vercel deployments are reproducible from the git commit that produced them | A "backup" of a build artifact is the source commit; git already is that backup |
| Application code, `SPECIFICATION/`, `PRODUCT_ROADMAP/` | GitHub (`origin`) | Standard git remote; already in place |
| **Evidence signing key material** (`EVIDENCE_SIGNING_KEY_B64`) | **Currently, none beyond Render's own environment-variable store.** | This is the one real gap this plan identifies: Render's env var store is a configuration store, not a durable backup. If the Render account or that specific service were ever lost or misconfigured, this key is gone — and with it, the ability to ever verify (or produce new, chain-continuous) Evidence again. **Recommendation**: store a copy of this value in a durable, access-controlled secret store outside Render (a password manager vault entry with restricted access is sufficient at this scale — not a new infrastructure service). |
| Operator/admin credentials | Same gap, same recommendation, lower severity (rotatable without historical consequence, unlike the signing key) | — |

## Backup strategy

Daily automated backups plus point-in-time recovery, both provided by Render's managed Postgres on any paid plan — this is the entire mechanism. No custom backup script, no separate export-to-S3 cron job. Building a redundant custom backup pipeline on top of a managed feature that already exists would be exactly the unnecessary service this sprint avoids.

## Retention policy

Whatever window the selected Render paid plan provides (Render's own plans vary retention by tier — confirm the exact window against the specific plan chosen at upgrade time, rather than assuming a number here that may not match the actual plan). The retention window should be **explicitly re-confirmed and documented in `OPERATIONS_RUNBOOK.md` at the moment the plan is chosen**, not left as an assumption.

## Restore procedure

`OPERATIONS_RUNBOOK.md` already documents a rollback/restore procedure for app code, policy state, and compromised keys. It explicitly states the database restore path **has never been exercised against this schema.** This plan requires, as a Sprint 1 deliverable (not a future one): a real, scheduled restore drill — restore the paid-tier backup into a throwaway database, run the test suite's assumptions against it (or at minimum confirm the app boots and reads real data against the restored instance), and record how long it actually took. That measured number, not a guess, is what sets the RTO below.

## Disaster recovery objectives

**RPO (Recovery Point Objective): target 1 hour.** Render's point-in-time recovery, once enabled on a paid plan, supports recovery to a specific point in time within the retention window — an hour is a realistic, conservative target for how much data a real incident could lose, not a claim about the platform's actual technical granularity (which should be confirmed during the restore drill above, and this target tightened if the drill shows better is realistically achievable).

**RTO (Recovery Time Objective): target 4 hours.** This reflects today's actual operational reality: one engineer, no on-call rotation, no automated failover, and — until the drill above happens — no verified restore time at all. Four hours is a realistic target for "an engineer notices or is paged, restores from backup, redeploys the API pointed at the restored database, and confirms `/health/ready`" performed manually. This number should be **replaced by the drill's actual measured time**, not kept as a permanent estimate — and revisited downward only once a real drill has happened more than once.

## What this plan deliberately does not include

- **No automated failover** (a standby replica that takes over automatically). Not justified at today's traffic or team size; the cost of building and maintaining it exceeds the cost of an occasional multi-hour manual restore at this stage.
- **No multi-region redundancy.** Same reasoning — this is Series-A-or-later scale work, not Sprint 1.
- **No third-party backup-monitoring service.** The scheduled health/smoke-test monitoring already being added in [05_OBSERVABILITY_DESIGN.md](05_OBSERVABILITY_DESIGN.md) is sufficient to notice a backup-related problem; a dedicated backup-monitoring product would be redundant with it.
