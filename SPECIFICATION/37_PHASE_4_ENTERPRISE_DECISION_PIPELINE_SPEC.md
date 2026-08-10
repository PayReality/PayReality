# Part 37 — Phase 4: Enterprise Decision Pipeline Specification

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md). **Diagram:** [38_PHASE_4_PIPELINE_SEQUENCE_DIAGRAM.md](38_PHASE_4_PIPELINE_SEQUENCE_DIAGRAM.md). **Supersedes, for sequence purposes only:** [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) §12.4's flowchart, which predates Phase 3's Runtime Truth extraction and still shows Principal resolution and Runtime Authority Context assembly as two separate boxes rather than one named call — §12's own prose and fail-closed table (§12.5) remain accurate and are not superseded.

## Purpose

This platform already runs one pipeline, end to end, for every Intent. This document exposes it as a canonical, staged sequence — not a redesign, a naming of what `routers/intents.py` and `services/intent_service.py::submit_intent` already do, in the order they already do it.

## The eleven canon disciplines, where they actually participate

Before the stage table: not every discipline participates in every Decision, and one — Dependency Intelligence — does not participate in the runtime pipeline at all. It is a build-time/test-time guarantee (the Phase 2 boundary tests), never consulted while a Decision is being made. Integrity Intelligence, similarly, is a longitudinal property of the architecture over time, not a per-Decision participant. Both are correctly absent from the stage table below — their absence is the accurate statement, not an omission.

## Stage table

### Stage 0 — Signature Verification

- **Inputs:** raw request body, `X-PayReality-Key-Id`, `X-PayReality-Signature` headers.
- **Outputs:** a resolved, authenticated `Agent`, or an HTTP 401.
- **Owner:** `app/dependencies.py::verify_agent_signature`.
- **Consumed disciplines:** none — this is authentication, prior to and independent of every canon discipline.
- **Produced artefacts:** none persisted; a 401 leaves no trace in `intents`/`decisions`/`evidence`.
- **Replay requirements:** none — this stage is not itself replayed; it gates whether any later stage runs.
- **Failure mode:** fail-closed by rejection (401) before any Intent row exists. No Decision, no Evidence — the request never entered the evidentiary trail at all.

### Stage 1 — Request-Level Validation

- **Inputs:** the authenticated `Agent`, `SubmitIntentRequest.agent_id`, `.requested_at`.
- **Outputs:** confirmation that the signing key belongs to the claimed `agent_id`, and that `requested_at` is inside `intent_signature_window_seconds`.
- **Owner:** `routers/intents.py::submit_intent` (router layer), `domain/auth/signature.py::check_timestamp_window`.
- **Consumed disciplines:** none.
- **Produced artefacts:** none persisted.
- **Replay requirements:** none.
- **Failure mode:** HTTP 401 (`agent_id_does_not_match_signing_key` or the timestamp-window rejection reason). No Intent row created.

### Stage 2 — Agent Lifecycle Gate

