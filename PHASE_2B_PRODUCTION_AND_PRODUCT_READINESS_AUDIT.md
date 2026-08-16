# Phase 2B: Production and Product Readiness Audit

Independent verification and product-readiness gate performed after Phase 2B (Historical Policy Binding + Live Per-Condition Explainability). This is an audit, not an implementation milestone: no policy engine, explanation algorithm, historical policy storage, or Enterprise Knowledge work was performed or changed while producing it. Every claim below was re-derived from current code, a fresh test run, and fresh live requests against production this session -- prior summary documents were treated as claims to verify, not facts to repeat.

## 1. Executive summary

Phase 2B's core technical claim holds up under fresh, independent re-verification: a historical decision's explanation is reconstructed from the exact policy state that governed it, never the currently active one, and this was re-proven today (not merely re-read from a prior report) by rerunning the full test suite against a live ephemeral OPA server and a real database. The authoritative/explanatory separation, determinism, and tenant isolation are all real, structural properties, not documentation claims.

Two things are genuinely new findings from this audit, not previously documented:

1. **`GET /v1/decisions/{decision_id}` has no authentication or organization-scoping of any kind** -- confirmed live in production this session. This is a pre-existing condition (not introduced by Phase 2B), but it is more severe than the previously-documented policy-binding/explanation permission asymmetry, and it was not called out with this level of clarity before.
2. **The Decision Center's own pipeline stage and its new expandable explanation card share the identical label "Runtime policies evaluated"** (`src/app/live/pages/LiveTestIntent.tsx:565` and `:947`), and the un-expanded pipeline stage displays a raw policy UUID list, not a human-readable policy name, as its only "why" signal. A non-technical operator cannot answer "why was this allowed?" from the collapsed view; even after expanding, the per-condition detail is technical notation (`amount <= 50000`), not business language.

Nothing found here requires a code fix as part of this audit, and no code was changed. Both authorization findings involve the authorization model and are reported as requiring explicit approval before any change, per this audit's own scope constraint.

**PHASE 2B FINAL VERDICT: PASS WITH WARNINGS.**

## 2. Scope

This is a verification and audit task. In scope: re-tracing every Phase 2B claim to code, tests, schemas, and live deployed artifacts; a fresh test run; a fresh live production check limited to safe, read-only, already-disclosed requests (no new production data was created); a UX audit of the Decision Center performed by tracing its actual rendering code (no browser tool is available, disclosed plainly rather than glossed over); and an evidence-based product-thesis and Enterprise Knowledge assessment. Out of scope, per explicit instruction: Enterprise Knowledge, Runtime Authority redesign, policy engine changes, explanation algorithm changes, and any historical policy binding change (none was found necessary). No such work was started.

## 3. Evidence reviewed

Documentation: `PHASE_2B_LIVE_PER_CONDITION_EXPLAINABILITY_SUMMARY.md`, `HISTORICAL_POLICY_BINDING_SUMMARY.md` (and its three companion docs), `RUNTIME_DECISION_CENTER_V2_SPEC.md`, `RUNTIME_DECISION_CENTER_V2_PHASE1_IMPLEMENTATION_SUMMARY.md`, `ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md`, `RBAC.md`.

Code, read directly this session (not assumed from the docs above): `server/app/services/decision_explanation_service.py`, `server/app/domain/policy_simulation/explainer.py`, `server/app/routers/intents.py` (full file), `server/app/dependencies.py` (`require_permission`, `get_current_organization`, `get_current_user_if_session`), `server/app/main.py` (router registration, confirming no global auth middleware exists), `server/tests/integration/test_decision_explanation.py` and `test_historical_policy_binding.py` (full files), `src/app/live/pages/LiveTestIntent.tsx` (the explanation-related sections and the pipeline-stage construction), `src/app/live/format.ts`, `src/app/live/types.ts`.

Live artifacts checked fresh this session: the production `openapi.json`, three live unauthenticated requests against `api.aisecurewatch.com` (below), the live container app revision status, and the current Terraform image tag against the current git `HEAD`.

## 4. Historical correctness verification

