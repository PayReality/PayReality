# Milestone 10: Decision Security Boundary and Decision Center Clarity

Remediates the two authorization findings and the two UX findings from `PHASE_2B_PRODUCTION_AND_PRODUCT_READINESS_AUDIT.md`. Narrowly scoped: no Enterprise Knowledge, no Runtime Authority redesign, no policy-evaluation semantic change, no historical policy binding change.

## 1. Scope

In scope: the authorization boundary on `GET /v1/decisions/{decision_id}` and `GET /v1/decisions/{decision_id}/policy-binding`, adversarial regression tests for both, a repository-wide sweep for structurally similar gaps (documented, not all remediated), and two Decision Center UX fixes (duplicate labeling, raw UUID as the primary "why" signal) plus a deterministic business/technical explanation layer. Out of scope, untouched: Enterprise Knowledge, multi-hop authority chains, Runtime Authority evaluation semantics, OPA policy semantics, policy compilation, historical policy binding architecture, AI Policy Builder architecture, Azure infrastructure, DNS, Render, the marketing website.

## 2. Findings from Phase 2B audit

1. `GET /v1/decisions/{decision_id}` had no authentication and no organization scoping at all -- confirmed live in production with a real unauthenticated request in the prior audit. **BLOCKER-SEVERITY.**
2. `GET /v1/decisions/{decision_id}/policy-binding` required authentication but not `Permission.RUNTIME_POLICY_VIEW`, letting a `REVIEWER`-role user see policy content `/explanation` correctly denied them.

Both were re-traced from scratch through the actual code before any change was made (`server/app/routers/intents.py`, `server/app/dependencies.py`, `server/app/domain/rbac/permissions.py`, `server/app/main.py`), not assumed from the audit document's own account.

## 3. Security fixes

### 3.1 `GET /v1/decisions/{decision_id}`

