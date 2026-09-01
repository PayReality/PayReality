# Part 6 — APIs

**Supersedes/synthesizes:** `docs/API_SPECIFICATION.md` (endpoint list without current RBAC/lifecycle detail), `openapi.json` (the machine-readable, always-authoritative source — this table is a human-readable derivative of it). Extracted directly from every `@router.*` decorator in `server/app/routers/*.py`, ~84 endpoints across 11 routers.

## 6.1 Auth legend

| Symbol | Meaning |
|---|---|
| 🔓 | No auth — public read |
| 🔑 | Agent signature (`verify_agent_signature`) |
| ✍️ | Trusted Connection signature (`verify_integration_identity_signature`) — same shape as 🔑, different identity type, never RBAC |
| 🛡️`<Permission>` | `require_permission(Permission.<X>)` — operator key bypasses, else Role → Permission |
| 👤 | Session-only (`get_current_user`) |
| 🏢 | Resolves acting organisation (`get_current_organization`) |
| ⛔410 | Retired — always returns `410 Gone` |

## 6.2 `intents.py` — prefix `/v1`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/intents` | 🔑 | Submit a signed Intent → runs the full Decision Engine pipeline, returns the Decision |
| GET | `/decisions/{decision_id}` | 🔓 | Fetch one Decision |
| POST | `/decisions/{decision_id}/resolve` | 🛡️`DECISIONS_RESOLVE` | Resolve a `HUMAN_REVIEW` decision (approve/deny), appends a second Evidence record |

## 6.3 `evidence.py` — prefix `/v1/evidence`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/verification-key` | 🔓 | Current Ed25519 public key, for independent offline verification |
| GET | `/verification-keys` | 🔓 | Full signing-key history (active + retired) |
| GET | `/{evidence_id}` | 🔓 | Fetch one Evidence record |
| GET | `` (list) | 🔓 | List Evidence, optional `decision_id` filter |
| POST | `/{evidence_id}/verify` | 🔓 | Re-check one record's signature |
| GET | `/chain/verify` | 🔓 | Verify signature + `previous_hash` continuity for an org-scoped range |

## 6.4 `agents.py` — prefix `/v1/agents`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `` (create) | 🛡️`AGENT_REGISTER` | Register a new Agent + its first Certificate (`issued`, not yet active) |
| GET | `` (list) | 🔓 | Agent Directory: search/filter (status, environment, owner, principal, `q`)/paginate |
| GET | `/{agent_id}` | 🔓 | Agent detail |
| PATCH | `/{agent_id}` | 🛡️`AGENT_MANAGE` | Edit metadata (description, purpose, model, version, runtime, platform, tags, labels) |
| DELETE | `/{agent_id}` | 🛡️`AGENT_RETIRE` | Semantic delete = retire |
| GET | `/{agent_id}/certificates` | 🔓 | Certificate history for an agent |
| GET | `/{agent_id}/audit` | 🔓 | Audit event history |
| POST | `/{agent_id}/audit/{event_id}/verify` | 🔓 | Verify one audit event's signature |
| POST | `/{agent_id}/activate` | 🛡️`AGENT_ACTIVATE` | `registered`/`suspended` → `active` |
| POST | `/{agent_id}/suspend` | 🛡️`AGENT_SUSPEND` | `active` → `suspended` |
| POST | `/{agent_id}/retire` | 🛡️`AGENT_RETIRE` | → `retired` (terminal) |
| POST | `/{agent_id}/revoke` | 🛡️`AGENT_REVOKE` | → `revoked` (terminal, compromise) |
| POST | `/{agent_id}/rotate-certificate` | 🛡️`AGENT_ROTATE` | New Certificate; old → `rotated` |
| POST | `/{agent_id}/transfer-owner` | 🛡️`AGENT_MANAGE` | Change `owner`/`business_unit` |
| POST | `/{agent_id}/heartbeat` | 🔓 (agent self-reports) | Updates `last_seen_at`, version/sdk/runtime |
| POST | `/bulk/suspend`, `/bulk/activate`, `/bulk/retire`, `/bulk/rotate` | 🛡️ matching permission | Bulk lifecycle actions, per-agent independent success/failure |

