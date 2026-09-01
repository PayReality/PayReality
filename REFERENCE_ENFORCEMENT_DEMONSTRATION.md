# Reference End-to-End Enforcement Demonstration (Trusted Integration Phase 6)

## What this proves

That the complete, real authority-to-execution loop PayReality already implements actually works, end to end, against real code -- not a slide, not a mock, not a UI simulation:

1. An Agent attempts a real business operation (this milestone's reference scenario: a supplier bank-details change).
2. A Trusted Adapter -- software the customer controls, not PayReality -- observes the actual attempted external operation and reports it through an approved Action Mapping.
3. That report becomes a canonical PayReality `Intent`.
4. Runtime Authority evaluates it against real organizational policy and returns `HUMAN_REVIEW`.
5. An authorized reviewer (holding the real `Permission.DECISIONS_RESOLVE` RBAC permission) approves it. **The original Decision is never rewritten** -- it still reads `HUMAN_REVIEW` forever; the approval is a separate, linked `DecisionResolution` record.
6. A Capability Authorization is issued from that approval (`issue_capability_for_reviewed_decision`), bound to the exact Agent, action, resource, environment, Runtime Connection, Action Mapping version, and `external_operation_id` the original attempt carried.
7. A reference Policy Enforcement Point verifies and consumes that Capability against PayReality's own real, authoritative endpoint, then -- only after successful consumption -- invokes a reference stand-in for the downstream business system.
8. Replaying the same, now-consumed Capability is refused. Requesting a second Capability for the same Decision is refused. Neither is simulated; both go through the real `verify_and_consume_capability`/`issue_capability_for_reviewed_decision` code paths.

## What this does not prove

- That PayReality itself performed the supplier bank-details change. It did not, and cannot: **PayReality is a Policy Decision Point (PDP), not the customer's production, non-bypassable Policy Enforcement Point (PEP).** The reference PEP (`scripts/reference_enforcement_adapter.py`) is exactly what its own name says -- a reference, proof-of-mechanism implementation, not a production enforcement deployment. A real customer PEP is the customer's own responsibility to build and operate.
- That no other path to the same downstream action exists. If an enterprise system can be reached through some route that never calls the reference PEP (or any real PEP) at all, nothing here detects or prevents that. This is a real, structural limit of the architecture, not a gap this milestone closes or claims to close.
- That the downstream reference business system's own "execution" in this demonstration is cryptographically tied to anything. `execute_downstream_operation()` in the reference script is a deliberately trivial stand-in (it prints and returns `True`) -- it is exactly as trustworthy as whatever process runs it, and its own success/failure is reported as a **separate fact** from Capability consumption, never conflated with it.
- That Capability consumption is proof the downstream business action completed. Consumption means an execution *permission* was used exactly once. Whether the enterprise system that received it actually finished the job is a different, later, separately-observed event -- if observed at all.
- That using this reference PEP makes a customer's integration "`VERIFIED`" in PayReality's own enforcement-assurance vocabulary. It does not. Only `ADVISORY` and `CAPABILITY_REQUIRED` are implemented and settable today (`EnforcementBinding.enforcement_assurance`'s own `CHECK` constraint); `VERIFIED`/`REGISTERED_EXTERNAL_PEP` remain unimplemented, and no code path -- including running this demonstration -- can set them.

## The PDP/PEP boundary, concretely

| Layer | Component | What it does | What it does NOT do |
|---|---|---|---|
| Observation | Trusted Adapter (`IntegrationIdentity`) | Customer-controlled; attests it observed a real external operation | Does not itself decide authority |
| Decision | PayReality Runtime Authority | Evaluates Actor/Principal, Action, Resource, Context, Authority, RuntimePolicy, Trusted Enterprise Facts; returns `ALLOW`/`DENY`/`HUMAN_REVIEW`; signs Evidence; can issue a Capability for an `ALLOW` or an approved `HUMAN_REVIEW` | Does not execute, block, or gate anything downstream |
| Enforcement | Reference PEP (`scripts/reference_enforcement_adapter.py`) | Customer-operated (a *reference* implementation here); verifies and consumes a Capability online, then may invoke a downstream operation | Is not PayReality; is not automatically present on every possible path to the protected action |

## The two required negative demonstrations

Both are exercised through the real code paths, not simulated in a UI or a mock:

- **Capability replay**: `test_replaying_a_consumed_capability_is_refused_and_never_reaches_downstream_execution` (`server/tests/integration/test_reference_enforcement_demonstration.py`) issues a real Capability, runs the actual `reference_enforcement_adapter.run()` function once (succeeds, consumes it, invokes the reference downstream stub), then runs it again with the identical token. The second call is refused (`capability_token_already_consumed`), and asserts `execute_downstream_operation()` was called exactly once across both attempts -- never for the replay.
- **Duplicate issuance**: `test_requesting_a_second_capability_after_issuance_fails_no_replacement_minted` requests a second Capability for the same, already-issued Decision. It is refused (`CapabilityAlreadyIssuedError`), and the test asserts exactly one `CapabilityToken` row exists for that Decision afterward -- the Phase 5.1 invariant, unregressed.

## How to run the demonstration

**The primary, fully-automated way** (real SQLite, real ephemeral OPA, real Ed25519 signing, real database constraints -- nothing here is mocked away):

```
cd server
.venv/Scripts/python.exe -m pytest -q tests/integration/test_reference_enforcement_demonstration.py -v
```

Every step above (1-8) is a real assertion in this file. Read the test names and docstrings in order; they narrate the scenario as they prove it.

**The reference PEP script standalone**, against a real running backend (local `uvicorn app.main:app`, or any environment where you hold the Operator Key), once you already have a valid Capability token (obtained via `POST /v1/decisions/{id}/capability-token/from-review`, or the SDK's `agent.request_capability_from_review()`):

```
PAYREALITY_API_URL=http://localhost:8000 \
PAYREALITY_OPERATOR_KEY=<ADMIN_API_KEY> \
python scripts/reference_enforcement_adapter.py \
    --audience reference-pep \
    --token <the capability token> \
    --action vendor_payment \
    --resource supplier:SUPPLIER_482 \
    --environment demo
```

**To reproduce the negative replay test manually**: run the exact same command a second time, unchanged. The first run prints `CAPABILITY VERIFIED AND CONSUMED` followed by a separate `DOWNSTREAM EXECUTION: executed successfully` line; the second prints `CAPABILITY REJECTED: capability_token_already_consumed` and `DOWNSTREAM EXECUTION: not attempted` -- the reference business system function is never called for it. To reproduce the duplicate-issuance negative test, call `POST /v1/decisions/{id}/capability-token/from-review` again for the same Decision; it returns `409 capability_already_consumed_for_decision` (or `capability_already_issued`, depending on whether the first Capability has been consumed yet).

## Reference architecture

```
Agent attempts operation
        |
        v
Trusted Adapter (customer-controlled) observes it
        |
        v  approved Action Mapping version
canonical Intent  ---------------------------->  PayReality Runtime Authority
                                                          |
                                                    HUMAN_REVIEW
                                                          |
                                          reviewer approves (DecisionResolution)
                                          [original Decision remains HUMAN_REVIEW]
                                                          |
                                          issue_capability_for_reviewed_decision
                                                          |
                                                          v
                                              signed, short-lived, single-use
                                                    Capability token
                                                          |
                                                          v
                                        Reference PEP: verify_and_consume (online)
                                             |                          |
                                        rejected                    consumed
                                    (no downstream call)                |
                                                                         v
                                                    reference downstream business
                                                    system stand-in "executes"
                                                    (a separate, distinct fact)
```

## Business operation idempotency, composed with Capability idempotency

Two independent invariants, both intact and both exercised together in `test_transport_retry_after_approval_does_not_create_a_new_decision_or_bypass_issuance`:

- **Decision idempotency** (Phase 3): the same `external_operation_id` with the same authority-relevant fields always resolves to the *same* Decision, even retried after that Decision has already been approved and had a Capability issued from it.
- **Capability idempotency** (Phase 5.1): that same Decision may still have at most one Capability, ever -- a transport-level retry of the business operation cannot be used to sneak past the one-Capability-per-Decision guarantee by re-triggering issuance.

## Evidence and Authorization Receipt

Nothing here required a new representation. The existing Receipt (`AuthorizationReceiptResponse`) and Decision Detail surfaces already render `human_review` (the resolution) and `capability` (issuance/consumption state) generically, regardless of which runtime path or which issuance function produced them -- confirmed directly by reading `authorization_receipt_service.py` and the frontend `AuthorizationReceiptPage.tsx`/`DecisionDetailPage.tsx`, and by this milestone's own `test_full_reference_scenario_authority_to_execution` asserting the original Decision still reads `HUMAN_REVIEW` after a real execution happened downstream of it. Historical Evidence is never rewritten; the review resolution and Capability state remain separate, linked, immutable records.

## Known, disclosed, structural limits (not regressions)

- A `DecisionResolution` (approval) is not itself gated on the originating Agent/IntegrationIdentity still being active -- the fail-closed check happens at Capability *issuance* time, not at approval time. This is a deliberate design point, not an oversight: the approval is a human's authorization signal; issuance is where authority is actually granted, and that is where the live re-check belongs.
- An Identity revoked *after* a Capability has already been issued, but *before* it is verified, does not retroactively invalidate that already-issued Capability -- verification checks the token's own signed claim (what was true at issuance), never live database state at verification time. This is Phase 5's own already-documented TOCTOU limit (`SPECIFICATION/14_SECURITY_MODEL.md` §14.8), unchanged and unregressed by this milestone. The Capability's own short TTL and single-use consumption bound this window.
- `POST /v1/capability-tokens/verify` is gated by the platform Operator Key only, with no per-request tenant scoping -- by design, matching every other Operator-Key-authenticated endpoint (`RBAC.md`: "Operator key bypass — deliberately permanent"). This is not a cross-tenant bypass in practice: a Capability token can only ever match the one `CapabilityToken` row whose hash it corresponds to, so there is no confusion vector between tenants' tokens, only a shared trust boundary on who may call the verify endpoint at all -- an already-known, pre-existing platform characteristic, not something this milestone introduces or could reasonably close without redesigning the Operator Key model itself (explicitly out of scope).
- Bypassing the reference PEP entirely -- reaching the real enterprise system through some other path that never calls it -- is not detectable or preventable by anything in this architecture. See "What this does not prove" above.

## Files

- `scripts/reference_enforcement_adapter.py` -- the reference PEP: verify-and-consume, then (only on success) invoke the reference downstream stand-in, as two separately-reported steps.
- `server/tests/integration/test_reference_enforcement_demonstration.py` -- the automated, real end-to-end proof.
- `server/tests/unit/test_reference_enforcement_adapter.py` -- unit tests of the script's own new control-flow logic (never invoke downstream execution when verification fails).
