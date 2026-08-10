# Part 46 — Phase 5 Repository Integrity Report

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md), frozen at tag `runtime-governance-phase-4`. **Method:** every architectural document in this repository (the 63 pre-existing root `.md` files, `README.md`, `SECURITY.md`, `SPECIFICATION/00`-`42`, code comments describing architecture, and the one diagram family found) compared directly against `server/app/` as it exists at this commit. This is Phase 5's Objective 1 (Architectural Integrity Audit) — no fix is proposed in this document except where already made and cross-referenced; classification only.

## Classification key

- **Documentation stale** — the doc describes a past state; the code has moved on and the doc was never updated.
- **Code stale** — the reverse: code that no longer matches its own stated purpose (none found this pass — see note at the end).
- **Behaviour changed** — a deliberate, documented change since the doc was written (not itself a defect).
- **Intent unclear** — no way to tell, from the artifacts available, which side is authoritative.
- **Historical artifact** — accurate for when it was written, explicitly self-labeled as a plan/proposal, never claimed to describe current state.
- **Not a problem** — an apparent mismatch that, on inspection, is intentional and already documented as such.

## Findings

### 1. `SECURITY.md` — "Rego injection" bullet named a deleted file as the live path

**Claim (pre-correction):** "the Rego source comes from the compiler (`domain/compiler/compiler.py`)... reachable via the operator-key-gated `activate_policy` flow."
**Reality:** `domain/compiler/` does not exist on disk. The live path is `runtime_policy_service.deploy_policy` -> Compiler V2, gated by the `RUNTIME_POLICY_PUBLISH` RBAC permission, not an operator key; `activate_policy` returns HTTP 410 ([17_LEGACY_COMPONENTS.md](17_LEGACY_COMPONENTS.md)).
**Classification: Documentation stale — corrected this phase.** This is the single most consequential finding in this audit: an active security-posture document naming the wrong code path for its most consequential injection surface. Fixed directly, surgically, one bullet only (see [48_PHASE_5_IMPLEMENTATION_REPORT.md](48_PHASE_5_IMPLEMENTATION_REPORT.md)) — this document does not claim to be a historical record (its own first line: "as it actually stands"), so leaving it wrong was not an option the way it would be for a self-labeled proposal doc.

### 2. `MASTER_ROADMAP.md` — "Status: proposed" while roughly half its objectives are shipped

**Claims found stale, with code evidence:**
- "Two independent OPA writers today" — false; `domain/compiler/` is deleted, `routers/policies.py`'s four write endpoints return 410, `upload_policy` has exactly one call site (`runtime_policy_service.py`).
- "Authority Model... exists only as thin, disconnected fragments" — false; `BusinessUnit` (`db/models.py:26`), `Department` (`:42`), `Team` (`:58`) are real tables with real FKs from `Principal`.
- "Extend Evidence with cryptographic chaining" (listed as future Phase 5) — false; `previous_hash`/`_resolve_chain_scope`/`_previous_chain_hash` (`services/intent_service.py`) are live and have been since before this migration program began.
**Claims still accurate:** the RTAL DSL (Objective 3) — zero references to it anywhere in `server/app/**/*.py`. The Authority Graph's traversal/impact-analysis capability (Objective 4) — the underlying `AuthorityRelationship` FKs exist (`db/models.py:925`), but no recursive-traversal or impact-analysis function exists anywhere.
**Classification: Documentation stale.** Already named as unreconciled drift in [23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md) §23.5 and every subsequent phase's Outstanding Issues since Phase 2; this is the first phase to actually open the file and separate its stale claims from its still-accurate ones. **Not corrected in place** — see [47_PHASE_5_NEED_ANALYSIS.md](47_PHASE_5_NEED_ANALYSIS.md) for why this document's own established policy is to supersede, not rewrite, the 63 root docs.

### 3. `VERSION_3_ROADMAP.md` — several "Enterprise Pilot"/"Seed Ready" items already shipped

Human login/RBAC (listed as the single highest-priority Enterprise Pilot item) and Evidence key rotation (listed under "Seed Ready," after several other items) are both fully shipped (`routers/auth.py`, `routers/users.py`, `domain/rbac/permissions.py`; `db/models.py::SigningKey`). Genuinely still-open items are also confirmed still open: no exportable signed evidence bundle (`routers/organization.py`'s `/exports/evidence` returns a plain list, not a signed manifest), no real ERP/IAM connector (`EnterpriseSystem`'s own docstring: "no connector code exists for any row here"), no row-level multi-tenancy (zero `organization_id ==` filters in `principals.py`/`agents.py`/`runtime_policies.py`).
**Classification: Documentation stale** (for the shipped items) **/ Not a problem** (for the honestly-still-open items — the roadmap is accurate there).

