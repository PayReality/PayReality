# Part 38 — Phase 4: Pipeline Sequence Diagram

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md). **Stage definitions:** [37_PHASE_4_ENTERPRISE_DECISION_PIPELINE_SPEC.md](37_PHASE_4_ENTERPRISE_DECISION_PIPELINE_SPEC.md). Drawn directly from `dependencies.py`, `routers/intents.py`, `services/intent_service.py`, `services/runtime_truth_service.py`, `domain/decision/engine.py`, and `services/resolution_service.py` — the runtime as implemented today, not as originally imagined by any pre-existing design document.

## The submission path (Stages 0–9)

```mermaid
sequenceDiagram
    participant Caller as Agent (caller)
    participant Router as routers/intents.py
    participant Deps as dependencies.verify_agent_signature
    participant Svc as intent_service.submit_intent
    participant DB as intents / decisions / evidence
    participant Truth as runtime_truth_service.resolve
    participant Ctx as authority_context_service
    participant Engine as decision_engine.evaluate
    participant OPA as OPA (compiled Rego)
    participant Sign as evidence.signing

    Caller->>Router: POST /v1/intents (signed body)
    Router->>Deps: verify_agent_signature()
    alt signature invalid / key unknown
        Deps-->>Caller: 401 (no Intent row ever created)
    else signature valid
        Deps-->>Router: Agent
        Router->>Router: agent_id matches signing key?
        Router->>Router: check_timestamp_window(requested_at)
        alt either check fails
            Router-->>Caller: 401 (no Intent row ever created)
        else both pass
            Router->>Svc: submit_intent(agent, action, amount, currency, ...)
            Svc->>Svc: Agent lifecycle gate (revoked/retired/registered)
            alt revoked, retired, or registered
                Svc-->>Router: raise (no Intent row ever created)
                Router-->>Caller: 403
            else active or suspended
                Svc->>DB: INSERT Intent (nonce UNIQUE)
                alt nonce already used
                    DB-->>Svc: IntegrityError
                    Svc-->>Router: ReplayDetectedError
                    Router-->>Caller: 409
                else Intent persisted
                    alt Agent suspended
                        Svc->>DB: INSERT Decision(HUMAN_REVIEW, AGENT_SUSPENDED)
                        Svc->>Sign: sign evidence payload
                        Svc->>DB: INSERT Evidence
                        Svc-->>Router: (Intent, Decision, Evidence)
                    else action not recognized
                        Svc->>DB: INSERT Decision(HUMAN_REVIEW, unrecognized_action)
                        Svc->>Sign: sign evidence payload
                        Svc->>DB: INSERT Evidence
                        Svc-->>Router: (Intent, Decision, Evidence)
                    else recognized action, agent active
                        Svc->>Truth: resolve(db, agent, amount)
                        Truth->>DB: get(Principal, acting_for_principal_id)
                        Truth->>Ctx: resolve_runtime_authority_context(principal, amount)
                        Ctx->>DB: org / business_unit / department / team / delegations lookups
                        Ctx-->>Truth: authority_context dict
                        Truth-->>Svc: ResolvedFacts(principal, principal_name, authority_context)
                        Svc->>Engine: evaluate(intent, context, principal_name, policy_store, opa_client)
                        Engine->>DB: PolicyStore.get_active()
                        alt no active policy
                            Engine-->>Svc: Decision(HUMAN_REVIEW, no_active_policy)
                        else active policy found
                            Engine->>OPA: query(opa_input, timeout_ms)
                            alt timeout or OPA error
                                OPA-->>Engine: exception
                                Engine-->>Svc: Decision(HUMAN_REVIEW, opa_timeout | opa_error)
                            else OPA responds
                                OPA-->>Engine: {allow?, deny?, requires_review?, evaluated_mandates}
                                Engine-->>Svc: Decision(ALLOW | DENY | HUMAN_REVIEW)
                            end
                        end
                        Svc->>DB: INSERT Decision (policy_version, policy_bundle_hash, authority_version pinned)
                        Svc->>Sign: sign evidence payload (+ principal_name, authority_context, delegation_chain)
                        Svc->>DB: INSERT Evidence
                        Svc-->>Router: (Intent, Decision, Evidence)
                    end
                    Router-->>Caller: 200 SubmitIntentResponse
                end
            end
        end
    end
```

## The human-review resolution path (Stage 10 — a separate, later request)

```mermaid
sequenceDiagram
    participant Reviewer as Human reviewer
    participant Router as routers/intents.py
    participant RBAC as require_permission(DECISIONS_RESOLVE)
    participant Res as resolution_service.resolve_decision
    participant DB as decisions / decision_resolutions / evidence
    participant Sign as evidence.signing

    Reviewer->>Router: POST /v1/decisions/{id}/resolve
    Router->>RBAC: permission check
    alt not permitted
        RBAC-->>Reviewer: 403
    else permitted
        Router->>Res: resolve_decision(decision_id, resolution, resolved_by)
        Res->>DB: get(Decision, decision_id)
        alt decision not found
            Res-->>Router: DecisionNotFoundError
            Router-->>Reviewer: 404
        else decision.outcome != HUMAN_REVIEW
            Res-->>Router: DecisionNotHumanReviewError
            Router-->>Reviewer: 409
        else already resolved
            Res-->>Router: DecisionAlreadyResolvedError
            Router-->>Reviewer: 409
        else resolvable
            Res->>Sign: sign second evidence payload (chained via previous_hash)
            Res->>DB: INSERT Evidence (approver/approval_outcome, reviewer/review_outcome)
            Res->>DB: INSERT DecisionResolution
            Res-->>Router: DecisionResolution
            Router-->>Reviewer: 200 ResolveDecisionResponse
        end
    end
```

## Reading this diagram against [37](37_PHASE_4_ENTERPRISE_DECISION_PIPELINE_SPEC.md)

Every `alt`/`else` branch above corresponds to exactly one row of [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) §12.5's fail-closed outcome table or one of [37](37_PHASE_4_ENTERPRISE_DECISION_PIPELINE_SPEC.md)'s ten stages — nothing in this diagram is inferred; each arrow names the actual function call or database statement it represents. The two diagrams together (this one, sequence; [37](37_PHASE_4_ENTERPRISE_DECISION_PIPELINE_SPEC.md), stage detail) are meant to be read side by side: this file answers "in what order, and under what condition," the stage table answers "with what inputs, outputs, and failure semantics."
