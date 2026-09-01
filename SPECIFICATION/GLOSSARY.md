# Glossary

Every term of art used across this specification, defined once. Alphabetical. Each entry cross-references the part where it's covered in depth.

**Action Mapping** — Customer-facing term for `IntegrationContractVersion`: a deterministic, versioned, human-approved statement of what one external system operation (e.g. `ChangeSupplierBankDetails`) means in PayReality's canonical vocabulary (e.g. "Update supplier bank details"). Lifecycle `draft → validated → approved → retired`; multiple `approved` versions of the same mapping may legitimately coexist. Approved does not mean active — a Runtime Connection selects which approved version is actually used. [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.12

**Agent** — A certificate-holding identity, acting for a Principal, that submits signed Intents. Has a full lifecycle (registered → active ⇄ suspended → revoked/retired). [11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md)

**Assurance** — A live read of what's actually running (agent counts, active policy, decision volume by outcome), computed from the database on every request, never a cached or seeded score. [01_PRODUCT_OVERVIEW.md](01_PRODUCT_OVERVIEW.md) §1.3

**Authority** — The delegated, scoped, time-bounded right to act. Two historical representations exist: the retired Authority/Mandate model, and the current Authority Model (`AuthorityRelationship` with real FKs). [08_RUNTIME_AUTHORITY.md](08_RUNTIME_AUTHORITY.md), [17_LEGACY_COMPONENTS.md](17_LEGACY_COMPONENTS.md)

**Authority Freshness**: The re-attestation lifecycle on a `RuntimePolicyRecord`: `last_attested_at`, `next_review_at`, `review_cadence_days`, and `authority_expires_at`. Re-attesting (`attest_policy`) only updates those fields; it is a label update, never a status change, and it never touches `authority_expires_at` itself. REVIEW DUE (the current time has passed `next_review_at`) is a dashboard reminder that never blocks anything on its own. AUTHORITY EXPIRED (the current time has genuinely passed `authority_expires_at`) is a real decision-time check, but only for a matched policy whose `risk_level` is high or critical, where it downgrades what would otherwise be ALLOW to HUMAN_REVIEW with reason `authority_review_overdue`. A low or medium risk policy past its `authority_expires_at` is a disclosed, accepted trade-off, not silently ignored. [POC_READINESS_REPORT.md](../POC_READINESS_REPORT.md) §4.

**Authority Graph** — The AI Authority Builder's full extraction result for one corpus: policies, principals, resources, operations, relationships, conflicts, gaps, and questions. [09_AI_AUTHORITY_BUILDER.md](09_AI_AUTHORITY_BUILDER.md)

**Authority Model** — Phase 1's real organisational hierarchy (`BusinessUnit → Department → Team`) and delegation graph. [08_RUNTIME_AUTHORITY.md](08_RUNTIME_AUTHORITY.md)

**Authorization Receipt** — A named, shipped, stable artifact (`GET /v1/decisions/{id}/receipt`) that packages one Decision's existing Evidence, Authority, Trusted Enterprise Facts, and (where Adapter-mediated) integration provenance into one human-readable view. It is **not** a second cryptographic artifact or a stronger proof than Evidence itself — it presents the same signed record, never claims the downstream action executed, and is gated by the same `EVIDENCE_VIEW` permission Evidence itself requires. [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.4

**Bundle / Policy Bundle** — The compiled, versioned Rego module produced by Compiler V2 from a set of `RuntimePolicy` objects; identified by a `bundle_hash` computed over its Rego source and manifest (excluding the compile timestamp, so identical input always hashes identically). [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) §7.6

