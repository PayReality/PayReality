# PayReality: POC Readiness Report

**Status: current as of Milestone 17.1 (POC Readiness Remediation), 2026-08-25.** This document is the honest boundary between what exists and what does not. Every claim below is checked against the actual code and test results in this repository, not the aspiration in any planning document. Status labels used throughout: **LIVE** (real, shipped, exercised by passing tests), **VERIFIED** (a specific test count/result backing a LIVE claim), **REFERENCE ONLY** (a real, working artifact built explicitly to prove a mechanism, not a production integration), **NOT BUILT**, **OPEN QUESTION**, **RECOMMENDED** (a follow-up named but not implemented).

---

## 1. Runtime Authority

**LIVE:**
- Deterministic decision engine (`domain/decision/engine.py`): `ALLOW`/`DENY`/`HUMAN_REVIEW`, zero LLM/DB/service imports (architectural-boundary tests prove this, not convention).
- Policy compilation (Compiler V2): vocabulary validation, compile-time conflict/ambiguity rejection, never a runtime surprise.
- Policy versioning: immutable `RuntimePolicyRecord` rows, one per version, never mutated.
- Historical Policy Binding: a decision made under policy v1 stays correctly explainable against v1 forever, independent of later changes.
- Fail-closed semantics: every ambiguous or unresolved branch (`no_active_policy`, `opa_timeout`, `opa_error`, `undetermined`) resolves to `HUMAN_REVIEW`, never a default `ALLOW`.
- **Scope.agent narrowing** (fixed this milestone): a policy authored to apply only to a specific Agent now actually discriminates between that agent and any other. Previously silently inert for every organization since the feature was introduced -- see Section 7.

**VERIFIED:** full backend suite passing -- **491 passed, 0 failed, 0 skipped** (up from 484 before this milestone, the +7 being exactly the new `test_scope_agent_authorization.py` tests). The dedicated `test_scope_agent_authorization.py` (7 tests) and the pre-existing `test_decision_engine.py`, `test_rego_generator.py`, `test_compiler_v2.py` (55 tests) all pass together, confirming the fix introduced no regression to any pre-existing decision, compiler, or Rego-generation behavior.

## 2. Authority Intelligence

**LIVE:**
- Candidate extraction from governance documents (Authority Graph, AI Authority Builder / AI Policy Builder pipelines) -- produces `PolicyExtractionCandidate`/discovery rows, never a live authority on its own.
- Human promotion/validation: `promote_candidate` is the only code path that turns a candidate into a real, enforceable draft `RuntimePolicy`. No candidate is ever auto-promoted.
- Compile-time conflict/ambiguity handling: Compiler V2 rejects two policies that could jointly match the same real Intent, and rejects a condition field that isn't in the active vocabulary.

**NOT BUILT / explicitly not claimed live:** any AI functionality beyond candidate proposal and human-gated promotion. The LLM never independently resolves a conflict, never creates authority on its own, and is architecturally excluded from the runtime decision path.

## 3. Trusted Enterprise Facts

**LIVE:**
- Registered fact sources (`FactSource`), Ed25519 key registration, active/revoked lifecycle.
- Signed fact ingestion (`fact_service.ingest_fact`), canonical attestation payload binding organization, source, subject, key, value, timestamps, and nonce.
- Mandatory expiry -- no fact type has an unbounded default.
- Replay protection -- `UNIQUE(source_id, nonce)`, the same mechanism already proven for Intent replay defense.
- Contradiction handling -- two currently-trusted, disagreeing facts raise `FactConflictError` rather than picking one.
- Tenant isolation -- every fact query is organization-scoped; a cross-tenant fact can never resolve.
- Runtime condition usage -- `enterprise_knowledge.<key>` conditions, resolved before OPA evaluation, fed through a dedicated, namespaced OPA input section.
- Evidence binding -- the exact fact snapshot relied upon (key, value, subject, source, timestamps) is recorded on the Decision's own Evidence payload.

**REFERENCE:**
- The `supplier_approved` scenario (AP-Invoice-Agent / SAP naming) -- a reference construction proving the mechanism end-to-end, not a real SAP integration.

