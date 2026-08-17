# Milestone 15: RBAC Verification Matrix

## Method (real, not source-inferred)

Every result below came from real HTTP calls against the live production API (`https://api.aisecurewatch.com`),
using real user accounts created for this purpose (a dedicated test organization, "Milestone 15 RBAC
Verification," created via the platform-admin Operator Key, deactivated/cleaned up after testing) and
real session tokens obtained via `POST /v1/auth/login` -- not simulated, not inferred from source, and
not the direct-call-the-checker-function convention this codebase's own test suite otherwise uses. No
browser automation was available (confirmed via a fresh tool check, not assumed), so "UI allowed" below
is determined by reading the actual frontend gating code (`hasPermission(...)` calls, or their absence)
rather than clicking through a real browser session; every "API allowed" column is a genuine live
result. Two cells (marked below) were inconclusive due to the API's own rate limiter (120 requests per
60-second sliding window, `server/app/security.py`) tripping during a dense verification run; they are
disclosed as inconclusive rather than silently filled in with an assumption.

Every result was captured **twice**: once against the pre-Milestone-15 production deployment (to confirm
the real, live bug existed) and once after this milestone's fix was built, deployed, and verified
`Healthy` at 100% traffic (`ca-payreality-api-prod-cus--0000010`, image `prod-a84f77b`). Rows marked
**FIXED THIS MILESTONE** changed between those two runs; every other row was already correct in both.

## Roles actually present in the codebase

`server/app/domain/rbac/permissions.py`: `OWNER`, `GOVERNANCE_ADMIN`, `AGENT_ADMIN`, `REVIEWER`,
`AUDITOR`, `EXECUTIVE` -- all six tested, not a representative subset.

## Matrix

