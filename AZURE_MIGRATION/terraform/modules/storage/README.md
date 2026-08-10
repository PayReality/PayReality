# Module: storage

**Owner:** platform/infrastructure engineer. **Purpose:** object storage for document uploads, evidence exports, and (ahead of build, per this milestone's own instruction) Authorization Receipts — the Azure home for the one thing Sprint 1's assessment found had no dedicated home at all (uploaded document bytes have lived directly inside Postgres until now).

## What this module creates

- One Storage Account, **no public network access**, versioning and 30-day soft-delete on both blobs and containers.
- One Private Endpoint (blob subresource) into the shared `privatelink.blob.core.windows.net` DNS zone.
- Three containers: `uploads`, `evidence-exports`, `authorization-receipts`.
- A lifecycle management policy: `uploads` tiers to Cool after 90 days; `evidence-exports` and `authorization-receipts` tier to Cool after 180 days. **Neither rule ever deletes anything** — both categories are compliance-relevant records this platform's own architecture already treats as permanent (`SPECIFICATION/45_PHASE_5_BROKEN_PROMISE_REPORT.md`'s append-only-evidence promise); an automatic deletion rule on either would contradict that outright.
- One role assignment: the Container App's managed identity gets **Storage Blob Data Contributor**, scoped to this account only.

## Why `authorization-receipts` exists before Authorization Receipts do

This milestone's own instructions ask this module to design storage for "future Authorization Receipts." The container is provisioned now, empty, for the same reason Postgres's database is provisioned empty pending Milestone 4's data migration and Container Apps' image is a placeholder pending Milestone 6 — infrastructure exists ahead of the feature that will use it only when a milestone's own instructions say so explicitly, never on this module's own initiative.

## Retention strategy

30-day soft delete (accidental-deletion recovery window) on top of the never-delete lifecycle policy above. Together: nothing in `evidence-exports`/`authorization-receipts` is ever automatically removed, and even a manual/accidental deletion has a 30-day undo window before it's final.

## Access control

Private Endpoint only; RBAC (`Storage Blob Data Contributor`) for the one identity that needs it; `allow_nested_items_to_be_public = false` at the account level, so no container or individual blob can be made public even by a future, well-intentioned misconfiguration.

## Inputs / Outputs

See `variables.tf`/`outputs.tf`. `replication_type` defaults to `LRS`; set to `GRS` for `prod` in `environments/prod.tfvars` (documented, not hardcoded, matching the same environment-specific-value pattern used in `modules/postgres`).
