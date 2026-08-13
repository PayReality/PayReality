# Architecture

> **This document is superseded by [SPECIFICATION/00_INDEX.md](SPECIFICATION/00_INDEX.md).** It is kept in place as a design-time record, not deleted or rewritten, but where its description of the live decision path conflicts with the specification — most notably: it still describes the legacy Authority/Mandate pipeline as live, which was fully retired (see [SPECIFICATION/17_LEGACY_COMPONENTS.md](SPECIFICATION/17_LEGACY_COMPONENTS.md)) — the specification is current and this document is not. See [SPECIFICATION/16_CURRENT_LIMITATIONS.md](SPECIFICATION/16_CURRENT_LIMITATIONS.md) §16.2 for the full reconciliation.

This describes the system as it actually exists in this repository, not the aspirational version. Where something is a known gap rather than a design choice, it's marked as such and cross-referenced to [VERSION_3_ROADMAP.md](VERSION_3_ROADMAP.md).

## System overview

```
                        ┌─────────────────────┐
                        │   Frontend (Vercel)  │
                        │  React + Vite SPA    │
                        └──────────┬───────────┘
                                   │ HTTPS, VITE_API_URL
                                   │ (CORS: single allowed origin)
                                   ▼
                        ┌─────────────────────┐
                        │   FastAPI backend    │
                        │   server/app/main.py │
                        └──┬────────────┬──────┘
                           │            │
                 ┌─────────┘            └─────────┐
                 ▼                                 ▼
        ┌────────────────┐                ┌────────────────┐
        │   PostgreSQL    │                │  Open Policy    │
        │  (system of      │                │  Agent (OPA)    │
        │   record)        │                │  Rego evaluator │
        └────────────────┘                └────────────────┘
```

The backend is a single FastAPI process. It is the only thing that talks to Postgres or OPA; the frontend never does. OPA has no auth of its own (see SECURITY.md); it must never be reachable from outside the backend's private network, or, in the current zero-cost pilot deployment, it runs embedded in the same container bound to loopback only, which is never reachable from any other service at all (see DEPLOYMENT.md).

## The Runtime Authority pipeline

This is the core of the product: everything else (frontend pages, the policy pipeline, evidence) exists to feed or expose this:

1. **Onboarding** (`server/app/services/document_service.py`, `domain/extraction/`): a delegation-of-authority PDF is uploaded and parsed into candidate Authorities (scope, limit, currency, conditions) via `ClaudeExtractionProvider` when `ANTHROPIC_API_KEY` is set, or a deterministic `FakeExtractionProvider` fallback for environments without it. Extraction failure doesn't fail the upload: the document lands in `extraction_failed` status and can be retried (`server/app/routers/policies.py::upload_document`).
2. **Human review** (`services/review_service.py`): a human approves or rejects each extracted Authority, optionally editing the extracted limit/currency/conditions. The *original* AI-extracted values are retained in separate `extracted_*` columns even after an edit, so a later audit can see what the AI proposed versus what a human actually approved.
3. **Compilation** (`domain/compiler/compiler.py`, `services/policy_service.py`): approved Authorities for a document compile into a new draft Policy: a set of Mandates (per-principal, per-scope limits and review thresholds) plus a Rego bundle, hashed (`bundle_hash`) so any later drift between the DB's record of what was compiled and what's actually loaded into OPA is detectable. `CompilationConflictError` surfaces when two Authorities produce contradictory Mandates rather than silently picking one.
4. **Activation** (`policy_service.activate_policy`): the compiled bundle is pushed into OPA (`HttpOpaClient.upload_policy`/`upload_data`), and exactly one Policy row can be `status = 'active'` at a time, enforced by a Postgres partial unique index (`idx_policies_single_active`), not just application logic. Reactivating a previously-retired version's id is the rollback mechanism; there is no separate "rollback" endpoint because none is needed.
5. **Decision** (`domain/decision/engine.py::evaluate`): an Agent's signed Intent is turned into an OPA input document (`{intent, context, agent, policy_version}`) and queried against the active bundle. The result is one of `ALLOW`, `DENY`, or `HUMAN_REVIEW`; and critically, the *only* path to `ALLOW` requires OPA to explicitly return `allow: true` with `deny` not also true. An OPA timeout, an OPA error, or no active Policy at all all resolve to `HUMAN_REVIEW`. This is Principle 8 (fail-closed) enforced at the type level, not by convention: `evaluate()` has no code path that returns `ALLOW` except the one explicit success case.
6. **Evidence** (`domain/evidence/signing.py`, `services/intent_service.py`): every Decision writes an Evidence record: the Decision's outcome, the Intent that produced it, and the Mandates evaluated, canonically serialized (sorted keys, no whitespace) and ED25519-signed over its SHA-256 digest. A `HUMAN_REVIEW` decision that's later resolved appends a *second* Evidence record (via `resolution_service.resolve_decision`) rather than mutating the first; the Decision row is genuinely immutable after creation, matching the "created once, never updated" lifecycle guarantee.
7. **Assurance** (`src/app/live/pages/LiveAssurance.tsx`): reads real counts (agents, policies, decisions by outcome) from the live API. No synthetic scoring, no seeded numbers.

