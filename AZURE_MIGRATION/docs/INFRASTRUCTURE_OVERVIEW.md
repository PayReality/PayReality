# Infrastructure Overview

**Status:** final, Milestone 2. **Scope:** what the Terraform project under `AZURE_MIGRATION/terraform/` provisions, and how it relates to the Render deployment it will eventually replace (`AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md`).

## What exists after this milestone

Nothing in Azure — Milestone 2 is design and authoring only. What exists is a complete, `terraform validate`-passing, modular IaC project that Milestone 3 applies.

## The ten modules, in dependency order

1. **resource-group** — the container everything else lives in.
2. **networking** — VNet, three delegated/undelegated subnets, two generic Private DNS zones.
3. **managed-identity** — two identities: the Container App's runtime identity, and a separate GitHub-Actions-federated CI/CD identity.
4. **key-vault** — RBAC-authorized, Private-Endpoint-only, owns every secret (real ones Terraform itself generates, placeholders for the four Render-originated ones Milestone 5 populates out-of-band).
5. **postgres** — Flexible Server, VNet-integrated (no public endpoint), empty until Milestone 4's data migration.
6. **storage** — Blob Storage for uploads/evidence-exports/authorization-receipts, Private-Endpoint-only, empty until Milestone 7.
7. **container-registry** — Standard SKU, AAD-only auth, empty until Milestone 6 pushes a real image.
8. **container-apps** — the compute target Milestone 1's Discovery found missing from the original service list; runs today's exact container image once Milestone 6 supplies it, wired to every secret above already.
9. **monitoring** — Log Analytics + Application Insights, no alert rules yet (Milestone 8).
10. **diagnostics** — routes every other resource's logs/metrics into (9).

## What this replaces, one line each

| Render/Vercel today | Azure after Milestone 3 |
|---|---|
| One free web service, embedded OPA | One Container App, same container, same embedded OPA, unchanged |
| One free Postgres, expiring, no backups | Flexible Server, 35-day backups, PITR, private only |
| Document bytes in Postgres | Blob Storage (Milestone 7 — not yet moved) |
| Env vars in Render's store | Key Vault, resolved via managed identity |
| No registry (builds from Dockerfile) | Container Registry, AAD-only |
| Nothing | Log Analytics + App Insights |

## What Milestone 2 explicitly did not do

Deploy anything. Modify `server/app/` (confirmed — see the Conformance Report). Configure an alert. Migrate data. Move a secret's real value anywhere.
