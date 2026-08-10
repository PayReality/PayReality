# RBAC: Enterprise Roles, Permissions, and Organisation Identity

## Why this exists

PayReality already governs AI authority: every agent action is checked against a policy before it runs, and every decision is signed into Evidence. Before this change, PayReality had no equivalent governance over *human* authority: every administrative action (creating a Principal, approving a rule, resolving a HUMAN_REVIEW decision, retiring an agent) was gated by one shared static secret (`X-PayReality-Operator-Key`, `server/app/security.py::verify_operator_key`) compared against one config value, and "who did this" was a free-text field a person typed in themselves. Agent actions were cryptographically attributable; human actions were not.

This is the same philosophy applied to people: a fixed set of roles, a fixed set of permissions, and a real (not free-text) identity behind every administrative action.

## The permission model

`server/app/domain/rbac/permissions.py` is a pure, dependency-free module (no DB, no network) -- the same convention this codebase already uses for other fixed vocabularies (`scope_vocabulary.py`'s `KNOWN_SCOPES`, `compiler_v2.py`'s `FinancialVocabulary`). A new permission or role is a code change reviewed like any other, not a runtime-configurable table an Owner could silently expand.

Six roles, matching the spec exactly:

| Role | Can | Cannot |
|---|---|---|
| **Organisation Owner** | Everything -- every permission in the system | -- |
| **Governance Administrator** | Create/edit/publish Runtime Policies, review AI Authority Builder output, view evidence and decisions | Manage organisation, billing, users, or delete the organisation |
| **Agent Administrator** | Register, suspend, rotate, retire, and manage agents and agent groups | Edit or publish Runtime Policies |
| **Reviewer** | Review AI-extracted authority, approve, reject | Publish anything |
| **Auditor** | Read-only: evidence, decisions, governance, policies, agents, assurance | Modify anything |
| **Executive** | Read-only dashboards (assurance only) | Everything else |

The mapping lives in one place, `ROLE_PERMISSIONS: dict[Role, frozenset[Permission]]`, and every enforcement point calls `has_permission(role, permission)` -- **never** `role == Role.OWNER` or similar. The role-to-permission mapping is the one place role identity turns into an authorization decision; nothing downstream re-derives it.

Permission names match the spec's own examples plus the full set a coherent role actually needs (e.g. the spec named five agent-lifecycle permissions as examples; a role that can suspend an agent but not reactivate it isn't a coherent role, so `agent.activate`/`agent.revoke`/`agent.manage`/`agent.view` exist alongside the five named ones):

```
organisation.manage, organisation.delete, users.manage, integrations.manage,
api_keys.manage, operator_keys.view, audit.export, settings.view,
runtime_policy.create, runtime_policy.edit, runtime_policy.publish, runtime_policy.view,
authority.review,
agent.register, agent.activate, agent.suspend, agent.retire, agent.revoke,
agent.rotate, agent.manage, agent.view,
principal.manage,
evidence.view, decisions.view, decisions.resolve, assurance.view
```

## Enforcement: `require_permission`, layered on top of the existing gate

`server/app/dependencies.py::require_permission(permission)` replaced every router's `Depends(verify_operator_key)` with `Depends(require_permission(Permission.X))`. It checks, in order:

1. **The existing shared operator key**, if the `X-PayReality-Operator-Key` header is present. This behaves *exactly* as `verify_operator_key` always has: correct key = full bypass (Owner-equivalent access to everything), wrong key = `401 invalid_operator_key`, unconfigured = `503`. Every existing integration (SDK, frontend, existing automation, CI) keeps working with zero changes required. A present-but-wrong key never silently falls through to permission checking below -- that would change what "wrong operator key" means today.
2. **Otherwise, a bearer token** (`Authorization: Bearer <token>`), resolved to a `Role` via `auth_service.resolve_role_for_token` and checked against the requested permission. The token is either a session id (a human who logged in) or an API key (see below) -- both resolve to the same `Role` enum, so the same `has_permission` check covers both paths.

This is additive, not a replacement. `verify_operator_key` itself is untouched (`server/app/security.py`).

