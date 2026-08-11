# Production Cutover Program — Phase 2: Data Migration Assessment

**Status: plan only. Nothing in this document has been executed.**

## Is migration necessary?

**Yes**, and the burden of proof for "unnecessary" is not met. To prove migration unnecessary would require showing Azure's Postgres already holds Render's current production data. It does not:

- Azure's database (`psql-payreality-staging-cus`) contains exactly what Milestones 3 and 5 put there: one bootstrap organization, one signing-key registration, schema at head — no organizations, agents, policies, or Evidence records reflecting real production use.
- This session has no credentials to query Render's database directly, so it does not claim a specific row count there. That is not needed to reach this conclusion: the architectural fact stands regardless of the exact number — Render has been the operating production system, Azure has not, and no mechanism has ever moved data from one to the other.

Therefore: **migration is required**, and no exact migration plan for it has been produced by any prior milestone. This document produces one now, as a plan, per this phase's instruction not to execute it yet.

## Migration method

PostgreSQL Flexible Server supports direct `pg_dump`/`pg_restore` against a standard `postgresql://` connection string; Render's Postgres exposes exactly that. The recommended method:

1. **Extract**: `pg_dump --format=custom --no-owner --no-acl` against Render's *external* connection string (Render's dashboard exposes both internal and external connection strings; the external one is required since Render's Postgres is not reachable from Azure's VNet).
2. **Stage**: land the dump file somewhere both sides can reach it for the import step — Azure Blob Storage (`stprstagingadzg`, an existing, already-provisioned container) is the natural choice, avoiding a third-party transfer path.
3. **Load**: `pg_restore` against Azure Postgres's connection string, executed from inside the VNet (e.g., via the Container App's own exec access, which already has network reachability to the Postgres subnet — confirmed repeatedly across Milestones 3–5) or a purpose-built one-off migration job.
4. **Reconcile schema**: Azure's schema is already at Alembic head (`d7e28b4c91a6`) from an empty database. Render's schema, if it has been running longer without every Azure-side migration applied in the same order, needs its own `alembic current` checked before the dump — the two must match before `pg_restore` runs, or the restore will fail or produce inconsistent state.

## What requires special handling, not just a generic table copy

- **The Evidence hash chain.** `payload_hash`/`previous_hash` linkage (`server/app/domain/evidence/signing.py`) must survive the copy byte-for-byte — a generic row-by-row migration tool that touches timestamps or column ordering could silently break a chain that verifies today. `pg_dump`/`pg_restore` preserve this correctly (they move raw bytes, not re-serialize), which is the main reason this method is recommended over an application-level export/import.
- **The signing-key registry.** Azure's `signing_keys` table currently has one entry (`signing_key_azure_prod_v1`, Milestone 5). If Render's production Evidence records were signed with Render's own key (`signing_key_prod_v1`, per `render.yaml`), migrated Evidence records will carry `key_id=signing_key_prod_v1`, but Azure's registry doesn't have that key's public key registered — verification would fail post-migration. **Render's actual public key (not the private key) needs to be registered in Azure's `signing_keys` table before or during migration**, or historical Evidence verification breaks on the very first record checked. This is a real, specific technical requirement this assessment surfaces, not a generic caveat.
- **Placeholder secrets.** `ANTHROPIC_API_KEY` is still a placeholder in Azure. If any migrated data depends on AI-generated content being regenerable or on live AI calls at read time, that path is broken until Phase 1's disclosed gap closes — unrelated to the migration mechanism itself, but a real interaction to be aware of.

## Migration window

A **read-only freeze on Render** is required for the actual cutover-time migration (not this assessment's dry run), bounded by however long `pg_dump`+transfer+`pg_restore` takes against the real data volume — unknown without running it once, since this session cannot access Render's actual database size. Recommend measuring this with a real dry run (next section) before committing to a specific window length in the Cutover Plan.

## Validation strategy

1. Row counts per table, Render vs. Azure, post-restore — exact match required, not "close enough."
2. A sample of Evidence records' `verify_payload` result — must return `True` for every sampled record, using the correctly-registered signing key(s) (see above).
3. Alembic `current` on both sides — must match `d7e28b4c91a6` (or whatever the true head is at migration time) exactly.
4. Application-level smoke test (login, one intent submission, one Evidence lookup) against the migrated data, not just raw SQL checks.

## Rollback strategy for this step specifically

Because this method is a **copy**, not a **move**, Render's database is never modified or emptied by the migration itself. If validation fails, the fix is: diagnose, re-run the extract/load with a corrected method, and re-validate — Render's data is never at risk of loss from this step, only Azure's copy needs to be discarded and redone. This is a materially safer migration shape than an in-place transformation would be, and this assessment recommends keeping it that way deliberately.

## Recommended next step, not part of this assessment

Before this plan is trusted for a real cutover window estimate, run it once as a dry run against a disposable copy of Azure's database (not the live one), using Render's actual data, to get real numbers for size, duration, and the exact signing-key-registry adjustment needed. This assessment stops short of that because it is an action, not a plan, and this phase's instruction is "do not execute yet."
