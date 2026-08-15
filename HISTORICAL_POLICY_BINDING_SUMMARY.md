# Historical Policy Binding, Summary

Synthesizes `HISTORICAL_POLICY_BINDING_IMPLEMENTATION.md`, `HISTORICAL_POLICY_BINDING_TEST_REPORT.md`, and `HISTORICAL_POLICY_BINDING_PRODUCTION_VERIFICATION.md`.

## What this milestone closed

The Phase 2 Readiness Audit named a real gap: nothing persisted which exact Runtime Policy bundle a historical decision was evaluated against. Re-verifying against the current codebase from scratch (not assuming the prior audit was right) found the gap was real but narrower than described: both halves most people would assume are linked, which bundle was active (`Decision.policy_id`, an immutable, retired-not-deleted `Policy` row), and what each policy's content was at any past version (`RuntimePolicyRecord`, immutable per version), were already durably persisted. Only the join between them, the manifest naming which `RuntimePolicyRecord`s a given bundle actually contained, was missing. It was already computed in memory at deploy time and discarded once pushed to OPA.

The fix is exactly that size: one nullable JSONB column (`Policy.bundle_manifest`), one line in `deploy_policy` to stop discarding a value it already computes, and one new, org-scoped, read-only endpoint (`GET /v1/decisions/{id}/policy-binding`). No new persistence architecture, no second policy engine, no duplicated policy content, no change to `GetDecisionResponse` or the existing signing/evidence flow.

## Verification

Six new integration tests, all real (real service functions, a real ephemeral OPA server, a real relational database via a disclosed SQLite compatibility layer since no Postgres/Docker was available in this environment), prove: historical stability (a decision keeps resolving to its original bundle after a later version activates), bundle stability (the manifest survives and stays correct across a redeploy), tenant isolation (the new endpoint 404s on cross-org access), lifecycle survival (retirement doesn't destroy reconstruction), evidence consistency (Evidence's own policy fields match the bound bundle exactly), and, most substantively, that the binding gives the existing Simulator explainer everything it needs to reconstruct a decision's exact original policy state even after two subsequent redeploys, using the real $100,000 threshold, not whatever's active now.

Full backend suite: 379 passed (373 existing, unchanged, plus these 6). Frontend build unaffected; no frontend files were touched this round.

Deployed through the existing Azure process: new image built and pushed, Terraform plan reviewed (exactly one change, the image tag) and applied, new container revision reached `Healthy` at 100% traffic. The migration's success is confirmed by necessary implication of that health state (`entrypoint.sh` runs `alembic upgrade head` with `set -e` before `uvicorn` ever starts; a failed migration would have prevented the container from ever becoming healthy). The new endpoint's registration, response schema, and authorization gate were confirmed live directly against the real production `/openapi.json` and a real unauthenticated request (correctly rejected, `401`).

No test credentials or browser tool were available in this session, the same disclosed limitation as every prior verification round in this engagement. A live production decision's binding was not created and inspected end-to-end this session; the identical, unmodified code path that would do so was verified thoroughly against real infrastructure in the test suite instead. This distinction is stated plainly, not blurred.

## Completion gate

**HISTORICAL POLICY BINDING: PASS.**

Every requirement was met with real evidence: the data model was re-audited rather than assumed, the binding was defined and implemented at the smallest safe scope, historical integrity was proven (not just argued) across six real regression scenarios including tenant isolation and lifecycle survival, the Decision API exposure was deliberately scoped to only what's traceable to the exact historical decision, Evidence's independent sufficiency was verified, the explainability prerequisite was proven concretely rather than left as a claim, and the change was deployed through the real Azure process with live confirmation of everything that's verifiable without a credential this session doesn't have.

## Is the platform ready for Phase 2B (live per-condition explainability)?

**Architecturally, yes,** for the first time. The one thing that was genuinely blocking it, not knowing which policy content a past decision was actually evaluated against, is closed and proven sufficient, including under the adversarial condition (two subsequent redeploys) most likely to have exposed a gap.

**Not yet scoped or approved to build.** What Phase 2B would still require: turning the test file's `intent`/`context` reconstruction (currently real, but written as test glue) into a real, callable function; a decision on how that surfaces in the Decision Center's UI (the spec's own Phase 1 already reserved the space for it); and a decision on how to handle the pre-existing-column limitation (no historical bundle from before `Policy.bundle_manifest` existed can ever be backfilled, disclosed in the implementation doc, not something this milestone can retroactively fix).

Per instruction, no Phase 2B work and no Enterprise Knowledge work were started. Awaiting explicit approval before either begins.
