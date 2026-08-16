# Runtime Authority Thesis Evolution

## 1. Purpose

This document exists to preserve the reasoning behind a shift in how PayReality's founders are thinking about the Runtime Authority problem, based on a set of external conversations (founder, prospective customer, and enterprise practitioner). It is a research record, not a specification: its job is to make sure the evidence and the reasoning that produced a change in thinking are not lost, so the founder and cofounder can return to it later, test it against more evidence, and decide deliberately whether and how it should change the product.

**This document is a research record, not an approved product specification.**

Nothing in this document authorizes a change to the Runtime Authority engine, the API, the frontend, the website, or any database schema. Where this document identifies something the current architecture does not yet do, that is recorded as an open question or a hypothesis, not as a requirement.

## 2. Original Thesis

PayReality's original framing, as built into the current Runtime Authority engine, is approximately:

> AI agents increasingly have the ability to take consequential actions on behalf of organizations. Organizations need a deterministic runtime mechanism to determine whether an AI agent is authorized to execute a high-impact action before execution.

This thesis is embedded directly in the shipped system: a `RuntimePolicy` (principal, action, scope, flat conditions, effect) is compiled to Rego and evaluated by OPA at the moment an `Intent` is submitted, producing exactly one of `ALLOW`, `DENY`, or `HUMAN_REVIEW`. The implicit assumptions behind this framing were:

- That "is this action authorized" is answerable as a single, point-in-time rule evaluation against a known principal, action, and set of conditions.
- That the organization's rules for what is authorized can be expressed directly as flat, declarative conditions (thresholds, scopes, roles) without needing to represent the human process that produced those rules.
- That the moment of execution is the meaningful moment to evaluate authority, rather than a later step in a longer decision process that happens before execution.

## 3. What Recent Conversations Changed

The original question the system was built to answer is:

> "Is the AI authorized to perform this action?"

Recent conversations, most directly with Lourens Joubert, surfaced a deeper and prior question:

> "What makes this action authorized in the first place?"

This distinction matters because a runtime rule evaluation (the first question) can only be as correct as the rules it evaluates, and those rules are themselves the output of something else: an organizational process, a set of SOPs, a chain of delegated authority, and a sequence of approvals that happens *before* anyone (human or AI) reaches the point of execution. If PayReality only ever answers the first question, it risks encoding a shallow, ad hoc approximation of authorization logic instead of the organization's actual, already-existing decision process. The open question this raises is not "was our rule engine wrong" (it evaluates the rules it is given correctly and deterministically); it is "were we asking the engine to evaluate the right thing."

## 4. The Human-Process Insight

**INTERPRETATION**, grounded in the Lourens Joubert conversation (see §8 for the underlying observation): a human performing a consequential action inside an organization does not consult a single, flat rule at the moment of execution. Their authority to act is the end of a longer chain:

```
Human:
SOP
  -> process
    -> authority
      -> approvals
        -> decision
          -> execution
```

The corresponding chain PayReality's current system evaluates is shorter, and starts later:

```
AI (current Runtime Authority):
SOP/process (not modeled today)
  -> authority (partially modeled: RuntimePolicy scope, Authority Graph delegation)
    -> approvals (modeled only as a single generic HUMAN_REVIEW escalation)
      -> runtime evaluation (fully modeled: OPA/Rego, deterministic)
        -> execution
```

**HYPOTHESIS**: an AI agent, if it is to be trusted with consequential actions the way a human is, may need to reproduce the organization's existing decision process (the same SOP, the same authority chain, the same approval sequence a human would go through), rather than simply receive a generic runtime permission grant that was defined independently of that process.

This is not claimed to be universally correct. Lourens' own framing was conditional: "the correct approach depends on the transaction type and the definition of 'transaction.'" Some transaction types may genuinely be simple enough that a flat rule is a faithful representation of the organization's authority; others may not be. This document does not assume which is which.

