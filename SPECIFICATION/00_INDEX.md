# PayReality Platform — Architecture Specification

**Status:** canonical. **Supersedes:** the 63 top-level `.md` files in the repo root wherever they conflict with this document (see "Relationship to existing documents" below). **Audience:** the founder, or any engineer who needs to understand the platform well enough to redesign it from scratch without reading the source first.

This is not a README and not a pitch deck. It is an internal architecture handbook: for every subsystem, it explains what exists, why it exists, who calls it, whether it is active/deprecated/partial/dead, and what it would take to rebuild it. Where the codebase and an existing doc disagree, this specification follows the codebase — verified by reading the actual files, in most cases the same files this session already modified, migrated, and live-tested end-to-end.

## How this specification is organized

50 numbered parts plus this index and a glossary, one file each, in [SPECIFICATION/](.):

| # | File | Covers |
|---|------|--------|
| 1 | [01_PRODUCT_OVERVIEW.md](01_PRODUCT_OVERVIEW.md) | What PayReality is, who it's for, the core pitch |
| 2 | [02_SYSTEM_ARCHITECTURE.md](02_SYSTEM_ARCHITECTURE.md) | The whole system, one diagram at a time |
| 3 | [03_FRONTEND.md](03_FRONTEND.md) | React/Vite app: routing, pages, components, state |
| 4 | [04_BACKEND.md](04_BACKEND.md) | FastAPI app: structure, layering, every module |
| 5 | [05_DATABASE.md](05_DATABASE.md) | All 33 tables, relationships, migrations |
| 6 | [06_APIS.md](06_APIS.md) | All ~90 endpoints, request/response shapes |
| 7 | [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) | Compiler V2, Rego generation, OPA |
| 8 | [08_RUNTIME_AUTHORITY.md](08_RUNTIME_AUTHORITY.md) | Authority Model + Runtime Authority Context (Phases 1–2) |
| 9 | [09_AI_AUTHORITY_BUILDER.md](09_AI_AUTHORITY_BUILDER.md) | Document → extracted authority candidates |
| 10 | [10_AI_POLICY_BUILDER.md](10_AI_POLICY_BUILDER.md) | Document → draft Runtime Policy |
| 11 | [11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md) | Agents, Certificates, lifecycle, SDK |
| 12 | [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) | Intent → Decision, evaluation order |
| 13 | [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md) | Signing, chaining, key rotation, verification |
| 14 | [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md) | AuthN/AuthZ, RBAC, crypto, threat model |
| 15 | [15_USER_JOURNEYS.md](15_USER_JOURNEYS.md) | End-to-end walkthroughs by role |
| 16 | [16_CURRENT_LIMITATIONS.md](16_CURRENT_LIMITATIONS.md) | Known gaps, honestly stated |
| 17 | [17_LEGACY_COMPONENTS.md](17_LEGACY_COMPONENTS.md) | What's dead, what's dormant, what's active |
| 18 | [18_DEPENDENCY_GRAPH.md](18_DEPENDENCY_GRAPH.md) | Module/package/service dependency maps |
| 19 | [19_REPOSITORY_WALKTHROUGH.md](19_REPOSITORY_WALKTHROUGH.md) | Every folder, file-by-file |
| 20 | [20_ARCHITECTURAL_ASSESSMENT.md](20_ARCHITECTURAL_ASSESSMENT.md) | Candid critique: what's good, what's fragile |
| 21 | [21_FOUNDER_LEARNING_GUIDE.md](21_FOUNDER_LEARNING_GUIDE.md) | Reading order + concepts for a non-engineer founder |
| 22 | [22_BUILD_FROM_SCRATCH.md](22_BUILD_FROM_SCRATCH.md) | If you had to rebuild this platform in 90 days |
| 23 | [23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md) | Frozen baseline (commit `eb54f3e`) for the Runtime Governance Architecture migration; maps every subsystem above to its owning discipline |
| 24 | [24_PHASE_1_RUNTIME_CORE_PLAN.md](24_PHASE_1_RUNTIME_CORE_PLAN.md) | Phase 1 plan, risk assessment, conformance checklist, and roadmap |
| 25 | [25_PHASE_1_CONFORMANCE_REPORT.md](25_PHASE_1_CONFORMANCE_REPORT.md) | Phase 1 Architecture Conformance Report — gate passed |
| 26 | [26_PHASE_2_DEPENDENCY_DECLARATION.md](26_PHASE_2_DEPENDENCY_DECLARATION.md) | Phase 2: declared ownership, allowed/forbidden dependency edges, automated conformance checks |
| 27 | [27_PHASE_2_CONFORMANCE_REPORT.md](27_PHASE_2_CONFORMANCE_REPORT.md) | Phase 2 Architecture Conformance Report — gate passed |
| 28 | [28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md) | Phase 3: catalog of every fact this platform resolves, with owner/version/authority basis |
| 29 | [29_PHASE_3_RESOLVER_INTELLIGENCE_SPEC.md](29_PHASE_3_RESOLVER_INTELLIGENCE_SPEC.md) | Phase 3: resolution source/method/authority/freshness/confidence per fact |
| 30 | [30_PHASE_3_RUNTIME_TRUTH_SPEC.md](30_PHASE_3_RUNTIME_TRUTH_SPEC.md) | Phase 3: the resolution/evaluation boundary, formalized as `runtime_truth_service.py` |
| 31 | [31_PHASE_3_ARCHITECTURE_EXTRACTION_REPORT.md](31_PHASE_3_ARCHITECTURE_EXTRACTION_REPORT.md) | Phase 3: already-existed vs. formalized vs. renamed vs. invented, per concept |
| 32 | [32_PHASE_3_GAP_ANALYSIS.md](32_PHASE_3_GAP_ANALYSIS.md) | Phase 3: what doesn't exist, what should stay absent, what should become an extension point |
| 33 | [33_PHASE_3_MIGRATION_REPORT.md](33_PHASE_3_MIGRATION_REPORT.md) | Phase 3: every code change, with before/after and behavioral-impact verification |
| 34 | [34_PHASE_3_CONFORMANCE_REPORT.md](34_PHASE_3_CONFORMANCE_REPORT.md) | Phase 3 Architecture Conformance Report — gate passed |
| 35 | [35_PHASE_4_INTENT_INTELLIGENCE_SPEC.md](35_PHASE_4_INTENT_INTELLIGENCE_SPEC.md) | Phase 4: Intent's runtime-required vs. implementation-only fields; Blueprint named |
| 36 | [36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md](36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md) | Phase 4: context classified by lifecycle/persistence/replayability/what it affects |
| 37 | [37_PHASE_4_ENTERPRISE_DECISION_PIPELINE_SPEC.md](37_PHASE_4_ENTERPRISE_DECISION_PIPELINE_SPEC.md) | Phase 4: the ten-stage pipeline, inputs/outputs/owner/disciplines/artefacts/replay/failure mode per stage |
| 38 | [38_PHASE_4_PIPELINE_SEQUENCE_DIAGRAM.md](38_PHASE_4_PIPELINE_SEQUENCE_DIAGRAM.md) | Phase 4: the pipeline as actually implemented, as sequence diagrams |
| 39 | [39_PHASE_4_ARCHITECTURE_EXTRACTION_REPORT.md](39_PHASE_4_ARCHITECTURE_EXTRACTION_REPORT.md) | Phase 4: already-existed vs. formalized vs. renamed vs. invented, per concept |
| 40 | [40_PHASE_4_GAP_ANALYSIS.md](40_PHASE_4_GAP_ANALYSIS.md) | Phase 4: what remains implicit, what should stay implementation detail, what belongs in Phase 5 |
| 41 | [41_PHASE_4_MIGRATION_REPORT.md](41_PHASE_4_MIGRATION_REPORT.md) | Phase 4: every code/documentation change, with before/after and behavioral-impact verification |
| 42 | [42_PHASE_4_CONFORMANCE_REPORT.md](42_PHASE_4_CONFORMANCE_REPORT.md) | Phase 4 Architecture Conformance Report — gate passed |
| 43 | [43_PHASE_5_INTEGRITY_INTELLIGENCE_SPEC.md](43_PHASE_5_INTEGRITY_INTELLIGENCE_SPEC.md) | Phase 5: what Integrity Intelligence actually is in this implementation — a small check set plus a periodic audit practice, not a new subsystem |
| 44 | [44_PHASE_5_ARCHITECTURAL_DRIFT_REPORT.md](44_PHASE_5_ARCHITECTURAL_DRIFT_REPORT.md) | Phase 5: duplicated concepts, contradictory terminology, dead diagrams, duplicated ownership |
| 45 | [45_PHASE_5_BROKEN_PROMISE_REPORT.md](45_PHASE_5_BROKEN_PROMISE_REPORT.md) | Phase 5: the eleven named architectural promises, each classified with evidence; silent risks |
| 46 | [46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md](46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md) | Phase 5: every documentation-vs-implementation mismatch found, classified |
| 47 | [47_PHASE_5_NEED_ANALYSIS.md](47_PHASE_5_NEED_ANALYSIS.md) | Phase 5: does Integrity Intelligence need to exist? (Verdict: not as new infrastructure) |
| 48 | [48_PHASE_5_IMPLEMENTATION_REPORT.md](48_PHASE_5_IMPLEMENTATION_REPORT.md) | Phase 5: the three minimal changes made, each tied to a demonstrated problem |
| 49 | [49_PHASE_5_CONFORMANCE_REPORT.md](49_PHASE_5_CONFORMANCE_REPORT.md) | Phase 5 Architecture Conformance Report — gate passed, final phase |
| 50 | [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) | Trusted Integration Architecture (its own, unrelated Phase 1–4): Action Mapping, Trusted Connection, Runtime Connection, the Adapter-mediated runtime path, operation idempotency, and why Capability Authorization is currently suppressed on it |
| — | [GLOSSARY.md](GLOSSARY.md) | Every term of art, defined once |