**NOT BUILT:**
- A real SAP (or any other) connector.
- A generic connector platform.
- Continuous enterprise synchronization of any kind.

## 4. Authority Freshness

**LIVE:**
- Attestation fields (`last_attested_at`, `next_review_at`, `review_cadence_days`, `authority_expires_at`) on `RuntimePolicyRecord`.
- Re-attestation (`attest_policy`) -- updates the fields, records an immutable `attested` lifecycle event, never changes `status`.
- Review-due reporting (`list_due_for_reattestation`) -- surfaced in the existing lifecycle dashboard as its own, separately-named section (`due_for_reattestation`), never merged into the pre-existing `upcoming_expirations` (a different, unrelated concept: an active row's own scheduled `effective_until`).
- Authority expiry -- for a matched policy with `risk_level` in `{high, critical}` and a genuinely passed `authority_expires_at`, the decision is downgraded to `HUMAN_REVIEW` with reason `authority_review_overdue`. A low/medium-risk expired policy is a disclosed, accepted trade-off, not silently ignored.
- **Frontend surfacing** (completed this milestone): `RuntimePolicyDashboardPage` now shows a "Due for re-attestation" count and list, with a permission-gated Attest action, and an explicit, separately-labeled "Authority expired" indicator per row when `authority_expires_at` has actually passed.

**Review due vs. authority expired, stated once more because it matters:** review-due is a visibility reminder that never blocks anything on its own. Authority expiry is a real, decision-time fail-closed check, but only for high/critical-risk policies. The UI and the backend both keep these two facts distinct at every layer -- never one hidden inside the other.

## 5. Capability Authorization

**LIVE:**
- Short-lived, signed capability tokens (`domain/capability/token.py`), reusing the platform's existing Ed25519 signing-key registry unchanged.
- Resource/action/constraint binding -- a token authorizes the exact evaluated amount, currency, action, and resource; any deviation at verification time is rejected.
- Audience binding -- a token issued for one enforcement adapter cannot be used against another.
- Nonce/replay defense -- atomic, database-level single-use consumption (`UPDATE ... WHERE consumed_at IS NULL`), the same guarantee class as Intent's own replay defense.
- Online verify-and-consume -- the only verification mode built this program; offline signature verification is a distinct, unbuilt architecture.
- Capability evidence -- issuance and consumption are queryable, persisted facts (`CapabilityToken` rows), kept distinct from Decision Evidence itself.

**REFERENCE ONLY:**
- `scripts/reference_enforcement_adapter.py` -- proves the token/binding mechanism (replay, tampering, expiry, mismatch are all genuinely rejected) for calls routed through it. It does not prove, and is explicitly labeled as not proving, that a real enterprise target system cannot be reached through some other path.

**NOT BUILT:**
- A real enterprise Policy Enforcement Point of any kind.
- A real API-gateway plugin.
- Real orchestration-platform enforcement (UiPath, Maestro, or otherwise).
- A SAP enforcement integration.
- Offline, distributed capability verification.
- Enterprise execution confirmation (proof the target action actually completed as authorized).

## 6. Evidence

**LIVE:**
- Policy-version binding -- every Decision's Evidence pins the exact policy version and bundle hash it was evaluated against.
- Fact binding -- the exact resolved facts used are recorded on the same Evidence payload.
- Capability issuance/consumption evidence -- queryable, but as a distinct `CapabilityToken` record, not folded into the signed Evidence payload itself.
- Existing cryptographic integrity -- Ed25519 signing, hash-chaining, key-rotation history, all pre-existing and unmodified by this program.

**Stated explicitly, because it's the limit that matters most:** **capability consumption is not proof the business action completed.** Authorization decision, capability issuance, capability consumption, and execution confirmation are four distinct concepts. Only the first three exist today. The fourth does not.

## 7. Security

- **RBAC**: two new, deliberately narrow permissions this program added -- `FACTS_MANAGE` and `CAPABILITY_ISSUE` -- both granted to Governance Admin only, neither folded into an existing broader permission.
- **Multi-tenancy**: every new table (`fact_sources`, `enterprise_facts`, `capability_tokens`) is organization-scoped; every query filters on it.
- **Agent identity**: unchanged lifecycle, unchanged certificate model. **Scope.agent remediation (this milestone)**: `Agent.id`, the real, globally-unique, never-reused primary key, now correctly reaches the OPA input as `agent.id`, closing a gap where an authored agent-scoped policy could never match any agent at all. Verified: policy scoped to Agent A matches Agent A, refuses Agent B, refuses cross-tenant identity, and never produces `ALLOW` when agent identity is absent (7 dedicated tests, part of the 491 passing overall).
- **FactSource identity**: a distinct, separately-registered identity from any Agent -- an AI agent can never self-attest a consequential external fact about itself.
- **Evidence signing**: unchanged, reused by capability tokens without modification.
- **Replay protection**: three independent instances of the same proven mechanism -- Intent nonce, fact attestation nonce, capability token nonce -- all `UNIQUE`-constraint-backed, none a cache with its own expiry.
- **Fail-closed behavior**: consistently the default across every new surface added by the prior and current milestones -- missing/expired/conflicting facts, expired high-risk authority, and every pre-existing engine branch.

## 8. Positioning boundary

**Accurate today, unqualified:**
- "Authority and Evidence Infrastructure"
- "Runtime Authority"
- "Deterministic authority decision"
- "Trusted enterprise facts"
- "Decision evidence"
- "Capability authorization"

**Not yet supportable as an unqualified platform claim:**
- "Runtime Enforcement"
- "Prevents unauthorized actions"
- "Blocks AI from executing"
- "Cannot execute without PayReality"
- "Non-bypassable"

**Why:** a real enterprise Policy Enforcement Point must exist on the *only* valid execution path before any of the second list becomes technically supportable. PayReality is, today, a Policy Decision Point. It decides. It does not yet gate. The reference enforcement adapter proves the cryptographic mechanism that a real PEP would use -- it does not, and cannot, prove that no other path to the protected action exists, because no real target-system integration exists yet for it to be the only path to.

## 9. What the first real POC must prove

```
organizational authority
  -> trusted real enterprise fact
  -> real autonomous/automated action request
  -> PayReality decision
  -> capability
  -> REAL enforcement point
  -> real target action
  -> execution evidence/confirmation
```

Most importantly: **attempting to bypass the enforcement point and reach the protected action directly must fail.** Nothing in this repository today can make that claim true, because no real enforcement point has been deployed against a real target system. Everything upstream of that step is real and tested; that one step is the actual, current boundary of this platform's capability.

## 10. Known open items

- **Real PEP deployment model** -- OPEN QUESTION. Which of the compared models (API-gateway plugin, sidecar, orchestration step, direct target integration) fits the first real POC's actual target system is unknown until one exists.
- **Execution confirmation** -- OPEN QUESTION / NOT BUILT. No callback mechanism exists for a target system to report back that an authorized action actually completed.
- **Online vs. offline capability verification** -- OPEN QUESTION. Online verify-and-consume is built and works; whether a real deployment needs offline verification (and its own distributed replay strategy) is unknown without a real latency/availability requirement from a real integration.
- **First enterprise fact source** -- OPEN QUESTION. No real fact source has been identified; the reference `supplier_approved` scenario is illustrative only.
- **First target system** -- OPEN QUESTION. No real enforcement target has been identified.
- **Policy-authoring clarity gap for unresolved facts** -- RECOMMENDED. See `UNKNOWN_FACT_AUTHORING_BEHAVIOR.md`'s own Recommended Follow-Up section: no in-UI guidance currently exists near condition authoring to surface the DENY-vs-HUMAN_REVIEW distinction to a reviewer.

---

## Final verdict

**POC READY FOR ENTERPRISE INTEGRATION DISCOVERY.**

Not "production ready." Not "runtime enforcement ready." Those claims remain false until a real enterprise Policy Enforcement Point exists, independent of this or any prior milestone. What is true: the decision, freshness, fact, and capability-binding infrastructure a real POC will need is built, tested, and demonstrated end to end against real infrastructure. The next real engineering step is not more of this infrastructure -- it is a real enterprise integration telling this platform what to build next.
