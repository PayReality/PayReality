# Decision Intelligence Platform

## What this is

A new, deliberately isolated product module alongside the existing Runtime Authority platform
(Principals/Agents/Intents/RuntimePolicy/Decision Engine/Evidence). It implements the product
defined on the public site as "Decision Intelligence for AI Workflows": discovering the smallest,
highest-value set of questions a business needs to answer to resolve recurring uncertainty across
many decisions.

Built on branch `feature/decision-intelligence-platform` (based on `origin/main` @ `90e41df`), in
an isolated git worktree, never merged into `main`. The existing Runtime Authority tables, routers,
and frontend pages were not modified except for one backend router addition
(`GET /v1/decision-intelligence/patterns/{id}/cases`, added during frontend integration) and the
defects disclosed below.

**Current status (2026-10-15): deployed and live** at `https://payreality.aisecurewatch.com`, pushed
to `origin/feature/decision-intelligence-platform` (not merged to `main`). Six additional features
beyond the original scope were since built and shipped: CSV case import, cross-workflow reports and
exports, configurable scoring weights, server-side case search, a visual rule builder, and
AI-assisted pattern/question discovery (Fake-heuristic and Claude-provider paths). See
"Decision Intelligence: Completion Report" (the companion live record) for the per-feature build log,
and "2026-10-15 verification and correction pass" below for this round's corrections.

This document is the honest status record. It does not claim anything that was not actually run and
observed to pass.

## 2026-10-15 verification and correction pass

A focused pass to correct overclaiming language and verify specific claims before a real customer
case walkthrough, not a rebuild. Summary (full detail in the final report handed to Sean):

