# Part 2 — Architecture Audit: Ownership Map

**Status:** final. **Method:** every module under `server/app/domain/`, `server/app/services/`, `server/app/routers/` inspected directly (37 files total); grouped by the discipline that owns it where one of the eleven applies, and by product function where it sits outside the canon's core runtime path (authoring tools, identity, organization admin — real product surface, not Runtime Authority itself). No file was modified during this audit.

## Core runtime path — the eleven-discipline canon, as implemented

| Module | Owning discipline | Owned concepts | Depends on | Forbidden dependencies (must never gain) |
|---|---|---|---|---|
| `domain/decision/engine.py` | Runtime Authority | `evaluate()`, `Decision`, fail-closed branching | `dataclasses`, `typing` only — verified by test | `app.db`, `app.services`, `app.routers` (tested, `test_architectural_boundaries.py`) |
| `domain/decision/scope_vocabulary.py` | Canonical Fact Intelligence | `KNOWN_SCOPES`, `is_recognized_scope` | nothing | any DB/service import |
| `services/runtime_truth_service.py` | Runtime Truth | `ResolvedFacts`, `resolve()` | `app.db.models`, `authority_context_service` | `domain.decision` (tested, Phase 5), `app.routers` |
| `services/authority_context_service.py` | Resolver Intelligence | `classify_risk`, `resolve_runtime_authority_context`, delegation resolution | `app.db.models`, `sqlalchemy` | — |
| `services/intent_service.py` | Decision Evidence (composition point) | `submit_intent`, `append_evidence`, evidence payload shape, evidence chaining | `domain.decision`, `runtime_truth_service`, `runtime_policy_service`, `domain.evidence.signing` | — |
| `services/resolution_service.py` | Decision Evidence (human-review resolution) | `resolve_decision`, `DecisionResolution` | `intent_service.append_evidence` | — |
| `domain/compiler_v2/*` (5 files) | Policy Intelligence | `RuntimePolicy` -> Rego compilation, `PolicyBundle`, `bundle_hash`, vocabulary validation | `domain.runtime_policy`, `domain.decision.scope_vocabulary` (Phase 3) | `app.db` (tested) |
| `services/runtime_policy_service.py` | Policy Intelligence (persistence/deploy) | `deploy_policy`, single-writer guard, OPA reconciliation | `domain.compiler_v2`, `app.db.models`, `app.opa_client` | — |
| `domain/runtime_policy/*` (6 files) | Policy Intelligence (authoring model) | `RuntimePolicy`, `Scope`, `ConditionSet`, `Constraints`, `Effect`, validation | nothing outside `domain/` | `app.db` |
| `domain/evidence/signing.py` | Decision Evidence | `sign_payload`, `payload_hash`, `verify_evidence` | nothing outside stdlib/crypto | `app.db`, `app.services` |
| `services/evidence_service.py` | Decision Evidence (read/verify) | `get_evidence`, `verify_chain`, signature re-verification | `domain.evidence.signing`, `app.db.models` | — |
| `services/signing_key_service.py` | Decision Evidence (key lifecycle) | `SigningKey` registry, key rotation | `app.db.models` | — |

**No violation found** in this group — every edge matches [26_PHASE_2_DEPENDENCY_DECLARATION.md](../SPECIFICATION/26_PHASE_2_DEPENDENCY_DECLARATION.md), and the three edges most load-bearing for architectural safety are continuously tested, not merely declared.

