# Part 16 — Current Limitations

**Supersedes/synthesizes:** the "known gaps" sections scattered across `SECURITY.md`, `ARCHITECTURE.md`, `PRODUCTION_CHECKLIST.md`, `VERSION_3_ROADMAP.md`. This part is the single, current, consolidated list — every item here was either directly confirmed against the code/production this session or flagged inline in the parts above; each entry links back to where it's discussed in depth.

This list exists for the same reason `PRODUCT.md` states as an operating principle: *"an enterprise buyer who catches a vendor overclaiming once stops trusting everything else that vendor says."* Nothing below is a hidden gap — each is either already named in an existing document or newly surfaced by this specification's direct verification pass.

## 16.1 Known and named, unresolved

| Gap | Detail | Where discussed |
|---|---|---|
| **Fake/simulated AI providers on the hosted demo** | The hosted Render deployment does not have `ANTHROPIC_API_KEY` configured for at least some environments, so the AI Authority Builder and AI Policy Builder fall back to their deterministic fake providers rather than real Claude-backed extraction. This is a configuration gap, not a code gap — both pipelines are built for the real provider and switch automatically once the key is set. | [09_AI_AUTHORITY_BUILDER.md](09_AI_AUTHORITY_BUILDER.md) §9.6, [10_AI_POLICY_BUILDER.md](10_AI_POLICY_BUILDER.md) §10.7 |
| **SDK's default onboarding flow needs the shared operator key** | `Agent._resolve_principal_id` passes `operator_auth=True` when creating a new Principal — meaning a fresh SDK integration onboarding a new Principal needs the shared, full-bypass operator key configured, not just a scoped RBAC API key. A production integration onboarding many principals routinely would be over-provisioned relative to what it actually needs to do. **Updated, Milestone 3:** that operator key now also requires an explicit `organization_id` (`Agent(api_key=..., organization_id=...)`, SDK `0.2.0`) — the underlying "over-provisioned relative to what it needs" gap is unchanged, but the SDK at least functions again against a real multi-tenant deployment (a separate, independent bug — `_resolve_principal_id`'s own `GET /v1/principals` call sending no credentials at all — was also found and fixed in the same pass). | [11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md) §11.8 |
| **Several live SDK/Deploy paths are unverified end-to-end** | The SDK's `register`/`authorize`/`heartbeat` flows are tested with the SDK's own local test suite (`sdk-python/tests/`), but a fully live, production-hosted round trip — a real external process using the SDK against the real hosted API, not this session's own direct API calls — has not been exercised as part of this specification's verification pass. | This part; see also [22_BUILD_FROM_SCRATCH.md](22_BUILD_FROM_SCRATCH.md) for what a rebuild should verify explicitly before calling the SDK production-ready |
| **MFA is schema-ready, not enforced** | `User.mfa_enabled` exists and Organisation Settings can toggle a requirement flag, but no actual TOTP/MFA challenge is implemented in the login flow. | [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md) §14.7 |
| **No account lockout after repeated failed logins** | `authenticate()` has no failure-count tracking; only rate limiting (IP-based, in-process) provides any friction against brute force. | [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md) §14.6 |
| **Rate limiting is single-instance** | In-process memory (`_request_log` dict); a second backend instance shares no state with the first, so the effective limit multiplies with instance count rather than staying fixed. | [02_SYSTEM_ARCHITECTURE.md](02_SYSTEM_ARCHITECTURE.md) §2.5 |
| **Field-vocabulary validation gap in Compiler V2** | `Vocabulary.is_valid_action` validates the *action* name against a known set; nothing validates that a condition's *field* is a real, meaningful field. A typo'd condition field compiles cleanly and simply never matches at runtime, silently — no compile-time error, no runtime error, just a policy that never does what its author intended. | [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) §7.11 |
| **No automatic promotion from AI Authority Builder discovery to the real Authority Model** | Discovered Principals/Resources/Relationships are informational; a human must manually create the equivalent real `Principal`/`Resource`/`AuthorityRelationship` rows. No code path connects a reviewed `AuthorityRelationship` (corpus-scoped, discovery) to a real, enforceable `AuthorityRelationship` (Phase 1, resolved-FK) automatically. | [08_RUNTIME_AUTHORITY.md](08_RUNTIME_AUTHORITY.md) §8.6, [09_AI_AUTHORITY_BUILDER.md](09_AI_AUTHORITY_BUILDER.md) §9.5 |
| ~~No frontend UI for the org hierarchy or delegation graph~~ **Resolved.** `BusinessUnit`/`Department`/`Team` now have a dedicated management UI (Organisation Settings → Organisation Structure, Phase 5 Release 1: `GET/POST/PATCH/DELETE /v1/business-units`, `/v1/departments`, `/v1/teams`). `AuthorityRelationship` resolution/activation already had a UI (Authority Builder's Corpus Review, Phase 4 Release 2). | [08_RUNTIME_AUTHORITY.md](08_RUNTIME_AUTHORITY.md) §8.6 |
| **No dedicated UI for chain verification** | `GET /v1/evidence/chain/verify` is a real, callable, unauthenticated endpoint, but `LiveEvidence.tsx` only surfaces per-record `/verify`, not a chain-level view. | [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md) §13.4 |
| **Agent Directory has no column-level sort** | Always `created_at desc`; no sort parameter on `GET /v1/agents`. | [11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md) §11.7 |
| **Bulk agent operations are N sequential transactions**, not a set-based update | Fine at Directory-driven batch sizes; not a substitute for a true bulk-migration tool at 10,000+-agent scale. | [11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md) §11.7 |
| **Domain-agnostic adapter model is partial** | The `Vocabulary` protocol seam exists and is used by Compiler V2, but only one vocabulary (`FinancialVocabulary`) has ever been built — the broader `DOMAIN_REFACTOR_PLAN.md` itemized plan for a second domain adapter has not been executed. | [02_SYSTEM_ARCHITECTURE.md](02_SYSTEM_ARCHITECTURE.md) §2.8, [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) §7.13 |
| **Single-tenant routing, multi-tenant-shaped schema** | **Resolved across essentially every remaining enterprise-facing surface, Milestone 3 (Enterprise Surface Isolation) — see §16.6.** Milestone 1 closed the gap for Evidence, organisation structure, Principals, and Authority Graph reads. Milestone 2 closed it for Runtime Policies/OPA. Milestone 3 closed it for the AI Authority Builder's mutating endpoints, the AI Policy Builder's single-document pipeline, the Agent Platform (list/detail/bulk actions), Evidence chain verification's crash, Blob Storage/Azure AI Search, and the Operator Key's frontend/SDK/smoke-test callers — and built the Organization Lifecycle (create/deactivate/archive/invite/accept) that had no API or UI of any kind before this milestone. Still genuinely open: `AuthorityRelationship.cross_org_approved` remains dead schema (defined, never read — see [09_AI_AUTHORITY_BUILDER.md](09_AI_AUTHORITY_BUILDER.md) §9.8); lifecycle events written by `runtime_policy_service.py`'s own CRUD functions still don't stamp `organization_id` on the event row itself; the new frontend organization UI was verified by TypeScript compilation only, not interactively browser-tested (no live backend reachable in this development environment); Blob Storage/Azure AI Search org-scoping was not verified against a real Azure account. | [09_AI_AUTHORITY_BUILDER.md](09_AI_AUTHORITY_BUILDER.md) §9.8, [10_AI_POLICY_BUILDER.md](10_AI_POLICY_BUILDER.md) §10.9, [11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md) §11.10, [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md) §13.8, [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md) §14.6 |
| **OPA runs embedded, loopback-only, in the same container as the API** | A cost-driven interim choice for the zero-cost pilot deployment, not the documented target topology (OPA as its own private network service once billing exists). | [02_SYSTEM_ARCHITECTURE.md](02_SYSTEM_ARCHITECTURE.md) §2.7 |

## 16.2 Corrections this specification made to existing documents' stated status

Every item below was found stated as "not yet built" or "proposed" in an existing top-level document, and confirmed via direct code/migration/production inspection to actually be shipped:

| Document | Stale claim | Actual status |
|---|---|---|
| `PHASE_0.md` | `Status: proposed` | **Implemented** — legacy pipeline fully retired, migration `805e62a44ac1` applied |
| `PHASE_1_AUTHORITY_MODEL.md` | `Status: proposed` | **Implemented** — migration `b58b031aeb21` applied, live-verified |
| `PHASE_2_RUNTIME_CONTEXT.md` | `Status: proposed`; also claimed "dot-path access into context already works for any field today" | **Implemented**, but that specific claim was **false until this session's fix** — see §16.3 |
| `PHASE_5_EVIDENCE.md` | `Status: proposed` | **Implemented** — migration `411edb414123` applied, live-verified |
| `README.md` / `PRODUCT.md` | "No human login/RBAC system yet"; "no key rotation"; "no evidence hash-chaining" | **All three shipped** — RBAC (Phase 10), signing-key registry, Evidence chaining (Phase 5) |
| `ARCHITECTURE.md` | Describes the legacy Authority/Mandate pipeline as the live decision path | **Superseded** — Compiler V2 is the sole OPA writer; the legacy pipeline's write endpoints are `410` |
| `POLICY_COMPILER_V2.md` | "Today's compiler doesn't enforce most conditions at all" | **False today** — every condition compiles to real, evaluated Rego ([07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md)) |

## 16.3 The one verified-in-production bug this session found and fixed

Worth restating here as the clearest illustration of why this specification insists on direct verification over trusting prior documentation: `PHASE_2_RUNTIME_CONTEXT.md` asserted, without having actually tested it, that a condition field like `context.authority.department` would resolve correctly against the real OPA input. It did not — it silently compiled to `input.intent.context.authority.department`, a path that never exists, so the condition simply never matched, with **no error anywhere**. This was only caught because a real signed Intent was pushed end-to-end against a live compiled policy and the expected `ALLOW` came back `DENY`. Fixed (`_resolve_base_and_field` in `rego_generator.py`), tested, and re-verified live (the same Intent flipped to `ALLOW` after the fix). See [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) §7.5 for the full mechanics.

## 16.4 What "current limitation" does not mean here

None of the items above are secretly broken production paths silently failing right now — every core enforcement path (§2.3's sequence) is live, tested, and verified. These are scope boundaries and unfinished edges, named the same way `PRODUCT.md` names them: honestly, and specifically, so a reader can decide what matters to their own use case rather than discovering a gap the hard way.

## 16.5 Milestone 2 (Multi-Tenant Foundation): what changed

Full detail, Architecture Decision Record, and test report in `MILESTONE_2_MULTI_TENANT_FOUNDATION_SUMMARY.md`. In summary:

- `RuntimePolicyRecord`, `Policy`, `SimulationScenario`, `RuntimePolicyLifecycleEvent`, and `PolicyActivationSchedule` all gained a nullable `organization_id` column (migration `a7d3e9f2c6b1`), backfilled to the platform's one bootstrapped Organisation for any pre-existing deployment.
- Every function in `runtime_policy_service.py`, `runtime_policy_lifecycle_service.py`, `runtime_policy_safety_checks.py`, and their two routers now takes/threads `organization_id`. `organization_id=None` remains its own valid, consistent scope (matching `evidence_service.verify_chain`'s existing convention), not an error.
- Each organization now compiles to, and deploys, its **own** OPA package (`payreality.authorization.org_<hex>`, via `opa_client.org_package_path`/`bundle_builder.retarget_package`) and its own `policies` table active row (`idx_policies_single_active_per_org`) — not a single package/row shared platform-wide. Proven against a real OPA server, not mocked, in `tests/integration/test_multi_tenant_opa_isolation.py`.
- `intent_service.submit_intent` now evaluates a real Intent against the acting Principal's own organization's active Policy and OPA package — the actual decision-time path, not just the authoring/CRUD surface.
- The Operator Key is now platform-admin-only: it must name an explicit target organization (`X-PayReality-Organization-Id`) on every org-scoped request; there is no default.
- Three genuine cross-tenant data leaks found and fixed while wiring the lifecycle service: `search_policies` and `get_dashboard` loaded every organization's `RuntimePolicyRecord` rows unconditionally, and `get_timeline`/`cancel_schedule` had no organization check at all (an IDOR).

## 16.6 Milestone 3 (Enterprise Surface Isolation): what changed

Full detail, files changed, test report, and remaining risks in `MILESTONE_3_ENTERPRISE_SURFACE_ISOLATION_SUMMARY.md`. This milestone's own repository audit (`MULTI_TENANT_ARCHITECTURE_VERIFICATION.md`) named the BLOCKERs it closed; in summary:

- **AI Authority Builder** ([09_AI_AUTHORITY_BUILDER.md](09_AI_AUTHORITY_BUILDER.md) §9.8): `resolve_principal`, `resolve_relationship`, `activate_relationship`, `answer_question`, `approve_graph`, and `get_principal_candidates` had no organization check of any kind — the worst finding of the pre-milestone audit, since `approve_graph` returned a full cross-org corpus snapshot and wrote a falsely-attributed audit record into the victim organization's own history. Three new router-level dependencies close this, mirroring `_authorized_corpus`'s existing convention.
- **AI Policy Builder** ([10_AI_POLICY_BUILDER.md](10_AI_POLICY_BUILDER.md) §10.9): the single-document pipeline had no organization concept at all — no column, no authentication on five read endpoints. `PolicyExtractionUpload` gained `organization_id`; `PolicyExtractionCandidate` resolves its own via exactly one of its two parents (upload or corpus).
- **Agent Platform** ([11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md) §11.10): `GET /v1/agents`/`GET /v1/agents/{id}` had no organization check (confirmed in the pre-milestone audit); auditing every endpoint per this milestone's own scope found the same gap on `create_agent` and every single-agent mutation/bulk action.
- **Evidence** ([13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md) §13.8): `GET /v1/evidence/chain/verify` — the one endpoint built for credential-free third-party verification — crashed (`TypeError`) for any organization with real data, a missing-argument bug with zero prior test coverage.
- **Organization Lifecycle** (new): create/deactivate/reactivate/archive an organization, and invite/accept/revoke membership — none of this existed in any form before this milestone; `Organization(...)` was constructed in exactly one place in the whole codebase, a startup-only bootstrap hook. `ensure_owner_bootstrapped` itself was fixed to stop resolving "the organisation" via "whichever is oldest," the last remaining assumption of that kind after Milestone 2 fixed the Operator Key's own instance of it.
- **Blob Storage / Azure AI Search**: both gained real `organization_id` scoping (blob path prefix; a new, versioned search index with a filterable field) — already self-documented as unsafe for multi-tenancy before this fix, not live-verified against a real Azure account after it.
- **SDK / smoke test**: `Configuration.organization_id` (SDK `0.1.0` → `0.2.0`, a real breaking change), attached alongside the Operator Key on every operator-authenticated call; `scripts/smoke_test.py` updated to match, plus two independent pre-existing header bugs fixed in the same pass.
- **Frontend**: `X-PayReality-Organization-Id` now travels alongside the Operator Key from `apiClient.ts`'s single request choke point; a new Platform Organizations page and an Invite Member flow are the first UI ever built for the Organization Lifecycle above. Verified by `npm run build` (clean TypeScript compile) only — not interactively browser-tested, no live backend reachable in this development environment.

None of the items above are secretly broken production paths silently failing right now — every core enforcement path (§2.3's sequence) is live, tested, and verified. These are scope boundaries and unfinished edges, named the same way `PRODUCT.md` names them: honestly, and specifically, so a reader can decide what matters to their own use case rather than discovering a gap the hard way.

## 16.7 Trusted Integration Architecture: current vs. future, named explicitly

Trusted Integration Phases 1–4 (see [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md)) are complete and live. Phase 5 (Capability/enforcement work for the Adapter-mediated path) has **not begun**. This split must never blur into a single "Trusted Integration is done" or "Trusted Integration is future" claim — both are simultaneously true, for different parts of it.

**LIVE TODAY:**

| Capability | Detail |
|---|---|
| Action Mapping lifecycle | draft → validated → approved → retired; multiple approved versions may coexist |
| Trusted Connection | registered, certificate-backed `IntegrationIdentity`, its own lifecycle |
| Runtime Connection | draft → active → retired `EnforcementBinding`, explicit Agent allow-list, single-active-per-scope enforced |
| Adapter-mediated runtime submission | `POST /v1/integration-runtime/intents`, full trust-chain verification, trusted context filtering |
| Operation idempotency | Phase 3, `external_operation_id` + canonical fingerprint, DB-enforced |
| Integration rejection vs. DENY distinction | pre-evaluation trust failures never produce a Decision or Evidence |
| Decision/Receipt integration provenance | `GetDecisionResponse.integration`, `AuthorizationReceiptResponse.integration`, Agent Detail's Trusted Connections section |
| Settings → Integrations UI | full guided journey: connect a System, create/validate/approve/retire Action Mappings, register a Trusted Connection, configure/activate/test a Runtime Connection |
| SDK support for the Adapter path | `payreality.integration.Adapter.attest()` (Python SDK 0.5.0) — real, shipped, but undocumented in `SDK_ARCHITECTURE.md`/`SDK_REFERENCE.md` until this pass |

**NOT YET LIVE / FUTURE (named, not implied):**

| Item | Status |
|---|---|
| Capability Authorization for Adapter-mediated decisions | Explicitly, deliberately suppressed (`CapabilityNotAvailableForIntegrationIntentError`) — not a gap in disguise, a named boundary. See [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.9 |
| A real Policy Enforcement Point for either runtime path | Does not exist for any customer today — see [ENTERPRISE_MESSAGING_GUIDE.md](../ENTERPRISE_MESSAGING_GUIDE.md) §6 |
| Vendor-specific Adapter connectors (SAP, Workday, etc.) | None exist; every Adapter is customer-built against the documented request shape |
| Automatic discovery of external operations/schemas | No discovery mechanism of any kind; every Action Mapping is hand-authored and human-approved |
| Mapping-drift monitoring | No automated detection if an external system's real operation shape diverges from an approved Action Mapping over time |
| Full self-host / dedicated-instance productization | Not packaged as a SKU; see [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.11 |

## 16.8 Documentation debt disclosed by this pass, not fixed

`06_APIS.md`'s auth (🔓/🔑/🛡️/👤) annotations for the ~84 endpoints that predate Trusted Integration were **not** re-verified against current code in this pass — several are already known to be stale relative to Milestones 10–12's security hardening (e.g. `GET /v1/decisions/{id}` and the Evidence list are annotated 🔓 here but now require authentication). This pass added accurate annotations only for the new Trusted Integration endpoints (§6.new in [06_APIS.md](06_APIS.md)). A full re-audit of the pre-existing table is real, disclosed, remaining work — do not treat its current auth column as current-state truth without re-checking against the router source.
