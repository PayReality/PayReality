# Decision Intelligence Platform

## What this is

A new, deliberately isolated product module alongside the existing Runtime Authority platform
(Principals/Agents/Intents/RuntimePolicy/Decision Engine/Evidence). It implements the product
defined on the public site as "Decision Intelligence for AI Workflows": discovering the smallest,
highest-value set of questions a business needs to answer to resolve recurring uncertainty across
many decisions.

Built on branch `feature/idea-b-decision-intelligence-platform` (based on `origin/main` @ `90e41df`),
in an isolated git worktree, never merged, never pushed, never deployed. The existing Runtime
Authority tables, routers, and frontend pages were not modified except for one backend router
addition (`GET /v1/decision-intelligence/patterns/{id}/cases`, added during frontend integration —
see Known limitations) and two stale frontend fixtures that would otherwise have silently broken
(`Layout.test.ts`'s known-nav-set assertion, `demo/fixtures/users.ts`'s demo permission list).

This document is the honest status record. It does not claim anything that was not actually run and
observed to pass.

## The product chain

`Workflow` → `Case` (a real decision situation) → `Pattern` (recurring uncertainty found across
cases) → `Question` (the core differentiator: which question, answered, resolves the most
uncertainty) → `Answer` (authoritative, approved by someone other than whoever submitted it) →
`DecisionRule` / `RuleVersion` (a versioned, inspectable condition tree derived from one approved
answer) → `Replay` (running a rule version against real persisted cases and comparing to the
historical/baseline decision — agreement with that baseline is reported as agreement, never as
proof of correctness).

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
  is prefixed `DI_`. This was a deliberate choice: building parallel auth/tenancy for an isolated
  module would have been pure risk with no product benefit.
- **Frontend**: a new feature directory `src/app/decision-intelligence/`, one top-level nav entry
  ("Decision Intelligence", gated on `di_case.view`), pages for every stage of the chain above, all
  calling the real backend through `decisionIntelligenceApi` (`src/app/decision-intelligence/api.ts`)
  — no mock/hardcoded data in the shipped pages.
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
| `DIAuditEvent` | Append-only log of every mutating action on the above. No update/delete path is exposed. | — |

Every top-level entity carries `organization_id`; every query is scoped by it. Join tables
(`DIPatternCase`, `DIQuestionPattern`, `DIQuestionCase`) carry uniqueness constraints on their pair.

## Scoring methodology

`server/app/domain/decision_intelligence/scoring.py`, versioned as `scoring_version = "v1"`.
Inputs: `reach`, `impact`, `risk`, `answerability`, `decision_sensitivity` — each an independently
estimated/measured value, never auto-derived from the others. **Any missing input makes the whole
score `None`, not a default/average** — a missing dimension must stay visibly missing, never
silently read as low-priority or zero. The frontend renders a `None` score as "not yet assessed,"
not as blank or zero (`ScoreDisplay.tsx`). The exact weights and formula are documented in the
module's own docstring, which is the source of truth; this file does not duplicate it to avoid the
two drifting apart.

## Decision logic and replay

The rule schema (`rule_schema.py`) is a typed Pydantic tree: `Condition` (field/operator/value),
`CompositeCondition` (AND/OR of conditions), `RuleAction` (decision + human-review flag),
`RuleSchema` (root condition, action, exceptions, missing-data behavior). The evaluator
(`rule_evaluator.py`) is a pure function with no DB/network access — it only interprets this typed
tree against a facts dict, it never executes arbitrary code. The same function backs both the
"test this rule" endpoint (no persistence) and the real replay executor, so a rule is tested with
the exact logic that later runs for real. A rule version cannot be marked `validated` unless its
source Answer is `approved` (`validation.py`).

Replay executes synchronously against an explicitly selected set of persisted cases (documented as
a scale-appropriate choice, not a hidden limitation) and never touches a live decision path — it is
a reporting/evaluation operation only, with its own `DIReplayRun`/`DIReplayCaseResult` tables.
"Agrees with baseline" and "baseline was correct" are kept as distinct claims throughout the code,
comments, and frontend copy.

## Security and governance

- Every route resolves the acting user/organization through the same dependency existing
  human-session routes use, and checks a `DI_`-prefixed `Permission` server-side. A standalone
  check confirmed all 45 routes carry a permission dependency (zero ungated routes).
- Tenant isolation: every query scoped by `organization_id`; covered by an integration test asserting
  cross-organization access fails rather than silently returning empty results.
- Separation of duties: `DIAnswer.approver_user_id` can never equal `author_user_id` when
  transitioning to `approved` — enforced in the service layer, not just documented, and surfaced in
  the frontend as a disabled/explained control, not only a backend 400.
