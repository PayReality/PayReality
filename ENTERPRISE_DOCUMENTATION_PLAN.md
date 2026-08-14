# Enterprise Documentation Plan

**Purpose**: a plan for the eight customer-facing documentation sets Phase 7 names, not the guides themselves at full length. Writing all eight in full now, before a single real pilot customer has asked a single real question, risks documenting an imagined workflow instead of an actual one. This plan specifies audience, scope, structure, and source-of-truth for each, so each can be written efficiently, accurately, and in the right order once needed, drawing on the internal `SPECIFICATION/` documents (already accurate, already maintained across every prior milestone) as the ground truth rather than re-deriving platform behavior from scratch.

## Sequencing recommendation (PROPOSED)

Not all eight are equally urgent before the first pilot. Recommended order:

1. **Administrator Guide** and **Developer Guide**, needed on day one of any pilot (Deployment and Integration, per the Pilot Program Guide).
2. **Runtime Authority Guide** and **Authority Intelligence Guide**, needed as soon as the pilot's first real documents and policies are being worked with.
3. **Security Guide**, needed before or during any security review a pilot prospect's own team runs, which for an enterprise buyer is realistically before contract signature, not after.
4. **Architecture Guide** and **Operations Guide**, useful earlier for a technically sophisticated prospect but not blocking for a first pilot.
5. **Integration Guide**, expand only once a second, materially different integration pattern exists beyond direct API/SDK use; writing it now would mean documenting a single case as if it were a catalog.

## 1. Administrator Guide