### 4. `README.md` — three independent findings

- **Stale test count**: "36 unit tests" (also repeated in `PAYREALITY_MASTER_BLUEPRINT.md`, `DEPLOYMENT.md`); actual count today is 186 (`pytest --collect-only`, this session). **Documentation stale.**
- **Contradicts a sibling doc on deployment status**: README states the backend "is not yet hosted anywhere reachable by the live frontend"; `GO_LIVE.md` states it is live at a specific URL with a verified TLS cert. **Intent unclear** as a pair — `DEPLOYMENT.md` (a third doc) is explicit that it predates the cutover, so the three-way relationship is chronological, not contradictory, once all three are read together; but README and `GO_LIVE.md` alone, without that context, directly disagree on the single most basic operational fact.
- **Defines "Authority"/"Mandate" using the retired legacy model**: README's own top-line glossary (its first substantive content) describes "Mandates" as the live mechanism underpinning Authority. [GLOSSARY.md](GLOSSARY.md) states plainly that Mandate is legacy vocabulary ("in the now-retired legacy pipeline") and that the current model is `AuthorityRelationship`. README never mentions `AuthorityRelationship`, Organisation/BusinessUnit/Department/Team, or any Phase-1 Authority Model concept. **Documentation stale**, and the highest-visibility instance found this pass — this is the first document most new readers open.

**Not corrected in place** for any of the three — see [47](47_PHASE_5_NEED_ANALYSIS.md).

### 5. `RUNTIME_AUTHORITY_TRANSFORMATION.md`, `PHASE_0.md` — frame an already-closed risk as the top open item

Both describe the two-OPA-writer risk as live, urgent, unaddressed. Both are self-labeled `Status: proposed` planning documents, written before the retirement happened. **Classification: Historical artifact.** Unlike `SECURITY.md`, neither claims to describe current state — `PHASE_0.md`'s own header says "proposed." No correction needed or made; this is exactly what a proposal document is supposed to look like after its proposal is executed.

### 6. `ARCHITECTURE.md` — internally inconsistent (banner vs. body)

Already carries a corrective banner (added in this migration's Phase 0 / Baseline work) pointing to `SPECIFICATION/00_INDEX.md` and naming the legacy pipeline as retired — but the document's own body, a few lines below the banner, still narrates the legacy pipeline in the present tense as "the core of the product." **Classification: Not a problem, by design** — the banner already tells a reader which half to trust, and 00_INDEX.md's own stated policy is supersession, not line-by-line correction, of the 63 root docs.

### 7. `12_DECISION_ENGINE.md` §12.4's flowchart

Already found and corrected in Phase 4 (a pointer blockquote, not a rewrite) — the diagram predated Phase 3's Runtime Truth extraction. Re-verified accurate as of this phase. **Classification: Not a problem** (already resolved).

### 8. Code stale — none found

No code path was found whose own stated purpose (docstring, comment, or name) no longer matches what it actually does. Every discrepancy found in this audit is documentation lagging code, never the reverse. This is itself worth stating plainly: it means the repository's drift has a consistent direction, which narrows what any future integrity check needs to watch for.

## Summary table

| # | Document | Classification | Corrected this phase? |
|---|---|---|---|
| 1 | `SECURITY.md` (Rego injection bullet) | Documentation stale | **Yes** |
| 2 | `MASTER_ROADMAP.md` | Documentation stale (partially) | No — policy reasons, see [47](47_PHASE_5_NEED_ANALYSIS.md) |
| 3 | `VERSION_3_ROADMAP.md` | Documentation stale (partially) / Not a problem (partially) | No |
| 4 | `README.md` (3 findings) | Documentation stale / Intent unclear | No |
| 5 | `RUNTIME_AUTHORITY_TRANSFORMATION.md`, `PHASE_0.md` | Historical artifact | No — correctly self-labeled |
| 6 | `ARCHITECTURE.md` | Not a problem (already resolved, Phase 0) | Already done |
| 7 | `12_DECISION_ENGINE.md` §12.4 | Not a problem (already resolved, Phase 4) | Already done |
| 8 | Any code contradicting its own stated purpose | None found | N/A |
