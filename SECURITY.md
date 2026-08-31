# Security

> **This document is superseded by [SPECIFICATION/14_SECURITY_MODEL.md](SPECIFICATION/14_SECURITY_MODEL.md).** It is kept in place as a design-time record, not deleted or rewritten, but it predates RBAC's actual shipped shape and the entire Trusted Integration Architecture (Action Mapping, Trusted Connection, Runtime Connection, the Adapter-mediated runtime path — see [SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md](SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md)). Where this document's description of authentication/authorization conflicts with the specification, the specification is current and this document is not.

A full review of this codebase's security posture as it actually stands, written the same way the rest of this pass was done: real findings, real fixes where a fix was proportionate, and named gaps where it wasn't yet.

## Authentication

Four mechanisms exist.

- **Agent signature** (`server/app/domain/auth/signature.py`): an Agent's ED25519 private key is generated client-side (`src/app/live/crypto.ts`) and never transmitted; only the public key is registered server-side via `POST /v1/agents`. Every `POST /v1/intents` is signed over the raw request body, and the signature is checked against the stored public key plus a timestamp window (`INTENT_SIGNATURE_WINDOW_SECONDS`, default 300s) to bound replay. This is real, working, and was already in place before this pass.
- **Operator key** (`server/app/security.py::verify_operator_key`), added in an earlier pass and unchanged since: `ADMIN_API_KEY` is a single shared secret, checked with `hmac.compare_digest` (constant-time, avoiding a timing side-channel), required via `X-PayReality-Operator-Key`. A present, correct key is still a full bypass on every gated endpoint -- every existing integration built against it keeps working with zero changes.
- **Human login + session** (RBAC.md, added in this pass): `POST /v1/auth/login` authenticates a real `User` (bcrypt-hashed password) and returns a session bearer token, which is the session id itself, not a JWT -- validating it is one indexed lookup against a row the database can revoke instantly. Fixed expiry at login (not sliding), a deliberate scope reduction.
- **API keys** (RBAC.md, added in this pass): a per-developer, role-scoped credential distinct from the operator key. The raw secret is shown once at creation and only its SHA-256 hash is stored.
- **None (by design)**: every `GET` and the evidence-verification endpoints. There's no per-tenant boundary to authorize reads *against* yet (single-tenant today), and the frontend's own dashboards need this data. This stops being correct the moment there's a second, mutually distrusting tenant (see VERSION_3_ROADMAP.md).

