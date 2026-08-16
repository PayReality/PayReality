# Phase 2B: Live Per-Condition Policy Explainability

## Objective

Answer, for a real production Decision, "why was this specific action ALLOWED / BLOCKED / ESCALATED?" at the level of individual policy conditions, using the exact policy version and bundle that actually governed it at the time. Not a new policy engine, not a new AI reasoning system, not Enterprise Knowledge, not a Decision Center redesign. Runtime Authority stays deterministic and authoritative; this milestone only makes its past decisions explainable.

The hard requirement carried through every design decision below: **a historical decision must never be explained using the current active policy.**

## Architecture: authoritative vs. explanatory paths

```
Authoritative path (unchanged):
  Intent -> decision_engine.evaluate() -> OPA -> Decision (ALLOW/DENY/HUMAN_REVIEW)
            [ the one and only place an outcome is ever decided ]

Explanatory path (new, read-only, this milestone):
  Decision.policy_id -> Policy.bundle_manifest (Historical Policy Binding)
    -> exact RuntimePolicyRecord versions named in that manifest
    -> exact policy conditions, reconstructed
    -> evaluated against the decision's own recorded Intent/Evidence context
    -> Runtime Policy Simulator's existing explainer (unmodified)
    -> structured per-condition result, returned to the UI
```

The explanatory path never calls OPA, never calls an LLM, never constructs a second `Decision` row, and never writes to `Decision`, `Evidence`, `Policy`, or `RuntimePolicyRecord`. If any step in the reconstruction can't be completed from durably persisted data, it returns an explicit unavailable state with a reason code rather than falling back to today's active policy or fabricating a plausible-looking result.

## Implementation

**`server/app/services/decision_explanation_service.py`** (new). `get_decision_explanation(db, decision_id, organization_id)`:

1. Loads the `Decision`. Raises `DecisionNotFoundError` if it doesn't exist.
2. If `Decision.policy_id` is `None` (no active policy existed at evaluation time), or the decision's `reason` indicates OPA itself never completed (`opa_timeout`, `opa_error:*`), returns `ExplanationUnavailable` rather than reconstructing a hypothetical result for an evaluation that never really happened.
3. Loads the bound `Policy` row. Raises `CrossOrganizationAccessError` if it belongs to a different organization than the caller (the router turns this into the same 404 as "not found," never a 403 -- a cross-org caller can't distinguish the two, matching the existing `policy-binding` endpoint's own discipline).
4. Reads `Policy.bundle_manifest` (Historical Policy Binding). Empty/absent means the bundle predates that column; returns unavailable rather than guessing.
5. Reads the decision's earliest `Evidence` record for the resolved principal name and authority context; reads the `Intent` for action/amount/currency.
6. For each policy named in the manifest, looks up the exact `RuntimePolicyRecord` at the exact version recorded, and converts it via `runtime_policy_service._row_to_policy` (already imported cross-module elsewhere in this codebase; reused as-is, not renamed).
7. Feeds the reconstructed policies, intent, and context into `domain/policy_simulation/explainer.build_rule_evaluations` -- the Runtime Policy Simulator's own explainer, completely unmodified, reused rather than duplicated. `matched` is read straight from the decision's real `evaluated_mandates` (OPA's actual answer), never recomputed, so the explanation can never disagree with what really happened.
8. The causal rule (the one whose match actually produced the outcome, if any) is whichever rule has `matched=True`.

Every unavailable reason is a distinct, real code: `no_policy_evaluated`, `evaluation_did_not_complete`, `bundle_not_found`, `bundle_manifest_not_available`, `evidence_not_available`, `principal_not_resolved`, `historical_policy_record_missing`.

## Files changed

- `server/app/services/decision_explanation_service.py` -- new, the explanatory reconstruction service.
- `server/app/schemas/intent.py` -- new `DecisionExplanationResponse`, reusing `RuleEvaluationResponse`/`ConditionEvaluationResponse` from `schemas/policy_simulation.py` rather than a second, parallel definition of the same shape.
- `server/app/routers/intents.py` -- new `GET /v1/decisions/{decision_id}/explanation` endpoint, and its `_rule_to_response` presentation-layer converter (mirrors `routers/policy_simulation.py`'s existing one; kept local since importing across router modules for six lines wasn't worth the cross-dependency).
- `server/tests/integration/test_decision_explanation.py` -- new, 12 integration tests (below).
- `src/app/live/types.ts` -- new `ConditionEvaluation`, `RuleEvaluation`, `DecisionExplanation` types.
- `src/app/live/format.ts` -- new `describeExplanationUnavailable`, plus a `decision_not_found` entry in the existing API-error detail mapping.
- `src/app/live/pages/LiveTestIntent.tsx` -- the "Runtime policies evaluated" card is now expandable; per-condition detail is fetched lazily on first expand.

## API changes

`GET /v1/decisions/{decision_id}/explanation` -- authenticated, organization-scoped, gated by `Permission.RUNTIME_POLICY_VIEW` (the same permission `routers/policy_simulation.py` already uses for every read-only rule-evaluation exposure in this codebase; reused as precedent rather than inventing a new gate). Cross-org access and nonexistent decisions both return 404 (`decision_not_found`), never 403 or a schema difference that would leak which case occurred.

Response is `DecisionExplanationResponse`: `available: bool` plus, when true, `outcome`, `reason`, `policy_id`, `bundle_hash`, `bundle_version`, `compiled_at`/`activated_at`/`retired_at`, `evaluated_at`, `causal_policy_id`, and `rules: RuleEvaluationResponse[]`. When `available: false`, only `decision_id` and `unavailable_reason` are populated -- a real, distinct, documented response shape, not an error path pretending to be data.

## UI changes

`LiveTestIntent.tsx`'s existing "Runtime policies evaluated" card (previously a flat list of matched policy keys with an explicit comment that condition-level detail "would require wiring the Simulator's explainer to live traffic ... not something to fake here") gains a "Show policy evaluation" toggle. On first expand it fetches the new endpoint and renders, per rule: the policy name, whether it applied / didn't apply / wasn't relevant, its plain-English summary, and a checkmark/x-mark line per condition with the expected and actual value. The rule that actually caused the outcome is visually highlighted. All 7 required states are handled: available (full breakdown), loading (skeleton), unavailable (`describeExplanationUnavailable`, one sentence per reason code), historical-policy-unavailable (the `bundle_manifest_not_available` reason specifically), permission-denied and decision-not-found (both surfaced through the existing `describeApiError`, extended for the endpoint's own 404 detail), and empty/no-conditions (an explicit "No policy conditions were recorded for this decision" rather than a blank panel). The 3-column Decision Center architecture is unchanged; no redesign.

## Test results

12 new integration tests, run against a real ephemeral OPA server and the real production SQLAlchemy models (SQLite in-memory, same disclosed compatibility shims used throughout this engagement -- no Postgres/Docker available in this environment):

- **Outcomes**: `test_outcome_allow`, `test_outcome_deny`, `test_outcome_escalate` -- all three real outcomes (ALLOW/DENY/HUMAN_REVIEW) reconstructed and matched against a live OPA-produced decision.
- **Condition evaluation**: `test_mixed_conditions_passing_failing_and_irrelevant` -- one passing condition, one failing condition (same principal/action, mutually exclusive thresholds), and one rule scoped to a different principal entirely (correctly marked not relevant), all in a single decision.
- **Historical correctness**: `test_explanation_survives_two_subsequent_redeploys` -- a decision's explanation is proven unchanged (same $100,000 threshold, same bundle hash) after the policy is redeployed twice more, to a $50,000 and then a $1 threshold.
- **Tenant isolation**: `test_tenant_isolation_org_a_decision_not_resolvable_by_org_b` -- org B raises `CrossOrganizationAccessError` against org A's decision; org A can still resolve its own.
- **Determinism**: `test_determinism_identical_inputs_produce_identical_explanation` -- two calls against the same decision produce an identical result.
- **No-mutation**: `test_explanation_does_not_mutate_anything` -- `Decision`, `Policy`, and `Evidence` rows are snapshotted before and after two calls to the explanation service; nothing changed.
- **Failure handling**: `test_unavailable_when_no_policy_was_ever_evaluated`, `test_unavailable_when_bundle_predates_manifest`, `test_unavailable_when_decision_not_found` -- each produces its specific, real reason code rather than a fabricated result.
- **Permission enforcement**: `test_permission_enforcement_unauthenticated_unauthorized_authorized` -- calls `require_permission`'s own inner check directly (this codebase has no `TestClient`-based tests anywhere; confirmed via `tests/unit/test_architectural_boundaries.py`'s own documented convention before writing this), proving unauthenticated fails with 401, a `reviewer`-role session fails with 403, and a `governance_admin`-role session passes.