## 5. Emerging Authority Model

**HYPOTHESIS** -- a conceptual model for discussion, not an implemented or approved architecture:

```
Organization
  |
  v
SOPs / operating procedures
  |
  v
Business process
  |
  v
Roles / principals
  |
  v
Delegated authority
  |
  v
Limits / conditions
  |
  v
Approval requirements
  |
  v
Transaction context
  |
  v
AI action proposal
  |
  v
Runtime Authority evaluation
  |
  v
ALLOW / BLOCK / ESCALATE
  |
  v
Execution
```

Brief description of each layer:

- **SOPs / operating procedures**: the organization's documented (or undocumented) standard way of handling a given kind of action. Today, entirely outside PayReality's data model.
- **Business process**: the sequence of steps an SOP implies (who does what, in what order). Not modeled today.
- **Roles / principals**: who is entitled to act. Modeled today (`Principal`, `Role`, `BusinessUnit`/`Department`/`Team`).
- **Delegated authority**: who has granted authority to whom, and under what bounds. Partially modeled today (`AuthorityRelationship` with `delegation`/`escalation`/`inheritance` kinds, validity windows).
- **Limits / conditions**: thresholds and constraints on an authorized action. Modeled today (`RuntimePolicy.conditions`, flat AND-only).
- **Approval requirements**: who must sign off, in what sequence, before an action proceeds. Modeled today only as a single-step generic escalation (`HUMAN_REVIEW` -> one `resolve_decision` call); no multi-step, role-gated approval chain exists.
- **Transaction context**: the specific facts of the transaction under evaluation (amount, counterparty, timing). Modeled today (`Intent`, `AuthorityContext`).
- **AI action proposal**: the AI's request to act. Modeled today (`Intent` submission).
- **Runtime Authority evaluation**: the deterministic, point-in-time check. Modeled today, and the strongest, most proven part of the system (OPA/Rego, Historical Policy Binding, per-condition explainability).
- **ALLOW / BLOCK / ESCALATE**: the outcome. Modeled today.
- **Execution**: what happens after the decision. Outside PayReality's current scope; the calling system executes.