Intent Intelligence, Context Intelligence, and Integrity Intelligence have no dedicated module — by design, per [35](../SPECIFICATION/35_PHASE_4_INTENT_INTELLIGENCE_SPEC.md), [36](../SPECIFICATION/36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md), and [43](../SPECIFICATION/43_PHASE_5_INTEGRITY_INTELLIGENCE_SPEC.md): each is a documented property of the existing modules above (Intent's schema, the context dict assembled inside `intent_service.py`, and the check set spread across `test_architectural_boundaries.py`/`test_runtime_truth_boundary.py`/`test_policy_compilation_ordering.py`), not a fourteenth-through-sixteenth module. This audit found no code anywhere claiming to "be" one of these three disciplines as a standalone module — the specifications' own restraint (Phase 3/4/5, "deliberately not built") holds.

## Identity, authority-graph, and admin surface — real product code, outside the eleven-discipline runtime path

| Module | Owns | Depends on | Notes |
|---|---|---|---|
| `services/agent_service.py` | Agent lifecycle (register/suspend/revoke/retire), Certificate issuance, Principal directory | `app.db.models` | Feeds Runtime Truth's Principal lookup; does not itself participate in evaluation |
| `domain/auth/signature.py` | ED25519 request-signature verification, replay-window check | stdlib crypto only | Gatekeeps every `POST /v1/intents` before Stage 1 of the pipeline |
| `services/auth_service.py` | Human login/session, bcrypt password hashing, API keys | `app.db.models` | RBAC's authentication half |
| `domain/rbac/permissions.py` | Six roles, permission enumeration | nothing outside `domain/` | RBAC's authorization half |
| `services/organization_service.py` | Organization/BusinessUnit/Department/Team CRUD, Principal assignment | `app.db.models` | The Phase-1 Authority Model's admin surface |
| `services/ai_authority_builder_service.py` + `domain/ai_authority_builder/*` | Document -> extracted Authority-candidate pipeline | `domain.extraction` (Claude/fake provider) | Feeds the legacy Authority review flow, distinct from Compiler V2 |
| `services/ai_policy_builder_service.py` + `domain/ai_policy_builder/*` | Document -> draft `RuntimePolicy` translation | `domain.extraction`, `domain.runtime_policy` | Live, active — feeds Compiler V2 directly, not the retired pipeline |
| `services/document_service.py`, `services/review_service.py` | Read-only views onto the legacy `Document`/`Authority` tables | `app.db.models` | **Verified live, not dead**: both are called from `routers/policies.py`'s still-functioning `GET` endpoints. Only the legacy pipeline's four *write* endpoints (`upload_document`, `review_authority`, `compile_policy`, `activate_policy`) are retired (410); the read views over historical rows created before retirement remain intentionally reachable. Confirmed by direct call-site check before writing this row — an easy, plausible misclassification this audit specifically checked rather than assumed. |
| `services/policy_service.py` | Read-only view onto the legacy `Policy` table | `app.db.models` | 8 lines; the "which policy is currently active" view `12_DECISION_ENGINE.md` §12.3 already documents as still meaningfully live |

## Architectural violations found

**None.** This audit re-walked every import edge Phase 2's boundary tests check, plus every module listed above, looking specifically for a forbidden edge, a duplicated responsibility, or unnecessary complexity beyond what Phases 1–5 already found and fixed. None was found beyond what [44_PHASE_5_ARCHITECTURAL_DRIFT_REPORT.md](../SPECIFICATION/44_PHASE_5_ARCHITECTURAL_DRIFT_REPORT.md) already documents (the `evaluated_mandates` naming residue, already self-commented; the two-roadmap duplication, already documented, out of code entirely).

## Unnecessary complexity / duplicated responsibility — findings

- **Two parallel document-intelligence pipelines**: `domain/extraction/*` (feeds AI Authority Builder) and `domain/ai_policy_builder/text_extraction.py` + its own `claude_provider.py`/`fake_provider.py` (feeds AI Policy Builder) are two independent implementations of "call Claude to extract structured data from a document, with a fake provider for tests," not sharing a base class or common provider interface. This is not a forbidden dependency (each stays inside its own domain subpackage) and is not currently causing a bug — but it is duplicated responsibility: the same provider-pattern (`Provider` protocol, `ClaudeProvider`, `FakeProvider`) is authored twice, once per pipeline, rather than once and reused. A future third extraction use case would be the natural trigger to unify these; building a shared abstraction now, with only two current call sites and zero evidence either has diverged incorrectly, would be exactly the kind of speculative consolidation [47_PHASE_5_NEED_ANALYSIS.md](../SPECIFICATION/47_PHASE_5_NEED_ANALYSIS.md)'s own principle argues against. Recorded here as a real, evidence-based finding, not queued as work — see [03_PRODUCT_GAP_ANALYSIS.md](03_PRODUCT_GAP_ANALYSIS.md) for why it is not ranked.
- **The `Policy`/`RuntimePolicyRecord` two-table split** (legacy `policies` table vs. Compiler V2's `runtime_policies` table) is real, load-bearing complexity — but it is not duplicated responsibility in the accidental sense: `12_DECISION_ENGINE.md` §12.3 and [26_PHASE_2_DEPENDENCY_DECLARATION.md](../SPECIFICATION/26_PHASE_2_DEPENDENCY_DECLARATION.md) both document precisely why it exists (the Decision Engine's `PolicyStore` protocol was never migrated off the legacy table; `deploy_policy` writes a fresh compatibility row to it on every deploy). Collapsing the two tables into one would be a genuine architecture change this program's constraints forbid speculating about; noted here as complexity that is understood and justified, not unnecessary.

## Frontend and product-surface ownership

Not yet covered by direct inspection in this section — see [03_PRODUCT_GAP_ANALYSIS.md](03_PRODUCT_GAP_ANALYSIS.md), which incorporates a dedicated frontend/SDK/operations audit rather than duplicating it here. This document's scope is the backend's architectural ownership map, which the eleven-discipline canon and Phases 1–5 both govern directly; the frontend does not participate in Runtime Authority's evaluation path at all (every canon discipline lives entirely in `server/app/`), so its absence from this table is not a gap in this audit's coverage of the *architecture* — it is coverage of a different concern (*product*), addressed next.
