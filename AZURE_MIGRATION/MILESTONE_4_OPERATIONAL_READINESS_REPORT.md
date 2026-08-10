# Milestone 4: Operational Readiness Report

Assesses whether the Azure staging environment could be *operated* day-to-day, not just whether it *runs* — the distinction the Platform Readiness Report (Milestone 3) intentionally left for this milestone.

## What's operationally solid today

- **Deployment is repeatable and reviewable.** Every change goes through `terraform plan` review before `apply`; the current state has zero drift (`terraform plan` → "No changes").
- **Recovery from a restart is clean and fast.** Forced restart this milestone: full startup sequence, `/health` green within 15 seconds, no manual intervention needed.
- **Logs are genuinely queryable.** An operator can run a live KQL query against Log Analytics and see real container output within minutes — confirmed twice, independently, across two milestones.
- **Backups run automatically** with a 35-day window and a real, usable point-in-time restore point already available.
- **Secrets never require manual handling in normal operation** — the managed-identity path has now proven itself across two independent container starts (initial deploy, forced restart).
- **The runbook exists and has been used, not just written** — `MILESTONE_3_OPERATIONAL_CHECKLIST.md`'s exact commands were used verbatim during this milestone's own restart and exec verification.

## What is not yet operationally ready

1. **No one gets paged.** Zero alert rules exist beyond App Insights' auto-created (and functionally inert, for this purpose) Smart Detection action group. If the Container App crashes, if Postgres becomes unreachable, if Key Vault access starts failing — nothing notifies anyone. This is the single largest operational gap found this milestone.
2. **No application-level APM.** An operator investigating a slow request today has container stdout logs and that's it — no distributed trace, no dependency timing breakdown, no App Insights data at all. Diagnosable via logs, but slower than it should be.
3. **No rehearsed disaster recovery.** PITR is configured and has a real restore point, but nobody on this program has actually performed a restore-to-new-server drill. The first real restore should not be the first time anyone has done one.
4. **The Evidence signing key is still a placeholder.** Not an infrastructure gap, but it does mean this environment cannot yet be used to validate a real, end-to-end evidence-signing workflow — only the platform underneath it.
5. **The per-client-IP rate limiter is in-process, not shared across replicas.** Already a known, documented, deferred item (Sprint 1's T12) — restated here because Milestone 4's own load test reconfirmed it's real and would behave inconsistently the moment `max_replicas` goes above 1 under real multi-client load (each replica enforces its own independent 120-req/60s counter per IP, so the *effective* per-client limit multiplies by however many replicas happen to be serving that client — not a security hole, but not the single global limit the number "120" implies either).

## Recommended before production operation (not before this milestone's own gate)

1. Configure baseline alert rules: Container App unhealthy/restart-looping, Postgres unreachable/high CPU, Key Vault access-denied spike. Straightforward, Terraform-managed, no new absolute-rule conflict — a natural next step, not attempted this milestone since alert *thresholds and notification targets* are a scope decision for whoever owns on-call, not something to invent unilaterally.
2. Decide on an APM approach for Application Insights (SDK integration is an application-code change, needs its own scoping).
3. Schedule one deliberate, explicitly-approved PITR restore drill against a disposable resource group, understanding it will leave a new Postgres server that this program's "no deletion" rule would then keep.
4. Complete Milestone 5's real secret population before treating this environment as anything beyond a platform/infrastructure proof.

## Verdict

**Operationally sound as an infrastructure platform. Not yet operationally ready to be anyone's production system** — primarily on the strength of the missing alerting, which is the one gap in this list that directly determines whether an incident gets noticed at all.