- `DIAuditEvent` rows are written for every mutating action on Questions, Answers, Decision Rules,
  and Replay runs. No endpoint exposes updating or deleting an audit event.

## Testing performed (independently re-run and confirmed by the orchestrating session, not only
claimed by the implementing agents)

- Backend: `server/.venv/Scripts/python.exe -m pytest` — new Decision Intelligence unit + integration
  tests: **61/61 passed** (38 unit: scoring, rule evaluator, validation; 23 integration: lifecycle,
  RBAC, tenant isolation, audit events). Full repo suite after the change: **1101 passed, 23 skipped,
  0 failed** (baseline before any change was 1040 passed, 23 skipped — i.e. exactly baseline + 61 new
  tests, zero regressions).
- Frontend: `npx vitest run src/app/decision-intelligence` — **10/10 passed**. Full repo suite
  (`npm test`): **153 passed, 2 failed** on one run; the 2 failures are in
  `src/app/ai-authority-builder/CorpusReviewPage.test.tsx`, a file this work never touched
  (confirmed via `git diff origin/main --stat` showing zero changes to that directory) and which
  passes 2/2 in isolation — a pre-existing full-suite-load flake, not a regression.
- `npm run build` (real Vite production build): succeeds, every new page ships as its own
  lazy-loaded chunk.
- **Not run**: a real `alembic upgrade head` against Postgres (Docker was unavailable in the
  implementing agent's sandbox). Mitigated by running only the new migration, in isolation, against
  a SQLite database stamped at the prior head revision (`upgrade` → `downgrade` → `upgrade` all
  verified, all 13 new tables and FKs confirmed present via `sqlalchemy.inspect`), and by a
  `Base.metadata.create_all()` run including the new models. This is a real gap in verification
  evidence, not a claim that the migration is untested — it just wasn't run against the real target
  database engine. **Before this branch is merged, run the actual migration against a real Postgres
  instance and confirm it end to end.**
- **Not run**: a browser-based end-to-end journey (sign in → create workflow → case → pattern →
  question → answer → rule → replay → report) — no browser automation was available to either
  implementing agent. The component/integration tests above cover the same logic at a lower level,
  but a real end-to-end click-through has not been performed.

## Known limitations / explicitly out of scope for this pass

- **CSV case import**: not implemented. No import endpoint exists; do not expose an import control
  in any future UI work without building it for real.
- **AI-assisted pattern/question suggestion**: not implemented. The product works entirely as a
  manual analysis workflow today, which is itself a hard requirement (the platform must remain
  useful with no AI service configured) — this just means that capability hasn't been *added* yet.
- **Reports/exports beyond the per-workflow overview**: only `GET /workflows/{id}/overview` exists.
  No cross-workflow aggregate report, no PDF/CSV export of Decision Intelligence data.
- **Settings and Help pages**: not built. No Decision-Intelligence-specific settings exist yet
  (scoring weights are presently fixed in code, not admin-configurable).
- **Cases list search**: client-side only, page-scoped. No server-side full-text search over case
  facts.
- **No visual rule builder**: rule authoring is a structured JSON textarea (consistent with how this
  app already handles `Case.facts`); `RuleDetailPage` renders the resulting tree, test results, and
  version history as real structured UI, not raw JSON.
- **Reverse-lookup lists** ("which patterns/questions reference this case") on Case Detail are
  bounded best-effort client-side lookups across a workflow's own (deliberately small) pattern/
  question sets, not a dedicated reverse-index endpoint, except for `GET /patterns/{id}/cases`,
  which was added for real.
- **Not deployed anywhere.** No production hosting, DNS, or database changes were made. This is a
  feature branch in a worktree, reviewed and tested locally only.

## Before this is mergeable

1. Run the real Alembic migration against an actual Postgres instance (not just SQLite) and confirm.
2. Perform at least one real, manual end-to-end click-through of the full chain in a running
   instance.
3. A product decision on the frontend judgment calls disclosed by the implementing agents
   (Reviewer's exact permission grant vs. its descriptive gloss; `GOVERNANCE_ADMIN` holding
   `DI_REPORT_VIEW`; the two added "ready for review"/"approved for operational use" question
   endpoints) — all defensible interpretations of an ambiguous brief, not bugs, but worth a
   deliberate yes/no rather than silent acceptance.
4. Code review of the one backend change made during frontend integration
   (`GET /v1/decision-intelligence/patterns/{id}/cases`) alongside everything else, since it landed
   after the backend's own original review checkpoint.
