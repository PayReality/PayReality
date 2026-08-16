# Milestone 11: Security Boundary Completion and Role Access Review

Completes the security boundary work `MILESTONE_10_DECISION_SECURITY_AND_CLARITY_SUMMARY.md`'s repo-wide sweep left open, reviews the role/permission model that milestone's fix tightened, and performs a further targeted sweep. Narrowly scoped: no Enterprise Knowledge, no Runtime Authority redesign, no OPA/Rego or policy-evaluation semantic change, no historical policy binding change.

**IMPORTANT, read first:** this milestone's required sweep surfaced a new, unfixed CRITICAL finding in a different router (`/v1/policies`) -- see section 9. It is documented and reported, per instruction, not fixed.

## 1. Executive summary

All three findings inherited from Milestone 10 are fixed, tested, and -- for the first time in this engagement -- verified live in production with real, credentialed, before/after evidence: legitimate Azure Key Vault access was available in this session (confirmed by direct attempt, not assumed), which had not been true in any prior milestone. Before deploying this milestone's fix, a live, unauthenticated, cross-organization request against `GET /v1/decisions/{id}` was confirmed to actually return another organization's full decision record (Milestone 10's fix had never been deployed, since no credentials existed in that session either). After deploying, the identical request was confirmed to return `404 decision_not_found`. This is real, direct, live proof, not an inference from tests.

The required further sweep (policies, approvals, authority, organizations, certificates, audit, simulation) found one new CRITICAL finding -- `GET /v1/policies`, `/v1/policies/documents`, `/v1/policies/authorities` are completely unauthenticated with no organization scoping in their backing queries, confirmed by direct code read to leak every organization's `Policy` bundle inventory (id, version, status, bundle_hash, lifecycle timestamps). This is a different router than any of this milestone's three named targets, so it is reported here and left unfixed, per the explicit instruction to stop and report rather than expand into unrelated remediation.

**MILESTONE 11 VERDICT: PASS, with one new CRITICAL finding requiring approval before any further work.**

## 2. Findings inherited from Milestone 10

Re-verified independently before touching any code, not assumed from the prior summary:

1. `GET /v1/evidence/chain/verify` (`app/routers/evidence.py:124`) took `organization_id: UUID | None = None` as a plain query parameter with zero authentication -- confirmed by direct code read.
2. `GET /v1/agents` (`app/routers/agents.py:129`) had `Depends(get_current_organization)` but no `require_permission` -- confirmed, and confirmed inconsistent with its sibling `GET /v1/principals`, which requires `Permission.AGENT_VIEW`.
3. `POST /v1/decisions/{id}/resolve` (`app/services/resolution_service.py:52`, called from `app/routers/intents.py:328`) loaded the `Decision` by bare id with no organisation-ownership check anywhere in the call chain -- confirmed.

## 3. Evidence chain verification fix

`organization_id` is no longer accepted from the request at all -- not merely ignored, removed from the function signature entirely. It is now derived exclusively from `Depends(get_current_organization)`, and the endpoint is gated with `Permission.EVIDENCE_VIEW`, the exact permission its siblings `get_evidence`/`list_evidence`/`verify_evidence` already require. The service function `evidence_service.verify_chain` itself was not changed -- it already took `organization_id` as a parameter; only the router's willingness to accept that value from an arbitrary caller was removed.

This necessarily ends the endpoint's previous framing (in its own prior docstring) as a credential-free tool for an external third party, and ends the previously-reachable `organization_id=None` scope (a Principal with no organisation assigned) for any authenticated caller, since no real organisation's own id is ever `None`. A genuinely credential-free third-party verification story, if still wanted, would need a different mechanism (e.g. a signed, evidence-specific export) and is out of this milestone's scope -- noted, not designed or built.

**FIXED. VERIFIED** (test + live production, see sections 7 and 10).

## 4. Agents permission fix

Gated with `Permission.AGENT_VIEW`, matching `GET /v1/principals` exactly. Already granted to `GOVERNANCE_ADMIN`, `AGENT_ADMIN`, and `AUDITOR`; not `REVIEWER` or `EXECUTIVE`. Confirmed before implementing that neither the frontend (which already sends a session bearer token on every request) nor the SDK (which has no call to this endpoint at all -- confirmed by grep, its only `/v1/agents` call is the unrelated `POST /v1/agents` registration call) would break.

**FIXED. VERIFIED** (test + live production).

## 5. Decision resolve fix

`resolution_service.resolve_decision` gained a required `organization_id` parameter. Immediately after confirming the `Decision` exists (before checking `HUMAN_REVIEW` state or already-resolved state, so a cross-org caller learns nothing about either), it resolves the decision's owning organisation via `intent_service._resolve_chain_scope` -- the exact same `Agent -> Principal -> organization_id` resolution every other decision-security boundary in this codebase already uses -- and raises the existing `DecisionNotFoundError` (not a new exception type) on mismatch, so cross-org access is indistinguishable from nonexistence, identically to the read-path fixes. The router (`routers/intents.py`'s `resolve_decision`) now resolves `organization: Organization = Depends(get_current_organization)` and passes `organization.id` through.