**FACT**, re-verified live this session (not reused from a prior run): `test_explanation_survives_two_subsequent_redeploys` (`test_decision_explanation.py`) was re-executed against a fresh ephemeral OPA server and passed. It deploys a policy with a $100,000 threshold, submits a decision under it, then redeploys the same policy key twice more (to $50,000, then $1), and asserts after each redeploy that the explanation still reports `expected_value == 100000` and the same `bundle_hash`. This is the same scenario `PHASE_2B_LIVE_PER_CONDITION_EXPLAINABILITY_SUMMARY.md` claimed; it was not accepted on the strength of that document alone.

The reconstruction chain was traced directly in `decision_explanation_service.py`: `Decision.policy_id` (immutable FK) -> `Policy.bundle_manifest` (Historical Policy Binding) -> `RuntimePolicyRecord` looked up by the exact `(policy_key, version)` pair named in the manifest (never "latest") -> `_row_to_policy` -> fed into the unmodified Simulator explainer. There is no code path in this file that reads the currently active `RuntimePolicyRecord` or currently active `Policy` row for reconstruction; every lookup is keyed off values captured at the original decision's own bundle.

`test_historical_stability_decision_survives_later_policy_version`, `test_bundle_stability_and_manifest_reconstruction`, and `test_lifecycle_retirement_does_not_destroy_reconstruction` (`test_historical_policy_binding.py`) were also re-executed fresh and passed, corroborating the same property at the binding layer (below the explanation layer).

**Not accepted as equivalent**: a current-policy lookup was checked and ruled out as the mechanism -- confirmed by reading the code, not inferred from the test passing alone.

## 5. Determinism verification

Traced directly in `decision_explanation_service.py` and `explainer.py`:

- **Does not call OPA**: confirmed by import inspection -- the file imports `intent_service`, `explainer`, and `runtime_policy_service._row_to_policy` only; no `HttpOpaClient` or `opa_client` import exists in this module.
- **Does not call an LLM**: no AI/LLM client import exists anywhere in this file or `explainer.py`.
- **Does not mutate state**: `test_explanation_does_not_mutate_anything` was re-run fresh and passed -- it snapshots `Decision`, `Policy`, and `Evidence` rows, calls the service twice, reloads, and asserts no field changed.
- **Does not depend on current policy state**: confirmed by §4 above.
- **Does not fetch external knowledge**: confirmed -- no Enterprise Knowledge code exists anywhere in the platform (§12), so there is nothing for this module to call even if it wanted to.
- **Does not silently fall back to current policy**: confirmed -- every lookup failure (`bundle_not_found`, `bundle_manifest_not_available`, `historical_policy_record_missing`, etc.) returns `ExplanationUnavailable` with a distinct reason code rather than substituting a different policy version.
- **Returns an explicit unavailable state on failure**: seven distinct reason codes exist and each has a dedicated test (`test_unavailable_when_no_policy_was_ever_evaluated`, `test_unavailable_when_bundle_predates_manifest`, `test_unavailable_when_decision_not_found`), all re-run fresh and passing.

`test_determinism_identical_inputs_produce_identical_explanation` was re-run fresh and passed (two calls against the same decision produce an equal dataclass).

## 6. Tenant isolation verification

**FACT**, re-verified fresh: `test_tenant_isolation_org_a_decision_not_resolvable_by_org_b` (explanation) and `test_tenant_isolation_cross_org_cannot_resolve_binding` (policy-binding) both re-ran and passed. Both construct two real organizations, deploy a policy and submit a real decision under org A via a live OPA round trip, then assert org B's id raises `CrossOrganizationAccessError` (explanation) or gets a 404-shaped result (policy-binding), while org A can still resolve its own decision normally. Valid-organization access and cross-organization access are both exercised in the same test, not just the negative case.

The router-level behavior was confirmed by code, not just the service-level exception: `get_decision_explanation` in `routers/intents.py` catches both `DecisionNotFoundError` and `CrossOrganizationAccessError` and returns the identical `HTTPException(404, "decision_not_found")` for both -- a cross-org caller and a caller of a nonexistent decision get byte-identical responses, so cross-org access cannot be distinguished from nonexistence. This matches the platform's existing intended behavior (the same discipline `get_decision_policy_binding` already used before Phase 2B).

**Not weakened to make anything pass**: no test or code was modified during this audit.

## 7. Authorization review

This section covers the specific inconsistency named in the task, plus one additional finding surfaced while tracing it.