| Role | Action | UI allowed | API allowed (live) | Expected | Result |
|---|---|---|---|---|---|
| Owner | Settings view/manage | Yes | 200 | Allowed (has every permission) | PASS |
| Owner | Agent register/activate/rotate | Yes | 201/404\* | Allowed | PASS |
| Owner | Agent detail/certificates/audit | Yes | 404\* | Allowed | PASS |
| Owner | Policy create/view/publish | Yes | 201/200/404\* | Allowed | PASS |
| Owner | Authority review (AI builder actions) | Yes | 404\* | Allowed | PASS |
| Owner | AI Authority/Policy Builder read views | Yes | 200 | Allowed | PASS |
| Owner | Runtime policy lifecycle dashboard | Yes | 200 | Allowed | PASS |
| Owner | Decisions view/resolve | Yes | 404\*/404\* | Allowed | PASS |
| Owner | Evidence view | Yes | 200 | Allowed | PASS |
| Owner | Assurance/health view | Yes | 200 | Allowed | PASS |
| Owner | User management | Yes | 201 | Allowed | PASS |
| Owner | Audit export (legacy documents) | Yes | 200 | Allowed | PASS |
| Governance Admin | Settings view/manage | No (nav hidden, M15 fix) | 403 | Denied (no `settings.view`) | PASS |
| Governance Admin | Agent register/activate/rotate | No (buttons gated, M14 fix) | 403 | Denied (no `agent.register`/`activate`/`rotate`) | PASS |
| Governance Admin | Agent view (list + detail/certs/audit) | Yes (nav) | 200 / 404\* | Allowed (`agent.view`) | PASS |
| Governance Admin | Policy create/view/publish | Yes | 201 / 200 / 404\* | Allowed (all three granted) | PASS |
| Governance Admin | Authority review (AI builder actions + reads) | Yes | 404\* / 200 | Allowed (`authority.review`) | PASS |
| Governance Admin | Runtime policy lifecycle dashboard | Yes | 200 | Allowed (`runtime_policy.view`) | PASS |
| Governance Admin | Decisions view/resolve | Yes (nav, M15 fix) | 404\* / 404\* | Allowed (both granted) | PASS |
| Governance Admin | Evidence view | Yes | 200 | Allowed | PASS |
| Governance Admin | Assurance/health view | Yes | 200 | Allowed | PASS |
| Governance Admin | User management | No | 403 | Denied (no `users.manage`) | PASS |
| Governance Admin | Audit export (legacy documents) | No | 403 | Denied (Owner-only) | PASS |
| Agent Admin | Settings view/manage | No | 403 | Denied | PASS |
| Agent Admin | Agent register/activate/rotate | Yes | 404\* | Allowed (all granted) | PASS |
| Agent Admin | Agent detail/certificates/audit | Yes | 404\* | Allowed (`agent.view`) | PASS |
| Agent Admin | Policy create/view/publish | No | 403 / **403** / 403 | Denied (none granted) | **PASS -- FIXED THIS MILESTONE** (list view was live `200` before the fix, see below) |
| Agent Admin | Authority review (AI builder actions + reads) | No | 403 / **403** | Denied | **PASS -- FIXED THIS MILESTONE** (reads were live `200` before the fix) |
| Agent Admin | Runtime policy lifecycle dashboard | No (nav hidden, M15 fix) | **403** | Denied | **PASS -- FIXED THIS MILESTONE** (was live `200` before the fix) |
| Agent Admin | Decisions view/resolve | No (nav hidden, M15 fix) | 403 / 403 | Denied | PASS |
| Agent Admin | Evidence view | No (nav hidden, M15 fix) | 403 | Denied | PASS |
| Agent Admin | Assurance/health view | No (nav hidden, M15 fix) | 403 | Denied | PASS |
| Agent Admin | User management | No | 403 | Denied | PASS |
| Agent Admin | Audit export | No | 403 | Denied | PASS |
| Reviewer | Settings view/manage | No | 403 | Denied | PASS |
| Reviewer | Agent register/activate/rotate | No | 403 | Denied | PASS |
| Reviewer | Agent view (list + detail/certs/audit) | No (nav hidden, M15 fix) | 403 / **403** | Denied (no `agent.view`) | **PASS -- FIXED THIS MILESTONE** (detail/certs/audit were live `200`, ungated, before the fix) |
| Reviewer | Policy create/view/publish | No | 403 / **403** / 403 | Denied (none granted) | **PASS -- FIXED THIS MILESTONE** (list view was live `200` before the fix) |
| Reviewer | Authority review (AI builder actions + reads) | Yes | 404\* / 200 | Allowed (`authority.review`, the role's sole permission) | PASS |
| Reviewer | Runtime policy lifecycle dashboard | No (nav hidden, M15 fix) | 403 | Denied (no `runtime_policy.view`) | PASS |
| Reviewer | Decisions view/resolve | No (nav hidden, M15 fix) | 403 / 403 | Denied | PASS |
| Reviewer | Evidence view | No (nav hidden, M15 fix) | 403 | Denied | PASS |
| Reviewer | Assurance/health view | No (nav hidden, M15 fix) | 403 | Denied | PASS |
| Reviewer | User management | No | 403 | Denied | PASS |
| Reviewer | Audit export | No | 403 | Denied | PASS |
| Auditor | Settings view/manage | No | 403 | Denied | PASS |
| Auditor | Agent register/activate/rotate | No | 403 | Denied | PASS |
| Auditor | Agent view (list + detail/certs/audit) | Yes | 200 / 404\* | Allowed (`agent.view`) | PASS |
| Auditor | Policy create/view/publish | No / Yes / No | 403 / 200 / 403 | View allowed, create/publish denied (exactly `runtime_policy.view`) | PASS |
| Auditor | Authority review (AI builder actions + reads) | No | 403 / **403** | Denied (no `authority.review`) | **PASS -- FIXED THIS MILESTONE** (reads were live `200` before the fix) |
| Auditor | AI Policy Builder candidates / lifecycle dashboard | No | **INCONCLUSIVE (429, rate-limited)** | Denied / Allowed respectively | Not independently confirmed this run -- same permission (`authority.review` denied, `runtime_policy.view` granted) already confirmed via the sibling checks above; disclosed as unconfirmed for these two exact endpoints rather than assumed |
| Auditor | Decisions view/resolve | Yes / No | 404\* / 403 | View allowed, resolve denied | PASS |
| Auditor | Evidence view | Yes | 200 | Allowed | PASS |
| Auditor | Assurance/health view | Yes | 200 | Allowed | PASS |
| Auditor | User management | No | 403 | Denied | PASS |
| Auditor | Audit export | No | 403 | Denied (Owner-only) | PASS |
| Executive | Settings/Agents/Policies/Authority-review/Decisions/Evidence/Users/Audit-export | No (nav hidden, M15 fix) | 403 across every one tested | Denied (role's only permission is `assurance.view`) | PASS |
| Executive | Assurance/health view | Yes | 200 | Allowed | PASS |

\* `404` in the API-allowed column means the request reached the resource-lookup code (permission check
passed) and failed only because the test used a syntactically valid but non-existent UUID (no real
agent/policy/decision was created for every check) -- this is a deliberate, valid technique: FastAPI
resolves the `require_permission` dependency before the route body runs, so `404` here is proof of
**granted** access, not evidence of anything about permissions. A `403` always means the permission
check itself failed. A small number of real resources (one org, one draft policy per allowed role) were
also created live during this verification, confirming the pattern holds for genuinely existing
resources too, not only the 404-after-permission-pass technique.

## Boundary conditions (also real, live-tested)

| Scenario | Result | Expected | Status |
|---|---|---|---|
| No credential at all | `401` | Rejected | PASS |
| Garbage/invalid bearer token | `401` | Rejected | PASS |
| Operator Key + `X-PayReality-Organization-Id`, org-scoped endpoint | `200` | Allowed (Operator Key is a deliberate platform-admin-equivalent bypass, by design) | PASS |
| A real Owner **session token** (no Operator Key) against a platform-admin-only lifecycle endpoint (`POST /v1/organizations/{id}/deactivate`) | `422` (FastAPI's required-header validation on the missing `X-PayReality-Operator-Key` header) | Rejected -- confirms a session token, even an Owner's, cannot bypass into platform-admin-only endpoints | PASS (the `422` status code is a minor API-consistency wart worth a future cleanup to a `401`, but the actual security property -- rejection -- holds) |
| A brand-new organization's own agent list, immediately after creation | `200`, empty list | Confirms tenant isolation baseline: a new org starts with zero visibility into any other org's data | PASS |

## What this confirms, live, not by inference

The real finding of this milestone: **before the fix**, `GET /v1/runtime-policies` (list/detail/
versions/diff) plus its dry-run action, `GET /v1/agents/{id}` and its certificate/audit sub-resources,
and most of the AI Authority Builder's and AI Policy Builder's read endpoints returned `200` for **every
role tested**, including ones holding none of the relevant permission (Agent Admin, Reviewer, Auditor,
and by the same code pattern, Executive). **After the fix**, every one of those same live calls, with
the same real user accounts and session tokens, now returns `403` for every role that should not have
access, and continues to succeed for every role that should. This is a genuine before/after live
comparison, not a single post-fix snapshot asserted to be correct.