- **Inputs:** `Agent.status`.
- **Outputs:** proceed, or reject.
- **Owner:** `services/intent_service.py::submit_intent`, lines checking `revoked`/`retired`/`registered`.
- **Consumed disciplines:** none directly — Agent lifecycle status is Agent Architecture ([11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md)), a subsystem this pipeline reads but does not own.
- **Produced artefacts:** none — `revoked`/`retired`/`registered` reject with **no Intent row created at all** ([12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) §12.4's own finding, unchanged).
- **Replay requirements:** none (nothing was recorded to replay).
- **Failure mode:** exception (`AgentRevokedError`/`AgentRetiredError`/`AgentNotOperationalError`) caught at the router, HTTP 403. `suspended` is **not** rejected here — it proceeds to Stage 3 and is handled at Stage 5.

### Stage 3 — Intent Persistence

- **Inputs:** every field of `SubmitIntentRequest` plus the resolved `Agent`.
- **Outputs:** a persisted `Intent` row, or `ReplayDetectedError`.
- **Owner:** `services/intent_service.py::submit_intent`, the `db.add(intent); db.flush()` block.
- **Consumed disciplines:** none yet — this is Intent Intelligence's object being recorded, not yet evaluated.
- **Produced artefacts:** `intents` row (`id`, `agent_id`, `action`, `amount`, `currency`, `counterparty`, `context`, `nonce`, `requested_at`, `received_at`) — write-once, no update path exists anywhere in this codebase.
- **Replay requirements:** this row *is* the primary replay artefact for every caller-supplied fact ([36](36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md)).
- **Failure mode:** `UniqueConstraint(agent_id, nonce)` violation -> `IntegrityError` -> caught, rolled back, re-raised as `ReplayDetectedError` -> HTTP 409. No Decision/Evidence created for a rejected replay.

### Stage 4 — Suspended-Agent Short-Circuit (conditional)

- **Inputs:** `Agent.status == "suspended"`.
- **Outputs:** a `HUMAN_REVIEW` Decision, reason `AGENT_SUSPENDED`.
- **Owner:** `services/intent_service.py::submit_intent`.
- **Consumed disciplines:** none — OPA is never queried; this is a lifecycle-status short-circuit, not an authority evaluation.
- **Produced artefacts:** `Decision` (`policy_id=None`, `evaluated_mandates=[]`) and `Evidence` (`status="PENDING"`, no `principal_id`/`authority_context`/`principal_name` — none were ever resolved).
- **Replay requirements:** self-contained — the Decision/Evidence pair fully explains the outcome (`AGENT_SUSPENDED`) without needing any other table.
- **Failure mode:** N/A — this stage's only outcome is `HUMAN_REVIEW`; there is no further failure within it. Execution ends here for a suspended Agent; Stages 5–9 do not run.

### Stage 5 — Action Vocabulary Gate

- **Inputs:** `Intent.action`.
- **Outputs:** proceed, or a `HUMAN_REVIEW` Decision, reason `unrecognized_action`.
- **Owner:** `domain/decision/scope_vocabulary.py::is_recognized_scope`, called from `services/intent_service.py`.
- **Consumed disciplines:** Canonical Fact Intelligence ([28](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md)) — this is the one runtime read of the `action` fact's identity enumeration.
- **Produced artefacts (on rejection only):** `Decision`/`Evidence` pair identical in shape to Stage 4's, reason `unrecognized_action`; OPA never queried. Execution ends here on rejection.
- **Replay requirements:** self-contained, as Stage 4.
- **Failure mode:** `HUMAN_REVIEW`, not `DENY` — an unrecognized action is ambiguous, not explicitly disallowed (spec 9.3/12.6).

### Stage 6 — Runtime Truth Resolution

- **Inputs:** the authenticated `Agent`, `Intent.amount`.
- **Outputs:** a `ResolvedFacts` value (`principal`, `principal_name`, `authority_context`).
- **Owner:** `services/runtime_truth_service.py::resolve` ([30](30_PHASE_3_RUNTIME_TRUTH_SPEC.md)), composing `services/authority_context_service.py`.
- **Consumed disciplines:** Resolver Intelligence ([29](29_PHASE_3_RESOLVER_INTELLIGENCE_SPEC.md)) end to end — this stage *is* Resolver Intelligence's one call site.
- **Produced artefacts:** none persisted at this stage in isolation — `ResolvedFacts` is an in-memory value consumed immediately by Stage 7 and Stage 9; nothing here writes to the database on its own.
- **Replay requirements:** the *values* this stage produces must reach Stage 9's persistence for the Decision to be replayable ([36](36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md)) — this stage itself has no independent replay story; it is re-run fresh for every Intent, by design, never cached.
- **Failure mode:** none distinct from a normal DB error — an absent Principal degrades gracefully to `ResolvedFacts(principal=None, principal_name=str(agent.acting_for_principal_id), authority_context={"risk_level": ...})`, never raises.

### Stage 7 — Runtime Authority Evaluation

- **Inputs:** `{action, amount, currency}`, `{**caller_context, timestamp, authority: resolved.authority_context}`, `resolved.principal_name`, the active `Policy` row.
- **Outputs:** a `Decision` value (`outcome`, `reason`, `evaluated_mandates`, `policy_id`, `policy_version`, `policy_bundle_hash`, `authority_version`).
- **Owner:** `domain/decision/engine.py::evaluate`, querying OPA via `_EngineOpaClient`.
- **Consumed disciplines:** Policy Intelligence (the compiled Rego bundle OPA evaluates), Runtime Authority (this stage's own outcome), Context Intelligence ([36](36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md), the `context` document evaluated against).
- **Produced artefacts:** none persisted directly — `evaluate()` is pure, DB-free ([27](27_PHASE_2_CONFORMANCE_REPORT.md)'s tested guarantee); its return value is persisted by Stage 8.
- **Replay requirements:** `policy_version`/`policy_bundle_hash`/`authority_version` on the returned `Decision` are exactly what makes this stage's result independently checkable later without needing the `policies` table's current state ([24](24_PHASE_1_RUNTIME_CORE_PLAN.md)).
- **Failure mode:** fail-closed exhaustively — see [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) §12.5's table (`no_active_policy`, `opa_timeout`, `opa_error:<code>`, `undetermined` all resolve to `HUMAN_REVIEW`; exactly one code path reaches `ALLOW`).

### Stage 8 — Decision Persistence

- **Inputs:** the `Decision` value from Stage 7, `runtime_policy_service.resolve_mandate_ids`.
- **Outputs:** a persisted `decisions` row.
- **Owner:** `services/intent_service.py::submit_intent`.
- **Consumed disciplines:** none new — this is Runtime Authority's outcome being recorded, not re-evaluated.
- **Produced artefacts:** `decisions` row — immutable once written (`DecisionResolution` is a separate table for the human-review-resolution event, spec 8.2's "created once, immutable, never updated" guarantee).
- **Replay requirements:** this row is a primary replay artefact; joined with `Intent` and `Evidence` it accounts for every input and output of Stages 3–9.
- **Failure mode:** none distinct from a normal DB error.

### Stage 9 — Decision Evidence Production

- **Inputs:** the persisted `Decision`, `resolved.principal`/`.principal_name`/`.authority_context`, `Decision.authority_version`/`.policy_version`/`.policy_bundle_hash`.
- **Outputs:** a signed `evidence` row.
- **Owner:** `services/intent_service.py::append_evidence`/`_build_evidence_payload`.
- **Consumed disciplines:** Decision Evidence, in full — chain scope resolution, previous-hash lookup, payload construction, signing.
- **Produced artefacts:** `evidence` row (`payload`, `key_id`, `signature`, `status`, `organization_id`) — the payload now additionally carries `principal_name` as of this phase ([41](41_PHASE_4_MIGRATION_REPORT.md)).
- **Replay requirements:** this is the record Decision Evidence's replay coordinate is built from — as of this phase, self-contained for every fact Runtime Authority actually evaluated (see [36](36_PHASE_4_CONTEXT_INTELLIGENCE_SPEC.md)'s gap-closure note).
- **Failure mode:** none distinct from a normal DB/signing error; there is no fail-closed branching within this stage — it runs identically regardless of the Decision's outcome (`ALLOW`/`DENY`/`HUMAN_REVIEW` are all evidenced).

### Stage 10 — Human Review Resolution (conditional, separate request)

- **Inputs:** `decision_id`, `resolution` (`approved`/`denied`), `resolved_by`, an authenticated session user (optional).
- **Outputs:** a `DecisionResolution` row and a second, chained `Evidence` record.
- **Owner:** `services/resolution_service.py::resolve_decision`.
- **Consumed disciplines:** Decision Evidence (a second evidentiary event, chained to the first via `previous_hash`), RBAC ([14_SECURITY_MODEL.md](14_SECURITY_MODEL.md), gating who may call this endpoint).
- **Produced artefacts:** `decision_resolutions` row, a second `evidence` row (`approval_outcome`/`approver` — legacy keys kept unchanged — plus `reviewer`/`review_outcome`, this architecture's correctly-named equivalents).
- **Replay requirements:** the two `Evidence` records for one `Decision` (submission-time and resolution-time) together form the complete evidentiary history; neither alone is sufficient for a `HUMAN_REVIEW` decision that was later resolved.
- **Failure mode:** `DecisionNotFoundError` (404), `DecisionNotHumanReviewError` (409 — cannot resolve a Decision that was never `HUMAN_REVIEW`), `DecisionAlreadyResolvedError` (409 — `DecisionResolution.decision_id` is unique).

## What this specification deliberately does not do

- It does not merge or reorder any stage. Every stage above is a direct restatement of code that already runs in this exact sequence.
- It does not invent stage boundaries where the code has none — Stage 6 and Stage 7 are two different functions today (`runtime_truth_service.resolve`, `decision_engine.evaluate`) called back-to-back, not one combined stage, because that is how the actual call graph is shaped.
- It does not assign Dependency Intelligence or Integrity Intelligence a runtime stage. Neither participates in producing any single Decision; forcing them into this table would misrepresent what they actually are (build-time and longitudinal guarantees, respectively).