**Audience**: the pilot's named business/operations owner (Pilot Program Guide's "business owner"), not necessarily an engineer.
**Source of truth**: `SPECIFICATION/`'s organization/RBAC/settings sections, live-verified in Milestones 3 and 5.
**Scope**: creating and configuring an organization; inviting members and assigning roles (Owner, Governance Admin, Agent Admin, Reviewer, Auditor, Executive, each already a real, shipped role with a real, fixed permission set, never "check roles directly," per the platform's own RBAC discipline); reviewing and approving Runtime Policies and Authority Intelligence extraction candidates; managing API keys; organization lifecycle actions (deactivate, reactivate, archive) and what each actually does to the organization's data (nothing is deleted by deactivation).
**Explicitly out of scope for this guide**: writing signed Intents or touching the API directly, which belongs in the Developer Guide.

## 2. Developer Guide

**Audience**: the pilot's named technical owner.
**Source of truth**: the Python SDK's own README/docstrings, `scripts/smoke_test.py` as a working reference implementation, and the live API itself (`docs/openapi.json`).
**Scope**: installing the SDK, generating an Agent's keypair, registering and activating an Agent (the two-step `registered` to `active` lifecycle, including why the step exists: a freshly issued certificate is not usable for signing until explicitly activated), constructing and submitting a signed Intent, handling the three possible outcomes (ALLOW, DENY, HUMAN_REVIEW), and verifying Evidence independently.
**A concrete decision this plan makes now**: this guide should be built from `scripts/smoke_test.py` directly, since that script is a real, currently-passing, end-to-end working example against live production (proven repeatedly across Milestones 5-7), not a hypothetical code sample. Documentation drift is the likeliest single failure mode for a developer guide; anchoring it to a script that is actually run against real production in every milestone is the concrete mitigation.

## 3. Security Guide

**Audience**: a prospect's security/compliance reviewer, likely never speaking to PayReality directly during their own internal review.
**Source of truth**: `SPECIFICATION/14_SECURITY_MODEL.md`, already comprehensive (authentication mechanisms, RBAC, crypto choices and their rationale, threat model with an explicit PASS/residual-risk table).
**Scope**: authentication and authorization model; cryptographic choices (Ed25519 for signing, SHA-256 for hashing/API keys, bcrypt for passwords, and why each was chosen for its specific use, not a single blanket "we use encryption" claim); multi-tenant isolation (what's isolated, how it was tested, referencing the real second-organization test from Milestone 5); Evidence integrity and what a compromised signing key would and wouldn't affect; what is NOT yet built (account lockout, distributed rate limiting, MFA enforcement), stated as plainly here as `SPECIFICATION/16_CURRENT_LIMITATIONS.md` already states it internally. **This guide should not read as more reassuring than the internal specification it's built from**; a security reviewer who later finds the gap disclosed internally but omitted externally will trust the vendor less than one who finds it disclosed in both places.

## 4. Architecture Guide

**Audience**: a prospect's own architect or engineering lead evaluating fit before commercial conversations mature.
**Source of truth**: `ARCHITECTURE.md`, `AZURE_MIGRATION/`'s own accumulated documentation, and this engagement's own Milestone 4-7 summaries for the current, real Azure production topology.
**Scope**: the Intent-to-Evidence request flow; the Runtime Policy compile/deploy/OPA-evaluation pipeline; the Authority Intelligence extraction pipeline (document to Blob/Search to Foundry to reviewable candidate); the multi-tenant isolation model; the Azure production topology (Container Apps, Postgres Flexible Server, Key Vault, Managed Identity, AI Foundry, AI Search, Blob Storage), stated as currently live, not aspirational, since Milestone 7 proved it end-to-end on the real production domain.

## 5. Operations Guide

**Audience**: whoever on the customer's side needs to know what to do when something looks wrong, day-to-day.
**Source of truth**: `OPERATIONS_RUNBOOK.md`, already real and currently accurate for the Render-era operational model, needing an Azure-native update once Render is actually retired (Milestone 7's own open item).
**Scope, customer-facing subset only** (the internal runbook covers PayReality's own infrastructure operations, which a customer never needs): what the health/readiness endpoints mean, how to interpret the three Intent outcomes operationally, what to do if a Runtime Policy needs an emergency rollback (the platform's own rollback mechanism, reactivating a prior version, not a separate emergency process), and how to escalate to PayReality.

## 6. Integration Guide

**Audience**: an engineer connecting an existing internal system (an ERP, a procurement tool, an internal agent framework) to Runtime Authority.
**Scope, honestly bounded**: today, this is the Developer Guide's direct-API/SDK content, generalized slightly for "your system calls our API" rather than "you write a standalone script." **This plan deliberately does not invent a catalog of named-system integration guides** (a specific ERP, a specific procurement platform) since none has been built or pilot-tested; doing so now would describe integrations that do not exist. Expand this guide with a named system's specific guidance only after a real pilot actually builds that integration.

## 7. Runtime Authority Guide

**Audience**: a business or governance stakeholder who needs to understand the product conceptually, not operate it directly.
**Source of truth**: `ENTERPRISE_MESSAGING_GUIDE.md` (this milestone) for language, `SPECIFICATION/`'s Runtime Policy and decision-engine sections for mechanism.
**Scope**: what an Intent, a Decision, and a Runtime Policy are, in plain business language; the three outcomes and what each means for a real transaction; how a Runtime Policy's lifecycle (draft through activation) maps to a real governance approval process; what the Runtime Policy Simulator lets a reviewer check before any real policy goes live.

## 8. Authority Intelligence Guide

**Audience**: whoever will actually upload the customer's governance documents and review the resulting Authority Graph, typically the Administrator Guide's same audience.
**Source of truth**: `AI_EXTRACTION_PIPELINE.md`, `AI_POLICY_BUILDER_ARCHITECTURE.md`, and `AI_PIPELINE_CONSOLIDATION_REVIEW.md` (Milestone 6) for the current, correct state of which pipeline does what.
**Scope**: what document types work well (delegation memos, approval matrices, signing schedules); how to read a returned Authority Graph (principals, resources, relationships, conflicts, gaps, questions, each with a citation and the model's own stated confidence and reasoning); why every conflict and gap surfaced is a feature, not an extraction failure, since the alternative is silently picking one interpretation; and the explicit, repeated point that nothing here becomes a live policy without a human promoting and approving it.

## What this plan deliberately does not do

It does not produce all eight guides at full length in this milestone. Given the Pilot Program Guide's own honest state (no pilot has run, no reference customer exists), writing exhaustive documentation for workflows nobody has yet exercised end-to-end as a real customer risks documenting the platform's own internal assumptions rather than a real user's actual questions. The Administrator and Developer Guides are the two genuinely blocking items for a first pilot and should be written in full first, from the sources named above; the rest should follow this same sourcing discipline as they're needed.
