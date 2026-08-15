# Runtime Decision Center V2, Data Provenance Audit

Traces every value the Phase 1 page (`src/app/live/pages/LiveTestIntent.tsx`) displays, from UI to frontend type to API response to backend schema/source. Nothing here is upgraded from LIVE/PLANNED/VISION without the citation to back it.

## Business context column

| UI element | Frontend source | API | Backend source | Class |
|---|---|---|---|---|
| Agent dropdown options | `LiveAgent.name` | `GET /v1/agents` | `Agent` model | LIVE |
| Action dropdown options | `policyStudioApi.getVocabulary()` | `GET /v1/runtime-policies/vocabulary` | `FINANCIAL_VOCABULARY.known_actions` | LIVE |
| Principal name | `LivePrincipal.name` (looked up from `agentsApi.listPrincipals()`) | `GET /v1/principals` | `Principal` model | LIVE |
| Role / Team / Department / Business unit / Organization | `PrincipalAuthorityContext` / `AuthorityContext` | `GET /v1/principals/{id}/authority-context`, or `payload.authority_context` on Evidence | `authority_context_service.resolve_runtime_authority_context` (`Principal`/`Team`/`Department`/`BusinessUnit`/`Organization` models) | LIVE |

## Runtime authority pipeline (center column)

| Stage | Basis | Class |
|---|---|---|
| "Intent accepted and identity verified" | Inferred, not a returned field: a `decision` object exists only if `verify_agent_signature` (`app/dependencies.py`) and the replay/timestamp window check already passed. If either failed, `handleSubmit`'s first `try` block would have thrown and no `decision` would exist. | LIVE (a true inference from a real precondition, not a directly-returned flag) |
| "Delegated authority" | Same authority-context sources as above | LIVE |
| "Runtime policies evaluated" | `GetDecisionResponse.evaluated_mandates` | LIVE |
| "Risk classified" | `EvidencePayload.risk_classification`, computed by `authority_context_service.classify_risk(amount)`: LOW < $50k, MEDIUM ≥ $50k, HIGH ≥ $100k, CRITICAL ≥ $250k, a static amount threshold, not a modeled risk score | LIVE |
| "Evidence recorded" | `SubmitIntentResponse.evidence_id` | LIVE |

## Decision column

| UI element | Source | Class |
|---|---|---|
| Outcome badge (ALLOW/DENY/HUMAN_REVIEW) | `GetDecisionResponse.outcome` | LIVE |
| Reason sentence | `GetDecisionResponse.reason` (a real backend code such as `no_active_policy`, `opa_timeout`) translated through `describeReason`'s static `REASON_SENTENCE` map | LIVE data, curated (not fabricated) English |
| Policies evaluated / Mandate IDs | `evaluated_mandates` / `evaluated_mandate_ids` | LIVE |
| Enterprise system | `GetDecisionResponse.enterprise_system_name`, resolved server-side in `routers/intents.py`'s `_enterprise_system_name` from the real `EnterpriseSystem` row | LIVE |
| Risk classification | Same as pipeline | LIVE |
| Evidence recorded (Yes/No) | Presence of `result` | LIVE |
| Approve/Deny buttons | `POST /v1/decisions/{id}/resolve` | LIVE, unchanged pre-existing capability |
| "Resolved X by Y" | `GetDecisionResponse.resolution` (`ResolutionSummary`) ← `DecisionResolution` model | LIVE |
| "Could not evaluate" error text | `describeApiError`, translating a real `ApiError` (signature failure, `agent_suspended`/`agent_retired`/`agent_not_operational`, `replay_detected`, or any other non-2xx) | LIVE data, curated English |
| Fail-closed sentence in the Blocked state | Reused verbatim from `PlatformOverview.tsx` | Product-principle copy, not a data claim; nothing to trace |

## Authority chain section

| UI element | Source | Class |
|---|---|---|
| Principal → Agent chain | Same principal/authority-context sources as above | LIVE, correctly scoped to one hop |
| Delegation rows (operation, resource) | `AuthorityContext.delegations` (`DelegationEdge[]`), from `authority_context_service._active_inbound_delegations` reading the `AuthorityRelationship` table | LIVE |

