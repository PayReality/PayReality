# Part 26 — Phase 2: Dependency Intelligence Declaration

**Status:** implementation complete. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md), frozen at tag `runtime-governance-phase-1`. **Objective, as revised for this phase:** declare architectural ownership, declare allowed and forbidden dependency edges, add automated conformance checks where practical, change no runtime behavior beyond what's required to enforce a declared boundary.

This phase adds no new capability. Every dependency declared below already exists in the codebase, verified by direct reading (§18.3–18.6 of this specification) — this document is the first time it is stated as a checked architectural commitment rather than an implicit convention a future engineer would have to rediscover by reading the code.

## 26.1 Declared ownership

Restated from the baseline's §23.4 in Dependency Intelligence's own vocabulary — each subsystem is a **Discipline**, accountable for exactly the boundary named:

| Discipline | Owns | Does not own |
|---|---|---|
| Policy Intelligence | `domain/compiler_v2/*`, `services/runtime_policy_service.py`, `services/ai_policy_builder_service.py` | Whether a decision is ultimately allowed — that's Runtime Authority's act, never Policy Intelligence's |
| Runtime Authority | `domain/decision/engine.py` exclusively | Where a policy came from, how it was authored, what a resolved value means |
| Decision Evidence | `domain/evidence/signing.py`, `services/evidence_service.py`, the evidence-construction functions in `services/intent_service.py`, `services/resolution_service.py` | Whether a decision was correct — Evidence records, it never evaluates |
| Context (informal; no dedicated discipline module yet, per baseline §23.4/Phase 3 scope) | `services/authority_context_service.py` | Resolving external facts — this service enriches from internal data only |

## 26.2 Declared allowed dependency edges

Every edge below is already real, traced directly against the import graph (§18.3 of this specification), now stated as a permanent, intended relationship rather than an artifact of how the code happened to be written:

- `services/intent_service.py` → `domain/decision/engine.py` (orchestration depends on Runtime Authority to evaluate)
- `services/intent_service.py` → `services/authority_context_service.py` (orchestration depends on Context to enrich)
- `services/intent_service.py` → `domain/evidence/signing.py` (orchestration depends on Decision Evidence to sign)
- `services/resolution_service.py` → `services/intent_service.py`'s `append_evidence` (review resolution depends on Decision Evidence's own construction path, never duplicates it)
- `services/runtime_policy_service.py` → `domain/compiler_v2/*` (Policy Intelligence's service layer depends on its own compiler)
- `services/ai_policy_builder_service.py` → `domain/runtime_policy`, → `services/runtime_policy_service.py` (extraction depends on Policy Intelligence to promote a candidate into a real policy)

## 26.3 Declared non-dependency (the positive absence)

**`domain/decision/engine.py` — Runtime Authority — depends on nothing in this codebase besides the Python standard library.** Verified directly: its only imports are `dataclasses` and `typing`. It knows Policy Intelligence, Context, and Decision Evidence exist only through the `OpaClient`/`PolicyStore` Protocols its caller supplies — it cannot name, import, or reach any of their implementations. This is not an oversight to fix; it is the single cleanest piece of architectural discipline already present in this codebase, and this document exists partly to make sure it stays that way on purpose rather than by accident.

## 26.4 Declared forbidden dependency edges

Two kinds, per the canon's own distinction — a bare non-edge (nothing should ever connect these two, in either direction) and a cycle-forming reverse edge (a forward edge already exists legitimately; its reverse is what's forbidden).

**Bare non-edges:**

1. `domain/decision/engine.py` (Runtime Authority) → `app.db`, `app.services`, or `app.routers`, in any form. Runtime Authority must remain pure and testable without a database, exactly as it is today (§26.3). Any future import from these paths into this file is a violation, full stop, regardless of how small.
2. `domain/` in general → `app.db.models`, direct construction or query. Verified today: zero instances across the entire package. Declared here as a permanent constraint, not an accident of current convenience — the moment a domain module needs a database, that need belongs in a service, not in domain logic.

**Cycle-forming reverse edge:**

3. Any writer other than `services/runtime_policy_service.py::deploy_policy` setting a `Policy` row's `status` to `'active'`, or writing to the OPA `payreality.authorization` package. The forward edge (`deploy_policy` writes both) is legitimate and sole. A second writer recreates exactly the risk `PHASE_0.md`/§17 of this specification already retired once — this is not a new rule, it is the existing `UnexpectedActiveWriterError` guard (`runtime_policy_service.py`) restated as a declared, permanent architectural fact rather than an implicit assumption defended by one exception class.
4. `routers/policies.py`'s four legacy write endpoints (`upload_document`, `review_authority`, `compile_policy`, `activate_policy`) resuming any write behavior. Permanently retired (`410`), by design, per Phase 0. A regression here would silently reopen the exact risk item 3 already guards against from the other direction.

## 26.5 Automated conformance checks added this phase

New file: `server/tests/unit/test_architectural_boundaries.py`. Each declared rule above gets exactly one direct, static or behavioral test — no new third-party dependency introduced (consistent with this codebase's own deliberately shallow dependency set, §18.1), using only `ast` (standard library) for the import-boundary checks and the existing test fixtures for the behavioral ones:

| Rule (§26.4 item) | Test | Kind |
|---|---|---|
| 1 | `test_decision_engine_imports_nothing_from_db_services_or_routers` | Static (AST-parsed imports) |
| 2 | `test_domain_package_never_imports_db_models` | Static (AST-parsed imports, whole package walk) |
| 3 | `test_second_writer_to_active_policy_is_rejected` | Behavioral (exercises `UnexpectedActiveWriterError` directly — previously untested) |
| 4 | `test_legacy_policy_write_endpoints_remain_retired` | Behavioral (asserts all four endpoints still return `410` — previously untested) |

Items 3 and 4 were previously enforced in running code but had zero test coverage — confirmed by searching the existing test suite before writing these (`grep` for `UnexpectedActiveWriterError`, `410`, `_RETIRED_DETAIL` across `tests/`: no hits). This phase closes that coverage gap; it does not change the enforcement itself, which was already correct.

## 26.6 What this phase deliberately does not do

Per the revised objective's own instruction to avoid changing runtime behavior unless required to enforce a boundary: no production code path changes in this phase. `UnexpectedActiveWriterError` already existed and already worked; it is now tested, not rewritten. The `410` responses already existed; they are now tested, not rewritten. The only "new" runtime-adjacent artifact is the test suite itself, which never executes in production.
