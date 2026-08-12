# Authority Intelligence Program — Phase 4: Runtime Policy Simulator — Summary

**Date:** 12 August 2026
**Commit:** `ba431af`
**Principle:** 100% deterministic. No LLM anywhere in this phase. Reuse the existing Runtime Authority Engine and OPA evaluation. Never modify production Runtime Policies. Never persist simulated decisions.

---

## What it is

A dry run of Runtime Authority: given a hypothetical Intent and a Runtime Policy version, execute exactly the OPA evaluation production would perform — including every *other* currently-active policy, so the simulation reflects what deploying this version would actually change, not this policy in a vacuum — and return the decision, a rule-by-rule explanation, an authority trace, and an unsigned evidence preview. Nothing is written anywhere except an optional saved Test Scenario's own input definition.

**Route**: `/governance/:policyKey/simulate`, linked from the existing Policy Workspace page.

## How it's built — almost entirely reused, not new

This was the central design question, and the answer changed the shape of the work significantly: this codebase already had most of what "reuse the existing Runtime Authority Engine, reuse OPA evaluation" requires.

| Piece | Status |
|---|---|
| `runtime_policy_service._row_to_policy` / `_other_active_policies` | **Reused unchanged.** Already composes "candidate policy + everything else active" — exactly the set a real deployment would put into production. |
| `domain/compiler_v2/dry_run.py`'s isolated-package mechanism | **Reused unchanged.** Already rewrites the compiled Rego's package to a unique throwaway name, loads it, queries it, deletes it — verified against real OPA before this phase existed. |
| `domain/compiler_v2/compiler_v2.compile_bundle` | **Reused unchanged.** Same Rego generator, same validation, same conflict detection real deployments use. |
| `domain/evidence/signing.payload_hash` | **Reused unchanged** for the Evidence Preview's hash — deliberately **not** used for signing (see Security below). |
| `domain/policy_simulation/batch_evaluator.py` | **New.** Extends the exact same isolation pattern to "load once, query many," since `dry_run()` is one-shot by design and re-uploading identical Rego per row for a 5,000-row batch would be pure waste. |
| `domain/policy_simulation/explainer.py` | **New.** A deterministic, Python-side re-statement of each policy's Scope/Condition evaluation, mirroring `rego_generator.py`'s exact field-resolution and operator semantics so it can never disagree with what the compiled Rego actually did. |
| `domain/policy_simulation/authority_trace.py` | **New.** Presentation-only synthesis of already-known facts into the "AI Agent → Principal → Policy vN → outcome" narrative. |
| `SimulationScenario` table | **New.** Persists only a saved question (input + expected outcome) — never a saved answer. |

## A necessary, honest deviation from the literal spec

**"Reuse the existing Runtime Authority Engine"** — `domain/decision/engine.py`'s `evaluate()` — was **not** called directly. Its `PolicyStore.get_active()` abstraction is built for "the one production-active Policy row," which a simulation's compiled-but-undeployed bundle isn't. The **already-existing** dry-run tool (`routers/runtime_policies.py`'s `/dry-run` endpoint) hits this identical tension and resolves it the same way: it reads OPA's raw `allow`/`deny`/`requires_review` booleans directly and maps them to ALLOW/DENY/HUMAN_REVIEW inline, bypassing `engine.evaluate()` for the same architectural reason. This phase's `_decision_from_flags()` mirrors that exact existing mapping, in the same order, rather than inventing a second one. What *is* reused with zero deviation is OPA itself — the actual evaluator — and the compiled Rego it evaluates.

## Verified against real OPA, not just read

A real, ephemeral local OPA 1.7.1 server (this repo's own existing `tests/integration/conftest.py` fixture) backs 5 integration tests:

- The exact `POLICY_SIMULATOR.md` worked example (R850,000 against a R500,000 limit, with a CFO Override rule active) correctly escalates, not allows or denies.
- An under-limit amount correctly allows.
- The Python-side explainer's `matched` flag for each rule agrees with OPA's own `evaluated_mandates` — not a second, independent judgment.
- The new batch load-once/query-many mechanism produces correct, independent results across four different inputs against one loaded bundle.
- Cleanup is verified directly: after the batch context manager exits, querying its throwaway path returns nothing.

12 further pure, DB-free unit tests cover the explainer's condition/operator semantics in isolation (LTE/GTE/EQ/NEQ/LT/GT/IN/CONTAINS/EXISTS, the `context.`-prefix routing, missing-field handling) and the authority trace builder.

**249/249 backend tests passing (17 new), zero regressions.** No existing router, service, compiler, or engine file was modified — every new capability was added by importing from existing modules, never editing them.

**Frontend**: production build verified clean (no TypeScript checker exists in this project to type-check against; no browser testing was performed this session — the same honest limitation noted in Phase 3).

## Security review (self-directed, matching this program's own established practice)

- **Never modifies production Runtime Policies**: confirmed by code — nothing in this phase calls `create_policy`/`edit_policy`/`deploy_policy`/`compile_policy` (the mutating functions); only read-only lookups plus the pure `compile_bundle()` (an in-memory computation, not a write) and OPA writes scoped exclusively to throwaway `payreality.dryrun.*`/`payreality.batch.*` packages, never `payreality.authorization`.
- **Never persists a simulated decision**: confirmed — `SimulationResult`/`BatchSimulationResult`/`ScenarioRunResult` are plain, never-saved dataclasses; the only database write anywhere in this phase is `SimulationScenario`'s own input/expected-outcome definition.
- **Evidence Preview is deliberately never signed.** Reusing the real Evidence signing key for a simulated, never-real decision would produce a signature that verifies successfully against the real production public key — indistinguishable from genuine Evidence to anyone checking it later. The preview carries a hash only, and an explicit `preview: true` marker, so it can never be mistaken for or replayed as a real Decision Receipt.
- **Permission**: every endpoint requires `Permission.RUNTIME_POLICY_VIEW` — the same permission viewing a policy already requires, correctly weaker than the `EDIT`/`PUBLISH` permissions that would be needed to actually change something, since nothing here changes anything.

## Honest gaps and scope notes

1. **Always simulates against the current latest version of the selected policy_key**, matching the existing dry-run tool's own behavior exactly. Selecting an arbitrary *older* historical version to simulate against specifically is not supported in this phase.
2. **Batch Simulation's per-row context mapping is flat**: any CSV column beyond `principal`/`action`/`resource`/`amount`/`currency` is passed through as a top-level Runtime Authority Context key, not a nested structure (e.g. a `department` column becomes `context.department`, not `context.authority.department`). A policy whose conditions expect a specific nested shape needs its CSV columns to match that shape's flattened keys.
3. **No live staging round-trip** was performed this session (unlike Phase 2's live Azure verification) — everything above is unit/integration-level against a local, ephemeral OPA instance, not the deployed Azure environment.
4. **No UI screenshots** — no browser/screenshot tool is available in this environment.

## Recommendation

The core mechanism is real, reused correctly, and proven against live OPA — this is not a mocked-up demo of what a simulator would do. Before relying on it for a genuine pre-deployment sign-off process, run it once against staging with a real, multi-policy bundle and a real historical-action CSV to confirm the batch path's performance and the context-flattening behavior (#2 above) match what a reviewer actually expects for existing policies' condition fields.

Per the Completion Gate implicit in this program's pattern: stopping here, awaiting review before any further phase.