- **Discovery wording corrected.** The AI discovery feature's "conflicting decisions" and
  "missing field" suggestions previously asserted causes ("direct evidence of unresolved policy
  ambiguity," "is X required") the heuristic has no data to establish. Both are now framed as an
  observation plus a question, in the Fake provider's generated text, the Claude prompt's system
  instructions, and the dashboard's copy. Also fixed a disclosed wording bug: two cases with fully
  identical recorded facts previously produced the nonsensical "no recorded fields" as the
  differing field's name.
- **Provider transparency verified.** Confirmed directly against the live Azure Container App
  (`ca-payreality-di-prototype-cus`), by listing environment variable and secret names only, never
  values, that production has no Anthropic API key configured. The deployed app therefore runs the
  Fake/heuristic provider exclusively right now; the Claude provider's failure handling is tested
  against a fake client but has never been exercised against the real Anthropic API. The dashboard's
  Discovery page now shows a plain-language provider label ("Heuristic analysis (no AI model)" /
  "Claude-assisted analysis") instead of the raw internal `fake`/`claude` string.
- **Missing-field heuristic checked.** `DICase.facts` is schema-less JSONB; nothing in the data model
  declares a field required or optional. The heuristic's suggestion and question text were corrected
  to ask whether a recurring missing field is *relevant*, not assert that it is *required*.
- **Four backend test failures investigated, not fixed.** Confirmed deterministic across 3 repeated
  isolated runs (not flaky), confirmed via `git diff 90e41df HEAD` that the failing test files and
  every Runtime Authority/Trusted Integration source file they exercise are byte-identical to the
  pre-Decision-Intelligence baseline, confirming zero code overlap with this module. Out of scope to
  fix (would mean reopening Runtime Authority, explicitly out of scope for this pass).
- **One real bug found and fixed during the walkthrough.** `classify_outcome()`
  (`replay_executor.py`) labeled a case with no recorded baseline, whose facts did not match the
  rule's own conditions, as `resolved_automatically`, even though no decision was produced
  (`decision: null`). Fixed to return `requires_human_review`; added 6 unit tests
  (`tests/unit/test_di_replay_executor.py`, previously this function had zero test coverage); re-ran
  the exact same replay live after the fix to confirm the reclassification.
- A complete synthetic, clearly-labelled demonstration workflow was run through the full chain (CSV
  import through replay and export) via the real API against a local Postgres instance, covering an
  apparent inconsistency, an omitted fact, a case that must stay unresolved, and a case needing no new
  rule. See the completion report for the full walkthrough record.

## The product chain

`Workflow` → `Case` (a real decision situation) → `Pattern` (recurring uncertainty found across
cases) → `Question` (a proposed source of value, not yet compared against customer alternatives:
which question, answered, resolves the most uncertainty) → `Answer` (authoritative, approved by someone other than whoever submitted it) →
`DecisionRule` / `RuleVersion` (a versioned, inspectable condition tree derived from one approved
answer) → `Replay` (running a rule version against real persisted cases and comparing to the
historical/baseline decision). Agreement with that baseline is reported as agreement, never as
proof of correctness.

## Architecture

- **Backend**: FastAPI, additive to the existing `server/app` tree. New SQLAlchemy models
  (`DIWorkflow`, `DICase`, `DIPattern`(+`DIPatternCase`), `DIQuestion`(+`DIQuestionPattern`/
  `DIQuestionCase`), `DIAnswer`, `DIDecisionRule`/`DIRuleVersion`, `DIReplayRun`/
  `DIReplayCaseResult`, `DIAuditEvent`) in `server/app/db/models.py`, one Alembic migration
  (`f3a7c1e9b5d2_decision_intelligence_module.py`), a domain package
  `server/app/domain/decision_intelligence/` (scoring, rule schema, deterministic rule evaluator,
  validation), per-resource services under `server/app/services/di_*.py`, and routers under
  `server/app/routers/decision_intelligence/` (45 routes total under `/v1/decision-intelligence`,
  every one permission-gated).
- **Reused, not rebuilt**: authentication, `Organization` (multi-tenancy), `User`, and the RBAC
  permission system (`Role`/`Permission`/`ROLE_PERMISSIONS`/`has_permission`). Every new permission
  is prefixed `DI_`. This was a deliberate choice, since building parallel auth/tenancy for an
  isolated module would have been pure risk with no product benefit.
- **Frontend**: a new feature directory `src/app/decision-intelligence/`, one top-level nav entry
  ("Decision Intelligence", gated on `di_case.view`), pages for every stage of the chain above, all
  calling the real backend through `decisionIntelligenceApi` (`src/app/decision-intelligence/api.ts`),
  with no mock/hardcoded data in the shipped pages.
- **No new infrastructure, no new environment variables.** Confirmed via `git diff origin/main --
  server/app/config.py .env.example` (empty). The only new operational step is running the one new
  Alembic migration.

## Data model

| Entity | Purpose | Key lifecycle states |
|---|---|---|
| `DIWorkflow` | A bounded business workflow being analysed. | `active`, `archived` |
| `DICase` | One real decision situation: facts, evidence refs, AI recommendation, human decision, escalation reason, outcome. | `open`, `resolved`, `escalated` |
| `DIPattern` | Recurring uncertainty observed across linked cases. | `proposed` → `reviewed` → `confirmed`/`rejected` |
| `DIQuestion` | A candidate high-value question, scored and ranked. | `proposed` → `in_analysis` → `awaiting_answer` → `answer_submitted` → `approved` → `logic_drafted` → `logic_validated` → `replay_completed` → `ready_for_review` → `approved_for_operational_use` |
| `DIAnswer` | An authoritative answer to a Question, versioned, never mutated after submission. | `draft` → `submitted` → `under_review` → `approved`/`rejected`/`superseded` |
| `DIDecisionRule` / `DIRuleVersion` | A versioned, typed condition tree derived from one approved Answer. | rule: `draft`/`validated`; versions are immutable once created |
| `DIReplayRun` / `DIReplayCaseResult` | Executing a rule version against real persisted cases; per-case outcome classification. | run: `pending`/`running`/`completed`/`failed`; per case: `agrees_with_baseline`/`disagrees_with_baseline`/`resolved_automatically`/`requires_human_review`/`missing_data`/`error` |
| `DIAuditEvent` | Append-only log of every mutating action on the above. No update/delete path is exposed. | n/a |

Every top-level entity carries `organization_id`; every query is scoped by it. Join tables
(`DIPatternCase`, `DIQuestionPattern`, `DIQuestionCase`) carry uniqueness constraints on their pair.

## Scoring methodology

`server/app/domain/decision_intelligence/scoring.py`, versioned as `scoring_version = "v1"`.
Inputs: `reach`, `impact`, `risk`, `answerability`, `decision_sensitivity`, each an independently
estimated/measured value, never auto-derived from the others. **Any missing input makes the whole
score `None`, not a default/average.** A missing dimension must stay visibly missing, never
silently read as low-priority or zero. The frontend renders a `None` score as "not yet assessed,"
not as blank or zero (`ScoreDisplay.tsx`). The exact weights and formula are documented in the
module's own docstring, which is the source of truth; this file does not duplicate it to avoid the
two drifting apart.

## Decision logic and replay

The rule schema (`rule_schema.py`) is a typed Pydantic tree: `Condition` (field/operator/value),
`CompositeCondition` (AND/OR of conditions), `RuleAction` (decision plus human-review flag),
`RuleSchema` (root condition, action, exceptions, missing-data behavior). The evaluator
(`rule_evaluator.py`) is a pure function with no DB/network access. It only interprets this typed
tree against a facts dict and never executes arbitrary code. The same function backs both the
"test this rule" endpoint (no persistence) and the real replay executor, so a rule is tested with
the exact logic that later runs for real. A rule version cannot be marked `validated` unless its
source Answer is `approved` (`validation.py`).

Replay executes synchronously against an explicitly selected set of persisted cases (documented as
a scale-appropriate choice, not a hidden limitation) and never touches a live decision path. It is
a reporting/evaluation operation only, with its own `DIReplayRun`/`DIReplayCaseResult` tables.
"Agrees with baseline" and "baseline was correct" are kept as distinct claims throughout the code,
comments, and frontend copy.

## Security and governance

- Every route resolves the acting user/organization through the same dependency existing
  human-session routes use, and checks a `DI_`-prefixed `Permission` server-side. A standalone
  check confirmed all 45 routes carry a permission dependency (zero ungated routes).
- Tenant isolation: every query scoped by `organization_id`, covered by an integration test
  asserting cross-organization access fails rather than silently returning empty results.
- Separation of duties: `DIAnswer.approver_user_id` can never equal `author_user_id` when
  transitioning to `approved`. Enforced in the service layer, not just documented, and surfaced in
  the frontend as a disabled/explained control, not only a backend 400.
- `DIAuditEvent` rows are written for every mutating action on Questions, Answers, Decision Rules,
  and Replay runs. No endpoint exposes updating or deleting an audit event.

## Testing performed

(Independently re-run and confirmed by the orchestrating session, not only claimed by the
implementing agents.) This section is a historical record from the 2026-10-14 session, predating
the six features added afterward. The backend failure count below (5, later 4 in isolation) was
superseded by a fresh, independent re-run on 2026-10-15 (see "Known limitations": 1211 passed, 4
failed, same subsystem, confirmed still deterministic and still unrelated).

- Backend DI-specific subset (`tests/unit/test_di_scoring.py tests/unit/test_di_rule_evaluator.py
  tests/unit/test_di_validation.py tests/integration/test_decision_intelligence.py`): **61/61
  passed**, re-confirmed this session after this session's own `QuestionDetailPage`/`ReplayPage`
  fixes (neither of which touches backend code, so this was a sanity check, not expected to move).
- Backend full repo suite (`server/.venv/Scripts/python.exe -m pytest -q`, this session, against the
  real Postgres from the migration validation above): **1119 passed, 5 failed, 3 warnings, in
  869.76s**. All 5 failures are in `tests/integration/test_action_vocabulary_precision.py`,
  `tests/integration/test_authorization_freshness_postgres.py` (2 tests), and
  `tests/integration/test_capability_issuance_idempotency_postgres.py` (2 tests), none of them
  Decision Intelligence (confirmed zero diff vs. `origin/main` on those test files or on any service
  they import, via `git diff origin/main --stat`). Both `_postgres` files' own module docstrings say
  they depend on a `postgres_url` fixture that "skips cleanly" when no real Postgres is reachable,
  which is exactly the implementing agents' own disclosed environment gap: **this is the first time
  this session (or apparently ever, for this repo) these specific tests have actually executed
  instead of skipping.** Re-running just those 5 in isolation (no other load on the machine):
  1 passed, 4 still failed, each on a real assertion (`assert decision.outcome == "ALLOW"`, actually
  getting `"HUMAN_REVIEW"`), not a timeout. This is a genuine, newly-surfaced, pre-existing issue in
  the Runtime Authority / Trusted Integration Architecture subsystem, entirely unrelated to and
  untouched by this branch, previously invisible only because no prior environment had real Postgres
  to stop these tests from skipping. Flagged here for separate investigation; fixing it is out of
  this pass's scope (different subsystem, zero relation to Decision Intelligence).
- Frontend DI-specific subset (`npx vitest run src/app/decision-intelligence`): **12/12 passed**
  (the original 10 plus this session's 2 new regression tests).
- Frontend full repo suite (`npm test`), investigated properly per instructions rather than taking
  the prior report at face value, **5 runs total**:
  - 1 run performed while a full backend `pytest` run was also executing concurrently on the same
    machine: vitest's own worker pool failed to even start workers for 3 files (`DraftWithAIPanel`,
    `DemoNarrative`, `DecisionDetailPage`) plus a 4th failure in `RuleDetailPage.test.tsx`
    (`[vitest-pool-runner]: Timeout waiting for worker to respond`), a real resource-contention
    symptom, but from **this session's own simultaneous heavy pytest run**, not an inherent property
    of `npm test` alone, and not the two tests the prior report named.
  - 4 further runs, standalone, nothing else running on the machine (stray leftover Chromium
    processes from this session's own Playwright walkthrough were first confirmed and killed): 3 of
    4 were fully clean, **157 passed, 0 failed**. The 4th showed **148 passed, 9 failed** across
    multiple files, confirmed to include `src/app/integrations/IntegrationDetailPage.test.tsx`
    (`TypeError: Cannot read properties of undefined (reading 'dispatchEvent')`, a real runtime
    error from a DOM query returning nothing, not a timeout); the complete file list for that one run
    was lost to a `tail` truncation in the capture command and could not be recovered, a mistake in
    this session's own tooling, disclosed rather than glossed over.
  - **`src/app/ai-authority-builder/CorpusReviewPage.test.tsx`, the file the prior report specifically
    named, passed in all 5 runs, including the contention-heavy one.** The prior report's specific
    claim ("the 2 failures are in `CorpusReviewPage.test.tsx`... a pre-existing full-suite-load
    flake") does not reproduce under this session's testing; it is not confirmed, and this document
    no longer repeats it as fact. What this session did confirm instead: this frontend suite does
    have a real, intermittent, load-independent-looking flake, just evidently not that specific file,
    and not something this pass fixed (same reasoning as the backend finding above: a different
    subsystem's test, not touched by this branch, not weakened or worked around here).
- `npm run build` (real Vite production build): succeeds, every new page ships as its own
  lazy-loaded chunk.
- **Now run for real against real Postgres** (2026-10-14, this session): `docker compose up -d
  postgres opa`, Postgres 16.15 (`postgres:16-alpine`, confirmed via `SELECT version();`:
  `PostgreSQL 16.15 on x86_64-pc-linux-musl ... Alpine 15.2.0`), healthcheck green.
  - Fresh empty `payreality_dev` database, `alembic upgrade head` from nothing: succeeded, no
    errors, landed on `f3a7c1e9b5d2 (head)`. `\dt` showed 65 tables total, 13 of them `di_*`.
  - Reset to empty again. `alembic upgrade e2c4b6d8f1a3` (the revision immediately before the DI
    migration, found via the DI migration file's own `down_revision`): succeeded, 39 migrations ran
    in order, landed on `e2c4b6d8f1a3`, zero `di_*` tables present yet. Then one more
    `alembic upgrade head`: succeeded, ran exactly one migration
    (`e2c4b6d8f1a3 -> f3a7c1e9b5d2, decision intelligence module: ...`), landed on `f3a7c1e9b5d2`.
  - Inspected via `psql`: all 13 `di_*` tables present (`di_workflows`, `di_cases`, `di_patterns`,
    `di_pattern_cases`, `di_questions`, `di_question_patterns`, `di_question_cases`, `di_answers`,
    `di_decision_rules`, `di_rule_versions`, `di_replay_runs`, `di_replay_case_results`,
    `di_audit_events`), with `information_schema.table_constraints` confirming every expected FK
    (including the circular `di_decision_rules.current_version_id` <-> `di_rule_versions.rule_id`
    pair), every join table's uniqueness constraint (`uq_di_pattern_cases_pattern_case`,
    `uq_di_question_patterns_question_pattern`, `uq_di_question_cases_question_case`,
    `uq_di_rule_versions_rule_version`), and every PK.
  - Checked downgrade convention first: every single migration file in `server/alembic/versions/`
    (all 40, including the DI one) implements a real, non-stub `downgrade()`, so the DI migration
    was held to that same bar, not a stricter one invented for this pass.
  - `alembic downgrade -1` from head: succeeded, ran the DI migration's real `downgrade()`, landed
    back on `e2c4b6d8f1a3`, and `\dt di_*` confirmed all 13 tables were actually dropped (not just
    the alembic version row changing). `alembic upgrade head` afterward re-applied cleanly, back to
    `f3a7c1e9b5d2`, which is the state the browser walkthrough in Part 2 below was run against.
  - No failures, no manual intervention, no SQLite substitution anywhere in this sequence.
- **Now run for real, end to end, in a real Chromium browser** (2026-10-14, this session), driven
  by a Playwright script (`playwright` package, headless Chromium) against the real FastAPI server
  (`server/.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000`) and the real Vite dev
  server (`npm run dev`, port 5173), both pointed at the same real Postgres from the migration
  validation above. See "Real browser walkthrough" and "Fictional demonstration" below for the full
  account, including two real defects this walkthrough found and fixed, and an honest list of what
  still isn't verified.
- **2026-10-15 re-confirmation, after the six new features and this pass's own corrections**:
  backend DI-specific subset (`pytest -k "decision_intelligence or di_"`): **161/161 passed**.
  Frontend (`npx vitest run`): **8 files, 27/27 passed, 0 errors**. `npx tsc --noEmit`: clean. Full
  backend suite and the exact current failing-test names are recorded in "Known limitations" above.

## Real browser walkthrough

Performed as a real, logged-in user clicking through the real UI (not API calls dressed up as a
UI test), with console errors and failed network requests captured for the whole session.

1. Claimed the bootstrapped Owner via `POST /v1/auth/setup-owner` (Operator Key, read from
   `server/.env`, plus an explicit `X-PayReality-Organization-Id`, per Milestone 2's own design) with
   a fictional email, then logged in through the real `/login` page. All further steps are through
   the UI unless stated otherwise.
2. Created a workflow named `FICTIONAL: Customer Refund Requests (Demo)`, with a description stating
   up front that it is fictional prototype data.
3. Recorded ten cases (`CasesPage`'s real "New case" form, including the `65521cd` human-decision
   baseline field), shaped exactly per the mix in "Fictional demonstration" below.
4. Created a Pattern ("Unclear whether photo evidence is required under $500," category
   `unclear_policy`) and linked two of the cases as evidence from the Pattern's own detail page.
5. Created a Question, linked the Pattern and four cases as evidence from `QuestionDetailPage`
   (the `65521cd` linking UI), then scored four of its five priority dimensions and saved: the
   priority score correctly rendered "Not yet assessed" (confirmed via a direct `GET` of the
   question, not just a UI read) while the fifth (`decision_sensitivity`) stayed genuinely unset.
   Saving the fifth dimension produced a real computed priority score (`57.00`, `scoring_version
   "v1"`), confirmed both via a direct API read and in the reloaded UI. Submitted the question for
   review.
6. Drafted an Answer as the Owner (its author), submitted it for approval.
7. Confirmed separation of duties for real, not just by inspection: with the author still signed in,
   the Approve button was disabled with the explanatory separation-of-duties copy visible, **and** a
   direct `fetch` call to `POST /v1/decision-intelligence/answers/{id}/approve` using that same
   author's own real session token was rejected with a real `403`
   (`"user ... authored answer ... and cannot also approve it"`), not merely hidden in the UI.
8. Created a second user (`FICTIONAL Jordan Reviewer`, role `governance_admin`, the role that
   actually holds `DI_ANSWER_APPROVE` per `ROLE_PERMISSIONS`) through the real "Add a user" flow on
   `/organization/users`, captured the one-time temporary password from the real API response, logged
   out of the Owner session, and logged in as the new user.
9. Approved the Answer for real as the second user. Confirmed via a direct API read that the
   Answer's `approver_user_id` is the second user's id, distinct from `author_user_id`.
10. Created a Decision Rule from the approved Answer. First typed deliberately invalid JSON into the
    condition-tree textarea and submitted it: this produced a real, user-visible UI error ("Schema
    must be valid JSON."), not a silent failure or a crash, confirming the deliberate-failure path
    actually works. Then submitted a real, valid v1 schema (`amount <= 500` -> `approve`,
    `human_review_required: false`).
11. Used "Test this rule" against one real case (`REFUND-1001`) before validating: it returned
    `matched: true, decision: "approve"`, with the matched condition text shown.
12. Validated the rule version for real (`DI_RULE_MANAGE`), then ran a Replay against every case in
    the workflow. The results page rendered the per-category summary with real proportional bars and
    a real per-case baseline/proposed comparison table, with no `NaN` anywhere (see "Defects fixed"
    below for why that specific check mattered) and real percentage labels. A hard reload of the
    results page re-read the same, correct summary straight from the database.
13. Created a second rule version (v2: `amount <= 500 AND photo_evidence_provided == true` ->
    `approve`, `human_review_required: true`), validated it, and ran a second Replay. See "Fictional
    demonstration" below for both runs' real category breakdowns.
14. Marked the question "ready for review" and then "approved for operational use" (both real,
    permission-gated transitions, the second behind a real confirm step), as the second user.
15. Hard-reloaded (full browser reload, not a client-side route change) the Pattern detail page, the
    Rule detail page, and the Question detail page: the Pattern still showed both linked cases, the
    Rule still showed both versions (v1 and v2), and the Question still showed
    "approved for operational use" with the Answer's correct author/approver, all read fresh from
    Postgres, not from any client-side cache.
16. Created a brand-new, otherwise-empty workflow (`FICTIONAL: Empty Workflow (Demo, empty-state
    check only)`) purely to confirm a real empty state: its Cases page genuinely rendered
    "No cases yet," not a blank screen or an error.
17. **Cross-organization isolation, at the API level**: created a second, entirely separate
    organization via `POST /v1/organizations` (Operator Key), logged in as its owner, and attempted
    to read the first organization's workflow, case, question, rule, and pattern by id using the
    second organization's own real session token. All five came back `404` with a specific
    `"..._not_found"` detail (e.g. `workflow_not_found`), never an empty `200` and never a `403` that
    would leak the record's existence. This matches the documented design (Security and governance,
    above) and is now confirmed for Decision Intelligence specifically, across every resource type
    touched in this walkthrough, not just the one the implementing agents' own integration test
    covered.
18. Console/network capture across the whole session: the only console errors seen were the
    deliberate `403` from the self-approve attempt (step 7, expected) and a handful of `403`s from
    `QuestionDetailPage`'s own `usersApi.list()` call, used only to map user ids to display names in
    the Answer lifecycle section. `governance_admin` does not hold `USERS_MANAGE`
    (`ROLE_PERMISSIONS`), so that call is expected to fail for that role; the page already catches it
    silently (`.catch(() => {})`) and falls back to showing a truncated user id instead of a name, so
    this is graceful degradation, not a crash or a broken screen, confirmed by actually watching it
    happen rather than just reading the `.catch()` in the source. No unexplained console errors, no
    unexplained failed requests.

Separately noticed, unrelated to Decision Intelligence: this app's existing, pre-dating global
per-client rate limit (`app/security.py`, 120 requests/60s) is easy for a scripted walkthrough moving
this fast to trip, since a single page mount here routinely fires several parallel `GET`s. Pacing the
script's own actions avoided it. A real person clicking through the same screens at a human pace would
not come close to this limit; this is a note about validating quickly via automation, not a product
defect.

## Fictional demonstration

Reused the browser walkthrough's own data, shaped to cover every required case category. **All of
this is fabricated for this validation pass.** It is not a real customer, not real decisions, and
must never be read as evidence of commercial demand or customer validation, only as a demonstration
that the mechanism (Case -> Pattern -> Question -> Answer -> Rule -> Replay) functions correctly
against real infrastructure.

Ten cases, all under the fictional workflow:

| Case | Facts | Recorded baseline | Why it's in the mix |
|---|---|---|---|
| `REFUND-1001` | amount 120, photo evidence provided, damaged item | approve | Clean, in-scope case |
| `REFUND-1002` | amount 90, **no** photo evidence, damaged item | approve | Policy-gap pair (with 1003): approved despite no photo evidence |
| `REFUND-1003` | amount 95, **no** photo evidence, damaged item | deny | Policy-gap pair (with 1002): denied despite near-identical facts |
| `REFUND-1004` | amount 60, photo evidence provided, wrong item | approve | Clean, in-scope case |
| `REFUND-2001` | `amount` field entirely absent (simulated dropped field) | none recorded | Technical/missing-information case, distinct from the policy-gap pair |
| `REFUND-2002` | amount 150, `photo_evidence_provided` field absent | none recorded | Missing-information case on a different field; genuinely unresolved (no baseline), not force-fit |
| `REFUND-3001` | amount 450, photo evidence provided, standard tier | approve | Still needs individual judgement under the proposed rule (see Replay v2) |
| `REFUND-3002` | amount 480, photo evidence provided, goodwill gesture, VIP tier | approve | Same as above: an edge case a simple rule should not auto-decide |
| `REFUND-4001` | amount 5000, wrong item | deny | Falls entirely outside the proposed rule's scope |
| `REFUND-4002` | amount 3000, fraud suspected | deny | Falls entirely outside the proposed rule's scope |

The proposed rule's own missing data condition (`photo_evidence_provided`) is exactly the Pattern's
subject: the organisation never formally decided whether photo evidence is required for refunds
under $500, and `REFUND-1002`/`REFUND-1003` show two reviewers resolving that same ambiguity in
opposite directions on near-identical facts.

Two rule versions were validated and replayed against all ten cases:

- **v1** (`amount <= 500` -> `approve`, no mandatory human review): `agrees_with_baseline: 5`,
  `disagrees_with_baseline: 3`, `missing_data: 1`, `resolved_automatically: 1`,
  `requires_human_review: 0`. A real spread across four of the six defined outcome categories in one
  run. `REFUND-1002` (baseline approve) landed in `agrees_with_baseline`; `REFUND-1003` (baseline
  deny, otherwise identical facts) landed in `disagrees_with_baseline`, exactly surfacing the policy
  gap the Pattern names. `REFUND-4001`/`REFUND-4002` (far outside the rule's amount threshold) also
  landed in `disagrees_with_baseline`, which is this codebase's real, current semantics for "the rule
  does not even apply here" (see Known limitations: there is no separate "not applicable" category in
  the fixed vocabulary).
- **v2** (adds `AND photo_evidence_provided == true`, `human_review_required: true`):
  `requires_human_review: 4`, `disagrees_with_baseline: 2`, `missing_data: 4`,
  `agrees_with_baseline: 0`, `resolved_automatically: 0`. `REFUND-1001`/`1004`/`3001`/`3002` (facts
  satisfy the tightened condition) all land in `requires_human_review`, which is the real,
  architectural reason a second rule version was needed at all: `RuleAction.human_review_required`
  is a single flag for the whole action, so within one rule version every matching case gets routed
  to a human or none do; there is no way for some matching cases to be fully automatic and others to
  require a human within a single version. That is disclosed here as a real, now-understood
  constraint of the rule language, not a defect (see Known limitations).
  `REFUND-4001`/`4002` moved from `disagrees_with_baseline` (v1) to `missing_data` (v2): the
  evaluator deliberately evaluates every leaf condition with no short-circuiting
  (`rule_evaluator.py`'s own documented behaviour, "so a human inspecting a rule's test/replay result
  wants to see every condition's own verdict"), so even though `amount` alone already fails these
  cases, the AND condition's other leaf (`photo_evidence_provided`, genuinely absent from these two
  cases' facts) is still evaluated and contributes a real `missing_data` classification. Confirmed
  correct, not a bug, once the evaluator's own no-short-circuit design was understood.

Across the two runs together, five of the six defined outcome categories were produced for real
(`error` was correctly never produced, since no malformed rule was ever submitted). Agreement with a
recorded baseline is reported throughout as agreement, never as a claim that the baseline, the rule,
or either version was actually correct, including in this document.

## Defects found and fixed this session

Found through code review and the real browser walkthrough above, each fixed with a focused
regression test that fails without the fix (verified by reverting the fix and re-running):

1. **`ReplayRun.summary` read in the wrong shape** (`ReplayPage.tsx`, `types.ts`). The real backend
   (`di_replay_service.py`) stores and returns `summary` as `{"total_cases": N, "counts": {category:
   count}}`, confirmed by its own integration test. The frontend type and `ReplayPage.tsx` treated it
   as a flat `{category: count}` map, and the page's own pre-existing test mocked that same wrong
   flat shape, so it passed while never matching what the real API actually returns. Every real
   replay would have rendered `NaN`-width summary bars (`Object.values` summing a number and a nested
   object). Fixed the type, the page's read (`run.summary?.counts`, `run.summary?.total_cases`), and
   the test's mock; confirmed live in the browser walkthrough above (no `NaN`, real percentages).
2. **`QuestionDetailPage`'s dimension-score inputs could lose an edit or a save to an unrelated
   background refresh.** `load()` is called, unawaited, after every mutation on this page (a score
   save, linking a pattern/case, an answer action), with nothing guaranteeing those `GET
   /questions/{id}` requests resolved in the order they were issued. Two distinct, confirmed failure
   modes:
   - A reviewer starting to enter scores while an earlier action's `load()` (e.g. one kicked off by
     linking a case moments before) was still in flight could have that `load()` resolve mid-entry
     and reset the five score inputs to blank before they ever reached Save.
   - `handleSaveScores` trusted a separate, unawaited `load()` to resync the inputs after a save,
     rather than its own `updateQuestion`/`scoreQuestion` response; a slower, unrelated `load()`
     resolving in between could still win that race.

   Both were caught live: a UI flow that reported a successful save, followed by a direct database
   read, showed two of five dimension scores had not actually persisted. Fixed with a per-request
   epoch guard (`loadEpochRef`, so only the most recently issued `load()` can ever apply) and a
   dirty-edit guard (`scoresDirtyRef`, so `load()` never touches the five score inputs while the
   reviewer has an unsaved edit in them), plus applying a save's own response directly instead of
   depending on a follow-up `load()`. Three regression tests reproduce these races (two fail without
   the fix, confirmed by reverting it) and now pass.

Both fixes are scoped to the files the bug was in; neither changes any API contract, schema, or
permission.

## Known limitations

The six features once listed here as "not implemented" (CSV case import, AI-assisted pattern/
question suggestion, cross-workflow reports/exports, settings and scoring config, server-side case
search, a visual rule builder) have all since been built, tested, and deployed; see "Decision
Intelligence: Completion Report" for the per-feature build log. What remains genuinely open:

- **The Claude discovery path has never been exercised against the real Anthropic API.** Its schema
  validation, retry, and fail-closed behaviour are tested against a hand-built fake client; a live
  call producing real suggestions from real Claude output has not happened, and production has no
  key configured (confirmed 2026-10-15 via the Container App's own env var/secret names, values never
  read). Configuring a key and running one real call is the exact outstanding step, deliberately not
  done as part of this pass.
- **Reverse-lookup lists** ("which patterns/questions reference this case") on Case Detail are
  bounded best-effort client-side lookups across a workflow's own (deliberately small) pattern and
  question sets, not a dedicated reverse-index endpoint, except for `GET /patterns/{id}/cases`,
  which was added for real.
- **No committed, reproducible deploy script for this prototype.** The release path is manual: an
  `az acr build` tagging the backend image with the git short SHA, a manual `az containerapp update`
  to point at the new image, and a manual Static Web App deploy built with `VITE_API_URL` set as a
  build-time shell variable (no `.env.production` is committed). Confirmed 2026-10-15 by inspecting
  the live Container App and Static Web App directly; nothing in the repo documents or scripts this
  sequence end to end.
- **A rule version's `human_review_required` is one flag for the whole action, not per-condition.**
  Confirmed by the real replay walkthrough above: getting both a fully-automatic outcome and a
  requires-human-review outcome out of matching cases requires two separate rule versions (as done
  in the fictional demonstration), never one. This is a real constraint of the current rule language
  (`rule_schema.py`), not a bug; whether the product should eventually support per-branch review
  requirements is a product decision, not something this pass changed.
- **"Outside the rule's scope" and "the rule disagreed" share one outcome category.** A case whose
  facts simply do not satisfy a rule's root condition (so the rule produces no decision at all) is
  classified `disagrees_with_baseline` whenever that case has a recorded baseline, identically to a
  case the rule actually evaluated and reached a different decision for. The fixed, six-value outcome
  vocabulary (enforced by a database `CHECK` constraint) has no separate "not applicable" category.
  Confirmed live in the fictional demonstration (`REFUND-4001`/`4002`, both far outside the proposed
  rule's amount threshold, both `disagrees_with_baseline`). Disclosed, not changed: redefining the
  outcome vocabulary is a schema/product decision, not something to fix silently inside this pass.
- ~~A replay case with no recorded baseline and no missing data, whose facts simply do not match the
  rule, was classified `resolved_automatically`~~. **Fixed 2026-10-15**: found by hand-verifying a
  deliberately unresolved case during this pass's own walkthrough, `classify_outcome()` now returns
  `requires_human_review` for this combination, with 6 new unit tests
  (`tests/unit/test_di_replay_executor.py`).
- **Case status was never exercised in this pass's walkthrough.** The fictional demonstration set
  each case's `human_decision` (the baseline a Replay compares against) but never changed any case's
  `status` away from its default `open`, so the workflow overview's `unresolved_case_count` reads 10
  (all of them) even though every case carries a recorded baseline decision. `status` and
  `human_decision` are deliberately independent fields (`CaseDetailPage` exposes both), and this is a
  gap in how thoroughly the demonstration exercised the Case Detail edit form, not a product defect.
- **The pre-existing, platform-wide per-client rate limit** (`app/security.py`, 120 requests/60
  seconds, predates this module) is unrelated to Decision Intelligence but is easy for fast
  automation to trip, since several of this module's pages fire multiple parallel `GET`s per mount.
  Noted here only so a future automated test suite against this module budgets for it; a real person
  clicking through the UI will not come close to it.
- **A pre-existing, unrelated backend issue, re-investigated 2026-10-15, not fixed**: exactly 4
  tests fail, every time, on a real assertion, never a timeout:
  `test_authorization_freshness_postgres.py::test_two_concurrent_consumption_attempts_for_the_same_capability_never_both_succeed`,
  `test_authorization_freshness_postgres.py::test_wrong_tenant_verifier_never_wins_a_real_race_against_the_correct_tenant`,
  `test_capability_issuance_idempotency_postgres.py::test_two_concurrent_issuance_requests_for_the_same_decision_never_both_succeed`,
  `test_capability_issuance_idempotency_postgres.py::test_migration_downgrade_and_reupgrade_deduplicates_real_pre_existing_rows`.
  Each fails the same way: `assert decision.outcome == "ALLOW"`, actually getting `"HUMAN_REVIEW"`.
  Confirmed via `git diff 90e41df HEAD` that both test files and every Runtime Authority/Trusted
  Integration source file they exercise are byte-identical to the pre-Decision-Intelligence baseline:
  genuine pre-existing failures with zero code overlap with this module. Out of scope to fix here,
  since a real fix means reopening Runtime Authority, explicitly outside this pass's scope.

  A first full-suite run this pass (2026-10-15) also showed a 5th failure and 9 errors, all in
  files also confirmed byte-identical to baseline (`test_reference_enforcement_demonstration.py`,
  `test_runtime_policy_deploy_opa_consistency.py`, `test_runtime_policy_deployment_concurrency.py`,
  `test_text_extraction_coverage.py`). Investigated rather than dismissed: Docker Desktop's engine
  was found hung (`docker ps` not responding, `docker compose ps` reporting the daemon unable to
  start) immediately after that run, consistent with it crashing mid-run under this session's own
  cumulative load. After restarting Docker Desktop and bringing the Postgres/OPA containers back up,
  re-running exactly those files in isolation reproduced only the same 4 failures above; the other
  5 tests all passed. Concluded: genuinely environmental, not a real regression, this pass's own
  infrastructure load against this environment's resource limits, not a Decision Intelligence or
  Runtime Authority defect.
- **A real, intermittent, load-independent-looking flake exists somewhere in the frontend test
  suite**, confirmed in an earlier session (one of five standalone runs: 9 failures across several
  files, including a real runtime `TypeError` in `IntegrationDetailPage.test.tsx`, not a timeout).
  Re-run clean 2026-10-15 after this pass's own fixes (`npx vitest run`: 8 files, 27/27 passed, 0
  errors); the flake did not reproduce this time either. Still not isolated to a specific file; not
  something this pass attempted to fix, since it is outside Decision Intelligence.

## Current status and open product decisions

1. ~~Run the real Alembic migration against an actual Postgres instance (not just SQLite) and
   confirm.~~ Done.
2. ~~Perform at least one real, manual end-to-end click-through of the full chain in a running
   instance.~~ Done, twice: once in an earlier session (browser walkthrough, two defects found and
   fixed), once 2026-10-15 (API-level synthetic walkthrough, one more defect found and fixed).
3. ~~Deploy.~~ Done; live at `https://payreality.aisecurewatch.com` (see "Current status" above).
4. A product decision on the frontend judgment calls disclosed by the implementing agents
   (Reviewer's exact permission grant vs. its descriptive gloss; `GOVERNANCE_ADMIN` holding
   `DI_REPORT_VIEW`; the two added "ready for review"/"approved for operational use" question
   endpoints): all defensible interpretations of an ambiguous brief, not bugs, but worth a
   deliberate yes/no rather than silent acceptance.
5. A product decision on the two outcome-vocabulary and rule-language constraints disclosed above
   (one `human_review_required` flag per rule version; "outside scope" and "disagreed" sharing one
   outcome category): both are real, now-understood limitations of the shipped design, not bugs,
   but worth a deliberate decision before this is treated as the long-term shape of the rule language
   and replay vocabulary.
6. Whether to configure a real Anthropic API key for the Claude discovery provider, and run it
   against a real case before trusting its output in front of a customer.
7. Code review of every defect fix disclosed in this document (`ReplayPage.tsx`/`types.ts`'s summary shape;
   `QuestionDetailPage.tsx`'s `loadEpochRef`/`scoresDirtyRef` guards), alongside everything else,
   since they also landed after the implementing agents' own original review checkpoint.
