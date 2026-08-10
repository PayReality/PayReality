# Phase 0: Legacy Removal & Platform Stabilisation

Status: proposed. This phase precedes and is independent of the rest of the transformation program's sequencing — it addresses a live risk in the current platform, not a step toward a future capability. Nothing here should wait on Phase 1 planning to complete.

## Why this phase exists

`RUNTIME_AUTHORITY_TRANSFORMATION.md` §1 identified a genuine, currently-live architectural risk: two independently-triggerable code paths write to the exact same OPA package (`"authorization"`) and the exact same single-active-row slot in the `policies` table, with zero coordination between them.

- **Path A (legacy)**: `domain/compiler/compiler.py` (`compile_authorities`, `REGO_TEMPLATE`) → `services/policy_service.py` (`compile_document`, `activate_policy`) → mounted live via `routers/policies.py`.
- **Path B (current)**: `domain/compiler_v2/` → `services/runtime_policy_service.py` (`deploy_policy`) → mounted live via `routers/runtime_policies.py`.

Both call `HttpOpaClient.upload_policy("authorization", ...)`. Both write a new active row into the same `policies` table, retiring whatever was previously active there. Neither path is aware the other exists. A deploy through either one silently clobbers whatever the other path last pushed into OPA, with no error, no warning, and no audit trail of the collision itself.

This phase eliminates that risk by ending with **exactly one live Runtime Policy pipeline** — Compiler V2 / Runtime Policy Studio — and either safely retiring or explicitly disabling the legacy path's ability to write to production enforcement.

## What "legacy" means here, precisely

Not everything touched by the legacy pipeline is legacy. Distinguish carefully:

- **Legacy and in scope for removal from the live write path**: `domain/compiler/compiler.py`'s `REGO_TEMPLATE`/`compile_authorities`; `services/policy_service.py`'s `compile_document`/`activate_policy`; the document-upload-and-review authoring surface in `routers/policies.py`; the `Authority`/`Mandate`/`Constraint` tables as an *authoring* target (not necessarily as historical data — see Rollback Strategy). This removal executed as planned (see `SPECIFICATION/17_LEGACY_COMPONENTS.md`). **Update (Authority-as-a-continuous-object, Stage G):** `Authority`/`Mandate` later gained a *different*, new authoring target unrelated to the one removed here (`ai_policy_builder_service`/`runtime_policy_service`, not `routers/policies.py`) — the removal described in this document and the later revival are two separate write paths, not a reversal of this plan.
- **Not legacy, shared, and unaffected**: the `Principal` table (used by both pipelines identically — `RuntimePolicy.scope.principal` matches against `Principal.name` the same way `Authority.principal_id` always has); `routers/principals.py`'s plain `create_principal`/`list_principals` endpoints (these are generic principal management, not part of the legacy compilation pipeline); the `policies` DB table's *schema* (both pipelines write rows of the same shape; only the legacy *writer* is retired, not the table).

## Removing the Legacy Authority/Mandate Pipeline

This directly reuses `MIGRATION_PLAN_V4.md` Phase D's already-designed approach rather than inventing a new one, since that plan was specifically scoped around this exact retirement:

1. **Backfill**: for every currently-`active` legacy `Policy`/`Mandate` row, produce an equivalent `RuntimePolicy` draft (`max_amount`/`currency` become `Condition{field: "amount", operator: "<=", value: max_amount}` plus, if set, a currency condition). One draft per distinct principal+scope grant.
2. **Review**: each backfilled draft goes through Policy Studio's real lifecycle — submit for review, approve, compile, dry-run against a sample of recent historical Intents (to confirm it reproduces the same decisions the legacy policy was producing), deploy. Never auto-promoted to active without this review.
3. **Cutover verification**: for a defined verification window, run both the legacy policy and its backfilled `RuntimePolicy` equivalent's dry-run against the same live traffic sample and confirm identical outcomes before deploying the new one for real.
4. **Disable, don't delete, the authoring surface**: once every backfilled policy is deployed and verified, `routers/policies.py`'s document-upload/compile/activate endpoints return `410 Gone` (or an equivalent explicit "retired" response) rather than being removed from the router table outright in this phase. This preserves the ability to inspect what those endpoints were for during the stabilisation window, and makes the retirement observable (a monitoring alert on any remaining caller hitting a `410` surfaces integrations nobody knew still existed).
5. **Data preserved**: `Authority`/`Mandate`/`Constraint` rows are never deleted. They remain queryable for audit continuity — every Evidence record ever produced under the legacy pipeline references a `policy_id` that still resolves, and `EVIDENCE.md`'s append-only, tamper-evident guarantee already covers this regardless of which compiler produced the policy behind a given historical decision.
6. **Actual code removal** (deleting `compiler.py`, `policy_service.py`, the disabled router functions) is an explicit, separate, later decision — not part of this phase — made only once nothing in production still depends on them and only with direct sign-off, given how consequential deleting a production authorization code path is, even a disabled one.

## Eliminating Dual OPA Writers

Once step 4 above lands, there is exactly one code path (`runtime_policy_service.deploy_policy`) capable of calling `HttpOpaClient.upload_policy("authorization", ...)`. No new abstraction is needed to "coordinate" two writers — the fix is removing the second writer's ability to write, not building a lock/coordinator between two systems that shouldn't both exist.

