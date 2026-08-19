# PayReality vs. the ABSA Briefing: Product-to-Architecture Audit

**Status: audit only. No code was changed to produce this document. Every claim below traces to a specific file and line, verified directly against the real codebase, not inferred from names, comments, or filenames alone.**

**Method:** six independent research passes, each tracing one subsystem end to end through real code (not docs, not comments alone): Authority Intelligence/Authority Graph, Runtime Policy model and lifecycle, the Runtime Authority decision engine and fact resolution, Evidence/Authorization Receipt architecture, SDK/integration pattern, and policy-change/version-binding behavior. Findings below are synthesized from those six passes plus direct verification of the highest-stakes claims.

**The one instruction this whole document obeys:** the ABSA briefing is a contract already sent to a real prospect. This is not a redesign exercise. Every recommendation below extends or corrects what exists; nothing proposes rebuilding PayReality into a different kind of product.

---

## PART I -- What PayReality has promised Gavin

Extracted, material, checkable claims from the briefing:

1. A pipeline: Enterprise source material → Authority Graph → Runtime Policies → Runtime Authority → Approve/Reject/Review → Authorization Receipt → Evidence Portal.
2. Runtime Authority evaluates a proposed action **before it executes**, and "nothing today" does this check at the moment of action.
3. Decisions are deterministic; the same input produces the same output every time; a decision "can be inspected rule by rule."
4. **Zero LLM sits on the enforcement path.** AI is used once, offline, for extraction only.
5. Every decision produces a **signed Authorization Receipt**: actor, action, context, authority, policy version, rules evaluated, decision, approval/exception, outcome -- generated **as part of the decision itself, not reconstructed afterward**, cryptographically signed, independently verifiable.
6. **Fail-closed**: an unresolvable determination is routed to human review, never allowed by default.
7. Runtime Authority needs no customer PII -- only policy metadata (actor, action, amount/scope, policy/delegation).
8. A policy change (e.g. a threshold from R80,000 to R150,000) requires **only a new Runtime Policy version**, not a rebuild of the agent or workflow.
9. Decisions remain bound to **the exact policy version active when they occurred**, permanently, even after later policy changes.
10. A proposed integration pattern: a single call inserted into a Maestro-orchestrated UiPath step, which "pauses... until the call returns."
11. MuleSoft (or similar) is described as a data source an agent may call for external facts (e.g. a credit-bureau-style check) before proposing an action -- implying PayReality's own decision can also draw on enterprise facts like "supplier approved," "sufficient budget."
12. A sample Authorization Receipt (Appendix A) names specific fields as part of one decision: Agent, Action, Supplier, Amount, Authority, Policy, Conditions evaluated/passed/failed, Decision, **Approver** (a named role, e.g. "Payments manager"), Policy effective date, Receipt ID.
13. The POC's five test criteria: Translation, Authority, Enforcement, Change, Evidence.

---

## PART II -- What the product actually does today

Grounded in the six research passes, organized by subsystem. Full citations are in Part III's matrix; this section is the narrative summary.

**Runtime Authority (the decision engine) is real, deterministic, and fail-closed -- the strongest part of the product, and it matches the document closely.** `server/app/domain/decision/engine.py`'s `evaluate()` has an AST-enforced test (`test_architectural_boundaries.py`) proving it imports nothing from the database, services, or any LLM provider. Every failure branch (no active policy, OPA timeout, OPA error, an undetermined result) resolves to `HUMAN_REVIEW`, never a default `ALLOW`. Policy conflicts that could make two rules ambiguously match the same real request are rejected at **compile time** -- a policy that could double-match cannot become live at all.

**Evidence -- the real name for what the document calls "Authorization Receipt" -- is real, signed, and atomically bound to the decision.** ED25519 signing happens in the same database transaction as the decision itself, not as a follow-up step. Hash-chaining and a chain-verification endpoint are real. Historical Policy Binding is real, tested, and directly proves the exact scenario the ABSA document's Appendix A implies: a decision made under one policy version remains correctly, independently explainable and verifiable forever, even after the policy is changed twice more.

**Authority Intelligence extraction is real and produces genuinely structured, provenanced output -- but it does not compile into Runtime Policies the way the document describes.** Only one of its eight extracted categories (policy candidates, generated directly from the source text by the model) has a real path into a `RuntimePolicy`, and that path is human-triggered, not automatic compilation from the graph's structural elements (principals, relationships, limits, conflicts).

**Runtime Policies are flat, single-step, AND-only rules -- there is no process-chain, multi-stage, or sequential-approval concept anywhere in the codebase.** This was independently confirmed to a very high degree of certainty. Rollback creates a new draft rather than reactivating history directly, by deliberate design.

**PayReality is a queried decision service, not an execution gate.** No proxy, capability token, or execution-blocking mechanism exists anywhere. Whether an action is actually gated depends entirely on the calling integration choosing to call `authorize()` first and choosing to respect the answer.

