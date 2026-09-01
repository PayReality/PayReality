# Phase 6.1: Production Authorization Assurance

Closes three specific authorization-assurance gaps Phase 6's own hostile review exposed and honestly disclosed, rather than fixed. Not a new product surface -- see [REFERENCE_ENFORCEMENT_DEMONSTRATION.md](REFERENCE_ENFORCEMENT_DEMONSTRATION.md) for the loop this strengthens.

## Part A: Authorization freshness at Capability consumption

**Before this phase**: `verify_and_consume_capability` checked only the token's own signed claim -- signature, expiry, audience, exact parameters. It never re-checked whether the Agent, IntegrationIdentity, EnforcementBinding, or Organization a Capability depended on were still live. A Capability issued while everything was active remained fully consumable for the rest of its short TTL even after one of those was revoked in between -- proven, not assumed, by Phase 6's own test suite (`test_revoked_integration_identity_after_issuance_but_before_verification_fails_closed`, which used to assert exactly that gap).

**Now**: `capability_service._check_consumption_freshness` re-checks, immediately before the atomic consume, using the identical helpers issuance already used (`_check_agent_active`, `_check_integration_identity_active`, `_check_enforcement_binding_active`, and the new `_check_organization_active`):

- The originating Agent must still be `active`.
- The Organization (tenant) must still be `active` -- new to both issuance and consumption this phase; a real, small, previously-unchecked consistency gap.
- For an Adapter-mediated Capability, the IntegrationIdentity and EnforcementBinding must still be `active`.

**The freshness boundary, precisely**: this re-validates whether the *revocable identities and bindings* a Capability depends on are still eligible right now. It deliberately does **not** re-run Runtime Authority evaluation, re-check the original RuntimePolicy, or re-verify Trusted Enterprise Facts -- those determined whether the action was authorized under the authority state that existed at Decision time, a question the Capability's own immutable signed payload already answers. Turning verification into a second full policy evaluation would be a materially larger architecture this phase's own brief explicitly warned against building without proof it was necessary; no such proof exists, and the smaller check above is the one this phase actually needed.

**Ordering is the safety property, not an implementation detail.** The freshness check runs strictly before the atomic `consumed_at` UPDATE, in the same uncommitted transaction. A failed check raises without ever touching `consumed_at`:

