# Part 41 — Phase 4 Migration Report

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md), frozen at tag `runtime-governance-phase-3`. This report itemizes every code and documentation change this phase made — one code change, one documentation pointer, both minimal.

## Change 1: `principal_name` added to the Decision Evidence payload

**File:** `server/app/services/intent_service.py`.

**Before:** `_build_evidence_payload`/`append_evidence` accepted `principal_id` (a foreign key) but no separate field for the resolved Principal *name* string — the exact value `decision_engine.evaluate()` received as `acting_for_principal_id` and OPA matched against every compiled `RuntimePolicy.scope.principal`.

**After:** both functions gained an additive `principal_name: str | None = None` parameter; `_build_evidence_payload` writes it into the payload dict only when not `None` (identical conditional-inclusion style already used for `principal_id`, `authority_context`, `authority_version`, etc.). `submit_intent`'s real-evaluation `append_evidence(...)` call now passes `principal_name=resolved.principal_name` — a value `runtime_truth_service.resolve()` already computed (Phase 3); no new resolution logic was written.

**Discipline:** Context Intelligence ([36](36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md)).

**Why:** every other value Runtime Authority evaluates against has been pinned explicitly onto its Decision/Evidence record since Phase 1, specifically so replay never depends on a live, mutable row still meaning what it meant at evaluation time. `principal_id` alone (a stable FK) does not satisfy that guarantee for the *name* actually matched — reconstructing it requires dereferencing the FK through the `principals` table's *current* state, and nothing in the schema guarantees `Principal.name` hasn't changed since (no immutability constraint exists; only the absence of an update endpoint today).

**Behavioral change:** None to any Decision outcome. This is a purely additive field on a record already written; no Decision is computed differently, no branch changed. Verified: `pytest tests/ -q` — 182 passed before this change (Phase 3's count), 184 passed after (the two additions are new tests for this exact field, described below).

**Scope not touched:** the two intent_service branches that never resolve a Principal at all (suspended agent, unrecognized action) continue to omit `principal_name` from their Evidence payload, exactly as they already omitted `principal_id`/`authority_context` — no new behavior was added to a code path this phase's own directive says should stay untouched unless a real gap requires it. `resolution_service.py`'s Stage-10 evidence call (human review resolution) was left unchanged for the same reason: it never carried `principal_id`/`authority_context` either, and adding `principal_name` there alone, asymmetrically, would misrepresent that record's actual scope (a "who reviewed" event, not a re-evaluation of authority).

## Change 2: documentation pointer in `12_DECISION_ENGINE.md`

**File:** `SPECIFICATION/12_DECISION_ENGINE.md`.

A four-line blockquote was added directly under the file's header, noting that §12.4's flowchart predates the Phase 3 Runtime Truth extraction (it still shows Principal-name resolution and Runtime Authority Context assembly as two boxes, now one call) and pointing to [37](37_PHASE_4_ENTERPRISE_DECISION_PIPELINE_SPEC.md)/[38](38_PHASE_4_PIPELINE_SEQUENCE_DIAGRAM.md) for the current sequence. No other line of `12_DECISION_ENGINE.md` was changed — its prose and fail-closed table (§12.5) remain accurate and are cited directly, not restated, by this phase's new documents. This follows the exact precedent set in the Baseline phase for `ARCHITECTURE.md` (a pointer added, the body left alone), not a new pattern.

## Test additions

`server/tests/unit/test_evidence_payload.py` (new): two tests, directly exercising the pure function `_build_evidence_payload` (no DB, no fixture) — `principal_name` present when supplied, absent when not, mirroring `principal_id`'s existing conditional-inclusion behavior.

## Total behavioral footprint of Phase 4

Zero observable Decision-outcome behavior changed. Every Decision this platform produces after Phase 4 resolves identically, for identical input, to before Phase 4 — the sole code change adds one additional, already-computed value to the Evidence record already being written for a Decision, without altering what that Decision is.