**No live enterprise-fact resolution exists.** "Is this supplier approved," "is there sufficient budget" -- nothing in the codebase calls out to an external system to check either. This was independently confirmed from two different angles (the decision-engine trace and the integration trace), and the code says so of itself in its own docstrings.

**There is no UiPath- or Maestro-specific code anywhere.** The proposed integration pattern is generic and has never been built or tested against either platform by name.

---

## PART III -- Capability matrix

Legend: **WORKING** / **PARTIALLY WORKING** / **FOUNDATION EXISTS** / **MISSING** / **CONTRADICTS CURRENT ARCHITECTURE**

### AUTHORITY INTELLIGENCE

| Capability | Status | Evidence | Gap | Change type |
|---|---|---|---|---|
| Governance document ingestion/extraction | **WORKING** | `server/app/domain/ai_authority_builder/provider.py:126-138`; real Claude/Azure Foundry providers plus a disclosed fake fallback | None functional; live-AI-vs-fake status per environment is a separate, already-tracked backlog item | -- |
| Actors, roles, delegated authority | **WORKING** | `CandidatePrincipal`/`CandidateRelationship`, `provider.py:24-79` | None | -- |
| Thresholds, conditions, exceptions | **PARTIALLY WORKING** | Only the `policies` category (`CandidateRuntimePolicy`, reused from `ai_policy_builder`) carries scope/conditions/effect; the graph-structural categories carry none | Thresholds/conditions live in a parallel, document-read-directly path, not synthesized from the graph's own structure | Documentation clarity, or new extraction logic if literal graph→condition synthesis is wanted |
| Approval relationships | **WORKING** (as delegation links only) | `CandidateRelationship.kind` (`delegation`/`escalation`/`inheritance`), `db/models.py:1192-1195` | Carries no threshold/amount -- a delegation link, not an approval-limit record | -- |
| Provenance | **WORKING** | `source_excerpt`/`source_location`/`clause_reference`/`extraction_reasoning` are real DB columns, `db/models.py:1063-1082` | None | -- |
| Human validation before use | **WORKING** | `resolve_principal`/`resolve_relationship`/`activate_relationship`/`promote_candidate`, all `AUTHORITY_REVIEW`-gated | None | -- |
| Version history of one graph's content over time | **MISSING** | No re-extraction endpoint exists for a corpus; what versions is the approval-audit-trail (`AuthorityGraphApproval.version`) and cross-corpus diffing, not one graph's content evolving | A corpus is extracted once; there's no "re-run extraction, see what changed" loop | New component if wanted |

### AUTHORITY GRAPH

| Capability | Status | Evidence | Gap | Change type |
|---|---|---|---|---|
| Canonical representation of actors/relationships | **WORKING** | `AuthorityGraph` dataclass, 8 categories, `provider.py:126-138` | None | -- |
| Compiles into Runtime Policies | **CONTRADICTS DOCUMENT'S FRAMING** | No `compile_from_graph` function exists anywhere (confirmed by exhaustive grep). Only policy candidates (extracted directly from text, not from the graph's own structure) can become a draft policy, via human-triggered `promote_candidate` | The document's "Authority Graph compiles into Runtime Policies" describes a mechanism that doesn't exist; what exists is a human manually authoring/promoting policy, informed by having read the graph | This is the single most consequential finding in this audit -- see Part V |
| Graph queried live at decision time | **CONTRADICTS DOCUMENT'S IMPLICATION** | Only the fully-resolved-and-activated subset of relationships (a separate "Authority Model" table, not the raw graph) ever reaches a live decision, and only as enrichment context, never as policy logic | The Authority Graph itself is purely an authoring-time artifact | Documentation correction; matches the platform's own internal glossary already |
| Effective dates / version-bound graph state | **FOUNDATION EXISTS** | Policy-level historical binding is real and strong (Part VIII); graph-level version history is not (see above) | -- | -- |

### RUNTIME POLICIES

| Capability | Status | Evidence | Gap | Change type |
|---|---|---|---|---|
| Deterministic representation, versioned, compiled | **WORKING** | `compiler_v2.py`, `bundle_builder.py`; one Rego rule per policy, one bundle per organization | None | -- |
| Full lifecycle (draft → review → approve → compile → active → retire) | **WORKING** | `runtime_policy_service.py`, `runtime_policy_lifecycle_service.py`; every transition guarded | None | -- |
| Rollback | **WORKING, by deliberate design** | Creates a new draft (`rollback_policy`, `dataclasses.replace(..., status=DRAFT)`), never reactivates history directly | None -- this is a feature, not a bug, but worth stating precisely if asked | -- |
| Scheduled activation/retirement | **PARTIALLY WORKING** | Real rows, real endpoints; `process_due_schedules` exists but nothing calls it automatically -- "there is no task runner anywhere in this platform," per the function's own docstring | Needs an external cron/trigger; none exists today | Extension (a scheduled job, or document as an operational dependency) |
| Relationship to flat policies / process chains | **See Part VII** | -- | -- | -- |
| Compile-time ambiguity rejection | **WORKING** | `_policy_conflicts`, real interval-overlap proof, blocks a policy from ever going live if it could double-match | None | -- |