## 6.5 `runtime_policies.py` — prefix `/v1/runtime-policies`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/vocabulary` | 🔓 | The condition-field vocabulary the manual editor offers |
| GET | `` (list) | 🔓 | List policies, optional `status` filter |
| GET | `/{policy_key}` | 🔓 | Latest version of a policy |
| GET | `/{policy_key}/versions` | 🔓 | All versions |
| GET | `/{policy_key}/versions/{version}` | 🔓 | One specific version |
| POST | `` (create) | 🛡️`RUNTIME_POLICY_CREATE` | New draft (version 1) |
| PUT | `/{policy_key}` | 🛡️`RUNTIME_POLICY_EDIT` | New version of an existing policy_key (never mutates a row) |
| POST | `/{policy_key}/submit-for-review` | 🛡️`RUNTIME_POLICY_EDIT` | `draft` → `pending_review` |
| POST | `/{policy_key}/approve` | 🛡️`AUTHORITY_REVIEW` | `pending_review` → `approved` |
| POST | `/{policy_key}/reject` | 🛡️`AUTHORITY_REVIEW` | `pending_review` → `rejected` |
| POST | `/{policy_key}/compile` | 🛡️`RUNTIME_POLICY_EDIT` | `approved` → `compiled` (runs `compiler_v2`) |
| POST | `/{policy_key}/dry-run` | 🔓 | Simulate a hypothetical Intent against a compiled-but-not-yet-active policy |
| POST | `/{policy_key}/deploy` | 🛡️`RUNTIME_POLICY_PUBLISH` | `compiled` → `active`; recompiles + pushes the **full** active set to OPA |
| GET | `/{policy_key}/diff` | 🔓 | Diff two versions (`from_version`/`to_version`) |

## 6.6 `policies.py` — legacy pipeline, prefix `/v1/policies`

| Method | Path | Auth | Status |
|---|---|---|---|
| GET | `/documents` | 🔓 | **Active** (read-only) |
| POST | `/documents` (upload) | — | ⛔410 |
| GET | `/authorities` | 🔓 | **Active** (read-only) |
| PATCH | `/authorities/{id}` (review) | 🛡️`AUTHORITY_REVIEW` | ⛔410 |
| POST | `/compile` | 🛡️`RUNTIME_POLICY_EDIT` | ⛔410 |
| POST | `/{policy_id}/activate` | 🛡️`RUNTIME_POLICY_PUBLISH` | ⛔410 |
| GET | `` (list) | 🔓 | **Active** (read-only) |

See [17_LEGACY_COMPONENTS.md](17_LEGACY_COMPONENTS.md) for the full retirement record.

## 6.7 `ai_policy_builder.py` — prefix `/v1/ai-policy-builder`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/status` | 🔓 | Whether a real or fake extraction provider is configured |
| POST | `/upload` | — | Upload a single document, triggers extraction |
| GET | `/uploads` | 🔓 | List uploads |
| GET | `/uploads/{id}` | 🔓 | One upload's status |
| GET | `/uploads/{id}/candidates` | 🔓 | Candidates extracted from one upload |
| GET | `/candidates` | 🔓 | List candidates, filterable |
| GET | `/candidates/{id}` | 🔓 | One candidate |
| PUT | `/candidates/{id}` | 🛡️`AUTHORITY_REVIEW` | Edit a candidate before promoting |
| POST | `/candidates/{id}/dismiss` | 🛡️`AUTHORITY_REVIEW` | Reject a candidate |
| POST | `/candidates/{id}/promote` | 🛡️`AUTHORITY_REVIEW` | Promote to a real draft `RuntimePolicy` |

## 6.8 `ai_authority_builder.py` — prefix `/v1/ai-authority-builder`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/status` | 🔓 | Provider status |
| POST | `/corpora` | 🛡️`AUTHORITY_REVIEW` | Upload multiple documents as one corpus, triggers analysis |
| GET | `/corpora` | 🔓 | List corpora |
| GET | `/corpora/{id}` | 🔓 | One corpus |
| GET | `/corpora/{id}/summary` | 🔓 | Graph summary (counts of principals/resources/operations/relationships/conflicts/gaps) |
| GET | `/corpora/{id}/principals` \| `/resources` \| `/operations` \| `/relationships` \| `/conflicts` \| `/gaps` \| `/questions` | 🔓 | Each discovered entity type, individually listable |
| POST | `/questions/{id}/answer` | 🛡️`AUTHORITY_REVIEW` | Answer a clarification question |

