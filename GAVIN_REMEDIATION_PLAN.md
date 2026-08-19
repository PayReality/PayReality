# PayReality / ABSA: Remediation and Implementation Plan

**Status: planning only. No code changed. Built directly on GAVIN_ABSA_PRODUCT_AUDIT.md's accepted findings, not a new discovery pass.**

---

## A. Gavin Readiness Remediation Map

### Gap 1 -- "Authorization Receipt" has no distinct shipped identity

- **Current state:** the substance lives in `Evidence` (`server/app/db/models.py:715`), a JSON payload plus signature/hash-chain. No `AuthorizationReceipt` object anywhere. The website calls the concept "Coming Soon."
- **Target state:** a stable, named, well-typed projection over Evidence + Decision + the historical-policy-explanation mechanism, exposed as a real API shape and export, with the website's status corrected once it genuinely meets the criteria below.
- **Files/components likely affected:** new `server/app/schemas/authorization_receipt.py`; new `server/app/services/authorization_receipt_service.py` (assembly only, no new writes); new route in `server/app/routers/evidence.py` or a new `receipts.py` router; `PayReality website/src/app/pages/products/AuthorizationReceipts.tsx` and the developer equivalent (status update, last step, gated on real acceptance).
- **Architecture decision:** projection, not a new table (Scope Decision 1 below).
- **Dependencies:** none -- can start immediately.
- **Risk:** low. Purely additive; no existing write path changes.
- **Acceptance test:** a receipt for a decision made under policy v1, requested again after the org has redeployed to v2 and v3, still reports v1's exact values (reusing the already-passing historical-binding tests as the underlying proof); signature verification still passes; tampering with any field fails verification.

### Gap 2 -- No Authority Graph → Runtime Policy compiler

- **Current state:** only `CandidateRuntimePolicy` (one of eight extracted categories, generated directly from source text by the model) has a real promotion path (`promote_candidate`) into a draft `RuntimePolicy`. Principals/relationships/conflicts have no code bridge to policy logic.
- **Target state:** promotion is gated on the candidate's referenced principals/relationships being *resolved and active* in an *approved* graph version (Gap 3), and the resulting draft carries real provenance back to the exact graph elements that justified it. The compiler does not synthesize new policy logic from graph structure -- it validates and links.
- **Files/components likely affected:** `server/app/services/ai_policy_builder_service.py` (`promote_candidate`, `build_runtime_policy_from_candidate`); `server/app/services/ai_authority_builder_service.py` (resolution/activation state to check against); `server/app/domain/runtime_policy/runtime_policy.py` (new provenance fields, additive); a new `server/app/domain/compiler_v2/graph_gate.py`-style validation step, or a service-level function, not a new compiler module inside `compiler_v2` itself (Compiler V2 stays domain-agnostic and untouched).
- **Architecture decision:** see Scope Decision 3.
- **Dependencies:** Gap 3 (needs a real "approved graph version" to gate against).
- **Risk:** medium. Touches the promotion path real customers may already rely on (currently used and tested); must stay backward-compatible for candidates not tied to a graph-structural principal at all.
- **Acceptance test:** promoting a candidate whose principal is unresolved in the target graph version fails with a structured diagnostic, not a silent draft; promoting a candidate whose principal/relationship *is* resolved and active succeeds and the resulting `RuntimePolicy` records which graph version/elements produced it; the same graph state produces the same compile result every time (deterministic).

### Gap 3 -- Authority Graph has no real version history

- **Current state:** `AuthorityGraphApproval` already exists as an additive, immutable, hashed record per reviewer-approval action, with an incrementing `version` integer -- closer to a real versioning primitive than the audit's own brief initially assumed. `get_graph_diff` already exists for cross-corpus diffing.
- **Target state:** each `AuthorityGraphApproval` genuinely represents an immutable, retrievable snapshot of the graph's *resolved* state at that moment (not just an approval timestamp), linked to its predecessor, with diffing available between two approvals of the *same* corpus, not only across corpora.
- **Files/components likely affected:** `server/app/services/ai_authority_builder_service.py` (`approve_graph`, `get_graph_diff`); `server/app/db/models.py` (an additive `supersedes_approval_id` nullable FK on `AuthorityGraphApproval`, if not already equivalent to one).
- **Architecture decision:** see Scope Decision 2. First task here is re-reading `AuthorityGraphApproval`'s exact current schema before finalizing -- the audit did not capture its full column list, only its behavior.
- **Dependencies:** none new; extends an existing mechanism.
- **Risk:** low-medium, depends on exactly how much `approve_graph` already snapshots vs. references live rows.
- **Acceptance test:** approving a graph twice for the same corpus produces two independently retrievable, immutable snapshots; a diff between them correctly reports what changed; a later change to live `AuthorityPrincipal`/`AuthorityRelationship` rows never alters an already-approved snapshot's own content.