### RUNTIME AUTHORITY

| Capability | Status | Evidence | Gap | Change type |
|---|---|---|---|---|
| Pre-execution interception | **PARTIALLY WORKING / DEPENDS ENTIRELY ON INTEGRATION** | No proxy/capability-token/execution-block exists anywhere; `authorize()` is a voluntarily-called opinion service | PayReality cannot itself prevent a non-compliant caller from acting regardless of the answer | See Part V -- this needs precise, honest framing, not a code fix |
| Actor / action / resource / amount | **WORKING** | `SubmitIntentRequest`, real fields | None | -- |
| Contextual facts (internal) | **WORKING** | `authority_context_service.py`; org/department/team/role/delegation | None | -- |
| Contextual facts (external enterprise systems) | **MISSING** | `enterprise_system_service.py`'s own docstring: "no connector code exists for any row here"; confirmed independently by two research passes | No live fact resolution against any external system exists at all | New component (a real connector framework) -- explicitly out of scope for now, see Part XII |
| Deterministic evaluation | **WORKING** | AST-enforced import-boundary test | None | -- |
| APPROVE / REJECT / REVIEW | **WORKING** | `engine.py:141-175`, exact mapping confirmed, contradictory allow+deny resolves to DENY | None | -- |
| Fail-closed | **WORKING** | Every branch confirmed; three distinct fail-closed layers (unrecognized action, no active policy, zero matching policies) | None | -- |
| Human escalation | **PARTIALLY WORKING** | Real resolve endpoint, real service; resolution never re-consults policy (correct), but there is no push/callback to the calling system -- the caller must poll | The "Maestro pauses until Approve/Reject/Review" framing implies REVIEW is also a wait state; it isn't -- `authorize()` returns REVIEW immediately, and resuming a paused workflow after a human resolves it is not built | Extension: a webhook/callback, or explicit documentation that REVIEW requires the caller to poll |
| Policy version selection | **WORKING** | Fully automatic, server-side, scope-based; caller never specifies a policy id | The document's phrase "carrying... the relevant policy reference" is not literally accurate -- no caller-supplied reference is needed or supported | Documentation correction |

### EVIDENCE

| Capability | Status | Evidence | Gap | Change type |
|---|---|---|---|---|
| "Authorization Receipt" as a named, shipped concept | **CONTRADICTS CURRENT ARCHITECTURE -- AND THE COMPANY'S OWN WEBSITE** | No backend model/table named this exists. The live, deployed marketing website itself labels this "Coming Soon" / "Planned Architecture" on both its product and developer pages, stating explicitly: "Runtime Authority's decision engine and the Evidence Portal are live today; Authorization Receipts are how that evidence evolves." | The company's own public site directly contradicts presenting this as shipped to a real prospect | **Top priority -- see Part V** |
| The substance behind the name (signed record with the claimed fields) | **WORKING**, under the name "Evidence" | `Evidence.payload` genuinely carries actor/action/context/authority/policy version/matched rules/outcome/approval data | Organized as free-form JSON, not a dedicated receipt schema; missing the self-contained/offline/transparency-log properties the website itself says receipts are specifically being built to add | Extension, not replacement, if literal "receipt" branding + those properties are wanted |
| Atomic signing at decision time | **WORKING** | Same DB transaction as the Decision row, confirmed, no async gap | None | -- |
| Tamper evidence / chain verification | **WORKING** | Hash-chaining real; `chain/verify` checks both signature and continuity | Endpoint is authenticated/org-scoped, not the credential-free third-party verification the document's "independently verified" phrasing could imply | Documentation precision, or a future public verification surface |
| Policy-version binding | **WORKING, tested, exactly the claimed scenario** | `test_historical_policy_binding.py`, `test_decision_explanation.py` -- two decisions under two different policy versions each remain independently, correctly explainable forever | None | -- |
| Per-condition breakdown as part of the signed artifact | **PARTIALLY WORKING** | The signed Evidence payload carries which rules matched, not a full per-condition pass/fail breakdown; that granular explanation is correctly reconstructed on demand via `decision_explanation_service`, not baked into the original signature | If the sample receipt's "Conditions evaluated: 4, passed: 3" is expected to be part of the signed document itself (not a separately-callable, provably-correct reconstruction), that's not built | Extension, if wanted |
| Named required approver (e.g. "Payments manager") at decision time | **MISSING** | No evidence found of a policy-level "required approver role" field; review resolution records who approved only after the fact | The sample receipt's "Approver: Payments manager" field is not something the system can determine at decision time from policy alone today | New, small field on RuntimePolicy/constraints, if wanted |
| Key rotation | **WORKING** | Real multi-key registry, old keys independently retrievable | None | -- |

### INTEGRATION

