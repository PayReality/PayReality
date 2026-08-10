# Part 23 — Runtime Governance Migration Baseline v1.0

**Status:** frozen baseline, established `2026-08-10` against commit `eb54f3e` (`main`). **Scope:** Stage J (27 modified files, 6 untracked, uncommitted as of this writing) is explicitly excluded from this baseline and from the migration it governs — see §23.0. **Purpose:** this document is the fixed reference point the Runtime Governance Architecture migration measures itself against, phase by phase. It does not restate Parts 1–22 of this specification; it cites them, and adds the one layer they don't yet have: which of the eleven Runtime Governance disciplines owns each existing subsystem, and what the gap is between what exists and what that discipline requires.

## 23.0 Why Stage J is out of scope, explicitly

An architectural decision, not an oversight: Stage J (organisation-structure CRUD, enterprise-system registration, and associated schema/service changes across `db/models.py`, `intent_service.py`, `runtime_policy_service.py`, and 24 other files) is mid-flight, uncommitted, and unrelated in origin to this migration. This baseline is built against the last commit *before* Stage J's changes exist in any form — `eb54f3e` — using a separate git worktree (`runtime-governance-migration` branch) so that reading, documenting, or eventually modifying code for this migration never touches, depends on, or is confused with Stage J's in-progress work. Stage J will be rebased onto the result of this migration once both are independently complete. Anything below that would need to change once Stage J lands is flagged as **Deferred Until Stage J Integration**, not silently assumed away.

## 23.1 Correcting the record before anything else

An earlier reconnaissance pass for this program (conducted before this baseline, against the working tree rather than committed `HEAD`) concluded the legacy Authority/Mandate policy pipeline was "still live" and created an active two-OPA-writer risk requiring elimination in Phase 2. **That conclusion was wrong, and this baseline corrects it explicitly rather than carrying the error forward.** Verified directly against this worktree: `server/app/domain/compiler/` does not exist (confirmed via direct filesystem check, not inference), and `server/app/routers/policies.py`'s four write endpoints unconditionally return `410` (§17.2–17.3 of this specification). The full retirement — deletion of `domain/compiler/compiler.py`, trimming of `policy_service.py`/`document_service.py`/`review_service.py`, migration `805e62a44ac1` dropping the now-unused `Intent` columns, deletion of the frontend page that still called the retired endpoints — is already committed, already in `HEAD`, and confirmed against production data (zero non-empty legacy rows).

What genuinely remains open, per §17.4 of this specification, is narrower than "eliminate the risk": the `policies` table is **not** dead — it is live, single-writer infrastructure (`runtime_policy_service.deploy_policy`), protected by a defense-in-depth exception (`UnexpectedActiveWriterError`) that fires if the active row wasn't written by that function. This is a **correct, working, already-single-writer state** defended by a runtime check — not a live conflict waiting to be fixed. Phase 2's actual job (§23.6) is to make this ownership *declared*, so the guarantee holds by construction rather than by one exception class remembering to fire, not to close a conflict that no longer exists.

## 23.2 Current architecture, by reference

The complete, verified current architecture is Parts 1–22 of this specification. This baseline does not reproduce it. The subsystems relevant to this migration, and where they're documented:

| Subsystem | Specification part | Status as documented |
|---|---|---|
| Runtime Policy Engine (Compiler V2) | [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) | Active, sole OPA writer |
| Runtime Authority Context | [08_RUNTIME_AUTHORITY.md](08_RUNTIME_AUTHORITY.md) | Active, ephemeral per-request enrichment |
| AI Authority Builder / AI Policy Builder | [09](09_AI_AUTHORITY_BUILDER.md) / [10](10_AI_POLICY_BUILDER.md) | Active, two of three historical extraction pipelines |
| Agent Architecture | [11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md) | Active, full lifecycle + SDK |
| Decision Engine | [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) | Active, fail-closed by construction |
| Evidence Engine | [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md) | Active, signing + chaining + key rotation |
| Security Model / RBAC | [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md) | Active |
| Legacy Components | [17_LEGACY_COMPONENTS.md](17_LEGACY_COMPONENTS.md) | Retirement complete except `policies` table (§23.1) |
| Dependency Graph | [18_DEPENDENCY_GRAPH.md](18_DEPENDENCY_GRAPH.md) | Verified acyclic, one-directional `routers → services → domain` |

