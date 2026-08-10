# Module: postgres

**Owner:** platform/infrastructure engineer (provisioning); whoever holds database-admin responsibility thereafter. **Purpose:** the primary application database — the direct Azure replacement for Render's `payreality-db`.

## What this module creates

- One PostgreSQL Flexible Server, v16, **private access only** (VNet-integrated via the delegated `postgres` subnet from `modules/networking` — no public endpoint, no separate `azurerm_private_endpoint` resource, since Flexible Server's VNet integration is its own distinct mechanism from the generic Private Endpoint used by Key Vault/Storage).
- Its own dedicated Private DNS Zone (name tied to the server itself, per Azure's requirement — see the networking module's README for why this isn't created there instead).
- One application database inside the server.
- A generated 32-character administrator password (`random_password`), written immediately into Key Vault as `postgres-administrator-password` — never output in plain Terraform output, never referenced in any `.tfvars` file.
- A full, ready-to-use `DATABASE_URL` connection string (matching `app/config.py`'s exact expected scheme, `postgresql+psycopg://`, with `sslmode=require` added — Flexible Server enforces TLS by default and today's Render connection strings don't specify it), written into Key Vault as `database-url`.

## Sizing assumptions

`B_Standard_B1ms` (Burstable), 32 GiB storage — proportionate to today's pilot-scale traffic (`AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md`), not a guess at enterprise load. Both are variables, changed by editing `environments/*.tfvars`, not by editing this module, when real usage data justifies a bigger tier.

## Backup strategy and PITR

`backup_retention_days` defaults to **35, the maximum Azure allows** — backups are among the cheapest resources in this entire project relative to what they protect. Point-in-time recovery is automatic within that retention window; Flexible Server has no separate "enable PITR" toggle to set — restoring to any point within the retained window is simply how `az postgres flexible-server restore` already works. `geo_redundant_backup_enabled` defaults to `false` in this module and should be set `true` for `prod` specifically in `environments/prod.tfvars` — staging's data is disposable, so paying for its geo-redundant backup has no matching benefit.

## High availability options

Zone-redundant HA is supported (`high_availability_enabled`) but **off by default in every environment today**. Named as a real, understood future-expansion option, not built ahead of a demonstrated need — this application's own layer is already fail-closed by construction (`SPECIFICATION/45_PHASE_5_BROKEN_PROMISE_REPORT.md`), and no incident so far has been caused by the infrastructure-level failure mode HA protects against.

## Connection strategy

The application connects using the standard `postgresql+psycopg://` scheme it already uses today, over TLS, resolved through the server's own private DNS zone from inside the VNet — the Container App never needs a public route to the database, and the database is unreachable from the public internet at all.

## Migration path from Render (no data migration performed by this module)

This module provisions an **empty** server and database. Milestone 4 is what actually moves data (`pg_dump`/`pg_restore`, per `AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md`'s risk #6) — right-sized for this platform's current data volume, not Azure Database Migration Service, which would be disproportionate tooling for a pilot-scale database.

## Inputs / Outputs

See `variables.tf`/`outputs.tf` — every input is either a cross-module reference (VNet/subnet/Key Vault IDs) or a documented, overridable default; every output is an identifier or a Key Vault secret *name*, never a secret value.
