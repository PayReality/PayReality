# Runtime Decision Center V2, Phase 2 Readiness Audit

Audit only. Nothing in this document was built. Findings below come from direct source reads of `server/app/domain/decision/engine.py`, `server/app/domain/policy_simulation/explainer.py`, `server/app/domain/compiler_v2/bundle_builder.py`, `server/app/services/authority_context_service.py`, `server/app/services/intent_service.py`, `server/app/db/models.py`, `server/app/schemas/intent.py`, and `server/app/routers/enterprise_systems.py`, cited with file:line where it matters.

## What Runtime Authority already knows but doesn't currently expose

**1. Individual policy conditions / per-condition results.** The OPA response `decision/engine.py` reads (lines 139-175) is only `allow`/`deny`/`requires_review`/`review_reason`/`deny_reason`/`evaluated_mandates`, i.e. aggregate booleans; the compiled Rego (`compiler_v2/bundle_builder.py:108-144`) never emits per-condition output keys. **No per-condition result exists in the OPA response today.**

The real per-condition explainer already exists: `domain/policy_simulation/explainer.py`'s `ConditionEvaluation`/`RuleEvaluation`, used today only by the Runtime Policy Simulator (`policy_simulation_service.py`). It is a deterministic Python re-statement of the same `Condition`/`Scope` objects the Rego generator reads, not a second re-run against OPA, so reusing it for real decisions is the right direction rather than building a second explanation engine. It needs the real `RuntimePolicy` objects, `intent`, `context`, `acting_for_principal_id`, and the real `evaluated_mandates` list. The `intent`/`context`/`principal` inputs are all reconstructable from what's already persisted (`Intent.context`, `Evidence.payload["authority_context"]`/`["principal_name"]`), no recomputation needed. The real gap: nothing persists which exact set of `RuntimePolicyRecord`s a past Decision's bundle actually contained (`bundle_builder.build_bundle`'s manifest, listing every compiled policy id/name/version/scope, is generated in memory and never persisted; `bundle_uri` is a synthetic string, not a retrievable artifact). Reconstructing the historical rule set a past decision was evaluated against is real design work, not a wiring job.

**2. Policy identifiers/versions/bundle info.** `policy_version`/`policy_bundle_hash` exist transiently on `decision_engine.Decision` and land in `Evidence.payload`, but never on the `Decision` DB row or `GetDecisionResponse`. Small, bounded addition. Full compiled Rego source by `policy_version` is not stored anywhere retrievable; it's deterministically re-derivable from `RuntimePolicyRecord.content` since `bundle_hash` is content-addressed, but only once item 1's historical-policy-set problem is solved.

**3. Authority/decision engine versions.** `DECISION_ENGINE_VERSION` versions only the `evaluate()` function's own decision logic (bump only if replaying a past decision could change its outcome), not the compiler or OPA or policy content. No changelog concept exists anywhere in the codebase. The version string itself is already real and already on Evidence; exposing it is small, a human-readable changelog of what it means at each version is design work.

**4. Delegated authority beyond one hop.** Confirmed: this is a **service-layer limit, not a data-model limit**. `authority_context_service._active_inbound_delegations` explicitly does one hop by its own comment ("not a multi-hop chain walk... Phase 4"). The underlying `AuthorityRelationship` table is a general graph-edge table (`from_principal_id`/`to_principal_id`/`kind`/validity/status/`cross_org_approved`) that's fully walkable transitively today. Real design work (traversal + cycle handling + a sane UI for an N-hop chain), but not blocked on any missing schema.

**5. Approval requirements.** No structured "who must approve" concept exists anywhere. `Effect` is only ALLOW/DENY/REQUIRE_HUMAN_REVIEW with no approver metadata attached; the free-text `resolved_by`/`reviewer` fields are Decision Evidence's only "who acted" concept. `Permission.DECISIONS_RESOLVE` is a fixed, non-decision-specific RBAC permission, not a per-policy approver rule. Would be a genuinely new domain concept, not an exposure gap.

**6. Principal/enterprise context.** No gap on Principal (`AuthorityContext` already surfaces everything the model has). `EnterpriseSystem` has `type` and `status` beyond the `id`/`name` already shown; small addition to include them.

**7. Evidence metadata.** Signing-key rotation history (`GET /v1/evidence/verification-keys`) and per-record/chain verification (`POST /v1/evidence/{id}/verify`, `GET /v1/evidence/chain/verify`) are real, already-shipped, already-callable endpoints; simply not joined into the Decision Center's Evidence section today. Same bucket as the "signer" gap the Data Provenance audit found (`agentsApi.listCertificates`, also already callable).

**8. Decision metadata.** `GetDecisionResponse` omits `Decision.policy_id` and `Decision.created_at`, both real columns; trivial to add. `Intent` columns (`correlation_id`, `counterparty`, `context`, `nonce`, `requested_at`, `received_at`) are similarly real and similarly unexposed.

## Enterprise Knowledge boundary, independently verified

