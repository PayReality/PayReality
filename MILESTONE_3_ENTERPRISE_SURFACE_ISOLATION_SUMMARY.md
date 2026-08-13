# Milestone 3 — Enterprise Surface Isolation — Summary

**Status: Complete.** 13 implementation/documentation commits, 345/345 server unit tests passing, 14/14 real-OPA integration tests passing, 68/68 Python SDK unit tests passing, one clean frontend production build. No code from Milestone 2 (Runtime Authority, Runtime Policies, OPA package isolation) was touched or redesigned, per this milestone's own explicit instruction.

**Roadmap reference:** `PAYREALITY_ENTERPRISE_HARDENING_PLAN.md`; `MILESTONE_2_MULTI_TENANT_FOUNDATION_SUMMARY.md`; `MULTI_TENANT_ARCHITECTURE_VERIFICATION.md` (the read-only audit that named every BLOCKER this milestone closes).

---

## Implementation Summary

Milestone 2 made Runtime Authority genuinely multi-tenant. `MULTI_TENANT_ARCHITECTURE_VERIFICATION.md` then independently audited the rest of the platform and found the isolation had not propagated anywhere else: five confirmed BLOCKERs (unguarded Authority Builder mutating endpoints, a fully unauthenticated AI Policy Builder pipeline, a crashing Evidence-chain-verification endpoint, an unauthenticated Agent Detail Page/Agent list, and no way to create a second Organization at all), plus a cross-tenant authorization gap in a Runtime Policy background operation, plus zero organization scoping in Blob Storage/Azure AI Search, plus a fully broken SDK. This milestone closed all of it — the "transition of every remaining enterprise-facing surface to the new architecture" the prompt asked for.

**Repository audit, before implementation:** a full-repo grep sweep for `organization_id`, `organization`, `tenant`, `Operator Key`, `global`, `default organization`, `first organization`, `shared cache`, `platform admin` across `server/`, `src/`, `sdk-python/`, and `scripts/`, plus five parallel deep-read passes (Identity/Authority Graph, Runtime Policy/OPA cross-check, Evidence/AI Policy Builder, SDK/platform-global-state, Blob/Search/background-jobs) and one frontend-specific pass, none of which relied on the prior verification report's own conclusions without independently re-reading the current code.

### 1. Authority Builder

Five mutating endpoints (`resolve_principal`, `resolve_relationship`, `activate_relationship`, `answer_question`, `approve_graph`) and one read endpoint (`get_principal_candidates`) had no organization check of any kind — gated only by `Permission.AUTHORITY_REVIEW`, a capability check that says nothing about *whose* data is being touched. `approve_graph` was the worst instance: it took a `corpus_id` but never verified ownership, so any reviewer in any organization could pull another organization's full corpus snapshot and write a falsely-attributed approval record into that organization's own audit trail. Fixed with three new router-level dependencies (`_authorized_authority_principal`, `_authorized_relationship`, `_authorized_question`), each resolving the target row's own corpus and comparing `organization_id` against the caller's — mirroring `_authorized_corpus`'s existing convention exactly. `approve_graph` now depends on `_authorized_corpus` directly.

**Disclosed, not fixed:** `AuthorityRelationship.cross_org_approved` remains dead schema — defined, never read anywhere in the codebase. Wiring it in (verifying the two principals in a relationship, not just the corpus, belong to the same organization) is a genuine improvement beyond this fix's literal scope, tracked as a follow-up.

### 2. AI Policy Builder

The single-document pipeline had no organization concept at all: `PolicyExtractionUpload`/`PolicyExtractionCandidate` had no organization column, five read endpoints were reachable with zero authentication, and `promote_candidate`'s existing `CrossOrganizationPromotionError` guard (Milestone 2) only ever fired for the `corpus_id` path — every single-document candidate has `corpus_id=None` by construction, so the guard never protected this pipeline. `PolicyExtractionUpload` gained a nullable `organization_id` column; `PolicyExtractionCandidate` deliberately did **not** get its own — it resolves via exactly one of its two parents (`upload_id` or `corpus_id`), mirroring the existing "resolve through the parent" convention. `list_candidates` (callable with neither filter) previously returned every organization's candidates unconditionally; fixed via an outer join through both possible parents. Every endpoint now depends on `get_current_organization`; a new `_authorized_upload` dependency mirrors `_authorized_corpus`.

### 3. Organization Lifecycle

