# Enterprise Messaging Guide

**Purpose**: the single source of truth for how PayReality's Runtime Authority platform should be described, everywhere. Every other Milestone 8 deliverable (website copy, sales material, pilot documentation) should trace back to the definitions in this document, not restate them independently. Every factual claim below is labeled VERIFIED (checked directly against the shipped platform across Milestones 1-7), INFERRED (a reasonable conclusion from verified facts, not itself directly tested), or PROPOSED (a messaging choice being recommended, not a fact).

## 1. The one-sentence description

**PROPOSED, as the canonical version**: "Runtime Authority is the authorization layer that decides, before an AI agent acts, whether it actually has the authority to take that action, and produces a cryptographically signed record of that decision."

Three words carry the entire claim and should never be dropped in any shortened version: **before** (pre-execution, not after-the-fact review), **authority** (a specific, delegable, enterprise concept, not a vague safety notion), **signed** (independently verifiable, not just logged).

## 2. What Runtime Authority actually is (VERIFIED)

A pre-execution authorization runtime for AI agents acting as autonomous parties in real business transactions (payments, purchase orders, access grants, and similar). The mechanism, exactly as shipped:

1. An AI agent, holding an Ed25519 certificate issued at registration, signs an **Intent**: a structured description of the action it wants to take (an action type, an amount, a counterparty, a resource, and so on).
2. The platform verifies the signature against the agent's active certificate, then evaluates the Intent against two things: the organization's compiled **Runtime Policies** (deterministic rules, evaluated by a real Open Policy Agent instance, never a language model) and the **Authority Graph** (who has delegated what authority to whom, extracted from the organization's own governance documents).
3. The result is exactly one of three outcomes: **ALLOW**, **DENY**, or **HUMAN_REVIEW**. There is no fourth outcome and no partial/fuzzy result; a Runtime Policy either matches deterministically or it doesn't.
4. Every decision produces a signed **Evidence** record (Ed25519, canonical JSON, hash-chained to the record before it), independently verifiable by anyone holding PayReality's published public key, without needing to trust PayReality's own systems or ask PayReality to vouch for it.

This is a **policy decision point** for autonomous AI actors, with a cryptographic evidence trail, not a chat interface, not a dashboard product, and not a model.

## 3. What it is not, and the exact replacement language (Phase 3)

| Remove | Why it's wrong | Replace with |
|---|---|---|
| "AI governance platform" | A category so broad it could mean model risk management, content moderation, prompt review, or bias auditing, none of which this product does | "Runtime Authority platform" or "pre-execution authorization runtime for AI agents" |
| "AI observability" | Observability watches and logs what already happened; this product's entire value is deciding **before** anything happens | "Pre-execution authorization" or "runtime authorization" |
| "Agent monitoring" | Monitoring is passive; this product is an active decision point an agent's action cannot bypass | "Runtime authorization" or "authority verification" |
| "AI safety" (used generically) | Too broad, invites comparison to model-alignment work this product has nothing to do with | "Delegated authority enforcement" or "authorization for autonomous agents" |
| "Guardrails" | Implies content filtering or prompt-level constraints on a model's output; this product constrains real-world actions, not text generation | "Pre-execution authorization" |

**The one defensible comparison, stated precisely**: existing AI platforms (model providers, agent frameworks) give an agent *capability*, the ability to call a function, place an order, move money. None of them independently verify that the agent's specific action, at that specific moment, is something the organization has actually authorized, and none of them produce a cryptographically verifiable record of that check. Enterprise identity systems (Okta, Azure AD, and similar) authenticate *who* is acting but were built for human sessions, not fine-grained, deterministic, per-transaction authority decisions for autonomous, non-human actors. Runtime Authority is the layer that sits specifically in that gap: after identity, before execution.

## 4. Authority Intelligence (VERIFIED)

The AI-assisted layer that turns an organization's real, existing governance documents, delegation-of-authority memos, approval matrices, signing schedules, into machine-readable Authority Graph data: named principals and their reporting relationships, resources, operations, delegation/escalation/inheritance relationships, and (Phase 3 of the Authority Intelligence Program) an explicit accounting of every conflict, gap, and open question the extraction found, each with its own citation back to the source document and the model's own stated reasoning and assumptions. As of Milestone 6, this runs on Azure AI Foundry, confirmed live via real extractions producing genuine model reasoning, not a deterministic template.

**The one non-negotiable messaging constraint**: nothing extracted this way ever becomes a live, enforced Runtime Policy without an explicit human promotion and approval step. Say this plainly in every piece of material that mentions Authority Intelligence; it is the answer to the single most predictable enterprise objection ("so an AI decides our authority rules?").

## 5. Runtime Policies and OPA (VERIFIED)

Policies are structured data (scope, conditions, effect), never natural-language rules interpreted at decision time. They compile to real Rego and are evaluated by a real, embedded Open Policy Agent instance, the same open-source engine used for policy-as-code in cloud infrastructure and Kubernetes. A policy's lifecycle is explicit and auditable: draft, submitted for review, approved, activated (which triggers real compilation and a real OPA deployment with a recorded bundle hash), and eventually deprecated, archived, or rolled back. Nothing about evaluation is probabilistic; the same input against the same active policy set produces the same decision every time, which is precisely why the Evidence record is worth signing at all.

## 6. Evidence (VERIFIED)

Every decision, ALLOW, DENY, or HUMAN_REVIEW, produces a signed record: the Intent, the outcome, the specific policy version and Authority context that produced it, and a payload hash chained to the prior record. Verification is a real, independent cryptographic check against a published public key, not a "trust our dashboard" claim. A signing-key registry (added specifically to close this gap) means a key rotation never breaks verification of Evidence signed under a prior key.

## 7. Multi-tenancy and Enterprise Surface Isolation (VERIFIED)

Every organization's Runtime Policies, OPA packages, Authority Graph data, Evidence, agents, Blob-stored documents, and Azure AI Search index entries are isolated by organization at the data layer, not just the UI layer. A second organization was created and live-tested specifically to prove this (Milestone 5): it saw zero agents, zero policies, and zero documents belonging to the first. This is a real, tested property, not an assumption.

## 8. SDK (VERIFIED)

A Python SDK, versioned, generating real Ed25519 keypairs client-side and signing every Intent before it ever leaves the calling process. The private key never transits to PayReality's servers at registration or at any later point.

## 9. Azure architecture (VERIFIED)

Production runs on Azure Container Apps, Azure Database for PostgreSQL Flexible Server, Azure Key Vault, Azure AI Foundry, Azure AI Search, and Azure Blob Storage, secured with Managed Identity throughout, no shared static credentials where identity-based access is possible. The production domain, `api.aisecurewatch.com`, is live on this infrastructure with a real, auto-renewing certificate (Milestone 7). This is real, current, and appropriate to say in present tense, not "planned" or "in progress."

## 10. Claims that must NOT be made (guardrails on this document's own guidance)

- **No SOC 2 claim of any kind** until Milestone 8's own Launch Readiness assessment (below) is acted on; SOC 2 preparation has not begun.
- **No specific customer, logo, or case study** beyond what genuinely exists; as of this milestone, PayReality has no completed enterprise pilot and no reference customer. Say "designed for," "built for," never "used by."
- **No uptime/SLA number** has ever been measured under real production load; do not invent one.
- **No claim that Authority Intelligence eliminates the need for a human reviewer**; the opposite is the correct and more defensible claim.
- **No claim of "zero-downtime" or "instant" cutover capability** as a general platform property; that phrase describes one specific completed migration event (Milestone 7), not an ongoing product feature.

## 11. Tone

Enterprise, precise, confident without exaggeration. This platform's actual story, real cryptographic evidence, real OPA evaluation, a real multi-tenant Azure production environment, a real (if young) engineering history visible in its own architecture decisions, is stronger than any generic AI-category buzzword. Every sentence in customer-facing material should survive the question "could a skeptical enterprise security reviewer ask us to prove this in the first pilot call," because for this product, unusually, almost everything can actually be proven: the Evidence is signed, the policies are deterministic, the isolation is tested.
