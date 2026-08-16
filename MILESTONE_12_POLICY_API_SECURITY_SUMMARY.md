# Milestone 12: Policy API Security Boundary and Cross-Tenant Metadata Protection

Closes the CRITICAL finding Milestone 11's required sweep discovered and deliberately left unfixed: the legacy `/v1/policies` read endpoints had zero authentication and no organisation scoping. Narrowly scoped: no Enterprise Knowledge, no Runtime Authority redesign, no policy-evaluation or OPA semantic change, no historical policy binding change, no policy-product redesign.

## 1. Executive summary

The vulnerability was independently re-verified from source (not trusted from the prior report) and reproduced live against production before any fix was deployed: an unauthenticated `GET /v1/policies` request returned a real Policy bundle row (id, version, status, bundle hash, lifecycle timestamps). All three endpoints (`/v1/policies`, `/v1/policies/documents`, `/v1/policies/authorities`) now require authentication and an appropriate existing permission, and the two endpoints with a real ownership chain (`Policy.organization_id`, `Authority.principal_id -> Principal.organization_id`) are fully organisation-scoped. The third (`documents`) has no ownership chain at all in the current schema -- this is disclosed explicitly as a residual, structural limitation, not silently presented as solved.

Live, credentialed, before/after verification against production confirmed: the vulnerability was real and exploitable before this deploy, and is closed after it -- including direct proof that a second real organisation authenticated against the same live system receives an empty list, never the first organisation's real policy data.

The required post-fix sweep found no new CRITICAL or HIGH finding.

**MILESTONE 12 VERDICT: PASS.**

## 2. Original vulnerability

Independently re-traced from source, not assumed from `MILESTONE_11_SECURITY_BOUNDARY_COMPLETION_SUMMARY.md`:

```
endpoint -> router -> service -> database query -> organization boundary -> permission boundary -> response
```

| Endpoint | Router | Service | Query | Org boundary (before) | Permission (before) |
|---|---|---|---|---|---|
| `GET /v1/policies` | `policies.py:list_policies` | `policy_service.list_policies(db)` | `select(Policy).order_by(Policy.version.desc())` | None | None |
| `GET /v1/policies/documents` | `policies.py:list_documents` | `document_service.list_documents(db)` | `select(Document)` | None (and none possible -- see section 5) | None |
| `GET /v1/policies/authorities` | `policies.py:list_authorities` | `review_service.list_authorities_for_review(db, ...)` | `select(Authority)` (+ an unscoped `all_approved` cross-check for duplicate detection) | None | None |

All three confirmed by direct code read of `app/routers/policies.py`, `app/services/policy_service.py`, `app/services/document_service.py`, and `app/services/review_service.py` as they existed before this milestone's changes.

## 3. Affected endpoints

Exactly the three named in the task, confirmed to be the only unauthenticated read endpoints in this router. The router's four write endpoints (`upload_document`, `review_authority`, `compile_policy`, `activate_policy`) were re-verified to each `raise HTTPException(status_code=410, ...)` as the literal first statement in their function body -- no database access occurs before the retirement error, so they were, and remain, safe regardless of their permission gate.

## 4. Root cause