The distinction this model is meant to draw out: everything above "Limits / conditions" in this diagram is, today, either unmodeled or only partially modeled by PayReality, and largely already exists inside the organization in some other form (documents, ERP/IAM systems, people's heads). PayReality's existing strength is at and below "Runtime Authority evaluation." The open question is whether PayReality's role should expand upward to *represent* those upper layers, or stay focused on faithfully *enforcing* whatever the organization's existing systems for those layers already produce.

## 6. What PayReality May Actually Be

**HYPOTHESIS**:

> PayReality may not be the system that invents an organization's governance.
>
> It may be the enforcement layer that makes an organization's existing authority structures technically enforceable when autonomous systems attempt to act.

**STATUS: HYPOTHESIS -- NOT YET VALIDATED**

## 7. What We Still Don't Know

This is an open-question register. None of these are answered by this document; they are listed to make the next round of research concrete.

### Organizational process
- How are SOPs represented inside a typical enterprise customer (formal documents, informal tribal knowledge, workflow-tool configuration)?
- Where do authoritative SOPs live, and who owns changes to them?
- Are they structured (machine-readable) or mostly free-text documents?
- How frequently do they change, and how would a runtime system stay current?

### Authority
- Where does delegated authority actually live in a real customer environment: IAM, ERP, HR systems, approval-workflow tools, policy documents, or scattered across several?
- How is delegation represented, and how does inheritance work in practice (e.g., does a delegate's authority expire when the delegator's does)?

### Transaction
- What actually constitutes "a transaction" for authorization purposes, and does this differ meaningfully across transaction types (Lourens' own framing)?
- How different are authorization rules across transaction types?
- What is the actual "point of no return" after which an action cannot be safely undone?

### Runtime
- What must be evaluated immediately before execution, versus what can safely be evaluated earlier in the process?
- Which state is immutable once a workflow begins, and which can still change?

### Changes during execution
- What should invalidate an already-approved action: authority revocation, policy changes, external risk changes, supplier changes, amount changes, timeouts, or other external events?
- Lourens' answer to a version of this question was explicitly conditional on transaction type and the definition of "transaction" -- no universal answer should be inferred from a single conversation.

### Platform boundary
- What should PayReality itself enforce, versus what should remain inside the customer's existing workflow systems?
- What should be delegated to the AI platform the agent runs on (e.g., HappyRobot), if that platform already has its own workflow/governance controls?
- Where does Runtime Authority need to sit relative to platforms that already contain workflow and governance logic? This is an open strategic question raised directly by the Leor Schiffer conversation (§8) and is not resolved here.

### Enterprise Knowledge
- What information is actually required at evaluation time versus resolvable earlier?
- Which facts need to be resolved before evaluation, and by what process?
- Which information must never be fetched live during deterministic evaluation (a constraint the existing Enterprise Knowledge design already takes as a hard requirement, per `PAYREALITY_ENTERPRISE_KNOWLEDGE_RESOLUTION_VISION.md`)?

## 8. Research Evidence

| Source | Role/context | Observation | What it suggests | Confidence |
|---|---|---|---|---|
| Lourens Joubert | Founder-level conversation partner, operational/process background | At the payment stage, his system makes no further judgment; stage-gating happens earlier in the process. "How would a human do it? Replicate it." Challenged PayReality: "I also still distinctly get the feeling you are still trying to solve for the end without understanding the analysis of what gets you there. Ie sops etc." | The runtime evaluation point may be too late in the process to be the primary place authorization logic is defined; the prior process/SOP analysis may be the more important thing to understand and represent first. | MEDIUM (a single, direct, first-hand conversation with someone with relevant operational experience; not independently corroborated) |
| Lourens Joubert | Same conversation, follow-up | Whether an already-approved transaction should be invalidated by authority revocation, external risk changes, policy changes, or other transaction-specific conditions depends on the transaction type and the definition of "transaction." | No universal rule exists for execution-time invalidation; it is transaction-dependent. Do not generalize a single answer. | LOW (explicitly non-generalizable per the source's own framing) |
| Wesley Fredericks (Supertube Associates) | Practitioner/consulting conversation | Enterprise clients are raising governance, policy, and standards concerns as AI becomes more capable. Larger organizations are more conservative about letting autonomous agents act on their data/systems; smaller organizations are more willing to experiment. Governance maturity may progress from frameworks/policies, to human-in-the-loop controls, to deeper technical enforcement. | There may be a market maturity curve, with technical enforcement (PayReality's current model) as a later stage rather than an immediate ask for most organizations. | LOW (a single practitioner's observation from one conversation, not statistically validated) |
| Bernard Arpajou de Araluze (HappyRobot) | First customer contact | Recommended speaking with deployment teams, since they have more visibility into governance implementation than first-line contacts. | Deployment-facing roles may be a better source of concrete governance detail than sales/first-contact roles. | LOW (a referral, not a substantive finding itself) |
| Leor Schiffer (HappyRobot) | Deployment-oriented conversation, referred by Bernard | "We're handling all that in our platform tbh," in response to a question about governance implementation around enterprise AI agents. | AI platforms may increasingly build their own workflow/governance controls in-house. This raises an open strategic question about where Runtime Authority needs to sit when the AI platform itself already has governance logic; it does not indicate HappyRobot has adopted or validated PayReality's thesis, and does not confirm their architecture in either direction. | LOW (a single short statement; substance and scope of their in-platform governance were not detailed in the conversation) |
| Pretty Newman | Doctoral/research-oriented conversation partner | Responded positively to the framing that "authority becomes a fundamental architectural problem" as AI moves from assisting people to acting on behalf of organizations, and said it intersects with her own research questions. | A potential future research collaboration or validation conversation. No conclusions can be drawn yet; the substantive conversation has not happened. | LOW (an expression of interest, not a finding; conversation still pending) |
| CJ Claassen, Ernst Grosse-Heitmeyer, other enterprise AI contacts | N/A | No substantive conversation evidence available in the current record beyond contact identification. | Not enough evidence to include a finding. | N/A -- omitted per instruction not to manufacture conclusions from a profile alone |

## 9. Research Plan

**Recommendation: do not immediately build a new major product subsystem based on the hypotheses in this document.**

Instead, the next step should be a structured discovery phase: interview approximately 10-15 enterprise practitioners and map real workflows, rather than generalizing from the handful of conversations in §8.

Prioritize:

- Enterprise AI leaders
- Deployment teams
- Enterprise architects
- Operational systems leaders
- Governance/risk leaders
- CIO/CTO-level practitioners

For each interview, investigate:

1. Pick one real workflow.
2. How does a human perform it?
3. What SOP governs it?
4. Who has authority?
5. What are the limits?
6. What approvals are required?
7. What systems provide the necessary information?
8. What exceptions exist?
9. What can change while the transaction is in flight?
10. What would prevent the organization from allowing an AI to perform the action autonomously?
11. What must be demonstrated before they would trust autonomous execution?
12. What would cause an already-approved action to be stopped?

## 10. Workflow Mapping Template

Reusable template for each interview in the research plan above:

```
WORKFLOW:
BUSINESS ACTION:
HUMAN ACTOR:
AI ACTOR:
SYSTEMS INVOLVED:

SOP:
AUTHORITY SOURCE:
DELEGATION:
LIMITS:
CONDITIONS:
REQUIRED APPROVALS:
EXCEPTIONS:

EXECUTION POINT:
POINT OF NO RETURN:

WHAT CAN CHANGE DURING EXECUTION?

WHAT WOULD INVALIDATE AUTHORIZATION?

WHAT INFORMATION MUST BE AVAILABLE AT RUNTIME?

WHAT WOULD THE ORGANIZATION REQUIRE BEFORE TRUSTING AN AI TO DO THIS?
```

## 11. Implications for Existing PayReality Architecture

This section reviews what already exists against the emerging thesis in §§4-6. It does not propose any code, schema, or architecture change. Classifications below are grounded in a fresh read of the current documentation and code (not assumed from this document's own hypotheses).

| Component | Current state (LIVE FACT) | Classification against the emerging thesis |
|---|---|---|
| Runtime Authority / Runtime Policy / OPA-Rego evaluation | Flat rule model: `Scope{principal, action, agent?, resource?}`, AND-only `Conditions`, `Effect{allow/deny/require_human_review}`, compiled to Rego, evaluated deterministically. No SOP or business-process concept exists in the schema. | **Already compatible** as the deterministic evaluation layer at the bottom of the model in §5; **potentially needs refinement** if upper layers (SOP/process/approval chains) are ever represented, since today's flat conditions would need to express whatever those layers produce. |
| Authority Graph / delegation / principals | `BusinessUnit`/`Department`/`Team`/`Resource` tables exist; `Principal` has real org/dept/team/role columns; `AuthorityRelationship` models `delegation`/`escalation`/`inheritance` edges with validity windows, traversed via recursive SQL (not a graph database). Documented in `PHASE_4_AUTHORITY_GRAPH.md` (headed "proposed," but confirmed built and wired into decision-context enrichment). | **Already compatible** with the "Roles / principals" and "Delegated authority" layers in §5; multi-step, role-gated approval *chains* specifically are **unknown / likely needs refinement** -- delegation and escalation edges exist, but a sequenced, multi-party approval chain is a different (and currently absent) concept. |
| Approvals (HUMAN_REVIEW / resolve_decision) | Exactly one generic escalation outcome (`HUMAN_REVIEW`), resolved by a single free-text `resolve_decision` call (one reviewer, one event, no role requirement, no sequencing). Explicitly single-step; `RUNTIME_AUTHORITY_TRANSFORMATION.md` names "Approval Structures" as considered and deferred. | **Potentially needs refinement** if real organizational approval chains (the "Approval requirements" layer in §5) turn out to require multi-step, role-gated sequencing -- but this should not be assumed without evidence from §9's research plan. |
| Evidence / decision records / Historical Policy Binding | Each Decision's Evidence persists exact policy version/bundle/manifest, principal/agent identity, resolved authority context, and (for HUMAN_REVIEW) reviewer/outcome. Phase 2B (this repository's most recent milestone) added per-condition explainability from the exact historical policy state. | **Already compatible** and, if anything, a strength: this is the most mature part of the system for proving *what was actually evaluated and why*, which would remain valuable regardless of how the upper layers evolve. |
| Runtime Policy Simulator | Dry-runs a single hypothetical Intent against the real compiled bundle; rule-level explainability, saved scenarios, batch simulation. Rule/decision-level only -- no process- or workflow-level simulation. | **Already compatible** at the rule level; **potentially needs refinement** if a future need emerges to simulate a multi-step process rather than a single decision point -- not assumed here. |
| Multi-tenancy | Org-scoped throughout; `BusinessUnit -> Department -> Team` hierarchy already exists on `Principal` and is resolved into decision context via `authority_context_service.py`. | **Already compatible** with representing organizational structure; does not by itself represent SOPs or process, which are a different concept from org-unit hierarchy. |
| Enterprise Knowledge | Designed, not built (`ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md`: "a design, not a build"; `PAYREALITY_ENTERPRISE_KNOWLEDGE_RESOLUTION_VISION.md`: "Living document... Exploratory... Nothing in this document should be read as a commitment"). Designed to resolve external business facts (e.g., vendor-approved, AML-passed, budget-available) as versioned local snapshots, never live calls, to preserve OPA's determinism. Its own open-questions section already flags, unresolved, whether business assertions could resemble a workflow-like dependency graph. | **Unknown** -- its existing design is about verifying prerequisite facts, not about representing SOPs or approval processes directly, but the two could turn out to be related once more evidence exists. This document does not conclude that Enterprise Knowledge should be built to address the SOP/process gap; that would be an unjustified leap from a design intended to solve a different problem. |

## 12. What We Should NOT Do Yet

- Do not build Enterprise Knowledge merely because it sounds necessary.
- Do not redesign the Runtime Authority engine.
- Do not add execution re-checking without evidence.
- Do not assume every transaction requires the same authorization model.
- Do not assume SOPs can simply be converted into OPA policies.
- Do not assume AI platforms are insufficient.
- Do not position PayReality against existing AI platforms until the boundary is better understood.
- Do not treat a handful of interviews (or the conversations in §8) as product validation.

## 13. Current Working Thesis

> Organizations already possess systems of authority -- SOPs, policies, roles, delegated permissions, approval thresholds, exceptions and operating processes -- but these systems were primarily designed around human actors. As AI systems become capable of taking consequential actions, organizations need a way to make those existing authority structures enforceable when an autonomous system attempts to act.
>
> PayReality's potential role is to provide that runtime enforcement layer.

**STATUS: WORKING HYPOTHESIS**

**VALIDATION STATUS: IN PROGRESS**

**NO ARCHITECTURAL CHANGE APPROVED FROM THIS DOCUMENT**

## 14. Decision Gate

Proceed toward any implementation only if multiple independent enterprise conversations (per the research plan in §9) demonstrate recurring patterns around:

- Authority representation
- SOP/process enforcement
- Delegated authority
- Approval boundaries
- Runtime enforcement
- Execution-time changes

No specific feature described or implied in this document should be treated as mandatory until those patterns are established across multiple independent sources, not inferred from the single-conversation evidence in §8.