## 6.9 `auth.py` — prefix `/v1/auth`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/login` | 🔓 | Email/password → session token |
| POST | `/logout` | 👤 | Revoke the current session |
| GET | `/me` | 👤 | Current user + their permission list |
| POST | `/setup-owner` | 🔓 (first-run only) | Bootstrap the Owner account when none exists |

## 6.10 `organization.py` — prefix `/v1/organization`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/settings` | 🏢 | Organisation Settings |
| PATCH | `/settings` | 🛡️`ORGANISATION_MANAGE` | Edit settings |
| GET | `/integrations` | 🔓 | Integration status (AI providers, etc.) |
| GET | `/health` | 🔓 | Basic health/status read |
| GET | `/evidence/export` | 🔓 | Bulk Evidence export |
| GET | `/api-keys` | 🛡️`API_KEYS_MANAGE` (view) | List API keys (never returns the raw key) |
| POST | `/api-keys` | 🛡️`API_KEYS_MANAGE` | Issue a new API key (raw key returned once, at creation only) |
| DELETE | `/api-keys/{id}` | 🛡️`API_KEYS_MANAGE` | Revoke a key |

## 6.11 `users.py` — prefix `/v1/users`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `` (list) | 🛡️`USERS_MANAGE` | List org users |
| POST | `` (create) | 🛡️`USERS_MANAGE` | Invite/create a user |
| PATCH | `/{user_id}/role` | 🛡️`USERS_MANAGE` | Change role |
| PATCH | `/{user_id}/status` | 🛡️`USERS_MANAGE` | Enable/disable |

## 6.12 `principals.py` — prefix `/v1/principals`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `` (create) | 🔓 | Create a Principal |
| GET | `` (list) | 🔓 | List Principals |

## 6.13 API design conventions

- **Every mutating endpoint's auth is a `Permission`, never a `Role` check** — the router layer never asks "is this an Owner"; it asks `require_permission(Permission.X)`, and `has_permission` resolves that against whichever role the caller's token maps to. This is Phase 10's central invariant, enforced structurally rather than by convention (see [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md)).
- **Reads were open by default when this table was first written** — this reflected the single-tenant-per-deployment scope of that time, not a permanent design choice. **Stale as of Milestones 2, 3, 10, and 11** (multi-tenancy, then RBAC, then a series of confirmed-and-fixed unauthenticated read endpoints — see [16_CURRENT_LIMITATIONS.md](16_CURRENT_LIMITATIONS.md) §16.8): a number of reads in the table above are annotated 🔓 from that earlier era and are almost certainly now permission-gated. Do not treat the 🔓/🔑/🛡️/👤 column above as current-state truth without re-checking the router source for anything not added in Trusted Integration (§6.14 onward), which was verified fresh for this pass.
- **`POST .../dry-run` and `GET .../diff` are the two genuinely side-effect-free "what if" endpoints** in the whole API — both are deliberately unauthenticated reads-with-simulation, not because the data is unimportant but because they mutate nothing.
- **Every lifecycle-transition endpoint takes an optional `reason`/`actor`** and returns the full updated resource, never a bare `204` — this is what lets the frontend re-render the Agent Detail page's lifecycle timeline immediately from the response, without a second round-trip.
- **`compile` and `deploy` are separate steps everywhere they appear** (both the legacy pipeline's now-410'd endpoints and the current `runtime_policies.py`) — compiling produces and hashes a bundle without making it live; deploying is the only action that ever writes to OPA. This separation is what makes `dry_run_policy` possible: it can simulate against a compiled-but-undeployed bundle.

