# Part 31 — Phase 3 Architecture Extraction Report

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md). **Method:** for every concept this phase's three disciplines touch, classify it as one of: **Already existed** (true today, unchanged), **Formalized** (true today, now named/documented for the first time), **Renamed** (existing thing, new label only), or **Invented** (did not exist before this phase). Per the Phase 3 directive, the expectation going in was that almost every row would read "Already existed" or "Formalized" — that expectation held.

| Concept | Classification | Evidence |
|---|---|---|
| `action` fact identity (the `KNOWN_SCOPES` enumeration) | Already existed | `scope_vocabulary.py`, present since before this phase, unchanged in content |
| `action` having exactly one authoritative definition | Formalized | Previously true only by convention (two literals happened to match); now true structurally (`FinancialVocabulary.known_actions` imports `KNOWN_SCOPES` rather than restating it) — see Migration Report [33](33_PHASE_3_MIGRATION_REPORT.md) |
| `amount`, `currency` as unvalidated, caller-supplied facts | Already existed | `schemas/intent.py`; no validation added or claimed |
| `principal` resolving by name, not foreign key, into `RuntimePolicy.scope.principal` | Already existed | Confirmed in `AUTHORING_ARCHITECTURE.md` and unchanged in `runtime_policy.py::Scope` |
| `risk_level` classification thresholds | Already existed | `authority_context_service.classify_risk`, unmodified by this phase |
| Enterprise-structure enrichment fields (organization/business_unit/department/team/role) | Already existed | Phase 1 Authority Model additions, unmodified |
| One-hop delegation resolution | Already existed | `_active_inbound_delegations`, unmodified |
| A cataloged, named list of every fact this platform resolves, with owner/version/authority stated per fact | Formalized | Did not exist as a document before [28](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md); every row in it cites pre-existing code |
| A cataloged, named list of every fact's resolution source/method/authority/freshness/confidence | Formalized | Did not exist as a document before [29](29_PHASE_3_RESOLVER_INTELLIGENCE_SPEC.md); every row in it cites pre-existing code |
| The resolution-before-evaluation control-flow boundary | Already existed | Confirmed structurally by the pre-existing, pre-Phase-3-passing test `test_decision_engine_imports_nothing_from_db_services_or_routers` ([27](27_PHASE_2_CONFORMANCE_REPORT.md)) |
| That boundary having its own name and single call site (`runtime_truth_service.resolve`) | Formalized | New module; logic moved verbatim, not rewritten — see [30](30_PHASE_3_RUNTIME_TRUTH_SPEC.md) |
| `ResolvedFacts` as a named, frozen return type | Renamed | Previously two unrelated local variables (`principal`, `authority_context`) inside `submit_intent`; now one dataclass. No new field exists that wasn't already a local variable |
| `FinancialVocabulary.known_actions` sourced from `KNOWN_SCOPES` instead of a hand-copied literal | Renamed (of a dependency, not a fact) | The fact's *value* is unchanged (same three strings); only which line of code is authoritative for it changed |
| A Resolver abstraction / interface / registry | **Not built** | Explicitly rejected — see [29](29_PHASE_3_RESOLVER_INTELLIGENCE_SPEC.md) "What this specification deliberately does not do." Recorded here because the phase directive asked this report to show its work on judgment calls, not just outcomes |
| A Fact Registry / Fact Version storage | **Not built** | Explicitly rejected — see [28](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md); every fact's Meaning Version is `1` and no infrastructure exists to store a second |
| Multi-hop delegation resolution | **Not built** | Already deferred by the pre-existing code's own docstring before this phase began; this phase does not change that scope |
| A currency vocabulary/enumeration | **Not built** | Confirmed absent by search; a real, honestly-stated gap, not a silent omission — carried into the Gap Analysis [32](32_PHASE_3_GAP_ANALYSIS.md) |

## Summary

Of the sixteen rows above, twelve are **Already existed** or **Formalized/Renamed** descriptions of pre-existing behavior; four are explicit **Not built** entries recording infrastructure this phase considered and declined to build. Zero rows are **Invented** in the sense of new runtime behavior with no prior basis. This matches the phase directive's stated expectation and its governing principle: extract before you create, name before you build, formalize before you refactor.
