# Authority Intelligence Program — Phase 3: Explainability & Human Review — Summary

**Date:** 12 August 2026
**Commit:** `5f3992b`
**Scope:** Make Authority Intelligence fully explainable and reviewable. No architecture redesign, no new Azure services, no new AI providers, no new agents/copilots, no change to Runtime Authority or the approval workflow itself.

---

## What changed

The reviewer's pipeline is now literally: Governance Documents → Authority Intelligence → **Extracted Evidence** → **Reasoning** → Detected Authority → Authority Graph Candidate → Human Review → Approval — the two new stages (bolded) are real, queryable domain objects, not narrative.

| Task | Deliverable |
|---|---|
| 1. Explainability Model | `clause_reference`, `extraction_reasoning`, `detected_assumptions`, `ambiguity_flags` — first-class columns on every Principal, Resource, Operation, Relationship, and Policy candidate. Asked of the model via the existing forced tool-use schema; never inferred after the fact. |
| 2. Evidence Mapping | Every finding's confidence, source document, clause, quotation, and reasoning is returned by the existing per-category endpoints (`ExplainabilityFields`, inherited by every response schema) — surfaced directly in the Reviewer Workspace, not a separate lookup. |
| 3. Conflict Workspace | `conflict_type` (authority/threshold/role/policy/delegation/circular_delegation) and a deterministic `reviewer_recommendation`. `circular_delegation` also gets independent, deterministic graph-cycle detection (`detect_circular_delegations`) over the corpus's own delegation edges — not left to the model to notice across a graph it can't fully see in one pass. |
| 4. Missing Information Detection | `detect_missing_information`: a deterministic, code-computed backstop (unknown reporting lines, unresolved relationships, policies with no numeric limit on a money-moving action, delegations with no stated source) — independent of the model's own self-reported Gaps/Questions. |
| 5. Coverage Analysis | `extract_text_with_coverage` (new; the original `extract_text` is untouched) returns deterministic parsing statistics — clauses analysed/ignored, tables extracted, images skipped — aggregated per corpus via `get_coverage`. Never an LLM's self-report. |
| 6. Reviewer Workspace | `CorpusReviewPage.tsx` rebuilt around a sticky decision bar (coverage %, conflict count, Approve action) and tabs (Authority Graph / Conflicts / Missing Information / Coverage / Diff / Approval History) — built to be scanned and decided on, like a pull request, not read as a chat transcript. |
| 7. Diff View | `get_graph_diff`: this corpus's candidate graph vs. the Authority Graph already in force for the same organisation — new/removed authorities, changed thresholds, changed reporting lines, changed responsibilities. A deterministic comparison; the model's job ended at extraction. |
| 8. Approval Audit | `approve_graph` appends one immutable `authority_graph_approvals` row: reviewer, version, an evidence snapshot, an optional reason, and a `graph_hash` reusing `domain/evidence/signing.py`'s canonicalize/hash pattern unchanged. Strictly additive — it does not itself resolve, activate, or promote anything. |
| 9. Runtime Integration | Verified by direct code tracing (see below), not a live test — this environment has no local Postgres. |
| 10. Security Review | See below. |

---

## Task 9: Runtime Integration Verification

`grep`-confirmed: `runtime_policy_service.create_policy` has exactly two callers in the entire codebase:

1. `ai_policy_builder_service.promote_candidate` — hard-gated on `row.status != "pending_review"` raising before any policy is built.
2. `routers/runtime_policies.py`'s direct create-policy endpoint — an unrelated, human-authored-from-scratch path (Policy Studio), not an AI-candidate path at all.

`dismiss_candidate` sets `status = "dismissed"` and never calls `create_policy`; no code path anywhere resets a candidate's status back to `pending_review` once it's `dismissed` or `promoted` — the transition is one-way. **Confirmed: a rejected/dismissed candidate cannot reach Runtime Authority.** This was verified by reading the actual guard clauses and enumerating every call site, not asserted from memory of an earlier phase's report.

This specific invariant was not additionally covered by a new automated test: `promote_candidate`/`dismiss_candidate` are DB-dependent, and this codebase's own established convention (`test_ai_authority_builder.py`'s own docstring) is that DB-dependent functions are verified against a real Postgres instance, not a fake/in-memory one — no local Postgres was reachable in this session (confirmed by a connection-timeout error), so this remains a code-reading confirmation, not a fresh executed test.