### 7.1 `policy-binding` vs `explanation` (the originally-named inconsistency)

Both endpoints depend on `get_current_organization` (`app/dependencies.py:130`), which **does require authentication** -- it returns `401 authentication_required` with no operator key and no bearer token, and `401 invalid_operator_key` / `401 invalid_or_expired_credential` on a bad one. This is a correction to how the prior summary's language ("no permission-level gate at all") could be read: `policy-binding` is not unauthenticated. The actual asymmetry is narrower and more specific than "no protection":

- `GET /v1/decisions/{id}/policy-binding`: requires a valid credential resolving to *some* organization. Does **not** call `require_permission` for any specific RBAC permission. Any authenticated user of any role in that organization -- including a role granting zero explicit permissions -- can retrieve the org's policy manifest content (policy names, scopes, effects, versions).
- `GET /v1/decisions/{id}/explanation`: requires the same authentication, **plus** `Permission.RUNTIME_POLICY_VIEW` specifically (`routers/intents.py:247`).

**Concrete consequence, confirmed against the actual RBAC model** (`domain/rbac/permissions.py`, read earlier this engagement and not re-contradicted this session): the `REVIEWER` role has only `AUTHORITY_REVIEW`, not `RUNTIME_POLICY_VIEW`. A `REVIEWER`-role user can authenticate, call `policy-binding`, and see full policy manifest content for their organization, but is correctly denied (`403 permission_denied`) at `explanation` for the same underlying content.

**Is this intentional?** No evidence found that it was a deliberate design decision -- `RBAC.md` has zero mentions of `policy-binding`, and `PHASE_2B_LIVE_PER_CONDITION_EXPLAINABILITY_SUMMARY.md` itself frames it as "discovered... while choosing the new endpoint's permission," not as a pre-existing, deliberate split. **OBSERVATION**: this reads as an oversight from when `policy-binding` was built (Historical Policy Binding), not a considered decision to make it more permissive than `explanation`.

**Does it create an actual security issue?** A narrow one: a role intentionally scoped to *not* see Runtime Policy content (`REVIEWER`) can currently see policy names/scopes/effects (not the full per-condition breakdown, but structural policy metadata) via the older endpoint. This is real but bounded -- it leaks policy structure, not decision outcomes or Evidence content, and only within the caller's own organization.

**Classification: SECURITY FIX -- REQUIRES APPROVAL.** The correct fix (adding `Permission.RUNTIME_POLICY_VIEW` to `policy-binding`) is small and low-risk in isolation, but it is an authorization-model change to a live, shipped endpoint, which this audit's own scope requires be reported rather than silently applied.

### 7.2 `GET /v1/decisions/{decision_id}` has no authentication or org-scoping at all (new finding, more severe)

Traced directly in `routers/intents.py:113-114`:

```python
@router.get("/decisions/{decision_id}", response_model=GetDecisionResponse)
def get_decision(decision_id: UUID, db: Session = Depends(get_db)):
```

No `require_permission`, no `get_current_organization`, no auth dependency of any kind. Confirmed there is no global auth middleware that would cover this gap: `app/main.py`'s only registered middleware is `observability_middleware` and `CORSMiddleware` (neither performs authentication), and `include_router` calls carry no router-level `dependencies=`.