## 6.14 `integration_contracts.py` — prefix `/v1/integrations`, Trusted Integration Phase 1 (Action Mapping)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `` (create System) | 🛡️`INTEGRATION_CONTRACT_MANAGE` | Register a new Integration (System) |
| GET | `` (list) | 🛡️`INTEGRATION_CONTRACT_MANAGE` | List Systems |
| GET | `/{integration_id}` | 🛡️`INTEGRATION_CONTRACT_MANAGE` | Fetch one System |
| POST | `/{integration_id}/contract-versions` (create mapping) | 🛡️`INTEGRATION_CONTRACT_MANAGE` | Draft a new Action Mapping version |
| GET | `/{integration_id}/contract-versions` (list) | 🛡️`INTEGRATION_CONTRACT_MANAGE` | List an Action Mapping's versions |
| GET | `/{integration_id}/contract-versions/{version_id}` | 🛡️`INTEGRATION_CONTRACT_MANAGE` | Fetch one Action Mapping version |
| PATCH | `/{integration_id}/contract-versions/{version_id}` (edit draft) | 🛡️`INTEGRATION_CONTRACT_MANAGE` | Edit a draft Action Mapping |
| POST | `/{integration_id}/contract-versions/{version_id}/validate` | 🛡️`INTEGRATION_CONTRACT_MANAGE` | draft → validated |
| POST | `/{integration_id}/contract-versions/{version_id}/approve` | 🛡️`INTEGRATION_CONTRACT_PUBLISH` | validated → approved (deliberately a separate, stronger permission than drafting) |
| POST | `/{integration_id}/contract-versions/{version_id}/retire` | 🛡️`INTEGRATION_CONTRACT_PUBLISH` | approved → retired |

## 6.15 `integration_identities.py` — prefix `/v1/integration-identities`, Trusted Integration Phase 2 (Trusted Connection)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `` (create) | 🛡️`INTEGRATION_IDENTITY_MANAGE` | Register a new Trusted Connection, issues its first certificate (one-time key reveal, never persisted server-side) |
| GET | `` (list) | 🛡️`INTEGRATION_IDENTITY_MANAGE` | List Trusted Connections |
| GET | `/{identity_id}` | 🛡️`INTEGRATION_IDENTITY_MANAGE` | Fetch one Trusted Connection |
| GET | `/{identity_id}/certificates` | 🛡️`INTEGRATION_IDENTITY_MANAGE` | Certificate history for one Trusted Connection |
| POST | `/{identity_id}/activate` | 🛡️`INTEGRATION_IDENTITY_MANAGE` | registered → active |
| POST | `/{identity_id}/suspend` | 🛡️`INTEGRATION_IDENTITY_MANAGE` | active → suspended (temporary; certificate untouched) |
| POST | `/{identity_id}/rotate` | 🛡️`INTEGRATION_IDENTITY_MANAGE` | Issues a new certificate, retires the old one |
| POST | `/{identity_id}/revoke` | 🛡️`INTEGRATION_IDENTITY_MANAGE` | Terminal |
| POST | `/{identity_id}/retire` | 🛡️`INTEGRATION_IDENTITY_MANAGE` | Terminal |

## 6.16 `enforcement_bindings.py` — prefix `/v1/enforcement-bindings`, Trusted Integration Phase 2 (Runtime Connection)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `` (create draft) | 🛡️`INTEGRATION_CONTRACT_MANAGE` | Draft a Runtime Connection (Trusted Connection + Action Mapping + environment) |
| GET | `` (list) | 🛡️`INTEGRATION_CONTRACT_MANAGE` | List Runtime Connections |
| GET | `/{binding_id}` | 🛡️`INTEGRATION_CONTRACT_MANAGE` | Fetch one Runtime Connection, including `allowed_agent_ids` |
| PATCH | `/{binding_id}` (edit draft) | 🛡️`INTEGRATION_CONTRACT_MANAGE` | Edit a draft Runtime Connection |
| GET | `/{binding_id}/allowed-agents` | 🛡️`INTEGRATION_CONTRACT_MANAGE` | List the explicit Agent allow-list |
| POST | `/{binding_id}/allowed-agents/{agent_id}` (add) | 🛡️`INTEGRATION_CONTRACT_MANAGE` | Add an Agent to the allow-list (draft only) |
| DELETE | `/{binding_id}/allowed-agents/{agent_id}` (remove) | 🛡️`INTEGRATION_CONTRACT_MANAGE` | Remove an Agent from the allow-list (draft only) |
| POST | `/{binding_id}/activate` | 🛡️`INTEGRATION_CONTRACT_PUBLISH` | draft → active — the actual deployment moment, deliberately gated by the stronger permission |
| POST | `/{binding_id}/retire` | 🛡️`INTEGRATION_CONTRACT_PUBLISH` | active → retired |
| POST | `/{binding_id}/enforcement-assurance` | 🛡️`INTEGRATION_CONTRACT_MANAGE` | Trusted Integration Phase 5: sets the customer-declared `enforcement_assurance` label (`ADVISORY` or `CAPABILITY_REQUIRED` only; any other value, including `VERIFIED`/`REGISTERED_EXTERNAL_PEP`, is rejected with `422 InvalidEnforcementAssuranceError`). Carries no authority meaning; not restricted to `draft` status. |