Gated with `Permission.DECISIONS_VIEW` -- an **existing** RBAC permission (`domain/rbac/permissions.py:69`, `decisions.view`) defined since Phase 10 but never enforced anywhere in the codebase until now (confirmed by a repo-wide grep before use: it appeared only in `permissions.py` itself and in two roles' permission sets). No new permission was invented. Already granted to `GOVERNANCE_ADMIN`, `AUDITOR`, and `OWNER` (via the full-permission set); not granted to `REVIEWER`, `AGENT_ADMIN`, or `EXECUTIVE`.

Organization-scoping reuses the exact resolution path Runtime Authority Context and the Evidence chain already use: `Intent.agent_id -> Agent.acting_for_principal_id -> Principal.organization_id` (`intent_service._resolve_chain_scope`, unmodified). A new service function, `intent_service.get_decision_for_organization(db, decision_id, organization_id)`, wraps this resolution and raises `DecisionNotFoundError` or `CrossOrganizationAccessError`; the router catches both and returns the identical `HTTPException(404, "decision_not_found")` for either, so cross-org access can never be distinguished from nonexistence -- matching `get_decision_policy_binding`'s pre-existing discipline exactly.

### 3.2 `GET /v1/decisions/{decision_id}/policy-binding`

Gated with `Permission.RUNTIME_POLICY_VIEW`, the same permission `/explanation` already required. This was confirmed unintentional, not a deliberate design choice: `RBAC.md` has zero mentions of this endpoint, and no other documentation or code comment anywhere claims the asymmetry was considered. `/explanation` was **not** weakened to match; `/policy-binding` was tightened to match it.

### 3.3 SDK compatibility fix (required for fix 3.1 not to break real callers)

Before writing any test, the actual callers of `GET /v1/decisions/{decision_id}` were traced, not assumed. The Decision Center frontend already sends a session bearer token on every request (`apiClient.ts`'s `request()`, unconditionally) and needed no change. The official Python SDK's `Agent.get_decision()` (`sdk-python/payreality/agent.py`), however, called this endpoint with **zero authentication of any kind** -- the same class of gap as the server-side bug this milestone fixes, on the client side. Left unfixed, gating the server endpoint would have broken every real SDK-based agent integration's ability to poll its own decision result, directly violating "existing legitimate authorized access must continue working."

Fixed with a one-line change: `operator_auth=True`, the exact mechanism the SDK's own `register`/`activate`/`revoke`/`rotate` calls already use, requiring no new configuration from any `Agent` instance that already performs those calls. The SDK's own test suite (68 tests) was run and passes unmodified.

## 4. Authorization model used

`Permission.DECISIONS_VIEW` (decision reads) and `Permission.RUNTIME_POLICY_VIEW` (policy-binding, matching `/explanation`) -- both pre-existing permissions in `domain/rbac/permissions.py`, neither invented for this milestone. Enforcement goes through the existing `require_permission()` dependency (`app/dependencies.py`), the same layered check (operator key bypass, then bearer-token-resolved role, then permission lookup) every other permission-gated endpoint in this codebase already uses.

**Product consequence, disclosed rather than smoothed over:** `AGENT_ADMIN`, `REVIEWER`, and `EXECUTIVE`-role users can no longer retrieve a decision's detail via the Decision Center or the API, since none of those roles hold `DECISIONS_VIEW`. This is the direct, correct consequence of closing a defect where literally every role (and no role at all) could previously do so. Whether any of those three roles *should* be granted `DECISIONS_VIEW` going forward is a role-design/product decision this milestone does not make unilaterally -- flagged in section 11 as requiring approval, not decided here.

## 5. Organization isolation model

Reused, not invented: the same `Agent -> Principal -> organization_id` resolution (`_resolve_chain_scope`) the Evidence chain and Runtime Authority Context already depend on. `organization_id=None` (a real, valid scope for a Principal with no organization assigned, per that function's own pre-existing docstring) is explicitly tested: a real organization's session can never read a `None`-scoped decision, since `None != any real UUID` -- it is simply unreachable via this path, never silently granted to whichever organization happens to ask.

## 6. Adversarial tests

New file: `server/tests/integration/test_decision_security_boundary.py`, 12 tests, run against a real ephemeral OPA server and a real (SQLite-backed) database running the actual production models -- the same real-infrastructure discipline as every prior milestone's test suite in this engagement. Tests the actual authorization path (the service functions the router calls), not the route:

| Scenario (task's own lettering) | Test | Result |
|---|---|---|
| A. Unauthenticated decision read | `test_unauthenticated_decision_read_returns_401` | 401 `authentication_required` |
| D. Insufficient permission (decision read) | `test_decision_read_denied_for_role_without_decisions_view` (REVIEWER) | 403 `permission_denied` |
| Authorized role, decision read | `test_decision_read_allowed_for_role_with_decisions_view` (GOVERNANCE_ADMIN) | passes silently |
| B. Authorized same-org decision read | `test_same_organization_decision_read_succeeds` | real decision returned, fields match |
| C. Cross-organization access, non-disclosure | `test_cross_organization_decision_read_denied` | `CrossOrganizationAccessError`; own org still resolves normally |
| Nonexistent vs. cross-org, same shape | `test_nonexistent_decision_raises_the_same_shape_of_error_as_cross_org` | `DecisionNotFoundError`, mapped identically to cross-org by the router (verified by code, per this codebase's no-`TestClient` convention) |
| `organization_id=None` edge case | `test_decision_with_no_organization_is_not_reachable_by_a_real_organization` | `CrossOrganizationAccessError` |
| E. Policy binding without permission | `test_policy_binding_denied_without_runtime_policy_view` (REVIEWER) | 403 |
| F. Policy binding with permission | `test_policy_binding_allowed_with_runtime_policy_view` (GOVERNANCE_ADMIN), `..._for_auditor` (AUDITOR) | pass |
| G. Explanation without permission | `test_explanation_denied_without_runtime_policy_view` | 403 (re-confirms already-existing, unmodified Phase 2B behavior in this milestone's own suite) |
| H. Explanation with permission | `test_explanation_allowed_with_runtime_policy_view` | passes |

All 12 pass. **FIXED, VERIFIED.**

## 7. Decision Center UX changes

`src/app/live/pages/LiveTestIntent.tsx`:

- The center pipeline's stage previously labeled **"Runtime policies evaluated"** is renamed **"Policy evaluation"**. The expandable card previously sharing that identical label is renamed **"Why this decision was made"** -- the two are now unambiguously distinct, and the second name states plainly what the card answers.
- The pipeline stage's detail text previously listed raw policy UUIDs (`evaluated_mandates.join(", ")`) directly. Checked, not assumed: `GetDecisionResponse` has no policy name or version field anywhere (confirmed by reading `schemas/intent.py` and `types.ts`), so per instruction, none was invented. The stage now shows an honest count ("N policies evaluated. See 'Why this decision was made' below for detail.") and points at the renamed card, which is where a real reconstructed policy name already lives once expanded.
- The card's own collapsed state previously also listed the raw UUIDs unconditionally. That list was removed from the collapsed view entirely; the button's own subtitle already carries the count. The raw policy identifier is now shown only inside each expanded `RuleEvaluationCard`, as a small, explicitly labeled "Policy ID:" line below a border -- present for an auditor, no longer primary.
- Toggle button text updated to match: "Show explanation" / "Hide explanation".

## 8. Business vs. technical explanation model

New in `src/app/live/format.ts`: `describeConditionBusiness` and `describeConditionTechnical`, both pure, deterministic functions -- **no LLM, no semantic invention**. Reused directly in `ConditionRow`.

- `describeConditionTechnical` preserves the exact prior notation (`field operator expected_value (actual: value)`) verbatim, now labeled "Technical detail:" and shown in smaller, muted text below the business line -- nothing removed, only reordered and labeled.
- `describeConditionBusiness` humanizes only what can be done deterministically: a small, explicit field-label table (currently just `amount` -> "Payment amount", the one field this platform's own vocabulary is confident about) and a complete mapping of `Operator`'s small, closed enum (`<=`, `>=`, `<`, `>`, `==`, `!=`, `in`, `contains`, `exists`) to English phrases -- operators are a fixed, unambiguous set, unlike arbitrary field names, so translating all of them is safe where translating an arbitrary unknown field would not be. An unrecognized field keeps its raw name verbatim rather than an invented label. `amount` conditions with a numeric comparison get a fully-worded sentence, e.g. `"Payment amount ($75,000) exceeds the allowed limit of $100,000."`; every other condition still gets a real English sentence (`"{field} was {operator phrase} {value} (actual: {value}) -- matched/did not match."`) rather than bare symbolic notation, without asserting a business meaning that wasn't verified.

Both branches were reviewed against the task's own example (`"Payment amount is within the delegated approval limit of $100,000."` vs. `scope.action.amount <= 100000`) and produce that same style of sentence for the one case (`amount`, `<=`) where the example applies; no other condition shape was assumed to deserve the same confident phrasing.

## 9. Regression results

Full backend suite: **403 passed, 0 failed** (391 pre-existing + 12 new security-boundary tests), rerun fresh after all changes. Frontend build (`npm run build`): **passed**. SDK test suite (`sdk-python`): **68 passed**, confirming the `operator_auth=True` fix didn't break anything. `git diff --check`: clean (only pre-existing LF/CRLF line-ending warnings, not new whitespace errors).

## 10. Remaining security findings

A repository-wide sweep (section 5's instruction: search every endpoint reading decisions, evidence, policy bindings, explanations, or authority context) found the following, **none remediated in this milestone** since none is part of the decision-read boundary this milestone scoped:

| Endpoint | Auth? | Org-scoped? | Classification | Note |
|---|---|---|---|---|
| `GET /v1/evidence/chain/verify` | **None** -- `organization_id` is a plain, caller-supplied query parameter | **None** | **CRITICAL, REQUIRES FUTURE APPROVAL** | Confirmed by direct code read (`app/routers/evidence.py:124-134`): zero `Depends` performs authentication. Returns `total`, `intact` (bool), and lists of invalid-signature/broken-link Evidence UUIDs for *any* organization_id supplied, including `None`. Does not leak decision/evidence content directly, but does leak cross-tenant business-activity volume and audit-chain integrity status with no credential at all -- structurally the same class of defect as the bug this milestone fixed. The sibling endpoint `POST /{evidence_id}/verify` (single record) *is* correctly gated with `Permission.EVIDENCE_VIEW`, making this inconsistency likely unintentional, not confirmed as deliberate design. |
| `GET /v1/agents` (list) | `get_current_organization` only | Yes | MEDIUM, OUT OF SCOPE | Has authentication and org-scoping but no `require_permission` gate, unlike its sibling `GET /v1/principals` (list), which requires `Permission.AGENT_VIEW`. Not a decision-read endpoint. |
| `POST /v1/decisions/{decision_id}/resolve` | `Permission.DECISIONS_RESOLVE` | **None found** -- no `get_current_organization`/org comparison in the handler | MEDIUM, OUT OF SCOPE | A write endpoint, not a read, and explicitly out of this milestone's read-boundary scope; flagged because it sits immediately beside the endpoints just fixed. Not verified further this milestone. |
| `GET /v1/decisions/{id}`, `.../policy-binding`, `.../explanation` | Yes | Yes | LOW | Fixed this milestone (`.../policy-binding`) or already correct (`.../explanation`, and `.../{id}` as of this milestone). |
| `GET /v1/evidence/{id}`, `GET /v1/evidence` (list), `POST /v1/evidence/{id}/verify` | `Permission.EVIDENCE_VIEW` | Yes | LOW | Confirmed fully protected by direct code read. |
| `GET /v1/principals/{id}/authority-context`, `GET /v1/principals` (list) | `Permission.AGENT_VIEW` | Yes | LOW | Confirmed fully protected. |
| `GET /v1/agents/{agent_id}` (exposes decision/evidence history for that agent) | `_authorized_agent` (auth + org-scope) | Yes | LOW | The only route exposing `list_decisions_for_agent`/`list_evidence_for_agent`; both gated. |

The `evidence/chain/verify` finding is the most serious item this milestone surfaced. It is documented here, not fixed, per explicit instruction to remediate only what is clearly part of this milestone's decision-security boundary.

## 11. Remaining UX findings

- Whether `AGENT_ADMIN` and/or `EXECUTIVE` should be granted `DECISIONS_VIEW` (so they can still use the Decision Center to see their own test decisions) is a real product/role-design question this milestone surfaces but does not decide. **REQUIRES FUTURE APPROVAL.**
- No browser-automation tool is available in this environment (checked this session, not assumed). The renamed labels, the collapsed-state count text, and the business/technical condition layout were verified by tracing the actual rendering code and by a clean frontend build, not by observing them rendered in a real browser. Layout stability, exact visual spacing, and real-device rendering remain **UNVERIFIED**.
- The business-language layer currently only has confident phrasing for one field (`amount`). Every other field still produces a grammatically real but generic sentence rather than a tailored one -- an intentional, disclosed limitation (task instruction: do not fabricate semantic interpretations for fields that can't be safely translated), not an oversight.

## 12. Explicit out-of-scope items

Enterprise Knowledge, multi-hop authority chains, Runtime Authority evaluation semantics, OPA policy semantics, policy compilation, historical policy binding architecture, AI Policy Builder architecture, Azure infrastructure, DNS, Render, the marketing website -- none were touched, consulted for changes, or referenced as a dependency by anything in this milestone.

## 13. Production deployment status

**Not deployed this session.** Consistent with every prior milestone's disclosed constraint in this engagement: no PayReality API credential, operator key, or bearer token is available in this environment, and Key Vault secret-value retrieval is blocked by this environment's own permission classifier (not attempted again this session, since the prior audit already confirmed this same block minutes of engagement-time ago and nothing about credential availability has changed). No production data was created and no Key Vault permissions were modified to work around this.

**"Production verification unavailable in this environment."**

The code changes are committed and pushed to `main` (see section 14); deploying them follows the exact same `az acr build` + Terraform pattern used in every prior milestone once real deployment credentials are available in a session that has them. No claim of live-authenticated verification is made here.

## 14. Final completion verdict

| Requirement | Status |
|---|---|
| Unauthenticated decision access fixed | **FIXED, VERIFIED** (test + code trace) |
| Cross-org decision access blocked | **FIXED, VERIFIED** |
| Insufficient permissions blocked | **FIXED, VERIFIED** |
| Policy-binding permission inconsistency resolved | **FIXED, VERIFIED** |
| Regression tests exist | **FIXED, VERIFIED** (12 new, all passing) |
| Full backend tests pass | **VERIFIED** (403 passed) |
| Frontend build passes | **VERIFIED** |
| Decision Center terminology clearer | **FIXED** (code trace only, not browser-verified) |
| Raw UUID no longer primary operator-facing information | **FIXED** (code trace only, not browser-verified) |
| Business explanations deterministic and honest | **FIXED, VERIFIED** (no LLM; pure functions; unrecognized fields fall back honestly) |
| No fabricated functionality introduced | **VERIFIED** (no invented permission, no invented policy name/version field, no invented business phrasing beyond what's deterministically derivable) |
| Production deployment | **NOT VERIFIED** -- no credentials available this session, disclosed plainly |
| Enterprise Knowledge | **NOT STARTED** |

**MILESTONE 10: PASS WITH DISCLOSED LIMITATIONS.**

Every fixable-without-a-credential requirement in this milestone's own completion gate was met with real evidence: two live security defects closed using existing, previously-unused permissions rather than invented ones, a compatibility break in the official SDK caught and fixed before it could ship, twelve new adversarial tests exercising the actual authorization path (not just the route), a full regression pass (403 backend + 68 SDK tests + a clean frontend build), and two real UX defects fixed with a deterministic, non-fabricated business-language layer. The "disclosed limitations" are exactly two: production deployment could not be verified live (no credentials in this environment, stated plainly rather than faked), and one additional CRITICAL-severity finding (`evidence/chain/verify`) was discovered during the required regression sweep and is reported, not fixed, since it falls outside this milestone's decision-read boundary.

**Enterprise Knowledge was not started.** No architecture, engine, or policy-semantic change was made. This document does not authorize proceeding to any further phase.