A dedicated audit confirmed, by direct grep across all of `server/app` (not just the doc files), that none of the following exist as working code: vendor approval status, AML status, insurance verification, banking verification, budget availability checks, employee/HR status checks, country as a structured field, cost centre as a structured field, or any real integration client for SAP/Oracle/Workday/ServiceNow/any external system. `EnterpriseSystem`'s own service module states in its own docstring that `status` never leaves `"configuration_required"` because "no connector code exists anywhere in this codebase to earn that state." The OPA input document has exactly four top-level keys (`intent`, `context`, `agent`, `policy_version`), no `enterprise_knowledge` key or reserved slot, empty or otherwise. `"enterprise_knowledge"` as a literal string or concept appears only in the three planning `.md` files, never in `.py` code. Enterprise Knowledge remains entirely VISION; this audit found no evidence to the contrary.

## Phase 2 proposal

### Bucket A, already available (frontend wiring only)

| Item | Customer value | Complexity | Risk | Dependency | Strengthens the Runtime Authority story |
|---|---|---|---|---|---|
| Signer/certificate detail on a decision (`agentsApi.listCertificates`) | Medium, completes "who signed this" | Low | Low | None | Yes, direct evidence of cryptographic identity |
| Evidence chain/signature verification inline (`/verify`, `/chain/verify`) | High, turns "trust us" into "verify it yourself" in place | Low | Low | None | Yes, this is the platform's core differentiator made clickable |
| Signing-key rotation history on the Evidence section | Low to medium, mostly an audit/compliance nicety | Low | Low | None | Minor |

**Recommendation: do this first.** Lowest risk, no schema changes, and the evidence-verification item in particular is a strong, cheap addition to exactly the page meant to be the platform's flagship moment.

### Bucket B, backend-supported but not exposed (small API/schema additions)

| Item | Customer value | Complexity | Risk | Dependency | Strengthens the story |
|---|---|---|---|---|---|
| `policy_version`/`policy_bundle_hash`/`authority_version` directly on `GetDecisionResponse` | Medium, removes the Evidence-fetch dependency for these | Low | Low | None | Moderate, mostly a plumbing cleanup |
| `Decision.created_at`, `Decision.policy_id` on `GetDecisionResponse` | Low to medium, enables a real decision-level timestamp in the Timeline | Low | Low | None | Moderate, fixes a real gap this audit found (no decision timestamp exists today) |
| `EnterpriseSystem.type`/`status` on the decision response | Low | Low | Low | None | Minor |
| Intent fields (`correlation_id`, `counterparty`, `context`, `nonce`, timestamps) | Low, mostly debugging/audit value | Low | Low | None | Minor |

**Recommendation: reasonable second wave**, bundle with Bucket A since both are low-risk additive schema/response changes with no design ambiguity.

### Bucket C, requires architectural work

| Item | Customer value | Complexity | Risk | Dependency | Strengthens the story |
|---|---|---|---|---|---|
| Per-condition policy explainability on live decisions, reusing the Simulator's explainer | Very high, this is the single most-requested capability in the original brief | High | Medium (must not regress the Simulator's own use of the same explainer) | Solving the historical-policy-set persistence problem first | Very high, this is the "why" a Decision Center is supposed to answer |
| Multi-hop authority chain resolution | Medium to high for larger orgs with real delegation chains; low for orgs with flat structures | Medium | Low to medium (cycle handling, performance on deep chains) | None blocking (schema already supports it) | High, "delegated authority" is the platform's core thesis |
| Structured approval-requirement concept | Medium, mostly relevant once Enterprise Knowledge or more complex approval workflows exist | High | Medium | Product decision on what "requires approval" should mean structurally | Medium |
| Decision engine version changelog | Low | Low to medium | Low | None | Low |

**Recommendation: the per-condition explainability item is the one worth real investment.** It's the most valuable single thing this audit found, reuses existing, already-correct logic rather than inventing a second engine, and is exactly what the original brief asked for. It should not be scoped until the historical-policy-set persistence problem (what a past Decision's bundle actually contained) has an owner and a design, since faking it against today's active policy rather than the one actually evaluated would silently misattribute reasoning to the wrong rule set for any decision made before the most recent policy change.

### Bucket D, Enterprise Knowledge

Everything named in Workstream 5's boundary check: vendor approval, AML, insurance, banking, budget, employee status, country, cost centre, and live external-system state. All confirmed VISION, all belong to `ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md`'s own roadmap, none should be scoped as part of "Phase 2" of this specific page. This bucket is out of scope for any near-term work per that document's own explicit deferral, restated here rather than revisited.

## Recommendation for what Phase 2 (if approved) should actually contain

Buckets A and B only: real, low-risk, immediately available or near-available data that completes what Phase 1 already started, exactly matching this platform's demonstrated pattern of shipping only what's real. Bucket C's explainability item is the right next big investment after that, but needs its own design pass (specifically: how to persist or reconstruct a decision's historical rule set) before it's buildable, not before it's valuable. Bucket D stays untouched.