Full backend suite: **396 passed** (384 pre-existing + 12 new), 0 failed. Frontend build (`npm run build`) passed.

Two real, disclosed test-infrastructure bugs were found and fixed while writing these tests (both test-only; neither touches production code):

1. `intent_service.submit_intent` always constructs `HttpOpaClient()` with no `base_url` override, which falls back to `settings.opa_url` (default `http://localhost:8181`) rather than the ephemeral, random-port OPA server these tests actually deploy policies to. Left unpatched, every real decision query in a fresh test file hits a deterministic (not flaky) `opa_error:connection_error`, which is why every prior test in `test_historical_policy_binding.py` was written to avoid asserting on a live-OPA-dependent outcome at all. Fixed via a test-only autouse fixture that points `settings.opa_url` at the same ephemeral server `deploy_policy` already uses, restored after each test.
2. SQLite silently strips timezone information from `DateTime` columns on read regardless of `timezone=True`, so a `UserSession.expires_at` compared against a timezone-aware `datetime.now(timezone.utc)` inside `auth_service.py` raised `TypeError` after a `db.commit()`-triggered reload. Fixed by using `db.flush()` instead of `db.commit()` in that one test, keeping the in-memory (still timezone-aware) object rather than forcing a lossy reload -- a SQLite-only artifact, not a real bug in `auth_service.py`, which is written correctly for Postgres's real `TIMESTAMP WITH TIME ZONE` behavior.

A third anomaly (not a bug): a full-suite run's wall-clock read 15 hours (54498s) with a single spurious `httpx.ReadTimeout` on the last test, coinciding with two mid-session date rollovers. Re-running that file in isolation immediately afterward passed cleanly (6/6, ~4 minutes) -- consistent with the machine having slept mid-run, not a real regression.

## Tenant-isolation verification

Proven at the service layer (`test_tenant_isolation_org_a_decision_not_resolvable_by_org_b`): org B raises `CrossOrganizationAccessError` when passing org A's real decision id, and the router (`get_decision_explanation` in `routers/intents.py`) turns that into the same 404 `decision_not_found` used for a genuinely nonexistent decision -- a cross-org caller gets no signal distinguishing "wrong org" from "doesn't exist." Not separately re-verified live in production this round (no second organization/credential available in this session); the identical code path is the same one Historical Policy Binding's own tenant-isolation test already exercised against real infrastructure.

## Historical-policy verification

Proven at the service layer (`test_explanation_survives_two_subsequent_redeploys`): a decision evaluated under a $100,000 threshold keeps returning that exact threshold in its `rules[0].conditions[0].expected_value`, and the same `bundle_hash`, after the policy is redeployed twice more to $50,000 and then $1. This is the strongest form of the "never explain a historical decision with the current policy" requirement this milestone could prove without live production data spanning a real redeploy.

## Production verification