Note this reuses `INTEGRATION_CONTRACT_MANAGE`/`PUBLISH` rather than defining separate Runtime-Connection-specific permissions — a deliberate choice, not an oversight, since a Runtime Connection is inseparable from the Action Mapping it deploys.

## 6.17 `integration_runtime.py` — the Adapter-mediated runtime path, Trusted Integration Phase 2–3

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/integration-runtime/intents` | ✍️ Trusted Connection signature (`verify_integration_identity_signature`) | The Adapter-mediated equivalent of `POST /v1/intents` — see [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.4 for the full pre-evaluation check sequence |

Authenticated the same shape as an Agent's own Intent signature (an Ed25519 signature checked against the Trusted Connection's active certificate), never a `Permission`/RBAC check — a Trusted Adapter is not a human session.

## 6.18 Trusted Integration additions to existing routers

| Method | Path | Change |
|---|---|---|
| GET | `/v1/decisions/{decision_id}` | Response gained `integration: DecisionIntegrationSummary \| null` |
| GET | `/v1/decisions/{decision_id}/receipt` | Response gained `integration: ReceiptIntegrationSummary \| null` |

## 6.19 `capability_tokens.py`, prefix `/v1`, Capability Authorization

Predates Trusted Integration (issued for the agent-direct path from the start); extended by Trusted Integration Phase 5 to also cover the Adapter-mediated path. Not previously documented in this part; added here for completeness alongside the Phase 5 update.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/decisions/{decision_id}/capability-token` | 🛡️`CAPABILITY_ISSUE` (deliberately not `DECISIONS_VIEW`; viewing a decision and minting an executable capability for it are different privileges) | Issues a short-lived, signed, single-use Capability for a Decision whose `outcome` is `ALLOW`. `409 decision_not_allow` otherwise. For an Adapter-mediated Decision, also re-checks live that the Trusted Connection and Runtime Connection are still active: `409 integration_identity_not_active` / `409 enforcement_binding_not_active` if either has since been suspended, revoked, or retired. Phase 5.1: if the Decision already has a Capability, `409 capability_already_issued` (unexpired, unconsumed) / `409 capability_already_consumed_for_decision` / `409 capability_expired_not_renewed` — never a second usable Capability for the same Decision. |
| POST | `/decisions/{decision_id}/capability-token/from-review` | 🛡️`CAPABILITY_ISSUE` (Trusted Integration Phase 5.1: same permission as direct issuance, not a new one) | Issues a Capability for a `HUMAN_REVIEW` Decision an authorized reviewer has since approved, without mutating the original Decision (it still reports `outcome == "HUMAN_REVIEW"`). `409 decision_not_human_review` if the Decision isn't `HUMAN_REVIEW`; `409 review_not_resolved` if no resolution exists yet; `409 review_not_approved` if the resolution is `"denied"`. Shares every other precondition and error code with the endpoint above (live status re-checks, the three idempotency outcomes) via the same underlying issuance path. |
| POST | `/capability-tokens/verify` | Operator key only (`verify_operator_key` directly, not via `require_permission`; no symbol in §6.1's legend covers this shape. The reference enforcement adapter's own call, a trusted machine caller with no human RBAC session, not a human operator) | Verifies and atomically consumes a Capability. Optional `environment`/`enforcement_binding_id` request fields (Phase 5) pin an expectation against the token's own signed claim if supplied; omitted, they're skipped. `409 capability_binding_mismatch` on a mismatch, alongside the pre-existing `404`/`401`/`403`/`409` outcomes for not-found, expired, audience-mismatch, constraint-mismatch, invalid-signature, and already-consumed. |

Both are additive and `null` for every agent-direct decision — no existing caller's parsing breaks.