- The token is **not** marked consumed on a freshness failure.
- Downstream execution is never invoked (the reference PEP's own `run()` never reaches `execute_downstream_operation()`).
- No new Decision is created, no replacement Capability is minted, no auto-renewal happens.

**State restoration -- defined explicitly, not left ambiguous**: because a freshness failure never consumes the token, a *subsequent* attempt re-checks current state fresh. If the underlying identity is restored (e.g. an Agent un-suspended) before the Capability expires, that next attempt may succeed. This is the deliberate design, not an oversight -- see `test_state_restoration_lets_a_subsequent_attempt_succeed`.

**Query cost**: up to 4 additional indexed primary-key lookups always (Decision, Intent, Agent, Organization), plus 2 more conditionally for an Adapter-mediated Capability (IntegrationIdentity, EnforcementBinding) -- `db.get(Model, id)`, never a table scan. Not separately benchmarked this phase (no load-testing harness exists in this repo to measure against); the claim above is a code-reading fact (count the `db.get`/`db.scalar` calls in `_check_consumption_freshness` and its helpers), not a measured latency number.

**Consumption concurrency proof**: `test_capability_tokens.py::test_replay_rejection` (SQLite, sequential) already proved the *shape* of single-use enforcement pre-Phase-6.1. `test_authorization_freshness_postgres.py::test_two_concurrent_consumption_attempts_for_the_same_capability_never_both_succeed` (new this phase) is the real-Postgres, genuinely-concurrent proof that adding the freshness check ahead of the atomic UPDATE did not reopen a double-spend window -- two threads, two separate connections, a `threading.Barrier` forcing simultaneous arrival, against the project's own `docker compose up -d postgres` service. **Disclosed honestly**: this environment's Docker daemon was not reachable when this phase ran (`docker compose up -d postgres` failed with "cannot connect to the Docker API"), so this test executed as an explicit, clean `pytest.skip` here, following the repo's own established convention for every other Postgres-gated test -- it was not run, and its result is not claimed as proof. The test exists, is committed, and will run for real the next time this suite executes somewhere Docker is reachable (CI, or a local environment with Docker Desktop running).

## Part B: Tenant Scoped Verification Identity

**Before this phase**: `POST /v1/capability-tokens/verify` was gated only on the platform-wide Operator Key, with no per-request tenant concept at all. Not itself a cross-tenant bypass (a Capability is looked up by its own unique token hash, so no request can ever be confused for another tenant's), but a real, avoidable trust-boundary gap: nothing distinguished "a verifier scoped to Organization A" from "an unrestricted global verification actor."

**Now**: the endpoint is gated exactly like every other org-scoped Capability endpoint -- `require_permission(Permission.CAPABILITY_VERIFY)` (new, narrow permission, granted to Governance Administrator alongside the existing `CAPABILITY_ISSUE`) plus `get_current_organization`. No new identity concept was introduced: an organisation creates a real, tenant-bound `ApiKey` (the existing, already-hashed, already-revocable credential model) with a role holding `Permission.CAPABILITY_VERIFY`, and hands it to its own reference PEP. The resolved organisation is always passed through as `expected_organization_id`; `domain/capability/token.py::verify_capability_token` checks it against the Capability's own signed `organization_id` claim, before even the audience check, and rejects a mismatch with a distinct `CapabilityTenantMismatchError` (`403 capability_tenant_mismatch`).

**The Operator Key still works** -- preserved deliberately, not silently broken, exactly as Milestone 2 already left it: it must name its target organisation explicitly via `X-PayReality-Organization-Id`, and is checked against the token's tenant the same as any `ApiKey`, not exempt from the boundary.

`scripts/reference_enforcement_adapter.py` and the Python SDK's `Agent.verify_capability()` were both updated to prefer a real, tenant-scoped credential (`PAYREALITY_API_KEY` / `bearer_token`) over the Operator Key, reusing the SDK's own existing `admin_auth=True` preference order rather than a second, hand-rolled auth path.

**Cross-tenant concurrency proof**: `test_tenant_scoped_verification.py::test_tenant_a_verifier_cannot_consume_tenant_bs_capability` (SQLite, sequential) already proved the wrong tenant is rejected. `test_authorization_freshness_postgres.py::test_wrong_tenant_verifier_never_wins_a_real_race_against_the_correct_tenant` (new this phase) races the correct tenant's verifier against the wrong tenant's verifier for the *same* token from two separate Postgres connections at the same instant, and asserts the wrong tenant never succeeds and never consumes the token regardless of database scheduling order. Same honest disclosure as above: this test is real and committed but did not execute in this environment (Docker unreachable) -- it ran as an explicit skip, not as proof.

## Part C: Canonical Action Vocabulary Precision

**Before this phase**: Phase 6's reference scenario mapped `ChangeSupplierBankDetails` to `vendor_payment` -- the closest value the closed action vocabulary had, and the only option that milestone's own brief allowed ("do not invent uncontrolled semantics purely for the demo"). Changing a supplier's payout routing and actually paying a vendor are materially different business authorities.

**Now**: `supplier_bank_details_change` is a real, canonical action (`compiler_v2.GENERALIZATION_PROOF_SCOPES`, alongside the existing `disable_user`). `Scope.action` matching is, and always was, exact-string (no wildcard or inheritance mechanism exists anywhere in this codebase), so the two authorities were already structurally isolated the moment they became distinct strings -- verified with a real, deployed policy in `test_action_vocabulary_precision.py`: an organisation authorizing `vendor_payment` does not authorize `supplier_bank_details_change`, and a new action with no policy of its own fails closed to `HUMAN_REVIEW`, never silently ALLOW.

**A real, adjacent gap this surfaced and closed**: `compile_bundle`'s actual runtime default already validated against the generic vocabulary (`GENERIC_VOCABULARY`), but four human/AI-facing surfaces -- Policy Studio's own action dropdown (`GET /v1/runtime-policies/vocabulary`), the AI Authority Builder and AI Policy Builder extraction prompts, and Draft-with-AI's own validation -- all still checked against the narrower, financial-only vocabulary. `disable_user`, and now `supplier_bank_details_change`, could compile and deploy via a direct API call but never be authored through the product's own surfaces. All four now use `GENERIC_VOCABULARY`.

**Phase 6's demo migrated**: `server/tests/integration/test_reference_enforcement_demonstration.py`'s own `ACTION` constant, the demo's SAP Action Mapping fixture (`fixtures/integrations.ts`, `amount_path`/`currency_path` also set to `null` -- the operation itself moves no money), and the demo's own `DECISION_HERO_ADAPTER_REVIEW` decision fixture (a new, precise `POLICY_SUPPLIER_BANK_DETAILS_REVIEW` policy fixture replaces the old `vendor_payment`-scoped ones it incorrectly cited). No historical data was rewritten -- all of this is fixture/seed data regenerated on demo load, never a persisted production record.

## Hostile review

A deliberate pass against this phase's own brief's attack list, each mapped to the specific test that exercises it (not inferred from code presence alone):

| Attempt | Result | Proof |
|---|---|---|
| Consume after Agent revoked (Agent-direct) | Fails closed, token not consumed | `test_authorization_freshness.py::test_agent_direct_consumption_fails_closed_after_agent_revoked` |
| Consume after Agent revoked (Adapter-mediated) | Fails closed, token not consumed | `test_authorization_freshness.py::test_adapter_mediated_consumption_fails_closed_after_agent_revoked` |
| Consume after IntegrationIdentity revoked | Fails closed, token not consumed | `test_authorization_freshness.py::test_consumption_fails_closed_after_integration_identity_revoked` |
| Consume after EnforcementBinding revoked | Fails closed, token not consumed | `test_authorization_freshness.py::test_consumption_fails_closed_after_enforcement_binding_retired` |
| Consume after tenant (Organization) deactivated | Fails closed, token not consumed | `test_authorization_freshness.py::test_consumption_fails_closed_after_tenant_deactivated` |
| Cross-tenant verifier consumes another org's Capability | Rejected, `CapabilityTenantMismatchError`, token not consumed | `test_tenant_scoped_verification.py::test_tenant_a_verifier_cannot_consume_tenant_bs_capability` |
| Operator Key targeting the wrong organisation | Rejected, same tenant-mismatch path as an `ApiKey` | `test_tenant_scoped_verification.py::test_operator_key_targeting_the_wrong_organization_also_fails_the_tenant_check` |
| Revoked `ApiKey` used to verify | Rejected at auth (401), before reaching Capability logic at all | `test_tenant_scoped_verification.py::test_revoked_api_key_fails_both_checks` |
| Wrong-role `ApiKey` (lacks `CAPABILITY_VERIFY`) | Rejected at permission check (403) | `test_tenant_scoped_verification.py::test_api_key_with_a_role_lacking_the_permission_is_denied` |
| Wrong audience / environment / binding / principal / action / resource | Each still independently rejected, unregressed by this phase's changes | `test_tenant_scoped_verification.py` (audience/environment cases), pre-existing `test_capability_tokens.py` cases |
| Replay a consumed Capability | Rejected, `CapabilityTokenAlreadyConsumedError` | `test_capability_tokens.py::test_replay_rejection`; real-Postgres race version above |
| Duplicate issuance for the same Decision | Rejected (Phase 5.1 invariant, reconfirmed unregressed) | `test_authorization_freshness.py` reconfirms; `test_capability_issuance_idempotency*.py` |
| Coarse `vendor_payment` authority attempting `supplier_bank_details_change` | `decision.outcome != "ALLOW"` -- the coarser authority does not silently cover the precise one | `test_action_vocabulary_precision.py::test_vendor_payment_authority_does_not_silently_authorize_supplier_bank_details_change` |
| Submit an unknown canonical action | Rejected, `ContractValidationError` (Action Mapping) / AI drafting rejects a hallucinated action | `test_action_vocabulary_precision.py` (both cases) |
| Race two consumption attempts for the same token | Real-Postgres proof: exactly one wins, database-enforced | `test_authorization_freshness_postgres.py` (skipped in this environment, see above) |
| Race a revocation against consumption (freshness-check-to-atomic-UPDATE window) | Not additionally locked -- disclosed, accepted, narrow TOCTOU window; not solved this phase (see Part A, "smallest defensible change") | Design decision, not a test claim -- documented, not silently left undocumented |
| State restoration after a freshness failure | A later attempt, after the revoked identity is restored, may succeed within the TTL -- deliberate, not a bug | `test_authorization_freshness.py::test_state_restoration_lets_a_subsequent_attempt_succeed` |

## What did not change

- `VERIFIED` / `REGISTERED_EXTERNAL_PEP` enforcement assurance: still unimplemented. A tenant-scoped verification credential does not make a customer's external PEP non-bypassable, and this phase does not claim otherwise.
- The Operator Key: not deprecated, not removed -- narrowed to the same "must name its target organisation, still tenant-checked" model Milestone 2 already established, extended here to the verify endpoint specifically.
- No migration: `Organization.status`, `ApiKey`, and `Permission` were all pre-existing; adding one new `Permission` enum member and one new `GENERALIZATION_PROOF_SCOPES` entry required no schema change.
- Evidence and Authorization Receipt semantics: unchanged. No historical Decision was rewritten; the freshness check is a live, point-in-time validation, never retroactive.
