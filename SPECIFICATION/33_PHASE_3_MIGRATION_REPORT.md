# Part 33 — Phase 3 Migration Report

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md), frozen at tag `runtime-governance-phase-2`. This report itemizes every code change this phase made — two, both minimal, both behavior-preserving — plus the boundary each one extracts or clarifies.

## Change 1: `FinancialVocabulary.known_actions` now imports `KNOWN_SCOPES` instead of restating it

**File:** `server/app/domain/compiler_v2/compiler_v2.py`

**Before:**
```python
@dataclass(frozen=True)
class FinancialVocabulary:
    known_actions: frozenset[str] = frozenset(
        {"vendor_payment", "purchase_order_create", "wire_transfer"}
    )
```

**After:**
```python
from app.domain.decision.scope_vocabulary import KNOWN_SCOPES

@dataclass(frozen=True)
class FinancialVocabulary:
    known_actions: frozenset[str] = KNOWN_SCOPES
```

**Discipline:** Canonical Fact Intelligence ([28](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md)).

**Why:** The `action` fact previously had two independent definitions of its identity — `scope_vocabulary.py::KNOWN_SCOPES` (used by `intent_service.py` to short-circuit unrecognized actions to `HUMAN_REVIEW`) and this hand-copied literal (used by the compiler to validate a `RuntimePolicy`'s `scope.action` at compile time). They happened to contain the same three strings, kept in sync only because whoever last edited one remembered to edit the other. This is precisely the failure mode Canonical Fact Intelligence exists to catch.

**Behavioral change:** None. `KNOWN_SCOPES` and the literal it replaces are set-equal; `is_valid_action` returns identical results for every possible input, before and after. Verified: `pytest tests/unit/test_compiler_v2.py tests/unit/test_architectural_boundaries.py -q` — 27 passed, both before and after.

**New dependency introduced:** `domain/compiler_v2` now imports from `domain/decision`. This is a `domain -> domain` edge (both sides remain free of `app.db`, `app.services`, `app.routers`), consistent with Phase 2's declared boundary rules ([26](26_PHASE_2_DEPENDENCY_DECLARATION.md)) — no forbidden edge was crossed. Re-verified by rerunning `test_architectural_boundaries.py`'s `test_domain_package_never_imports_app_db` after this change.

## Change 2: Runtime Truth extracted into `server/app/services/runtime_truth_service.py`

**Files:** `server/app/services/runtime_truth_service.py` (new), `server/app/services/intent_service.py` (edited).

**Before** (`intent_service.py::submit_intent`, inline):
```python
principal = db.get(Principal, agent.acting_for_principal_id)
principal_name = principal.name if principal else str(agent.acting_for_principal_id)
authority_context = resolve_runtime_authority_context(db, principal, amount)

engine_decision = decision_engine.evaluate(
    intent={"action": action, "amount": amount, "currency": currency},
    context={**context, "timestamp": to_utc_iso(requested_at), "authority": authority_context},
    acting_for_principal_id=principal_name,
    policy_store=_DbPolicyStore(db),
    opa_client=_EngineOpaClient(HttpOpaClient()),
)
```

**After:**
```python
resolved = runtime_truth_service.resolve(db, agent, amount)

engine_decision = decision_engine.evaluate(
    intent={"action": action, "amount": amount, "currency": currency},
    context={**context, "timestamp": to_utc_iso(requested_at), "authority": resolved.authority_context},
    acting_for_principal_id=resolved.principal_name,
    policy_store=_DbPolicyStore(db),
    opa_client=_EngineOpaClient(HttpOpaClient()),
)
```

The downstream `append_evidence(...)` call's arguments changed from `principal_id=principal.id if principal else None, authority_context=authority_context` to `principal_id=resolved.principal.id if resolved.principal else None, authority_context=resolved.authority_context`. The import of `resolve_runtime_authority_context` directly into `intent_service.py` was removed (no longer called from there); `runtime_truth_service` is imported in its place, alongside the still-needed `classify_risk` import from `authority_context_service`.

**Discipline:** Runtime Truth ([30](30_PHASE_3_RUNTIME_TRUTH_SPEC.md)).

**Why:** `submit_intent` already resolved facts and evaluated authority as two non-interleaved steps; the extraction gives that existing separation a name and a single call site instead of two local variables recomputed inline.

**Behavioral change:** None. Every line inside `runtime_truth_service.resolve` is the pre-existing inline code, moved verbatim — no condition, ordering, or value changed. Verified: full suite (`pytest tests/ -q`) — 180 passed before this change, 182 passed after (the two additions are new tests, described below; zero pre-existing test's outcome changed).

**New dependency introduced:** `services/runtime_truth_service.py` imports `services/authority_context_service.py` — a dependency `services/intent_service.py` already had before this phase (it imported `authority_context_service` directly). This phase relocates the import target, it does not add a new edge between disciplines.

## Test additions

`server/tests/unit/test_runtime_truth_service.py` (new): two tests covering `ResolvedFacts`' shape (construction/field access) and its immutability. `resolve()` itself is not given a new unit test, deliberately: it is DB-dependent, and this codebase has no DB-backed unit-test fixture anywhere (confirmed by inspection before writing this file) — `resolve()` inherits the same "verified by the full integration suite, not mocked" status its two constituent calls already had, rather than this phase inventing a new testing pattern to manufacture coverage.

## Documentation-only changes

`SPECIFICATION/00_INDEX.md` updated to register Parts 28–34 (this document included). No other file's prose was altered by this phase.

## Total behavioral footprint of Phase 3

Zero observable runtime behavior changed. Every Decision this platform produces after Phase 3 is bit-for-bit identical, for identical input, to the Decision it would have produced before Phase 3 — confirmed by the full test suite's unchanged pass/fail outcomes across all 180 pre-existing tests.
