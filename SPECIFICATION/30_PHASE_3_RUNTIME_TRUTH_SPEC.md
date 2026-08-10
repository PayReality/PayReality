# Part 30 — Phase 3: Runtime Truth Specification

**Status:** Phase 3 implementation complete, tested, uncommitted pending this specification. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md). **Depends on:** [28](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md), [29](29_PHASE_3_RESOLVER_INTELLIGENCE_SPEC.md).

## Purpose

Runtime Truth is the boundary between *resolving what is true right now* and *evaluating whether it's permitted*. This platform has always respected that boundary in its control flow — `submit_intent` has never once let a resolution step and an authority-evaluation step interleave. What it lacked was a name and a single call site for the resolution half. This phase adds exactly that, and nothing else.

## The boundary, as it already existed

Before this phase, `services/intent_service.py::submit_intent` performed, inline, in this fixed order:

1. Look up the Agent's Principal (Principal Directory).
2. Call `authority_context_service.resolve_runtime_authority_context(db, principal, amount)`.
3. Call `decision_engine.evaluate(...)`, passing the two resolved values in as `acting_for_principal_id` and `context["authority"]`.

Nothing between steps 1–2 and step 3 ever fed a Decision Engine output back into resolution, and nothing inside `decision_engine.evaluate` ever performed its own lookup — confirmed structurally, not just by convention, by the Phase 2 boundary test `test_decision_engine_imports_nothing_from_db_services_or_routers` ([27](27_PHASE_2_CONFORMANCE_REPORT.md)), which was already passing before this phase began. The separation was real. It was only unnamed and scattered across two local variables in one function body.

## What this phase changed

A new module, `server/app/services/runtime_truth_service.py`:

```python
@dataclass(frozen=True)
class ResolvedFacts:
    principal: Principal | None
    principal_name: str
    authority_context: dict

def resolve(db: Session, agent: Agent, amount: float | None) -> ResolvedFacts:
    principal = db.get(Principal, agent.acting_for_principal_id)
    principal_name = principal.name if principal else str(agent.acting_for_principal_id)
    authority_context = resolve_runtime_authority_context(db, principal, amount)
    return ResolvedFacts(principal=principal, principal_name=principal_name, authority_context=authority_context)
```

`submit_intent` now calls `runtime_truth_service.resolve(db, agent, amount)` once, in place of the inline two-step sequence, and reads `resolved.principal`, `resolved.principal_name`, `resolved.authority_context` everywhere it previously read the two local variables directly.

`authority_context_service.py` is unchanged. `resolve_runtime_authority_context`'s own logic, `classify_risk`'s thresholds, and every query inside `_active_inbound_delegations` are byte-identical to before this phase.

## Why this is an extraction, not a redesign

- **Zero new resolution logic.** Every line inside `resolve()` already existed in `submit_intent`, moved verbatim.
- **Zero new dependency.** `runtime_truth_service.py` imports `authority_context_service` — a dependency `intent_service.py` already had; this phase relocates the call, it does not introduce a new edge between disciplines.
- **Zero behavior change**, verified: the full test suite (182 tests as of this phase, up from 180 — see Migration Report [33](33_PHASE_3_MIGRATION_REPORT.md) for the two additions) passes identically before and after this change.
- **One new name.** `ResolvedFacts` gives Decision Evidence and Runtime Authority a single, frozen, typed value to both consume — replacing two loosely-related local variables that happened to always be computed together.

## What this specification deliberately does not do

- It does not introduce a `RuntimeTruthService` class, a caching layer, or a pluggable resolver interface. `resolve()` is a plain function because a plain function is all the one real call site (`submit_intent`) has ever needed.
- It does not change where in the request lifecycle resolution happens. Resolution still happens exactly once, immediately before `decision_engine.evaluate()`, exactly as before.
- It does not attempt to make `ResolvedFacts` a general-purpose "current state of the world" object. It holds exactly the two things `submit_intent` already carried forward into evidence and evaluation — nothing more was added on the theory that a future consumer might want it.