---

## Task 10: Security Review

| Check | Result |
|---|---|
| No evidence leakage | New endpoints (`coverage`, `missing-information`, `diff`, `approvals`) all scope strictly by `corpus_id`/organisation, matching the existing category endpoints exactly. |
| No cross-document contamination | `detect_circular_delegations` operates only on one extraction call's own in-memory graph; `get_graph_diff` scopes comparison Authorities by `organization_id`; every new column/table is `corpus_id`-scoped. |
| No hidden AI reasoning | `extraction_reasoning`/`detected_assumptions`/`ambiguity_flags` are returned by every relevant endpoint and rendered directly in the Reviewer Workspace — the opposite of hidden. |
| Only deterministic evidence stored | `reviewer_recommendation`, coverage statistics, missing-information items, circular-delegation detection, and `graph_hash` are all computed in Python — grep-confirmed zero new LLM calls anywhere in these functions. `conflict_type` is the one field still asked of the model, which is correct: it is the model's own classification of its own already-model-reported finding, the same standard `description`/`reasoning` were already held to before this phase. |
| No prompt exposure | Grep-confirmed: no response schema or router references `SYSTEM_PROMPT_TEMPLATE`/`build_system_prompt` anywhere. |
| No sensitive governance leakage | No new logging statement includes document content or extracted PII — the one Phase 3 touches (`add_document`'s existing exception handler) is unchanged and only ever logged `corpus_id`/`document_id`. |

**Pre-existing gap, not introduced by Phase 3, not newly worsened**: the new GET endpoints inherit the exact same missing organisation-scoping/authentication that Phase 2's security review already flagged as the platform's top remaining production gap for every Authority Graph read endpoint. Phase 3 did not fix this — closing it means touching the pre-existing AI Policy Builder read surface too, and remains correctly out of this phase's "no redesign" scope. It is not a new risk; it is the same one, now with more fields exposed through the same unguarded door.

---

## Verification actually performed this session

- **211 pre-existing + 21 new = 232/232 backend tests passing**, run before and after every code change, zero regressions.
- **Migration verified via offline `alembic ... --sql` generation** (both upgrade and downgrade) — syntactically valid, exactly the intended additive DDL. Not run against a live Postgres: no local instance was reachable (`OperationalError: connection timeout expired` to `localhost:5432`), consistent with this codebase's own established DB-testing boundary.
- **Full app import** (`from app.main import app`) succeeds — confirms no circular imports, no missing schema/model wiring across the router/schema/service/model changes.
- **Frontend production build** (`npm run build`) succeeds cleanly, including the rebuilt `CorpusReviewPage`. **Not verified**: this project has no TypeScript compiler installed at all (no `tsconfig.json`, no `typescript` package) — Vite/esbuild transpiles without type-checking, so a type mismatch that doesn't also break at the JS level would not be caught by this build. No browser-based or interactive testing was performed.
- **Circular-delegation detection** spot-checked directly (a 3-hop cycle found correctly, an escalation edge correctly excluded, a normal hierarchy correctly produces zero findings, duplicate cycle detection deduplicated) — beyond the unit tests, via a standalone script.

---

## Remaining gaps (honest, not exhaustive)

1. **Organisation-scoping on read endpoints** — pre-existing, flagged again above, not fixed in this phase.
2. **HTTP-level, end-to-end verification of the new endpoints against a live deployment** was not performed — no staging round-trip was run this session (unlike Phase 2, which did reach live Azure resources); everything above is unit-level and static verification only.
3. **`GraphDiff`'s "removed authorities"/"new thresholds" categories** rely on the pre-existing `Authority`/`Mandate` promotion path having actually run for prior corpora — on an organisation with no prior approved Authorities at all, every diff category will correctly, but perhaps unhelpfully, show everything as "new." This is accurate, not broken, but worth knowing before demoing on a fresh organisation.
4. **No UI screenshots** are included — this environment has no browser/screenshot tool available to me.

## Recommendation

Ship it to staging and exercise it against a real corpus before wider use — the backend is unit-tested and internally consistent, but this phase's own honest gap list (#2 above) means the true end-to-end path (upload → extract with the new fields populated by the live model → review in the new UI → approve → diff) has not been watched happen for real, only assembled from independently-verified parts.

Per the Completion Gate: stopping here. No production deployment, no new AI agents, no additional copilots. Awaiting explicit approval before the next phase.