| Capability | Status | Evidence | Gap | Change type |
|---|---|---|---|---|
| API-based enforcement | **WORKING, as an opinion API** | Real `POST /v1/intents` | See Runtime Authority row above for the gating nuance | -- |
| SDK, synchronous pre-action pattern | **WORKING** | `Agent.authorize()`, real blocking HTTP call, matches the "pause until it returns" pattern architecturally | None for this pattern itself | -- |
| UiPath-compatible integration | **MISSING (as a named, tested integration)** | Zero UiPath/Maestro references anywhere in the codebase, confirmed by exhaustive grep | The proposed pattern is generic and unbuilt against either platform specifically | New integration work, first proof point being exactly the proposed POC |
| External fact retrieval | **MISSING** | Same finding as Runtime Authority's external-facts row | -- | -- |
| Enterprise connectors | **MISSING** | `enterprise_systems` is a static label only | -- | -- |

### CHANGE MANAGEMENT

| Capability | Status | Evidence | Gap | Change type |
|---|---|---|---|---|
| Policy changes without touching the calling agent | **WORKING** | Policy lookup is fully server-side by organization; caller's request never references a policy | None | -- |
| Validation / approval / activation | **WORKING** | Full lifecycle, safety-checked before activation | None | -- |
| Version history / rollback | **WORKING** | Every version permanently retained; rollback creates a fresh draft | None | -- |
| Old vs. new policy behavior | **WORKING** | Confirmed: activating v2 changes the very next identical call's outcome, zero caller change | None | -- |
| In-flight decisions during a policy change | **PARTIALLY WORKING (code-verified, not test-verified)** | Resolution never re-consults policy state, so a HUMAN_REVIEW decision awaiting resolution is unaffected by a later policy change -- but no dedicated regression test exists for this composed scenario | Add a test; behavior itself already appears correct | Test only |
| Evidence binding to policy version | **WORKING, tested** | See Evidence row above | None | -- |

---

## PART IV -- Existing architecture we should preserve

Everything in this list is production-quality, well-tested, and should not be touched except by extension:

- `domain/decision/engine.py` -- the deterministic core. Architecturally the most defensible part of the whole platform; the AST-enforced import-boundary test is a genuinely strong guarantee, not just a comment.
- `domain/compiler_v2/` -- Rego compilation, compile-time conflict detection, per-organization bundle isolation.
- `domain/evidence/signing.py` and the whole Evidence chain/rotation mechanism.
- `runtime_policy_lifecycle_service.py` -- the full draft→active state machine, safety checks, and (deliberately) non-destructive rollback.
- `decision_explanation_service.py` and Historical Policy Binding -- this is the single strongest, most directly-provable claim in the entire ABSA document, and it already works exactly as described.
- The AI Authority Builder's provenance model (source_excerpt/clause_reference/extraction_reasoning) -- genuinely more rigorous than most competitors' extraction tooling, and should be the foundation for anything built next, not replaced.
- Multi-tenant isolation (per-org OPA package, per-org policy rows).

---

## PART V -- Critical gaps, ranked by what matters most to ABSA's own stated concerns