Built from nothing: before this milestone, `Organization(...)` was constructed in exactly one place in the entire codebase (`ensure_owner_bootstrapped`, a startup-only hook). Now:
- **Create/list/update/deactivate/reactivate/archive** an arbitrary organization (`routers/organization_lifecycle.py`, `/v1/organizations`), gated on `verify_operator_key` — platform-admin-only, no session/role fallback. `require_permission`'s operator-key branch can't express this: `Role.OWNER` holds every `Permission` via `_ALL_PERMISSIONS`, so no new Permission value could ever be operator-key-exclusive within that system.
- **Invite/accept/revoke membership** (`routers/organization.py`'s new `/invitations` endpoints, `routers/auth.py`'s new `POST /v1/auth/accept-invitation`) — the real email-and-accept flow `POST /v1/users` never was: a one-time, SHA-256-hashed token (same pattern as `api_keys.key_hash`), delivered however the inviter chooses, since this platform sends no email itself.
- **Organization Discovery**: `GET /v1/organizations` lists every organization, so a platform admin holding only the Operator Key can learn which ids are valid for `X-PayReality-Organization-Id`.
- **Default Organization Selection / Organization Switching**: deliberately *not* built as stateful concepts. A session-token user belongs to exactly one organization (`User.organization_id`, `NOT NULL`) — there is nothing to switch between. The Operator Key has no default by design (Milestone 2) and now must always name its target explicitly per request, which *is* "switching," expressed statelessly rather than via a server-side session concept this platform's auth model doesn't otherwise have.
- **Membership Validation**: `accept_invitation` checks token existence, pending status, and expiry before a `User` row is ever created.
- **`ensure_owner_bootstrapped`** no longer resolves "the organization" via "whichever is oldest" — it runs its create-org-and-owner logic only when zero organizations exist anywhere, removing the last "first organization" assumption in the codebase (the other instance, the Operator Key's own default, was already fixed in Milestone 2).

### 4. Agent Platform

`GET /v1/agents`/`GET /v1/agents/{id}` had no organization check (the pre-milestone audit's finding); auditing every agent endpoint per this milestone's own scope found the same gap on `create_agent`, every single-agent mutation (update/delete/activate/suspend/retire/revoke/rotate/transfer, plus certificate/audit-event reads), and all four bulk operations. `Agent` has no `organization_id` of its own — reachable only via `acting_for_principal_id` → `Principal.organization_id`. Fixed with a new `_authorized_agent` router dependency (applied to every single-agent endpoint except `heartbeat`, already correctly self-scoped via signature verification), `list_agents` filtering via an inner join through `Principal`, and `bulk_transition` checking each `agent_id` before acting.

### 5. Evidence Platform

`GET /v1/evidence/chain/verify` — the one endpoint built for credential-free third-party verification — crashed (`TypeError`) for any organization with real data: `verify_chain` called `verify_evidence(db, record.id)` omitting the required `organization_id` argument, with zero prior test coverage. One-line fix; two new tests. The rest of the Evidence Platform (`get_evidence`/`list_evidence`/`verify_evidence`, the `/organization/exports/evidence` download, hash-chain independence per organization) was already correctly scoped from Milestone 1 and required no changes.

### 6. Blob Storage

`upload_document_to_blob`'s path gained an organization segment (`authority-corpora/{organization_id}/{corpus_id}/...`, `"unscoped"` for the legacy `None` scope). No delete/cleanup/retention path exists for documents of *any* organization — confirmed nothing deletes the underlying DB row either, so this is a pre-existing "nothing is ever cleaned up" gap, not a new leak; out of this milestone's isolation-specific scope.

### 7. Azure AI Search

The index schema gained a filterable `organization_id` field. Azure AI Search doesn't support adding a field to an existing index in place, so the index name itself was bumped (`config.py`'s `azure_ai_search_index_name` default, `-v2`), letting the existing idempotent "check if exists, else create" logic create the new schema fresh. `retrieve_corpus_text`'s query filter now requires `organization_id` to match, not just `corpus_id` — defense in depth.

### 8. Background Jobs

Full inventory taken (nothing beyond what was already known): `_reconcile_opa_with_active_policies` and `_ensure_authority_intelligence_search_index` (both startup-only, the latter now producing an org-aware index per #7 above) and `process_due_schedules` (externally triggered, no in-process scheduler exists anywhere in this platform). `process_due_schedules`'s own per-schedule organization threading was already correct; its *router-level authorization gate* was not — `Permission.RUNTIME_POLICY_PUBLISH` is held by any tenant's own Owner/Governance Admin, so one tenant could trigger execution of every *other* tenant's due schedules using nothing but their own session token. Fixed by switching to `verify_operator_key`.

### 9. SDK

`Configuration.organization_id` (new field), attached alongside the Operator Key on every `operator_auth=True` call in `HttpClient.request`, raising the same clear `AuthenticationError` already used for a missing `api_key`. Version bumped `0.1.0` → `0.2.0` — a real breaking change under semver. A genuinely independent, pre-existing bug was also found and fixed in the same pass: `_resolve_principal_id`'s own `GET /v1/principals` call sent zero credentials at all, 401'ing on every real deployment since Milestone 1 gated that endpoint — masking the `organization_id` requirement entirely, since `register()` never got far enough to need it. `scripts/smoke_test.py` updated to match (`PAYREALITY_ORGANIZATION_ID`), plus two more independent pre-existing header bugs fixed in the same file (`verify_evidence`, `check_assurance` previously sent no headers at all).

### 10. Frontend

Every page already flows through `apiClient.ts`'s single `request()` choke point, and a session-token user belongs to exactly one organization by schema design — so the "no page should assume a single organization exists" requirement reduces to: (a) the Operator Key path, which is genuinely platform-admin and needed the header, and (b) a UI for the brand-new Organization Lifecycle endpoints, which had none. Built: `organizationId.ts` (mirrors `operatorKey.ts`), `apiClient.ts` header injection, `OperatorKeyField.tsx`'s new organization-id input, a new `PlatformOrganizationsPage.tsx` (`/organization/platform`), and an "Invite a member" section added to `UsersPage.tsx`.

---

## Architecture Decisions

- **`verify_operator_key` as a distinct, platform-admin-only primitive**, not a new `Permission` value. `Role.OWNER: _ALL_PERMISSIONS` means Owner automatically inherits any Permission ever added, so no Permission can be made operator-key-exclusive within `require_permission`'s existing design. `verify_operator_key` already existed, unused by any router, and is exactly the right shape (Operator-Key-only, no session/role fallback).
- **`PolicyExtractionCandidate` resolves organization via its parent, never its own column** — extends the existing "resolve through the parent" pattern (already used for every corpus-scoped Authority Graph table) to the AI Policy Builder's own upload/corpus duality, rather than introducing a third, independent organization column that could drift from the other two.
- **Organization Switching/Default Selection deliberately not built as stateful UI concepts** — this platform's auth model is stateless-per-request (session/API-key/operator-key resolve identity fresh on every call), and a normal user has exactly one organization by schema design. Building a "current org" server-side session concept for a case that doesn't structurally exist would have been scope invented, not scope required.
- **`ensure_owner_bootstrapped` simplified, not just patched** — since `create_organization`'s own single `db.commit()` now guarantees an org is never left without an Owner, the old per-boot "does the oldest org have an owner" re-check was a stale recovery path, not a real one worth preserving under the new design.
- **Azure AI Search's index versioned (`-v2`), not migrated in place** — the service doesn't support adding a field to an existing index; a name bump lets the existing idempotent create-logic do the work without new migration tooling.

---

## Files Changed

**New:** `server/alembic/versions/c3f8a1b2d5e9_enterprise_surface_isolation.py`, `server/app/services/organization_lifecycle_service.py`, `server/app/schemas/organization_lifecycle.py`, `server/app/routers/organization_lifecycle.py`, `server/tests/unit/test_organization_lifecycle.py`, `server/tests/unit/test_organization_bootstrap.py`, `server/tests/unit/test_evidence_chain_verification.py`, `server/tests/unit/test_second_organization_onboarding.py`, `src/app/live/organizationId.ts`, `src/app/organization/PlatformOrganizationsPage.tsx`.

**Modified (backend):** `server/app/db/models.py`, `server/app/main.py`, `server/app/config.py`, `server/app/routers/{agents,ai_authority_builder,ai_policy_builder,auth,organization,runtime_policy_lifecycle}.py`, `server/app/services/{agent_service,ai_authority_builder_service,ai_policy_builder_service,authority_intelligence_service,evidence_service,organization_service}.py`, `server/tests/unit/{test_organization_isolation,test_authority_intelligence_service}.py`.

**Modified (SDK/scripts):** `sdk-python/payreality/{__init__,agent,client,configuration}.py`, `sdk-python/pyproject.toml`, `sdk-python/tests/{test_agent_heartbeat,test_agent_register,test_client,test_configuration}.py`, `scripts/smoke_test.py`.

**Modified (frontend):** `src/app/live/apiClient.ts`, `src/app/live/components/OperatorKeyField.tsx`, `src/app/organization/{OrganizationSettingsPage,UsersPage,api,types}.tsx/ts`, `src/app/routes.tsx`.

**Modified (docs):** `SPECIFICATION/{09_AI_AUTHORITY_BUILDER,10_AI_POLICY_BUILDER,11_AGENT_ARCHITECTURE,13_EVIDENCE_ENGINE,14_SECURITY_MODEL,16_CURRENT_LIMITATIONS}.md`.

## Test Report

- **Server: 345/345 unit tests pass** (up from 322 at Milestone 2's close — 23 new: 12 Authority Builder isolation, 10 Agent Platform isolation, 12 AI Policy Builder isolation, 2 Evidence chain verification, 16 Organization Lifecycle, 2 organization bootstrap, 2 second-organization onboarding, 3 Blob/Search org-scoping — net after some are grouped differently across commits; exact per-commit counts are in each commit message). **14/14 real-OPA integration tests pass**, unaffected — confirmed by explicit rerun.
- **Python SDK: 68/68 unit tests pass** (4 files updated for the new `organization_id` field/version; 3 new tests).
- **Frontend: `npm run build` succeeds cleanly** (TypeScript compiles, new page correctly code-split) — run after every frontend-touching commit in this milestone, not just once at the end.
- **Not live-verified** (consistent with this entire engagement's environmental constraint — no live Postgres, no live Azure resources, no live OPA-backed production deployment reachable from this development environment): the Alembic migration (verified offline, both directions, via `alembic --sql`); Blob Storage/Azure AI Search org-scoping (no real Azure Storage account or Search service reachable); the frontend Organization Lifecycle UI (verified by clean TypeScript compilation only, not interactively browser-tested — no live backend reachable).

## Remaining Risks

1. **`AuthorityRelationship.cross_org_approved` is still dead schema.** Defined, never read. `resolve_relationship`/`activate_relationship` verify the corpus belongs to the caller but not that the two principals in a relationship belong to the same organization as each other. Genuine improvement, not implemented — beyond this milestone's literal "verify the target object belongs to the caller's organization" scope.
2. **Lifecycle events written by `runtime_policy_service.py`'s own CRUD functions still don't stamp `organization_id`** on the event row itself (a Milestone 2 disclosure, unchanged by this milestone — out of scope, Runtime Policies were explicitly not to be revisited).
3. **No delete/cleanup/retention path exists for Authority Intelligence documents**, in Blob Storage or Postgres, for any organization. Not a new leak this milestone introduced; a pre-existing gap surfaced while org-scoping the upload path.
4. **Blob Storage/Azure AI Search org-scoping is code-complete but not live-verified** against a real Azure account.
5. **The frontend Organization Lifecycle UI was not interactively browser-tested.** No live backend is reachable in this development environment. Verified by TypeScript compilation only.
6. **The mutating Authority Builder fix and the Agent Platform fix both rely on router-level dependencies, not service-layer signature changes** (deliberately, matching this codebase's existing `_authorized_corpus` convention for sub-resources) — a future caller of the underlying service functions that bypasses the router (there are none today) would not inherit the check automatically.
7. **`GET /v1/organizations` (Organization Discovery) has no pagination.** Fine at any realistic near-term tenant count; a known, small, undisclosed-until-now scaling limit, named here for completeness.

## Recommendation for Milestone 4

This milestone's own Scope Rules named what's explicitly excluded unless required to complete it: Azure migration, Render retirement, Website redesign, UI redesign, Enterprise Knowledge Resolution. None of that work was required here, so none of it was begun.

Per `PAYREALITY_ENTERPRISE_HARDENING_PLAN.md`'s naming and the roadmap sequencing already on record (`MILESTONE_2_MULTI_TENANT_FOUNDATION_SUMMARY.md`'s own recommendation), the next milestone is **Milestone 3 — Azure Completion & Cutover Readiness** in that roadmap's own numbering (distinct from this session's "Milestone 3 — Enterprise Surface Isolation," a naming collision worth flagging explicitly rather than letting it cause confusion later). `MULTI_TENANT_ARCHITECTURE_VERIFICATION.md`'s own Azure-readiness audit found the ten named Azure service areas (Postgres, Container Apps, Key Vault, Managed Identity, Monitoring, Backups/DR, Networking — Blob Storage and AI Search were the two exceptions, now closed by this milestone) unblocked by the multi-tenant work; that audit's other finding — a Terraform-level risk where the AI Foundry/AI Search modules are unconditional, with no per-environment toggle — remains open and should be fixed before any production `terraform apply`, independent of milestone sequencing.

Not proceeding into further work without explicit go-ahead, consistent with this milestone's own Scope Rules and the pattern established at the close of every prior milestone in this engagement.