**Live confirmation this session** (a safe, read-only, unauthenticated request against a nonexistent decision id, not a real org's data):

```
GET https://api.aisecurewatch.com/v1/decisions/00000000-0000-0000-0000-000000000000
-> 404 {"detail":"decision_not_found"}
```

This 404 response itself required no credential of any kind -- confirming live that the code path really is reachable with zero authentication. For comparison, the same unauthenticated request against `/explanation` and `/policy-binding` both correctly return `401 authentication_required`:

```
GET .../explanation      -> 401 {"detail":"authentication_required"}
GET .../policy-binding   -> 401 {"detail":"authentication_required"}
```

**What this means in practice**: anyone who obtains a real decision's UUID (from a log line, a URL, a support ticket, browser history, or any other leak) can retrieve that decision's outcome, reason, agent id, action, amount, currency, and matched-policy identifiers -- across any organization -- with no credential at all. Practical severity is reduced by UUIDv4 being unguessable by brute force, but this is still a genuine, structural absence of authorization on a live endpoint that returns real financial-decision data.

**Is this pre-existing or introduced by Phase 2B?** Pre-existing. `get_decision_policy_binding`'s own docstring (written during the Historical Policy Binding milestone, before Phase 2B) already states plainly: "`GET /v1/decisions/{id}` itself has no such scoping (a separate, pre-existing, unrelated fact, not something this endpoint changes)." Phase 2B did not introduce, worsen, or touch this. It was, however, not previously surfaced with this level of explicitness as a standalone finding, which is why this audit reports it now.

**Classification: SECURITY FIX -- REQUIRES APPROVAL.** This is the more consequential of the two authorization findings in this document. No fix was applied.

## 8. Production verification

Credential availability was checked directly this session, not assumed:

- No PayReality API credential, operator key, or bearer token exists in this environment's shell environment or any `.env` file (`.env.example` only).
- Azure Key Vault (`kv-pr-prod-c6ceqz`) secret **names** are listable (`admin-api-key`, `evidence-signing-key-b64`, etc.), but retrieving an actual secret **value** (`az keyvault secret show ... --query value`) was denied by this environment's own permission classifier ("Blocked by classifier") when attempted this session. This was a real attempt, not an assumption.
- No browser-automation tool is registered in this session (confirmed via tool search; only a non-interactive HTML-to-markdown fetch tool is available).
- Creating a brand-new real organization/user/policy on the live production system purely to manufacture a test credential was considered and deliberately not done: it would be a consequential, unrequested write to shared production state, which this audit's read-only verification purpose does not require and this session is not authorized to perform unilaterally.

**AUTHENTICATED PRODUCTION VERIFICATION: NOT POSSIBLE.**

What was verified instead, live, this session, all read-only and requiring no credential:

| Check | Result |
|---|---|
| Git `HEAD` vs. deployed image tag | `HEAD` is `75e83cf` (docs-only commit); `prod.tfvars` still points at `prod-5041fbc` (the Phase 2B backend commit); no backend code has changed since that deploy. |
| Live container app revision | `ca-payreality-api-prod-cus--0000007`, `Healthy`, 100% traffic (unchanged since Phase 2B's own deploy). |
| `openapi.json` | `GET /v1/decisions/{decision_id}/explanation` and `DecisionExplanationResponse`'s full schema are present in the live production schema. |
| Unauthenticated `/explanation` | `401 authentication_required`. |
| Unauthenticated `/policy-binding` | `401 authentication_required`. |
| Unauthenticated `/decisions/{id}` (bare) | `404 decision_not_found` -- reachable with zero credential (see §7.2). |

The identical, unmodified code path was additionally exercised end-to-end against real infrastructure (a real OPA server, a real database) in the fresh test run in §4-6, which is the closest substitute available in this environment for a credentialed live round trip.

## 9. Browser/UX verification

**BROWSER VERIFICATION: NOT POSSIBLE.** No browser-automation tool is available in this session (confirmed via tool search this session, not assumed from a prior session's finding). No claim below should be read as an observed rendering in an actual browser.

In its place, the actual rendering code (`src/app/live/pages/LiveTestIntent.tsx`) was traced line by line for the states the task named:

| State | Traced code path | Observation |
|---|---|---|
| Empty | `!decision && !submitting` | Calm placeholder text, form remains usable. |
| Evaluating | `!decision && submitting` | Single "Evaluating..." indicator (no fabricated staged animation implying independent backend sub-steps). |
| Allow / Deny | `decision.outcome`, `OUTCOME_STYLE` map | Distinct icon/color per outcome (`CheckCircle2`/green, `XCircle`/red). |
| Escalate / Awaiting Approval | `outcome === "HUMAN_REVIEW" && status === "PENDING"` | Amber styling, Approve/Deny buttons, matches the platform's only real approval workflow (§ product thesis, §11). |
| Blocked | Submission-time error before any decision exists | Distinct copy path (`describeApiError`), reuses the platform's existing fail-closed sentence rather than inventing new copy. |
| Explanation loading | `explanationLoading` | Two skeleton bars. |
| Explanation expanded | `explanationExpanded && explanation.available` | Renders `RuleEvaluationCard` per policy, causal rule visually highlighted. |
| Explanation unavailable | `explanation.available === false` | One sentence via `describeExplanationUnavailable`, keyed by the specific reason code -- not a generic error. |
| Error state | `explanationError` (a real fetch failure, distinct from `available: false`) | `Alert` with a retry button. |

**Lazy loading**: confirmed by code -- `handleToggleExplanation` only calls `loadExplanation` on first expand for a given decision id (`explanationDecisionId !== decision.id`), not on every render or on decision load.

**Layout stability on expansion**: cannot be confirmed without a real browser (this requires observing actual reflow, which static code tracing cannot do). Flagged as **UNVERIFIED**, not claimed either way.

**Whether a non-technical operator can answer "why was this allowed/blocked" without understanding OPA/Rego**: traced concretely, not guessed --

- **Collapsed (default) view**: the center pipeline's "Runtime policies evaluated" stage detail is literally `${count} policies evaluated: ${decision.evaluated_mandates.join(", ")}` (`LiveTestIntent.tsx:569`), and `evaluated_mandates` contains raw `RuntimePolicy.id` values (confirmed in `compiler_v2/bundle_builder.py:119`: `evaluated_mandates contains {policy.id}`), which are typically UUIDs, not policy names. **An operator cannot answer "why" from the default view** -- they see a policy identifier, not a policy name or reason.
- **Expanded view**: `RuleEvaluationCard` does show the human-authored `policy_name` and a translated status label ("Applied"/"Not applied"/"Not relevant"), which is a real improvement. But `ConditionRow` renders raw `{field} {operator} {expected_value}` (e.g., `amount <= 50000`) plus `(actual: 75000)` with no currency formatting, no field-name humanization, and the backend's own `rule.summary` string is written in the same register (e.g., `"Failed: amount <= 50000 (actual: 75000)."`). **An operator can identify which policy and roughly which numeric comparison decided the outcome, but is still reading a condition, not a sentence a compliance officer would write.**

## 10. Explanation quality review

Classified per the task's four-way taxonomy, based on the actual payload and rendering code (no translation layer was invented for this classification; only what exists was inventoried):

| Element | Classification | Evidence |
|---|---|---|
| Policy name (`rule.policy_name`) | LIVE BUSINESS EXPLANATION | Human-authored string from the policy's own `name` field; rendered directly. |
| Applied/Not applied/Not relevant status label | LIVE BUSINESS EXPLANATION | `LiveTestIntent.tsx:172`, a real translation of `matched`/`scope_matched` into plain words. |
| Top-level outcome (`ALLOW`/`DENY`/`HUMAN_REVIEW`) | LIVE BUSINESS EXPLANATION | `formatStatus`/`OUTCOME_STYLE`, already-shipped, humanized. |
| `unavailable_reason` sentences | LIVE BUSINESS EXPLANATION | `describeExplanationUnavailable` (`format.ts:105`), one full sentence per reason code. |
| Per-condition detail (`field operator expected_value`, `actual: ...`) | LIVE TECHNICAL EXPLANATION | Raw field names and operator symbols, no currency/unit formatting, no humanized field labels. |
| Rule `summary` string (e.g., `"Failed: amount <= 50000 (actual: 75000)."`) | LIVE TECHNICAL EXPLANATION | Generated in `explainer.py:158-163`, deliberately mirrors Rego semantics exactly (by design, for correctness) rather than business phrasing. |
| Bundle hash / policy version / evaluated-at footer | LIVE TECHNICAL EXPLANATION | Audit-trail-grade detail, shown directly beneath the rule list rather than behind a secondary disclosure. |
| Business-language translation of a *specific numeric condition* (the task's own example: "Payment exceeded the delegated approval limit of $100,000") | MISSING | No such translation layer exists anywhere in the codebase for condition-level content; confirmed by reading `explainer.py` and `format.ts` in full. This was not assumed to be missing -- it was checked for and not found. |

**Smallest improvement identified (not implemented, per this audit's scope):** a single, small display-mapping function -- field name to a human label (`amount` -> "Payment amount"), operator symbol to a phrase (`<=` -> "at or below"), and currency-aware number formatting -- applied only at render time in `ConditionRow`. This would not require any backend change (the raw values are already present in the payload) and would not touch `explainer.py`'s own Rego-mirroring correctness guarantee, since the technical values would still be computed identically; only their on-screen phrasing would change. This is identified as a candidate, not scoped or approved here.

## 11. Product thesis assessment

The claim under evaluation: *"PayReality can prove not only what decision an AI system made, but why that decision was authorized or rejected according to the exact authority and policy state that existed at the time."*

**What is genuinely proven** (re-verified this session, not merely re-read): a decision's outcome, the exact policy version and bundle hash that produced it, and a per-condition breakdown of that exact historical policy state are all real, reconstructed correctly even after the policy has since changed twice, backed by passing tests against real infrastructure and a live-confirmed production deployment. The "why," at the level of *which rule and which condition*, is proven.

**What remains unproven**: that this is *usable* proof for a non-technical audience without engineering assistance (§9-10 above: the default view shows a policy UUID, and the expanded view uses technical notation). The claim as marketing language ("can prove... why") is defensible for an auditor willing to read a condition expression; it is not yet defensible as "a compliance officer can look at this screen and understand it unassisted."

**What is still merely vision**: multi-hop authority chains, Enterprise Knowledge-informed conditions, and any representation of organizational SOPs/approval-chain process upstream of the flat rule itself (see `RUNTIME_AUTHORITY_THESIS_EVOLUTION.md`, a separate, explicitly-labeled hypothesis document, not conflated with this audit's findings).

**Verdict**: Phase 2B materially strengthens the technical half of this claim (the reconstruction is real, tested, and live) but has not yet closed the usability half. This is a finding, not a criticism of scope -- Phase 2B's own stated objective was the reconstruction, not a full UX translation layer, and it should not be judged against a goal it never claimed.

## 12. Enterprise Knowledge assessment

Per instruction, Enterprise Knowledge was not built or scoped as part of this audit. Evidence gathered:

- `ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md`: "A design, not a build... PROPOSED throughout." Zero code, zero schema, zero connector exists anywhere in the repository -- confirmed by the absence of any Enterprise Knowledge import, table, or router in the codebase this session.
- `PAYREALITY_ENTERPRISE_KNOWLEDGE_RESOLUTION_VISION.md`: "Living document... Exploratory... Nothing in this document should be read as a commitment."
- `RUNTIME_AUTHORITY_THESIS_EVOLUTION.md` (this repository's own most recent research document): the customer-conversation evidence gathered so far (Lourens Joubert, Wesley Fredericks, Leor Schiffer, Pretty Newman) is explicitly about organizational process/SOP/approval-chain structure, not about missing *external system facts* (the specific problem Enterprise Knowledge's design solves -- vendor-approved, AML-passed, budget-available, etc.). No conversation record cited there names a missing external fact that blocked a real evaluation.
- No repository evidence was found of the existing flat rule-plus-condition model failing in practice for lack of an external fact.

Answering the task's specific questions:
- What information is missing from runtime evaluation today? No concrete, repeated instance was found in the evidence reviewed.
- Is missing information repeatedly appearing in real customer workflows? Not evidenced yet -- the customer-conversation record is about process/SOP structure, a different gap (see `RUNTIME_AUTHORITY_THESIS_EVOLUTION.md` §4-7), not about external-fact resolution.
- Does the existing model fail without external organizational knowledge? Not evidenced.
- Can existing enterprise systems provide the necessary facts? Unknown -- no specific system or fact has been named as needed yet.
- Is a local versioned knowledge layer actually required? Not evidenced as required yet.

**ENTERPRISE KNOWLEDGE: NOT YET JUSTIFIED.**

## 13. Findings matrix

| Area | Status | Evidence | Priority | Recommendation |
|---|---|---|---|---|
| Historical policy binding | PASS | 6 tests re-run fresh, all passing; $100,000 threshold survives two redeploys | -- | None |
| Per-condition explainability | PASS | 12 tests re-run fresh, all passing; determinism and no-mutation independently confirmed | -- | None |
| Decision Center UX | PASS WITH WARNINGS | Duplicate "Runtime policies evaluated" label; raw UUID shown in collapsed pipeline stage; technical condition notation in expanded view | MEDIUM | Rename one of the two duplicate labels; consider a display-only humanization layer for condition text (§10) |
| Authenticated production verification | REQUIRES RESEARCH | No credential available; Key Vault secret retrieval blocked by this environment's own classifier; creating new production data to manufacture a credential was deliberately avoided | LOW (blocked by environment, not by product readiness) | Obtain a real test-organization credential through a channel outside this session (e.g., a scoped credential the user provisions) before the next audit |
| Browser verification | REQUIRES RESEARCH | No browser-automation tool available this session; substituted with a full code trace | LOW (blocked by tooling, not by product readiness) | Run a manual browser pass, or add a browser-automation tool to this environment, before treating the UI as fully verified |
| Policy-binding authorization | REQUIRES APPROVAL | `policy-binding` requires authentication but not `RUNTIME_POLICY_VIEW`; a `REVIEWER`-role user can see policy content `explanation` correctly denies them | MEDIUM | Add `Permission.RUNTIME_POLICY_VIEW` to `policy-binding` -- small, low-risk, but an authorization-model change requiring explicit approval |
| Bare decision-read authorization | REQUIRES APPROVAL | `GET /v1/decisions/{id}` has zero authentication or org-scoping, confirmed live this session | HIGH | Decide whether this endpoint should require authentication/org-scoping at all -- a larger authorization-model question than policy-binding's, since callers of this endpoint today (if any rely on it being open) are unknown without further investigation |
| Enterprise Knowledge | NOT JUSTIFIED | No repository or customer-conversation evidence of a missing-external-fact failure | -- | Do not build; revisit if the research plan in `RUNTIME_AUTHORITY_THESIS_EVOLUTION.md` surfaces concrete instances |

## 14. Remaining risks

- The two authorization findings in §7 remain live and unaddressed in production, pending explicit approval on whether and how to fix them.
- No end-to-end authenticated verification of `/explanation` or `/policy-binding` against a real decision has ever been performed in this environment, across two consecutive milestones now -- this is an accumulating verification gap, not a one-time disclosure, and should be closed with a real credential at the next opportunity rather than repeatedly deferred.
- No real browser has ever rendered the Decision Center's new explanation panel -- layout stability on expansion (an explicit item the task asked about) is genuinely unknown, not merely "not yet checked for the first time."
- The UX findings in §9-10 (duplicate label, raw UUID in the default view, technical condition notation) mean the product's own core "why" claim is currently better proven to an engineer reading test output than to the enterprise operator the product is for.

## 15. Recommended next step

Do not proceed to Enterprise Knowledge or any Runtime Authority redesign. The smallest useful next steps, in priority order, none of which are authorized by this document alone:

1. Decide, with explicit approval, whether and how to close the two authorization findings in §7 -- particularly §7.2, the fully unauthenticated decision-read endpoint, which is the highest-severity item this audit found.
2. Obtain a real, scoped test credential (or a safe path to create one) so the next audit can perform genuine authenticated production verification instead of repeating this disclosure a third time.
3. Add a browser-automation tool to this environment, or perform a manual browser pass outside it, before the Decision Center's UX is treated as verified rather than code-traced.
4. If and when capacity allows, a small, display-only humanization pass on condition text (§10) would close most of the gap between "provable" and "understandable by a non-technical operator" -- scoped narrowly enough that it would not need to touch `explainer.py`'s correctness-preserving design.

## 16. Explicit completion verdict

**PHASE 2B: PASS WITH WARNINGS.**

The technical substance of Phase 2B -- historical correctness, determinism, tenant isolation, no-mutation, and the authoritative/explanatory separation -- was independently re-verified with fresh evidence this session and holds without qualification. The "warnings" in this verdict are: two authorization findings requiring explicit approval (one newly surfaced at higher severity than previously documented), a real but bounded UX gap between what the system can prove and what a non-technical operator can currently read off the screen, and two verification gaps (credentials, browser) that remain genuinely unclosed rather than newly introduced.

**AUTHENTICATED PRODUCTION VERIFICATION: NOT POSSIBLE** (this session; see §8 for the specific, real reasons).

**BROWSER VERIFICATION: NOT POSSIBLE** (this session; see §9 for the specific, real reasons, and for the code-trace performed in its place).

**ENTERPRISE KNOWLEDGE: NOT YET JUSTIFIED.**

No code was changed by this audit. No architecture, engine, or explanation-algorithm change was made. Both authorization findings are reported, not fixed, and both require explicit approval before any change is made. This document does not authorize proceeding to Enterprise Knowledge or any other next phase.