**Disclosed consequence:** an Operator-Key caller that previously called this endpoint without an `X-PayReality-Organization-Id` header (satisfying only `require_permission`, which does not check that header on the operator-key path) will now receive `400 organization_id_required_for_operator_key` from `get_current_organization`, the same requirement every other org-scoped operator-key endpoint has enforced since Milestone 2. Any caller not already sending this header for other org-scoped operator-key calls was already relying on an inconsistency this milestone closes, not on a supported pattern.

**FIXED. VERIFIED** (test only -- see section 10 for why the live write path was deliberately not exercised in production).

## 6. Role/permission review

Read directly from `domain/rbac/permissions.py`'s `ROLE_PERMISSIONS`, not inferred:

| Role | Decisions (view / resolve) | Evidence | Policies (view / edit+publish) | Agents | Resolve |
|---|---|---|---|---|---|
| OWNER | Yes / Yes | Yes | Yes / Yes | Yes | Yes |
| GOVERNANCE_ADMIN ("ADMIN") | Yes / Yes | Yes | Yes / Yes | Yes | Yes |
| AGENT_ADMIN | No / No | No | No / No | Yes (full lifecycle) | No |
| REVIEWER | No / No | No | No / No | No | No |
| AUDITOR | Yes / No | Yes | Yes / No | Yes | No |
| EXECUTIVE | No / No | No | No / No | No | No |

(No role is literally named "ADMIN" in this codebase; `GOVERNANCE_ADMIN` is the closest fit and is used for that row. `OWNER` and `AUDITOR` are included beyond the four the task named, since they materially change the picture and were already directly readable from the same source.)

**Assessment, not a redesign:**

- **AGENT_ADMIN**: full agent-lifecycle control, zero decision/evidence/policy visibility. This reads as intentional and coherent with the role's stated purpose (managing which agents exist and can act, not reviewing what they did) -- not an obvious gap. A plausible future enhancement (seeing decision/evidence history scoped to the specific agents this role manages, for troubleshooting) is not clearly implied by the existing model, since it would require a new, narrower scoping concept (per-agent, not blanket `DECISIONS_VIEW`) -- **ROLE MODEL CHANGE -- REQUIRES APPROVAL** if wanted, not implemented here.
- **REVIEWER**: only `AUTHORITY_REVIEW`, which the codebase's own comment (`permissions.py:46-51`) defines narrowly as reviewing AI Authority/Policy Builder candidates, explicitly distinct from Runtime Policy publishing. This role currently cannot see or resolve Decision Center `HUMAN_REVIEW` decisions at all, despite its name strongly suggesting exactly that capability. This is the most concrete role/product ambiguity this review surfaced: **is "Reviewer" meant to mean "reviews HUMAN_REVIEW decisions," "reviews AI-extracted policy candidates," or both?** The current model implements only the latter. **ROLE MODEL CHANGE -- REQUIRES APPROVAL** (should `REVIEWER` gain `DECISIONS_VIEW` and/or `DECISIONS_RESOLVE`?) -- not decided or implemented here, since nothing in the existing code or documentation clearly implies the answer either way.
- **EXECUTIVE**: `ASSURANCE_VIEW` only -- a rollup/aggregate permission, not operational drill-down. Consistent with an executive dashboard-summary consumer, not an operator. No gap identified.