## Runtime policy evaluation section

Flat list of `evaluated_mandates` (policy keys). No per-condition pass/fail is shown or implied; the caption states this explicitly. See the Phase 2 Readiness Audit for why (the real per-condition explainer exists but needs the historical policy-set problem solved first, not a simple wiring job).

## Evidence section (per record)

| Field | Source | Class |
|---|---|---|
| Evidence ID | `EvidenceResponse.evidence_id` ← `Evidence.id` | LIVE |
| Status | `Evidence.status`, set by `_evidence_status_for_outcome` at submission (ALLOW→VERIFIED, DENY→REJECTED, HUMAN_REVIEW→PENDING) and by `resolution_service` on resolve (VERIFIED/REJECTED) | LIVE |
| Key ID | `Evidence.key_id` | LIVE |
| Recorded at | `payload.recorded_at`, `datetime.now(timezone.utc).isoformat()` at the moment `_build_evidence_payload` runs | LIVE |
| Risk classification, Authority outcome, Approval outcome | `payload.risk_classification` / `authority_outcome` / `approval_outcome` | LIVE (approval_outcome is `null` on the submission-time record; only the resolution-time record sets it, confirmed by reading `resolve_decision`'s call to `append_evidence`) |
| Reviewer / Approver | `payload.reviewer` / `payload.approver` | LIVE, but **only present on the resolution-time record**. Confirmed by reading `intent_service.py`'s submission-time `append_evidence` call directly: it passes no `approver`/`reviewer` argument at all, so both are `None` on every ALLOW/DENY/fresh-HUMAN_REVIEW record. The UI's `p.reviewer ?? p.approver` correctly renders nothing for these, not a placeholder. |
| Policy version / Policy bundle hash / Decision engine version | `payload.policy_version` / `policy_bundle_hash` / `authority_version` | LIVE. These fields were already real in the backend's JSON response before this task; the frontend's `EvidencePayload` TypeScript type simply hadn't declared them until Phase 1's implementation added the declaration (no backend change). |
| Previous record hash | `payload.previous_hash` = `payload_hash(prior_evidence.payload)`, i.e. a hash of the immediately preceding record's payload within the same organization scope, not a hash of this record itself | LIVE, but the label should more precisely say "hash of the prior record" rather than imply a self-hash; noted in the UX audit as a small copy clarification. |
| Matched policies | `payload.matched_mandate_ids` | LIVE |
| Signature | `Evidence.signature` (Ed25519), truncated for display | LIVE |

### Gap found during this audit: "signer" is real but not shown

The task asked this audit to pay particular attention to "signer." The agent's signing certificate (`agent.certificate_id`, and the `Certificate` model's `public_key`/`issued_at`/`status` fields, already used elsewhere in `AgentDetailPage.tsx`) is real, already-fetchable data that Phase 1 does **not** display anywhere on the Decision Center. This is a Phase 1 completeness gap, not a Phase 2 concept: the data is already available via the existing `agentsApi.listCertificates(agentId)` call, it was simply not wired into this page. Recorded here rather than silently left out.

## Timeline section

| Event | Source | Class |
|---|---|---|
| "Request sent" | `Date.now()` at the moment the client calls `postSigned`, labeled explicitly as local/client-observed | Real, but not a server timestamp; labeled honestly as such |
| "Evidence recorded" | `Evidence.created_at` on the submission-time record | LIVE |
| "Resolved X by Y" | `DecisionResolution.created_at` | LIVE |

Confirmed during this audit: `GetDecisionResponse` has no timestamp field of its own (`Decision.created_at` exists as a DB column but is not in the response schema). The Timeline's three real timestamp sources above are the only ones actually available; no fourth "OPA evaluation started/finished" timestamp exists anywhere, since evaluation is one atomic call, not an independently timed step.

## Summary of classifications

Every value currently rendered on the Decision Center is **LIVE**: either returned directly by an existing API response, or a genuinely correct inference from a real precondition (the "identity verified" pipeline step), or copy (the fail-closed sentence, the "condition-level detail isn't available" caption) rather than a data claim. Nothing on the page today is PLANNED or VISION; those categories describe what's absent, not what's shown, per Phase 1's own scope discipline.
