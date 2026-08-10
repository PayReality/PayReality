# Sprint 1, Part 4 — Secrets Management Guide

**Status:** final. **Method:** every secret category the directive names, checked directly against the code that handles it.

## Audit

| Category | Exists? | Where | Handling |
|---|---|---|---|
| API keys (per-developer) | Yes | `db/models.py::ApiKey`, RBAC-scoped | Raw secret shown once at creation, only a SHA-256 hash (`key_hash`) plus a non-secret `key_prefix` stored at rest — the same pattern Stripe/GitHub use, by the code's own comment. **No rotation mechanism**: revoking one is delete-and-recreate, not a graceful rotate-with-overlap. |
| API keys (shared operator) | Yes | `ADMIN_API_KEY`, `security.py::verify_operator_key` | Compared with `hmac.compare_digest` (constant-time). **No rotation mechanism at all** — changing the env var and redeploying instantly invalidates every existing integration using the old value, with no grace window. |
| Signing keys (Evidence/audit) | Yes | `EVIDENCE_SIGNING_KEY_B64`/`_ID`, `signing_key_service.py` | **The one secret category with real rotation already built**: a registry (`SigningKey` table) tracks every key ever used, retires the previous key automatically when a new one boots, and preserves historical verification for records signed under a retired key. This is the model the other two categories should be measured against, not rebuilt from scratch. |
| JWT secrets | **N/A — none exist.** | — | Confirmed by direct search: sessions are a database-backed bearer token (the session row's own id), not a JWT. There is no JWT signing secret to manage because there is no JWT. |
| Database credentials | Yes | `DATABASE_URL` | Render-issued connection string, held only as an environment variable, `sync: false` in `render.yaml` (never committed). No separate credential-rotation process beyond whatever re-provisioning the database itself would require. |
| Cloud credentials (Render/Vercel API tokens) | Yes, but held outside this codebase | — | These live with whoever operates the deploy (a human's Render/Vercel account), not in any file this audit can inspect. Out of this repository's control surface by design — noted for completeness, not a code-level finding. |
| Third-party integration credentials | One: `ANTHROPIC_API_KEY` | `config.py`, three `claude_provider.py` call sites | Optional, feature-flagged, no rotation mechanism, but low severity — its absence degrades AI features to `configuration_required`, it does not affect Runtime Authority's core path. |

## Hardcoded secrets

**None found.** A direct pattern search for inline API keys, passwords, and secret-looking literals across `server/app` returned zero real hits (only test fixtures and `settings.*` references, which are correctly reading from configuration, not embedding a value).

## Insecure handling

**None found at the code level.** Constant-time comparison is used where it matters (`hmac.compare_digest` for the operator key); hashing is used where it matters (bcrypt for passwords, SHA-256 for API keys); nothing is logged that shouldn't be (`config.py`'s own comment states this explicitly and the logging code was checked, not just the comment trusted).

## Missing rotation

Two real gaps, both already named above:
1. **`ADMIN_API_KEY` has no rotation mechanism.** This is the platform's full-bypass credential — the highest-value secret in the system — and it's also the one with the weakest rotation story.
2. **Per-developer API keys** can be revoked but not rotated gracefully (no overlap window between old and new).

The Evidence signing key is the one category already solved correctly and needs no further work this sprint.

## Missing isolation

- **No environment-level secret isolation is enforced by anything other than convention.** Nothing prevents someone from accidentally reusing the same `EVIDENCE_SIGNING_KEY_B64` or `ADMIN_API_KEY` value across local, staging, and production — it would still work, silently, which is worse than failing loudly. [03_ENVIRONMENT_STANDARD.md](03_ENVIRONMENT_STANDARD.md) states the requirement; nothing technical currently enforces it.
- **No secrets manager exists** (AWS Secrets Manager, HashiCorp Vault, Doppler, or equivalent) — every secret is a plain environment variable in Render's/Vercel's own store.

## Recommended minimum secure solution

**Do not introduce a dedicated secrets-manager service this sprint.** Render's and Vercel's built-in environment-variable stores, marked `sync: false`, already provide "not committed to git, encrypted at rest by the platform, accessible only to those with deploy access" — which is the actual security property a secrets manager would add at this company's current size. Introducing Vault or AWS Secrets Manager now would be operational overhead (a new service to run, monitor, and back up) with no concrete threat this audit found that it would close. The threshold at which it becomes justified is concrete and named here for later, not guessed at: **once secrets need to be shared across more than Render/Vercel's own platforms** (e.g., a Kubernetes cluster, a second cloud provider, or a compliance requirement that specifically names centralized secret rotation audit logs — SOC 2 may eventually ask for this, but that is Sprint 2+ territory per this sprint's own stop condition).

What **is** recommended, all within the existing model:
1. Extend `ADMIN_API_KEY`'s handling to support a brief dual-key overlap window during rotation (accept either the current or the immediately-previous value for some bounded period), the smallest change that closes the sharpest gap.
2. Add the same environment-isolation discipline the signing key already has — a one-line pre-deploy check that a new environment's secret values don't match another environment's, catching an accidental copy-paste before it ships.
3. Document (not automate yet) a fixed rotation cadence for `ADMIN_API_KEY` and per-developer API keys — e.g., annually or on any suspected exposure — since a documented-but-manual process is proportionate at today's scale, and automating a rotation schedule nobody has ever needed to invoke yet would be speculative work this sprint's own directive rules out.

Concrete tasks for all of this are in [08_ENGINEERING_IMPLEMENTATION_PLAN.md](08_ENGINEERING_IMPLEMENTATION_PLAN.md).