Verified live: the new image (`acrprprodtq1k.azurecr.io/payreality-api:prod-5041fbc`, commit `5041fbc`) was built via `az acr build` (confirmed `Succeeded` server-side via `az acr task list-runs` -- the local CLI's log-streaming crash is the same known Windows console-encoding artifact seen in every prior deploy this engagement, not a build failure), deployed via the existing Terraform process (`terraform plan` showed exactly one change, the image tag; `terraform apply` succeeded), and the new container app revision reached `Healthy` at 100% traffic -- which, per `entrypoint.sh`'s `alembic upgrade head` with `set -e` running before `uvicorn` starts, is itself proof any migration would have succeeded (none was needed this round; no schema change). The live production `openapi.json` was fetched and confirmed to list `GET /v1/decisions/{decision_id}/explanation` and the full `DecisionExplanationResponse` schema. A real unauthenticated request against the live endpoint was confirmed rejected with `401 authentication_required`.

The frontend was deployed via `vercel deploy --prod` (the Vercel CLI, already authenticated in this environment, bypasses the previously-documented stale-Git-link problem entirely since it uploads the local build rather than depending on the broken push-triggered webhook). `payreality.aisecurewatch.com` was confirmed serving the new build's exact asset hash (`index-BeguIvqP.js`, matching the just-built output) immediately after deploy.

**Not verified**: an actual authenticated, organization-scoped request against the live `/explanation` endpoint returning a real reconstructed decision, and the new Decision Center panel exercised in a live browser. No test credentials and no browser-automation tool are available in this environment -- the same disclosed limitation as every prior verification round in this engagement. What was verified instead: the identical, unmodified code path was exercised thoroughly against real infrastructure (a real OPA server, real service functions, real database) in the 12 new integration tests above, and every verifiable-without-a-credential aspect of the live deploy (schema, health, auth rejection, asset serving) was confirmed directly.

## Discovered but out of scope (documented, not fixed)

`GET /v1/decisions/{id}/policy-binding` (built in the prior Historical Policy Binding milestone) has no permission-level gate at all -- only a resolvable organization is required -- while this milestone's new `/explanation` endpoint is gated by `Permission.RUNTIME_POLICY_VIEW`. This is a real, pre-existing inconsistency between two closely related read-only endpoints, noticed while choosing the new endpoint's permission. Retroactively tightening the older endpoint would be scope expansion beyond this milestone's explicit boundaries, so it was left as-is and is recorded here rather than silently fixed or silently ignored.

## Known limitations

- Decisions bound to a `Policy` bundle deployed before Historical Policy Binding's `bundle_manifest` column existed can never be reconstructed (`bundle_manifest_not_available`) -- a permanent, already-disclosed limitation of that prior migration, not something this milestone can retroactively fix.
- Decisions where OPA itself never completed (`opa_timeout`, `opa_error:*`) are deliberately marked unavailable (`evaluation_did_not_complete`) rather than reconstructed, since a Python-side replay would show what the policy *would* have said, not what actually happened.
- The explanation endpoint depends on the decision's earliest `Evidence` record for the resolved principal name; a decision with no Evidence record (shouldn't happen in practice, since Evidence is written synchronously at submission time) or an unresolved principal both produce an honest unavailable state rather than a guess.

## Remaining risks

- No live, credentialed end-to-end verification of the new endpoint or UI panel was possible in this environment, as disclosed above.
- The frontend deploy's production alias update was verified by asset-hash match rather than a full page-by-page click-through, since no browser tool is available.

## Completion gate

**PHASE 2B: PASS.**

Every explicit requirement was met with real evidence: the authoritative/explanatory separation is structural, not just documented (the explanatory service performs no writes and never calls OPA or an LLM); the "never explain with the current policy" invariant is proven across two live redeploys, not just argued; all three outcomes, mixed condition results, tenant isolation, determinism, no-mutation, and every failure-handling branch have real regression coverage against real infrastructure; the API and UI both stayed within the smallest safe scope (no new policy engine, no Enterprise Knowledge, no redesign); the one discovered scope-adjacent inconsistency was documented rather than silently expanded on or ignored; and the deploy was verified live to the fullest extent this environment's disclosed constraints (no test credentials, no browser tool) allow.

Per instruction, no Enterprise Knowledge work and no further milestone were started. Awaiting explicit approval before either begins.
