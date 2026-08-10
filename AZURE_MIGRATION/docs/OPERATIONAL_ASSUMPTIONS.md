# Operational Assumptions

**Status:** final, Milestone 2. Every number below is a variable default, not a hardcoded constant — each is stated here as the assumption it represents, so a future engineer changing the variable also updates the reasoning, not just the value.

| Assumption | Value | Basis |
|---|---|---|
| Traffic scale | Pilot-scale, one Container App, `min_replicas=1`/`max_replicas=3` | Confirmed directly in `AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md`; this is a like-for-like migration of Render's own single-instance topology, not a scale-up |
| Database size | Burstable `B_Standard_B1ms`, 32 GiB storage | Smallest generally-available Flexible Server tier; ample for today's data volume including document bytes still living in Postgres (Milestone 7 moves those, not this one) |
| Data durability requirement | 35-day backup retention, PITR, geo-redundant backup for prod | Matches Sprint 1's own Backup & Disaster Recovery Plan reasoning: backups are cheap relative to what they protect |
| Availability requirement | No zone-redundant HA in either environment | This application's fail-closed design already protects against the failure modes that matter most (`SPECIFICATION/45_PHASE_5_BROKEN_PROMISE_REPORT.md`); infrastructure-level HA is a real, named future option, not a demonstrated current need |
| Deploy frequency | Low — single active revision, no blue-green | Consistent with today's actual deploy cadence (manual, infrequent, per `AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md`) |
| Log retention | 30 days | Proportionate to debugging need; would change if a compliance requirement (out of this program's scope) named a longer window |
| Rate-limiting assumption | Single-instance-safe only | The in-process rate limiter (`server/app/security.py`) still assumes one instance; `max_replicas` is capped at 3 specifically so this assumption is never silently violated before it's fixed (Sprint 1's own deferred Task T12) |
| Staging traffic | Effectively zero, may scale to zero (`min_replicas=0`) | Staging is a rehearsal environment, not customer-facing |
