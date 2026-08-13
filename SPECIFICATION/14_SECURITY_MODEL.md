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
| Cross-tenant data exposure | **Milestone 1 (Security & Authorization Hardening)** closed Evidence read/verify, organisation-structure (business unit/department/team) CRUD, Principals, and all 14 Authority Graph read endpoints (18 isolation regression tests, `test_organization_isolation.py`). **Milestone 2 (Multi-Tenant Foundation)** closed the two gaps Milestone 1 deliberately deferred: `RuntimePolicyRecord`/`Policy`/lifecycle/schedule tables now all have `organization_id`, each organisation compiles to and deploys its own OPA package (`idx_policies_single_active_per_org`, per-organisation OPA packages, proven against a real OPA server — see [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) §7.12), and the Operator Key is now platform-admin-only — it must name an explicit target organisation, with no "whichever organisation was created first" default. Milestone 2 also found and fixed two further leaks while wiring the lifecycle service: `search_policies`/`get_dashboard` previously read every organisation's rows unconditionally, and `get_timeline`/`cancel_schedule` had no organisation check at all (an IDOR). | Not yet covered by either milestone: the mutating Authority Builder endpoints (`resolve_principal`, `resolve_relationship`, `activate_relationship`, `answer_question`, `approve_graph`) don't yet verify their target row's organisation, only that the caller holds `AUTHORITY_REVIEW`. Newly introduced by Milestone 2's Operator Key change, deliberately deferred: the frontend's Operator Key flow, the Python SDK's admin-key path, and `scripts/smoke_test.py` all still call org-scoped endpoints with no target-organisation header, and will fail until updated (see [16_CURRENT_LIMITATIONS.md](16_CURRENT_LIMITATIONS.md) §16.5). Also disclosed: lifecycle events written by `runtime_policy_service.py`'s own CRUD functions don't yet stamp `organization_id` on the event row itself, though the policy record they describe does. |

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