## Data model

Postgres, managed via Alembic (`server/alembic/versions/`, 4 migrations to date). Key tables and the relationships that matter:

```
Principal ──< Authority ──< Mandate >── Policy ──< Decision >── Evidence
    │             │                                    │
    └──< Agent ──< Certificate                     Intent (1:1 with Decision)
                                                        │
                                              DecisionResolution (0/1 per Decision)
```

- **`Base.type_annotation_map`** forces every `datetime` column to `TIMESTAMPTZ`: a deliberate fix for a real bug hit during development (the local Postgres install's server timezone defaulted to UTC+2; without this, timezone-aware Python datetimes silently converted to server-local wall-clock time on write, which broke Mandate validity-window comparisons against Intent timestamps in the Rego bundle). This is why every timestamp column is explicit rather than left to Postgres's bare `TIMESTAMP` default.
- **`reviewer_id`** and **`resolved_by`** are free-text columns, kept exactly as every existing reader depends on. A real `users` table and RBAC now exist (RBAC.md); `resolved_by_user_id` (on `DecisionResolution`) and the approve/reject audit fields (on `RuntimePolicyRecord.content.audit`) additively record the real, authenticated `User` alongside the free-text field when a session exists (Authority-as-a-continuous-object, Stage D) -- the free-text columns themselves were not removed or replaced.
- **JSONB** is used for genuinely variable-shape data (Intent `context`, Authority/Mandate `conditions`, Evidence `payload`), not as a substitute for real columns anywhere a fixed schema was knowable.
- **`Evidence.status`** (`VERIFIED`/`PENDING`/`REJECTED`) is set at creation time based on the resolution outcome, not derived from a live signature check; `POST /v1/evidence/{id}/verify` is the actual cryptographic check and is intentionally a separate, repeatable operation.

## Auth architecture

Three distinct mechanisms exist today (full detail in `docs/API_SPECIFICATION.md`'s auth table and in SECURITY.md):

1. **Agent signature** (`app/domain/auth/signature.py`, `app/dependencies.py::verify_agent_signature`): the only mechanism that existed before this pass. An Agent's Certificate holds an ED25519 keypair; the private key is generated client-side and never transmitted (`src/app/live/pages/LiveAgents.tsx` + `crypto.ts`). Every `POST /v1/intents` is signed over the raw request body and checked against a timestamp window (`INTENT_SIGNATURE_WINDOW_SECONDS`) to prevent replay.
2. **Operator key** (`app/security.py::verify_operator_key`): added in this pass. A single shared `ADMIN_API_KEY`, compared with `hmac.compare_digest`, gating every endpoint that mutates Policy state or resolves a `HUMAN_REVIEW` decision. This is explicitly a stand-in for a real human RBAC system, not a design endpoint; see SECURITY.md and the roadmap for why it's proportionate today and what replaces it.
3. **None**: every read endpoint. This is a deliberate current-state choice, not an oversight: there's no user-identity system yet to authorize reads *against*, and the frontend's dashboards need to read this data. It stops being appropriate the moment a second, mutually distrusting tenant exists (see roadmap V3.2).

## Request lifecycle

Every request passes through exactly one middleware (`app/security.py::observability_middleware`), which:

1. Applies a per-client-IP fixed-window rate limit (429 if exceeded).
2. Assigns/propagates an `X-Request-ID`.
3. Calls the route handler, catching any unhandled exception and converting it to a clean `{"detail": "internal_error"}` 500 (the real exception is logged server-side with the same request id, never leaked to the caller).
4. Adds security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and `Strict-Transport-Security` when `ENVIRONMENT=production`).
5. Logs one structured JSON access line per request.

This was deliberately built as one middleware rather than several stacked ones: an earlier version split rate limiting, headers, and logging into three separate `app.middleware("http")` functions, and a route handler's exception was silently lost between layers (Starlette's `BaseHTTPMiddleware` has a documented history of this), producing an empty 500 body instead of the clean JSON one. Caught by testing before merge; the single-middleware version is the fix, not a stylistic preference.