As a defense-in-depth measure (not a substitute for the above): add an assertion at `deploy_policy`'s upload step that the bundle_hash comparison it already performs (`BundleChangedSinceCompileError`) also confirms the *previous* active policy's `bundle_uri` matches the expected `runtime_policy_studio:...` format — if it doesn't (i.e., something else wrote to that slot), fail loudly rather than silently overwriting. This catches any residual writer this phase might have missed, including the reconciliation-on-startup logic added earlier this engagement (`main.py`'s `_reconcile_opa_with_active_policies`), which itself only reconciles from `RuntimePolicyRecord`'s active rows — confirm it does not need any change once the legacy writer is gone, since it was never aware of the legacy path to begin with.

## Unifying Deployment

"Deployment" here means the OPA-writing act itself, already unified once dual-writer status ends. No separate "unify deployment" engineering work is needed beyond what's described above — this heading is retained to make explicit that after this phase, "deploy a policy" means exactly one thing, through exactly one function, with exactly one target.

## Simplifying Routing

- `routers/policies.py`: authoring endpoints (`POST /v1/policies/documents`, compile, activate) return `410` per step 4 above. Any read-only endpoints that serve historical data (e.g. viewing a legacy `Authority`/`Mandate` record for audit purposes) remain live and unchanged — this phase retires *authoring*, not *history*.
- `routers/principals.py`: unchanged. It's shared infrastructure, not part of the legacy pipeline.
- No route path changes, no redirects needed beyond what already exists from the earlier URL-naming cleanup this engagement already performed.

## Removing Dead Models

- `Intent.requested_scope` and `Intent.metadata` (the `metadata_` column): confirmed via exhaustive grep to be declared but never written by any code path. Two options, not one prescribed answer — this decision should be made deliberately, not defaulted:
  - **(a) Remove the columns.** Cleanest, but is a genuine schema change to a live production table with historical rows; requires a migration and a rollback plan (below).
  - **(b) Leave them, documented as reserved/unused.** Zero risk, defers the decision. Given this phase's own stated goal is debt *removal*, not just risk mitigation, (a) is the recommended default — but only after confirming (via a production data check, not assumption) that zero historical rows have non-null values in either column, since a non-null historical value would mean something *did* write them at some point via a path this audit missed.
- No other dead models were found in the current audit beyond these two columns and the legacy Authority/Mandate authoring surface itself (already covered above).

## Removing Duplicate APIs

- The AI Policy Builder (`routers/ai_policy_builder.py`) and AI Authority Builder's embedded "policies" category (`routers/ai_authority_builder.py`) both ultimately call the same `promote_candidate`-shaped logic against the same `policy_extraction_candidates` table, keyed by `upload_id` vs. `corpus_id` respectively. This is **not** recommended for removal in Phase 0 — the Authority Builder is a superset used for multi-document Authority Model extraction (Phase 1+), while the Policy Builder's single-document flow remains a legitimate, simpler authoring surface for a single policy from a single document. Consolidating these is explicitly deferred to Phase 6 (Platform) or later, once real usage data shows whether the simpler single-document flow is still used once the Authority Builder is fully wired to Phase 1's model — removing it now would be premature.

## Migration Strategy

1. Ship the backfill tooling (step 1 above) as an internal, operator-triggered script/endpoint — not automatic, not run against production without explicit review of its output first.
2. Run backfill in a non-production environment first; manually diff every backfilled `RuntimePolicy` draft against its source legacy policy's actual semantics before trusting the mechanical translation.
3. Run the cutover verification window (step 3) in production with both pipelines still live, comparing dry-run outcomes only — no real decisions depend on the backfilled policies yet.
4. Deploy backfilled policies for real, one at a time, each independently verified via a follow-up live dry-run confirming the deployed bundle produces the expected decision for a known test Intent.
5. Disable the legacy authoring surface (`410`) only after every backfilled policy is confirmed active and correct.
6. Decide the dead-column removal (schema migration) as a separate, small, independently-reversible migration — do not bundle it with the backfill/cutover work above, since it has nothing to do with the OPA-writer risk and bundling unrelated changes makes rollback harder to reason about.

## Rollback Strategy

- **Backfill/cutover rollback**: since the legacy pipeline is never modified or disabled until step 5, rolling back at any point before step 5 is simply "stop deploying backfilled policies" — the legacy pipeline continues operating exactly as it did before this phase started. This is the reason step 5 (disabling the legacy surface) is deliberately the *last* step, not an early one: it's the one step in this phase that isn't trivially reversible by inaction.
- **Post-disable rollback**: if disabling the legacy authoring surface (`410`) surfaces an unexpected dependency (some caller nobody knew about), re-enable the endpoints (revert the `410` change) — this is a fast, low-risk code revert, since no data was deleted and no schema changed in that step.
- **Dead-column removal rollback**: standard schema-migration rollback discipline — the migration should be written as a reversible pair (add column back, migration framework's own down-migration), and should not be deployed in the same release as any other Phase 0 change, so it can be rolled back independently if needed.
- **General principle**: every step in this phase is sequenced so that the *hardest-to-reverse* action (disabling legacy authoring) happens last, after every softer, fully-reversible step has already been verified — matching the same "verify before you can't go back" discipline `MIGRATION_PLAN_V4.md` already uses for its own Phase D.

## Exit Criteria

Phase 0 is done when:
1. `routers/policies.py`'s authoring endpoints return `410` and have for a defined stabilisation period (recommend: one full billing/reporting cycle) with zero unexpected caller alerts.
2. Every historical legacy-pipeline decision still has a resolvable `policy_id` and independently-verifiable Evidence.
3. Exactly one function in the codebase can call `HttpOpaClient.upload_policy`.
4. The dead-column decision (remove or formally document as reserved) has been made and executed, not left ambiguous.
5. Full existing test suite passes, unmodified in intent (test *files* may move/rename to reflect the retired surface, but no test's *assertion* about current-pipeline behavior changes).
