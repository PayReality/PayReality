# Historical Policy Binding Analysis

Research only, per instruction. Nothing here was implemented. This investigates precisely the gap the Phase 2 Readiness Audit named: nothing currently persists which exact Runtime Policy bundle a historical decision was evaluated against. The finding is more specific, and the fix smaller, than that audit assumed.

## What is currently persisted

- **`Decision.policy_id`** (`server/app/db/models.py:669`): a nullable foreign key to a specific `Policy` row. Confirmed by reading `deploy_policy` (`services/runtime_policy_service.py:661-701`) that every deploy **creates a new `Policy` row** and retires (never deletes or mutates) whatever was previously active for that organization. `Decision.policy_id` is therefore already a durable, immutable pointer to the exact bundle-row active at evaluation time, this part of the problem is already solved and has been all along.
- **`RuntimePolicyRecord`** (`db/models.py:778-798`): "One row per version, never mutated after creation... editing produces a new row with an incremented version," by its own docstring. Every historical version of every policy's actual content is permanently retained.
- **`Evidence.payload`**: `policy_version`, `policy_bundle_hash`, `authority_version` (Phase 1, now also on `GetDecisionResponse` as of Phase 2A). These identify *which bundle* (by hash and version number) was active, correctly and durably.

## What is actually missing

The **manifest**, the list of which specific `RuntimePolicyRecord`s (by id and version) were compiled into a given `Policy` bundle row. `compiler_v2/bundle_builder.py:164-184` computes exactly this at compile time:

```python
manifest = {
    "bundle_id": bundle_id, "version": bundle_version,
    "compiler_version": COMPILER_VERSION, "compiled_at": now.isoformat(),
    "policies": [{"id": p.id, "name": p.name, "version": p.version, "effect": p.effect.value, "scope": {...}} for p in policies],
}
```

This manifest is part of what gets hashed into `bundle_hash` (line 196, `hashable_manifest`), then used only to generate the Rego source pushed to OPA. **It is never persisted anywhere.** The `Policy` model has no `manifest` column; `bundle_uri` is a synthetic string, not a retrievable artifact (confirmed in the earlier Phase 2 audit). Once `compile_bundle` returns, the manifest exists only in memory for the duration of that one request.

## Precisely what this means

Both halves of "which policies were evaluated" that most people would assume are linked are actually independently durable:
1. **Which bundle was active**: solved, via `Decision.policy_id` pointing to an immutable `Policy` row.
2. **What each individual policy's content was at any past version**: solved, via immutable `RuntimePolicyRecord` rows.

The missing link is only the **join between them**: given a `Policy` row, which `RuntimePolicyRecord` (id + version) rows were its members. Without that join, you cannot answer "what were the actual conditions RuntimePolicySimulator's explainer would need" for a bundle compiled six months ago, even though every individual fact required to answer it still exists somewhere in the database.

## Whether it can be safely attached to the decision/evidence record

Yes, and narrowly. The manifest is already computed, in memory, at the exact moment `deploy_policy` calls `compile_bundle` (`runtime_policy_service.py:678-680`). Persisting it requires no new computation, no recomputation of anything historical, and no change to what's evaluated at runtime; it's writing down a value that already exists at that instant and is currently thrown away. This is the single smallest, safest possible fix to this problem, exactly the kind of "smallest possible addition" this task's other workstreams asked for elsewhere, just not authorized for implementation in this task.

## What schema/API changes would eventually be required

1. **Schema**: add a `manifest` JSONB column to the `Policy` table (`db/models.py`), or a separate `policy_bundle_members` join table if a queryable per-row join is preferred over a JSONB blob. Either is additive; neither touches any existing column or any other table.
2. **Write path**: in `deploy_policy` (`runtime_policy_service.py`), persist the `manifest` (or the `bundle_policies` list it's built from) onto the new `Policy` row at the same point it's already computed, before or alongside the existing `db.add`/commit for that row. No new query, no new computation.
3. **Read path**: a new function (e.g., `get_policy_manifest(db, policy_id)`) that a future explainability feature would call, given `Decision.policy_id`, to retrieve the exact set of `RuntimePolicyRecord`s (id + version) to feed into `policy_simulation/explainer.py`'s existing `RuleEvaluation`/`ConditionEvaluation` logic, alongside the already-solved problem of reconstructing `intent`/`context`/`principal` from `Intent` columns and `Evidence.payload` (confirmed available in the Phase 2 Readiness Audit).
4. **No backfill is possible** for decisions made before this column exists: old `Policy` rows have no manifest and cannot get one retroactively (the in-memory manifest at their compile time is gone). This is a limit worth stating plainly now, before anyone assumes a future explainability feature would work uniformly across all historical decisions; it wouldn't, only for ones evaluated after this change ships.

## Correction to the prior Phase 2 Readiness Audit

That audit's framing, "nothing persists which exact set of `RuntimePolicyRecord`s a past Decision's bundle actually contained," is accurate as a description of the symptom but understated how solved the rest of the problem already is. It is not a broad architectural gap. It is one missing join, backed by two already-immutable data sources, fixable by persisting a value that is already computed and already discarded. This does not change the recommendation to design before implementing (a JSONB-vs-join-table decision, a backfill-impossibility disclosure, and the actual explainer-wiring work all still deserve their own pass), but it means that design pass is small, not the "genuinely new architecture" tier of work Bucket C's other items belong to.
