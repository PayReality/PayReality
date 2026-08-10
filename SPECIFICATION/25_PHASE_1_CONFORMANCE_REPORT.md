# Part 25 — Phase 1 (Runtime Core) Architecture Conformance Report

**Status:** Phase 1 implementation complete, tested, uncommitted pending this report. **Baseline:** [23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md). **Plan:** [24_PHASE_1_RUNTIME_CORE_PLAN.md](24_PHASE_1_RUNTIME_CORE_PLAN.md).

## Ownership — has ownership become clearer?

Yes, in the specific, narrow way Phase 1 targeted. Decision Evidence's ownership of "which policy version, which authority version, which resolution source governed this decision" moved from *implicit and indirect* (reconstructable only via `Decision.policy_id` → a live join against the `policies` table) to *explicit and self-contained* (`policy_version`, `policy_bundle_hash`, `authority_version` recorded directly on the Evidence payload, redundant with but independent of the FK). No other discipline's ownership changed.

## Boundaries — did any discipline collapse into another?

No. Every new field was placed by checking which discipline's own boundary it belongs to before writing it:
- `authority_version` lives on `Decision`/`Evidence`, produced by `decision/engine.py` — Runtime Authority's own boundary, not borrowed from Policy Intelligence.
- `resolved_by`/`responsible_party` were deliberately scoped to only the one place an actual resolution step exists (`authority_context`) — extending them to the agent's self-asserted Intent fields would have manufactured a Resolver Intelligence distinction the current architecture doesn't have, collapsing an honest "this doesn't apply yet" into a fabricated one.
- `reviewer`/`review_outcome` were added only in `resolution_service.py`, never in `intent_service.py`'s main evaluation path — keeping "who evaluated" (Runtime Authority, at decision time) and "who reviewed" (a human, after the fact, only for `HUMAN_REVIEW`) from blurring into each other despite both currently being recorded through the same `append_evidence` function.

## Dependencies — were any forbidden dependencies introduced?

No new dependency of any kind was introduced. Every change either added a field to an existing dataclass/payload or read a column (`Policy.bundle_hash`) that already existed and was already reachable from the same call site. `domain/decision/engine.py` remains DB-free (verified: no new import of `db.models` or any SQLAlchemy construct). The `routers → services → domain` layering (§18.3 of this specification) is unchanged.

## Runtime — does runtime still faithfully follow the architecture?

Yes, more faithfully than before on the one dimension Phase 1 targeted (explicit version pinning), unchanged on every other dimension. The evaluation sequence itself — agent-status gate → context resolution → OPA query → Decision → Evidence — was not reordered, split, or merged.

## Documentation — does documentation still describe reality?

Improved on the one item in scope: `ARCHITECTURE.md` now points to the current specification instead of silently remaining stale. Not addressed in this phase, by design (deferred to Phase 5 per the baseline's §23.5/§23.6): `MASTER_ROADMAP.md` and `VERSION_3_ROADMAP.md` remain unreconciled with each other.

## Replay — does replay remain deterministic?

Strengthened, not merely preserved. Before Phase 1, replaying a decision's governing policy version required the `policies` table row to still exist. After Phase 1, the Evidence record is self-sufficient for this specific question — it no longer depends on a live database join to answer "which policy version, which bundle, which evaluation engine version governed this decision." This is a direct, verifiable improvement in replay robustness, not just a preservation of the status quo.

## Evidence — has evidence become richer?

Yes, by five new optional fields (`authority_version`, `policy_version`, `policy_bundle_hash`, `resolved_by`/`responsible_party`, `reviewer`/`review_outcome`), all additive, `payload_version` unchanged at `2`. No existing field was removed, renamed, or had its meaning changed.

## Risk — did this phase reduce architectural risk?

Yes, modestly and specifically: the risk that a future export or replay of Evidence, performed without live database access, could not determine which policy version applied is now closed. No new risk was introduced — every change is additive Python/JSONB, no migration, confirmed by 171 passing tests (164 unit, 7 real-OPA integration, including the one integration test that exercises this exact code path end to end: `test_unmodified_decision_engine_consumes_compiler_v2_output`).

## Outstanding issues — everything still not conforming

Carried forward from the baseline, unaffected by Phase 1, in the order the migration roadmap will address them:

- **Dependency Intelligence not yet declared** (Phase 2): the single-writer guarantee on the `policies` table is real and correct today, but still enforced by one defensive exception class (`UnexpectedActiveWriterError`) rather than a declared, checked artifact.
- **Canonical Fact Intelligence, Resolver Intelligence, Runtime Truth not yet separated** (Phase 3): `FinancialVocabulary` remains a private compiler vocabulary; no Resolver declaration model exists; resolution and evaluation remain one code path in `decision/engine.py`.
- **Intent Intelligence's Blueprint not yet derived** (Phase 4): `Intent`'s required fields remain fixed schema columns, not policy-derived.
- **Integrity Intelligence not yet implemented** (Phase 5): the `MASTER_ROADMAP.md`/`VERSION_3_ROADMAP.md` drift named in the baseline remains uncorrected, as does the compiler's field-vocabulary validation gap (§16.1 of this specification) — neither is a regression from this phase, both predate it.
- **Six-role provenance remains genuinely partial by architecture, not by oversight**: "who approved" (a required input to a decision) has no real instance in this codebase today and was correctly not fabricated. This is expected to remain true until a policy actually requires an approval-as-input, not a gap Phase 1 could or should have closed artificially.

**Gate status: passed.** Phase 2 may proceed once this report and the accompanying commit are reviewed.
