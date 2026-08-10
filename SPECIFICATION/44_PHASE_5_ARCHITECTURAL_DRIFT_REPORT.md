# Part 44 — Phase 5 Architectural Drift Report

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md). **Companion:** [46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md](46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md) (per-document classification); this report groups the same evidence by drift *pattern* rather than by document, per Phase 5's Objective 2.

## Duplicated concepts / multiple definitions of the same thing

- **The `action` fact, historically** — `scope_vocabulary.KNOWN_SCOPES` and `compiler_v2.FinancialVocabulary.known_actions` were two independent, hand-synchronized literals of the same three strings. **Closed** in Phase 3 ([28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md)) — cited here as this repository's clearest exemplar of the pattern, not as an open item.
- **Two independent, un-cross-referenced roadmaps** — `MASTER_ROADMAP.md` and `VERSION_3_ROADMAP.md` both claim ownership of "what this platform builds next," covering overlapping ground (evidence chaining, human login, multi-tenancy all appear in both), neither referencing the other. Already named in [23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md) §23.5; this pass confirms the overlap is real, not superficial (see [46](46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md) findings 2–3).
- **Two incompatible "Phase N" numbering schemes** — `MASTER_ROADMAP.md`'s own phase numbers (Phase 0 = stabilisation, ..., Phase 4 = Authority Graph traversal, Phase 5 = Evidence chaining) do not match the numbers this migration program uses (`SPECIFICATION/23`-`42`'s own Phase 1 = Runtime Core, ..., Phase 4 = Intent/Context/Pipeline). A code comment in `db/models.py` (on `AuthorityRelationship.from_principal_id`) cites "Phase 1 (PHASE_1_AUTHORITY_MODEL.md)" for a feature `MASTER_ROADMAP.md` itself calls "Phase 4." Two numbering tracks share the digits 0–5 while meaning entirely different scopes — a genuine source of confusion for anyone cross-referencing "Phase 1" between a root roadmap and this migration's own baseline.
- **"Mandate"/"Authority" terminology** — [GLOSSARY.md](GLOSSARY.md) explicitly documents two historical representations and names the legacy one as retired; `README.md` and `PRODUCT.md` nonetheless define the product's central primitive using the retired vocabulary at their most visible, first-read positioning language. Detailed in [46](46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md) finding 4.

## Abandoned architecture / obsolete specifications

- **`domain/compiler/compiler.py`** (the legacy Authority/Mandate compiler) — fully deleted from the filesystem; four correctly-referencing docs (`DOMAIN_ABSTRACTION.md`, `DOMAIN_AGNOSTIC_ARCHITECTURE.md`, `DOMAIN_REFACTOR_PLAN.md`, `MIGRATION_PLAN_V4.md`) already frame it as a retirement candidate, consistent with their own self-labeled "design/plan" status. Two documents (`SECURITY.md`, fixed this phase; `RUNTIME_AUTHORITY_TRANSFORMATION.md`/`PHASE_0.md`, historical artifacts, not fixed) still describe it as live — see [46](46_PHASE_5_REPOSITORY_INTEGRITY_REPORT.md) findings 1 and 5.
- **The "Policy Bundle" renaming proposal** (`AUTHORING_ARCHITECTURE.md`) — an aspirational rename of `Policy` to "Policy Bundle" that was never adopted anywhere in the actual schema, code, or any other document. A small, genuinely abandoned naming proposal, harmless (nothing depends on it, nothing contradicts it, it simply never happened) but worth naming so a future reader doesn't mistake `AUTHORING_ARCHITECTURE.md`'s vocabulary for the live one.
- **RTAL, the Runtime Authority DSL** (`PHASE_3_DSL.md`) — not abandoned, but genuinely never started: zero references anywhere in `server/app/**/*.py`. Distinct from "abandoned" (nothing was built and then dropped); recorded here because it's the one MASTER_ROADMAP phase claim this audit confirms is still accurately "proposed."

## Dead diagrams

- **`ARCHITECTURE.md`'s own pipeline diagram** (Onboarding -> Human review -> Compilation via the legacy compiler -> Activation) depicts a pipeline that no longer exists. Already flagged by the document's own corrective banner (added at this migration's Baseline phase) — a genuinely dead diagram, but one already under a "read the banner first" notice rather than an undisclosed trap.
- **`12_DECISION_ENGINE.md` §12.4's flowchart** — depicted Principal-name resolution and Runtime Authority Context assembly as two separate steps; Phase 3's Runtime Truth extraction made them one call. Already corrected with a pointer in Phase 4 ([41_PHASE_4_MIGRATION_REPORT.md](41_PHASE_4_MIGRATION_REPORT.md)).
- No other diagrams (Mermaid or ASCII) were found depicting a subsystem in a way that contradicts current code — every other diagram checked (in `PHASE_5_EVIDENCE.md`'s lineage sketch, `POLICY_STUDIO_WIREFRAMES.md`'s text-mode wireframes) describes something that either still matches reality or is self-labeled as a proposal never executed.

## Duplicated ownership

- **`MASTER_ROADMAP.md` vs. `VERSION_3_ROADMAP.md`** (above) — two documents, no shared owner declaration, overlapping scope.
- **`GITHUB_PROJECT_STRUCTURE.md` and `IMPLEMENTATION_BACKLOG.md`** both derive their content from `MASTER_ROADMAP.md` as if it were the single execution-tracking source of truth — a second layer of the same duplication, inheriting `MASTER_ROADMAP.md`'s own staleness one level further downstream without adding a new independent error of their own.

## Contradictory terminology baked into the schema itself (not just documentation)

- **`Decision.evaluated_mandates`** — per its own code comment (`db/models.py`), "despite its name, this has never referenced the real `mandates` table"; it holds matched `RuntimePolicy` id strings. A second column, `evaluated_mandate_ids`, was added specifically to hold real `Mandate` row ids once one exists for a matched policy. This is genuine, self-documented, live schema-level terminology drift — not hidden (the comment says so plainly), but still a real trap for anyone reading the column name without the comment. **Classification: Not a problem in the sense of being concealed** (it is explicitly, honestly commented at the point of definition) **but a real, permanent source of confusion** for any future reader who queries the schema directly (e.g., in a raw SQL tool) without also reading the ORM model's comments.

## Legacy structures that look dead but are not (the inverse finding, worth stating explicitly)

- **The `policies` table** (the legacy `Policy` model, distinct from `RuntimePolicyRecord`) looks, on first inspection, like dead legacy cruft sitting next to four genuinely dead tables in the same file — but it is not: `runtime_policy_service.deploy_policy` writes a fresh row to it on every deploy, and `_DbPolicyStore` (in `intent_service.py`) is what the live Decision Engine actually queries for "is there an active policy." Already correctly documented in [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) §12.3, which explicitly warns against the wrong assumption. Recorded here as a drift-adjacent risk in the opposite direction from every other finding in this report: not "documentation claims something exists that doesn't," but "something looks dead that isn't," which a less careful audit could get backwards.

## What was not found

No dependency cycle was found anywhere in `server/app/` beyond the two edges Phase 2's boundary tests already guard against (confirmed by direct check: `domain/decision` has no import of `domain/compiler_v2` or `runtime_policy`, so Phase 3's new `compiler_v2 -> domain/decision` edge does not close a cycle). No second instance of the `KNOWN_SCOPES`/`FinancialVocabulary`-style duplicated-fact pattern was found anywhere else in the codebase.
