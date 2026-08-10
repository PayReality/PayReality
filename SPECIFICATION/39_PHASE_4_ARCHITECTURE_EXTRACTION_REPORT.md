# Part 39 — Phase 4 Architecture Extraction Report

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md). **Method:** same as [31](31_PHASE_3_ARCHITECTURE_EXTRACTION_REPORT.md) — classify each concept this phase's disciplines touch as Already existed / Formalized / Renamed / Invented.

| Concept | Classification | Evidence |
|---|---|---|
| One universal, implicit Blueprint (same field set for every recognized action) | Already existed | `SubmitIntentRequest` has always been one flat schema; no per-action variance exists or ever existed in this codebase |
| "Blueprint" as a named architectural concept describing that fact | Formalized | Did not exist as a document before [35](35_PHASE_4_INTENT_INTELLIGENCE_SPEC.md); every claim in it cites pre-existing code |
| `counterparty`'s non-participation in evaluation | Already existed | Confirmed by search: zero references outside storage/display; `runtime_policy.py`'s own docstring already named `resource` as its "generic successor," unwired |
| Caller-supplied `context` being an open, Condition-addressable document | Already existed | `decision_engine.build_opa_input`, unchanged since original build |
| The distinction between caller-supplied and runtime-enriched context | Formalized | Both already existed as two separate code paths merged by one dict-spread expression; naming the distinction and its consequences (which one persists where, which one a Condition can reach) is new, the mechanism is not |
| `authority_context`'s persistence as a verbatim snapshot on Evidence | Already existed | Established in Phase 1 (`24_PHASE_1_RUNTIME_CORE_PLAN.md`), unmodified by this phase |
| `principal_name` as a value distinct from `principal_id`, with its own replay requirement | Formalized, then the one field added | `runtime_truth_service.resolve` already computed this string (Phase 3); it was never previously written anywhere except as an ephemeral argument to `decision_engine.evaluate()` |
| A cataloged, per-field classification of Intent's runtime-required vs. implementation-only fields | Formalized | Did not exist before [35](35_PHASE_4_INTENT_INTELLIGENCE_SPEC.md) |
| A cataloged, per-context-element classification (immutable/ephemeral/persisted/replayable/affects-what) | Formalized | Did not exist before [36](36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md) |
| The ten-stage pipeline sequence, end to end | Already existed | Every stage is a direct restatement of `routers/intents.py` + `services/intent_service.py` + `services/resolution_service.py`, unchanged in order or logic |
| The pipeline as one canonical, cross-referenced document with per-stage inputs/outputs/owner/disciplines/artefacts/replay/failure-mode | Formalized | Did not exist as one document before [37](37_PHASE_4_ENTERPRISE_DECISION_PIPELINE_SPEC.md); `12_DECISION_ENGINE.md` §12.4 covered part of the same ground at a coarser grain and is now cross-referenced, not duplicated |
| A sequence diagram of the pipeline as actually implemented | Formalized | [38](38_PHASE_4_PIPELINE_SEQUENCE_DIAGRAM.md) is new; every arrow names an existing function call |
| A per-action Blueprint schema / validation framework | **Not built** | Explicitly rejected — see [35](35_PHASE_4_INTENT_INTELLIGENCE_SPEC.md) "What this specification deliberately does not do"; no second action type exists yet to justify one |
| `counterparty` -> `Scope.resource` wiring | **Not built** | A real, pre-existing gap this phase names but does not close — see Gap Analysis [40](40_PHASE_4_GAP_ANALYSIS.md); closing it would be Runtime Policy Language / Compiler V2 scope, not Intent or Context Intelligence |
| Principal-row immutability enforcement (e.g. a DB trigger or removed write path) | **Not built** | Explicitly rejected — see [36](36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md); the actual replay risk is closed by pinning the resolved value onto Evidence, not by constraining Principal |
| A caller-supplied-context duplication onto Evidence | **Not built** | Explicitly rejected — `Intent.context` is already a sufficient, immutable, joinable replay artefact; duplicating it would add a second source of truth for no correctness gain |

## Summary

Sixteen rows: eleven **Already existed** or **Formalized**, one is the single genuine renamed-and-newly-persisted value (`principal_name`), four are explicit **Not built** entries. Zero rows are **Invented** in the sense of new runtime behavior without a prior basis. Consistent with Phase 3's result and with this phase's stated target.