This router (`policies.py`) is the retired, pre-Milestone-2 legacy Authority/Mandate authoring pipeline. Its write endpoints were correctly closed (`410 Retired`) when the pipeline was retired (`PHASE_0.md`), but its three read endpoints were deliberately kept reachable "for historical/audit access" (the router's own comment) and simply never received the authentication or organisation-scoping work every other endpoint touching the same underlying data (`Policy`, and, via `Principal`, `Authority`) received during Milestone 2's multi-tenant migration. `Document` was never given an `organization_id` column at all, since it predates multi-tenancy entirely and the pipeline it served was retired before that gap was ever revisited.

## 5. Security architecture applied

```
Authenticated identity -> Organization context -> Policy permission -> Organization-scoped policy query -> Response
```

- **`GET /v1/policies`**: `Depends(get_current_organization)` + `Permission.RUNTIME_POLICY_VIEW`. `policy_service.list_policies` now takes a required `organization_id` and filters `Policy.organization_id == organization_id` directly -- the same column Historical Policy Binding and every other Policy-reading code path already uses.
- **`GET /v1/policies/authorities`**: `Depends(get_current_organization)` + `Permission.AUTHORITY_REVIEW`. `review_service.list_authorities_for_review` now takes a required `organization_id` and joins `Authority.principal_id == Principal.id` filtered on `Principal.organization_id == organization_id` -- the only ownership chain this table has, since `Authority` predates multi-tenancy and carries no `organization_id` column of its own. The `duplicate_of` validation-flag cross-check (previously scanning *all* approved authorities system-wide) is now scoped by the same join.
- **`GET /v1/policies/documents`**: `Permission.AUDIT_EXPORT` (Owner-only) only -- no organisation-scoping was added, because none is possible. See section 5.1.

### 5.1 Documents: a disclosed, structural limitation, not a false guarantee

`Document` (`app/db/models.py`) has no `organization_id` column and no foreign key to anything organisation-scoped. It predates multi-tenancy; the legacy pipeline it served is retired and confirmed (the router's own docstring, verified against production, restated in section 10) to have zero rows in production. There is no ownership chain -- direct or indirect -- this table can be scoped by without a schema migration, which is explicitly out of this milestone's scope ("DO NOT redesign the policy product").

The fix applied (authentication + the single most restrictive existing permission, `AUDIT_EXPORT`) closes the actual CRITICAL defect (anyone, unauthenticated, could list every document) but does **not** provide per-organisation isolation, and this document does not claim otherwise. `test_g_list_documents_has_no_per_organization_isolation_a_known_limitation` (section 8) proves this in code rather than describing it only in prose. **REQUIRES APPROVAL** if true per-organisation isolation is ever needed here: it would require adding an `organization_id` column (or an indirect chain) to `Document`, a schema change this milestone does not make.

## 6. Permission model

No new permission was invented. Three existing permissions were reused, each already established as the correct fit for the resource it now gates:

- `Permission.RUNTIME_POLICY_VIEW` for `list_policies` -- the exact permission `GET /v1/decisions/{id}/explanation` and `.../policy-binding` already use to read this same `Policy` model.
- `Permission.AUTHORITY_REVIEW` for `list_authorities` -- the only authority-related permission this codebase defines (there is no separate view-only tier for authorities the way Runtime Policy has `RUNTIME_POLICY_VIEW` distinct from `CREATE`/`EDIT`/`PUBLISH`); already used by this same router's own `review_authority` write endpoint.
- `Permission.AUDIT_EXPORT` for `list_documents` -- an existing, Owner-only, "Organisation & platform administration" permission, chosen specifically because no per-org view permission would honestly describe what this endpoint can actually guarantee (section 5.1).

## 7. Organization-scoping implementation

Both scopable endpoints use column/join filters directly in the service layer, not post-query filtering, and not a caller-suppliable parameter of any kind:

```python
# policy_service.list_policies
select(Policy).where(Policy.organization_id == organization_id).order_by(Policy.version.desc())

# review_service.list_authorities_for_review
select(Authority).join(Principal, Authority.principal_id == Principal.id).where(
    Principal.organization_id == organization_id
)
```

`organization_id` in both cases comes exclusively from `Depends(get_current_organization)` in the router -- there is no request parameter of that name anywhere in this router, so a caller cannot select another organisation by any means.

## 8. Adversarial tests

New file: `server/tests/integration/test_policy_api_security.py`, 10 tests, same real-infrastructure discipline (real ephemeral OPA server, real SQLite-backed database running the actual production models) as every prior milestone:

| Task's scenario | Test | Result |
|---|---|---|
| A. Unauthenticated `/v1/policies` | `test_a_unauthenticated_list_policies_returns_401` | 401 |
| B. Unauthenticated `/v1/policies/documents` | `test_b_unauthenticated_list_documents_returns_401` | 401 |
| C. Unauthenticated `/v1/policies/authorities` | `test_c_unauthenticated_list_authorities_returns_401` | 401 |
| D/E/F. Org A sees only its own policies; never org B's; org B's real UUID never appears in org A's result set | `test_def_org_a_sees_only_its_own_policies_never_org_bs` | Two real policies (via real OPA deploys) in two real orgs, verified mutually exclusive |
| G. Documents cross-tenant protection | `test_g_list_documents_has_no_per_organization_isolation_a_known_limitation` | Proves the disclosed limitation in code, not just prose (section 5.1) |
| H. Org A cannot retrieve org B's authorities | `test_h_org_a_cannot_see_org_bs_authorities` | Two real orgs' authorities, verified mutually exclusive |
| (related) Duplicate-flag cross-check correctness | `test_h_duplicate_flag_still_works_within_the_same_organization` | Confirms the new org-scoping on the cross-check didn't break real intra-org duplicate detection |
| I. Insufficient permission | `test_i_list_policies_denied_without_runtime_policy_view` (REVIEWER), `test_i_list_documents_denied_without_audit_export` (AGENT_ADMIN), `test_i_list_authorities_denied_without_authority_review` (AUDITOR) | 403 in all three cases |
| J/K. Historical binding and policy lifecycle remain functional | Full suite re-run (below) | 427/427, including all Historical Policy Binding and Phase 2B tests unmodified |

All 10 new tests pass. A design correction made while writing tests, disclosed rather than hidden: the task's suggested "duplicate-flag cross-tenant leak" scenario (F/H-adjacent) was found, on direct analysis, to be **not actually independently exploitable** -- `_compute_flags`'s duplicate match is keyed on `principal_id` equality, and a real `Principal` row always belongs to exactly one organisation, so two different organisations' authorities can never share a `principal_id` in the first place. The `all_approved` cross-check was still scoped by organisation anyway, as a correctness/defense-in-depth improvement consistent with "every policy query must be organisation-scoped," and the test was rewritten to verify the more meaningful, real regression risk: that intra-organisation duplicate detection still works after the scoping change.

Full backend suite: **427 passed** (417 pre-existing + 10 new), rerun fresh. SDK suite: **68 passed**. Frontend build: **passed** (no frontend files changed this milestone). `git diff --check`: clean.

## 9. Historical binding verification

No code in `decision_explanation_service.py`, `runtime_policy_service.py`, or the `Policy`/`RuntimePolicyRecord` models was touched by this milestone. Verified, not assumed: the full `test_historical_policy_binding.py` and `test_decision_explanation.py` suites (part of the 427-test full run above) passed unmodified, including `test_explanation_survives_two_subsequent_redeploys` (the strongest existing proof that a decision's explanation never reflects a later policy version). `Policy.bundle_manifest`, `Decision.policy_id`, and every other Historical Policy Binding field remain reachable only through the already-organisation-scoped `GET /v1/decisions/{id}/explanation` and `.../policy-binding` endpoints (re-confirmed by direct code read this milestone, unchanged since Milestone 10/11) -- this milestone's fix does not add, remove, or alter any path to that data.

## 10. Production before/after evidence

Legitimate production credentials were available this session (same as Milestone 11). **Before deploying**, the vulnerability was reproduced live, not assumed still present:

```
GET https://api.aisecurewatch.com/v1/policies  (no credential)
-> 200 [{"policy_id":"ebbba3d8-...","version":1,"status":"active","bundle_hash":"sha256:ebf8ec...", ...}]
```

A real, active production Policy row, fully disclosed, unauthenticated.

**After deploying** commit `04b2817` (image `prod-04b2817`, container app revision `--0000009`, confirmed `Healthy` at 100% traffic):

| Check | Result |
|---|---|
| `GET /v1/policies`, unauthenticated | `401 authentication_required` (was `200` with real data) |
| `GET /v1/policies/documents`, unauthenticated | `401` |
| `GET /v1/policies/authorities`, unauthenticated | `401` |
| `GET /v1/policies`, authenticated as the organisation that owns the real policy | `200`, the same real policy row returned -- legitimate access preserved |
| `GET /v1/policies`, authenticated as a **different** real organisation | `200`, **empty list** -- not the first organisation's policy. Direct, live proof of cross-tenant isolation, not an inference. |

No new production data was created; both organisations and the one real policy record used above already existed from prior milestones' own verification activity.

**PRODUCTION VERIFICATION: LIVE, CREDENTIALED, VERIFIED.**

## 11. Remaining security findings

- **`GET /v1/policies/documents`'s lack of per-organisation isolation** (section 5.1) -- **REQUIRES APPROVAL** if ever needed; would require a schema change out of this milestone's scope. Currently mitigated by permission alone (Owner-only) and by the confirmed fact that zero documents exist in production.
- The post-fix targeted sweep (policies.py, policy service layer, `Policy`, `RuntimePolicyRecord`, documents, authorities, policy deployment, historical policy binding, decision explanation, plus a full `@router.get/post/put/patch/delete` inventory across every router file) found **no new CRITICAL or HIGH finding**. Every router file present in `app/routers/` was accounted for against the list already audited across Milestones 10-11; none was missed.
- Carried forward, unchanged, from Milestone 11: the `evidence_service.verify_chain` SQLite self-comparison test artifact (out of scope, not a security issue) and the broader role-visibility questions below.

## 12. Role-model questions

No role's permissions were changed. Read directly from `domain/rbac/permissions.py`:

| Role | View policies | Create | Modify | Deploy | Retire |
|---|---|---|---|---|---|
| OWNER | Yes | Yes | Yes | Yes | Yes |
| GOVERNANCE_ADMIN ("ADMIN") | Yes | Yes | Yes | Yes | Yes |
| AGENT_ADMIN | No | No | No | No | No |
| REVIEWER | No | No | No | No | No |
| AUDITOR | Yes | No | No | No | No |
| EXECUTIVE | No | No | No | No | No |

("Deploy" and "Retire" are both gated by `Permission.RUNTIME_POLICY_PUBLISH` in `runtime_policies.py`/`runtime_policy_lifecycle.py`, confirmed in this milestone's sweep, not re-litigated here.)

**Related to, and not a new instance of, Milestone 11's already-flagged `REVIEWER` ambiguity**: `REVIEWER` holds `AUTHORITY_REVIEW` and can approve/promote an AI-extracted Authority candidate into a *draft* Runtime Policy, but cannot see that resulting policy afterward (`RUNTIME_POLICY_VIEW` is absent). Whether `REVIEWER` should also see the runtime-policy outcome of its own review action is the same underlying "what is Reviewer actually for" question Milestone 11 already raised about Decision visibility -- noted here as the same open question, not a second, independent one. **ROLE MODEL CHANGE -- REQUIRES APPROVAL**, not decided or implemented.

## 13. Enterprise Knowledge status

**Enterprise Knowledge remains NOT STARTED.** No change was made to Enterprise Knowledge architecture, external fact resolution, any knowledge store, or deterministic evaluation semantics. This milestone touched only `app/routers/policies.py`, `app/services/policy_service.py`, and `app/services/review_service.py`.

## 14. Final completion verdict

| Requirement | Status |
|---|---|
| All three vulnerable endpoints require authentication | **FIXED, LIVE-VERIFIED** |
| Appropriate permission enforced on each | **FIXED, TEST-VERIFIED** (401/403 boundary confirmed by test for all three; live verification confirmed the 401 boundary specifically) |
| Every policy query organisation-scoped | **FIXED, LIVE-VERIFIED** for `list_policies` (`Policy.organization_id`); **FIXED, TEST-VERIFIED ONLY** for `list_authorities` (no second real production Authority record existed to prove live; the join-based scoping is proven by real, direct integration tests instead) |
| Caller cannot select another organisation | **FIXED, LIVE-VERIFIED** -- no `organization_id` parameter exists in the request for any of the three endpoints |
| Cross-tenant metadata enumeration blocked | **FIXED, LIVE-VERIFIED** (the empty-list-for-a-different-org proof in section 10) |
| Policy documents isolated | **REQUIRES APPROVAL** -- structurally not possible without a schema change; disclosed, not claimed as solved (section 5.1) |
| Policy authorities isolated | **FIXED, TEST-VERIFIED ONLY** |
| Adversarial tests pass | **VERIFIED** (10/10) |
| Full backend suite passes | **VERIFIED** (427/427) |
| SDK suite passes | **VERIFIED** (68/68) |
| Frontend builds | **VERIFIED** (unchanged this milestone) |
| Historical policy binding intact | **VERIFIED** (full suite, unmodified, all passing) |
| No new CRITICAL/HIGH finding within the audited policy boundary | **MET** -- post-fix sweep found none |

**MILESTONE 12: PASS.** Live, credentialed before/after verification was performed and is documented in section 10, as required. The one open item (`documents`' structural lack of organisation isolation) is disclosed as `REQUIRES APPROVAL`, not silently accepted as solved -- it does not change the overall verdict, since the actual CRITICAL defect (unauthenticated access) is fully closed and live-verified for all three endpoints.

Per instruction, this document does not authorize proceeding into Enterprise Knowledge or any further milestone. Awaiting explicit approval.