## Relationship to existing documents

The repository root holds 63 pre-existing markdown documents (`ARCHITECTURE.md`, `PHASE_0.md` through `PHASE_6_PLATFORM.md`, `RBAC.md`, `AGENT_LIFECYCLE.md`, `SDK_*.md`, the `POLICY_STUDIO_*.md` family, and more). Those documents are **not deleted or rewritten** — they remain in place as design-time records of intent, and several (`SDK_REFERENCE.md`, `POLICY_LANGUAGE_SPEC.md`, `OPERATIONS_RUNBOOK.md`) contain reference detail (full SDK method signatures, full Rego condition-operator tables) this specification deliberately does not reproduce line-for-line.

What this specification does differently:

- **It is grounded in current, verified state, not design-time intent.** The clearest example: `PHASE_0.md`, `PHASE_1_AUTHORITY_MODEL.md`, and `PHASE_5_EVIDENCE.md` each still say `Status: proposed` in their own headers, but all three are implemented, migrated, deployed, and live-verified as of this specification's writing (see [16_CURRENT_LIMITATIONS.md](16_CURRENT_LIMITATIONS.md) and [17_LEGACY_COMPONENTS.md](17_LEGACY_COMPONENTS.md) for the full reconciliation). Where a phase doc's stated status conflicts with the code, this specification states the code's actual status and says so explicitly.
- **It cross-references instead of duplicating.** Each part below cites which of the 63 documents it draws from and supersedes for that topic, so nothing is orphaned and nothing needs to be read twice to get the full picture.
- **It is organized by subsystem end-to-end**, not by project phase. The 63 documents are organized chronologically (by when they were written — `PHASE_0` through `PHASE_6`, plus ad hoc audits). This specification is organized by what a reader needs to understand a subsystem (Runtime Policy Engine, Evidence Engine, Agent Architecture) regardless of which phase introduced which piece of it.
- **Depth is calibrated per section**, deliberately, per the founder's own instruction: exhaustively enumerable material (all ~90 endpoints, all 33 tables, all ~75 backend files, all 20 frontend pages) is presented as structured reference tables, not restated in full prose per item; narrative/analytical material (why a decision was made, what a subsystem is for, what's fragile about it) is written in full prose. This keeps the specification usable as a genuine reference rather than a padded narrative.

## What "active / deprecated / partial / dead" mean in this specification

These four words recur throughout, always in this sense:

| Label | Meaning |
|---|---|
| **Active** | Currently the only or primary code path; used by real production traffic; the thing to build on top of |
| **Deprecated** | Still callable, but superseded — new work should not depend on it, and it is a removal candidate |
| **Partial** | Implemented as a schema/scaffold/API surface but not yet wired into the primary decision path, or not yet exposed in the frontend |
| **Dead** | Present in the codebase (or intentionally left as an empty table) but has zero remaining callers/writers; kept only because deleting it was assessed as unnecessary risk, not because it does anything |

## A note on scale and verification

This specification was produced by directly reading the repository — models, services, routers, migrations, the compiled Rego a real policy produces, and the actual Alembic migration history — rather than by re-describing the existing 63 documents' claims. Several factual corrections it makes to those documents' claims (e.g., the `rego_generator.py` field-routing bug fixed under Phase 2, described in [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md)) were only caught because this session insisted on live end-to-end verification rather than trusting an earlier design doc's own assertion. Treat any specific claim in this specification the same way: as accurate as of this writing, and re-verifiable against the same source it was derived from.
