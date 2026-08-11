# Module: alerts

**Owner:** platform/infrastructure engineer. **Purpose:** closes the single largest gap Milestone 4's validation found — zero alert rules existed anywhere in this environment, so nothing paged anyone on failure (`MILESTONE_4_RISK_REGISTER.md` #1). This module is Milestone 5's fix.

## What this module creates

One email-based action group, and five metric alert rules against real, `az`-confirmed metric names (not assumed from documentation) on the three resources most likely to fail silently:

- **Postgres availability** (`is_db_alive < 1`, Sev 0) — a dead database is a full outage of every feature.
- **Postgres storage** (`storage_percent > 85`, Sev 2) — actionable before it becomes an outage.
- **Container App restarts** (`RestartCount > 0`, Sev 1) — a crash loop reads as "restarting," not "down," to a plain health check.
- **Container App CPU** (`CpuPercentage > 80`, Sev 2) — approaching the point where requests start queuing.
- **Key Vault availability** (`Availability < 95`, Sev 1) — every secret-backed startup depends on this vault answering correctly.

## Why five specific rules, not a generic "monitor everything" approach

Each rule targets a failure mode this program has actually reasoned about or observed: the Postgres/Key Vault dependency chain that gates every container startup, and the restart/CPU signals that a simple `/health` check (itself dependent on the process being up enough to answer) can miss. More rules can be added the same way; these five are the minimum that closes the specific gap Milestone 4 found, not a ceiling.

## Inputs / Outputs

`resource_group_name`, `environment`, `tags`, `notification_email` (no default — every environment must consciously set this), and the three resource IDs to monitor. Outputs the action group's ID and name, in case a future module needs to attach its own alert to the same notification target.
