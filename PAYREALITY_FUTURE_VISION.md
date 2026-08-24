# PayReality: Future Vision and Architecture

**Status: living document, current as of 2026-08-24.** Synthesizes a founder-level first-principles product review (against `PayReality_Founder_Product_Master_v1.pdf`, an internal working document dated 21 August 2026) plus a follow-on deep-design pass on the three areas that review identified as unresolved. Every claim below is checked against the actual code in this repository, not the aspiration in either source document. Where something is real, it says so and cites where. Where something is planned but unbuilt, it says so plainly. Nothing here is phrased as accomplished when it isn't.

**Supersedes, for vision purposes only**: `MASTER_ROADMAP.md` and `PAYREALITY_MASTER_BLUEPRINT.md` (both dated 2026-08-12, predating almost everything in `BACKLOG_V1_CLOSURE.md` -- 36 unit tests, Render as the only host, no RBAC. Kept for historical reference, not current). Does not supersede `BACKLOG_V1_CLOSURE.md` (current, tactical, what's-open-right-now) or `PAYREALITY_ENTERPRISE_KNOWLEDGE_RESOLUTION_VISION.md` (the fact-resolution architecture this document's Part A builds directly on, not duplicates) or `GAVIN_ABSA_PRODUCT_AUDIT.md`/`GAVIN_REMEDIATION_PLAN.md` (the active engineering-tracked initiative, issue #3 and its nine children -- see "Relationship to existing work" at the end of this document, which any reader should treat as load-bearing, not a footnote).

---

## 1. Core thesis, reaffirmed

AI systems should not own their own authority. An autonomous system may interpret information, plan, and propose actions; the authority to perform a consequential business action originates with the organisation, is evaluated deterministically before execution, and is provable afterward.

This inversion -- authority external to the probabilistic actor, evaluated before execution, with evidence as a first-class output rather than a log line -- is the one part of the thesis that has survived every enterprise conversation unchanged, and unusually for a pre-PMF thesis, most of it is already built and tested, not aspirational.

## 2. The three pillars

- **Authority Intelligence**: governance sources -> AI-extracted candidates -> conflict detection -> mandatory human validation -> a versioned, compiled, enforceable policy. Real and shipped: Authority Graph extraction, `CandidateRuntimePolicy`, `promote_candidate`'s human-gated promotion into a draft `RuntimePolicy`, Compiler V2's compile-time ambiguity/conflict rejection.
- **Runtime Authority**: a deterministic, fail-closed decision engine with zero LLM/DB/service imports (proven by architectural-boundary tests, not convention). Real and shipped: `ALLOW`/`DENY`/`HUMAN_REVIEW`, every ambiguous or unresolved path failing closed to `HUMAN_REVIEW`, multi-tenant OPA-per-organisation isolation, real 1.4-2.5ms measured decision latency.
- **Verifiable Evidence**: an Ed25519-signed, hash-chained record permanently bound to the exact policy version that governed a decision. Real and shipped: signing-key rotation, Historical Policy Binding (a decision made under policy v1 stays correctly explainable against v1 forever, proven by real tests), per-condition explainability.

## 3. Product boundary

This is the single most important section to hold the line on, because every enterprise conversation will pull toward blurring it.

| | |
|---|---|
| **PayReality owns** | The Authority Model (validated, versioned, enforceable authority); the Runtime Decision and its deterministic evaluation; the Evidence Record and its cryptographic/historical binding. |
| **PayReality understands** | Enough process/trigger/fact context to evaluate a condition against it -- as inputs. It understands "this fact was true at this moment," never "here is the state machine this fact came from." |
| **PayReality integrates with** | Agent/identity registration, source-of-truth enterprise systems as fact/attestation providers, orchestration and RPA platforms (UiPath etc.) as callers, approval systems as a source of "approval granted." |
| **PayReality observes** | Nothing continuously. It is a queried, point-in-time decision service, not a monitoring platform. |
| **PayReality proves** | That a specific past decision was correctly evaluated against the exact authority, facts, and approvals that existed at that moment -- permanently, independent of what changed after. |
| **PayReality does NOT own** | Process orchestration or execution, workflow state, RPA execution, document management, enterprise-wide GRC cataloguing, LLM output as authority, continuous observability, or the underlying business action itself. It gates. It never executes. |

**The specific scope-creep risk to actively resist**: modeling "trigger legitimacy" and "process state" as PayReality-owned graph primitives rather than as externally-sourced facts a condition tests. The first is workflow orchestration wearing an authority costume; the second is what the architecture below is actually for. Two enterprise interviews (Gavin, Dehan) both nudge toward the former; the discipline is converting everything they raised into the latter.

## 4. Where PayReality sits today: PDP, not PEP

Precisely, and without euphemism: PayReality is a **Policy Decision Point** only. The SDK's `authorize()` makes a synchronous call, receives `ALLOW`/`DENY`/`HUMAN_REVIEW`, and the calling code decides what to do with that answer. Nothing in the shipped system prevents a caller from executing regardless of the answer, or from not calling at all. There is no **Policy Enforcement Point** anywhere in the real architecture.

This is not a bug to be quietly fixed. It is the honest current state, and it gates what language is safe to use in positioning (Section 8) until it changes.

## 5. Three areas requiring real design work

### A. Trusted Enterprise Facts

**What's already decided (planned, zero implementation)**: `ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md` and `ENTERPRISE_KNOWLEDGE_DECISION_RECORD.md` already specify facts as simple named assertions (subject, key, value, source, timestamp, expiry, optional attestation), attached to the OPA input as a new section, missing/stale/unattested -> fail-closed. This document does not replace that plan; it sharpens the trust model around it.

**A fact** is a named, typed, time-bound assertion about enterprise reality that a Condition tests -- not a new architectural layer, just an externally-sourced input to a mechanism that already exists.

**Required fields**: `subject`, `key`, `value` (typed), `source` (registered system id), `attested_by` (signing key id, if attested), `observed_at`, `recorded_at`, `expires_at` (mandatory -- no fact type gets an unbounded default), `attestation_type` (signed / connector-identity / caller-supplied).

**Trust has two independent axes**: who vouches for it (source authentication), and whether it's still fresh (unexpired). Neither alone is sufficient.

**Pull vs. push**: attested-push is the primary mechanism -- lower runtime latency, decouples decision availability from N external systems being reachable synchronously. Pull is a real trade (freshest possible answer, but couples decision latency and availability to every pulled source), reserved for a V2 case with a proven sub-minute-freshness requirement, never the default.

**Source authentication**: reuse the Ed25519 infrastructure already built and tested for Agent certificates and Evidence signing (`server/app/domain/evidence/signing.py`) -- register a fact source the way an Agent is registered. Do not invent a second identity primitive. Fallback for a source that can't sign: connector-identity auth (mTLS/API key) plus a materially shorter expiry.

**Non-negotiable rules**:
- Stale = unknown = fail-closed. No exception.
- Never let the requesting agent supply a fact about external state used as a gating condition -- that's the agent grading its own homework. Caller-supplied is acceptable only for facts inherent to the request itself (amount, resource id).
- A cache hit past `expires_at` is a miss, not a hit. Never opportunistically extend expiry to dodge a slow re-fetch.
- Contradictory facts from two trusted sources are not arbitrated by PayReality or an LLM -- same discipline as policy-conflict rejection. Contradiction -> unknown -> fail-closed -> human resolution, both attestations preserved in evidence.
- The evidence payload must include the fact snapshot actually relied upon (key, value, source, attestation reference, timestamp), extending the existing signed-payload schema that already binds `policy_version`/`bundle_hash` -- not a parallel evidence path.

**Smallest POC architecture**: one real connector, built against one pilot's one decisive fact, pushing a signed or connector-authenticated fact with mandatory expiry into a small facts table, checked at decision time via the same OPA input shape already in use. No generic connector SDK. No bidirectional sync engine. That is an enterprise data platform, and it is explicitly not what this is.

### B. Authority Freshness / Re-attestation

Gavin's sharpest objection, reduced to one sentence: **a policy can be correctly versioned and historically bound while still being stale relative to the organisation's current reality.**

**What can go stale**: the org's underlying reality -- policy text, delegation structures, approval matrices, control ownership, source documents. **A compiled Runtime Policy does not go stale in itself** -- Historical Policy Binding already guarantees it is permanently, correctly self-consistent. Staleness is a property of the relationship between an active version and the world, not of the object.

**Minimum model**:
- `last_attested_at`, `next_review_at`, `owner` -- new fields, small additions.
- `expires_at` (of the authority, distinct from the existing `retired_at`) -- new, optional per risk tier.
- Existing `approved_at`/`activated_at` and the existing lifecycle `status` enum are already sufficient; do not add a second parallel status field.
- Cadence is risk-based, set per policy or per risk tier, not a single global timer -- this is also what keeps the scope small: one interval field on an object that already exists, not a compliance-management subsystem.

**Behavior**:
- `review_due` reached -> surface it, keep enforcing, escalate visibility to the owner. Do not auto-deactivate a probably-still-correct policy.
- Genuinely expired, high-risk authority -> fail-closed to human review, the same consistent extension of the engine's existing "no silent fallback to permissive execution" principle. Low-risk expired authority is an accepted, disclosed trade-off, not a silent break.
- Source-document changes -> a manual "mark source revised" action by the document's owner, pushing `next_review_at` forward. **Expose a revalidation workflow. Do not watch, poll, or crawl documents.** Accept an inbound webhook opportunistically if a source system offers one; never build a watching service to get there.

**The GRC boundary**: own exactly one thing -- does this active, enforced policy have a fresh attestation. The moment this starts tracking document versions broadly, or a control catalogue independent of what's actually compiled and enforced, it has become GRC.

**V2**: the fields above, a due/overdue dashboard signal, a one-click re-attest action. **Much later, maybe never**: automated document diffing, dependency-aware cross-policy re-review, anything resembling a compliance calendar product.

### C. Enforcement: the PDP/PEP bridge

**Ten models compared** (bypass resistance / integration burden / ability to prove enforcement occurred):

| Model | Bypass resistance | Burden | Proves enforcement | Status |
|---|---|---|---|---|
| SDK-only (today) | None -- fully voluntary | Lowest | Cannot | **Built** |
| App-side wrapper | Moderate | Per-framework | No | Absent |
| Tool-wrapper (agent frameworks) | Moderate | Per-framework, agent-scoped | No | Absent -- good near-term fit given this product's framing |
| Orchestration-platform step | Good if platform enforces it | High, vendor-specific, certified | Better | Absent -- zero UiPath/Maestro-specific code exists anywhere |
| API-gateway | Good if no other reachable path | Moderate-high | Good | Absent -- good long-term fit |
| Sidecar/local (OPA-based) | Good with network policy | Real, but closest to what's already true (OPA is already the core) | Good | Absent -- arguably the most on-thesis heavy option |
| Reverse proxy | Good if sole path | Lower for a single POC target | Good | Absent -- pragmatic POC option |
| Service mesh | Very strong, narrow applicability | High, imposes a platform prerequisite | Good | Absent -- only where a mesh already exists |
| Direct target integration | Potentially strongest | Very high, bespoke, doesn't scale as a product motion | Excellent | Absent |
| Capability token | Depends entirely on what checks it | Moderate on issuance; unchanged on verification | Best available binding, if execution confirms | Absent |

**The capability-token verdict, stated plainly**: a capability token is not an eleventh enforcement location. It is a transport and proof mechanism. Something still has to refuse to execute without validating it -- one of the rows above. Without a real enforcement point, a signed token degenerates back to today's model with extra cryptography that changes nothing about bypassability. **Necessary, not sufficient.**

Where it genuinely earns its place: cryptographically tight, single-resource, single-amount, single-expiry, single-use binding between a specific decision and a specific execution attempt -- cheap to build because it reuses infrastructure that already exists and is already tested (Ed25519 signing; the nonce+timestamp+`UNIQUE(agent_id, nonce)` replay defense already built for Intent submission).

**Token fields**: `decision_id`, `principal`, `action`, `resource` (exact id, never a category), `constraints` (the exact amount/currency evaluated, bound not referenced), `policy_version`, `fact_hashes`, `issued_at`, `expires_at` (minutes, not hours), `nonce`, `audience` (the specific enforcement adapter this token is valid for), `signature`.

**Known, named limits, not silently accepted**:
- TOCTOU: a token authorizes conditions true at issuance; short expiry bounds the window, doesn't close it.
- Replay: nonce + single-use consumption, reusing the existing Intent-replay mechanism exactly.
- Revocation tension: short expiry mostly avoids needing it; real-time revocation checking reintroduces the synchronous dependency the offline-verifiable token was meant to avoid.
- Execution confirmation is unsolved even with tokens: nothing guarantees the target reports back that it executed under a given token unless a callback is deliberately built. Without it, evidence proves authorization was issued, never that execution happened as authorized.
- Partial failure is the target system's own transactional-integrity problem, outside the token model's scope entirely.

**Is this the clean bridge between PDP and PEP?** Only when paired with a real enforcement point. It cannot manufacture bypass resistance that doesn't otherwise exist. Building the token model alone produces better cryptography around the same voluntary system -- and marketing that as "enforcement" would be a real overclaim.

## 6. Failure modes (condensed catalog)

For each: what happens, who owns the risk, what PayReality can prevent vs. only detect.

**Trusted facts**: stale fact used (should be architecturally impossible -- a bug, not a risk to accept) · forged fact (prevented by source signature; a compromised source's own key is only detectable after the fact, same PKI boundary as anywhere) · compromised connector (detectable via anomaly, not preventable; risk owner is the connector operator) · wrong source (prevented by mandatory source-identity binding) · contradictory sources (fail-closed to human resolution, both preserved) · fact changes after decision (not a failure -- expected, decision remains valid as evaluated).

**Authority freshness**: expired policy still enforcing (prevented by design for high-risk tiers; disclosed trade-off for low-risk) · changed source document unnoticed (can't be prevented by design choice; only the revalidation workflow exists) · owner left the company (detectable, not preventable; PayReality's job is to surface it) · re-attestation missed (detectable via `next_review_at`, should escalate for high-risk) · wrong version activated (already prevented by the existing, tested lifecycle).

**Enforcement**: caller bypass (cannot be prevented in the current model at all) · token replay (prevented by nonce + single-use ledger) · PEP misconfiguration (owned by the adapter/integration, not PayReality's core) · target API bypass (an enterprise network-topology risk) · parameters changed before execution (prevented by amount/resource binding in the token; unpreventable without one) · PayReality unavailable (today: the caller's undisclosed choice -- a real, open gap) · PEP unavailable (the enforcement point's own availability design) · execution occurs but confirmation never returns (evidence proves authorization was issued, never that execution happened as authorized -- an honest limitation until a confirmation callback exists).

## 7. Roadmap

**ALREADY BUILT**: deterministic fail-closed Runtime Authority core · flat AND-only conditions with compile-time conflict rejection · RBAC (6 roles) and tested multi-tenant isolation · immutable, versioned policy history with tested Historical Policy Binding · Ed25519 signing for Evidence and Agent certificates · hash-chained Evidence · full Agent Lifecycle with nonce+timestamp+unique-constraint replay protection (directly reusable for fact attestation and token replay defense) · human-gated Authority Intelligence -> candidate -> promotion pipeline · a Pending Review queue.

**POC REQUIRED**: one real trusted-fact connector (Section 5A) for the POC's one decisive fact · mandatory fact expiry with fail-closed-on-stale as an enforced discipline · `last_attested_at`/`next_review_at`/`owner` plus a due/overdue signal (Section 5B) · one real enforcement adapter for the POC's specific target system (API-gateway or direct integration, whichever that system supports) · capability-token issuance reusing existing signing/replay infrastructure, paired with that one adapter.

*Factual note, not a design opinion*: a fourth/fifth decision verdict (`REQUIRE_APPROVAL`, `ESCALATE`, `REQUIRE_EVIDENCE` distinct from today's `HUMAN_REVIEW`) is a real schema and engine change against what exists today -- the `decisions` table's own `CheckConstraint` currently allows exactly `ALLOW`/`DENY`/`HUMAN_REVIEW`. Build this only if the actual POC surfaces a concrete need for the distinction, not because it was discussed in principle. `REQUIRE_EVIDENCE` specifically should not become a verdict at all -- it's already representable as the existing `Constraints.evidence_required` field, and treating it as a verdict conflates "how strong must the record be" with "what should execution do."

**V2 REQUIRED**: a second/third fact connector, still one-at-a-time and need-driven · risk-based review-cadence tiers · a sidecar or orchestration-step adapter for a second target system · a real execution-confirmation callback design.

**OPTIONAL LATER**: additional enforcement adapters per major orchestration vendor · richer multi-approver chains · cross-agent delegation.

**DO NOT BUILD**: a generalized connector/data-sync platform · document-watching or GRC tooling · any process/workflow graph PayReality itself owns · a dedicated graph database (the existing Authority Graph/Authority Model distinction is relational and shallow-query; no traversal-heavy workload has ever justified one) · a generalized PEP framework built speculatively before one real adapter is proven.

## 8. Positioning guardrails

Accurate today: **"Runtime Authority"** (a PDP capability name) · **"Authority Layer"** (a category/pillar name) · **"Authority and Evidence Infrastructure"** (the company-level frame -- correctly claims the two things that are real without claiming the third).

Borderline, only safe immediately qualified: **"Runtime Control"** ("decision control," "advisory control" -- not bare).

Not accurate today, anywhere, until a real adversarially-tested enforcement point exists for at least one integration: **"Runtime Enforcement."**

Avoid entirely until that point exists: **"prevents," "blocks," "stops," "enforces" (unqualified), "cannot execute without," "guarantees."** Using any of these about the current SDK-only integration is the same class of overclaim `GAVIN_ABSA_PRODUCT_AUDIT.md` already found in outward-facing material.

## 9. Final decisions

1. **Build next**: one real trusted-fact connector, one real enforcement adapter, capability tokens binding them, all for one real target system and one real POC.
2. **Absolutely not next**: a generalized PEP framework, a generalized connector platform, GRC/document-watching tooling, a new decision verdict without validated need, a second enforcement adapter before the first is proven.
3. **Biggest technical risk today**: the PDP/PEP gap -- every implicit "enforcement" claim rests on voluntary compliance, invisible until a real, adversarial integration exposes it in front of a buyer.
4. **Biggest product risk**: scope creep into process/workflow modeling disguised as "trigger legitimacy" or "process state" -- the thing this document exists to prevent, and the one most likely to happen anyway under deadline pressure because it feels like progress.
5. **Cleanest path to a real POC**: pick one target system (supplier payment or procurement authorization rank highest against the core thesis -- see the Founder & Product Master's own use-case ranking), build exactly one real enforcement adapter and one real fact connector for it, and demonstrate the full loop -- decision, token, enforced execution, evidence -- once, for real, end to end.
6. **What must be true before honestly claiming "enforce"**: a real, externally deployed enforcement point where the target action genuinely cannot execute without a valid, freshly-issued authorization -- verified by trying to bypass it and failing, not by a design document saying it should work.
7. **Does capability-token enforcement materially strengthen the company?** Yes, conditionally -- it materially and cheaply strengthens the evidence/binding story by reusing infrastructure that already exists, and it's a necessary building block for real enforcement. It does not, by itself, turn PayReality from PDP into PEP, and claiming otherwise before a real enforcement point exists would be exactly the overclaim this document exists to prevent.

## Relationship to existing work

This document is architecture and positioning discipline. It does not replace, and should be read alongside:

- `BACKLOG_V1_CLOSURE.md` -- what's actually open right now, tactically.
- `GAVIN_ABSA_PRODUCT_AUDIT.md` / `GAVIN_REMEDIATION_PLAN.md` -- the active, engineering-tracked initiative (GitHub issue #3 and its nine children) closing the gap between a real sales briefing already sent to a real enterprise prospect and what the product does today. Before any Gavin-facing architecture brief goes out (as the Founder & Product Master's own execution plan proposes), reconcile it with this already-in-flight work -- sending two uncoordinated PayReality documents to the same person in short succession undercuts exactly the credibility both are trying to build.
- `ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md` / `ENTERPRISE_KNOWLEDGE_DECISION_RECORD.md` / `PAYREALITY_ENTERPRISE_KNOWLEDGE_RESOLUTION_VISION.md` -- the fact-resolution architecture Section 5A builds on directly, including the prior, still-standing rejection of zero-knowledge proofs as the trust mechanism (attestation-first is the right tool; ZK conflicts with the explanation service's own "never fabricate" requirement).
