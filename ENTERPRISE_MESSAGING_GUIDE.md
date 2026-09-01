# Enterprise Messaging Guide

**Purpose**: the single source of truth for how PayReality should be described, everywhere. Every other deliverable (website copy, sales material, pilot documentation) should trace back to the definitions in this document, not restate them independently.

**Status: rewritten as of Milestone 17.1 (POC Readiness Remediation), 2026-08-25; extended 2026-08-31 (Product & Trust Documentation Baseline) to cover Trusted Integration Architecture Phases 1–4; extended again 2026-09-01 to cover Trusted Integration Architecture Phase 5 (Adapter-Backed Capability Authorization)**, superseding the prior version of this guide, which was written around a narrower "policy decision point sitting after identity, before execution" framing. That framing was accurate as far as it went but predates several real, shipped capabilities (Trusted Enterprise Facts, Authority Freshness, Capability Authorization, and now Trusted Integration) and undersold the platform's real architecture. This version is checked directly against the current codebase, `POC_READINESS_REPORT.md`, and [SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md](SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md), not against the aspiration in any planning document.

**One correction to this guide's own prior instruction**: §16 below previously listed "Authorization Receipt" as a prohibited artifact name, on the basis that it wasn't a real shipped thing distinct from Evidence. That was accurate on 2026-08-25 and is **no longer accurate** — `GET /v1/decisions/{id}/receipt` is a real, shipped, named endpoint (Issue #4), with a dedicated frontend page and its own permission gate. §16 and §18 below have been corrected. It remains true, and more important than ever to keep saying, that the Receipt is a *packaging* of Evidence, never a stronger or separate proof.

Every factual claim below is labeled **VERIFIED** (checked directly against the shipped platform and its passing tests), **REFERENCE ONLY** (a real, working artifact built specifically to prove a mechanism, not a production integration), **INFERRED** (a reasonable conclusion from verified facts, not itself directly tested), or **PROPOSED** (a messaging choice being recommended, not a fact).

---

## 1. Primary category (locked)

**"The Enterprise AI Authority Infrastructure."**

This is the public category positioning and should not be replaced by anything else in customer facing or website level material. The longer, more technical phrase "Authority and Evidence Infrastructure for autonomous enterprise systems" may still be used descriptively inside technical or internal material where it helps a reader (an engineer, a security reviewer) understand the shape of the system, but it is not the primary category and should not compete with it on a homepage, a deck title, or an elevator pitch.

## 2. Core thesis (do not change)

AI systems should not determine their own authority. Organizational authority exists outside the probabilistic actor, in the organization's own governance, policy, and delegation structures. PayReality externalizes that authority into deterministic, machine evaluable policy, so enterprises can determine whether a proposed AI action is authorized before execution, and preserve verifiable evidence of the decision.

Everything else in this document is a description of how that thesis is actually implemented today, and where the implementation currently ends.

## 3. The three pillars

1. **Authority Intelligence** (extraction): turns an organization's own governance documents, delegation of authority memos, approval matrices, and signing schedules into structured, provenanced, human reviewed candidate authority data. AI proposes; nothing here is ever auto enforced.
2. **Runtime Authority** (decision): a deterministic decision engine that evaluates a proposed AI action against the organization's active Runtime Policies and Authority context and returns exactly one of ALLOW, DENY, or HUMAN_REVIEW, every time, with no fourth outcome and no partial result.
3. **Verifiable Evidence** (proof): every decision produces a signed, hash chained record binding the decision to the exact policy version and facts that produced it, independently verifiable without asking PayReality to vouch for it.

## 4. The one sentence description

**PROPOSED, as the canonical version**: "PayReality is the Enterprise AI Authority Infrastructure: it decides, before an AI agent acts, whether that agent actually has the authority to take the action, and produces a cryptographically signed record of the decision."

Three words carry the entire claim and should never be dropped in any shortened version: **before** (pre execution, not after the fact review), **authority** (a specific, delegable, enterprise concept, not a vague safety notion), **signed** (independently verifiable, not just logged).

## 5. What PayReality actually is, mechanically (VERIFIED)

A pre execution authorization decision engine for AI agents acting as autonomous parties in real business transactions (payments, purchase orders, access grants, and similar). The mechanism, exactly as shipped:

1. An AI agent, holding an Ed25519 certificate issued at registration, signs an **Intent**: a structured description of the action it wants to take (an action type, an amount, a counterparty, a resource, and so on).
2. The platform verifies the signature against the agent's active certificate, then evaluates the Intent against the organization's compiled **Runtime Policies** (deterministic rules, evaluated by a real embedded Open Policy Agent instance, never a language model), the **Authority Graph and Authority Model** (who has delegated what authority to whom, extracted from the organization's own governance documents and human reviewed before use), and, where a policy condition calls for it, **Trusted Enterprise Facts** (see Section 8).
3. The result is exactly one of three outcomes: **ALLOW**, **DENY**, or **HUMAN_REVIEW**. A Runtime Policy either matches deterministically or it does not; every ambiguous, missing, expired, or unresolved branch resolves to HUMAN_REVIEW, never a default ALLOW.
4. Every decision produces a signed **Evidence** record (Ed25519, canonical JSON, hash chained to the record before it, written in the same database transaction as the decision itself), independently verifiable by anyone holding PayReality's published public key.
5. For an ALLOW decision, PayReality can additionally issue a signed **Capability Authorization** token, a separate, more limited step described in full in Section 8.

This is a decision and evidence system for autonomous AI actors, not a chat interface, not a dashboard product, and not a model.

## 6. Current architectural boundary (the single most important section in this document)

**PayReality is a Policy Decision Point (PDP) today. It is not a Policy Enforcement Point (PEP), and no production PEP exists anywhere in this system.**

Say precisely what that means every time it comes up, because it is the fact most likely to be assumed incorrectly by a reader who has not seen the codebase:

- PayReality evaluates a proposed action and determines whether it is authorized.
- PayReality produces signed evidence of that determination, before and independent of whatever happens next.
- For an ALLOW decision, PayReality can issue a cryptographically bound Capability Authorization token, a short lived, single use, tightly scoped credential that a downstream system could require before acting.
- PayReality cannot itself stop an agent, a workflow, or an enterprise system from proceeding after a DENY or a HUMAN_REVIEW, and it cannot stop a caller from acting without ever asking it in the first place. Whether an action is actually gated depends entirely on the calling integration choosing to call PayReality first and choosing to respect the answer, or on a real enforcement point downstream choosing to require a valid Capability Authorization token before acting.
- A reference enforcement adapter exists in this codebase (`scripts/reference_enforcement_adapter.py`). It is proof of mechanism only: it demonstrates that replay, tampering, expiry, and parameter mismatch are all genuinely rejected for any call routed through it. It does not prove, and its own comments explicitly say it does not prove, that a real enterprise target system cannot be reached through some other path that bypasses it entirely. It is not a SAP integration, not a production integration with any named platform, and not itself an enterprise Policy Enforcement Point.

The honest, complete answer to "what happens if PayReality cannot be reached, or is bypassed" is: nothing in PayReality today detects or prevents that. The entire enforcement guarantee, until a real PEP is deployed on the only path to the protected action, lives in the calling integration's own discipline. This is not a flaw to hide; it is the accurate current boundary of the product, and it is the single fact most likely to matter to a skeptical security or architecture reviewer.

## 7. Authority Intelligence (VERIFIED)

The AI assisted layer that turns an organization's real, existing governance documents into structured, provenanced Authority Graph data: named principals and their reporting relationships, resources, operations, delegation and escalation and inheritance relationships, and an explicit accounting of every conflict, gap, and open question the extraction found, each with its own citation back to the source document and the model's own stated reasoning and confidence.

**Precise and important nuance**: the Authority Graph does not compile into Runtime Policies as a structural, graph to graph transformation. Only one narrow slice of the extraction, AI proposed policy candidates generated directly from the source text, has a real, human gated path (`promote_candidate`) into a draft Runtime Policy. The rest of the graph (principals, relationships, conflicts, resources, operations) either has no code path into enforcement at all, or, for resolved and activated delegation relationships specifically, enriches the context a policy's own conditions can reference, but never generates or edits a condition on its own. Nothing extracted this way ever becomes a live, enforced Runtime Policy without an explicit human promotion and approval step.

**The one non negotiable messaging constraint**: say this plainly in every piece of material that mentions Authority Intelligence. It is the answer to the single most predictable enterprise objection: "so an AI decides our authority rules?" No. A human always promotes and approves.

## 8. Supporting capabilities (real, shipped, verified against the current codebase)

These three capabilities are real, shipped, and tested as of Milestone 17.1. Each has a specific, deliberately narrow scope. Do not describe any of them more broadly than stated here.

### 8.1 Trusted Enterprise Facts

Runtime Policies can reference facts that originate outside the authorization request itself, for example "is this supplier approved" or "is there sufficient budget," through a dedicated, namespaced `enterprise_knowledge.<key>` condition input resolved before OPA evaluation.

A fact is only usable when its registered source belongs to the same organization and is active, its signature verifies against that source's own registered Ed25519 public key, it has not expired (no fact type has an unbounded default expiry), and there is no unresolved contradiction with another currently trusted fact for the same subject and key. Replay is prevented the same way Intent replay is prevented, with a database level unique constraint on source and nonce.

**Boundaries that must be stated whenever this is described**:
- A fact has provenance, and a fact expires. Missing, expired, or conflicting facts all resolve to the same place, unknown, which the existing fail closed decision path already handles; none of those states is ever silently treated as true or as false.
- A trusted source assertion proves what that source asserted, not objective truth. PayReality verifies that a registered, active source signed a specific claim; it does not independently verify the real world fact the claim describes.
- The exact fact snapshot relied upon, key, value, subject, source, and timestamps, is recorded on the decision's own Evidence payload, so a past decision remains explainable against the facts it actually used.
- There is no real external connector today. The `supplier_approved` scenario in this codebase is a reference construction proving the mechanism end to end, not a real SAP or other enterprise system integration. Do not market this as a generic enterprise data platform, and do not imply a live connector to any named enterprise system exists.

### 8.2 Authority Freshness

Runtime Policy records carry attestation fields: `last_attested_at`, `next_review_at`, `review_cadence_days`, and `authority_expires_at`. Re attestation updates the review fields and records an immutable lifecycle event, without ever changing the policy's own active status. A dashboard surfaces which policies are due for re attestation, as its own, separately named signal.

**Boundaries that must be stated whenever this is described, because the two concepts are genuinely different and must never be merged in language**:
- **Review due** (`next_review_at` has passed) is a visibility reminder. It never blocks a decision on its own.
- **Authority expired** (`authority_expires_at` has genuinely passed) is a real, decision time fail closed check, but currently only for policies whose risk level is high or critical; a matched policy in that state is downgraded to HUMAN_REVIEW with an explicit reason. A low or medium risk expired policy is a disclosed, accepted trade off today, not silently ignored, but it does not by itself force a review.
- Do not turn this into generic GRC (governance, risk, and compliance) positioning. It is a specific freshness signal tied to Runtime Policy attestation, not a compliance management suite.

### 8.3 Capability Authorization

For an ALLOW decision, PayReality can issue a signed, short lived, single use authorization capability token, reusing the same Ed25519 signing key registry already used for Evidence. The token binds, under signature, the decision id, organization, principal, action, resource, the exact constraints evaluated (for example the specific amount and currency, not a category or a range), the policy version, the fact hashes relied upon, an audience naming the specific enforcement adapter it is valid for, an expiry, and a nonce. It can be verified and consumed exactly once, atomically, by an enforcement adapter, through an online verify and consume call; offline signature verification is a distinct, unbuilt architecture.

As of Trusted Integration Phase 5, this is true for a decision made through either runtime path, not only the agent-direct one. For a decision produced by a Trusted Adapter, issuance additionally re-checks, live, at the moment of issuance, that the underlying Trusted Connection and Runtime Connection are still active, not merely that they were active when the original Intent was accepted, and fails closed if either has since been suspended, revoked, or retired. When issued for that path, the token also carries the exact Runtime Connection, Action Mapping version, and environment under signature, and a verifier that knows which connection or environment it enforces can optionally pin that expectation against the token's own signed claim. A verifier that supplies neither is unaffected, exactly as before Phase 5.

**The boundary that must never be dropped, in bold in every document that mentions this capability**: **Capability Authorization is not itself enforcement.** It is a cryptographically tight, single resource, single amount, single expiry, single use binding between a decision and a proposed execution, for whatever real enforcement point chooses to check it. Something downstream must actually require the capability before acting, and nothing does in production today. The only enforcement adapter that exists in this codebase is the reference adapter described in Section 6, which is explicitly proof of mechanism, not a production integration. This applies identically, without exception, to a Capability issued for a Trusted-Adapter-mediated decision.

### 8.4 Trusted Integration

Runtime Authority has two ways to learn what an AI agent is attempting. The original way, unchanged: the agent's own signed description of itself. The newer way, additive: a customer-controlled **Trusted Adapter** — never PayReality's own component, never hosted by PayReality — observes a real operation against an enterprise system and reports it using a deterministic, human-approved **Action Mapping**, through a separately authenticated **Trusted Connection**.

**Three questions, never conflated, in every description of this capability**: *Agent* answers who is acting. *Trusted Adapter* answers what company-controlled component is attesting what action is being attempted. *PayReality* answers whether the organization authorizes that agent to perform that action under these conditions. The Adapter never gives the agent authority; PayReality never trusts the agent merely because an Adapter exists; the Adapter never objectively proves reality — it attests what it observed, structurally checked against an approved mapping, nothing stronger.

**Boundaries that must be stated whenever this is described**:
- The Adapter is customer-deployed, customer-controlled infrastructure. "PayReality secretly watches enterprise systems" is never an accurate description under any circumstance.
- An Action Mapping is deterministic, versioned, and requires a named human's approval before use; multiple approved versions of the same mapping may legitimately coexist (there is no single "current version").
- Only context explicitly bound by an approved mapping may influence a decision — never arbitrary caller-supplied metadata.
- A pre-evaluation trust failure on this path (an inactive connection, an agent not on the explicit allow-list, a mapping mismatch) is an **integration rejection**, never a `DENY` — no Decision, no Evidence, is produced for it. Keep this distinction as sharp as the ALLOW/DENY/HUMAN_REVIEW distinction itself.
- One real business operation produces one authority decision: a network retry of the same operation returns the existing Decision, never a new one; the same operation ID with different authority-relevant meaning is a conflict, never silently evaluated.
- **Capability Authorization can now be issued for an Adapter-mediated ALLOW decision** (Trusted Integration Phase 5). See §8.3's own account, including the live re-check at issuance and the still-unconditional "not itself enforcement" boundary, which applies to this path exactly as it does to the agent-direct one.

Full technical account: [SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md](SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md). Plain-language explainer for customer-facing material: [TRUSTED_ADAPTER_GUIDE.md](TRUSTED_ADAPTER_GUIDE.md).

### 8.5 Enforcement assurance (Trusted Integration Phase 5)

A Runtime Connection can carry a customer-declared `enforcement_assurance` label describing what the customer's own downstream checkpoint claims to require. Only two values exist and have any real implementation behind them: **ADVISORY** (the default, no declared requirement) and **CAPABILITY_REQUIRED** (the customer declares that their own checkpoint requires a valid Capability before it acts).

**The boundary that must never be dropped**: setting `CAPABILITY_REQUIRED` is the customer's own claim about their infrastructure. PayReality never independently verifies, tests, or observes that any downstream checkpoint actually enforces it, and the label carries no authority meaning of its own; Runtime Authority's own evaluation never reads it. Three further levels named in this platform's longer-term vision, **DECLARED_DECISION_CHECK**, **VERIFIED**, and **REGISTERED_EXTERNAL_PEP**, are not implemented: no code path can set them, and none should ever be described as available. This phase never registers or authenticates a distinct external enforcement workload as its own trusted identity, which is what any of those three levels would require.

## 9. Runtime Policies and OPA (VERIFIED)

Policies are structured data (scope, conditions, effect), never natural language rules interpreted at decision time. They compile to real Rego and are evaluated by a real, embedded Open Policy Agent instance, the same open source engine used for policy as code in cloud infrastructure and Kubernetes. A policy's lifecycle is explicit and auditable: draft, submitted for review, approved, activated (which triggers real compilation and a real OPA deployment with a recorded bundle hash), and eventually deprecated, archived, or rolled back (rollback creates a new draft rather than reactivating history directly, by deliberate design). Two policies that could jointly, ambiguously match the same real Intent are rejected at compile time, before either can go live. Nothing about evaluation is probabilistic; the same input against the same active policy set produces the same decision every time, which is precisely why the Evidence record is worth signing at all.

Runtime Policies today are flat, single stage, AND only rules. There is no multi step, sequential approval, or process chain concept anywhere in the codebase. Do not describe or imply a sequential approval chain (for example "first Finance, then Legal, then the CFO") as a shipped capability.

## 10. Evidence (VERIFIED)

Every decision, ALLOW, DENY, or HUMAN_REVIEW, produces a signed record, written in the same database transaction as the decision itself: the Intent, the outcome, the specific policy version and Authority context that produced it, the fact snapshot relied upon (Section 8.1), and a payload hash chained to the prior record. Verification is a real, independent cryptographic check against a published public key, not a "trust our dashboard" claim. A signing key registry means a key rotation never breaks verification of Evidence signed under a prior key.

Two precise points worth stating rather than implying: the chain verification endpoint that exists today requires the caller's own organization credentials, it is not yet a credential free, third party verification surface; and the signed payload carries which rules matched, not a full per condition pass and fail breakdown, which is instead correctly reconstructed on demand rather than baked into the original signature. Neither of these is a defect, but neither should be overstated as more portable or more self contained than it currently is.

## 11. Multi tenancy and Enterprise Surface Isolation (VERIFIED)

Every organization's Runtime Policies, OPA packages, Authority Graph data, Enterprise Facts, Capability Tokens, Evidence, agents, Blob stored documents, and Azure AI Search index entries are isolated by organization at the data layer, not just the UI layer. A second organization was created and live tested specifically to prove this: it saw zero agents, zero policies, and zero documents belonging to the first. This is a real, tested property, not an assumption.

## 12. SDK (VERIFIED)

A Python SDK, versioned, generating real Ed25519 keypairs client side and signing every Intent before it ever leaves the calling process. The private key never transits to PayReality's servers at registration or at any later point. Python is the only supported SDK language today.

## 13. Azure architecture (VERIFIED)

Production runs on Azure Container Apps, Azure Database for PostgreSQL Flexible Server, Azure Key Vault, Azure AI Foundry, Azure AI Search, and Azure Blob Storage, secured with Managed Identity throughout, no shared static credentials where identity based access is possible. The production domain, `api.aisecurewatch.com`, is live on this infrastructure with a real, auto renewing certificate. This is real, current, and appropriate to say in present tense, not "planned" or "in progress."

## 14. Current safe claims

- "The Enterprise AI Authority Infrastructure" as the category.
- PayReality evaluates a proposed AI action and determines whether it is authorized, before that action executes.
- PayReality makes a deterministic authorization decision: ALLOW, DENY, or HUMAN_REVIEW, evaluated by a real embedded OPA instance, never a language model at decision time.
- Every decision produces a signed, hash chained, independently verifiable Evidence record.
- For an ALLOW decision, PayReality can issue a signed, single use Capability Authorization token bound to the exact decision, principal, action, resource, constraints, policy version, and facts evaluated.
- PayReality resolves Trusted Enterprise Facts with provenance and mandatory expiry, and fails closed on anything missing, expired, or contradictory.
- PayReality tracks Authority Freshness (attestation, review cadence, and, for high or critical risk policies, a real fail closed check on expiry) as a distinct signal from review due.
- Authority Intelligence proposes candidate authority data and candidate policies from an organization's own governance documents, with full provenance; nothing is enforced without an explicit human promotion and approval.
- The platform is multi tenant, isolated at the data layer, and this isolation has been live tested with a real second organization.
- Production runs on Azure with Managed Identity throughout and a live custom domain with a real certificate.
- A customer-controlled Trusted Adapter can report a real enterprise operation to Runtime Authority through a deterministic, human-approved Action Mapping, with an explicit Agent allow-list and a genuine, DB-enforced idempotency guarantee against retries.
- PayReality's Authorization Receipt packages one decision's Evidence, authority, and (where applicable) trusted-integration provenance into one shareable, human-readable view — it is Evidence, presented, never a second or stronger proof.
- Capability Authorization can be issued for an ALLOW decision made through either runtime path, agent-direct or Trusted-Adapter-mediated; for the Adapter-mediated path, issuance re-checks that the underlying Trusted Connection and Runtime Connection are still active at that exact moment, not only at Intent submission. It remains not itself enforcement on either path.
- A Runtime Connection can carry a customer-declared `enforcement_assurance` label (`ADVISORY` or `CAPABILITY_REQUIRED`) describing what the customer's own downstream checkpoint claims to require; this is the customer's own unverified claim, never something PayReality tests or observes.

## 15. Future or conditional claims (state the condition every time)

- "PayReality can be the foundation for a real enforcement point" is fair once qualified: it requires a real Policy Enforcement Point built and deployed on the only path to the protected action, which does not exist today for any customer.
- "Capability Authorization enables enforcement" is fair only paired with "once a downstream system actually requires it before acting," never as a standalone claim.
- "PayReality resolves enterprise facts like supplier approval or budget sufficiency automatically" is fair only once a real connector exists for that specific fact; today this would have to be self reported by the caller or built as a new, scoped connector.
- "PayReality supports on premises deployment" is not true today; the platform is a multi tenant, Azure hosted service.
- "PayReality supports multi step or sequential approval chains" is not true today; only flat, single stage policies exist.
- Any claim of a named customer, pilot, or reference deployment should be added here only once one genuinely, verifiably exists; see Section 17.
- "PayReality has vendor connectors for [named enterprise system]" is not true today; every Trusted Adapter is customer-built against a documented request shape, and no vendor-specific (SAP, Workday, or similar) connector ships with the platform.
- "PayReality automatically discovers what an enterprise system's operations mean" is not true today; every Action Mapping is hand-authored and requires explicit human approval.
- "PayReality verifies that a downstream checkpoint actually requires or enforces a Capability" is not true today; a Runtime Connection's `CAPABILITY_REQUIRED` enforcement-assurance label is the customer's own declared claim about their infrastructure, never independently checked.
- "PayReality supports VERIFIED or REGISTERED_EXTERNAL_PEP enforcement assurance" is not true today, at all; only `ADVISORY` and `CAPABILITY_REQUIRED` have any implementation, and no code path can set the other three named levels.

## 16. Prohibited current state claims

Do not make any of the following as an unqualified, present tense platform claim:

- "Runtime Enforcement," used to mean PayReality itself enforces or blocks an action.
- "Blocks unauthorized actions" or "prevents AI from executing," stated as something PayReality itself does today.
- "Cannot execute without PayReality," or any variant implying PayReality sits on the only path to an action.
- "Non bypassable."
- "Authorization Receipt" described as a **second, independent, or stronger** proof than Evidence, or as proof that a downstream external action executed. (Corrected 2026-08-31: the term itself is now a real, shipped, named artifact — `GET /v1/decisions/{id}/receipt` — and is safe to use; what remains prohibited is overstating what it proves beyond the same Evidence it packages.)
- "The Trusted Adapter proves the external operation occurred," "the Adapter gives the Agent authority," or "PayReality trusts the Agent because an Adapter exists" — none of the three are true; see §8.4.
- Any claim that a Trusted-Adapter-mediated Capability, once issued or consumed, is itself enforcement, or proves anything about a downstream action beyond what the underlying Decision already established.
- Any claim that a Runtime Connection's `CAPABILITY_REQUIRED` enforcement-assurance label is independently verified, tested, or enforced by PayReality. It is the customer's own declared claim about their infrastructure.
- Any claim that `DECLARED_DECISION_CHECK`, `VERIFIED`, or `REGISTERED_EXTERNAL_PEP` enforcement assurance exists or can be set. None are implemented.
- "Adapter-mediated enforcement" or similar, implying a real enforcement mechanism exists for the trusted-Adapter path specifically — the same PDP boundary in §6 applies without exception to this path.
- Any claim that Authority Intelligence eliminates the need for a human reviewer; the opposite is the correct and more defensible claim.
- Any specific customer, logo, or case study beyond what genuinely exists (see Section 17).
- Any uptime or SLA number that has not actually been measured under real production load.
- "Zero downtime" or "instant cutover" as a general, ongoing platform property, rather than a description of one specific completed migration event.
- Any SOC 2 claim of any kind; SOC 2 preparation has not begun.
- A named required approver (for example, "routes to the Payments Manager") determined by policy at decision time; policy does not carry this field today, only post hoc resolution records who actually approved.
- REVIEW described as a literal pause that a calling workflow is automatically resumed from; today HUMAN_REVIEW is returned immediately and the caller must poll for resolution, there is no push or callback mechanism.

## 17. Customers, pilots, and references

As of this rewrite, PayReality has no completed enterprise pilot and no reference customer to name. There may be active prospect conversations and proposed proof of concept scenarios in progress; a conversation in progress, or even a detailed proposal sent to a named organization, is not a customer, a pilot, or a case study, and must never be described as one. Say "designed for" or "built for," never "used by," until a real, completed engagement exists and the relevant stakeholder has approved naming it. When a real pilot or customer exists, this section should be updated with the specific, approved fact, not a general upgrade in confidence.

## 18. Terminology table

| Concept | Safe today | Conditions and notes |
|---|---|---|
| Runtime Authority | YES | The decision engine and its ALLOW/DENY/HUMAN_REVIEW outcome. |
| Authority decision | YES | |
| Evaluates before execution | YES | Accurate for PayReality's own step; does not by itself mean the calling system cannot proceed regardless, see the PDP/PEP boundary. |
| Capability Authorization | YES | Not itself enforcement. Requires a downstream system that actually checks it. |
| Verifiable Evidence | YES | Independently verifiable signature and hash chain; verification endpoint today is credential gated, not yet a public transparency log. |
| Trusted Enterprise Facts | YES | Provenance of an assertion, not objective truth; fails closed when missing, expired, or contradictory. |
| Authority Freshness | YES | Review due and authority expired are distinct; only high or critical risk expiry currently forces HUMAN_REVIEW. |
| Authority Intelligence | YES | Proposes candidates with provenance; never auto enforced. |
| Policy Decision Point | YES | The accurate, precise name for what PayReality is today, on both the agent-direct and trusted-Adapter paths. |
| Trusted Adapter | YES | Customer-controlled, customer-deployed; never hosted by PayReality; never itself an enforcement point. |
| Action Mapping | YES | Deterministic, versioned, human-approved; multiple approved versions may coexist. |
| Trusted Connection / Runtime Connection | YES | The authenticated identity and its live deployment scope for the Adapter path, respectively. |
| Authorization Receipt | YES | Real, shipped, named endpoint as of Issue #4. Never describe it as a stronger or second proof beyond the Evidence it packages, and never as proof a downstream action executed. |
| Runtime Enforcement | NO | As an unqualified PayReality capability, on either runtime path. |
| Capability Authorization for a trusted-Adapter decision | YES | Issued subject to a live re-check of the Trusted Connection/Runtime Connection's active status at issuance time (Trusted Integration Phase 5); not itself enforcement, see §8.3. |
| Enforcement assurance: ADVISORY / CAPABILITY_REQUIRED | YES | Customer-declared labels on a Runtime Connection; never independently verified by PayReality, see §8.5. |
| Enforcement assurance: DECLARED_DECISION_CHECK / VERIFIED / REGISTERED_EXTERNAL_PEP | NO | Named in the long-term vision only; no implementation exists, and no code path can set them. |
| Blocks unauthorized actions | NO | |
| Cannot execute without PayReality | NO | |
| Non bypassable | NO | |
| PayReality watches/monitors enterprise systems | NO | The Trusted Adapter is customer infrastructure; PayReality has no standing access to any enterprise system. |
| Enforcement point | CONDITIONAL | Only when describing a real downstream PEP that has actually been deployed, or the reference enforcement adapter, clearly and explicitly labeled as proof of mechanism only. |
| Sequential or multi step approval | NO | Does not exist in the current policy model. |
| Named required approver at decision time | NO | Not determined by policy today; only recorded after the fact upon resolution. |

## 19. Language rules

**Safe words**: evaluates, determines authorization, authorizes, authorization decision, decision control, fail closed, Policy Decision Point.

**Use carefully, not banned, but always with context**: enforce, enforcement, intercept, block, stop, prevent, non bypassable, cannot execute without, sits between AI and enterprise systems, guarantees.

"Enforcement" and its relatives remain valid when the sentence is doing one of the following, and should be avoided otherwise:

1. Discussing enforcement as a general architectural concept (for example, explaining what a Policy Enforcement Point is in the abstract).
2. Discussing a future, not yet built, PEP integration, clearly marked as future or conditional.
3. Explaining that another enterprise system or enforcement point, a real one that actually exists downstream, acts on PayReality's decision; the acting is attributed to that system, not claimed as something PayReality itself does.
4. Discussing the reference enforcement adapter specifically, while clearly and immediately stating its limits (proof of mechanism only, not production enforcement, does not prove no other path exists).

Before publishing any sentence using one of the careful words, ask: could a skeptical enterprise security reviewer, reading only this sentence, conclude that PayReality itself stops a non compliant caller from acting? If yes, and that is not true today, rewrite the sentence.

## 20. Preserved disciplines

These disciplines from the prior version of this guide remain valid and are restated here rather than discarded:

- No SOC 2 claim of any kind; SOC 2 preparation has not begun.
- No specific customer, logo, or case study beyond what genuinely exists (Section 17).
- No uptime or SLA number that has not been measured under real production load.
- No claim that Authority Intelligence eliminates the need for a human reviewer.
- No claim of "zero downtime" or "instant" cutover as a general, ongoing platform property.

## 21. Tone

Enterprise, precise, confident without exaggeration. This platform's actual story, real cryptographic evidence, real OPA evaluation, a real multi tenant Azure production environment, real fact provenance and freshness tracking, a real capability binding mechanism, and a real, honestly disclosed boundary at the edge of enforcement, is stronger than any generic AI category buzzword or any overstated enforcement claim. Every sentence in customer facing material should survive the question "could a skeptical enterprise security reviewer ask us to prove this in the first pilot call," because for this product, unusually, almost everything upstream of the enforcement boundary can actually be proven, and the boundary itself is disclosed rather than hidden.