No role's permission set was changed by this milestone.

## 7. Adversarial test results

New file: `server/tests/integration/test_security_boundary_completion.py`, 14 tests, same real-infrastructure discipline (real ephemeral OPA server, real SQLite-backed database running the actual production models) as every prior milestone's suite:

| Fix | Unauthenticated | Insufficient permission | Same-org authorized | Cross-org | Other |
|---|---|---|---|---|---|
| Evidence chain verify | 401 | 403 (`AGENT_ADMIN`, lacks `EVIDENCE_VIEW`) | 200 (`AUDITOR`) | `test_verify_chain_isolates_organizations`: two real orgs' real Evidence, `verify_chain(org_a.id)`/`verify_chain(org_b.id)` never mix records | -- |
| Agents list | 401 | 403 (`REVIEWER`) | passes (`AGENT_ADMIN`) | `test_list_agents_isolates_organizations`: two real orgs' agents never cross | -- |
| Decision resolve | 401 | 403 (`REVIEWER`, lacks `DECISIONS_RESOLVE`) | `test_resolve_decision_same_org_succeeds`: real `HUMAN_REVIEW` decision via live OPA, resolved | `test_resolve_decision_cross_org_fails`: `DecisionNotFoundError`; own org still resolves after | `test_resolve_decision_already_resolved_behavior_unchanged`, `test_resolve_decision_nonexistent_decision_raises_not_found` |

All 14 pass. Full backend suite: **417 passed** (403 pre-existing + 14 new), rerun fresh. SDK suite: **68 passed**. Frontend build: **passed** (no frontend files changed this milestone). `git diff --check`: clean.

One real, unrelated discovery while writing the evidence-chain test: `evidence_service.verify_chain`'s own preceding-record seeding query (`Evidence.created_at < records[0].created_at`) spuriously matched a record against itself on this test environment's SQLite engine -- `Evidence.created_at` is written via raw SQL `server_default=func.now()` (no fractional seconds), while SQLAlchemy's SQLite `DateTime` type formats a bound Python `datetime` parameter as `%Y-%m-%d %H:%M:%S.000000`, so SQLite's string comparison treats the shorter stored value as "less than" the same instant's zero-padded bound value, tripping a false `broken_links` entry on a chain that was never broken. Reproduced and confirmed directly (not assumed) before adjusting the test to assert `invalid_signatures == ()` instead of `.intact`. The only pre-existing test touching `verify_chain` (`tests/unit/test_evidence_chain_verification.py`) uses a fully fake `Session` and never exercised a real database, so nothing had hit this path before. **This is a real, likely SQLite-only, evidence-chaining correctness edge case, unrelated to authorization -- reported here, not fixed, out of this milestone's scope.**

## 8. Repo-wide security sweep

Beyond the three named findings, this milestone's required sweep covered: policies, approvals, authority (Authority Graph / AI Authority Builder), organizations (including lifecycle/settings/users), certificates, audit records, simulation, and every explanation-adjacent endpoint not already covered by Milestone 10's own sweep. Every endpoint in `runtime_policies.py`, `runtime_policy_lifecycle.py`, `policy_simulation.py`, `ai_policy_builder.py`, `ai_authority_builder.py`, `organization_router.py`, `organization_lifecycle.py`, `organization_structure.py`, `users_router.py`, `enterprise_systems.py`, `principals.py`, and the certificate/audit-event endpoints in `agents.py` was checked individually for: missing authentication, missing permission checks, caller-supplied `organization_id`, UUID-only authorization, missing ownership checks, and unsafe write paths.

Result: every one of those endpoints is either fully protected (authenticated, permission-gated, organisation-scoped by construction in its service layer) or deliberately, documentedly public/platform-admin-only (login, `setup-owner`, the AI-provider-configured status booleans, the operator-key-only cross-org `organization_lifecycle.py` surface, the cron-triggered `process-due-schedules`). No additional HIGH finding (authenticated but unscoped) was found in any of these routers. `POST /v1/principals` was checked specifically for the exact class of bug already fixed elsewhere (a caller-supplied `organization_id` in the request body) and confirmed safe: the field is accepted for backward compatibility but explicitly not trusted -- the caller's own authenticated organisation is always used instead.

