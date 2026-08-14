# Pilot Program Guide

**Status: PROPOSED in full.** No enterprise pilot has run yet; there is no track record to draw on, so every stage below is a designed process grounded in verified platform capability, not a refinement of lived pilot experience. This document should be revised after the first real pilot, not treated as settled.

## Why this document exists

Milestone 8 marks the shift from building the platform to preparing it for the first real customers. A pilot program only works if it asks for exactly what the platform can actually deliver today (Milestones 1-7's verified capabilities) and is explicit about what it cannot yet promise (no SOC 2, no reference customer, no measured uptime under real load). This guide is written against that honest baseline.

## 1. Qualification

**Who this pilot is for**: an enterprise with at least one AI agent (or a near-term plan for one) taking real, consequential actions, financial transactions, purchase approvals, access grants, and an existing, even if informal, delegation-of-authority structure (who is allowed to approve what, up to what limit). The platform's Authority Intelligence layer is built specifically to extract structure from documents that already exist (memos, approval matrices, signing schedules); a prospect with zero written authority documentation is a weaker fit for a fast pilot, since the extraction step has nothing to work from.

**Qualification questions**, asked before a pilot is scoped:
- Does at least one AI agent or agentic workflow already exist, or is one committed within the pilot window?
- Does a real authority/delegation document exist (even an informal one) that could be uploaded to Authority Intelligence on day one?
- Is there a named technical owner who can integrate the SDK or call the API directly?
- Is there a named business owner who can review and approve the first Runtime Policy?
- What does success look like in the prospect's own words, stated before the pilot starts (see Success Metrics, below), not inferred afterward?

**Disqualifying signals, stated plainly**: a requirement for SOC 2 attestation before any pilot can begin (not available yet, see Launch Readiness); a requirement for on-premises deployment (this platform is Azure-hosted, multi-tenant, not designed for single-tenant on-prem); an expectation of a pre-built integration with a specific enterprise system this platform has not yet built a connector for (today's integration path is the API/SDK directly, not a catalog of pre-built connectors).

## 2. Discovery

A structured, time-boxed session (recommend one to two weeks, not open-ended) covering:

- **The real authority structure**: collect the actual documents (delegation memos, approval matrices) that Authority Intelligence will process. This is the single highest-leverage discovery artifact; everything downstream depends on it.
- **The real agent or workflow**: what action does it take, what's the current (pre-pilot) authorization path, what would "properly authorized" mean for this specific action.
- **The real integration surface**: how will Intents actually reach the platform, direct API calls, the Python SDK, or an existing internal orchestration layer that would need a thin adapter.
- **The organization's own tenancy needs**: one organization, or does the pilot need to represent an internal structure (business units, departments) the platform's own multi-tenant model can express.

**Output of discovery, always a written document**: the specific action(s) in scope, the specific document(s) Authority Intelligence will process, the specific success metrics (below), and an explicit non-goal list (what this pilot will *not* attempt to prove).

## 3. Deployment

Real steps, matching what the platform actually requires:

1. **Organization created** via the Organization Lifecycle (a real, tested, live capability since Milestone 3): one organization per pilot customer, never a shared or default organization.
2. **Owner account provisioned and claimed**: the pilot's named technical or business owner receives real credentials, not a shared operator key.
3. **Authority Intelligence corpus uploaded**: the real documents from Discovery, processed for real, producing a reviewable Authority Graph (principals, resources, relationships, conflicts, gaps, questions), never presented as final until a human reviews it.
4. **At least one Runtime Policy promoted and activated**: taken from an Authority-Intelligence-extracted candidate, through the platform's own real lifecycle (submit for review, approve, activate), producing a real, versioned, OPA-deployed policy with a recorded bundle hash.
5. **At least one Agent registered and activated**: a real Ed25519 certificate issued, the agent moved from `registered` to `active` through the platform's own lifecycle endpoint, matching exactly how the platform's own smoke test and every live validation in this engagement has proven the mechanism works.

## 4. Integration

Two supported paths today, both real and both already used in this engagement's own validation:

- **Direct API integration**: the caller signs its own Intent (Ed25519) and calls `POST /v1/intents` directly. Appropriate for a team already comfortable with request signing.
- **Python SDK**: `Agent(...)` handles keypair generation and signing; the caller only constructs the Intent's business fields. Appropriate for the common case and the path with the least new code for the pilot's engineering team to write.

**Not yet available, say so plainly if asked**: pre-built connectors for specific ERPs, procurement systems, or workflow tools. The integration surface is the API/SDK; anything system-specific is custom integration work scoped separately, not a catalog item.

## 5. Validation

A pilot is not "done" when Intents start flowing; it's validated when the specific scenarios from Discovery have each been demonstrated with real, reviewable Evidence:

- At least one real ALLOW decision, matching a documented delegation.
- At least one real DENY or HUMAN_REVIEW decision, matching a documented limit being exceeded, since this (not the ALLOW case) is what proves the authorization is actually doing something, not rubber-stamping.
- Independent Evidence verification performed by the customer's own team, not just PayReality's dashboard, using the published verification mechanism, since the entire point of a signed record is that it doesn't require trusting PayReality's word for it.
- A Runtime Policy Simulator run against at least one proposed change, showing the customer what would happen to a hypothetical Intent before any real policy change ships (a live, working capability, fixed and re-verified as of Milestone 6).

## 6. Success metrics

Defined per pilot during Discovery, never generic, but every pilot's metric set should include at minimum:

- **Time from document upload to a reviewable Authority Graph**: a direct measure of Authority Intelligence's actual value, and something the platform can genuinely report today.
- **Time from policy draft to activation**: measures whether the review/approve/activate lifecycle fits the customer's actual governance cadence, not just the platform's own speed.
- **Number of decisions correctly matching the customer's own expected outcome**, judged by the customer's own domain expert against the documented authority structure, not by PayReality.
- **Whether Evidence verification succeeded independently**, a binary, unambiguous, high-value metric precisely because it doesn't depend on subjective judgment.

## 7. Expansion

A successful pilot's natural next step is widening scope within the same organization, more agents, more policy categories, more of the real authority structure represented, before any conversation about a second organization or a broader company rollout. Expansion criteria (PROPOSED): the pilot's own success metrics were met, the customer's technical owner can independently create and activate a new Runtime Policy without PayReality's help, and no unresolved Evidence-verification or isolation concern remains open.

## 8. Reference customer

**No reference customer exists as of this milestone.** This section states the intended process for when one does, not a claim that one is available now. The first pilot that reaches Expansion with a customer willing to be named and quoted becomes the candidate; permission to reference the engagement (name, logo, quote, or all three) is a separate, explicit ask, never assumed from a successful pilot alone. Until that happens, every sales and marketing artifact produced in this milestone should say "designed for" and "built for," never "used by" or "trusted by," and PROPOSED case-study language elsewhere in this milestone's deliverables is written as a template to fill in later, not as if it already describes a real engagement.
