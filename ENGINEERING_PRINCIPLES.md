# Engineering Principles

The standing conventions this platform has been built and extended under, consistently, across every milestone. These are not aspirational; each one below is enforced in real, shipped code today, and a change that violates one of these should be treated as a design decision requiring the same scrutiny the original decision got, not a routine edit.

## The ones that must never be simplified away

**AI never makes an authorization decision.** It may propose (Authority Intelligence's candidates); it never decides. Every ALLOW/DENY/HUMAN_REVIEW outcome comes from OPA evaluating deterministic, versioned, human-approved Rego, full stop. If a future feature ever needs "let the model decide faster," the correct response is not to weaken this boundary; it is to design a new, explicitly-labeled feature that does not claim to be a Runtime Authority decision at all.

**Fail closed, always.** Uncertainty about authority is not authority. No matching policy, an unreachable OPA instance, a certificate that fails to verify: every one of these resolves to HUMAN_REVIEW or a hard rejection, never to a silent ALLOW. This is why HUMAN_REVIEW exists as a first-class outcome rather than an error state.

**Evidence is signed and hash-chained, never just logged.** A record's trustworthiness has to survive the customer not trusting PayReality's own dashboard. Anything that would make Evidence verifiable only by asking PayReality to vouch for it defeats the entire point of signing it in the first place.

**Cross-organization access looks like not-found, never like a permission error.** A caller who names another organization's resource by ID gets exactly the same response as a caller who named something that never existed. This is deliberate: a distinguishable "you're not allowed to see this" response leaks the existence of data across a tenancy boundary that shouldn't be observable at all.

## Multi-tenancy conventions

**Resolve organization through the parent, never duplicate the column.** When a row's natural owner is unambiguous through an existing relationship (a candidate through its upload or corpus, a scenario through its policy), resolve organization through that relationship rather than adding a second, independently-maintained `organization_id` that could drift from the source of truth.

**Additive, nullable-first migrations.** A schema change that adds multi-tenancy to an existing table adds the column nullable, backfills it, and only tightens the constraint later if ever. This is what has made every retrofit in this platform's history (Milestone 2's multi-tenant foundation, Milestone 3's surface isolation) possible without downtime or a breaking migration.

**"None" is its own valid, consistent scope, not an error.** Functions that predate multi-tenancy accept `organization_id: uuid.UUID | None` explicitly, and `None` means "the pre-multi-tenant, no-organization-set legacy scope," not "give me every organization's data." There is deliberately no call site anywhere in this codebase meaning "all organizations at once"; every caller already knows which organization it's acting as.

**Never check roles directly, always check permissions.** The Role-to-Permission mapping is the one place role identity is ever allowed to become an authorization decision. Every router calls `require_permission(Permission.X)`; none compares a role directly. Adding a role, or changing what an existing role can do, should be a one-line change to that mapping, never a hunt through routers for scattered role checks.

**The operator key is a deliberate, permanent, full bypass, not a removal candidate, but its scope has a boundary.** It exists for genuine platform-admin actions (creating an organization, executing a cross-tenant scheduled job) and, since Milestone 2, must always name its target organization explicitly. It is not a substitute for RBAC on ordinary, single-tenant actions; `verify_operator_key` and `require_permission`'s own operator-key branch are deliberately different primitives for exactly this reason (`_ALL_PERMISSIONS` means any tenant's own Owner already holds every permission that will ever exist, so a permission cannot be made operator-key-exclusive within the RBAC system itself).

## Extraction and AI-provider conventions

**A shared prompt/schema module, never a second copy.** When two providers (Claude, Azure AI Foundry) need to ask a model the same question in the same shape, the prompt, the schema, and the parsing logic live in one `extraction_shared.py`, imported by both provider implementations. A provider's own file should only ever contain "how to call this specific vendor," never "what to ask or how to interpret the answer."

**Inject the real vocabulary, never hardcode a second copy of it.** A prompt or schema that needs to know the platform's known actions or operators reads them from the same domain module (`FINANCIAL_VOCABULARY`, the `Operator` enum) the compiler itself uses, so the two can never drift apart.

**A saved scenario is a saved question, never a saved answer.** The Runtime Policy Simulator's Test Scenarios persist only the hypothetical input and the expected outcome; the actual outcome is always computed live, every time, so a scenario that passed yesterday can legitimately fail today if the policy changed, without that ever being treated as stale data needing a migration.

## Cryptography, applied deliberately, not uniformly

Ed25519 for signing (agent certificates, Evidence): small keys, fast verification, no footgun parameter choices. SHA-256 for hashing and API-key storage: the raw secret is already high-entropy and machine-generated, so a slow, salted hash buys nothing and costs a computation on every request. Bcrypt specifically and only for human passwords: the one secret in this system a human actually chose and might reuse or guess-ably pick, and therefore the one place a deliberately slow hash earns its cost. Constant-time comparison (`hmac.compare_digest`) for the operator key, specifically to avoid a timing side-channel a plain `==` would introduce. Choosing one cryptographic primitive for every use case would have been simpler to write and wrong for at least two of these four.

## Verification discipline

**State NOT VERIFIED rather than assume.** Every milestone in this platform's history that touched production infrastructure or a live claim distinguished directly-checked fact from inference from recommendation, explicitly, in its own deliverable documents. This is not bureaucratic labeling; it is the reason several real defects (a crashing Evidence endpoint, a Simulator broken for every organization, a website claiming the wrong core-runtime language) were caught by this engagement rather than by a customer or a technical due-diligence reviewer.

**Fake-session unit tests for DB orchestration logic; real Postgres and real OPA for integration tests.** A function's correctness in composing queries and business logic is tested with a minimal fake session that never touches a real database; a function's correctness against genuinely OPA-dependent mechanics (bundle isolation, real Rego evaluation) is tested against a real, ephemeral OPA instance. Mixing the two into one test either makes the unit suite slow and flaky or makes the integration suite miss what only a real OPA server would actually catch.

## Change discipline

**Minimal, targeted fixes over rewrites.** A milestone scoped as "fix these two blockers" fixes those two blockers, not a broader refactor of the surrounding code, even when a broader refactor might also be an improvement. Scope creep on a hardening or migration milestone is exactly how a platform this size accumulates unreviewed risk.

**Sequential lifecycle state machines, never a state-skipping shortcut.** An agent, a policy, or an organization moves through its lifecycle one real transition at a time (registered before active, draft before active, active before archived), matching how a real enterprise process actually works, and making every intermediate state a real, auditable moment rather than an implementation detail collapsed away for convenience.
