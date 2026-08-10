# Part 48 — Phase 5 Implementation Report

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md), frozen at tag `runtime-governance-phase-4`. Per [47_PHASE_5_NEED_ANALYSIS.md](47_PHASE_5_NEED_ANALYSIS.md)'s verdict, no framework, engine, or platform was built. Three changes were made, each tied to one specific, demonstrated problem from [45_PHASE_5_BROKEN_PROMISE_REPORT.md](45_PHASE_5_BROKEN_PROMISE_REPORT.md) or [46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md](46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md).

## Change 1: Policy Determinism — ordered queries

**File:** `server/app/services/runtime_policy_service.py`.

**Problem demonstrated:** `reconcile_opa_with_active_policies` and `_other_active_policies` both selected "every currently-active `RuntimePolicy`" with no `ORDER BY`. SQL does not guarantee row order without one; the identical active-policy set could return in a different physical order across two calls, and `build_bundle` serializes policies in list order, so `bundle_hash` — the value `deploy_policy`'s own staleness check compares against — could differ for zero actual policy change. Existing determinism tests (`test_bundle_builder.py`) held their input list literally fixed and could not have caught this.

**Fix:** both queries now end with `.order_by(RuntimePolicyRecord.policy_key)`.

**Behavioral change:** none to any currently-passing test or any Decision this platform produces — the fix only removes ordering *ambiguity* that was already latent, not currently observed to differ. `compile_bundle`'s output for any single, already-tested input list is byte-identical before and after.

**Tests added:** `server/tests/unit/test_policy_compilation_ordering.py` — two tests, each using a minimal recording fake `Session` (no real database, consistent with this codebase's established no-DB-fixture practice) to assert `ORDER BY` is present in the compiled SQL statement for both call sites.

## Change 2: Runtime Truth boundary — completing the non-dependency pair

**File:** `server/tests/unit/test_runtime_truth_boundary.py` (new).

**Problem demonstrated:** Phase 2 tested that `decision_engine.py` cannot import Runtime Truth's implementation. Nothing tested the reverse — whether `runtime_truth_service.py` could grow a dependency back onto `domain.decision`. True by inspection before this phase (confirmed: its only imports are `dataclasses`, `sqlalchemy`, `app.db.models`, `app.services.authority_context_service`); not continuously verified.

**Fix:** one new AST-based test, `test_runtime_truth_service_never_imports_the_decision_engine`, using the same technique as Phase 2's existing checks. Placed in a new file rather than added to Phase 2's `test_architectural_boundaries.py`, so this addition is never mistaken for a modification of a previous phase's own deliverable.

**Behavioral change:** none — a test-only addition; no production code touched.

## Change 3: `SECURITY.md` correction

**File:** `SECURITY.md` (root-level, pre-existing, never previously touched by this migration).

**Problem demonstrated:** the "Rego injection" bullet named a deleted file (`domain/compiler/compiler.py`) and a retired flow (`activate_policy`, now HTTP 410) as the live Rego-generation path — an active security-posture document misdirecting a reviewer toward the wrong code. See [46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md](46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md) finding 1 for why this was judged correction-worthy while the broader `MASTER_ROADMAP.md`/`VERSION_3_ROADMAP.md`/`README.md` drift was not: this document claims to describe current state (not a self-labeled proposal), the error is safety-relevant, and the fix is one bullet, not a rewrite.

**Fix:** the bullet now names the live path (`domain/compiler_v2/compiler_v2.py` -> `bundle_builder.py`, deployed via `runtime_policy_service.deploy_policy`, gated by the `RUNTIME_POLICY_PUBLISH` RBAC permission) and appends a short, explicit correction note citing this phase, following the same minimal-pointer precedent already established for `ARCHITECTURE.md` and `12_DECISION_ENGINE.md`.

**Behavioral change:** none — documentation only.

## What was deliberately not built

Per [47_PHASE_5_NEED_ANALYSIS.md](47_PHASE_5_NEED_ANALYSIS.md): no documentation-staleness detector, no semantic-drift scanner, no specification-consistency checker, no general dependency-cycle detector beyond the three specific edges now tested, no correction to `MASTER_ROADMAP.md`, `VERSION_3_ROADMAP.md`, or `README.md`. Each was considered and rejected with a stated reason, not overlooked.

## Test suite impact

Before Phase 5: 184 tests passing (Phase 4's count). After: **187 passing** — 184 unchanged in outcome, plus 2 (`test_policy_compilation_ordering.py`) plus 1 (`test_runtime_truth_boundary.py`). Zero tests removed, zero tests modified, zero pre-existing test's outcome changed.
