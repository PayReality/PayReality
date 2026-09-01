# Part 14 — Security Model

**Supersedes/synthesizes:** `SECURITY.md`, `RBAC.md`, `SDK_SECURITY.md`. `SECURITY.md` and `RBAC.md`'s design-time versions predate the actual shipped RBAC implementation in places; this part reflects the code as built, grounded in `security.py`, `dependencies.py`, `domain/rbac/permissions.py`, and `services/auth_service.py`, all read in full this session.

## 14.1 Four authentication mechanisms, layered so nothing already integrated breaks

| Mechanism | Function | What it proves |
|---|---|---|
| Agent signature (Ed25519) | `verify_agent_signature` | "This specific Agent, holding this specific Certificate's private key, submitted this exact request body" |
| Operator key | `verify_operator_key`, first branch of `require_permission` | "The caller holds the one shared platform-admin secret" — always a **full bypass** |
| Session token / API key → Role → Permission | `require_permission`, second branch | "The caller is a specific authenticated principal whose Role grants this specific Permission" |
| Session token → User | `get_current_user` | "The caller is this specific human," for routes that need identity, not just permission |

The operator key is checked **first**, unconditionally, in `require_permission`: if present, it must be correct (401 if wrong — it never silently falls through to the permission check below on a bad value) and always succeeds if correct, regardless of what any Role/Permission table says. This is what let RBAC (Phase 10) ship without breaking a single existing integration: the SDK, the frontend's own historical operator-key flow, and any external automation built before RBAC existed all keep working completely unmodified.

**A fifth mechanism, Milestone 3: `verify_operator_key` (`security.py`) used directly, not through `require_permission`.** `_ALL_PERMISSIONS` (§14.2) means `Role.OWNER` automatically holds *every* `Permission` value that will ever exist, including any new one added specifically to be operator-key-exclusive — so `require_permission`'s operator-key branch cannot express "this action is for a platform admin, not any tenant's own Owner." `routers/organization_lifecycle.py` (create/list/deactivate/reactivate/archive an *arbitrary* organisation) and `process_due_schedules` (executes every organisation's due schedules in one pass — previously gated by `Permission.RUNTIME_POLICY_PUBLISH`, which any tenant's own Owner/Governance Admin holds, letting one tenant trigger another's schedule execution) both depend on `verify_operator_key` directly instead: the pure Operator-Key-only check, with no session/role fallback at all, that existed in this codebase but was unused by any router before this milestone.

## 14.2 RBAC: roles, permissions, and the one rule that matters