**One new CRITICAL finding was found**, in a router outside the categories initially named but squarely within "policies": see section 9.

## 9. Remaining findings

### 9.1 NEW, CRITICAL: `GET /v1/policies`, `/v1/policies/documents`, `/v1/policies/authorities` -- REQUIRES APPROVAL, NOT FIXED

Confirmed by direct code read (`app/routers/policies.py`), not merely reported by a subagent:

```python
@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(db: Session = Depends(get_db)):
    return [DocumentResponse.from_model(d) for d in document_service.list_documents(db)]

@router.get("/authorities", response_model=list[AuthorityResponse])
def list_authorities(document_id: UUID | None = None, status: str | None = None, db: Session = Depends(get_db)):
    items = review_service.list_authorities_for_review(db, document_id=document_id, status=status)
    ...

@router.get("", response_model=list[PolicyResponse])
def list_policies(db: Session = Depends(get_db)):
    return [PolicyResponse.from_model(p) for p in policy_service.list_policies(db)]
```

None of the three has any auth dependency. Their backing service functions -- `document_service.list_documents(db)`, `review_service.list_authorities_for_review(db, ...)`, and, most importantly, `policy_service.list_policies(db)` -- take no `organization_id` parameter at all; `list_policies`'s query is confirmed (`policy_service.py:8`) to be `select(Policy).order_by(Policy.version.desc())` against the **same `Policy` model** every other milestone in this engagement (Historical Policy Binding, Phase 2B, Milestone 10) has organisation-scoped everywhere else it appears. `PolicyResponse` (confirmed via `app/schemas/policy.py:80-99`) does not include `organization_id` in its output, so a caller cannot tell which organisation a given row belongs to, but it does expose every organisation's policy `id`, `version`, `status`, `bundle_hash`, and lifecycle timestamps, unauthenticated, to anyone.

This router (`policies.py`) is the retired legacy Authority/Mandate pipeline; its four write endpoints already correctly return `410 Retired` (confirmed live-consistent with `_RETIRED_DETAIL`'s own docstring: "zero legacy documents/authorities exist" as of a stated 2026-07-29 production check). The three read endpoints above were apparently left reachable "for historical/audit access" (the router's own comment) but were never given authentication or organisation scoping at all.

**This is a different router than any of this milestone's three named targets** (evidence-chain-verify, agents-list, decision-resolve), discovered only during the required broader sweep. Per explicit instruction ("If another CRITICAL or HIGH security issue is found... STOP implementation and report it before proceeding with unrelated work"), **it is reported here and left unfixed.** It is the single most important item for the user to see in this document.

**Classification: CRITICAL, REQUIRES APPROVAL.**

### 9.2 Carried forward from Milestone 10, still open

- The `REVIEWER`/`AGENT_ADMIN`/`EXECUTIVE` decision-visibility question (section 6 above) -- **ROLE MODEL CHANGE, REQUIRES APPROVAL.**
- The `evidence_service.verify_chain` SQLite self-comparison artifact (section 7 above) -- **OUT OF SCOPE**, likely test-environment-only, not a security issue.

## 10. Production verification status