### Gap 4 -- No external enterprise-fact resolution

- **Current state:** `EnterpriseSystem` is a registered label only ("no connector code exists for any row here," by the model's own docstring). `runtime_truth_service` resolves only internal org-chart/role data.
- **Target state:** a small, generic Fact Resolver framework: a registry of fact definitions (each tied to a registered `EnterpriseSystem`), a resolver protocol, one real generic authenticated-HTTP implementation plus a static/test implementation, wired into intent evaluation as a new, explicit, fail-closed pre-evaluation step.
- **Files/components likely affected:** new `server/app/domain/fact_resolution/` package (protocol, `ResolvedFact`, static + HTTP resolvers); new `FactDefinition` table (additive, referencing existing `EnterpriseSystem`); `server/app/services/intent_service.py` (a new resolution step between `runtime_truth_service.resolve` and `decision_engine.evaluate`); `server/app/domain/compiler_v2/compiler_v2.py`'s `FinancialVocabulary.is_valid_field` (extend to recognize `facts.<key>` as valid only if registered for the org -- direct reuse of the field-vocabulary validation already shipped this session).
- **Architecture decision:** see Scope Decision 5.
- **Dependencies:** none technically; should land before Gap 2's compiler is exercised against a real fact-dependent policy, but not before the compiler mechanism itself.
- **Risk:** medium-high -- this is the one genuinely new subsystem in this plan, and the one most likely to attract scope creep if not held to "one fact, one config, one demo" discipline.
- **Acceptance test:** a policy condition referencing a registered fact resolves correctly via the static test resolver; a required fact that fails to resolve (timeout, missing, resolver error) fails closed to `HUMAN_REVIEW`, never a default `ALLOW`; the fact's source and resolved value appear in the resulting Evidence/receipt.

### Gap 5 -- No UiPath/Maestro-specific integration exists

- **Current state:** zero references anywhere in the codebase; the generic HTTP API is technically compatible but untested against either platform.
- **Target state:** a precise, documented, testable integration contract (OpenAPI shape, example payloads, reference sequence) plus a real test harness simulating an orchestrator's role against the real API -- explicitly labeled as a simulated harness, not a live UiPath/Maestro deployment.
- **Files/components likely affected:** new `docs/UIPATH_MAESTRO_INTEGRATION.md` or equivalent; new `server/tests/integration/test_orchestrator_contract.py` (simulated orchestrator: submit, branch on outcome, poll for REVIEW resolution, respect timeout/retry).
- **Architecture decision:** honest framing only -- see Scope Decision 9.
- **Dependencies:** Gaps 1, 2, 4 should be real first, so the harness exercises genuine behavior, not a stub.
- **Risk:** low technically; the only real risk is over-claiming compatibility that was never tested against the real platform.
- **Acceptance test:** the simulated harness demonstrates APPROVE-continues, DENY-stops, REVIEW-pauses-then-resumes-via-poll, and timeout-does-not-continue, all against the real API.

### Gap 6 -- PayReality cannot enforce its own decision (no execution gate)

- **Current state:** a queried opinion service; nothing prevents a non-compliant caller from proceeding regardless of the answer.
- **Target state (this phase):** honestly and precisely documented, in both ABSA-facing and internal materials, as an architectural characteristic, not silently left implicit. A signed authorization grant is designed (not built) as the concrete answer if a future phase needs non-bypassable enforcement.
- **Files/components likely affected:** documentation only, this phase.
- **Architecture decision:** deferred build, per Scope Decision 7.
- **Dependencies:** none.
- **Risk:** low if disclosed; high if left implicit and later discovered by ABSA's own security review.
- **Acceptance test:** N/A this phase (documentation, not code) -- revisit if promoted to a build phase.

### Gap 7 -- Human review is pull-based only

- **Current state:** real, correct, but requires polling `GET /v1/decisions/{id}`.
- **Target state (this phase):** confirmed sufficient for the first Gavin-ready implementation (Scope Decision 8); documented as the reference pattern for a Maestro wait-step. A webhook/callback is designed as a follow-on, not built now.
- **Files/components touched:** documentation (the same integration contract from Gap 5) plus the orchestrator-simulation test.
- **Risk:** low.
- **Acceptance test:** covered by Gap 5's harness (poll-until-resolved path).

---

## B. Dependency order

```
Milestone A (Authorization Receipts)  ----------------------\
                                                               \
Milestone B (Graph versioning)  --> Milestone C (Graph→Policy)  --> Milestone H (Orchestrator harness)
                                                               /
Milestone D (Fact Resolver)  ---------------------------------
                                                               /
Milestone E (Input model review, no build expected)  --------/

Milestone F (Enforcement contract / signed grant): design doc only, no build dependency
Milestone G (Human review continuation): confirmed polling-sufficient, documentation only
Milestone I (Process chains): explicitly not built
```

A can start immediately and finish before anything else. B and D can run in parallel with each other and with E. C depends on B. H depends on A, C, and D all being real. F and G produce a decision record each, not code, and can happen at any point without blocking anything else.

---

## C. Scope decisions

**1. Should Authorization Receipt be a new table or a projection over Evidence?**
**A projection.** Almost every field the ABSA document's sample receipt names is already present on `Evidence.payload` or reachable via `Decision`. The only genuinely new thing is packaging: a stable schema, a `GET` endpoint, and an export shape that calls the already-correct `decision_explanation_service` live for the per-condition detail rather than storing a second, potentially-divergent copy. No new persistent storage. Verification status is always computed on demand, never cached.

**2. What is the minimal Authority Graph versioning model?**
**Extend `AuthorityGraphApproval`, don't build a parallel `AuthorityGraphVersion` table.** It's already an immutable, hashed, incrementing-version record per approval action -- the closest thing to the exact primitive requested. The concrete additive work is: confirm (first task in Milestone B) that its snapshot genuinely captures resolved graph state, not just a timestamp; add a `supersedes_approval_id` reference if one doesn't already exist in some form; extend `get_graph_diff` to diff two approvals of the same corpus, not only across corpora. This is confirmed pending a direct re-read of the exact schema, per the process this plan is required to follow (re-read before deciding).

**3. What exactly should the Authority Graph compiler compile?**
**It validates and links; it does not synthesize.** The only real source of policy *content* (thresholds, conditions, effect) is the already-real `CandidateRuntimePolicy` extraction -- relationships and principals carry no threshold/condition data of their own and never will without a much larger, unrequested change. The compiler's actual job: given an approved graph version, gate `promote_candidate` on "does this candidate's principal resolve, and does any relationship it implies exist and is it active, in this specific approved version" -- block with a structured diagnostic if not -- and stamp real provenance (`source_graph_version_id`, `source_candidate_id`, resolved principal/relationship ids) onto the resulting draft. This makes "Authority Graph compiles into Runtime Policies" true in the sense that matters (a policy cannot exist without a coherent, resolved, approved graph behind it) without inventing a risky, magical condition-synthesis step nobody asked for.

**4. How should RuntimePolicy reference its source graph/provenance?**
**Additive fields, not a new table.** `source_graph_version_id`, `source_candidate_id`, and reuse of the already-existing `authority_id` linkage, following the same pattern already used for `delegated_by`/`risk_level` on `RuntimePolicy.constraints`.

**5. What is the minimum viable Fact Resolver architecture?**
As specified in the brief, with two refinements grounded in real code: (a) build it as an extension of the *already-existing* `EnterpriseSystem` registry (a `FactDefinition` row references an `EnterpriseSystem`), not a second, disconnected registry; (b) the field-vocabulary validation shipped in Compiler V2 this session (`is_valid_field`/`INVALID_FIELD`) is the exact, already-built hook to validate `facts.<key>` references at compile time -- extend it, don't rebuild it. One generic authenticated-HTTP resolver plus one static/test resolver is enough; no MuleSoft-equivalent platform.

**6. Do we need process-chain policies now?**
**No.** The reference demo (supplier approved AND budget available AND amount ≤ threshold) is fully expressible as three flat AND conditions against the existing `ConditionSet`. Confirmed no change needed to the policy model itself.

**7. Do we need a signed authorization grant now?**
**No -- design it, don't build it.** It directly answers the audit's most likely security-review question (Gap 6), so it's worth having a concrete, ready-to-build answer, but nothing in the actual Gavin-ready demo requires a downstream adapter that refuses execution without a grant -- the demo only requires the orchestrator to branch on the decision, which already works. Building it now would be exactly the kind of scope expansion this plan is instructed to avoid. Recommend a short, separate design note, not a build phase in this pass.

**8. Is polling sufficient for HUMAN_REVIEW in the first Gavin-ready implementation?**
**Yes.** It's a completely standard pattern for this class of workflow integration (both UiPath and Maestro have native wait/poll step types), and nothing in the demo's own step list requires sub-second resume latency. Document it as the reference pattern; design (don't build) a webhook as the next hardening step.

**9. What does "UiPath-ready" mean without a live UiPath environment?**
A precise, versioned integration contract plus a real test harness that plays the orchestrator's role against the real API and proves the contract holds (branch correctly on each outcome, respect timeouts, handle REVIEW-then-poll correctly) -- explicitly and permanently labeled as a simulated harness, never described as a verified UiPath/Maestro deployment.

**10. Which claims become fully demonstrable after this work, and which still need a real ABSA integration?**

*Fully demonstrable with real software, entirely in our own control, after Milestones A-D:* governance ingestion → extraction → human validation → versioned approved graph → gated compilation to a draft policy → normal lifecycle to active → real intent submission → fact resolution (against a configured test resolver) → deterministic ALLOW/DENY/REVIEW → receipt → cryptographic verification → policy change → new result with zero change to the calling agent → the old receipt still proving the old decision correctly.

*Still requiring a real ABSA integration:* a real UiPath/Maestro workflow actually pausing and branching (today only a simulated harness proves the contract); a real connection to one of ABSA's actual systems for a live fact (the framework will exist; the specific connector needs ABSA's own environment/credentials); the non-bypassable-enforcement question, if ABSA's security review requires it (Gap 6, deferred); and the data-residency/network-boundary questions the ABSA document itself already says need to be "resolved jointly, early" -- not something this codebase can answer unilaterally.

---

## D. Milestone plan

### Milestone A -- Authorization Receipts
**Definition of done:** a real endpoint returns a stable, named receipt for any decision, assembled entirely from existing Evidence/Decision/explanation data; verification is computed live, never stored; the historical-binding acceptance test (Gap 1) passes; website status updated only after this ships and is verified live, not before.

### Milestone B -- Authority Graph versioning
**Definition of done:** re-read `AuthorityGraphApproval`'s real schema first; confirm or extend it so each approval is a genuinely immutable, linked, diffable snapshot of resolved graph state; the versioning acceptance test (Gap 3) passes.

### Milestone C -- Authority Graph → Runtime Policy compilation gate
**Definition of done:** `promote_candidate` (or a thin wrapper around it) refuses to produce a draft policy when the candidate's referenced graph elements aren't resolved/active in the target approved version, with a structured diagnostic; a successful promotion carries real, queryable provenance back to the graph version and elements that justified it; the compilation acceptance test (Gap 2) passes.

### Milestone D -- Fact Resolver framework
**Definition of done:** a fact can be registered against an `EnterpriseSystem`, referenced in a policy condition as `facts.<key>`, validated at compile time by the extended vocabulary check, resolved live via a configured resolver (static for tests, generic HTTP for anything real), and fails closed to `HUMAN_REVIEW` on any resolution failure; the resolver and resolved value appear in the resulting receipt; the fact-resolution acceptance test (Gap 4) passes.

### Milestone E -- Input model review
**Definition of done:** an explicit written decision on whether `SubmitIntentRequest` needs any new structured fields (resource/resource_type/operation/scope/subject) for the reference demo, or whether existing `action`/`amount`/`context` are sufficient. Expected outcome, pending final review: no schema change needed for this demo; document the decision either way.

### Milestone H -- Orchestrator integration contract and simulated harness
**Definition of done:** a versioned integration contract document plus a passing test suite simulating an orchestrator's full lifecycle (submit, branch, poll-on-REVIEW, timeout/retry) against the real API, built on top of Milestones A-D so it's exercising genuine behavior.

### Not built this phase (documented decisions only)
- **F -- Enforcement contract / signed grant:** design note only.
- **G -- Human review continuation beyond polling:** design note only.
- **I -- Process chains:** not needed; no action.

---

**Waiting for explicit approval before writing any code**, per the instruction this plan was produced under. The order above (A, then B/D/E in parallel, then C, then H) is the recommended sequence; happy to reorder if a different starting point matters more for the actual next ABSA conversation.