Six fixed roles (`domain/rbac/permissions.py`, a plain enum + dict, not a database-configurable table — deliberately, matching this codebase's convention for fixed vocabularies like `KNOWN_SCOPES`/`FinancialVocabulary`: a new role or permission is a real security decision earning a code review, not a config toggle an Owner can flip at runtime):

| Role | Representative permissions |
|---|---|
| `owner` | **All** permissions (`_ALL_PERMISSIONS`, computed from the `Permission` enum itself so it can never drift from the real list) |
| `governance_admin` | Runtime Policy CRUD + publish, Authority review, Evidence/Decisions/Assurance view, Principal management |
| `agent_admin` | Full agent lifecycle (register/activate/suspend/retire/revoke/rotate/manage), Principal management |
| `reviewer` | `authority.review` only |
| `auditor` | Evidence/Decisions/Runtime-Policy/Agent/Assurance **view only** |
| `executive` | `assurance.view` only |

**"Never check roles directly. Always check permissions"** — this phrase appears verbatim in the module's own docstring as its central directive, and it is enforced structurally: every single router in this codebase calls `require_permission(Permission.X)`; none compares `role == Role.OWNER` or similar. The Role → Permission mapping (`ROLE_PERMISSIONS`) is the **one place** role identity ever becomes an authorization decision. This matters practically: adding a seventh role, or changing what `reviewer` can do, is a one-line change to `ROLE_PERMISSIONS`, never a hunt through every router for a scattered role check.

Fine-grained permission examples worth calling out because they encode a real product decision, not just plumbing:

- **`AUTHORITY_REVIEW` is explicitly not `RUNTIME_POLICY_PUBLISH`.** A Reviewer can promote an AI-extracted candidate into a real draft policy, but promoting produces a `draft` — publishing it still separately requires `RUNTIME_POLICY_PUBLISH`, which `reviewer` does not have. This is exactly how "a Reviewer cannot publish" stays true even though a Reviewer can promote.
- **`AGENT_ADMIN` includes `PRINCIPAL_MANAGE`,** reflecting that agent onboarding routinely requires creating or attaching a Principal — a role scoped to "administers agents" that couldn't touch Principals would be an incoherent grant in practice.

## 14.3 Session and API-key mechanics

- **Sessions (`UserSession`)**: the session id **is** the bearer token — no JWT, no separate opaque-token column. Validating a session is one indexed primary-key lookup; revoking is one row update (`revoked_at`). This is a deliberate tradeoff, stated plainly in the model's own docstring: instant server-side revocation (delete/expire the row) versus a signature-only token that stays valid until it expires on its own. Expiry is a **fixed** window set at login (default 480 minutes, overridable per-organisation via `Organization.settings["session_timeout_minutes"]`), not a sliding window refreshed on activity — simpler to reason about, at the cost of a genuinely active user eventually being logged out mid-session.
- **API keys (`ApiKey`)**: raw key format `pr_live_<32 random URL-safe bytes>`, shown to the operator **exactly once** at creation and never stored — only a SHA-256 hash (`key_hash`) and a short display prefix persist. SHA-256 rather than bcrypt is a deliberate, documented tradeoff: the raw key is already a high-entropy generated secret, not a human-guessable password, so a slow salted hash buys nothing and would cost a hash computation on every single authenticated request instead of only at login (the same tradeoff Stripe/GitHub-style API keys make).
- **Passwords**: bcrypt (`hash_password`/`verify_password`), the conventional choice for a genuinely human-chosen, guessable secret — correctly differentiated from the API-key case above rather than using one hashing strategy for both.
- **Token resolution order** (`resolve_role_for_token`): try session-token lookup first (an API key never parses as a UUID, so this falls straight through to the API-key path at negligible cost), then API-key lookup.

## 14.4 Crypto choices and why

| Choice | Where | Why |
|---|---|---|
| Ed25519 (not RSA/ECDSA) | Agent Certificates, Evidence/audit signing | Small keys and signatures, fast verification, no parameter-choice footguns (unlike RSA key size or ECDSA curve/nonce pitfalls) |
| SHA-256 | Evidence `payload_hash`, chaining, API key hashing | Standard, fast, no known practical collision attack at this scale |
| bcrypt | Password hashing only | Deliberately slow, salted — the correct tool specifically for human-guessable secrets |
| `hmac.compare_digest` | Operator key comparison | Constant-time comparison — an operator key check using `==` would be a timing side-channel |
| Canonical JSON (sorted keys, no whitespace) | Everything signed or hashed | Determinism: the same logical payload must always produce the same bytes for signing/verification/chaining to be reproducible by an independent third party |

## 14.5 Middleware-level protections

`observability_middleware` (§2.5): per-client-IP fixed-window rate limiting (429 past 120 req/60s, in-process memory), security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy` disabling geolocation/microphone/camera, `Strict-Transport-Security` in production), and a last-resort exception handler that never leaks a real stack trace or exception message to the caller (logs it server-side with the request id instead). CORS is a single explicit allowed origin, never a wildcard.

## 14.6 Threat model: what's covered, what's a named gap

| Threat | Mitigation | Residual risk |
|---|---|---|
| Forged Intent from a non-agent caller | Ed25519 signature over raw body, verified against an `active` Certificate only | None known |
| Replayed Intent | Timestamp window + `UNIQUE(agent_id, nonce)` DB constraint | None known |
| Evidence tampering after the fact | Signature verification + (Phase 5) chain-link verification catching deletion/reordering | None known within a single organisation's chain |
| Compromised evidence signing key | Signing-key registry preserves verifiability of everything signed before rotation | Requires an operator to actually detect compromise and rotate — no automatic detection |
| Credential stuffing / brute force on login | bcrypt (slow hash) + rate limiting | No account lockout after N failed attempts (see [16_CURRENT_LIMITATIONS.md](16_CURRENT_LIMITATIONS.md)) |
| A caller with the shared operator key doing anything | By design, a full bypass — this is the intentional stand-in RBAC was built to reduce reliance on, not eliminate (existing integrations still use it) | Anyone holding it has Owner-equivalent access; rotating it requires an env var change + redeploy, not a self-service action |
| Single-instance rate limiting bypassed by scaling out | None today (in-process memory) | A second backend instance shares no rate-limit state with the first |
| Cross-tenant data exposure | **Milestone 1** closed Evidence read/verify, organisation-structure CRUD, Principals, and all 14 Authority Graph read endpoints. **Milestone 2** closed Runtime Policies/OPA and made the Operator Key platform-admin-only. **Milestone 3 (Enterprise Surface Isolation)** closed essentially everything Milestone 2 deliberately deferred: the mutating Authority Builder endpoints (`resolve_principal`, `resolve_relationship`, `activate_relationship`, `answer_question`, `approve_graph`) now verify their target row's organisation via three new router dependencies, not just `AUTHORITY_REVIEW`; the AI Policy Builder's single-document pipeline gained an organisation column and authentication on every endpoint; the Agent Platform's list/detail/bulk-action endpoints (previously unauthenticated) now resolve organisation via `Principal`; `process_due_schedules` moved from a per-tenant permission to the platform-admin-only `verify_operator_key` gate (any tenant's own admin could previously trigger every *other* tenant's due schedule execution); Blob Storage/Azure AI Search gained real `organization_id` scoping; and the frontend/SDK/smoke-test callers Milestone 2 left broken were updated to send the required header. Milestone 3 also built the Organization Lifecycle (create/deactivate/reactivate/archive, invite/accept/revoke membership) that had no API or UI of any kind before it, and removed the last "whichever organisation was created first" assumption (`ensure_owner_bootstrapped`). | Disclosed, not fixed by Milestone 3: `AuthorityRelationship.cross_org_approved` remains dead schema (defined, never read); lifecycle events written by `runtime_policy_service.py`'s own CRUD functions still don't stamp `organization_id` on the event row itself; Blob Storage/Azure AI Search org-scoping was not verified against a real Azure account; the new frontend organization UI was verified by TypeScript compilation only, not interactively browser-tested. See [16_CURRENT_LIMITATIONS.md](16_CURRENT_LIMITATIONS.md) §16.6. |

## 14.7 What's active vs. partial

| Component | Status |
|---|---|
| Agent signature verification, replay protection | **Active** |
| Operator key bypass | **Active** — deliberately permanent, not a removal candidate |
| RBAC (roles, permissions, sessions, API keys) | **Active**, Phase 10, live-verified |
| Evidence signing, chaining, key rotation | **Active**, see [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md) |
| MFA (`User.mfa_enabled` column exists) | **Schema-ready, not enforced** — the column exists and Organisation Settings can toggle a requirement, but no actual MFA challenge flow is implemented at login (see [16_CURRENT_LIMITATIONS.md](16_CURRENT_LIMITATIONS.md)) |
| Account lockout after repeated failed logins | **Not built** |
| Distributed (multi-instance) rate limiting | **Not built** — in-process only |
| Trusted Adapter authentication, allow-list enforcement, operation idempotency | **Active**, see §14.8 |
| Capability Authorization for the Adapter-mediated path | **Active**, Trusted Integration Phase 5, see §14.8, [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.9 |
| Capability issuance idempotency (one Decision, at most one usable Capability) and post-review Capability issuance | **Active**, Trusted Integration Phase 5.1, see §14.9 |
| Enforcement assurance `VERIFIED`/`REGISTERED_EXTERNAL_PEP` (a registered, authenticated external PEP identity) | **Not built**; see §14.8, [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.16 |

## 14.8 Trusted Integration: a sixth authentication mechanism, and what it changes about the threat model

| Mechanism | Function | What it proves |
|---|---|---|
| Trusted Connection signature (Ed25519) | `verify_integration_identity_signature` | "This specific Trusted Connection, holding this specific certificate's private key, submitted this exact attested request" |

Structurally identical to Agent signature verification (§14.1) — same primitive, same "checked against an `active` certificate only" rule — but a genuinely separate identity type (`IntegrationIdentity`, never a second Agent model) with its own certificate table, its own lifecycle, and its own replay index (`UNIQUE(integration_identity_id, nonce)`, entirely independent of `UNIQUE(agent_id, nonce)`). Never RBAC/`Permission`-checked — a Trusted Adapter is not a human session, the same reasoning that keeps Agent signature verification outside RBAC too.

**Trust boundaries specific to this path, each a real, code-enforced check (not a convention) — see [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.4 for the full sequence**:

- A Trusted Connection must be `active` (not suspended, revoked, retired) to submit anything.
- A Runtime Connection binding names exactly one Trusted Connection; one that exists but belongs to a *different* Trusted Connection is indistinguishable from "not found" — never a signal that reveals another tenant's or another connection's binding exists.
- The origin Agent named in an attested request must independently be `active` **and** appear on that specific Runtime Connection's explicit allow-list — checked server-side regardless of what the Adapter itself claims.
- Only context keys an approved Action Mapping explicitly bound may reach policy evaluation; anything else is a hard rejection, closing the "smuggle an untrusted value in as if pre-approved" class of attack.
- `environment` is server-resolved from the active binding; a caller-supplied `environment` key is rejected outright, closing "claim staging while acting on production" (or the reverse).

**Tenant isolation**: every Trusted Integration table (`integrations`, `integration_contract_versions`, `integration_identities`, `integration_identity_certificates`, `enforcement_bindings`, `enforcement_binding_agents`) carries or resolves an `organization_id`, checked the same "cross-org looks like not-found" way as every other org-scoped resource in this codebase (§14.6). Not independently re-verified with a second organization this pass, the same disclosed limitation §14.6 already names for other Milestone 3-era surfaces — treat this as inherited from the established pattern, not freshly live-tested.

**Replay protection, two independent layers, never to be confused**: `(integration_identity_id, nonce)` uniqueness is authentication-level replay defense — "do not accept the same signed request object again." `(integration_id, environment, external_operation_id)` uniqueness is business-operation idempotency — "one real external event produces one authority decision," entirely orthogonal, and enforced by a separate partial-unique index. A request can fail one without the other.

**Capability Authorization is now extended to this path** (Trusted Integration Phase 5, `capability_service.issue_capability_for_decision`), reversing the prior blanket suppression (`CapabilityNotAvailableForIntegrationIntentError`, previously unconditional on `Intent.integration_identity_id is not None`). The security-scoping question this raised, issuing a bearer-style downstream execution credential on top of a trust chain (Adapter attestation + Binding authorization) rather than an Agent's own authority alone, is addressed by re-checking that trust chain live, at the moment of issuance, not merely trusting the Intent's historical provenance: `IntegrationIdentityNotActiveError`/`EnforcementBindingNotActiveError` (both HTTP 409) fail issuance closed if the named Trusted Connection or Runtime Connection has been suspended, revoked, or retired since the Intent was accepted. This narrows, but does not eliminate, the blast radius of a compromise that happens *after* a Capability has already been issued and not yet consumed: a live re-check at issuance cannot retroactively invalidate a Capability minted moments before a revocation, the same TOCTOU-shaped limit any short-TTL credential carries. The Capability's own short expiry and single-use consumption (§14.1's own signature/replay pattern, reused unchanged) are what bound that remaining window, not this check.

A verifier that knows which Runtime Connection or environment it enforces can additionally pin that expectation against the Capability's own signed claim (`CapabilityBindingMismatchError`, HTTP 409) at verification time; this is optional and skipped entirely by a verifier that does not supply it, so it changes nothing about an existing agent-direct verifier's behavior.

**What Phase 5 does not build**: a distinct, registered, authenticated external PEP identity. `EnforcementBinding.enforcement_assurance` lets a customer *declare* (`ADVISORY` or `CAPABILITY_REQUIRED` only, DB `CHECK`-constrained) that their own downstream checkpoint requires a Capability, but this is the customer's own unverified claim, never independently checked, tested, or observed, and carries no authority meaning of its own. The further levels this platform's longer-term vision names, `DECLARED_DECISION_CHECK`, `VERIFIED`, and `REGISTERED_EXTERNAL_PEP`, have no implementation: no code path can set them. Treating `CAPABILITY_REQUIRED` as proof of a non-bypassable checkpoint, or describing the other three levels as available, would misstate this boundary.

## 14.9 Capability Issuance Idempotency and Post-Review Capability Authorization (Trusted Integration Phase 5.1)

**The gap this phase closes**: Phase 5's own issuance path (`issue_capability_for_decision`) never checked whether a Capability already existed for a Decision before minting another. A hostile-review-style test confirmed this empirically before writing the fix: two calls, or two genuinely concurrent calls, against the same ALLOW Decision each independently succeeded, producing two separately valid, separately consumable Capabilities for what is meant to be one authorized business operation — the literal "one authorized action becomes two executable permissions" risk this section closes.

**The invariant**: one authority authorization lifecycle — one ALLOW Decision, or one approved HUMAN_REVIEW resolution — produces at most one *currently usable* Capability. `capability_tokens.decision_id` is now `UNIQUE` (migration `d4e8b1a6f2c9`), not merely indexed. This is a real, database-enforced guarantee, not application-level convention: `capability_service._issue_and_persist` always attempts the `INSERT` and handles the constraint violation on the losing side of a race, rather than trusting its own prior existence check alone — the identical discipline `resolution_service.resolve_decision` already established for `decision_resolutions.decision_id`'s own `UNIQUE` constraint.

A repeated or concurrent issuance request against a Decision that already has a Capability resolves to exactly one of three distinct, deliberately different outcomes, never a second successful mint:

| Existing Capability state | Result |
|---|---|
| Unexpired, unconsumed | `CapabilityAlreadyIssuedError` (HTTP 409 `capability_already_issued`) — the caller learns one is already outstanding (`capability_id`, `expires_at`); the raw token material is never re-returned, since `CapabilityToken` stores only a hash of it, never the token itself |
| Already consumed | `CapabilityAlreadyConsumedForDecisionError` (HTTP 409 `capability_already_consumed_for_decision`) — fail closed; a second Capability for an already-consumed authorization could permit duplicate execution of the same business operation |
| Expired, never consumed | `CapabilityExpiredNotRenewedError` (HTTP 409 `capability_expired_not_renewed`) — deliberately does **not** auto-issue a fresh one; authority conditions may have changed since the original Decision, and treating a historical ALLOW as indefinitely renewable authority on demand is exactly the failure mode this phase avoids. A genuine operational need to retry a lapsed authorization is a disclosed, deliberately unbuilt gap, not silently papered over with an invented renewal model |

Applies identically to the Agent-direct and Trusted-Adapter-mediated paths — both converge on the same `_issue_and_persist` implementation, so this is one fix, not two parallel ones that could drift.

**Post-Review Capability Authorization**: before this phase, a HUMAN_REVIEW Decision a reviewer later approved had no path to a Capability at all — `issue_capability_for_decision`'s `outcome == "ALLOW"` precondition rejected it permanently, even after approval (by design: the original Decision is immutable and never mutated to ALLOW). `capability_service.issue_capability_for_reviewed_decision` (new endpoint: `POST /v1/decisions/{decision_id}/capability-token/from-review`) closes this without weakening that guarantee: it requires `outcome == "HUMAN_REVIEW"` **and** an existing `DecisionResolution` row with `resolution == "approved"` (the only two values `decision_resolutions.resolution`'s own `CHECK` constraint allows — no "cancelled"/"expired" review state exists in this schema to check, and none was invented). The original Decision still reads `HUMAN_REVIEW` forever; the Capability is bound to the resolution, not a reinterpretation of the runtime evaluation. A `DecisionResolution` row can only ever be created by `resolve_decision`, itself gated on `Permission.DECISIONS_RESOLVE` and organisation-scoped — its mere existence with `resolution == "approved"` **is** the reviewer-legitimacy check; no second, parallel approval mechanism was built.

Post-review issuance reuses every live fail-closed re-check Phase 5 established (`IntegrationIdentityNotActiveError`, `EnforcementBindingNotActiveError`, `OriginAgentNotActiveError`) and the Phase 5.1 idempotency guarantee above, via the same shared `_issue_and_persist` tail — an approval from before an Adapter or Agent was revoked cannot override that revocation. It remains bound to the original Intent's `external_operation_id`, `resource`, and `constraints`: the approval authorizes continuation of that specific business operation, never a different one with equivalent-looking fields. Gated on the same `Permission.CAPABILITY_ISSUE` as direct issuance, not a new permission — minting a Capability is the same privilege either way; who was allowed to *approve* the review was already checked when the resolution itself was created.

## 14.10 Authorization Freshness and Tenant-Scoped Verification (Trusted Integration Phase 6.1)

**Consumption-time freshness** closes a TOCTOU limit §14.9's own Capability model still had after Phase 5.1: `verify_and_consume_capability` checked only the token's own signed claim, never live database state, so a Capability issued while its Agent/IntegrationIdentity/EnforcementBinding were active remained consumable for the rest of its TTL even after one was revoked in between — confirmed by test before this phase closed it, not merely inferred. `capability_service._check_consumption_freshness` now re-checks the same live-status helpers issuance already used, immediately before the atomic consume, in the same uncommitted transaction: `OriginAgentNotActiveError`, `IntegrationIdentityNotActiveError`, `EnforcementBindingNotActiveError` (Adapter-mediated only), and the new `TenantNotActiveError` (Organization.status, now checked at both issuance and consumption for the first time). Deliberately does **not** re-run Runtime Authority evaluation, RuntimePolicy, or Trusted Enterprise Facts — that would be a materially larger architecture (a second full policy evaluation), not the "smallest clear freshness boundary" this phase's own brief called for; the Capability's own immutable signed payload already answers what was authorized at Decision time.

A failed freshness check never marks the token consumed and never invokes downstream execution — the token remains exactly as usable as before the failed attempt, so a subsequent attempt after the underlying state is restored (e.g. an Agent reactivated) may still succeed within the remaining TTL. This is deliberate, not an oversight: freshness validation is live, against current state, every time it runs, never a one-way ratchet.

**Tenant-scoped verification** closes the other half of §14.9's own reconfirmed gap: `POST /v1/capability-tokens/verify` moved from the bare, non-tenant-scoped `verify_operator_key` check to `require_permission(Permission.CAPABILITY_VERIFY)` + `get_current_organization` — the same pattern `issue_capability` already used. The resolved organisation is checked against the Capability's own signed `organization_id` claim (`domain/capability/token.py`'s new `expected_organization_id` parameter, `CapabilityTenantMismatchError` on mismatch), checked before even the audience check so a wrong-tenant caller learns nothing else about a token it has no business inspecting. No new identity concept: an organisation issues a real, tenant-bound `ApiKey` (the existing, already-hashed, already-revocable credential) with a role holding the new permission. The platform Operator Key still works, unchanged from Milestone 2's own model (must name its target organisation explicitly), and is checked against the same tenant boundary as any `ApiKey` — not exempt from it. This was never a cross-tenant bypass in the exploitable sense (lookup is by the token's own unique hash, so no request could ever be confused for another tenant's), but it left the verify endpoint as the one Capability-adjacent surface with no expressible tenant scope at all.