## 23.3 Runtime, decision, evidence, and policy flow, by reference

- **Runtime/decision flow**: [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md), specifically §12.3's evaluation sequence (`intent_service.submit_intent` → agent-status gate → `authority_context_service.resolve_runtime_authority_context` → `decision.engine.evaluate` → OPA query → `Decision` row → `evidence_service.append_evidence`).
- **Policy flow**: [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md), specifically §7.5–7.11 (RuntimePolicy → validation → vocabulary check → `scope_overlap` conflict detection → `rego_generator` → `bundle_builder` → `bundle_hash` → OPA deploy).
- **Evidence flow**: [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md) (canonicalize → SHA-256 → Ed25519 sign → `previous_hash` chain link → `signing_keys` registry lookup on verify).

None of these flows change in shape during this migration unless a phase below says so explicitly. The migration's job is to make each stage's ownership and boundary declared and checkable, not to redesign the flow itself, per the founder's own "never rebuild working code" instruction.

## 23.4 Ownership boundaries — mapping subsystems to the eleven disciplines

This is the layer that doesn't exist anywhere else in this specification, because the specification predates the Runtime Governance canon.

| Discipline | Owner in this codebase | Gap classification |
|---|---|---|
| Enterprise Decision Model | `decision/engine.py`'s ALLOW/DENY/HUMAN_REVIEW interpretation; `Decision` table | **Already implemented**, clean match |
| Canonical Fact Intelligence | `compiler_v2.py`'s `FinancialVocabulary` (hardcoded action/field list) | **Implemented under a different, narrower shape** — a private compiler vocabulary, not an independently-owned fact registry with identity/definition/version |
| Policy Intelligence | `domain/compiler_v2/*`, `services/runtime_policy_service.py`, `ai_policy_builder` | **Already implemented**, strong match |
| Intent Intelligence | `intent_service.submit_intent`, fixed `Intent` schema | **Implemented under a different shape** — required fields are fixed columns, not derived per-policy |
| Context Intelligence | `authority_context_service.resolve_runtime_authority_context()` | **Already implemented**, strong match; open question below (§23.4.1) on whether it's persisted for replay |
| Resolver Intelligence | None | **Missing.** `EnterpriseSystem` is an explicit label registry with no connector code (by design, per its own status convention) |
| Runtime Truth | Conflated into `decision/engine.py` — no distinct resolve-then-evaluate split | **Not a distinct layer** yet; not a violation, just unseparated |
| Runtime Authority | `decision/engine.py::evaluate()` | **Already implemented**, the cleanest match in the codebase |
| Decision Evidence | `evidence/signing.py`, `evidence_service.py`, hash chain, key rotation | **Already implemented**, the most mature discipline here; provenance is partial (§23.4.2) |
| Dependency Intelligence | None named, but the actual dependency graph (§18.3) is already acyclic and single-directional by discipline | **Structurally present, not declared** — see §23.1's correction |
| Integrity Intelligence | None | **Missing**, and its absence is not abstract: §16.2 of this specification is itself a manually-performed instance of exactly the drift-detection this discipline should own going forward |

### 23.4.1 Resolved: Context is already persisted

Verified directly against `services/intent_service.py`: `authority_context` (the exact dict `resolve_runtime_authority_context()` builds) is passed straight into `append_evidence` → `_build_evidence_payload`, which stores it as `payload["authority_context"]` plus a surfaced `payload["delegation_chain"]` (lines 125–134, 406–412). This is already additive, already non-recomputed, and already exactly what Context Intelligence's persistence requirement asks for. **No Phase 1 work needed here** — this closes cleanly rather than opening a task.

### 23.4.2 Open question: full six-role provenance

Currently captured: `key_id`, `agent_id`. Not currently distinguished: who asserted a fact vs. who resolved it vs. who is responsible if it was wrong vs. who evaluated vs. who approved (as a required input) vs. who reviewed (after the fact, for `HUMAN_REVIEW`). Since this codebase's facts are almost entirely agent-asserted or context-service-computed rather than externally resolved, several of the six roles collapse onto the same party today — that's an honest reflection of the current architecture's simplicity, not a defect to force-fit. Phase 1 adds the fields; it does not manufacture distinctions the current architecture doesn't actually have.

## 23.5 Existing architectural debt, risk, and documentation drift