**What changed in this pass**: a real permission system now sits alongside the operator key (`server/app/domain/rbac/permissions.py`, `server/app/dependencies.py::require_permission`). Six fixed roles, each mapped to a fixed set of permissions; every mutating endpoint checks a permission, never a role directly. This is additive: the operator key is not deprecated, replaced, or weakened by this -- it remains a full, working Owner-equivalent bypass, unchanged. `resolved_by` and `reviewer_id` remain free-text fields for now; this phase ties *access* to a real identity and permission, not yet *attribution* of every historical free-text field (see RBAC.md's "What this doesn't fix"). Full detail in RBAC.md.

## Authorization

Enforced entirely at the endpoint/dependency level, not at the row level; there's no concept of "this user can only touch this principal's data" because there's only one tenant. This is correct today and named as a hard requirement before onboarding a second tenant, not an oversight to catch later. Enforcement itself is now permission-based (`Depends(require_permission(Permission.X))`) rather than a single undifferentiated "is this a legitimate operator" check -- see RBAC.md for the full mapping from role to permission to endpoint.

## Secrets management

- `EVIDENCE_SIGNING_KEY_B64` and `ADMIN_API_KEY` are read from environment variables (`server/app/config.py`, `pydantic-settings`), never hardcoded, never logged.
- **Boot-time enforcement, added in this pass**: `server/app/main.py::_validate_production_config` refuses to start at all when `ENVIRONMENT=production` and either secret (or a non-default `CORS_ORIGIN`) is missing. Previously the app would boot "successfully" with an empty signing key and silently produce unverifiable Evidence, or boot with every operator endpoint wide open; both now hard startup failures instead of silent degradation.
- **Not yet done**: secrets live in host-level env vars, not a dedicated secrets manager. Acceptable for the pilot-scale deployment recommended in DEPLOYMENT.md; a hard requirement (AWS Secrets Manager / Azure Key Vault, ideally HSM-backed for the signing key specifically) before the Series-A-scale deployment in that same document.

## Injection

- **SQL**: 100% SQLAlchemy ORM / Core with parameter binding (`db.get`, `select(...)`, `db.scalars(...)`): no raw string-interpolated SQL anywhere in `server/app`, including the one raw-SQL readiness check (`text("SELECT 1")`, a static string with no interpolation).
- **NoSQL/command injection**: not applicable; no shell-out, no dynamic query construction against OPA (the input document is a structured dict serialized by `httpx`, not string-built).
- **Rego injection**: policy content itself is only ever written by `HttpOpaClient.upload_policy`, and the Rego source comes from Compiler V2 (`domain/compiler_v2/compiler_v2.py` -> `bundle_builder.py`), not directly from user input. **Correction (Runtime Governance Architecture, Phase 5, [44_PHASE_5_ARCHITECTURAL_DRIFT_REPORT.md](SPECIFICATION/44_PHASE_5_ARCHITECTURAL_DRIFT_REPORT.md)):** this bullet previously named the legacy compiler (`domain/compiler/compiler.py`) and the "operator-key-gated `activate_policy` flow" as the live path -- both are retired (`routers/policies.py`'s `activate_policy` now returns HTTP 410; see SPECIFICATION/17_LEGACY_COMPONENTS.md). The one live write path today is `runtime_policy_service.deploy_policy`, gated by the `RUNTIME_POLICY_PUBLISH` RBAC permission (RBAC.md), not an operator key.

## Policy tampering

This is the most consequential attack surface in the whole system, because a tampered policy silently changes what gets `ALLOW`ed. Two real controls exist:

1. **`bundle_hash`** on every `Policy` row: a hash of the compiled bundle, letting a later audit detect drift between what the database says was activated and what's actually loaded into OPA.
2. **Network isolation of OPA itself**: OPA's own HTTP API (`upload_policy`, `upload_data`) has **no authentication of its own**. It trusts whatever can reach it. The only thing standing between "anyone on the internet" and "silently rewriting the active authorization policy" is that OPA must never be exposed on a public address; it must only be reachable from the FastAPI backend, on a private network. **This is called out explicitly in DEPLOYMENT.md's hosting recommendation and must be verified at every deploy**, not assumed. If OPA is ever accidentally exposed (a misconfigured security group, a debug port left open), that is a full authorization bypass, not a minor issue.

## Replay attacks

Two independent layers, both already in place before this pass:

- **Intent-level**: `nonce` + `agent_id` uniqueness constraint (`uq_intents_agent_nonce`) at the database level: a replayed Intent with the same nonce from the same agent is rejected regardless of timing.
- **Signature-level**: `requested_at` must fall within `INTENT_SIGNATURE_WINDOW_SECONDS` of the server's clock, bounding how long a captured signed request stays valid even before the nonce check runs.

## API abuse / rate limiting

**Added in this pass** (`server/app/security.py`): a fixed-window limiter (120 requests/60s per client IP, or per `X-Forwarded-For` when behind a proxy) applied globally. Before this, there was no limit of any kind; a single client could exhaust database connections or brute-force the operator key with unlimited attempts. Known limitation: the counter is in-process memory, so it only limits traffic to a single instance. Scaling to more than one backend instance requires moving this to shared state (Redis or equivalent) first; this is noted in ARCHITECTURE.md and DEPLOYMENT.md so it isn't discovered the hard way after a second instance is already live.

## Evidence integrity and cryptography

- **Algorithm**: ED25519 (via `pynacl`), signing the SHA-256 digest of a canonically-serialized (sorted keys, no incidental whitespace) JSON payload. This is a modern, well-regarded signature scheme, not a custom cryptographic construction.
- **Independent verifiability, added in this pass**: `GET /v1/evidence/verification-key` publishes the current public key, so a regulator, insurer, or auditor can verify a signature themselves (offline, without this server, without trusting this server's own `/verify` endpoint). Before this pass, verification was only possible by trusting this system's own `POST /v1/evidence/{id}/verify` result, which is a materially weaker guarantee for exactly the audiences (insurers, regulators) this evidence exists for.
- **Key rotation, fixed in this pass**: a `signing_keys` registry (`key_id -> public_key`, retained forever, never deleted) now backs verification: `evidence_service.verify_evidence` and `agent_service.verify_audit_event` both resolve the public key by the record's own `key_id` through this registry, not from whichever key is currently configured. Rotating `EVIDENCE_SIGNING_KEY_B64`/`_ID` and redeploying now retires the old key's registry row and registers the new one automatically (`main.py`'s startup hook, `signing_key_service.ensure_current_key_registered`) without invalidating anything signed under the old key. See EVIDENCE_KEY_ROTATION.md for the full mechanism and the operational rotation flow. `GET /v1/evidence/verification-keys` publishes the entire key history (active and retired) for offline verification of any record regardless of when it was signed.
- **Hash-chaining between records, implemented**: each Evidence row is independently tamper-evident (its own signature covers its own payload), and consecutive Evidence records for the same Decision are also cryptographically linked: every new record embeds `previous_hash`, the hash of the record immediately before it (`intent_service.py`'s `_previous_chain_hash`, verified by `evidence_service.verify_chain`, tested in `test_evidence_payload.py`/`test_signing.py`). A row deleted or reordered directly from the database (bypassing the API entirely) breaks the link at the exact gap it left, even though every remaining record's own signature still checks out, this is checkable independently of infrastructure-level audit logging (database access logs, which should still be enabled and monitored at the hosting layer per DEPLOYMENT.md; the chain check is a complement to that, not a replacement for it). Records written before this mechanism shipped (v1, pre-chaining) never had a `previous_hash` field at all; their absence of the field is expected and never treated as a break.
- **What a `false` verification result means**: per `verify_evidence`'s own docstring, a failed verification is a P1 operational signal (evidence of tampering or corruption) and must be treated as an incident by any caller, not logged as a routine negative result.

## Dependency and supply-chain posture

Checked directly as part of this pass, not assumed:

- **Frontend** (`npm audit`): found 3 vulnerabilities (1 critical: `tar`; 2 high: `react-router`, `vite`) at the start of this pass. **Fixed in this pass** by bumping `react-router` 7.13.0 → 7.18.1 and `vite` 6.3.5 → 6.4.3 (both same-major-version bumps, rebuilt and route-tested afterward; see the V3 execution notes for the verification transcript). `npm audit` now reports zero vulnerabilities.
- **Backend** (`pip-audit`): zero vulnerabilities found in any of the actual runtime dependencies (FastAPI, SQLAlchemy, psycopg, pynacl, httpx, anthropic, pypdf). The only advisories found were against `pip` itself (the packaging tool, not a runtime dependency of the deployed app), noted, not treated as a real finding.
- **Dependency footprint**: kept deliberately small (9 direct frontend dependencies after the V2 pass, 12 backend dependencies): a smaller dependency graph is a smaller attack surface, and this was a real design constraint during the V2 rebuild, not incidental.

## Transport and headers

- **HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy**, all added in this pass (`server/app/security.py::observability_middleware`). Previously none were set at all, meaning every response was missing basic clickjacking/MIME-sniffing/referrer-leak protection.
- **CORS**: a single explicit allowed origin (from `CORS_ORIGIN`), not a wildcard, with an explicit method allowlist (`GET, POST, PATCH`) and header allowlist, tightened in this pass from `allow_methods=["*"], allow_headers=["*"]`.
- **TLS**: terminated at the hosting platform (Vercel for the frontend already; Render for the backend today, with Azure Container Apps verified as the target platform and not yet cut over, per DEPLOYMENT.md and MILESTONE_4_AZURE_PRODUCTION_READINESS_SUMMARY.md), not something this application handles itself, correctly.

## Error handling and information disclosure

**Fixed a real bug in this pass**: the original three-middleware design lost unhandled exceptions between layers (a documented Starlette `BaseHTTPMiddleware` interaction), producing an *empty* 500 response body instead of a clean error (confusing, but not itself a leak). Collapsing to one middleware (`observability_middleware`) fixed this and made the guarantee explicit: every unhandled exception is caught, logged server-side with a `X-Request-ID` for correlation, and returned to the caller as a bare `{"detail": "internal_error"}`: no stack trace, no internal path, no library version ever reaches the client.

## What would make this materially stronger next (see VERSION_3_ROADMAP.md for sequencing)

1. Tie `resolved_by`/`reviewer_id`/`actor` to the resolving `User` directly now that real identity exists (RBAC.md), rather than leaving them free-text.
2. A full MFA challenge/verification flow -- today's `mfa_required` is a requirement flag and schema field only (RBAC.md).
3. Rate limiting backed by shared state once there's more than one backend instance.
4. A secrets manager (not env vars) once there's a real production account provisioned.