**Capability Authorization**: A short-lived, signed, single-use token (`domain/capability/token.py`) issued for an ALLOW decision, or (Trusted Integration Phase 5.1) for a HUMAN_REVIEW decision an authorized reviewer has since approved, binding decision, principal, action, resource, constraints, policy version, fact hashes, audience, nonce, and expiry into one signed payload. Verification and consumption happen atomically, so two concurrent presentations of the same token cannot both succeed. A capability token is explicitly not itself an enforcement mechanism: it is a transport and proof mechanism that only produces real bypass resistance when a genuine downstream Policy Enforcement Point actually requires and checks it before acting, which no production system does today. As of Trusted Integration Phase 5, issuance covers an Adapter-mediated ALLOW decision too, subject to a live re-check that the Trusted Connection and Runtime Connection are still active, and the signed payload additionally binds the exact Runtime Connection, Action Mapping version, and environment for that path. As of Phase 5.1, one authority authorization lifecycle (one ALLOW decision, or one approved review) produces at most one currently usable Capability, ever — `capability_tokens.decision_id` is database-unique, and a repeated or concurrent issuance request resolves to one of three distinct outcomes (already issued / already consumed / expired and not renewed) rather than a second usable token. As of Phase 6.1, consumption also re-checks whether the Agent/IntegrationIdentity/EnforcementBinding/Organization a Capability depends on are still live immediately before it is consumed (never re-evaluating the original authority decision itself), and verification is tenant-scoped — a caller may only verify a Capability signed for its own organisation, checked via a real, revocable, organisation-bound `ApiKey`, not the platform-wide Operator Key alone. [POC_READINESS_REPORT.md](../POC_READINESS_REPORT.md) §5, [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.9, [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md) §14.9–14.10.

**Enforcement Assurance**: A customer-declared label on an `EnforcementBinding` (Runtime Connection): `ADVISORY` (default, no declared requirement) or `CAPABILITY_REQUIRED` (the customer declares their own downstream checkpoint requires a valid Capability), the only two values a database `CHECK` constraint permits. Carries no authority meaning; Runtime Authority's own evaluation never reads it, and PayReality never independently verifies the declaration. `DECLARED_DECISION_CHECK`, `VERIFIED`, and `REGISTERED_EXTERNAL_PEP` are named in this platform's longer-term vision but have no implementation: no code path can set them, since doing so would require registering and authenticating a distinct external PEP identity, which this phase does not build. [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.16.

**Certificate** — An Agent's Ed25519 keypair record (public key only, server-side); status one of `issued/active/rotated/expired/revoked`. At most one `active` per agent, enforced by a partial unique DB index. [11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md) §11.3

**Chain scope** — The `organization_id` an Evidence record's hash-chain is partitioned by; `NULL` is itself a valid, consistent scope. [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md) §13.3

**Compiler V2** — The current, sole Rego-generating compiler (`domain/compiler_v2/`), replacing the retired legacy `domain/compiler/`. [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md)

**Decision** — The outcome of evaluating one Intent: `ALLOW`, `DENY`, or `HUMAN_REVIEW`, never a fourth value. Immutable after creation. [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md)

**Decision Engine** — `domain/decision/engine.py::evaluate()`, the pure function with exactly one code path to `ALLOW`. [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) §12.1

**Enforcement**: Not something PayReality performs today. See Policy Decision Point (PDP) and Policy Enforcement Point (PEP) below for the distinction: PayReality decides, it does not gate. [POC_READINESS_REPORT.md](../POC_READINESS_REPORT.md) §8.

**Evidence** — An Ed25519-signed, append-only record of a Decision (or a later resolution of one). Chained per organisation since Phase 5. [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md)

**External Operation ID** — The enterprise system's own stable identifier for one real business operation, supplied by a Trusted Adapter and scoped to `(integration, environment)`. One real operation produces one authority decision: a retry with the same ID and the same authority-relevant meaning returns the existing Decision; the same ID with different authority-relevant meaning is a conflict, never a new evaluation. Distinct from nonce replay protection, which is authentication-level, not business-operation-level. [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.7

**Fact Source**: The registered signing identity (`FactSource`) a Trusted Enterprise Fact is attested under: its own Ed25519 keypair, an active/revoked lifecycle, and no other state. Distinct from an Agent identity by design, so an agent requesting authorization can never supply a consequential external fact about itself as if it were an independent attestation. [POC_READINESS_REPORT.md](../POC_READINESS_REPORT.md) §3.

**Fail-closed** — The design principle that any ambiguity, error, timeout, or absence of a covering policy resolves to `HUMAN_REVIEW`, never `ALLOW`. [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) §12.5

**HUMAN_REVIEW** — One of the three Decision outcomes; requires a human to resolve via `resolution_service`, which appends a second Evidence record rather than mutating the first. [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md), [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md) §13.6

**Integration (System)** — Customer-facing term for `Integration`: one external enterprise system a customer has connected (e.g. "SAP S/4HANA"). Owns any number of Action Mappings, one per real operation. [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.3

**Integration rejection** — A pre-evaluation trust failure on the Adapter-mediated path (invalid Trusted Connection, inactive Runtime Connection, an Agent not on the allow-list, a mapping mismatch, an operation-ID conflict, and similar). Categorically different from DENY: it means PayReality could not establish a trustworthy request to evaluate at all, so no Decision and no Evidence are ever produced — never confuse the two. [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.8

**Intent** — A signed request an Agent submits describing an action it wants to take (action, amount, currency, counterparty, context). One row per submission, replay-protected via `UNIQUE(agent_id, nonce)`. [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md)

**Mandate** — A per-principal/scope limit compiled from an approved Authority, in the now-retired legacy pipeline. [17_LEGACY_COMPONENTS.md](17_LEGACY_COMPONENTS.md)

**OPA (Open Policy Agent)** — The external Rego-evaluating process the Decision Engine queries over HTTP. Never reachable from outside the backend's private network. [02_SYSTEM_ARCHITECTURE.md](02_SYSTEM_ARCHITECTURE.md) §2.1

**Operator key** — The single shared `ADMIN_API_KEY`; a full, permanent bypass of RBAC, checked first in `require_permission`. [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md) §14.1

**Permission** — A fixed, enumerated capability (e.g. `RUNTIME_POLICY_PUBLISH`); every enforcement point checks a Permission, never a Role directly. [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md) §14.2

**Policy Decision Point (PDP)**: PayReality's actual role today. It evaluates whether a proposed action is authorized under the currently active policy, produces the ALLOW, DENY, or HUMAN_REVIEW Decision and its signed Evidence before the action executes, and can issue a Capability Authorization token for an ALLOW. It does not itself block, gate, or execute anything; it decides. [01_PRODUCT_OVERVIEW.md](01_PRODUCT_OVERVIEW.md) §1.2, [POC_READINESS_REPORT.md](../POC_READINESS_REPORT.md) §8.

**Policy Enforcement Point (PEP)**: The role that does not yet exist in production: a real downstream system, on the only path to a protected action, that actually requires and checks a valid Capability Authorization (or equivalent) before letting that action proceed. `scripts/reference_enforcement_adapter.py` proves the token mechanism (replay, tampering, expiry, and mismatch are all genuinely rejected through it), but is explicitly a reference adapter proving that mechanism, not a production PEP; it cannot prove that no other path to the protected action exists. [POC_READINESS_REPORT.md](../POC_READINESS_REPORT.md) §5, §8.

**Principal** — The person, team, or organisation an Agent acts *for*, and who bears the risk of its actions. [05_DATABASE.md](05_DATABASE.md) §5.1

**RBAC** — Phase 10's role/permission system: six fixed roles, permission-only enforcement, sessions and API keys. [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md)

**Rego** — Open Policy Agent's policy language; what a `RuntimePolicy` compiles into. [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) §7.5–7.6

**Role** — One of six fixed identities (`owner`, `governance_admin`, `agent_admin`, `reviewer`, `auditor`, `executive`) mapped to a Permission set. Never checked directly at an enforcement point. [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md) §14.2

**Runtime Connection** — Customer-facing term for `EnforcementBinding` (+ its `EnforcementBindingAgent` allow-list): the live combination of one Trusted Connection, one approved Action Mapping, one environment, and an explicit allow-list of Agents. This is the point where an approved mapping becomes eligible for real Adapter use. Lifecycle `draft → active → retired`; exactly one Runtime Connection may be active per `(Trusted Connection, System, operation, environment)` scope, DB-enforced. [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.13

**RuntimeAuthority Context** — Phase 2's ephemeral, request-scoped enrichment of the OPA input (organisation, department, role, risk band, active delegations), merged under `context.authority`, never persisted, never a policy pre-filter. [08_RUNTIME_AUTHORITY.md](08_RUNTIME_AUTHORITY.md) §8.3–8.4

**RuntimePolicy** — The canonical, immutable value object every authoring path (manual, AI Authority Builder, AI Policy Builder) produces: scope, flat AND-only conditions, effect. [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) §7.2

**RuntimePolicyRecord** — The persisted, versioned row backing a `RuntimePolicy`; one immutable row per version. [05_DATABASE.md](05_DATABASE.md) §5.1

**Scope (of a RuntimePolicy)** — Who a policy applies to and over what: `principal` and `action` required, `agent` and `resource` optional narrowing. [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) §7.2

**Signing-key registry** — The `SigningKey` table and `signing_key_service.py`, preserving verifiability of records signed under a key that has since been rotated out. [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md) §13.2

**Trusted Adapter** — Customer-facing term for the `IntegrationIdentity` runtime role: a customer-controlled, authenticated, non-Agent component that observes or constructs the canonical Intent for a real external operation. Answers "what company-controlled component is attesting what action is being attempted," never "who is acting" (that's the Agent) and never "is this authorized" (that's PayReality). Runs inside the customer's own environment; PayReality does not host it and has no standing access to the enterprise systems it observes. [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.2, §50.11

**Trusted Connection** — Customer-facing term for `IntegrationIdentity` as a registered, certificate-holding identity: the "who" a Trusted Adapter authenticates as. Has its own Ed25519 certificate lifecycle (`registered → active ⇄ suspended → revoked/retired`), deliberately not a second Agent model even though the shape rhymes. [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.3

**Trusted Enterprise Fact**: A signed external assertion about enterprise reality (a subject, key, and value) attested by a registered Fact Source and bound to one organization, with a mandatory expiry (no fact type ships with an unbounded default). A missing, expired, or contradicting fact all resolve to the same place: unknown, handled by Runtime Authority's existing fail-closed path, never a default-forever trust. Proves only what the attesting source asserted, not that the assertion is objectively true. [POC_READINESS_REPORT.md](../POC_READINESS_REPORT.md) §3.

**Vocabulary** — The injectable protocol (`is_valid_action`) that keeps Compiler V2 domain-agnostic even though its one shipped implementation (`FinancialVocabulary`) is not. [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) §7.4
