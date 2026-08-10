# Part 43 — Phase 5: Integrity Intelligence Specification

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md). **Preceded by, and entirely dependent on:** [44](44_PHASE_5_ARCHITECTURAL_DRIFT_REPORT.md), [45](45_PHASE_5_BROKEN_PROMISE_REPORT.md), [46](46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md), [47_PHASE_5_NEED_ANALYSIS.md](47_PHASE_5_NEED_ANALYSIS.md) — this specification states a conclusion those four documents earn; it does not stand on its own.

## Purpose

Integrity Intelligence answers: **does this architecture's own description of itself stay true over time?** Every other discipline in this canon governs a Decision. Integrity Intelligence governs the canon's own claims about the ten disciplines that came before it — Canonical Fact Intelligence's catalog, Resolver Intelligence's sourcing, Runtime Truth's boundary, the Enterprise Decision Pipeline's stages, every promise Phases 1–4 pinned down as HELD.

## What Integrity Intelligence is, in this implementation

Per [47_PHASE_5_NEED_ANALYSIS.md](47_PHASE_5_NEED_ANALYSIS.md)'s evidence, Integrity Intelligence in this codebase is **not a module, service, or engine.** It is two things, both of which already exist:

**1. A small, distributed set of automated, continuously-running checks**, each tied to one specific, named promise:

| Check | Promise it guards | Since |
|---|---|---|
| `test_decision_engine_imports_nothing_from_db_services_or_routers` | Runtime Authority separation | Phase 2 |
| `test_domain_package_never_imports_app_db` | `domain/`'s database-freedom | Phase 2 |
| `test_runtime_truth_service_never_imports_the_decision_engine` | Runtime Truth separation | Phase 5 |
| `_is_unexpected_active_writer` + 3 tests | Single writer | Phase 2 |
| Four retired-endpoint tests | Legacy write paths stay retired | Phase 2 |
| `test_compiling_twice_is_byte_identical`, `test_bundle_hash_is_stable_across_different_compile_times` | Policy determinism (content, time axes) | pre-migration |
| `test_other_active_policies_query_is_ordered`, `test_reconcile_active_policies_query_is_ordered` | Policy determinism (ordering axis) | Phase 5 |

Every row is a real `pytest` test, run on every invocation of the suite, failing the build the moment its promise breaks. None of them is new infrastructure this phase built for its own sake — six rows predate Phase 5 entirely; this phase added exactly two, each tied to a specific, demonstrated gap ([45](45_PHASE_5_BROKEN_PROMISE_REPORT.md)).

**2. A periodic, human-or-agent-directed architectural reconciliation pass** — reading every architectural claim in the repository (root docs, `SPECIFICATION/`, code comments, diagrams) and comparing it directly against running code. This is not hypothetical: it is the exact activity every phase gate in this migration program has performed (verifying HEAD, re-running the full suite, writing a Conformance Report before proceeding), and it is what produced [44](44_PHASE_5_ARCHITECTURAL_DRIFT_REPORT.md)/[46](46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md)'s findings — a genuinely new pass, performed for the first time at this scope in this phase, but using no tool this repository didn't already have (careful reading, direct code inspection, `grep`).

## Why no third thing was built

[47_PHASE_5_NEED_ANALYSIS.md](47_PHASE_5_NEED_ANALYSIS.md) establishes this with evidence: every documentation-staleness and semantic-drift finding this audit produced required judgment a mechanical check cannot make (is a `Status: proposed` header intentional design-time record, or accidental drift?), and every finding was produced by one reading pass, not by inventing a parser or a scoring framework. Building a general "integrity engine" would not have found anything this phase's reading pass didn't already find, and would have permanently misclassified this repository's own deliberate policy (63 root docs kept as design-time record, never rewritten) as a defect.

## Architectural principles

1. **Integrity Intelligence does not create new facts, resolve new context, or evaluate new authority.** It only checks whether existing claims about all of that remain true.
2. **A promise worth naming is worth testing, at the smallest scope that actually catches its violation.** Every automated check in the table above is scoped to exactly one promise, using the cheapest technique that works (AST inspection for import boundaries, hash comparison for determinism) — never a general-purpose framework built ahead of a second concrete need.
3. **Not every drift is a defect.** A document self-labeled as a historical or proposed record is not "wrong" for describing a past or hypothetical state — [46](46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md)'s classification scheme (Documentation stale / Historical artifact / Not a problem, among others) exists specifically so Integrity Intelligence's judgment calls stay honest about this distinction rather than flattening everything into "broken."
4. **Correction is proportionate to consequence, not automatic.** `SECURITY.md`'s wrong claim was corrected directly because it was safety-relevant and narrow (one bullet); `MASTER_ROADMAP.md`'s broader drift was documented, not rewritten, because correcting it would mean abandoning this program's own established policy of superseding rather than editing the 63 root docs.

## Product boundary

Integrity Intelligence, as specified here, does not own: documentation authoring, roadmap maintenance, or terminology governance for the 63 pre-existing root documents (those remain [00_INDEX.md](00_INDEX.md)'s domain, by that document's own stated policy). It does not own general code review. It owns exactly the two things in the table and the reconciliation practice above — nothing broader was found justified.

## Future vision

If a specific, recurring, silently-dangerous pattern is found in a future phase — the same way Policy Determinism's ordering gap was found this phase — the correct response remains what this phase did: a small, targeted check tied to that one pattern, not an expansion of Integrity Intelligence into a framework. The eight promises from [45](45_PHASE_5_BROKEN_PROMISE_REPORT.md) that remain unautomated (append-only evidence, immutable decision, context persistence, evidence completeness, the general dependency-boundary promise, ownership violations beyond import edges, and the two documentation-facing categories) are not queued as "Integrity Intelligence's backlog" — per this document's own Principle 2, none of them should gain automated coverage until a future phase finds concrete evidence, the way this one did for determinism, that one of them has actually broken or is at genuine, demonstrated risk of breaking silently.