By reference, not restatement — this specification's own §16.1 and §16.2 already constitute the authoritative, current list. Summarizing only what's relevant to sequencing this migration:

- **Genuinely open and unresolved** (§16.1): MFA schema-only/not enforced; no account lockout; single-instance rate limiting; Compiler V2's field-vocabulary validation gap (a typo'd condition field compiles cleanly and silently never matches); no automatic promotion from AI Authority Builder discovery to the real Authority Model; single-tenant routing on a multi-tenant-shaped schema; OPA running embedded rather than as its own service.
- **Documentation drift already caught and corrected by this specification itself** (§16.2): `ARCHITECTURE.md`, `PHASE_0/1/2/5.md`, `README.md`/`PRODUCT.md`, and `POLICY_COMPILER_V2.md` all had stale "not implemented" or inaccurate claims, all now corrected in this specification. This specification's own "Supersedes" convention (§00_INDEX.md) — old documents kept as design-time records, never deleted, explicitly outranked where they conflict — is itself a real-world instance of the retirement-not-deletion discipline the canon requires of Policy/Fact/Resolver Evolution, arrived at independently before this migration began.
- **Documentation drift not yet reconciled**: `MASTER_ROADMAP.md` and `VERSION_3_ROADMAP.md` remain two independent, never-cross-referenced roadmaps for overlapping ground, and `IMPLEMENTATION_BACKLOG.md` still reads, in its own text, as unimplemented for phases this specification confirms are live. This specification's existence supersedes the *practical* effect of that drift (a reader has a correct, current source now), but the root documents themselves are still internally inconsistent with each other. This is the concrete first target for Phase 5's Integrity Intelligence work — not a hypothetical example, an already-cataloged one.
- **Two risks named in the earlier (uncorrected) reconnaissance that do not apply here**: shared-resource contention (no Budget/Ledger-shaped table exists anywhere in the current schema for it to apply to) and mid-flight policy-version ambiguity (evaluation is synchronous and atomic per intent, narrowing this risk well below the abstract scenario it was drawn from). Neither is fabricated as a problem to solve; both are recorded as dormant, to revisit if the schema ever grows a shared, contended resource.

## 23.6 What each phase actually needs to do, corrected against this baseline

| Phase | Original scope (prior planning turn) | Corrected scope, this baseline |
|---|---|---|
| 1 — Runtime Core | Close the two-writer risk; add six-role provenance; record Policy Version explicitly; fix doc drift | Two-writer risk is already closed (§23.1) — **removed from Phase 1's scope**. Remaining: confirm/extend Context persistence (§23.4.1), add provenance fields (§23.4.2) additively, record Policy Version + Authority Version explicitly at evaluation time, correct `ARCHITECTURE.md`'s remaining stale claims not already fixed by this specification |
| 2 — Dependency Intelligence | Eliminate multiple writers, ownership ambiguity | **Rescoped from elimination to declaration** — the single-writer state already exists; this phase declares it as an explicit, checked artifact rather than an implicit convention defended by one exception class |
| 3 — Canonical Fact Intelligence, Resolver Intelligence, Runtime Truth | Unchanged | Elevate `FinancialVocabulary` into a real fact registry via the existing `Vocabulary` protocol seam (already a partial adapter boundary, per §16.1); formalize Resolver Intelligence's declaration model without inventing connectors; split Runtime Truth out of `decision/engine.py` as its own step |
| 4 — Intent Intelligence, Context Intelligence, Enterprise Decision Pipeline | Unchanged | Blueprint derivation computed alongside the existing fixed schema, not replacing it; close §23.4.1's open question; document the pipeline as it now stands |
| 5 — Integrity Intelligence | Unchanged | First real target is the already-cataloged `MASTER_ROADMAP.md`/`VERSION_3_ROADMAP.md`/`IMPLEMENTATION_BACKLOG.md` drift (§23.5) — a concrete, pre-identified case, not a hypothetical one |

## 23.7 Baseline sign-off

This document is the fixed reference point. Every subsequent phase's Architecture Conformance Report measures against §23.4's ownership table and §23.5's debt/risk list as they stand here, not as they're later remembered to have stood. Changes to this baseline itself require the same explicit-approval standard the founder set for architectural changes generally — implementation proceeds without re-approval; the baseline does not move without it.