**1. "Authorization Receipt" is presented to a real prospect as shipped, while PayReality's own live website calls it "Coming Soon."** This is not an engineering gap -- it's a live business/credibility risk, and it exists *today*, independent of anything else in this audit. ABSA's security and architecture reviewers are exactly the kind of audience who checks a vendor's own public claims against what a salesperson said. This should be resolved before any further engineering work, by one of: (a) correcting the ABSA-facing narrative to describe **Evidence**, honestly, using its real capabilities (which are substantial and mostly match the document's *substance*, just not its *name* or its not-yet-built portability features), or (b) if the "Authorization Receipt" name and self-contained/offline-verifiable framing is commercially important, treat closing that specific gap as a real, scoped priority (see Part X) rather than continuing to describe it as already true.

**2. The Authority Graph does not compile into Runtime Policies.** This is the second-most consequential finding because it's the document's own headline pipeline diagram. What's real: a human reads the graph, and (separately) an AI-extracted policy candidate -- generated directly from the same source text, not from the graph's structure -- can be promoted into a draft policy through a real, human-gated workflow. For the ABSA demo's own proposed scenario (a flat R80,000 threshold with an approval requirement), this is very likely *sufficient in practice*, since a flat-threshold RuntimePolicy is exactly what the existing candidate-extraction-and-promotion path already produces well. The gap matters most if ABSA's own technical evaluators specifically probe "show me the graph turning into a policy" as a mechanism, not just an outcome.

**3. PayReality does not gate execution; it answers a question a caller must choose to ask and choose to respect.** This is architecturally sound and consistent with a "decision service, not a proxy" design (many good systems work this way -- this is not inherently a weakness), but it must be stated precisely to ABSA's security/architecture reviewers, who the document itself says will specifically ask "what happens if Runtime Authority cannot be reached" -- the honest, complete answer is that the entire enforcement guarantee lives in the calling workflow's own discipline, and PayReality has no independent mechanism to detect or stop a non-compliant caller.

**4. No live enterprise-fact resolution exists.** The Appendix A sample receipt's "Supplier: Approved supplier" field, if meant to represent a fact PayReality itself verified, isn't something the system can do today -- it would have to be self-reported by the caller (unverified) or built as a new connector. This is squarely the subject of the platform's own unimplemented "Enterprise Knowledge Resolution" research direction, not a small fix.

**5. REVIEW is not a genuine pause-and-resume state today.** `authorize()` returns HUMAN_REVIEW immediately; there is no mechanism for PayReality to later tell the calling workflow "you may now proceed." For the "Maestro pauses... until the call returns" framing to be literally true for the REVIEW outcome (not just ALLOW/DENY), either the calling integration must poll, or a callback mechanism needs to be built.

**6. No background scheduler exists.** Scheduled activation/retirement rows are real but inert unless something external triggers `process_due_schedules`. Low severity, easy fix, but relevant to the "Change" POC criterion if ABSA's own review timeline depends on scheduled cutovers.

---

## PART VI -- Target architecture

The smallest coherent evolution that makes the document's claims true, without rebuilding anything:

```
Enterprise source material
        |
        v
AI Authority Builder (unchanged) --extracts--> Authority Graph
        |                                            |
        | (policy candidates, already real)          | (principals/relationships,
        v                                             |  already real, human-resolved)
  promote_candidate (already real)                    v
        |                                    Authority Model (already real:
        v                                     resolved delegation edges)
  Draft RuntimePolicy                                 |
        |                                             | (enriches context only,
        v (submit/approve/compile/activate,           |  never generates conditions --
        |  all already real)                          |  unchanged, this is correct
        v                                              |  and should stay this way)
   Active RuntimePolicy <---------------------------- (context.authority.*)
        |
        v
Runtime Authority (decision engine, unchanged, already correct)
        |
        v
  APPROVE / DENY / HUMAN_REVIEW
        |
        v
  Evidence (rename/re-badge as "Authorization Receipt" only if that
  commercial decision is made deliberately -- see Part X)
```

The only genuinely new component this target architecture implies (beyond documentation/positioning fixes) is: a real, scoped decision on whether to (a) build the specific missing pieces named in Part V items 4-6, and/or (b) close the naming/positioning gap in items 1-2 through corrected messaging rather than new code. Both are legitimate answers; Part X sequences them by dependency and risk, not by assuming the answer.

---

## PART VII -- Relationship between Flat Policies, Process Chains, Authority Graph, and Runtime Policies

**Direct answer to the question this audit was specifically asked to resolve: process-chain policies do not exist in this codebase.** `ConditionSet` supports only a flat `all` (AND) grouping -- no `any`, no nesting, no sequence, no stage field anywhere in the domain model, database schema, or compiler. This was confirmed with very high confidence (an exhaustive grep for every plausible term, checked line by line). The only prior mention of a "process-chain" model is a recorded brainstorming conversation about a *possible future evolution* -- it was never built, and nothing in the current code should be read as an early version of it.

**So the real relationship is:**

- **Flat policies (RuntimePolicy) are the only policy primitive that exists.** Every RuntimePolicy is one scope match plus a flat AND of conditions, producing one of ALLOW/DENY/REQUIRE_HUMAN_REVIEW.
- **The Authority Graph is not "compiled into" Runtime Policies as a graph-to-graph transformation.** It's a discovery/review artifact. One narrow slice of it (AI-extracted policy candidates, generated directly from source text) has a real, human-gated promotion path into a draft RuntimePolicy. The rest (principals, relationships, conflicts, resources, operations, gaps) either has no code bridge to enforcement at all, or (for resolved, activated delegation relationships specifically) enriches the *context* a policy's own conditions can reference, but never generates or edits a condition itself.
- **The correct target architecture is closer to option A the audit brief named, with a correction:** *Authority Graph → (human-reviewed, partially AI-assisted) → RuntimePolicy → Runtime Authority* -- not a literal automatic compilation, and not a process-chain intermediate step, because process chains don't exist and building one now would be exactly the kind of premature, un-signaled-for expansion this platform's own prior internal audits have repeatedly warned against.
- **For ABSA's specific demo scenario** (a flat threshold + a review requirement), the existing flat-policy model is fully sufficient -- there is no need to build any multi-step primitive to satisfy the document's own proposed proof-of-concept. The place a genuine multi-step/sequential-approval need might arise is if a *future* customer's SOP has a real, ordered, multi-stage approval chain (e.g. "first Finance, then Legal, then CFO") that a single flat RuntimePolicy genuinely cannot express -- that need has not yet appeared in any real customer conversation on record, and per this platform's own standing engineering discipline, should not be built ahead of that real signal.

---

## PART VIII -- Evidence / Authorization Receipt architecture

**What's real today, under the name Evidence:**
- One ED25519-signed record per decision (plus one additional chained record per human resolution), created in the same database transaction as the decision itself -- genuinely atomic, not reconstructed after the fact.
- A hash-chain (`previous_hash`) providing tamper evidence across the whole sequence of a organization's evidence records, with a real chain-verification endpoint checking both signature validity and chain continuity.
- Permanent, exact historical policy binding: `Policy.bundle_manifest` plus never-mutated `RuntimePolicyRecord` rows let any past decision be correctly re-explained against the *exact* policy that governed it, forever, proven by tests that redeploy a policy twice more and confirm the original explanation never drifts.
- Multi-key signing history, so a record signed under a since-rotated key remains independently verifiable.
- A public, credential-free endpoint for the current and historical signing public keys (for genuine offline verification of signatures specifically).

**What's not real, and is the company's own disclosed roadmap, not this audit's invention:**
- A dedicated, portable, self-contained "Authorization Receipt" artifact distinct from an API call into Evidence.
- Credential-free, third-party verification of a *specific record's full content* (today's `chain/verify` requires the caller's own organization credentials).
- A public, append-only transparency log (the website's own "planned architecture" language for this).
- A per-condition pass/fail breakdown baked into the signed artifact itself, rather than correctly reconstructed on demand.
- A policy-declared "required approver" surfaced at decision time, rather than recorded only once a human actually resolves the review.

**Recommendation:** the underlying mechanism (Evidence) is strong enough that closing the naming/packaging gap is a real but bounded piece of work -- not a new cryptographic system, just an export/presentation layer over what already exists, plus (if wanted) the two small structural additions above (per-condition detail in the signed payload; a required-approver field). This should be scoped as its own, explicitly-named phase (Part X, Phase 2), not folded silently into "fix the messaging."

---

## PART IX -- End-to-end reference flow

Mapped against what's real vs. what needs building, using the document's own proposed scenario (Payments Agent, R80,000 threshold, Payments Manager review above it).

| Step | Real today? | Evidence |
|---|---|---|
| Source governance ingested | Yes | AI Authority Builder |
| AI extracts a candidate policy with the R80,000 threshold | Yes | `CandidateRuntimePolicy`, extracted directly from the SOP text |
| Human validates the candidate | Yes | `AUTHORITY_REVIEW`-gated promotion workflow |
| Authority Graph represents delegation/roles | Yes, as a separate concept from the promoted policy | Principals/relationships resolve independently |
| Runtime Policy compiled from the candidate | Yes | `promote_candidate` → draft → submit → approve → compile |
| Policy version becomes active | Yes | `deploy_policy`, full lifecycle |
| Agent proposes the action | Yes | SDK `authorize()`, real signed request |
| Runtime Authority intercepts before execution | **Only if the calling integration is built to wait for and respect the answer -- PayReality itself cannot enforce this** | Part V, finding 3 |
| Enterprise facts resolved (supplier approved, budget sufficient) | **No** | Part V, finding 4 -- would need to be self-reported by the caller today |
| Deterministic evaluation | Yes | `engine.py`, AST-enforced isolation |
| R50,000 + approved supplier + budget → APPROVE | Yes, if "approved supplier"/"budget" are supplied by the caller as already-known facts, not independently verified | -- |
| R95,000 → REVIEW, naming "Payments Manager" specifically | **Partially** -- REVIEW fires correctly; a specific named required-approver is not determined by policy today | Part V, finding 1 (Evidence matrix) |
| R50,000 + unapproved supplier → REJECT | **Only if "unapproved" is a fact the caller supplies** -- PayReality cannot independently check supplier approval | Part V, finding 4 |
| Unknown/unresolvable authority → fail closed | Yes | Three independently-confirmed fail-closed layers |
| Threshold raised to R150,000, new version activated, no agent rebuild | Yes | Confirmed, server-side automatic policy lookup |
| Decision A (v1) and Decision B (v2) both independently verifiable | Yes, tested exactly this way | `test_historical_policy_binding.py`, `test_decision_explanation.py` |

**Bottom line: the policy/versioning/evidence half of this flow is genuinely solid and already proven. The two real gaps are (a) PayReality cannot itself verify external facts like supplier-approval or budget-sufficiency, and (b) PayReality cannot itself force a calling workflow to respect its answer -- both need to be either built or explicitly scoped out of what a POC claims to prove.**

---

## PART X -- Implementation phases

Ordered by dependency; each phase is additive, not a rewrite.

### Phase 0 -- Immediate: correct the live commercial risk (no engineering, or trivial engineering)

**Objective:** stop presenting "Authorization Receipt" as shipped when the company's own website says otherwise.
**Why it exists:** this is the one finding in this audit that's already a live risk, independent of any further work.
**Reuse:** nothing changes technically; this is a messaging/positioning decision.
**Options:** (a) in any follow-up ABSA conversation, describe the real system as "Evidence," honestly, using its real capabilities; or (b) explicitly scope Phase 2 below as the real fix and disclose it as in-progress, not shipped.
**Dependencies:** none. **Risk of not doing this:** reputational, with the exact audience (a security/architecture review) most likely to check.

### Phase 1 -- Documentation correction, zero code change

**Objective:** make every internal and external description of the Authority Graph → Runtime Policy relationship match what the code actually does (Part VII).
**Components touched:** none (docs/messaging only).
**Definition of done:** no live document claims automatic graph-to-policy compilation; the real human-gated promotion path is described accurately.
**Risk:** none -- pure correction.

### Phase 2 -- Evidence → Authorization Receipt packaging (only if the name/portability commercially matters)

**Objective:** close the gap between the company's own "planned architecture" and a real shipped artifact.
**Reuse:** the entire Evidence/signing/chain-verification stack, unchanged.
**New components:** an export endpoint producing a self-contained, portable receipt document from an existing Evidence record plus its historically-bound policy explanation (already provably correct -- Part VIII); optionally, a public transparency-log surface if credential-free third-party verification is wanted.
**Data model changes:** none required for the core case; optional additive fields (per-condition detail already reconstructible, just needs embedding at export time) rather than new tables.
**Tests required:** the export must reproduce byte-for-byte the same historical explanation `decision_explanation_service` already proves is correct.
**Definition of done:** a receipt exported for a decision made under a policy that has since changed twice more still shows the original values, matching the existing historical-binding tests' own assertions.
**Dependencies:** none technically; commercially gated on whether ABSA (or any prospect) actually needs the portability/offline properties, or whether "Evidence Portal, honestly described" is sufficient.

### Phase 3 -- Named required-approver on a policy (small, optional)

**Objective:** let a RuntimePolicy declare which role must resolve its REVIEW outcome (e.g. "Payments Manager"), so a receipt can state this at decision time, not only after resolution.
**Components touched:** `RuntimePolicyRequest`/`RuntimePolicyRecord` schema (an additive `required_approver_role` field on `constraints`, matching the existing pattern for `risk_level`/`delegated_by`), Compiler V2's review-reason generation (already emits a reason string; extend to include the role), Evidence payload (thread the field through).
**Migration:** additive column, nullable, matching this codebase's established migration convention.
**Tests:** a policy with a required-approver role produces a REVIEW decision whose Evidence names that role.
**Risk:** low -- purely additive.

### Phase 4 -- REVIEW as a real pause-and-resume state (only if literal Maestro-pause behavior for REVIEW specifically is required)

**Objective:** let a calling workflow actually resume after a human resolves a review, instead of polling.
**New component:** a webhook/callback registered at `authorize()` time, called from `resolution_service.resolve_decision` once resolution completes.
**Risk:** medium -- this is the one phase that adds a genuinely new capability class (outbound calls from PayReality to a customer's system), and should be scoped carefully (retry semantics, security of the callback URL, etc.) rather than added casually.
**Dependencies:** none on the phases above; can run in parallel.

### Phase 5 -- Scheduled-policy-change automation (small)

**Objective:** make `process_due_schedules` actually run without a human remembering to trigger it.
**New component:** a scheduled job (the same category of gap the platform's own backlog already tracks for other cron-shaped needs -- this should likely be solved once, generically, not per-feature).
**Risk:** low.

### Explicitly not phased here: external enterprise-fact resolution (Part V finding 4)

This is a real, substantial gap, but building a generic connector framework is exactly the kind of larger, not-yet-signaled-for expansion this audit's own instructions warn against pursuing speculatively. If ABSA's actual POC needs a specific fact (e.g. "is this supplier on the approved list"), the narrowest correct move is a single, scoped connector for that one fact, built against that one real need when the POC reaches it -- not a general framework built ahead of any confirmed requirement.

---

## PART XI -- Acceptance tests

Several of these already exist and pass; they're listed here to show the full contract, not to imply all are new work.

1. **Policy versioning test -- ALREADY PASSING.** `test_historical_policy_binding.py`, `test_decision_explanation.py`: given policy v1 (threshold R80k), a R95k request resolves REVIEW; given v2 (threshold R150k) becomes active, the same R95k request now resolves APPROVE; the two decisions' receipts each remain correctly bound to their own policy version, forever.
2. **Evidence integrity test -- ALREADY PASSING.** Modifying any signed field of an Evidence record fails verification (`evidence_service.verify_evidence`, exercised by existing tests).
3. **Fail-closed test -- ALREADY PASSING.** No active policy, an OPA timeout, an OPA error, or an undetermined result all resolve to HUMAN_REVIEW, never ALLOW (`test_decision_engine.py`).
4. **LLM separation test -- ALREADY PASSING (as an architectural guarantee, not a runtime feature test).** `test_architectural_boundaries.py`'s AST-based import check proves the decision engine cannot reach an LLM provider even if one were unavailable, since it never imports one -- a stronger guarantee than a runtime "the extraction service is down" test would be, and already covers the intent of this acceptance criterion.
5. **Human review test -- ALREADY PASSING for the resolution half; NOT YET BUILT for the "identifies the required approver" half.** Given an action requires escalation, Runtime Authority returns REVIEW (confirmed); it does not yet identify a specific required approver from policy (Phase 3 above would close this).
6. **NEW -- Authorization Receipt honesty test (Phase 0/1).** No live customer-facing document or page describes "Authorization Receipt" as shipped without the same disclosure the company's own website already carries, until Phase 2 actually ships it.
7. **NEW -- Enterprise fact test (only relevant once/if Phase-beyond-this-audit work on external facts begins).** Given a policy condition references a fact this platform cannot resolve, the decision fails closed to REVIEW, never a false ALLOW based on an unverified caller-supplied claim. (Today, this is trivially true because no such condition type can exist yet -- worth re-asserting explicitly once/if it does.)
8. **NEW -- Integration non-compliance test.** Document explicitly, for ABSA's own architecture reviewers, what happens if a calling workflow calls `authorize()`, receives DENY or REVIEW, and proceeds anyway: nothing in PayReality detects or prevents this today. This isn't a test PayReality's own code can pass or fail -- it's a fact that must be disclosed, matching the platform's own standing "never hide a gap" discipline.

---

## PART XII -- What NOT to build yet

- **No process-chain / multi-step policy primitive.** Nothing in any real customer conversation on record requires it; the flat model is sufficient for the ABSA scenario as proposed.
- **No general enterprise-connector framework.** Build the one connector a real POC actually needs, if and when it needs it -- not a platform for hypothetical future connectors.
- **No automatic Authority-Graph-to-policy compiler for the structural categories** (principals/relationships/conflicts synthesizing conditions programmatically). The existing human-gated, text-extraction-based promotion path is sufficient for the proposed scenario; building automatic synthesis now would be solving a problem no real customer has asked for yet.
- **No rebrand of the whole Evidence system into "Authorization Receipts" without a deliberate decision** -- see Phase 0/2's explicit either/or framing. Don't let a naming change happen as an unplanned side effect of something else.
- **No UiPath/Maestro-specific SDK or adapter before a real POC exists to build it against.** Building integration code speculatively, before a real customer's real workflow exists to test it against, is exactly the premature-build pattern this platform's own history has repeatedly warned against.

---

## PART XIII -- Risks / unresolved architectural decisions

1. **Commercial decision needed, not an engineering one: does "Authorization Receipt" as a distinct, portable artifact matter enough to ABSA (or the broader market) to justify Phase 2, or is "Evidence, honestly described" sufficient?** This audit cannot answer this -- it's a product/positioning call for whoever owns that decision.
2. **How literally must "before it executes" hold for ABSA's specific security review?** If their architecture team requires PayReality to structurally prevent a bypass (not just answer a question a well-behaved caller asks), that is a materially larger scope than anything in this codebase today, and should be raised as an explicit question back to Gavin/ABSA's architecture team rather than assumed either way.
3. **Which enterprise fact(s), if any, does the actual POC scenario require PayReality to verify itself, versus accept as caller-supplied?** This determines whether Phase-beyond-this-audit connector work is needed at all for the chosen POC process.
4. **Does the chosen POC process need a named required-approver at decision time**, or is post-hoc resolution (already real) sufficient? Determines whether Phase 3 is needed.
5. **Does the "Maestro pauses... until the call returns" framing need to hold literally for REVIEW, or only for ALLOW/DENY?** Determines whether Phase 4 is needed.

---

## PART XIV -- Definition of "Gavin-ready", checked against the document's own 18-point list

| # | Requirement | Status |
|---|---|---|
| 1 | Enterprise governance enters the system | **Real** |
| 2 | Authority extracted with provenance | **Real** |
| 3 | A human can validate it | **Real** |
| 4 | Organizational authority represented structurally | **Real** (Authority Model, distinct from the Graph -- Part III) |
| 5 | Deterministic Runtime Policies created | **Real**, via human-gated promotion, not automatic graph compilation |
| 6 | An agent proposes a consequential action | **Real** |
| 7 | PayReality intercepts it before execution | **Real only if the integration is built to wait and respect the answer -- not independently enforceable** (Part V.3) |
| 8 | Required enterprise facts are evaluated | **Not real for external facts** (Part V.4) -- real only for internal org-chart/role facts |
| 9 | Runtime Authority returns APPROVE/REJECT/REVIEW | **Real** |
| 10 | No LLM makes the authorization decision | **Real, and unusually strongly proven** (AST-enforced test) |
| 11 | The action cannot bypass the authority result | **Not real** -- nothing prevents a non-compliant caller from proceeding anyway (Part V.3) |
| 12 | An Authorization Receipt is generated | **Real in substance, under the name Evidence -- not real under that name or with its planned portability properties** (Part V.1) |
| 13 | The receipt is cryptographically verifiable | **Real** |
| 14 | The receipt proves which authority/policy version produced the decision | **Real, tested** |
| 15 | A governance change can create a new policy version | **Real** |
| 16 | New actions follow the new version without changing the calling agent | **Real, tested** |
| 17 | Historical receipts remain bound to the authority that existed when they occurred | **Real, tested -- the strongest claim in the whole document, and it holds up exactly as described** |
| 18 | The Evidence Portal allows inspection/verification of this history | **Real** |

**13 of 18 are genuinely real today. 5 need an explicit decision (not necessarily a build): items 7 and 11 are the same underlying architectural characteristic (a decision service, not an enforcement gate) and need honest framing more than new code; item 8 needs a scoping decision about which specific fact the actual POC requires; item 12 needs a naming/positioning decision; item 9's REVIEW sub-case (pause-and-resume) needs a decision about whether literal pausing is required.**