CORS is a single configured origin (`CORS_ORIGIN`), not a wildcard, with an explicit method and header allowlist.

## Frontend architecture

React 18 + Vite 6 + react-router 7, no server-side rendering (that's the marketing site's pattern, not this app's; this is an authenticated operational tool, not a page that needs to be indexed). One route tree (`src/app/routes.tsx`), one nav (`src/app/components/Layout.tsx`), ordered to match the actual workflow: Overview → Authority → Policy → Runtime Decisions → Evidence → Assurance. Every legacy path from the pre-consolidation app (`/command-center`, `/authority-center`, etc.) redirects to its new home rather than 404ing.

`src/app/live/apiClient.ts` is the only thing that talks to the backend: a thin `fetch` wrapper, no state-management framework, no client cache layer, because the data volumes here don't need one yet. It attaches the operator key (from `localStorage`, entered via `OperatorKeyField` in the sidebar) to every request that has one set; unauthenticated/mis-keyed requests surface the backend's real error message rather than failing silently.

## Deployment architecture

See DEPLOYMENT.md for the full recommendation and rationale, and MILESTONE_4_AZURE_PRODUCTION_READINESS_SUMMARY.md for current live status. In short: frontend stays on Vercel (already working); backend is containerized (`server/Dockerfile`), which today runs on Render (the live production host) and, in parallel, on Azure Container Apps (the verified target platform, not yet cut over). In the current Render deployment, OPA runs embedded in the same container (loopback-only) and the existing free-tier Postgres is reused; once billing exists there, or on Azure once cutover happens, the recommended topology reverts to OPA as its own service and a paid, persistent Postgres (already true on Azure's side, per the milestone document above).

## Known architectural gaps (by design, not oversight)

These are named explicitly rather than left implicit, per the roadmap's phasing:

- **No human user/RBAC system.** `resolved_by` and `reviewer_id` are free-text identity strings; the operator key gates *that a* caller is a legitimate operator, not *which* operator. Building a full multi-user system before there's a second real user to build it for would be exactly the kind of premature complexity this rebuild was meant to remove.
- **Single evidence signing key, no rotation.** `Evidence.key_id` is stored per-record (schema-ready for multiple keys), but `evidence_service.verify_evidence` always verifies against whichever key is *currently* configured, not a historical registry keyed by `key_id`. Rotating the signing key today would silently break verification of everything signed under the old one. A real key registry (`key_id -> public_key`, retained indefinitely) is scoped in the roadmap, not shipped speculatively now.
- **No cryptographic chaining between Evidence records.** Each Evidence row is independently signed and tamper-evident on its own, but nothing links consecutive Evidence for the same Decision into a hash chain, so a deleted or reordered row is not, on its own, detectable from the Evidence table alone. Mitigated today by database-level access control and audit logging at the infrastructure layer (see SECURITY.md); a real hash-chained ledger is a roadmap item, not something to bolt on without designing the migration properly.
- **Rate limiting is in-process memory.** Fine for a single instance; a second instance would need this backed by shared state (Redis or equivalent) to actually limit anything.
