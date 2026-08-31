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
| Capability Authorization for the Adapter-mediated path | **Deliberately not built** — see §14.8, [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.9 |

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

**Capability Authorization is explicitly withheld from this path** (`CapabilityNotAvailableForIntegrationIntentError`, unconditional on `Intent.integration_identity_id is not None`) — named here again because it is as much a security-scoping decision as a product one: issuing a bearer-style downstream execution credential on top of a trust chain (Adapter attestation + Binding authorization) this architecture was never designed to carry that weight would widen the blast radius of a compromised Trusted Connection beyond what today's design accounts for. Extending Capability Authorization to this path safely is named, disclosed future work, not an oversight.