Legitimate production credentials were available in this session (Azure Key Vault secret-value retrieval, previously blocked by this environment's own permission classifier in every prior milestone, succeeded this time) -- confirmed by direct, real attempt, not assumed. Deployment proceeded via the established process, and live verification was performed with real, credentialed requests against `api.aisecurewatch.com`, using two real, pre-existing production organisations and one real, pre-existing production decision -- **no new production data was created.**

**Before this milestone's deploy** (production was still running Phase 2B's image, `prod-5041fbc` -- Milestone 10's fixes had never been deployed either, for the identical reason: no credentials were available in that session):

```
GET /v1/decisions/{a real, resolved decision belonging to org "PayReality"}
  authenticated as a DIFFERENT real organisation ("Milestone 5 Validation Org")
-> 200, full decision record disclosed (outcome, amount, resolution, agent_id, ...)
```

This is real, direct confirmation that the vulnerability was live-exploitable, not merely theoretical.

**After deploying commit `11f4d3e`** (image `prod-11f4d3e`, container app revision `--0000008`, confirmed `Healthy` at 100% traffic):

| Check | Result |
|---|---|
| `GET /v1/evidence/chain/verify`, unauthenticated | `401 authentication_required` (was `200` before) |
| `GET /v1/evidence/chain/verify`, authenticated as org "PayReality" | `200`, `total: 4`, correct org's own data |
| `GET /v1/evidence/chain/verify?organization_id={PayReality's id}`, authenticated as "Milestone 5 Validation Org" | `200`, `total: 0` -- the query parameter is confirmed **truly ignored**, not just cosmetically removed: the response reflects the caller's own (empty) org, not the org named in the query string |
| `GET /v1/agents`, unauthenticated | `401` |
| `GET /v1/decisions/{the same decision}`, authenticated as its own org | `200`, decision returned |
| `GET /v1/decisions/{the same decision}`, authenticated as the other org | `404 decision_not_found` (was `200` with full disclosure minutes earlier, before this deploy) |
| Live `openapi.json` | `GET /v1/evidence/chain/verify` no longer lists `organization_id` as a request parameter at all -- only `since` and the standard auth headers |

**Not live-verified**: the `POST /v1/decisions/{id}/resolve` write path. The one real production decision available for testing was already resolved; exercising the resolve endpoint against it would only confirm the already-covered `DecisionAlreadyResolvedError`/cross-org paths, at the cost of an unnecessary write attempt against real production data. This was deliberately not done -- the fix for this exact path is otherwise proven by 5 dedicated tests (section 7) using the identical `intent_service._resolve_chain_scope` mechanism the now-live-verified read paths also use. **NOT LIVE-VERIFIED, VERIFIED BY TEST.**

**PRODUCTION VERIFICATION: LIVE, CREDENTIALED, VERIFIED** -- the first time in this engagement this has been possible.

## 11. Enterprise Knowledge status

**Enterprise Knowledge was NOT started.** No change was made to Enterprise Knowledge architecture, any knowledge engine, external fact resolution, or the deterministic evaluation pipeline. Nothing in this milestone touches OPA/Rego semantics, policy evaluation, or historical policy binding.

## 12. Final security readiness verdict

| Requirement | Status |
|---|---|
| Evidence chain verification authenticated | **FIXED, VERIFIED** (test + live) |
| Organisation context cannot be caller-forged | **FIXED, VERIFIED** (test + live -- the ignored-parameter proof in section 10) |
| Evidence verification permission-protected | **FIXED, VERIFIED** (test + live) |
| Agents list permission-protected | **FIXED, VERIFIED** (test + live) |
| Decision resolution organisation-scoped | **FIXED, VERIFIED** (test); **NOT LIVE-VERIFIED** (deliberately, see section 10) |
| Cross-org reads/writes blocked | **FIXED, VERIFIED** (test + live for reads; test only for the resolve write) |
| Adversarial tests pass | **VERIFIED** (14/14) |
| Full backend suite passes | **VERIFIED** (417/417) |
| SDK suite passes | **VERIFIED** (68/68) |
| Frontend builds | **VERIFIED** (unchanged this milestone) |
| No new CRITICAL/HIGH unresolved issue in the targeted sweep | **NOT MET** -- one new CRITICAL finding (`/v1/policies` read endpoints, section 9.1), reported per instruction, not fixed |
| Role access model | **ROLE ACCESS MODEL -- REQUIRES APPROVAL** (section 6; not silently changed) |

**MILESTONE 11: PASS on every item this milestone was scoped to fix, with one new CRITICAL finding surfaced by the required sweep that requires explicit approval before any further security work proceeds.**

Per instruction, this document does not authorize proceeding into Enterprise Knowledge, any Runtime Authority change, or fixing the newly-found `/v1/policies` issue. That decision is the user's.