Every mutating endpoint across `agents.py`, `ai_authority_builder.py`, `ai_policy_builder.py`, `intents.py`, `policies.py`, `principals.py`, and `runtime_policies.py` was retrofitted this way -- roughly 30 call sites. The mapping from endpoint to permission followed each endpoint's actual effect, not a guess: e.g. `runtime_policies.py`'s `approve`/`reject` map to `authority.review` (exactly the Reviewer's one permission, "can approve/reject, cannot publish"), while `deploy` maps to `runtime_policy.publish`.

## Identity: Organisation, User, Session, API Key

Four new tables (`server/app/db/models.py`, migration `2d5a7c9e1f43_add_rbac_and_organisation_tables.py`):

- **`Organization`**: name, timezone, default currency/language, plus a `settings` JSONB blob for everything Organisation Settings needs that doesn't warrant its own column (see ORGANISATION_SETTINGS.md).
- **`User`**: email, name, `password_hash` (bcrypt), `role`, `status` (active/disabled), `mfa_enabled`, `must_reset_password`.
- **`UserSession`**: a bearer token that *is* the session id itself, not a JWT. Validating a session is one indexed primary-key lookup against a value the database can revoke instantly by deleting/expiring the row -- there's no signature to check and no way for a revoked session to still "look valid" until it expires on its own. Deliberately named `UserSession`, not `Session`, so it never collides with `sqlalchemy.orm.Session`, which every service in this codebase already imports as `Session`.
- **`ApiKey`**: a per-developer, role-scoped credential distinct from the operator key. The raw key (`pr_live_...`) is shown exactly once at creation time; only its SHA-256 hash and an 8-character display prefix are stored. SHA-256, not bcrypt: the raw key is a high-entropy generated secret, not a human-guessable password, so a slow salted hash buys nothing here and would cost real latency on every authenticated request instead of only at login -- the same tradeoff Stripe- and GitHub-style API keys make.

Session expiry is **fixed at login, not sliding**: simpler to reason about and to revoke, at the cost of a user being logged out mid-session once the timeout elapses rather than for as long as they stay active. This is a deliberate scope reduction for this phase, not an oversight.

## The Organisation Owner bootstrap

`server/app/services/organization_service.py::ensure_owner_bootstrapped`, called from `main.py`'s existing `lifespan` startup hook (the same pattern already built for evidence-key rotation, `signing_key_service.ensure_current_key_registered`): on every boot, idempotently ensure one `Organization` and one Owner `User` exist. If they already exist, this is a no-op. If not, it creates them with a random, unrecoverable password and logs a warning that the account needs to be claimed.

This never raises: a transient DB issue at boot logs `organisation_owner_bootstrap_failed_at_startup` and lets the app boot anyway, exactly like the signing-key hook. Verified directly (see Testing below) against a real unreachable database: the app still boots, serves `/health`, and correctly rejects an unauthenticated `GET /v1/auth/me` with `401`.

This bootstrap is **additive**, not a migration of the operator key into a new identity. Holding the operator key was, and remains, a full Owner-equivalent bypass on every endpoint -- nothing about that changed. The bootstrapped Owner account is a separate, new, real login for humans who want to start using the new system, alongside the operator key, not instead of it.

### Claiming the bootstrapped account: `POST /v1/auth/setup-owner`

The first version of this bootstrap logged the generated password once via `logger.warning` and called that "the real, disclosed retrieval path." In practice that's not usable: it requires digging through hosting-provider deploy logs, and there's no way to get a fresh password if that log line is ever missed or rotated out. There was no actual way for a real person to get their first account.

The fix: `routers/auth.py::setup_owner`, gated the same way every other administrative endpoint is (`require_permission(Permission.ORGANISATION_MANAGE)`), which means the Operator Key -- a credential every real deployment already has and already treats as fully trusted -- works as a bypass here too. Anyone holding it can set the Owner's real email and password directly, at any time, not just once at first boot. This only ever updates the single bootstrapped Owner row; it never creates a second user. The frontend's `/setup-owner` page (linked from the login page) is this endpoint's UI: enter the Operator Key, choose an email and password, and you're logged in as Owner immediately after.

This is also the practical password-reset story for the Owner account until a real reset-by-email flow exists: hold the Operator Key, visit `/setup-owner` again, set a new password.

## What this doesn't fix

- **MFA is a requirement toggle and a schema field only** (`User.mfa_enabled`), not a full TOTP enrollment/verification flow. Turning it on in Organisation Settings records the requirement; it does not yet challenge anyone at login.
- **Multi-tenancy is schema-shaped but not routed.** The tables support more than one `Organization`; nothing in this phase creates a second one or routes requests by tenant. `get_current_organization` resolves "the one bootstrapped organisation" for an operator-key caller.
- **No brute-force lockout on login** beyond the existing global per-IP rate limiter (`security.py`, 120 req/60s) -- a dedicated login-attempt throttle isn't built in this phase.
- **`resolved_by`/`actor`/`reviewer_id` are still free-text fields.** This phase ties *access* to a real permission; it does not yet rewrite every existing free-text attribution field to reference the resolving `User` directly. **Update (Authority-as-a-continuous-object, Stage D):** `DecisionResolution.resolved_by_user_id` and the RuntimePolicy approve/reject audit trail now additively record the real, authenticated `User` alongside the free-text field, closing this gap for those two specifically. `RuntimePolicy`'s `ApproveRequest`/`RejectRequest` schemas themselves still have no `*_user_id` field of their own -- narrower than originally scoped here, not yet fully closed.
- **No FK constraint** from `ApiKey.created_by_user_id` behavior beyond a plain nullable foreign key -- fine for this phase's scale, not hardened further.

## Testing: what's verified and how

`tests/unit/test_rbac_permissions.py` encodes the spec's exact can/cannot lists as assertions against the pure `ROLE_PERMISSIONS` matrix (e.g. "Reviewer can review but never publish", "Auditor is strictly read-only", "Executive has only assurance.view") -- a future change that silently breaks one of those promises fails a test, not a support ticket. `tests/unit/test_auth_service_crypto.py` covers the pure password-hashing and API-key-hashing functions the same way this codebase already tests `signing.py`'s pure crypto helpers.

Everything that touches the database (session/API-key resolution, the Owner bootstrap actually creating rows, login) has no local Postgres to run integration tests against in this environment, matching the same gap already disclosed in AGENT_LIFECYCLE.md and EVIDENCE_KEY_ROTATION.md for the rest of this codebase's DB-touching services. The bootstrap's failure path was instead verified directly against the real running app (`TestClient`, lifespan triggered): with `DATABASE_URL` pointed at an unreachable host, the app still boots cleanly, `/health` returns `200`, and `GET /v1/auth/me` correctly returns `401 authentication_required`. A real login → session → permission-checked-request round trip has not been exercised against a live database and should be before this is fully trusted in production.

All 153 backend unit tests pass (137 pre-existing plus 16 new).
