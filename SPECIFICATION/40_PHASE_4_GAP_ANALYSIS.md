# Part 40 — Phase 4 Gap Analysis

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md). **Scope:** Intent Intelligence, Context Intelligence, Enterprise Decision Pipeline only.

## What still remains implicit

- **Per-action Blueprint variance.** Every recognized `action` shares one field set today; nothing in the schema, compiler, or Decision Engine expresses "this action additionally requires field X." The moment a second action genuinely needs a field the others don't, this becomes visible pressure rather than a hypothetical.
- **`counterparty` -> `Scope.resource`.** `runtime_policy.py` already names the intended generalization; no code path populates it from a submitted Intent. A `RuntimePolicy` authored with a `scope.resource` value today can never actually match on it through the normal Intent-submission path.
- **`currency` as a live Condition input.** Reaches the OPA input (`intent.currency`); zero shipped policies condition on it; no vocabulary constrains its values ([32](32_PHASE_3_GAP_ANALYSIS.md)). Implicit today: whether an unrecognized or malformed currency string should behave like an unrecognized `action` (`HUMAN_REVIEW`) is undecided, because nothing has ever needed to decide it.
- **`policy_version` in the OPA input, uncheckable by Rego.** Present in every OPA query; no generated Rego references it ([12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) §12.6). Carried forward from the Phase 2 report, still open.

## What should intentionally remain implementation detail

- **Which specific function resolves `organization`/`business_unit`/`department`/`team`.** `authority_context_service._name_or_none`'s FK-lookup mechanics are exactly that — mechanics. [29](29_PHASE_3_RESOLVER_INTELLIGENCE_SPEC.md) already names the discipline-level fact (source, method, freshness); the helper function's own signature is not architecturally significant and should not be promoted into a specification.
- **The exact dict-spread expression building `context`** (`{**context, "timestamp": ..., "authority": ...}`). [36](36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md) documents the *distinction* this expression encodes (caller-supplied vs. runtime-enriched); the Python syntax used to encode it is implementation detail that can change freely without any architectural document needing an update.
- **`_resolve_chain_scope`/`_previous_chain_hash`'s query shape.** Decision Evidence's chaining mechanism is already specified at the architectural level ([13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md)); this phase's pipeline stage table cites it by name (Stage 9) without re-deriving its SQL.

## What belongs in Phase 5 (Integrity Intelligence)

- **Whether the pipeline's own documentation stays true over time.** This phase produced a snapshot ([37](37_PHASE_4_ENTERPRISE_DECISION_PIPELINE_SPEC.md), [38](38_PHASE_4_PIPELINE_SEQUENCE_DIAGRAM.md)) accurate as of `runtime-governance-phase-4`. Whether that snapshot is still accurate after a future code change is exactly Integrity Intelligence's question ("does the architecture's own promise about itself stay true"), not something Phase 4 can answer about its own future.
- **`MASTER_ROADMAP.md`/`VERSION_3_ROADMAP.md` drift**, carried forward unaddressed since the Phase 2 report.
- **Monitoring that a future stage addition doesn't silently break the fail-closed guarantee** ([12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) §12.1's "exactly one code path to ALLOW"). Phase 2's boundary tests catch dependency violations; nothing today would catch a second `ALLOW` path being introduced by accident — a longitudinal, Integrity Intelligence concern.

## What this phase did not need to solve

None of the gaps above blocked Phase 4's actual objective (making the existing pipeline explainable by inspection, and closing the one concrete replay gap found). Each is recorded here so it is visible and intentional.
