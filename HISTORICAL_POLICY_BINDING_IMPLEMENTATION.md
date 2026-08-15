# Historical Policy Binding, Implementation

Closes the join the Phase 2 Readiness Audit named: nothing persisted which exact Runtime Policy bundle a historical decision was evaluated against. Re-verified against the current codebase from scratch for this task, not assumed from that earlier audit.

## 1. Data model audit, re-verified

| Concept | Where it lives | Mutability |
|---|---|---|
| The active bundle | `Policy` table (`server/app/db/models.py:198-258`). Exactly one row per organization can have `status='active'` (partial unique index) at a time. | **Immutable per row.** `deploy_policy` (`services/runtime_policy_service.py:658-736`) always creates a new `Policy` row and retires (never deletes or mutates) whatever was active before. Confirmed by reading the function directly: `prior_active.status = "retired"`, then a fresh `Policy(...)` is constructed and added. |
| Policy versions | `RuntimePolicyRecord` table (`db/models.py:778-847`). One row per `(policy_key, version)`, unique-constrained. | **Immutable per row**, by its own docstring: "never mutated after creation... editing produces a new row with an incremented version." Confirmed: `edit_policy` always inserts a new row; the only in-place mutations observed (`row.content`, `row.status`) happen during `submit_for_review`/`approve`/`compile_policy`/`deploy_policy`'s own lifecycle bookkeeping (audit trail enrichment, status transitions), never to the rule-affecting fields (`scope`, `conditions`, `effect`) after creation. |
| Policy content | `RuntimePolicyRecord.content` (JSONB), the full `RuntimePolicy` domain object via `to_dict()`/`from_dict()`. | Immutable per version, as above. |
| The decision | `Decision` table (`db/models.py:662-704`). `policy_id` is a nullable FK to `Policy.id`, set once at creation (`services/intent_service.py:503`, `policy_id = uuid.UUID(engine_decision.policy_id) if engine_decision.policy_id else None`) and never updated afterward (no code path writes `Decision.policy_id` a second time). | Immutable once created. |
| Evidence | `Evidence` table (`db/models.py:707-740`), `payload` JSONB. Already carries `policy_version`/`policy_bundle_hash`/`authority_version` (Phase 1/2A). | Append-only; a resolution creates a second, separate row, never edits the first. |

**What was missing, and only this**: the manifest, which specific `RuntimePolicyRecord` (id + version) rows were compiled together into a given `Policy` row. `compiler_v2.compile_bundle` (`domain/compiler_v2/compiler_v2.py:172`) already builds this exact structure in memory (`PolicyBundle.manifest`, `domain/compiler_v2/bundle_builder.py:73-81, 164-184`), part of what gets hashed into `bundle_hash`, then discarded once the Rego is pushed to OPA. Confirmed directly: `deploy_policy` never persisted `result.bundle.manifest` anywhere before this change.

## 2. The binding, as implemented

```
Decision.policy_id (immutable FK)
   -> Policy row (immutable: bundle_hash, version, compiled_at, activated_at, retired_at)
      -> Policy.bundle_manifest (new: the exact RuntimePolicyRecord id+version list compiled into this bundle)
         -> RuntimePolicyRecord, looked up by (policy_key, version) (immutable content)
```

`GET /v1/decisions/{decision_id}/policy-binding` walks exactly this chain and nothing else. No query touches whatever policy is active today.

## 3. Historical integrity, how it's actually preserved

Not by re-deriving anything at read time; by the fact that every step above was already immutable except the one missing link, which is now populated with a value that was already correct and already computed at the moment it mattered (deploy time), never recomputed later. Editing, superseding, deactivating, or redeploying a policy creates new rows and retires old ones; it never touches an existing `Policy` or `RuntimePolicyRecord` row's identity, hash, or content. Proven, not just argued: see the test report's "historical stability" and "bundle stability" tests.

## 4. Smallest safe implementation

- **Schema**: one nullable JSONB column, `Policy.bundle_manifest` (migration `ed6215ef0acc`, `server/alembic/versions/ed6215ef0acc_policy_bundle_manifest.py`). Additive, matches this codebase's own established migration convention (nullable-first, no backfill possible or attempted for pre-existing rows, since their in-memory manifest no longer exists anywhere to backfill from).
- **Write path**: one line added to `deploy_policy` (`bundle_manifest=result.bundle.manifest`), reusing a value the function already computes for `bundle_hash` two lines above it. No new computation, no new query, no new persistence mechanism.
- **Read path**: one new endpoint, `GET /v1/decisions/{decision_id}/policy-binding` (`server/app/routers/intents.py`), reusing the existing `intent_service.get_decision` lookup and a plain `db.get(Policy, ...)`.
- Reused throughout: existing RuntimePolicy versioning, existing bundle hashing, existing Evidence, existing `runtime_policies.py` org-scoping pattern for the new endpoint's permission model. No second policy engine, no duplicated policy content (the manifest stores only `id`/`name`/`version`/`effect`/`scope`, a pointer plus enough to display without a second query, not the full compiled Rego or condition set), no new persistence architecture.

## 5. Decision API: what's exposed, and why only this

`GetDecisionResponse` (the existing polling endpoint) is **unchanged** by this milestone. `policy_version`/`policy_bundle_hash`/`authority_version` were already added there in Phase 2A, from Evidence, and remain as they were.

The new `DecisionPolicyBindingResponse` exposes: `decision_id`, `policy_id`, `bundle_hash`, `bundle_version`, `compiled_at`, `activated_at`, `retired_at`, and `policies` (the manifest's own list of `{id, name, version, effect, scope}` per included policy). Every one of these is read directly off the immutable `Policy` row `Decision.policy_id` has always pointed to, traceable to the exact historical decision, not to whatever happens to exist in the database today. Nothing was added because it merely existed somewhere; `authority_version` isn't repeated here (it's a decision-engine-wide version, not bundle-specific, already correctly placed on `GetDecisionResponse`), and the full compiled Rego source is deliberately not exposed (available in principle by recompiling from the manifest's `RuntimePolicyRecord`s, but that's real additional work belonging to a future explainability phase, not this one).

## 6. Evidence: independently sufficient, confirmed

Verified directly (see `test_evidence_is_internally_consistent_with_the_bound_policy`) that a real Evidence record's payload, on its own, already establishes: what happened (`action`, `amount`), when (`recorded_at`), who/what acted (`agent_id`, `principal_name`), which authority was involved (`authority_context`, `delegation_chain`), which policy state governed it (`policy_version`, `policy_bundle_hash`, matching the bound `Policy` row exactly), and whether it remains verifiable (`signature`, `previous_hash`, checkable via the existing, untouched `/v1/evidence/{id}/verify` and `/v1/evidence/chain/verify` endpoints). Nothing about the cryptographic evidence model was weakened or altered by this milestone; the binding endpoint is a read path over already-existing, already-immutable rows.

## 7. Explainability preparation: proven, not just argued

`test_explainer_can_reconstruct_the_exact_historical_policy_state` (see the test report) does this concretely: given only a historical `Decision`/`Evidence` pair (after the policy in question has since been redeployed twice, so "the active policy today" bears no resemblance to what actually applied), reconstructs the exact `RuntimePolicy` objects via the manifest and feeds them into the existing `policy_simulation.explainer.build_rule_evaluations`, unmodified. It correctly reproduces the original $100,000 threshold, not the current $1 one. The binding is sufficient for this. The one gap: `intent`/`context` reconstruction currently composes `Intent.context` (real, persisted) with `Evidence.payload["authority_context"]` (real, persisted) by hand at the call site; Phase 2B, if approved, would be the place to formalize that composition into a real function rather than test-only glue code. That is a small wiring task, not a data gap.

## 8. What this milestone deliberately does not touch

No Enterprise Knowledge, no enterprise connectors, no multi-hop authority, no decision confidence, no per-condition live explainability (Phase 2B), no second policy engine, no new evidence architecture. `GetDecisionResponse` was not modified. No existing endpoint's behavior changed, including `GET /v1/decisions/{id}`'s own pre-existing lack of organization scoping, which remains exactly as it was, a separate, pre-existing fact unrelated to this work.
